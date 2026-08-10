"""Construcción de las dependencias reales del turno, una vez por proceso.

Aquí es donde `Servicios` deja de ser abstracto: se ata al STT del proveedor, al
cliente OpenAI-compatible y al sintetizador local. La orquestación no importa
ninguno de los tres, y por eso los tests pueden ejercitar las rutas de
degradación —extractor que devuelve basura, redactor que se pasa del timeout—
sin red y sin modelos.

Los tres se construyen al arrancar (`app/main.py` lo llama en el ciclo de vida),
no en la primera petición: 63 MB de ONNX y dos handshakes TLS en medio de la
primera llamada del paciente se ven como un agente que tarda en saludar.
"""

from __future__ import annotations

import logging
import threading

from app.config import Config
from app.contratos import ERROR, SalidaTTS, Servicios

_log = logging.getLogger(__name__)

__all__ = ["obtener_servicios", "precargar_servicios"]

_servicios: Servicios | None = None
_candado = threading.Lock()


def _sintetizador_no_disponible(motivo: str):
    def sintetizar(texto: str) -> SalidaTTS:
        _log.error("TTS no disponible: %s", motivo)
        return SalidaTTS(b"", 0.0, 0.0, 0, ERROR, motivo)

    return sintetizar


def _construir(cfg: Config) -> Servicios:
    from app.audio.stt import ClienteSTT
    from app.llm.cliente import ClienteLLM

    stt = ClienteSTT(cfg)
    llm = ClienteLLM(cfg)

    try:
        from app.audio import tts

        sintetizador = tts.obtener_sintetizador(cfg)
        sintetizar = sintetizador.sintetizar
        metadatos_voz = {
            "modelo": cfg.modelo_voz,
            "muestreo_hz": sintetizador.muestreo_hz,
            "voz_espeak": sintetizador.fonemizador.voz,
        }
    except Exception as exc:  # noqa: BLE001 - /salud lo reporta; el proceso sigue
        _log.error("no se pudo preparar la voz: %s", exc)
        sintetizar = _sintetizador_no_disponible(str(exc)[:200])
        metadatos_voz = {"error": str(exc)[:200]}

    return Servicios(
        transcribir=stt.transcribir,
        completar=llm.completar,
        sintetizar=sintetizar,
        metadatos={"stt": stt.modelo, "llm": llm.modelo, "voz": metadatos_voz},
    )


def obtener_servicios(cfg: Config) -> Servicios:
    global _servicios
    with _candado:
        if _servicios is None:
            _servicios = _construir(cfg)
    return _servicios


def precargar_servicios(cfg: Config) -> None:
    """Se llama al arrancar. Los fallos quedan en el log y en `/salud`."""
    obtener_servicios(cfg)
