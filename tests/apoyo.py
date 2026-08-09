"""Constructores de observaciones para los tests. Sin lógica de política."""

from __future__ import annotations

from itertools import product
from typing import Iterator

from politica import Observacion, Presupuesto
from politica.motor import NUCLEO
from politica.parametros import TOPE_GLOBAL, TOPE_POR_SENAL

# Caso benigno de régimen tardío con vector completo: la línea base sobre la que
# cada test cambia solo lo que le interesa.
BASE_TARDIO: dict[str, object] = {
    "dia_postop": 7,
    "dolor_nrs": 1,
    "fiebre_c": 36.6,
    "herida": "normal",
    "movilidad": "normal",
    "apetito": "normal",
    "sueno": "normal",
}

BASE_TEMPRANO: dict[str, object] = {**BASE_TARDIO, "dia_postop": 1}


def obs(**cambios: object) -> Observacion:
    """Observación completa y benigna (día 7), con los campos indicados sustituidos."""
    return Observacion(**{**BASE_TARDIO, **cambios})  # type: ignore[arg-type]


def obs_temprano(**cambios: object) -> Observacion:
    """Igual que `obs`, en régimen temprano (día 1)."""
    return Observacion(**{**BASE_TEMPRANO, **cambios})  # type: ignore[arg-type]


def vacia(**cambios: object) -> Observacion:
    """Observación con todo AUSENTE salvo lo que se pase explícitamente."""
    ninguna = dict.fromkeys(BASE_TARDIO, None)
    return Observacion(**{**ninguna, **cambios})  # type: ignore[arg-type]


def presupuesto_agotado(
    tope_por_senal: int = TOPE_POR_SENAL, tope_global: int = TOPE_GLOBAL
) -> Presupuesto:
    """Presupuesto sin margen: ni por señal ni global."""
    return Presupuesto({senal: tope_por_senal for senal in NUCLEO}, tope_global)


# Rejilla reducida del espacio de entradas para los property tests. Incluye los
# bordes de cada umbral y `None` en cada señal del núcleo.
REJILLA: dict[str, tuple[object, ...]] = {
    "dia_postop": (1, 7, None),
    "dolor_nrs": (0, 4, 5, 6, 9, None),
    "fiebre_c": (36.5, 37.5, 37.8, 38.0, None),
    "herida": ("normal", "eritema_leve", "secrecion_purulenta", None),
    "movilidad": ("normal", "limitada_esperada", "incapacitante_nueva", None),
    "apetito": ("normal", "levemente_disminuido", "muy_disminuido", None),
    "sueno": ("normal", "levemente_alterado", "muy_alterado", None),
}


def barrido(rejilla: dict[str, tuple[object, ...]] = REJILLA) -> Iterator[Observacion]:
    """Producto cartesiano de la rejilla. Determinista y ordenado."""
    campos = tuple(rejilla)
    for combinacion in product(*(rejilla[campo] for campo in campos)):
        yield Observacion(**dict(zip(campos, combinacion)))  # type: ignore[arg-type]
