#!/usr/bin/env python3
"""
Exploración mínima Fase 1 — política de decisión clínica.
Responde Q1..Q6 sobre datos reales. NO escribe nada, NO asume esquemas:
imprime columnas/dtypes y falla ruidosamente si falta algo esperado.

Uso (Fedora/zsh):
    python -m venv .venv && source .venv/bin/activate
    pip install 'pandas>=2.0' 'openpyxl>=3.1' 'scikit-learn>=1.3'
    python explora_fase1.py /ruta/a/dataset

Salida: reporte de texto a stdout. Cópialo entero y tráemelo.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

# ---------- Config: nombres esperados (se verifican, no se asumen ciegamente) ----------
SHEET = "result"
F_DATASET = "dataset_final.xlsx"
F_TRAYECT = "trayectorias_postop_silver.xlsx"

SENIALES_NUM = ["dolor_nrs", "fiebre_c"]
SENIALES_CAT = ["movilidad", "herida", "apetito", "sueno"]
COL_ARQUETIPO = "arquetipo_trayectoria"
COL_LABEL = "label_ground_truth"
COL_CASO = "caso_id"
COL_TRAYID = "trayectoria_id"

SEP = "=" * 72


def _sec(titulo: str) -> None:
    print(f"\n{SEP}\n{titulo}\n{SEP}")


def _load(base: Path, fname: str) -> pd.DataFrame:
    ruta = base / fname
    if not ruta.exists():
        sys.exit(f"[FATAL] No existe: {ruta}")
    df = pd.read_excel(ruta, sheet_name=SHEET, engine="openpyxl")
    print(f"[OK] {fname}: {df.shape[0]} filas × {df.shape[1]} cols")
    return df


def _requiere(df: pd.DataFrame, cols: list[str], origen: str) -> None:
    faltan = [c for c in cols if c not in df.columns]
    if faltan:
        print(f"[WARN] En {origen} faltan columnas esperadas: {faltan}")
        print(f"       Columnas presentes: {list(df.columns)}")


def inspeccion_esquema(ds: pd.DataFrame, tr: pd.DataFrame) -> None:
    _sec("0. ESQUEMA REAL (verificar antes de confiar en nombres)")
    for nombre, df in [("dataset_final", ds), ("trayectorias_silver", tr)]:
        print(f"\n--- {nombre} ---")
        print("columnas:", list(df.columns))
        print("dtypes:")
        print(df.dtypes.to_string())


def q1_join(ds: pd.DataFrame, tr: pd.DataFrame) -> pd.DataFrame:
    _sec("Q1. INTEGRIDAD DEL JOIN  caso_id == 'caso_' + trayectoria_id")
    if COL_TRAYID not in tr.columns:
        print(f"[WARN] '{COL_TRAYID}' no está en trayectorias. Cols: {list(tr.columns)}")
        # intento heurístico: alguna col que empiece por 'tray'
        cand = [c for c in tr.columns if c.lower().startswith("tray")]
        print(f"       candidatas: {cand}")
        return tr.iloc[0:0]
    tr = tr.copy()
    tr["caso_id_derivado"] = "caso_" + tr[COL_TRAYID].astype(str)

    casos_ds = set(ds[COL_CASO].astype(str).unique()) if COL_CASO in ds.columns else set()
    casos_tr = set(tr["caso_id_derivado"].unique())

    print(f"casos únicos en dataset_final:      {len(casos_ds)}")
    print(f"casos únicos en trayectorias:       {len(casos_tr)}")
    print(f"intersección:                       {len(casos_ds & casos_tr)}")
    print(f"solo en dataset_final:              {len(casos_ds - casos_tr)}")
    print(f"solo en trayectorias:               {len(casos_tr - casos_ds)}")
    if casos_ds - casos_tr:
        print("  ejemplos solo-dataset:", sorted(casos_ds - casos_tr)[:5])
    if casos_tr - casos_ds:
        print("  ejemplos solo-trayect:", sorted(casos_tr - casos_ds)[:5])
    return tr


def _label_por_caso(ds: pd.DataFrame) -> pd.DataFrame:
    """Colapsa a 1 fila por caso_id. Verifica que el label sea realmente constante."""
    if COL_LABEL not in ds.columns or COL_CASO not in ds.columns:
        print(f"[WARN] Falta {COL_LABEL} o {COL_CASO} en dataset_final")
        return pd.DataFrame()
    g = ds.groupby(COL_CASO)[COL_LABEL].agg(["nunique", "first"])
    inconsist = g[g["nunique"] > 1]
    if len(inconsist):
        print(f"[ALERTA] {len(inconsist)} casos con label NO constante (viola gotcha):")
        print(inconsist.head(10).to_string())
    else:
        print("[OK] label constante por caso_id (gotcha confirmado)")
    return g["first"].rename(COL_LABEL).reset_index()


def q2_distribucion(ds: pd.DataFrame) -> pd.DataFrame:
    _sec("Q2. DISTRIBUCIÓN DEL LABEL — por CASO (no por turno)")
    lab = _label_por_caso(ds)
    if lab.empty:
        return lab
    print("\nconteo por caso:")
    print(lab[COL_LABEL].value_counts().to_string())
    print(f"total casos: {len(lab)}")
    print("\n(contraste) conteo por TURNO —métrica engañosa, no usar para diseño:")
    print(ds[COL_LABEL].value_counts().to_string())
    return lab


def _merge_senal_label(tr: pd.DataFrame, lab: pd.DataFrame) -> pd.DataFrame:
    if "caso_id_derivado" not in tr.columns or lab.empty:
        return pd.DataFrame()
    m = tr.merge(lab, left_on="caso_id_derivado", right_on=COL_CASO, how="inner")
    print(f"[merge señal↔label] {len(m)} casos con señal y label")
    return m


def q3_separabilidad(m: pd.DataFrame) -> None:
    _sec("Q3. SEPARABILIDAD UNIVARIADA POR SEÑAL (condicionada a clase)")
    if m.empty:
        print("[SKIP] merge vacío")
        return
    orden = ["verde", "amarillo", "rojo"]
    presentes = [c for c in orden if c in m[COL_LABEL].unique()]

    for s in SENIALES_NUM:
        if s not in m.columns:
            print(f"[WARN] señal numérica ausente: {s}")
            continue
        print(f"\n--- {s} (numérica) por clase ---")
        desc = m.groupby(COL_LABEL)[s].describe()[["count", "min", "25%", "50%", "75%", "max"]]
        print(desc.reindex(presentes).to_string())
        # solapamiento crudo: rango [min,max] de rojo vs percentil de verde
        if {"rojo", "verde"} <= set(presentes):
            rojo_min = m.loc[m[COL_LABEL] == "rojo", s].min()
            verde_p90 = m.loc[m[COL_LABEL] == "verde", s].quantile(0.90)
            print(f"  rojo.min={rojo_min}  verde.p90={verde_p90}  "
                  f"-> {'SOLAPAN' if rojo_min <= verde_p90 else 'SEPARAN'} en cola")

    for s in SENIALES_CAT:
        if s not in m.columns:
            print(f"[WARN] señal categórica ausente: {s}")
            continue
        print(f"\n--- {s} (categórica) tabla clase×valor ---")
        ct = pd.crosstab(m[COL_LABEL], m[s]).reindex(presentes)
        print(ct.to_string())


def q4_ambiguos(m: pd.DataFrame) -> None:
    _sec("Q4. ZONAS AMBIGUAS — rojo/amarillo con señales dentro del rango verde")
    if m.empty or COL_LABEL not in m.columns:
        print("[SKIP]")
        return
    verdes = m[m[COL_LABEL] == "verde"]
    if verdes.empty:
        print("[SKIP] no hay verdes")
        return
    # banda 'apariencia verde' = entre p10 y p90 de los verdes en las señales numéricas
    bandas: dict[str, tuple[float, float]] = {}
    for s in SENIALES_NUM:
        if s in m.columns:
            bandas[s] = (verdes[s].quantile(0.10), verdes[s].quantile(0.90))
    print("bandas 'aspecto verde' (p10..p90):",
          {k: (round(v[0], 2), round(v[1], 2)) for k, v in bandas.items()})

    no_verde = m[m[COL_LABEL].isin(["amarillo", "rojo"])].copy()
    def dentro(row: pd.Series) -> bool:
        return all(bandas[s][0] <= row[s] <= bandas[s][1] for s in bandas)
    if bandas:
        no_verde["parece_verde"] = no_verde.apply(dentro, axis=1)
        amb = no_verde[no_verde["parece_verde"]]
        print(f"\ncasos NO-verdes que 'parecen verdes' en señales numéricas: {len(amb)}")
        print(amb[COL_LABEL].value_counts().to_string())
        cols_show = [c for c in [COL_CASO, COL_LABEL, *SENIALES_NUM, *SENIALES_CAT] if c in amb.columns]
        if len(amb):
            print("\ndetalle (estos son los casos que un clasificador de 1 turno pierde):")
            print(amb[cols_show].head(20).to_string(index=False))


def q5_arquetipo(m: pd.DataFrame) -> None:
    _sec("Q5. arquetipo_trayectoria — ¿señal legítima o leakage del label?")
    if COL_ARQUETIPO not in m.columns:
        print(f"[WARN] ausente: {COL_ARQUETIPO}")
        return
    ct = pd.crosstab(m[COL_ARQUETIPO], m[COL_LABEL])
    print("tabla arquetipo × label:")
    print(ct.to_string())
    # pureza: si cada arquetipo mapea casi 1:1 a una clase, huele a leakage
    pureza = ct.max(axis=1) / ct.sum(axis=1)
    print("\npureza por arquetipo (max_clase / total):")
    print(pureza.round(3).sort_values(ascending=False).to_string())
    n_puros = (pureza >= 0.95).sum()
    print(f"\narquetipos con pureza>=0.95: {n_puros}/{len(pureza)}  "
          f"-> {'SOSPECHA de leakage; declararlo' if n_puros == len(pureza) else 'aporta señal, no es copia del label'}")


def q6_arbol_sonda(m: pd.DataFrame) -> None:
    _sec("Q6. SONDA: árbol prof<=3 (techo de separabilidad, NO modelo de producción)")
    try:
        from sklearn.tree import DecisionTreeClassifier, export_text
        from sklearn.model_selection import StratifiedKFold, cross_val_predict
        from sklearn.metrics import classification_report, confusion_matrix
    except ImportError:
        print("[SKIP] instala scikit-learn para esta sonda")
        return
    if m.empty:
        print("[SKIP]")
        return
    feats_num = [s for s in SENIALES_NUM if s in m.columns]
    feats_cat = [s for s in SENIALES_CAT if s in m.columns]
    X = m[feats_num].copy()
    for c in feats_cat:
        X[c] = m[c].astype("category").cat.codes  # ordinal crudo, solo sonda
    y = m[COL_LABEL].astype(str)
    print(f"features: {feats_num + feats_cat}  |  n={len(X)}")

    clf = DecisionTreeClassifier(max_depth=3, class_weight="balanced", random_state=0)
    n_min = y.value_counts().min()
    k = max(2, min(5, n_min))  # no más folds que la clase minoritaria
    print(f"CV estratificada k={k} (limitado por clase minoritaria n={n_min})")
    cv = StratifiedKFold(n_splits=k, shuffle=True, random_state=0)
    y_pred = cross_val_predict(clf, X, y, cv=cv)

    print("\nmatriz de confusión (filas=real, cols=pred), orden verde/amarillo/rojo:")
    labels = [l for l in ["verde", "amarillo", "rojo"] if l in y.unique()]
    print(pd.DataFrame(confusion_matrix(y, y_pred, labels=labels),
                       index=labels, columns=labels).to_string())
    print("\nreporte (mira RECALL de 'rojo', es la restricción dura):")
    print(classification_report(y, y_pred, labels=labels, zero_division=0))

    clf.fit(X, y)
    print("reglas del árbol (full-fit, solo para leer qué señales usa):")
    print(export_text(clf, feature_names=list(X.columns)))


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("uso: python explora_fase1.py /ruta/a/dataset")
    base = Path(sys.argv[1]).expanduser().resolve()
    if not base.is_dir():
        sys.exit(f"[FATAL] no es directorio: {base}")
    print(f"base: {base}")

    ds = _load(base, F_DATASET)
    tr = _load(base, F_TRAYECT)

    inspeccion_esquema(ds, tr)
    _requiere(ds, [COL_CASO, COL_LABEL], "dataset_final")
    _requiere(tr, [COL_TRAYID, *SENIALES_NUM, *SENIALES_CAT, COL_ARQUETIPO], "trayectorias")

    tr = q1_join(ds, tr)
    lab = q2_distribucion(ds)
    m = _merge_senal_label(tr, lab)
    q3_separabilidad(m)
    q4_ambiguos(m)
    q5_arquetipo(m)
    q6_arbol_sonda(m)

    _sec("FIN. Tráeme este reporte entero.")


if __name__ == "__main__":
    main()
