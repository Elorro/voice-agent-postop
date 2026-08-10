"""Texto por página, y detección del PDF sin capa de texto.

`pypdf` y no otro
-----------------
Es Python puro (378 kB de rueda, **cero dependencias transitivas**) y lee la capa
de texto que el PDF ya trae. Las alternativas se descartaron por lo que cuestan
en una imagen de 400 MB: `pdfplumber` arrastra `pdfminer.six` y `Pillow`,
`PyMuPDF` es un binario de ~20 MB, y cualquier ruta con OCR (`pytesseract`,
`ocrmypdf`) mete un binario nativo y un modelo de idioma para resolver **un**
documento del corpus.

El PDF escaneado: se DESCARTA, no se le hace OCR
------------------------------------------------
El corpus trae al menos un documento que es una imagen escaneada sin capa de
texto: `pypdf` devuelve cadena vacía o unos pocos caracteres de basura. Decisión
tomada y declarada: **se descarta explícitamente**, con su nombre en la salida
del indexador y en el README.

Por qué no OCR: el coste es un binario nativo (`tesseract` + datos de idioma
español, ~30 MB) y decenas de segundos por documento, y el beneficio es un
documento sobre 107 cuyo contenido está cubierto por los otros 23 de la misma
carpeta. Lo que NO es aceptable es el hueco silencioso: un documento que no está
en el índice y del que nadie se enteró es indistinguible de un bug del indexador.

El umbral de «sin capa de texto» es por CARACTERES POR PÁGINA y no por total: un
PDF de 40 páginas escaneadas puede acumular 300 caracteres de ruido y parecer un
documento corto legítimo.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from app.rag.tipos import Pagina

_log = logging.getLogger(__name__)

__all__ = [
    "MINIMO_CARACTERES_POR_PAGINA",
    "SUFIJOS_ACEPTADOS",
    "ErrorDeExtraccion",
    "extraer_paginas",
    "hash_de_texto",
    "tiene_capa_de_texto",
]

SUFIJOS_ACEPTADOS = frozenset({".pdf", ".txt", ".md", ".markdown"})
"""El reto pide PDF. `.txt`/`.md` se aceptan además porque no cuestan nada
(son el mismo camino sin el paso de pypdf) y hacen verificable el ciclo de la
consola sin fabricar un PDF."""

MINIMO_CARACTERES_POR_PAGINA = 40
"""Debajo de esto, la página no tiene capa de texto útil.

Calibrado, no supuesto: una página de guía clínica maquetada a una columna trae
2.000–4.000 caracteres; una página escaneada devuelve 0, y las que traen algo
devuelven el encabezado suelto que el visor dejó como texto. 40 caracteres
—media línea— separa las dos poblaciones con dos órdenes de magnitud de holgura.
La cifra por documento del corpus está en `docs/calibracion_rag.md`.
"""


class ErrorDeExtraccion(RuntimeError):
    """El archivo no se pudo abrir o leer. No es lo mismo que «sin texto»."""


def hash_de_texto(texto: str) -> str:
    """SHA-256 del texto **extraído**, no del archivo.

    Es lo que hace detectable el duplicado real del corpus: el mismo documento
    reexportado tiene otros bytes —otra fecha de creación, otro productor, otro
    orden de objetos— y el mismo texto. Un hash del archivo no vería nada.
    """
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def tiene_capa_de_texto(paginas: list[Pagina]) -> bool:
    """Verdadero si el promedio de caracteres por página supera el mínimo."""
    if not paginas:
        return False
    total = sum(len(p.texto.strip()) for p in paginas)
    return (total / len(paginas)) >= MINIMO_CARACTERES_POR_PAGINA


def extraer_paginas(ruta: Path) -> list[Pagina]:
    """Texto por página. Una página ilegible no tumba el documento entero.

    `pypdf` lanza en páginas concretas con la capa de texto corrupta; devolver
    lista vacía por eso perdería las otras 30 páginas buenas. Se registra y se
    sigue.
    """
    sufijo = ruta.suffix.lower()
    if sufijo not in SUFIJOS_ACEPTADOS:
        raise ErrorDeExtraccion(f"extensión no aceptada: {sufijo or '(ninguna)'}")

    if sufijo != ".pdf":
        try:
            texto = ruta.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ErrorDeExtraccion(str(exc)) from exc
        # Un texto plano no tiene páginas. Se declara «página 1» y se dice así en
        # la cita: inventar una paginación sería una referencia irresoluble.
        return [Pagina(1, texto)]

    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependencia de la imagen
        raise ErrorDeExtraccion(
            "falta pypdf: está en requirements.txt y en la imagen; "
            "fuera del contenedor, `pip install --user pypdf`"
        ) from exc

    try:
        lector = PdfReader(str(ruta))
        if lector.is_encrypted:
            # Muchos PDF «cifrados» del mundo real lo están con contraseña vacía
            # (solo restringen impresión). Se intenta; si no cede, se reporta.
            try:
                lector.decrypt("")
            except Exception as exc:  # noqa: BLE001
                raise ErrorDeExtraccion(f"PDF cifrado: {exc}") from exc
        total = len(lector.pages)
    except ErrorDeExtraccion:
        raise
    except Exception as exc:  # noqa: BLE001 - pypdf lanza de todo ante un PDF roto
        raise ErrorDeExtraccion(f"{type(exc).__name__}: {exc}") from exc

    paginas: list[Pagina] = []
    for numero in range(1, total + 1):
        try:
            texto = lector.pages[numero - 1].extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            _log.warning("%s: página %d ilegible (%s)", ruta.name, numero, exc)
            texto = ""
        paginas.append(Pagina(numero, texto))
    return paginas
