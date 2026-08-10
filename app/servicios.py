"""Construcción de las dependencias reales del turno, una vez por proceso.

Aquí es donde `Servicios` deja de ser abstracto: se ata al STT del proveedor, al
cliente OpenAI-compatible y al sintetizador local. La orquestación no importa
ninguno de los tres, y por eso los tests pueden ejercitar las rutas de
degradación —extractor que devuelve basura, redactor que se pasa del timeout—
sin red y sin modelos.

Los tres se construyen al arrancar (`app/main.py` lo llama en el ciclo de vida),
no en la primera petición: 63 MB de ONNX y dos handshakes TLS en medio de la
primera llamada del paciente se ven como un agente que tarda en saludar.

Desde el sub-paso 3.2 se construye aquí también el **almacén vectorial**, y por
la misma razón elevada al cuadrado: abrir la colección carga el embedder y lee el
índice sembrado. Es además el único punto donde se abre, y eso importa —el turno
lo consulta y la consola escribe en él— porque dos `PersistentClient` sobre el
mismo directorio SQLite en el mismo proceso son dos vías de escritura sin
coordinación entre ellas.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.config import Config
from app.contratos import ERROR, SalidaTTS, Servicios

_log = logging.getLogger(__name__)

__all__ = [
    "obtener_servicios",
    "precargar_servicios",
    "obtener_almacen",
    "obtener_registro_documentos",
    "estado_del_almacen",
]

_servicios: Servicios | None = None
_candado = threading.Lock()

_almacen: Any = None
_almacen_error: str = ""
_almacen_abierto = False
_candado_almacen = threading.Lock()

_registro_documentos: Any = None
_candado_registro = threading.Lock()


def obtener_almacen(cfg: Config) -> Any:
    """El almacén vectorial del proceso, o `None` si no se pudo abrir.

    Un índice que no abre NO tumba el servicio: el agente pierde la capacidad de
    responder preguntas y lo declara, la clasificación clínica sigue intacta
    —no depende del corpus— y `/salud` dice qué pasó. Caerse aquí convertiría un
    fallo de una función accesoria en una llamada de paciente perdida.
    """
    global _almacen, _almacen_error, _almacen_abierto
    with _candado_almacen:
        if _almacen_abierto:
            return _almacen
        _almacen_abierto = True
        if not cfg.rag_activo:
            _almacen_error = "RAG_ACTIVO=0: recuperación desactivada por configuración"
            _log.warning("%s", _almacen_error)
            return None
        try:
            from app.rag import indice

            _almacen = indice.abrir(cfg.almacen_indice, cfg.coleccion_rag)
            _log.info(
                "índice abierto en %s: %d fragmentos en «%s»",
                cfg.almacen_indice,
                _almacen.contar(),
                cfg.coleccion_rag,
            )
        except Exception as exc:  # noqa: BLE001 - /salud lo reporta; el proceso sigue
            _almacen_error = f"{type(exc).__name__}: {exc}"[:300]
            _log.error("no se pudo abrir el índice: %s", _almacen_error)
            _almacen = None
    return _almacen


def estado_del_almacen() -> tuple[bool, str]:
    """`(abierto, motivo)`. Lo consulta `/salud` sin volver a intentar la carga."""
    return (_almacen is not None), _almacen_error


def obtener_registro_documentos(cfg: Config) -> Any:
    """Inventario de documentos subidos, uno por proceso."""
    global _registro_documentos
    with _candado_registro:
        if _registro_documentos is None:
            from app.rag.documentos import Registro

            cfg.dir_subidos.mkdir(parents=True, exist_ok=True)
            _registro_documentos = Registro(cfg.dir_subidos / "inventario.json")
            huerfanos = _registro_documentos.reconciliar()
            if huerfanos:
                _log.warning(
                    "%d documento(s) quedaron a medio procesar en un arranque previo",
                    huerfanos,
                )
    return _registro_documentos


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

    almacen = obtener_almacen(cfg)
    if almacen is None:
        consultar_rag = None
    else:
        # Los parámetros de la fusión híbrida se atan aquí y no dentro del
        # almacén: `Almacen` es la pieza que habla con chromadb y no tiene por
        # qué conocer la configuración del proceso. El turno pide `(consulta, k)`
        # y nada más.
        def consultar_rag(consulta: str, k: int):
            return almacen.consultar(consulta, k, pool=cfg.rag_pool, alfa=cfg.rag_alfa)

    return Servicios(
        transcribir=stt.transcribir,
        completar=llm.completar,
        sintetizar=sintetizar,
        metadatos={"stt": stt.modelo, "llm": llm.modelo, "voz": metadatos_voz},
        consultar_rag=consultar_rag,
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
    obtener_registro_documentos(cfg)
