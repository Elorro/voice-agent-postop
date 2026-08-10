"""Inventario de los documentos subidos por la consola, y su ingesta.

El estado intermedio es requisito, no cortesía
----------------------------------------------
El reto pide un indicador visible de «procesado y disponible» por documento. Un
indicador binario mentiría durante el minuto que tarda la ingesta: el archivo ya
está subido y todavía no responde nada, y el operador no tendría forma de
distinguir «espere» de «falló». Por eso el ciclo de vida tiene cuatro estados y
los cuatro se ven:

    pendiente → procesando → disponible
                          ↘ error

`disponible` no se declara por haber terminado el bucle: se declara **después de
contar los trozos que quedaron en la colección** (`Almacen.contar_documento`).
Es la diferencia entre «creo que lo indexé» y «el índice lo tiene».

El inventario se persiste en JSON dentro del mismo volumen que los archivos. Si
el proceso se reinicia a mitad de una ingesta, al releerlo aparece un documento
en `procesando` que ya nadie está procesando; `reconciliar()` lo detecta al
arrancar y lo pasa a `error` en vez de dejarlo girando para siempre.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.rag.tipos import ORIGEN_SUBIDO, Trozo

_log = logging.getLogger(__name__)

__all__ = [
    "PENDIENTE",
    "PROCESANDO",
    "DISPONIBLE",
    "ERROR",
    "Documento",
    "Registro",
    "nombre_seguro",
]

PENDIENTE = "pendiente"
PROCESANDO = "procesando"
DISPONIBLE = "disponible"
ERROR = "error"

_ETIQUETAS = {
    PENDIENTE: "en cola",
    PROCESANDO: "procesando",
    DISPONIBLE: "procesado y disponible",
    ERROR: "error",
}


def nombre_seguro(nombre: str) -> str:
    """Nombre de archivo mostrable, sin rutas ni control.

    El archivo en disco NO se llama así —se llama por el identificador— así que
    esto no es la defensa contra el `../../etc/passwd`: la defensa es no usar
    nunca el nombre del cliente para construir una ruta. Esto es higiene de lo
    que se muestra y se registra.
    """
    limpio = unicodedata.normalize("NFC", nombre or "").replace("\x00", "")
    limpio = limpio.replace("\\", "/").rsplit("/", 1)[-1].strip()
    limpio = "".join(c for c in limpio if c.isprintable())
    return limpio[:180] or "documento"


@dataclass
class Documento:
    """Una entrada del inventario. Serializable tal cual a JSON."""

    id: str
    nombre: str
    estado: str
    bytes: int
    subido_en: str
    archivo: str = ""
    procesado_en: str = ""
    paginas: int = 0
    trozos: int = 0
    idioma: str = ""
    mensaje: str = ""

    def a_json(self) -> dict[str, Any]:
        datos = asdict(self)
        datos["etiqueta_estado"] = _ETIQUETAS.get(self.estado, self.estado)
        datos["disponible"] = self.estado == DISPONIBLE
        return datos


def _ahora() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


class Registro:
    """Inventario persistente. Un archivo JSON, un candado, escritura atómica.

    JSON y no SQLite: son decenas de entradas como mucho, el jurado tiene que
    poder abrirlo, y meter una segunda base de datos al lado de la de ChromaDB
    por una lista de veinte elementos sería pagar complejidad sin comprar nada.
    """

    def __init__(self, ruta: Path) -> None:
        self.ruta = ruta
        self._candado = threading.RLock()
        self._documentos: dict[str, Documento] = {}
        self._cargar()

    # -- persistencia -------------------------------------------------------- #

    def _cargar(self) -> None:
        if not self.ruta.is_file():
            return
        try:
            crudo = json.loads(self.ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _log.error("inventario ilegible en %s: %s", self.ruta, exc)
            return
        for entrada in crudo.get("documentos", []):
            try:
                campos = {k: v for k, v in entrada.items() if k in Documento.__annotations__}
                doc = Documento(**campos)
            except TypeError as exc:
                _log.warning("entrada de inventario descartada: %s", exc)
                continue
            self._documentos[doc.id] = doc

    def _guardar(self) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal = self.ruta.with_suffix(".json.tmp")
        temporal.write_text(
            json.dumps(
                {"documentos": [asdict(d) for d in self._documentos.values()]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        os.replace(temporal, self.ruta)

    # -- consulta ------------------------------------------------------------ #

    def listar(self) -> list[Documento]:
        with self._candado:
            return sorted(self._documentos.values(), key=lambda d: d.subido_en, reverse=True)

    def obtener(self, documento_id: str) -> Documento | None:
        with self._candado:
            return self._documentos.get(documento_id)

    # -- mutación ------------------------------------------------------------ #

    def crear(self, nombre: str, tamano: int, sufijo: str) -> Documento:
        with self._candado:
            documento_id = f"subido-{uuid.uuid4().hex[:12]}"
            doc = Documento(
                id=documento_id,
                nombre=nombre_seguro(nombre),
                estado=PENDIENTE,
                bytes=tamano,
                subido_en=_ahora(),
                archivo=f"{documento_id}{sufijo.lower()}",
            )
            self._documentos[documento_id] = doc
            self._guardar()
            return doc

    def actualizar(self, documento_id: str, **campos: Any) -> Documento | None:
        with self._candado:
            doc = self._documentos.get(documento_id)
            if doc is None:
                return None
            for clave, valor in campos.items():
                setattr(doc, clave, valor)
            self._guardar()
            return doc

    def eliminar(self, documento_id: str) -> Documento | None:
        with self._candado:
            doc = self._documentos.pop(documento_id, None)
            if doc is not None:
                self._guardar()
            return doc

    def reconciliar(self) -> int:
        """Marca en error lo que quedó `procesando` de un proceso anterior.

        Se llama al arrancar. Sin esto, un contenedor reiniciado a mitad de una
        ingesta muestra para siempre un documento «procesando» que nadie procesa,
        y el indicador del reto pasa de informar a mentir.
        """
        tocados = 0
        with self._candado:
            for doc in self._documentos.values():
                if doc.estado in (PENDIENTE, PROCESANDO):
                    doc.estado = ERROR
                    doc.mensaje = (
                        "el servicio se reinició durante el procesamiento; "
                        "vuelva a subir el documento"
                    )
                    tocados += 1
            if tocados:
                self._guardar()
        return tocados


# --------------------------------------------------------------------------- #
# Ingesta
# --------------------------------------------------------------------------- #
def ingerir(
    registro: Registro,
    almacen: Any,
    documento: Documento,
    ruta_archivo: Path,
    *,
    trozo_caracteres: int,
    solape_caracteres: int,
) -> None:
    """Extrae, trocea e indexa. **Corre en un hilo, nunca en el bucle de eventos.**

    El embedder es CPU pura: ~40 ms por trozo y decenas de segundos por
    documento. Ejecutarlo en la corrutina del endpoint congelaría el turno de voz
    del paciente que esté en línea, que es exactamente el fallo que la consola no
    puede provocar. Ver `app/api_documentos.py`, que la despacha con
    `run_in_executor`.

    Esta función no lanza: cualquier fallo termina en `estado=error` con su
    motivo, porque el sitio donde hay que ver el error es el indicador de la
    consola, no el log del servidor.
    """
    from app.rag import extraccion, idioma, troceo

    registro.actualizar(documento.id, estado=PROCESANDO, mensaje="")
    try:
        paginas = extraccion.extraer_paginas(ruta_archivo)
    except extraccion.ErrorDeExtraccion as exc:
        registro.actualizar(documento.id, estado=ERROR, mensaje=f"no se pudo leer: {exc}")
        return
    except Exception as exc:  # noqa: BLE001
        registro.actualizar(
            documento.id, estado=ERROR, mensaje=f"{type(exc).__name__}: {exc}"[:300]
        )
        return

    if not extraccion.tiene_capa_de_texto(paginas):
        registro.actualizar(
            documento.id,
            estado=ERROR,
            paginas=len(paginas),
            mensaje=(
                "el PDF no trae capa de texto (parece escaneado). Este sistema no "
                "hace OCR: suba una versión con texto seleccionable."
            ),
        )
        return

    texto = troceo.normalizar("\n".join(p.texto for p in paginas))
    lengua = idioma.detectar(texto)
    huella = extraccion.hash_de_texto(texto)
    crudos = troceo.trocear(
        paginas, max_caracteres=trozo_caracteres, solape_caracteres=solape_caracteres
    )
    if not crudos:
        registro.actualizar(
            documento.id,
            estado=ERROR,
            paginas=len(paginas),
            mensaje="no se obtuvo ningún fragmento de texto útil",
        )
        return

    trozos = [
        Trozo(
            id=f"{documento.id}-{k:05d}",
            texto=crudo.texto,
            ruta_relativa=documento.nombre,
            pagina=crudo.pagina,
            escenario="(subido por la consola)",
            idioma=lengua,
            origen=ORIGEN_SUBIDO,
            hash_documento=huella,
            documento_id=documento.id,
            indice=k,
        )
        for k, crudo in enumerate(crudos)
    ]

    try:
        almacen.agregar(trozos)
    except Exception as exc:  # noqa: BLE001
        registro.actualizar(
            documento.id, estado=ERROR, mensaje=f"el índice rechazó el documento: {exc}"[:300]
        )
        return

    # «Disponible» se afirma contando lo que quedó DENTRO, no lo que se mandó.
    dentro = almacen.contar_documento(documento.id)
    if dentro == 0:
        registro.actualizar(
            documento.id,
            estado=ERROR,
            mensaje="la inserción no dejó ningún fragmento en el índice",
        )
        return

    registro.actualizar(
        documento.id,
        estado=DISPONIBLE,
        paginas=len(paginas),
        trozos=dentro,
        idioma=lengua,
        procesado_en=_ahora(),
        mensaje="",
    )
    _log.info(
        "documento %s disponible: %d páginas, %d fragmentos", documento.id, len(paginas), dentro
    )
