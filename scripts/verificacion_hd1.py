"""Verificación de HD1 — salida terminal de la política sobre el dev set (160 casos).

Reimplementación INDEPENDIENTE de `docs/diseno/parametros_politica.md`, escrita
desde el texto de la spec y sin mirar `scripts/auditoria_fase1.py` ni el módulo de
Fase 2 (que todavía no existe). Ese aislamiento es el punto: si el módulo de 2.1 y
su oráculo salen del mismo código, el test no prueba nada.

El módulo de 2.1 debe REPRODUCIR estos números, no importar este archivo.

Qué verifica:
    V1  Criterio de aceptación de 2.1 sobre la salida terminal.
    V2  HD1 — desglose del cierre forzado (§7.4) y prueba de que la salida
        terminal está definida para los 160 casos.
    V3  Invariante de consistencia §4↔§5: compuerta 1.5 activa => n_total >= 1.
    V4  Evidencia del hueco: §7.1 literal deja 19 casos en REPREGUNTAR con
        vector completo.

Uso (desde la raíz del repo):
    DATASET_DIR=/home/luis/Projects/ParticipantArtifacts/dataset python3 scripts/verificacion_hd1.py

Determinista, idempotente, sin red. Sale con código 1 si algún número esperado
no se reproduce.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Literal, NamedTuple

import pandas as pd

DATASET_DIR = Path(os.environ.get("DATASET_DIR", "dataset"))

# --- Parámetros: copiados de parametros_politica.md, único lugar donde viven --- #
CORTE_ENRUTADOR = 4
UMBRAL_FIEBRE_FRANCA = 38.0
UMBRAL_DOLOR_SEVERO = {"tardio": 7, "temprano": 9}   # §3, umbral por régimen
G_FIEBRE = 37.8
G_DOLOR = 5
S_FIEBRE = 37.5
S_DOLOR = 5
CONTEO_TARDIO = 1
CONTEO_TEMPRANO = 2

Regimen = Literal["temprano", "tardio"]
Clase = Literal["verde", "amarillo", "rojo"]
Criterio = Literal["S1", "S2", "S3", "CIERRE_FORZADO"]

ESPERADO = {
    "recall_rojo": 1.000,
    "C_FN": 0,
    "c1": 0,
    "c3": 0,
    "c2": 11,
    "c2_temprano": 4,
    "c2_tardio": 7,
    "cierre_forzado": 19,
    "repreguntar_literal": 19,
}


class Salida(NamedTuple):
    clase: Clase
    criterio: Criterio
    regimen: Regimen
    n_total: int


# --------------------------------------------------------------------------- #
# Niveles de la política (§2 - §5, §7)
# --------------------------------------------------------------------------- #
def nivel_0(dia_postop: int) -> Regimen:
    """§2. Vector completo: dia_postop siempre presente en el dev set."""
    if not isinstance(dia_postop, (int,)) or bool(dia_postop < 0):
        raise ValueError(f"dia_postop invalido: {dia_postop!r}")
    return "tardio" if dia_postop >= CORTE_ENRUTADOR else "temprano"


def nivel_1(r: pd.Series | object, regimen: Regimen) -> dict[str, bool]:
    """§3. Cuatro banderas rojas. Vector completo => nunca DESCONOCIDO."""
    return {
        "purulenta": r.herida == "secrecion_purulenta",
        "movilidad_incapacitante": r.movilidad == "incapacitante_nueva",
        "fiebre_franca": r.fiebre_c >= UMBRAL_FIEBRE_FRANCA,
        "dolor_severo": r.dolor_nrs >= UMBRAL_DOLOR_SEVERO[regimen],
    }


def nivel_1_5(r: pd.Series | object, regimen: Regimen) -> dict[str, bool]:
    """§4. Compuerta de no-verde. SOLO_TARDIO."""
    if regimen != "tardio":
        return {}
    return {
        "g_fiebre": r.fiebre_c >= G_FIEBRE,
        "g_dolor": r.dolor_nrs >= G_DOLOR,
        "g_constitucional": (r.apetito == "muy_disminuido") and (r.sueno == "muy_alterado"),
    }


def nivel_2(r: pd.Series | object, regimen: Regimen) -> int:
    """§5. Conteo de señales blandas. s_dolor excluido de la base (H3)."""
    base = (
        r.fiebre_c >= S_FIEBRE,
        r.herida == "eritema_leve",
        r.apetito == "muy_disminuido",
        r.sueno == "muy_alterado",
    )
    n_base = sum(base)
    if regimen == "tardio":
        s_dolor = r.dolor_nrs >= S_DOLOR
    else:
        s_dolor = (r.dolor_nrs >= S_DOLOR) and (n_base >= 1)
    return n_base + int(s_dolor)


def agregacion(n_total: int, regimen: Regimen) -> Clase:
    """§5.2. Siempre produce una clase candidata."""
    umbral = CONTEO_TARDIO if regimen == "tardio" else CONTEO_TEMPRANO
    return "amarillo" if n_total >= umbral else "verde"


# --------------------------------------------------------------------------- #
# Salida terminal (§7.1 + §7.4)
# --------------------------------------------------------------------------- #
def terminal(r: pd.Series | object) -> Salida:
    regimen = nivel_0(int(r.dia_postop))
    banderas = nivel_1(r, regimen)
    if any(banderas.values()):                                   # S1
        return Salida("rojo", "S1", regimen, -1)

    compuerta = any(nivel_1_5(r, regimen).values())
    n_total = nivel_2(r, regimen)

    if (not compuerta) and n_total == 0:                         # S2
        return Salida("verde", "S2", regimen, n_total)

    umbral = CONTEO_TARDIO if regimen == "tardio" else CONTEO_TEMPRANO
    if n_total >= umbral:                                        # S3
        return Salida("amarillo", "S3", regimen, n_total)

    # §7.4 — cierre forzado: vector completo, ninguna S se cumple.
    candidata = agregacion(n_total, regimen)
    # Filtro: prohibiciones, no clases. Paso 1 (bandera DESCONOCIDO -> rojo) es
    # inalcanzable con vector completo; se omite aquí y se implementa en el modulo.
    if compuerta and candidata == "verde":                       # §4.1 punto 1
        candidata = "amarillo"
    return Salida(candidata, "CIERRE_FORZADO", regimen, n_total)


def suficiencia_literal(r: pd.Series | object) -> str:
    """§7.1 tal como está escrito HOY, sin §7.4. Documenta el hueco HD1."""
    s = terminal(r)
    return "REPREGUNTAR" if s.criterio == "CIERRE_FORZADO" else s.criterio


# --------------------------------------------------------------------------- #
# Carga
# --------------------------------------------------------------------------- #
def cargar(base: Path = DATASET_DIR) -> pd.DataFrame:
    """Join canónico. caso_id = 'caso_' + trayectoria_id."""
    tray, conv = base / "trayectorias_postop_silver.xlsx", base / "dataset_final.xlsx"
    for p in (tray, conv):
        if not p.exists():
            sys.exit(f"ERROR: no encuentro {p}. Define DATASET_DIR.")

    t = pd.read_excel(tray, sheet_name="result")
    d = pd.read_excel(conv, sheet_name="result")

    assert (d.groupby("caso_id")["label_ground_truth"].nunique() == 1).all(), \
        "label_ground_truth no es constante por caso_id"
    lab = d.groupby("caso_id")["label_ground_truth"].first().rename("label")

    t["caso_id"] = "caso_" + t["trayectoria_id"].astype(str)
    m = t.merge(lab, on="caso_id", how="left")
    assert m["label"].notna().all(), "join incompleto: hay casos sin label"
    assert len(m) == 160, f"se esperaban 160 casos, hay {len(m)}"
    assert m[["dia_postop", "dolor_nrs", "fiebre_c", "herida", "movilidad",
              "apetito", "sueno"]].notna().all().all(), "hay nulos en el nucleo"
    return m


# --------------------------------------------------------------------------- #
def main() -> int:
    m = cargar()
    f = pd.DataFrame([
        {"caso_id": r.caso_id, "real": r.label, **terminal(r)._asdict(),
         "literal": suficiencia_literal(r)}
        for r in m.itertuples()
    ])
    fallos: list[str] = []

    def check(nombre: str, obtenido: float) -> None:
        esperado = ESPERADO[nombre]
        ok = abs(obtenido - esperado) < 1e-9
        print(f"    {'OK ' if ok else 'FALLA'}  {nombre:20s} = {obtenido}"
              f"{'' if ok else f'   (esperado {esperado})'}")
        if not ok:
            fallos.append(nombre)

    print("=" * 72)
    print("V1 — Criterio de aceptación de 2.1 sobre la SALIDA TERMINAL")
    print("=" * 72)
    print(pd.crosstab(f["clase"], f["real"])
          .reindex(index=["verde", "amarillo", "rojo"],
                   columns=["verde", "amarillo", "rojo"]).fillna(0).astype(int)
          .to_string(), "\n")
    celdas = {"C_FN": ("verde", "rojo"), "c1": ("verde", "amarillo"),
              "c3": ("amarillo", "rojo"), "c2": ("amarillo", "verde")}
    check("recall_rojo", round((f[f.real == "rojo"]["clase"] == "rojo").mean(), 3))
    for nombre, (p, y) in celdas.items():
        check(nombre, len(f[(f.clase == p) & (f.real == y)]))
    c2 = f[(f.clase == "amarillo") & (f.real == "verde")]
    check("c2_temprano", len(c2[c2.regimen == "temprano"]))
    check("c2_tardio", len(c2[c2.regimen == "tardio"]))

    print("\n" + "=" * 72)
    print("V2 — HD1: cierre forzado (§7.4)")
    print("=" * 72)
    print("    criterio de cierre:", f["criterio"].value_counts().to_dict())
    check("cierre_forzado", len(f[f.criterio == "CIERRE_FORZADO"]))
    cf = f[f.criterio == "CIERRE_FORZADO"]
    print("\n" + cf.groupby(["regimen", "n_total", "clase", "real"]).size().to_string())
    sin_clase = f[~f["clase"].isin(("verde", "amarillo", "rojo"))]
    print(f"\n    {'OK ' if sin_clase.empty else 'FALLA'}  "
          f"salida terminal definida para los 160 casos "
          f"(sin clase: {len(sin_clase)})")
    if not sin_clase.empty:
        fallos.append("salida_terminal_indefinida")

    print("\n" + "=" * 72)
    print("V3 — Invariante §4↔§5: compuerta 1.5 activa  =>  n_total >= 1")
    print("=" * 72)
    contraejemplos = 0
    for r in m.itertuples():
        reg = nivel_0(int(r.dia_postop))
        if reg != "tardio" or any(nivel_1(r, reg).values()):
            continue
        if any(nivel_1_5(r, reg).values()) and nivel_2(r, reg) == 0:
            contraejemplos += 1
            print(f"    contraejemplo: {r.caso_id}")
    print(f"    {'OK ' if contraejemplos == 0 else 'FALLA'}  "
          f"contraejemplos = {contraejemplos}")
    print(f"    condiciones que lo sostienen: G_FIEBRE({G_FIEBRE}) >= S_FIEBRE({S_FIEBRE}) "
          f"-> {G_FIEBRE >= S_FIEBRE} | G_DOLOR({G_DOLOR}) >= S_DOLOR({S_DOLOR}) "
          f"-> {G_DOLOR >= S_DOLOR}")
    if contraejemplos:
        fallos.append("invariante_compuerta")

    print("\n" + "=" * 72)
    print("V4 — Evidencia del hueco: §7.1 literal, sin §7.4")
    print("=" * 72)
    print("   ", f["literal"].value_counts().to_dict())
    check("repreguntar_literal", len(f[f.literal == "REPREGUNTAR"]))

    print("\n" + "=" * 72)
    if fallos:
        print(f"RESULTADO: FALLA — {len(fallos)} verificacion(es): {', '.join(fallos)}")
        return 1
    print("RESULTADO: todas las verificaciones pasan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
