"""Detección de duplicados del corpus. Exactos y **casi** exactos.

Por qué no basta el hash del texto
-----------------------------------
El README del reto avisa de que el corpus trae documentos repetidos. El hash del
texto extraído los encuentra… si el texto es idéntico. **No lo es.** Medido
sobre los 106 documentos con capa de texto (2026-08-10):

    Jaccard  documento
    0,9822   total joint replacement/Orthopaedic Surgery - 2019 - Li - Postoperative
             Pain Management in Total Knee Arthroplasty.pdf
             ≡ total joint replacement/Postoperative Pain Management in Total Knee
             Arthroplasty.pdf
    0,9713   colorectal cancer/Recommendations for follow-up of colorectal cancer
             survivors.pdf
             ≡ colorectal cancer/ecommendations for follow-up of colorectal cancer
             survivors.pdf

Son el mismo artículo exportado dos veces. Lo que los diferencia es el encabezado
del editor: `Vol.:(0123456789)1 3` en una exportación y `Vol:.(1234567890)` en la
otra. Dos caracteres de maquetación, y el SHA-256 ya no coincide. Indexarlos por
duplicado no es solo desperdicio: el buscador devuelve dos veces el mismo párrafo
y gasta dos de los cinco puestos del top-k en decir lo mismo.

El criterio, y de dónde sale su número
--------------------------------------
Similitud de Jaccard sobre **shingles de 7 palabras** del texto canonizado
(minúsculas, sin tildes, sin puntuación). Un shingle de 7 palabras es lo bastante
largo para que la coincidencia no sea casual entre dos guías clínicas del mismo
tema, y lo bastante corto para sobrevivir a un salto de línea distinto.

El umbral es **0,90**, y está en un hueco medido, no en una intuición: los dos
pares duplicados puntúan 0,9713 y 0,9822, y **el siguiente par del corpus queda
por debajo de 0,30**. Entre 0,30 y 0,97 no hay ni un par. El umbral podría estar
en cualquier punto de ese hueco; 0,90 lo deja lejos de los dos bordes.

Se reproduce con `scripts/indexar_corpus.py`, que imprime cada descarte con su
gemelo y su similitud.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

__all__ = [
    "TAMANO_SHINGLE",
    "UMBRAL_JACCARD",
    "Detector",
    "canonizar",
    "huella",
    "jaccard",
]

TAMANO_SHINGLE = 7
UMBRAL_JACCARD = 0.90
MINIMO_PALABRAS = 50
"""Por debajo de esto no hay shingles suficientes para que el Jaccard signifique
nada: dos textos de 20 palabras pueden coincidir por casualidad."""

_NO_PALABRA = re.compile(r"[^a-z0-9ñ]+")


def canonizar(texto: str) -> list[str]:
    """Palabras en minúscula, sin tildes y sin puntuación.

    Es lo que hace que la diferencia entre dos exportaciones del mismo PDF —un
    encabezado de editor, un guion distinto, un espacio de más— deje de contar.
    """
    plano = unicodedata.normalize("NFD", texto.lower())
    plano = "".join(c for c in plano if unicodedata.category(c) != "Mn")
    return _NO_PALABRA.sub(" ", plano).split()


def huella(texto: str, tamano: int = TAMANO_SHINGLE) -> frozenset[bytes]:
    """Conjunto de shingles de `tamano` palabras, cada uno reducido a 8 bytes.

    Se guarda el hash y no el shingle: con 16.000 fragmentos y 106 documentos, el
    texto de los shingles ocuparía cientos de MB en memoria y no aporta nada —lo
    único que se hace con ellos es compararlos por igualdad—.
    """
    palabras = canonizar(texto)
    if len(palabras) < max(MINIMO_PALABRAS, tamano):
        return frozenset()
    return frozenset(
        hashlib.blake2b(
            " ".join(palabras[i : i + tamano]).encode("utf-8"), digest_size=8
        ).digest()
        for i in range(len(palabras) - tamano + 1)
    )


def jaccard(a: frozenset[bytes], b: frozenset[bytes]) -> float:
    """|A ∩ B| / |A ∪ B|. Cero si alguno está vacío."""
    if not a or not b:
        return 0.0
    interseccion = len(a & b)
    if not interseccion:
        return 0.0
    return interseccion / len(a | b)


class Detector:
    """Acumula documentos aceptados y decide si el siguiente es repetido.

    Comparación contra **todos** los aceptados, sin índice invertido ni MinHash:
    son 106 documentos y 5.565 pares, que en esta escala es un bucle de segundos.
    Un MinHash aproximaría el mismo número con una fuente de error nueva —falsos
    negativos por muestreo— a cambio de un tiempo que aquí no importa.
    """

    def __init__(self, umbral: float = UMBRAL_JACCARD) -> None:
        self.umbral = umbral
        self._exactos: dict[str, str] = {}
        self._huellas: list[tuple[str, frozenset[bytes]]] = []

    def evaluar(self, clave: str, texto: str) -> tuple[str | None, float, str]:
        """Devuelve `(gemelo, similitud, motivo)`. `gemelo=None` si es nuevo.

        `motivo` es «exacto» o «solapamiento», y viaja al informe del indexador:
        un descarte por hash idéntico y uno por 0,97 de Jaccard son hallazgos
        distintos y merecen leerse distinto.
        """
        digest = hashlib.sha256(texto.encode("utf-8")).hexdigest()
        gemelo = self._exactos.get(digest)
        if gemelo is not None:
            return gemelo, 1.0, "exacto"

        propia = huella(texto)
        for otra_clave, otra in self._huellas:
            similitud = jaccard(propia, otra)
            if similitud >= self.umbral:
                return otra_clave, similitud, "solapamiento"

        self._exactos[digest] = clave
        self._huellas.append((clave, propia))
        return None, 0.0, ""
