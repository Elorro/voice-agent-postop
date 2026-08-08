"""Auditoría de la Fase 1 — verificación de los [HECHO] declarados en
politica_decision.docx y protocolo_validacion.docx contra el dev set de 160 casos.

Secciones:
    A1  Hechos declarados que se confirman
    A2  D1 — [HECHO] falso: 'apetito/sueño muy alterados => cero verdes'
    A3  D2/D3 — cobertura y redundancia real del Nivel 1
    A4  D3 — ¿la bandera dolor>=7 es portante?
    A5  D4 — independencia: los 12 rojos son 6 pacientes x 2 días
    A6  D5 — colisión amarillo/rojo en fiebre (celda c3)
    A7  D6 — sensibilidad del umbral de fiebre y leave-one-patient-out
    A8  Hallazgo constructivo — conjunción apetito ∧ sueño
    A9  Matriz de confusión de la política literal sobre vector completo
    A10 Corte del enrutador temporal — costo de cada dirección de error

Uso (desde la raíz del repo):
    python3 scripts/auditoria_fase1.py
    DATASET_DIR=/ruta/a/dataset python3 scripts/auditoria_fase1.py

Determinista, idempotente, sin red. Falla ruidoso si el join no cierra.
"""
from __future__ import annotations

import os
import sys
from math import sqrt
from pathlib import Path

import pandas as pd

DATASET_DIR = Path(os.environ.get("DATASET_DIR", "dataset"))
TARDIO: tuple[int, ...] = (7, 14)
COLS = ["caso_id", "dia_postop", "dolor_nrs", "fiebre_c", "herida",
        "movilidad", "apetito", "sueno"]
ORDEN = ["verde", "amarillo", "rojo"]


# --------------------------------------------------------------------------- #
# Carga
# --------------------------------------------------------------------------- #
def cargar(base: Path = DATASET_DIR) -> pd.DataFrame:
    """Join canónico trayectorias × label. caso_id = 'caso_' + trayectoria_id."""
    tray = base / "trayectorias_postop_silver.xlsx"
    conv = base / "dataset_final.xlsx"
    for p in (tray, conv):
        if not p.exists():
            sys.exit(f"ERROR: no encuentro {p}. Define DATASET_DIR.")

    t = pd.read_excel(tray, sheet_name="result")
    d = pd.read_excel(conv, sheet_name="result")

    lab_por_caso = d.groupby("caso_id")["label_ground_truth"].nunique()
    assert (lab_por_caso == 1).all(), "label_ground_truth no es constante por caso_id"
    lab = d.groupby("caso_id")["label_ground_truth"].first().rename("label")

    t["caso_id"] = "caso_" + t["trayectoria_id"].astype(str)
    m = t.merge(lab, on="caso_id", how="left")
    assert m["label"].notna().all(), "join incompleto: hay casos sin label"
    assert len(m) == 160, f"se esperaban 160 casos, hay {len(m)}"

    m["regimen"] = m["dia_postop"].map(lambda x: "tardio" if x in TARDIO else "temprano")
    m["paciente"] = m["trayectoria_id"].str.rsplit("_", n=1).str[0]
    return m


# --------------------------------------------------------------------------- #
# Política tal como está escrita en politica_decision.docx
# --------------------------------------------------------------------------- #
def banderas_nivel1(r: pd.Series, *, con_dolor: bool = True,
                    umbral_fiebre_tardio: float = 38.0) -> dict[str, bool]:
    """Nivel 1, §3.2. umbral_fiebre_tardio se expone para el análisis de sensibilidad."""
    th = umbral_fiebre_tardio if r.regimen == "tardio" else 38.0
    return {
        "purulenta": r.herida == "secrecion_purulenta",
        "movilidad": r.movilidad == "incapacitante_nueva",
        "fiebre": r.fiebre_c >= th,
        "dolor": con_dolor and r.regimen == "tardio" and r.dolor_nrs >= 7,
    }


def senales_nivel2(r: pd.Series) -> list[str]:
    """Nivel 2, §3.3. OJO: la regla de conteo del documento solo está
    especificada para régimen TARDÍO; la rama temprana es una extensión
    del auditor, no de la política. Ver defecto D7."""
    s: list[str] = []
    if r.regimen == "tardio":
        if r.dolor_nrs >= 5:
            s.append("dolor>=5")
        if r.fiebre_c >= 37.5:
            s.append("fiebre>=37.5")
        if r.herida == "eritema_leve":
            s.append("eritema")
    else:
        if r.fiebre_c >= 37.5:
            s.append("fiebre>=37.5")
        if r.dolor_nrs >= 5:
            s.append("dolor>=5[EXTENSION]")
    if r.apetito == "muy_disminuido":
        s.append("apetito")
    if r.sueno == "muy_alterado":
        s.append("sueno")
    return s


def clasificar(r: pd.Series, **kw) -> str:
    """Vector COMPLETO: cota superior (sin evasión ni error de extracción).
    Con evidencia completa, '>=2 señales -> indagar' resuelve a S3 -> amarillo."""
    if any(banderas_nivel1(r, **kw).values()):
        return "rojo"
    return "verde" if not senales_nivel2(r) else "amarillo"


