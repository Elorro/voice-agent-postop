"""Estado de las llamadas en curso: un diccionario en proceso.

`llamada_id -> Llamada`. Sin base de datos y sin Redis, y no por simplificar:
hay **un servicio, un proceso, un worker** (ver `docker/entrypoint.sh`), así que
un diccionario protegido por un candado es exactamente el alcance del problema.
Meter un almacén externo aquí agregaría una dependencia de red al camino
crítico del turno para resolver una concurrencia que no existe.

La contrapartida está declarada: si el proceso muere, las llamadas **en curso**
se pierden. Lo que no se pierde es lo ya ocurrido — cada turno se anota en
`turnos.jsonl` en el momento en que sucede— y al cerrar, la llamada completa se
persiste a disco. El estado en memoria es el borrador; el registro es el acta.

Este módulo no importa `politica`: guarda las señales como un diccionario de
valores planos. Quien las convierte en `Observacion` es el orquestador, que es
el único punto del árbol que conoce el módulo de decisión.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = ["Llamada", "Almacen", "ahora_iso"]


def ahora_iso() -> str:
    """Instante en ISO-8601 con zona. El reloj del servidor solo sirve para
    fechar eventos: la latencia que se reporta la mide el navegador, con su
    propio reloj, y viaja como DELTA justamente para no mezclar los dos."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


@dataclass
class Llamada:
    """Una llamada viva. Mutable a propósito: es el borrador del turno."""

    id: str
    paciente_id: str | None
    dia_postop: int | None
    creada_ts: str
    senales: dict[str, Any]
    preguntas_por_senal: dict[str, int] = field(default_factory=dict)
    preguntas_totales: int = 0
    turno_idx: int = 0
    senal_pendiente: str | None = None
    abierta: bool = True
    clase: str | None = None
    criterio: str | None = None
    marcas: tuple[str, ...] = ()
    historial: list[dict[str, Any]] = field(default_factory=list)
    preguntas_del_paciente: list[str] = field(default_factory=list)
    cierre_anotado: bool = False

    def cobrar_pregunta(self, senal: str) -> None:
        """Contabilidad de HD7: el módulo de política LEE el presupuesto, el
        llamador lo COBRA. Y se cobra **al emitir la pregunta**, no al recibir
        la respuesta: si se cobrara al recibirla, un paciente que calla no
        consumiría presupuesto y la indagación no terminaría nunca."""
        self.preguntas_por_senal[senal] = self.preguntas_por_senal.get(senal, 0) + 1
        self.preguntas_totales += 1

    def gastadas(self, senal: str) -> int:
        return self.preguntas_por_senal.get(senal, 0)

    def a_json(self) -> dict[str, Any]:
        return {
            "llamada_id": self.id,
            "paciente_id": self.paciente_id,
            "dia_postop": self.dia_postop,
            "creada_ts": self.creada_ts,
            "senales": dict(self.senales),
            "presupuesto": {
                "preguntas_por_senal": dict(self.preguntas_por_senal),
                "preguntas_totales": self.preguntas_totales,
            },
            "turnos": self.turno_idx,
            "abierta": self.abierta,
            "clase": self.clase,
            "criterio": self.criterio,
            "marcas": list(self.marcas),
            "historial": self.historial,
            "preguntas_del_paciente": self.preguntas_del_paciente,
        }


class Almacen:
    """Diccionario de llamadas, protegido, con persistencia al cerrar."""

    def __init__(self) -> None:
        self._llamadas: dict[str, Llamada] = {}
        self._candado = threading.RLock()

    def crear(
        self,
        senales_iniciales: dict[str, Any],
        *,
        paciente_id: str | None = None,
        dia_postop: int | None = None,
    ) -> Llamada:
        llamada = Llamada(
            id=uuid.uuid4().hex[:12],
            paciente_id=paciente_id,
            dia_postop=dia_postop,
            creada_ts=ahora_iso(),
            senales=dict(senales_iniciales),
        )
        with self._candado:
            self._llamadas[llamada.id] = llamada
        return llamada

    def obtener(self, llamada_id: str) -> Llamada | None:
        with self._candado:
            return self._llamadas.get(llamada_id)

    def activas(self) -> list[Llamada]:
        with self._candado:
            return [ll for ll in self._llamadas.values() if ll.abierta]

    def persistir(self, llamada: Llamada, directorio: Path) -> Path | None:
        """Vuelca la llamada cerrada a `datos/llamadas/{id}.json`.

        Publicación atómica (`os.replace` vía `Path.replace`): un corte deja el
        archivo anterior o el nuevo, nunca uno a medias.
        """
        try:
            directorio.mkdir(parents=True, exist_ok=True)
            destino = directorio / f"{llamada.id}.json"
            temporal = destino.with_suffix(".json.tmp")
            temporal.write_text(
                json.dumps(llamada.a_json(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporal.replace(destino)
            return destino
        except OSError as exc:  # noqa: BLE001 - se reporta, no propaga
            import logging

            logging.getLogger(__name__).error(
                "no se pudo persistir la llamada %s: %s", llamada.id, exc
            )
            return None
