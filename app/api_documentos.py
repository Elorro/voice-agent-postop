"""Consola de administración: subir, listar y eliminar documentos. Compuerta G5.

Contrato del reto, ni más ni menos
----------------------------------
    GET    /consola                 la página (está en app/main.py)
    POST   /api/documentos          subir
    GET    /api/documentos          listar
    DELETE /api/documentos/{id}     eliminar

Las dos propiedades que la compuerta mide, y dónde se sostienen
---------------------------------------------------------------

**«Disponible para el agente sin reiniciar nada.»** El documento se indexa en la
MISMA colección que el corpus, sobre el MISMO objeto `Almacen` que consulta el
turno (`app/servicios.py` lo abre una sola vez por proceso). No hay recarga, no
hay segunda colección y no hay caché que invalidar: en cuanto `upsert` vuelve, la
siguiente consulta lo ve.

**«El agente deja de usarlo de inmediato.»** `DELETE` borra los fragmentos por
`where={"documento_id": …}` antes de responder. Si el borrado falla, la entrada
NO se quita del inventario: dejar el archivo listado con un error es recuperable;
quitarlo de la lista con sus fragmentos dentro del índice deja al agente citando
un documento que la consola jura haber borrado.

Por qué la ingesta va a un hilo
-------------------------------
El embedder es CPU pura y bloqueante. FastAPI corre este endpoint en el bucle de
eventos; ejecutar ahí la ingesta de un PDF de 40 páginas congelaría **todo** el
proceso durante decenas de segundos, incluido el turno del paciente que esté
hablando en ese momento. Se despacha con `run_in_executor` y el endpoint devuelve
de inmediato con estado `pendiente`; la consola descubre el resto preguntando por
`GET /api/documentos`, que es justo lo que hace visible el estado intermedio que
el reto exige.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.config import Config, obtener_config
from app.rag import documentos as doc
from app.rag.extraccion import SUFIJOS_ACEPTADOS
from app.servicios import obtener_almacen, obtener_registro_documentos

_log = logging.getLogger(__name__)

router = APIRouter()

TROZO_LECTURA = 1 << 20
"""Bytes por lectura al recibir el archivo. Se lee a trozos y no de una vez para
que un archivo enorme se rechace por tamaño **antes** de estar entero en memoria."""


def _cfg() -> Config:
    return obtener_config()


def _almacen_o_503(cfg: Config) -> Any:
    almacen = obtener_almacen(cfg)
    if almacen is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "el índice vectorial no está disponible; la consola no puede "
                "indexar. Consulte /salud para el motivo."
            ),
        )
    return almacen


@router.get("/api/documentos")
def listar_documentos() -> JSONResponse:
    """Inventario completo, con el estado de cada documento.

    Incluye `trozos_en_indice`, releído del índice y no del inventario: el
    inventario dice lo que el proceso cree, y el índice dice lo que hay. Que la
    consola muestre el segundo es lo que hace que «procesado y disponible»
    signifique algo verificable.
    """
    cfg = _cfg()
    registro = obtener_registro_documentos(cfg)
    almacen = obtener_almacen(cfg)
    salida = []
    for documento in registro.listar():
        datos = documento.a_json()
        datos["trozos_en_indice"] = (
            almacen.contar_documento(documento.id) if almacen is not None else None
        )
        salida.append(datos)
    return JSONResponse(
        {
            "documentos": salida,
            "indice_disponible": almacen is not None,
            "formatos": sorted(SUFIJOS_ACEPTADOS),
            "max_mb": cfg.subidos_max_mb,
        }
    )


@router.post("/api/documentos", status_code=202)
async def subir_documento(archivo: UploadFile = File(...)) -> JSONResponse:
    """Recibe el archivo, lo deja en el volumen y lanza la ingesta en un hilo.

    Devuelve **202 Accepted**, no 201: cuando esta respuesta sale, el documento
    está guardado pero todavía no indexado. Un 201 afirmaría que el recurso ya
    existe tal como se pidió, y la consola tendría que desmentirlo un segundo
    después.
    """
    cfg = _cfg()
    almacen = _almacen_o_503(cfg)
    registro = obtener_registro_documentos(cfg)

    nombre = doc.nombre_seguro(archivo.filename or "documento")
    sufijo = ("." + nombre.rsplit(".", 1)[-1]).lower() if "." in nombre else ""
    if sufijo not in SUFIJOS_ACEPTADOS:
        raise HTTPException(
            status_code=415,
            detail=(
                f"formato no aceptado: «{sufijo or 'sin extensión'}». "
                f"Acepta: {', '.join(sorted(SUFIJOS_ACEPTADOS))}"
            ),
        )

    tope = int(cfg.subidos_max_mb * 1_048_576)
    cfg.dir_subidos.mkdir(parents=True, exist_ok=True)

    # El identificador se crea antes de escribir para que el archivo en disco se
    # llame por él y NUNCA por el nombre que mandó el cliente: es lo que hace que
    # un «../../app/main.py» no pueda construir una ruta.
    documento = registro.crear(nombre, 0, sufijo)
    destino = cfg.dir_subidos / documento.archivo

    total = 0
    try:
        with destino.open("wb") as salida:
            while True:
                trozo = await archivo.read(TROZO_LECTURA)
                if not trozo:
                    break
                total += len(trozo)
                if total > tope:
                    raise HTTPException(
                        status_code=413,
                        detail=f"el archivo supera el máximo de {cfg.subidos_max_mb:g} MB",
                    )
                salida.write(trozo)
    except HTTPException:
        destino.unlink(missing_ok=True)
        registro.eliminar(documento.id)
        raise
    except OSError as exc:
        destino.unlink(missing_ok=True)
        registro.eliminar(documento.id)
        raise HTTPException(status_code=500, detail=f"no se pudo guardar: {exc}") from exc

    if total == 0:
        destino.unlink(missing_ok=True)
        registro.eliminar(documento.id)
        raise HTTPException(status_code=400, detail="el archivo llegó vacío")

    documento = registro.actualizar(documento.id, bytes=total) or documento

    bucle = asyncio.get_running_loop()
    tarea = bucle.run_in_executor(
        None,
        functools.partial(
            doc.ingerir,
            registro,
            almacen,
            documento,
            destino,
            trozo_caracteres=cfg.rag_trozo_caracteres,
            solape_caracteres=cfg.rag_solape_caracteres,
        ),
    )
    # El futuro NO se descarta. `ingerir` no lanza por diseño —sus fallos van al
    # estado del documento— así que lo único que puede llegar aquí es un error de
    # programación al invocarla: una firma que cambió, un argumento de más. Sin
    # este callback ese error se traga en silencio y el documento se queda «en
    # cola» para siempre, sin nada en el log y sin nada en la consola. Pasó, y por
    # eso está escrito: `TypeError: ingerir() takes 4 positional arguments but 6
    # were given`, invisible durante toda una verificación de G5.
    tarea.add_done_callback(lambda f: _reportar_ingesta(registro, documento.id, f))
    _log.info("documento %s recibido (%d bytes), ingesta despachada", documento.id, total)
    return JSONResponse(documento.a_json(), status_code=202)


def _reportar_ingesta(registro: Any, documento_id: str, futuro: Any) -> None:
    """Lleva al estado del documento cualquier fallo del hilo de ingesta."""
    try:
        futuro.result()
    except Exception as exc:  # noqa: BLE001
        _log.exception("la ingesta de %s falló", documento_id)
        registro.actualizar(
            documento_id,
            estado=doc.ERROR,
            mensaje=f"fallo interno durante la ingesta: {type(exc).__name__}: {exc}"[:300],
        )


@router.delete("/api/documentos/{documento_id}")
def eliminar_documento(documento_id: str) -> JSONResponse:
    """Borra los fragmentos del índice, el archivo y la entrada del inventario.

    En ese orden, y es deliberado: el índice primero, porque es lo único que el
    agente consulta. Si algo falla después, lo que queda es un archivo huérfano
    en el volumen —inofensivo— y no un documento que el agente sigue citando.
    """
    cfg = _cfg()
    registro = obtener_registro_documentos(cfg)
    documento = registro.obtener(documento_id)
    if documento is None:
        raise HTTPException(status_code=404, detail=f"documento desconocido: {documento_id}")

    almacen = obtener_almacen(cfg)
    borrados = 0
    if almacen is not None:
        try:
            borrados = almacen.borrar_documento(documento_id)
        except Exception as exc:  # noqa: BLE001
            _log.error("no se pudieron borrar los fragmentos de %s: %s", documento_id, exc)
            registro.actualizar(
                documento_id,
                estado=doc.ERROR,
                mensaje=f"no se pudo eliminar del índice: {exc}"[:300],
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    "no se pudieron borrar los fragmentos del índice; el documento "
                    "sigue listado a propósito, para que no quede citándose en silencio"
                ),
            ) from exc

    if documento.archivo:
        (cfg.dir_subidos / documento.archivo).unlink(missing_ok=True)
    registro.eliminar(documento_id)
    _log.info("documento %s eliminado (%d fragmentos)", documento_id, borrados)
    return JSONResponse(
        {"eliminado": documento_id, "fragmentos_borrados": borrados, "nombre": documento.nombre}
    )