def clasificar_forzando(r: pd.Series, regimen: str) -> str:
    """Reclasifica el caso como si el enrutador lo hubiera mandado al régimen dado.

    Es el instrumento del análisis A10: los días 4, 5 y 6 no existen en el dev set,
    así que el costo de mover el corte temporal no se puede medir directamente. Se
    acota usando el día 3 como proxy de 'temprano tratado como tardío' y el día 7
    como proxy de 'tardío tratado como temprano'.
    """
    rr = r.copy()
    rr["regimen"] = regimen
    return clasificar(rr)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p, d = k / n, 1 + z**2 / n
    c = (p + z**2 / (2 * n)) / d
    h = z * sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def _h(t: str) -> None:
    print(f"\n{'=' * 72}\n{t}\n{'=' * 72}")


# --------------------------------------------------------------------------- #
def main() -> None:
    m = cargar()

    _h("A1 · HECHOS declarados que se CONFIRMAN")
    print(f"join 160/160 sin pérdidas ............ {len(m) == 160}")
    print(f"desbalance 123/25/12 ................. {m.label.value_counts().to_dict()}")
    for col, val in [("herida", "secrecion_purulenta"), ("movilidad", "incapacitante_nueva")]:
        sub = m[m[col] == val]
        print(f"{col}={val:20s} n={len(sub)} labels={sub.label.value_counts().to_dict()}")
    amb = m[(m.label == "amarillo") & (m.dolor_nrs < 5) & (m.fiebre_c < 37.5)]
    print(f"'8 ambiguos de Q4' ................... n={len(amb)} "
          f"(eritema_leve en {int((amb.herida == 'eritema_leve').sum())}/{len(amb)})")

    _h("A2 · D1 — [HECHO] FALSO: 'apetito/sueño muy alterados => cero verdes'")
    for col, val in [("apetito", "muy_disminuido"), ("sueno", "muy_alterado")]:
        sub = m[m[col] == val]
        print(f"\n{col}={val}: n={len(sub)} labels={sub.label.value_counts().to_dict()}")
        print(sub[sub.label == "verde"][COLS].to_string(index=False))

    _h("A3 · D2/D3 — cobertura y redundancia real del Nivel 1")
    fl = m.apply(lambda r: pd.Series(banderas_nivel1(r)), axis=1)
    rojos = fl[m.label == "rojo"]
    print(f"falsos positivos de Nivel 1 sobre 148 no-rojos: "
          f"{int(fl[m.label != 'rojo'].any(axis=1).sum())}")
    print(f"rojos sin ninguna bandera: {int((~rojos.any(axis=1)).sum())}\n")
    for f in fl.columns:
        unico = rojos[rojos[f] & ~rojos[[c for c in fl.columns if c != f]].any(axis=1)]
        print(f"  {f:10s}: captura {int(rojos[f].sum()):2d}/12 rojos | "
              f"única que dispara en {len(unico)}")
    print(f"\ndominio real de dolor_nrs: {sorted(m.dolor_nrs.unique())}  <- no existen 7 ni 8")

    _h("A4 · D3 — ¿la bandera dolor>=7 es portante?")
    for con in (True, False):
        p = m.apply(lambda r: clasificar(r, con_dolor=con), axis=1)
        r = m.label == "rojo"
        print(f"con_bandera_dolor={con!s:5s} -> recall_rojo={(p[r] == 'rojo').mean():.3f}  "
              f"c3(rojo->amarillo)={int((r & (p == 'amarillo')).sum())}")

    _h("A5 · D4 — independencia: los 12 rojos son 6 pacientes x 2 días")
    for lb in ORDEN:
        s = m[m.label == lb]
        print(f"{lb:9s}: {len(s):3d} casos <- {s.paciente.nunique():2d} pacientes")
    lo, hi = wilson(12, 12); print(f"\nWilson95 recall=1.0 con n=12 casos ...... [{lo:.3f}, {hi:.3f}]")
    lo, hi = wilson(6, 6);   print(f"Wilson95 recall=1.0 con n= 6 pacientes ... [{lo:.3f}, {hi:.3f}]")

    _h("A6 · D5 — colisión amarillo/rojo en fiebre (la celda c3), día 7")
    d7 = m[(m.dia_postop == 7) & (m.fiebre_c.between(37.8, 37.99))]
    print(d7[COLS + ["label"]].to_string(index=False))

    _h("A7 · D6 — sensibilidad del umbral de fiebre en régimen TARDÍO")
    t = m[m.regimen == "tardio"]
    print(f"{'umbral':>7} {'rojos':>8} {'amarillos':>10} {'verdes':>8}")
    for th in (37.5, 37.6, 37.7, 37.8, 37.9, 38.0, 38.1):
        h = t.fiebre_c >= th
        print(f"{th:>7} {int((h & (t.label == 'rojo')).sum()):>6}/12 "
              f"{int((h & (t.label == 'amarillo')).sum()):>8}/10 "
              f"{int((h & (t.label == 'verde')).sum()):>6}/58")
    print("\nleave-one-patient-out sobre los 6 pacientes rojos:")
    for p_out in sorted(m[m.label == "rojo"].paciente.unique()):
        s = m[(m.paciente != p_out) & (m.regimen == "tardio")]
        print(f"  sin {p_out}: verde_max={s[s.label == 'verde'].fiebre_c.max():.1f} "
              f"rojo_min={s[s.label == 'rojo'].fiebre_c.min():.1f}")

    _h("A8 · HALLAZGO CONSTRUCTIVO — conjunción apetito ∧ sueño")
    c = m[(m.apetito == "muy_disminuido") & (m.sueno == "muy_alterado")]
    print(f"n={len(c)}  labels={c.label.value_counts().to_dict()}")
    print(f"verdes en la conjunción: {int((c.label == 'verde').sum())}  "
          f"| rojos cubiertos: {int((c.label == 'rojo').sum())}/12")

    _h("A9 · Matriz de confusión — política literal, vector completo (cota superior)")
    m["pred"] = m.apply(clasificar, axis=1)
    print(pd.crosstab(m.pred, m.label).reindex(index=ORDEN, columns=ORDEN, fill_value=0).to_string())
    print(f"\nrecall_rojo={(m[m.label == 'rojo'].pred == 'rojo').mean():.3f}  "
          f"c1(am->ve)={int(((m.label == 'amarillo') & (m.pred == 'verde')).sum())}  "
          f"c3(ro->am)={int(((m.label == 'rojo') & (m.pred == 'amarillo')).sum())}  "
          f"c2(ve->am)={int(((m.label == 'verde') & (m.pred == 'amarillo')).sum())}/123")
    for reg in ("temprano", "tardio"):
        s = m[m.regimen == reg]
        print(f"\n-- {reg} (n={len(s)}) --")
        print(pd.crosstab(s.pred, s.label).reindex(index=ORDEN, columns=ORDEN, fill_value=0).to_string())

    _h("A10 · Corte del enrutador temporal — costo de cada dirección de error")
    print("Los días 4, 5 y 6 NO existen en el dev set: el corte no es decidible por datos.")
    print("Se acota el costo de cada dirección con los días adyacentes como proxy.\n")

    print("--- Dirección SEGURA: día temprano enrutado a TARDÍO (sobre-escalar) ---")
    for d in (1, 3):
        s = m[m.dia_postop == d]
        pt = s.apply(lambda r: clasificar_forzando(r, "temprano"), axis=1)
        pT = s.apply(lambda r: clasificar_forzando(r, "tardio"), axis=1)
        v = s.label == "verde"
        c2 = int((v & (pt == "verde") & (pT == "amarillo")).sum())
        c4 = int(((pT == "rojo") & (pt != "rojo")).sum())
        print(f"  día {d:2d} (n={len(s)}, {int(v.sum())} verdes): "
              f"verde->amarillo (c2) = {c2}/{int(v.sum())} ({c2 / v.sum():.1%})  |  "
              f"pasan a ROJO (c4) = {c4}")

    print("\n--- Dirección PELIGROSA: día tardío enrutado a TEMPRANO (sub-escalar) ---")
    for d in (7, 14):
        s = m[m.dia_postop == d]
        pT = s.apply(lambda r: clasificar_forzando(r, "tardio"), axis=1)
        pt = s.apply(lambda r: clasificar_forzando(r, "temprano"), axis=1)
        rj = s.label == "rojo"
        print(f"  día {d:2d} ({int(rj.sum())} rojos): recall_rojo tardío={(pT[rj] == 'rojo').mean():.3f} "
              f"-> temprano={(pt[rj] == 'rojo').mean():.3f}")
        perdidos = s[rj & (pT == "rojo") & (pt != "rojo")]
        for _, p in perdidos.iterrows():
            print(f"    ROJO PERDIDO -> {pt[p.name]}: {p.caso_id} "
                  f"(dolor={p.dolor_nrs}, fiebre={p.fiebre_c}, herida={p.herida})")

    d3 = m[m.dia_postop == 3]
    pt3 = d3.apply(lambda r: clasificar_forzando(r, "temprano"), axis=1)
    pT3 = d3.apply(lambda r: clasificar_forzando(r, "tardio"), axis=1)
    sob = d3[(d3.label == "verde") & (pt3 == "verde") & (pT3 == "amarillo")]
    print(f"\n--- Costo de adelantar el corte al día 4 (proxy = día 3) ---")
    print(f"{len(sob)} de {int((d3.label == 'verde').sum())} verdes se sobre-clasificarían. "
          f"Señal que los dispara:")
    print(sob[["caso_id", "dolor_nrs", "fiebre_c", "herida", "apetito", "sueno"]].to_string(index=False))
    print("\nVEREDICTO: el costo de adelantar el corte es puro c2 y se concentra en eritema_leve;")
    print("el costo de atrasarlo es c3 sobre caso_tray_pac_42_00017_7. Corte fijado en día 4.")


if __name__ == "__main__":
    main()
