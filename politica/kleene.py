"""Lógica trivaluada de Kleene fuerte (§1.1).

Las tablas se escriben extendidas, entrada por entrada, en vez de derivarse de
un truco de orden: son la pieza que sostiene «AUSENTE nunca colapsa a FALSO», y
un lector tiene que poder cotejarlas contra la tabla de §1.1 sin ejecutar nada.
"""

from __future__ import annotations

from typing import Callable, Iterable, Mapping, TypeVar

from .tipos import Trivalor

__all__ = ["no", "y", "o", "conjuncion", "disyuncion", "alguna", "de_bool", "evaluar"]

V = Trivalor.VERDADERO
F = Trivalor.FALSO
D = Trivalor.DESCONOCIDO

T = TypeVar("T")

TABLA_NO: Mapping[Trivalor, Trivalor] = {V: F, F: V, D: D}

TABLA_Y: Mapping[tuple[Trivalor, Trivalor], Trivalor] = {
    (V, V): V, (V, F): F, (V, D): D,
    (F, V): F, (F, F): F, (F, D): F,
    (D, V): D, (D, F): F, (D, D): D,
}

TABLA_O: Mapping[tuple[Trivalor, Trivalor], Trivalor] = {
    (V, V): V, (V, F): V, (V, D): V,
    (F, V): V, (F, F): F, (F, D): D,
    (D, V): V, (D, F): D, (D, D): D,
}


def no(a: Trivalor) -> Trivalor:
    return TABLA_NO[a]


def y(a: Trivalor, b: Trivalor) -> Trivalor:
    return TABLA_Y[(a, b)]


def o(a: Trivalor, b: Trivalor) -> Trivalor:
    return TABLA_O[(a, b)]


def conjuncion(*valores: Trivalor) -> Trivalor:
    """Conjunción n-aria. Neutro V: la conjunción vacía es VERDADERO."""
    resultado = V
    for valor in valores:
        resultado = y(resultado, valor)
    return resultado


def disyuncion(*valores: Trivalor) -> Trivalor:
    """Disyunción n-aria. Neutro F: la disyunción vacía es FALSO.

    Ese neutro es el que da la semántica correcta a la compuerta de §4 en
    régimen TEMPRANO, donde no hay ninguna condición que evaluar.
    """
    resultado = F
    for valor in valores:
        resultado = o(resultado, valor)
    return resultado


def de_bool(b: bool) -> Trivalor:
    return V if b else F


def evaluar(valor: T | None, predicado: Callable[[T], bool]) -> Trivalor:
    """§1.1. `AUSENTE` (None) -> DESCONOCIDO; si no, se evalúa el predicado."""
    if valor is None:
        return D
    return de_bool(predicado(valor))


def alguna(valores: Iterable[Trivalor]) -> Trivalor:
    """Azúcar sobre `disyuncion` para iterables."""
    return disyuncion(*valores)
