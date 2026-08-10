"""Detección de idioma es/en. Método declarado, sin dependencias.

Por qué no una biblioteca
-------------------------
`langdetect`, `langid` o `fasttext` traen modelo y peso a una imagen cuyo
presupuesto entero es 400 MB, y resuelven un problema que aquí no existe: el
corpus tiene DOS idiomas conocidos de antemano y textos largos (páginas enteras
de guías clínicas), no tuits de ocho palabras. El caso difícil de la detección
de idioma —cadenas cortas, muchos candidatos— no se da.

Método
------
Frecuencia de **palabras función** (artículos, preposiciones, conjunciones). Son
las palabras más frecuentes de cualquier texto, no se traducen entre sí y casi no
aparecen en el idioma contrario. Se cuentan las ocurrencias de cada lista sobre
el texto normalizado y gana la mayor; empate o ambas en cero → `INDETERMINADO`,
que el indexador reporta y no oculta.

Coste declarado: un texto español con mucha cita en inglés (frecuente en las
guías colombianas, que citan literatura anglosajona) puede quedar clasificado
`en`. El idioma es **metadato**, no filtro: la recuperación no lo usa para
descartar nada, así que un error aquí no esconde un documento. Si algún día se
filtrara por idioma, esta decisión habría que revisarla.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["ES", "EN", "INDETERMINADO", "detectar", "contar_funcionales"]

ES = "es"
EN = "en"
INDETERMINADO = "indeterminado"

# Palabras función que NO son palabra del otro idioma. Se excluyen a propósito
# las ambiguas —«no», «a», «e», «me», «son», «fue», «ha»— porque sumarían a los
# dos lados y solo añadirían ruido.
_ES = frozenset(
    """
    el la los las un una unos unas de del al y o pero porque cuando donde
    que quien cual cuyo como si sin sobre entre hasta desde para por segun
    tras durante mediante ante bajo contra hacia ademas tambien aunque
    mientras entonces asi pues esta estas este estos esa esas ese esos
    aquel su sus mi mis tu tus nuestro nuestra se le les lo nos os
    ser estar tiene tienen puede pueden debe deben hay haber sido
    mas menos muy poco mucho todo toda todos todas otro otra cada
    """.split()
)

_EN = frozenset(
    """
    the of and or but because when where which who whose whom what
    that this these those there their them they his her its our your
    with without within from into onto upon about above below between
    among during through after before while although though however
    therefore thus such been being have has had was were will would
    should could can may might must shall not only also both each
    any some most more less than then per via
    """.split()
)

_PALABRA = re.compile(r"[a-z]+")


def _normalizar(texto: str) -> str:
    """Minúsculas y sin tildes: «según» y «segun» son la misma palabra función."""
    plano = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in plano if unicodedata.category(c) != "Mn")


def contar_funcionales(texto: str) -> tuple[int, int]:
    """Devuelve `(ocurrencias_es, ocurrencias_en)`. Expuesta para los tests."""
    palabras = _PALABRA.findall(_normalizar(texto))
    es = sum(1 for p in palabras if p in _ES)
    en = sum(1 for p in palabras if p in _EN)
    return es, en


def detectar(texto: str) -> str:
    """`es`, `en` o `indeterminado`. Nunca lanza."""
    es, en = contar_funcionales(texto)
    if es == 0 and en == 0:
        return INDETERMINADO
    if es == en:
        return INDETERMINADO
    return ES if es > en else EN
