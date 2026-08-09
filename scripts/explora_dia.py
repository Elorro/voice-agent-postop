#!/usr/bin/env python3
"""
Exploración D — ¿dia_postop modula los umbrales señal->criticidad?
Barato, sin efectos secundarios. Reutiliza el join ya validado.

Uso (desde dentro de dataset/):
    python explora_dia.py .
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

SHEET = "result"
F_DATASET = "dataset_final.xlsx"
F_TRAYECT = "trayectorias_postop_silver.xlsx"

SENIALES_NUM = ["dolor_nrs", "fiebre_c"]
SENIALES_CAT = ["movilidad", "herida", "apetito", "sueno"]
COL_LABEL = "label_ground_truth"
COL_CASO = "caso_id"
COL_TRAYID = "trayectoria_id"
COL_DIA = "dia_postop"
DIAS = [1, 3, 7, 14]
ORDEN = ["verde", "amarillo", "rojo"]
SEP = "=" * 72


def _sec(t: str) -> None:
    print(f"\n{SEP}\n{t}\n{SEP}")


def _load(base: Path, f: str) -> pd.DataFrame:
    return pd.read_excel(base / f, sheet_name=SHEET, engine="openpyxl")


def _merged(base: Path) -> pd.DataFrame:
    ds = _load(base, F_DATASET)
    tr = _load(base, F_TRAYECT)
    # label por caso (constante, ya verificado)
    lab = ds.groupby(COL_CASO)[COL_LABEL].first().reset_index()
    tr = tr.copy()
    tr["caso_id_derivado"] = "caso_" + tr[COL_TRAYID].astype(str)
    m = tr.merge(lab, left_on="caso_id_derivado", right_on=COL_CASO, how="inner")
    # el dia_postop de trayectorias es el del caso (1 fila por caso)
    print(f"[merge] {len(m)} casos  |  dias presentes: {sorted(m[COL_DIA].unique())}")
    return m


def d1_reparto(m: pd.DataFrame) -> None:
    _sec("D1. REPARTO casos por dia_postop × clase")
    ct = pd.crosstab(m[COL_DIA], m[COL_LABEL]).reindex(columns=ORDEN, fill_value=0)
    print(ct.to_string())
    print("\nceldas con 0 casos (no se puede estimar umbral ahí):")
    for dia in ct.index:
        for cls in ORDEN:
            if ct.loc[dia, cls] == 0:
                print(f"  dia {dia:>2} × {cls}: 0 casos")


def d2_deriva_intraclase(m: pd.DataFrame) -> None:
    _sec("D2. ¿Se desplaza la señal DENTRO de una clase con el día?")
    print("(si el verde tolera distinta fiebre/dolor según el día -> umbral debe condicionarse)")
    for cls in ORDEN:
        sub = m[m[COL_LABEL] == cls]
        if sub.empty:
            continue
        print(f"\n--- clase = {cls} (n={len(sub)}) ---")
        for s in SENIALES_NUM:
            piv = sub.groupby(COL_DIA)[s].agg(["count", "min", "median", "max"])
            piv = piv.reindex(DIAS)
            print(f"  {s}:")
            print(piv.to_string().replace("\n", "\n    "))


def d3_frontera(m: pd.DataFrame) -> None:
    _sec("D3. FRONTERA verde↔rojo por día (¿se mueve el cruce?)")
    for s in SENIALES_NUM:
        print(f"\n--- {s}: max(verde) vs min(rojo) por día ---")
        rows = []
        for dia in DIAS:
            sd = m[m[COL_DIA] == dia]
            vmax = sd.loc[sd[COL_LABEL] == "verde", s].max() if (sd[COL_LABEL] == "verde").any() else None
            rmin = sd.loc[sd[COL_LABEL] == "rojo", s].min() if (sd[COL_LABEL] == "rojo").any() else None
            amax = sd.loc[sd[COL_LABEL] == "amarillo", s].max() if (sd[COL_LABEL] == "amarillo").any() else None
            gap = (rmin - vmax) if (vmax is not None and rmin is not None) else None
            rows.append({"dia": dia, "verde_max": vmax, "amarillo_max": amax,
                         "rojo_min": rmin, "gap_verde_rojo": gap})
        print(pd.DataFrame(rows).to_string(index=False))
    print("\nlectura: si 'verde_max' cambia mucho entre días, un umbral global castiga a unos días.")
    print("        si 'gap_verde_rojo' es >0 y estable, un umbral global simple es defendible.")


def d4_categoricas_por_dia(m: pd.DataFrame) -> None:
    _sec("D4. Banderas rojas categóricas — ¿su pureza aguanta por día?")
    print("(purulenta / incapacitante_nueva deben seguir siendo casi solo-rojo en cada día)")
    banderas = {
        "herida": "secrecion_purulenta",
        "movilidad": "incapacitante_nueva",
    }
    for col, valor in banderas.items():
        if col not in m.columns:
            continue
        print(f"\n--- {col} == '{valor}' por día × clase ---")
        sub = m[m[col] == valor]
        if sub.empty:
            print("  (no aparece)")
            continue
        print(pd.crosstab(sub[COL_DIA], sub[COL_LABEL]).reindex(columns=ORDEN, fill_value=0).to_string())


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("uso: python explora_dia.py /ruta/a/dataset  (o . si ya estás dentro)")
    base = Path(sys.argv[1]).expanduser().resolve()
    m = _merged(base)
    d1_reparto(m)
    d2_deriva_intraclase(m)
    d3_frontera(m)
    d4_categoricas_por_dia(m)
    _sec("FIN. Tráeme el reporte entero.")


if __name__ == "__main__":
    main()
