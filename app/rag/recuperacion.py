"""Recuperación con umbral de suficiencia. Código puro: se prueba sin chromadb.

El umbral es la pieza clínica de este módulo
--------------------------------------------
Un buscador de vecinos más cercanos **siempre devuelve k resultados**. Sobre la
pregunta «¿cuánto cuesta el pasaje a Bogotá?» devolverá los cinco trozos del
corpus quirúrgico menos lejanos, y si esos trozos se le pasan a un modelo de
lenguaje con el encargo de responder, el modelo redacta algo. Ese algo es una
respuesta clínica inventada con aspecto de citada, que es el peor resultado
posible de todo el sistema.

Por eso la función devuelve **vacío** cuando el mejor score no alcanza el umbral,
y el llamador declara su límite en vez de improvisar. La regla es una sola y se
aplica a cada fragmento —no «si el mejor pasa, entran todos»—, porque un
acompañante con score bajo es exactamente el trozo del que el modelo saca la
frase que nadie escribió.

El valor del umbral vive en `app/config.py` (`RAG_UMBRAL`), no aquí: es un
parámetro de operación, calibrado y con procedimiento declarado en
`docs/calibracion_rag.md`. Este módulo solo lo aplica.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Sequence

from app.rag.tipos import Fragmento

_log = logging.getLogger(__name__)

__all__ = ["Recuperacion", "filtrar", "recuperar"]


@dataclass(frozen=True, slots=True)
class Recuperacion:
    """Resultado de una consulta, con lo que hace falta para el registro.

    `mejor_score` viaja aunque no haya fragmentos: es lo que permite auditar
    después «qué tan cerca estuvo» una consulta que se rechazó por umbral. Sin
    ese número, un umbral mal puesto es indistinguible de un corpus que no cubre
    el tema.
    """

    fragmentos: tuple[Fragmento, ...] = ()
    mejor_score: float | None = None
    examinados: int = 0
    umbral: float = 0.0
    ms: float = 0.0
    error: str = ""

    @property
    def suficiente(self) -> bool:
        return bool(self.fragmentos)

    def a_registro(self, max_caracteres: int) -> dict:
        """El bloque `rag` de una línea de `turnos.jsonl`."""
        bloque = {
            "consultas": 1,
            "citas": [f.a_cita(max_caracteres) for f in self.fragmentos],
            "mejor_score": (
                round(self.mejor_score, 4) if self.mejor_score is not None else None
            ),
            "umbral": self.umbral,
            "suficiente": self.suficiente,
        }
        if self.error:
            bloque["error"] = self.error
        return bloque


def filtrar(fragmentos: Sequence[Fragmento], umbral: float) -> list[Fragmento]:
    """Los fragmentos que alcanzan el umbral, en el orden que traían."""
    return [f for f in fragmentos if f.score >= umbral]


def recuperar(
    consultar: Callable[[str, int], Sequence[Fragmento]],
    consulta: str,
    *,
    k: int,
    umbral: float,
) -> Recuperacion:
    """Consulta el índice y aplica el umbral. Nunca lanza hacia el turno.

    `consultar` se recibe inyectada (`Almacen.consultar` en producción, una
    lista fija en los tests) por la misma razón que `Servicios` en el turno: la
    lógica de suficiencia tiene que poder ejercitarse sin modelo y sin índice,
    incluido el caso que más importa —el corpus no cubre la pregunta— que con un
    índice real solo se puede provocar por casualidad.
    """
    import time

    inicio = time.perf_counter()
    texto = (consulta or "").strip()
    if not texto:
        return Recuperacion(umbral=umbral)

    try:
        candidatos = list(consultar(texto, k))
    except Exception as exc:  # noqa: BLE001 - el turno sigue; se declara el límite
        _log.error("la consulta al índice falló: %s", exc)
        return Recuperacion(
            umbral=umbral,
            ms=(time.perf_counter() - inicio) * 1000,
            error=f"{type(exc).__name__}: {exc}"[:200],
        )

    mejor = max((f.score for f in candidatos), default=None)
    aceptados = filtrar(candidatos, umbral)
    return Recuperacion(
        fragmentos=tuple(aceptados),
        mejor_score=mejor,
        examinados=len(candidatos),
        umbral=umbral,
        ms=(time.perf_counter() - inicio) * 1000,
    )
