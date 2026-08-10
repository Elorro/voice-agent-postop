#!/usr/bin/env python3
"""Reejecuta cada decisión anotada en el registro y exige que dé lo mismo.

    python3 scripts/reejecutar_decisiones.py [ruta/turnos.jsonl]

Qué convierte esto en una verificación y no en una afirmación
-------------------------------------------------------------
Cada línea del registro lleva la ENTRADA y la SALIDA de `politica.decidir`. Este
script recorre el archivo, vuelve a llamar a la política con la entrada anotada,
y compara campo a campo con la salida anotada. Si el agente hubiera decidido con
otra cosa —un atajo, una regla suelta en el orquestador, un LLM— la salida
registrada dejaría de reproducirse desde la política y esto saldría distinto de
cero.

No es un test de la política (esa tiene su propia batería de 143 casos): es un
test de que **lo que corrió en producción fue la política**.

Códigos de salida:  0 todo coincide · 1 hay discrepancias · 2 no pudo ejecutarse.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

# Este script y los tests son los dos únicos sitios fuera de
# `app/dialogo/orquestador.py` que importan la política, y por la misma razón:
# son las herramientas que la verifican. Una herramienta de verificación que no
# pudiera importar lo que verifica no serviría de nada.
import politica  # noqa: E402
from app.config import obtener_config  # noqa: E402

CAMPOS = (
    "accion",
    "senal_a_indagar",
    "clase",
    "criterio",
    "regimen",
    "n_total",
    "banderas",
    "compuerta",
    "disparadores",
    "marcas",
)


def salida_a_json(decision: politica.Decision) -> dict[str, Any]:
    """Misma forma que anota `app/dialogo/orquestador.py`."""
    return {
        "accion": decision.accion.name,
        "senal_a_indagar": decision.senal_a_indagar,
        "clase": decision.clase.name if decision.clase else None,
        "criterio": decision.criterio.name if decision.criterio else None,
        "regimen": decision.regimen.name,
        "n_total": decision.n_total,
        "banderas": {k: v.name for k, v in decision.banderas.items()},
        "compuerta": decision.compuerta.name,
        "disparadores": list(decision.disparadores),
        "marcas": list(decision.marcas),
    }


def reejecutar(linea: dict[str, Any]) -> tuple[bool, list[str]]:
    bloque = linea["politica"]
    entrada = bloque["entrada"]
    presupuesto_json = bloque.get("presupuesto") or {}
    esperada = bloque["salida"]

    obs = politica.Observacion(
        dia_postop=entrada.get("dia_postop"),
        dolor_nrs=entrada.get("dolor_nrs"),
        fiebre_c=entrada.get("fiebre_c"),
        herida=entrada.get("herida"),
        movilidad=entrada.get("movilidad"),
        apetito=entrada.get("apetito"),
        sueno=entrada.get("sueno"),
    )
    presupuesto = politica.Presupuesto(
        preguntas_por_senal=presupuesto_json.get("preguntas_por_senal", {}),
        preguntas_totales=presupuesto_json.get("preguntas_totales", 0),
    )
    # Los topes también se leen del registro: son `[ESPECULACIÓN]` pendientes de
    # calibración, así que un cambio de valor no debe hacer irreproducible una
    # decisión que se tomó con los de entonces.
    obtenida = salida_a_json(
        politica.decidir(
            obs,
            presupuesto,
            tope_por_senal=presupuesto_json.get(
                "tope_por_senal", politica.parametros.TOPE_POR_SENAL
            ),
            tope_global=presupuesto_json.get(
                "tope_global", politica.parametros.TOPE_GLOBAL
            ),
        )
    )

    diferencias = [
        f"{campo}: registrado {esperada.get(campo)!r} != reejecutado {obtenida[campo]!r}"
        for campo in CAMPOS
        if campo in esperada and esperada.get(campo) != obtenida[campo]
    ]
    return not diferencias, diferencias


def main(argv: list[str]) -> int:
    if len(argv) > 2:
        print(__doc__)
        return 2
    ruta = Path(argv[1]) if len(argv) == 2 else obtener_config().ruta_turnos_jsonl
    if not ruta.is_file():
        print(f"error: no existe el registro {ruta}", file=sys.stderr)
        return 2

    revisadas = 0
    fallidas = 0
    sin_decision = 0
    ilegibles = 0

    for numero, texto in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
        texto = texto.strip()
        if not texto:
            continue
        try:
            linea = json.loads(texto)
        except json.JSONDecodeError:
            ilegibles += 1
            continue
        if linea.get("tipo") not in ("turno", "apertura"):
            continue
        bloque = linea.get("politica") or {}
        if not bloque.get("salida"):
            # Turno en el que la política rechazó la entrada (§8.2). No hay
            # decisión que reproducir; se cuenta y se dice.
            sin_decision += 1
            continue

        revisadas += 1
        try:
            igual, diferencias = reejecutar(linea)
        except Exception as exc:  # noqa: BLE001
            fallidas += 1
            print(f"línea {numero}: la reejecución lanzó {type(exc).__name__}: {exc}")
            continue
        if not igual:
            fallidas += 1
            print(
                f"línea {numero} (llamada {linea.get('llamada_id')}, "
                f"turno {linea.get('turno_idx')}):"
            )
            for diferencia in diferencias:
                print(f"    {diferencia}")

    print(f"registro: {ruta}")
    print(f"decisiones reejecutadas: {revisadas}")
    if sin_decision:
        print(f"turnos sin decisión (política rechazó la entrada): {sin_decision}")
    if ilegibles:
        print(f"líneas ilegibles saltadas: {ilegibles}")

    if fallidas:
        print(f"DISCREPANCIAS: {fallidas} de {revisadas}")
        return 1
    if revisadas == 0:
        print("no había ninguna decisión que reejecutar")
        return 0
    print("OK: cada decisión registrada se reproduce llamando a politica.decidir")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
