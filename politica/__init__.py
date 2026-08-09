"""Módulo puro de decisión clínica postoperatoria (Fase 2.1).

Implementa `docs/diseno/parametros_politica.md`, que es su única fuente de
parámetros. Sin estado, sin I/O, solo librería estándar: el validador y el
agente de producción importan exactamente este módulo.

    >>> from politica import decidir, Observacion
    >>> d = decidir(Observacion(7, 2, 36.8, "normal", "normal", "normal", "normal"))
    >>> d.clase.name, d.criterio.name
    ('VERDE', 'S2')
"""

from .motor import NUCLEO, PRESUPUESTO_VACIO, decidir
from .tipos import (
    Accion,
    Clase,
    Criterio,
    Decision,
    ErrorDeInvocacion,
    Observacion,
    Presupuesto,
    Regimen,
    Trivalor,
)

__all__ = [
    "decidir",
    "NUCLEO",
    "PRESUPUESTO_VACIO",
    "Accion",
    "Clase",
    "Criterio",
    "Decision",
    "ErrorDeInvocacion",
    "Observacion",
    "Presupuesto",
    "Regimen",
    "Trivalor",
]
