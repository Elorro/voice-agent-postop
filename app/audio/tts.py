"""Voz local: texto -> fonemas (espeak-ng) -> Piper (ONNX) -> WAV.

Todo ocurre dentro del contenedor. No hay proveedor de voz, no hay red en el
camino, y por tanto no hay una cuota ajena decidiendo si el agente puede hablar.

Por qué hacen falta DOS piezas y no basta el `.onnx`
---------------------------------------------------
El modelo de Piper no recibe texto: recibe una secuencia de identificadores de
fonema. Su `.json` declara `phoneme_type: espeak` y `espeak.voice: es-419`, es
decir que fue entrenado con los fonemas que produce **espeak-ng** para español
latinoamericano. Sin ese fonemizador no hay forma de construir la entrada, y con
uno distinto los identificadores no significarían lo mismo que en el
entrenamiento. Por eso la imagen instala `libespeak-ng1` + `espeak-ng-data`.

Se usa la biblioteca por `ctypes`, no el ejecutable: evita un `fork`+`exec` por
turno en el camino crítico y deja el estado (voz cargada) inicializado una sola
vez por proceso.

Segmentación en cláusulas, y por qué la hacemos nosotros
-------------------------------------------------------
`espeak_TextToPhonemes` avanza el puntero **más allá** del final de la cláusula
que acaba de fonemizar (lee por delante), así que el texto consumido no permite
recuperar con exactitud el signo de puntuación que la cerró — y ese signo es
justo lo que le da a Piper la prosodia de pregunta o de pausa. Partimos nosotros
el texto por puntuación, fonemizamos fragmento a fragmento y reponemos el signo:
así el signo que entra al modelo es el que estaba en el texto, no el que se
adivinó.
"""

from __future__ import annotations

import ctypes
import io
import json
import logging
import re
import threading
import time
import wave
from pathlib import Path
from typing import Any

from app.config import Config
from app.contratos import ERROR, OK, SalidaTTS

_log = logging.getLogger(__name__)

__all__ = ["Fonemizador", "Sintetizador", "obtener_sintetizador"]

# Modo de salida de espeak-ng: fonemización sin reproducir audio.
_AUDIO_OUTPUT_SYNCHRONOUS = 0x02
# `espeak_TextToPhonemes`: texto UTF-8 (bit 0) y fonemas en IPA (bit 1).
_ESPEAK_CHARS_UTF8 = 1
_ESPEAK_FONEMAS_IPA = 0x02

_TERMINADORES = ",.;:!?"
_CLAUSULAS = re.compile(r"[^,.;:!?…]+[,.;:!?…]?")
_EQUIVALENCIAS = {"…": ".", "¿": "?", "¡": "!"}

# Símbolos de control del vocabulario de Piper.
_INICIO, _FIN, _RELLENO, _ESPACIO = "^", "$", "_", " "


class Fonemizador:
    """espeak-ng por `ctypes`. Una instancia por proceso: la biblioteca tiene
    estado global (la voz seleccionada), así que compartirla entre hilos sin
    candado sería una condición de carrera silenciosa: el turno de otro hilo
    saldría fonemizado con otra voz."""

    def __init__(self, biblioteca: str, voz: str) -> None:
        self._lib = ctypes.CDLL(biblioteca)
        self._lib.espeak_Initialize.restype = ctypes.c_int
        self._lib.espeak_Initialize.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
        ]
        self._lib.espeak_SetVoiceByName.restype = ctypes.c_int
        self._lib.espeak_SetVoiceByName.argtypes = [ctypes.c_char_p]
        self._lib.espeak_TextToPhonemes.restype = ctypes.c_char_p
        self._lib.espeak_TextToPhonemes.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_int,
            ctypes.c_int,
        ]

        tasa = self._lib.espeak_Initialize(_AUDIO_OUTPUT_SYNCHRONOUS, 0, None, 0)
        if tasa <= 0:
            raise RuntimeError(f"espeak-ng no inicializa (código {tasa})")
        if self._lib.espeak_SetVoiceByName(voz.encode("utf-8")) != 0:
            raise RuntimeError(f"espeak-ng no tiene la voz {voz!r}")
        self.voz = voz
        self._candado = threading.Lock()

    def _fonemizar_fragmento(self, texto: str) -> str:
        crudo = texto.encode("utf-8")
        if not crudo.strip():
            return ""
        buffer = ctypes.create_string_buffer(crudo)
        puntero = ctypes.c_void_p(ctypes.addressof(buffer))
        partes: list[str] = []
        while puntero.value:
            devuelto = self._lib.espeak_TextToPhonemes(
                ctypes.byref(puntero), _ESPEAK_CHARS_UTF8, _ESPEAK_FONEMAS_IPA
            )
            if devuelto:
                partes.append(devuelto.decode("utf-8"))
        return " ".join(p for p in partes if p)

    def clausulas(self, texto: str) -> list[tuple[str, str]]:
        """`[(fonemas_ipa, signo_de_cierre), …]` en el orden del texto."""
        salida: list[tuple[str, str]] = []
        with self._candado:
            for encontrado in _CLAUSULAS.finditer(texto):
                fragmento = encontrado.group(0)
                signo = ""
                if fragmento and fragmento[-1] in _TERMINADORES + "…":
                    signo = _EQUIVALENCIAS.get(fragmento[-1], fragmento[-1])
                fonemas = self._fonemizar_fragmento(fragmento)
                if fonemas:
                    salida.append((fonemas, signo))
        return salida


