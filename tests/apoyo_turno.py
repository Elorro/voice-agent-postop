"""Dobles de los servicios externos del turno, y una configuración de prueba.

Los tres servicios del turno —STT, LLM y TTS— llegan al orquestador inyectados
(`app.contratos.Servicios`), así que aquí se sustituyen por dobles deterministas
y toda la batería corre sin red, sin claves y sin modelos. Es lo que permite
ejercitar las rutas que en producción no se pueden provocar a voluntad: el
extractor devolviendo basura, el redactor pasándose del timeout, el paciente que
no contesta nunca.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.config import Config, cargar_config
from app.contratos import ERROR, OK, TIMEOUT, SalidaLLM, SalidaSTT, SalidaTTS, Servicios
from app.llm.redactor import PROMPT_SISTEMA as PROMPT_REDACTOR
from app.rag.respuesta import PROMPT_SISTEMA as PROMPT_RAG
from app.rag.tipos import Fragmento

__all__ = [
    "config_de_prueba",
    "LLMFalso",
    "fragmento",
    "rag_fijo",
    "servicios",
    "stt_fijo",
    "tts_falso",
]


def config_de_prueba(tmp_path: Path, **cambios: str) -> Config:
    """Configuración real, con las rutas apuntando a un directorio temporal.

    Se usa `cargar_config` y no un `Config(...)` a mano a propósito: así el test
    ejercita la misma lectura de entorno que el proceso de producción, y un
    campo nuevo sin default lo rompe aquí y no en el contenedor.
    """
    import os

    entorno = {
        "LOGS_DIR": str(tmp_path / "logs"),
        "LLAMADAS_DIR": str(tmp_path / "llamadas"),
        "TARIFAS_RUTA": str(tmp_path / "tarifas.json"),
        **cambios,
    }
    previo = {clave: os.environ.get(clave) for clave in entorno}
    os.environ.update(entorno)
    try:
        return cargar_config()
    finally:
        for clave, valor in previo.items():
            if valor is None:
                os.environ.pop(clave, None)
            else:
                os.environ[clave] = valor


def escribir_tarifas(cfg: Config, modelos: dict[str, Any]) -> None:
    cfg.ruta_tarifas.parent.mkdir(parents=True, exist_ok=True)
    cfg.ruta_tarifas.write_text(
        json.dumps({"modelos": modelos}, ensure_ascii=False), encoding="utf-8"
    )


@dataclass
class LLMFalso:
    """Doble del cliente de inferencia, con guion programable.

    `respuestas_extractor` se consume en orden; agotada la lista, se repite la
    última. `redactor` decide qué hace el LLM #2, que es un camino distinto y
    con reglas distintas.
    """

    respuestas_extractor: list[str] = field(default_factory=list)
    # Proveedor caído / lento PARA EL EXTRACTOR. Es la ruta que en producción
    # solo aparece con el proveedor real fuera de servicio, y la que distingue
    # «el paciente no supo contestar» de «el agente no pudo preguntarle al
    # modelo» — la distinción que sostiene la enmienda a HD7.
    extractor_error: bool = False
    extractor_timeout: bool = False
    respuesta_redactor: str | None = None
    redactor_timeout: bool = False
    respuesta_rag: str | None = None
    rag_timeout: bool = False
    modelo: str = "modelo-de-prueba"
    tokens_in: int = 40
    tokens_out: int = 12
    llamadas: list[dict[str, Any]] = field(default_factory=list)

    def completar(
        self,
        mensajes: list[dict[str, str]],
        *,
        timeout_ms: int,
        max_tokens: int | None = None,
        temperatura: float = 0.0,
        formato_json: bool = False,
    ) -> SalidaLLM:
        sistema = mensajes[0].get("content") if mensajes else ""
        es_redactor = sistema == PROMPT_REDACTOR
        es_rag = sistema == PROMPT_RAG
        self.llamadas.append(
            {
                "rol": "rag" if es_rag else ("redactor" if es_redactor else "extractor"),
                "timeout_ms": timeout_ms,
                "mensajes": mensajes,
            }
        )
        if es_rag:
            if self.rag_timeout:
                return SalidaLLM("", float(timeout_ms), TIMEOUT, self.modelo)
            texto = self.respuesta_rag
            if texto is None:
                texto = "Según las guías, mantenga la herida limpia y seca."
            return SalidaLLM(texto, 9.0, OK, self.modelo, self.tokens_in, self.tokens_out)

        if es_redactor:
            if self.redactor_timeout:
                return SalidaLLM("", float(timeout_ms), TIMEOUT, self.modelo)
            texto = self.respuesta_redactor
            if texto is None:
                # Sin guion, el redactor devuelve el mismo texto: el turno debe
                # seguir marcando «llm» como fuente.
                texto = mensajes[-1]["content"]
            return SalidaLLM(texto, 5.0, OK, self.modelo, self.tokens_in, self.tokens_out)

        if self.extractor_timeout:
            return SalidaLLM("", float(timeout_ms), TIMEOUT, self.modelo)
        if self.extractor_error:
            return SalidaLLM("", 12.0, ERROR, self.modelo, detalle="429 de prueba")

        if self.respuestas_extractor:
            texto = (
                self.respuestas_extractor.pop(0)
                if len(self.respuestas_extractor) > 1
                else self.respuestas_extractor[0]
            )
        else:
            texto = "{}"
        return SalidaLLM(texto, 7.0, OK, self.modelo, self.tokens_in, self.tokens_out)


def stt_fijo(
    guion: list[str], *, resultado: str = OK
) -> Callable[[bytes, str], SalidaSTT]:
    """Transcripciones en orden; agotado el guion, devuelve cadena vacía.

    `resultado` permite simular el proveedor de transcripción caído o lento.
    Con `error`/`timeout` el texto sale vacío **y** el resultado lo declara, que
    es justo lo que distingue «el agente no oyó» de «el paciente calló»: el
    silencio del paciente es texto vacío con `resultado` en `ok`.
    """
    pendientes = list(guion)

    def transcribir(audio: bytes, nombre: str = "turno.webm", segundos: float | None = None):
        if resultado != OK:
            return SalidaSTT("", 3.0, resultado, segundos, detalle="proveedor de prueba")
        texto = pendientes.pop(0) if pendientes else ""
        return SalidaSTT(texto, 3.0, OK, segundos)

    return transcribir


def tts_falso(registro: list[str] | None = None) -> Callable[[str], SalidaTTS]:
    """Sintetizador de mentira: cuenta caracteres y devuelve bytes plausibles."""

    def sintetizar(texto: str) -> SalidaTTS:
        if registro is not None:
            registro.append(texto)
        return SalidaTTS(b"RIFF" + texto.encode("utf-8"), 2.0, len(texto) / 15.0, 22050)

    return sintetizar


def fragmento(
    texto: str = "Mantenga la herida limpia y seca durante las primeras 48 horas.",
    score: float = 0.72,
    ruta: str = "Appendicitis/PLAN DE CUIDADO EN CASA.pdf",
    pagina: int = 3,
) -> Fragmento:
    """Un fragmento recuperado, con metadatos plausibles."""
    return Fragmento(
        texto=texto,
        score=score,
        ruta_relativa=ruta,
        pagina=pagina,
        escenario="Appendicitis",
        idioma="es",
        origen="corpus",
        documento_id="corpus-0123456789abcdef",
        hash_documento="0123456789abcdef" * 4,
    )


def rag_fijo(fragmentos: list[Fragmento]) -> Callable[[str, int], list[Fragmento]]:
    """Recuperación de mentira: devuelve siempre los mismos fragmentos.

    Es la única forma de provocar a voluntad el caso que más importa —el corpus
    no cubre la pregunta— sin depender de qué haya en el índice real.
    """

    def consultar(consulta: str, k: int) -> list[Fragmento]:
        return list(fragmentos[:k])

    return consultar


def servicios(
    llm: LLMFalso,
    transcripciones: list[str],
    dichos: list[str] | None = None,
    consultar_rag: Callable[[str, int], list[Fragmento]] | None = None,
    *,
    stt_resultado: str = OK,
) -> Servicios:
    return Servicios(
        transcribir=stt_fijo(transcripciones, resultado=stt_resultado),
        completar=llm.completar,
        sintetizar=tts_falso(dichos),
        consultar_rag=consultar_rag,
    )
