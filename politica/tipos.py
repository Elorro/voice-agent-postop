"""Vocabulario del módulo de decisión clínica (HD5).

Solo tipos: ni lógica ni valores. Los parámetros viven en `politica.parametros`,
que este módulo NO importa (la dependencia va en el otro sentido).

Referencias de sección apuntan a `docs/diseno/parametros_politica.md`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from types import MappingProxyType
from typing import Mapping

__all__ = [
    "Trivalor",
    "Clase",
    "Regimen",
    "Accion",
    "Criterio",
    "Observacion",
    "Presupuesto",
    "Decision",
    "ErrorDeInvocacion",
]


class Trivalor(Enum):
    """§1.1 — todo predicado sobre una señal se evalúa en lógica trivaluada."""

    VERDADERO = auto()
    FALSO = auto()
    DESCONOCIDO = auto()


class Clase(Enum):
    """Clase clínica terminal."""

    VERDE = auto()
    AMARILLO = auto()
    ROJO = auto()


class Regimen(Enum):
    """§2 — régimen temporal derivado por el Nivel 0."""

    TEMPRANO = auto()
    TARDIO = auto()


class Accion(Enum):
    """Qué hace el agente con esta `Decision`."""

    CLASIFICAR = auto()
    REPREGUNTAR = auto()


class Criterio(Enum):
    """Por qué se cerró: §7.1 (S1/S2/S3), §7.4 (cierre forzado) o §8 (agotamiento)."""

    S1 = auto()
    S2 = auto()
    S3 = auto()
    CIERRE_FORZADO = auto()
    AGOTAMIENTO = auto()


class ErrorDeInvocacion(ValueError):
    """§8.2 — entrada imposible de un llamador correcto. Falla ruidoso, no clasifica."""


@dataclass(frozen=True)
class Observacion:
    """Vector observado en un turno. AUSENTE se representa como `None`.

    `dia_postop` NO es señal del núcleo (§1.2): es dato del seguimiento, no
    indagable. Su ausencia tiene tratamiento propio en §2.1.
    """

    dia_postop: int | None
    dolor_nrs: int | None
    fiebre_c: float | None
    herida: str | None
    movilidad: str | None
    apetito: str | None
    sueno: str | None


@dataclass(frozen=True)
class Presupuesto:
    """Estado de indagación que el llamador lleva. El módulo lo LEE, nunca lo muta (HD7).

    `preguntas_por_senal`: señal del núcleo -> repreguntas ya gastadas en ella.
    `preguntas_totales`: turnos de repregunta emitidos en la llamada.
    """

    preguntas_por_senal: Mapping[str, int]
    preguntas_totales: int

    def __post_init__(self) -> None:
        # Copia inmutable en la frontera: ni el módulo puede mutarla, ni una
        # mutación posterior del dict del llamador puede alterar esta instancia.
        object.__setattr__(
            self, "preguntas_por_senal", MappingProxyType(dict(self.preguntas_por_senal))
        )

    def gastadas(self, senal: str) -> int:
        return self.preguntas_por_senal.get(senal, 0)


@dataclass(frozen=True)
class Decision:
    """Salida única de `decidir`. Insumo del registro de escalamiento, no el registro.

    El módulo no sabe de `caso_id`, `paciente_id` ni `citas_RAG`: eso es de la
    capa de arriba.
    """

    accion: Accion
    clase: Clase | None
    criterio: Criterio | None
    senal_a_indagar: str | None
    regimen: Regimen
    banderas: Mapping[str, Trivalor]
    compuerta: Trivalor
    n_total: int
    disparadores: tuple[str, ...] = field(default=())
    marcas: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        object.__setattr__(self, "banderas", MappingProxyType(dict(self.banderas)))
