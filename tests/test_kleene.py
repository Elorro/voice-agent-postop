"""§1.1 — lógica trivaluada de Kleene fuerte."""

from __future__ import annotations

from itertools import product

import pytest

from politica import Trivalor
from politica.kleene import (
    alguna,
    conjuncion,
    de_bool,
    disyuncion,
    evaluar,
    no,
    o,
    y,
)

V, F, D = Trivalor.VERDADERO, Trivalor.FALSO, Trivalor.DESCONOCIDO
TODOS = (V, F, D)


def esperado_y(a: Trivalor, b: Trivalor) -> Trivalor:
    """Tabla de §1.1 transcrita como reglas por fila, no como diccionario.

    La tabla del módulo se escribe extendida; esta se escribe por filas. Si
    alguien edita una, la otra la contradice.
    """
    if a is V:
        return b
    if a is F:
        return F
    return F if b is F else D  # a is D


def esperado_o(a: Trivalor, b: Trivalor) -> Trivalor:
    if a is V:
        return V
    if a is F:
        return b
    return V if b is V else D  # a is D


@pytest.mark.parametrize("a,b", list(product(TODOS, TODOS)))
def test_tabla_de_la_spec(a: Trivalor, b: Trivalor) -> None:
    assert y(a, b) is esperado_y(a, b)
    assert o(a, b) is esperado_o(a, b)


def test_negacion() -> None:
    assert no(V) is F
    assert no(F) is V
    assert no(D) is D


def test_ausente_nunca_colapsa_a_falso() -> None:
    """El punto entero de §1.1: DESCONOCIDO no es FALSO."""
    assert D is not F
    assert y(D, V) is D
    assert o(D, F) is D
    assert no(D) is D
    # Lo único que absorbe un DESCONOCIDO es el elemento absorbente del operador.
    assert y(D, F) is F
    assert o(D, V) is V


@pytest.mark.parametrize("a,b", list(product(TODOS, TODOS)))
def test_conmutatividad(a: Trivalor, b: Trivalor) -> None:
    assert y(a, b) is y(b, a)
    assert o(a, b) is o(b, a)


@pytest.mark.parametrize("a,b,c", list(product(TODOS, TODOS, TODOS)))
def test_asociatividad_y_de_morgan(a: Trivalor, b: Trivalor, c: Trivalor) -> None:
    assert y(y(a, b), c) is y(a, y(b, c))
    assert o(o(a, b), c) is o(a, o(b, c))
    assert no(y(a, b)) is o(no(a), no(b))
    assert no(o(a, b)) is y(no(a), no(b))


def test_neutros_de_las_operaciones_n_arias() -> None:
    assert conjuncion() is V
    assert disyuncion() is F  # sostiene la compuerta vacía de §4 en TEMPRANO
    assert conjuncion(V, V, D) is D
    assert disyuncion(F, F, D) is D
    assert disyuncion(F, D, V) is V
    assert alguna([F, F]) is F


def test_evaluar_traduce_ausencia() -> None:
    assert evaluar(None, lambda x: True) is D
    assert evaluar(38.0, lambda t: t >= 38.0) is V
    assert evaluar(37.9, lambda t: t >= 38.0) is F
    assert de_bool(True) is V
    assert de_bool(False) is F


def test_evaluar_no_ejecuta_el_predicado_si_hay_ausencia() -> None:
    """Un predicado no tiene que saber tratar `None`: la ausencia se corta antes."""

    def explota(_: object) -> bool:
        raise AssertionError("el predicado no debe evaluarse sobre AUSENTE")

    assert evaluar(None, explota) is D