class Sintetizador:
    """Piper sobre onnxruntime, cargado una vez por proceso."""

    def __init__(self, cfg: Config) -> None:
        import onnxruntime

        self.ruta = cfg.ruta_modelo_voz
        self.meta: dict[str, Any] = json.loads(
            Path(cfg.ruta_config_voz).read_text(encoding="utf-8")
        )
        self.muestreo_hz = int(self.meta["audio"]["sample_rate"])
        self._mapa: dict[str, list[int]] = self.meta["phoneme_id_map"]
        inferencia = self.meta.get("inference", {})
        self._escalas = (
            float(inferencia.get("noise_scale", 0.667)),
            float(inferencia.get("length_scale", 1.0)),
            float(inferencia.get("noise_w", 0.8)),
        )
        self.fonemizador = Fonemizador(
            cfg.voz_biblioteca_espeak, self.meta["espeak"]["voice"]
        )

        opciones = onnxruntime.SessionOptions()
        opciones.log_severity_level = 3
        self._sesion = onnxruntime.InferenceSession(
            str(self.ruta), sess_options=opciones, providers=["CPUExecutionProvider"]
        )
        self._candado = threading.Lock()

    # -- fonemas -> identificadores ---------------------------------------- #
    def identificadores(self, texto: str) -> tuple[list[int], list[str]]:
        """Secuencia de ids para el modelo, y los símbolos que no estaban en el
        vocabulario (se descartan y se registran: un fonema fuera del mapa es
        un hueco en la voz, no un error que deba tumbar el turno)."""
        mapa = self._mapa
        ids: list[int] = list(mapa[_INICIO])
        desconocidos: list[str] = []

        def agregar(simbolo: str) -> None:
            if simbolo in mapa:
                ids.extend(mapa[simbolo])
                ids.extend(mapa[_RELLENO])
            else:
                desconocidos.append(simbolo)

        for fonemas, signo in self.fonemizador.clausulas(texto):
            for simbolo in fonemas:
                agregar(simbolo)
            if signo:
                agregar(signo)
            agregar(_ESPACIO)

        ids.extend(mapa[_FIN])
        return ids, desconocidos

    def sintetizar(self, texto: str) -> SalidaTTS:
        """Texto -> WAV PCM 16 bits mono. Nunca lanza: el fallo va en `resultado`."""
        import numpy as np

        inicio = time.perf_counter()
        try:
            ids, desconocidos = self.identificadores(texto)
            if len(ids) <= 2:
                raise ValueError("el texto no produjo ningún fonema")
            with self._candado:
                salida = self._sesion.run(
                    None,
                    {
                        "input": np.array([ids], dtype=np.int64),
                        "input_lengths": np.array([len(ids)], dtype=np.int64),
                        "scales": np.array(self._escalas, dtype=np.float32),
                    },
                )[0]
            audio = np.clip(np.squeeze(salida), -1.0, 1.0)
            pcm = (audio * 32767.0).astype(np.int16)
            wav = _envolver_wav(pcm.tobytes(), self.muestreo_hz)
            ms = (time.perf_counter() - inicio) * 1000
            if desconocidos:
                _log.info("TTS: símbolos fuera del vocabulario: %s", set(desconocidos))
            return SalidaTTS(
                wav=wav,
                ms=ms,
                segundos=len(pcm) / self.muestreo_hz,
                muestreo_hz=self.muestreo_hz,
                resultado=OK,
            )
        except Exception as exc:  # noqa: BLE001 - se reporta, no propaga
            ms = (time.perf_counter() - inicio) * 1000
            _log.error("TTS: fallo sintetizando: %s", exc)
            return SalidaTTS(b"", ms, 0.0, self.muestreo_hz, ERROR, str(exc)[:200])


def _envolver_wav(pcm: bytes, muestreo_hz: int) -> bytes:
    memoria = io.BytesIO()
    with wave.open(memoria, "wb") as escritor:
        escritor.setnchannels(1)
        escritor.setsampwidth(2)
        escritor.setframerate(muestreo_hz)
        escritor.writeframes(pcm)
    return memoria.getvalue()


_instancia: Sintetizador | None = None
_candado_instancia = threading.Lock()


def obtener_sintetizador(cfg: Config) -> Sintetizador:
    """Sintetizador único del proceso. Se construye al arrancar, no en el
    primer turno: cargar 63 MB de ONNX en medio de la primera llamada del
    paciente se vería como un agente que tarda cuatro segundos en saludar."""
    global _instancia
    with _candado_instancia:
        if _instancia is None:
            _instancia = Sintetizador(cfg)
    return _instancia
