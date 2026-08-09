"""Criterio de aceptación de Fase 2.1 sobre los 160 casos del dev set.

Único test que usa pandas y lee el dataset. Sin `DATASET_DIR` hace skip, no falla.

`scripts/verificacion_hd1.py` es el ORÁCULO: reimplementación independiente escrita
antes de que este módulo existiera. Se importa AQUÍ y solo aquí, para un test de
equivalencia caso a caso. Si el módulo lo importara, el test no probaría nada.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

if not os.environ.get("DATASET_DIR"):
    pytest.skip(
        "DATASET_DIR no definido: el test del dev set se omite", allow_module_level=True
    )

pd = pytest.importorskip("pandas", reason="pandas es dependencia de test, no del módulo")

from politica import Accion, Clase, Criterio, Observacion, Regimen, decidir  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
ORACULO = RAIZ / "scripts" / "verificacion_hd1.py"

CLASES = {"verde": Clase.VERDE, "amarillo": Clase.AMARILLO, "rojo": Clase.ROJO}
REGIMENES = {"temprano": Regimen.TEMPRANO, "tardio": Regimen.TARDIO}

# Números de `scripts/verificacion_hd1_salida.txt`. La spec ya está verificada:
# si el módulo no los reproduce, el módulo está mal.
ESPERADO = {
    "recall_rojo": 1.000,
    "C_FN": 0,
    "c1": 0,
    "c3": 0,
    "c2": 11,
    "c2_temprano": 4,
    "c2_tardio": 7,
    "S1": 12,
    "S2": 93,
    "S3": 36,
    "CIERRE_FORZADO": 19,
}


def _cargar_oraculo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("oraculo_hd1", ORACULO)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def oraculo() -> ModuleType:
    return _cargar_oraculo()


@pytest.fixture(scope="module")
def salida(oraculo: ModuleType) -> Any:
    """Un DataFrame con la decisión del módulo y la del oráculo para los 160 casos."""
    casos = oraculo.cargar()
    filas = []
    for r in casos.itertuples():
        entrada = Observacion(
            dia_postop=int(r.dia_postop),
            dolor_nrs=int(r.dolor_nrs),
            fiebre_c=float(r.fiebre_c),
            herida=str(r.herida),
            movilidad=str(r.movilidad),
            apetito=str(r.apetito),
            sueno=str(r.sueno),
        )
        d = decidir(entrada)
        assert d.accion is Accion.CLASIFICAR and d.clase is not None and d.criterio is not None
        filas.append(
            {
                "caso_id": r.caso_id,
                "real": r.label,
                "clase": d.clase,
                "criterio": d.criterio,
                "regimen": d.regimen,
                "n_total": d.n_total,
                "oraculo": oraculo.terminal(r),
            }
        )
    f = pd.DataFrame(filas)
    assert len(f) == 160
    return f


def _celda(f: Any, predicha: Clase, real: str) -> int:
    return int(len(f[(f.clase == predicha) & (f.real == real)]))


# --------------------------------------------------------------------------- #
# Criterio de aceptación
# --------------------------------------------------------------------------- #
def test_recall_rojo(salida: Any) -> None:
    rojos = salida[salida.real == "rojo"]
    assert len(rojos) == 12
    assert (rojos.clase == Clase.ROJO).mean() == ESPERADO["recall_rojo"]


def test_matriz_de_costos(salida: Any) -> None:
    assert _celda(salida, Clase.VERDE, "rojo") == ESPERADO["C_FN"]
    assert _celda(salida, Clase.VERDE, "amarillo") == ESPERADO["c1"]
    assert _celda(salida, Clase.AMARILLO, "rojo") == ESPERADO["c3"]
    assert _celda(salida, Clase.AMARILLO, "verde") == ESPERADO["c2"]


def test_c2_desagregado_por_regimen(salida: Any) -> None:
    c2 = salida[(salida.clase == Clase.AMARILLO) & (salida.real == "verde")]
    assert len(c2[c2.regimen == Regimen.TEMPRANO]) == ESPERADO["c2_temprano"]
    assert len(c2[c2.regimen == Regimen.TARDIO]) == ESPERADO["c2_tardio"]


def test_criterios_de_cierre(salida: Any) -> None:
    conteo = salida.criterio.value_counts().to_dict()
    assert conteo.get(Criterio.S1, 0) == ESPERADO["S1"]
    assert conteo.get(Criterio.S2, 0) == ESPERADO["S2"]
    assert conteo.get(Criterio.S3, 0) == ESPERADO["S3"]
    assert conteo.get(Criterio.CIERRE_FORZADO, 0) == ESPERADO["CIERRE_FORZADO"]
    assert conteo.get(Criterio.AGOTAMIENTO, 0) == 0  # vector completo: §8 no aplica


def test_los_19_cierres_forzados(salida: Any) -> None:
    """§7.4: los 19 son temprano, `n_total == 1`, VERDE, y todos verde real."""
    forzados = salida[salida.criterio == Criterio.CIERRE_FORZADO]
    assert len(forzados) == ESPERADO["CIERRE_FORZADO"]
    assert (forzados.regimen == Regimen.TEMPRANO).all()
    assert (forzados.n_total == 1).all()
    assert (forzados.clase == Clase.VERDE).all()
    assert (forzados.real == "verde").all()


# --------------------------------------------------------------------------- #
# Equivalencia con el oráculo, caso a caso
# --------------------------------------------------------------------------- #
def test_equivalencia_con_el_oraculo(salida: Any) -> None:
    discrepancias = [
        (r.caso_id, r.clase, r.oraculo.clase)
        for r in salida.itertuples()
        if r.clase is not CLASES[r.oraculo.clase]
    ]
    assert not discrepancias, f"{len(discrepancias)} casos difieren: {discrepancias[:5]}"


def test_equivalencia_de_criterio_y_regimen(salida: Any) -> None:
    for r in salida.itertuples():
        assert r.criterio.name == r.oraculo.criterio, r.caso_id
        assert r.regimen is REGIMENES[r.oraculo.regimen], r.caso_id
        if r.criterio is not Criterio.S1:  # el oráculo no evalúa §5 tras una bandera
            assert r.n_total == r.oraculo.n_total, r.caso_id


# --------------------------------------------------------------------------- #
# Par de colisión con su vector real (D5)
# --------------------------------------------------------------------------- #
def test_par_de_colision_en_el_dev_set(salida: Any) -> None:
    """Misma fiebre (37.9) y misma herida al día 7, clases distintas."""
    amarillo = salida[salida.caso_id.str.endswith("00012_7")]
    rojo = salida[salida.caso_id.str.endswith("00017_7")]
    assert len(amarillo) == 1 and len(rojo) == 1
    assert amarillo.iloc[0].clase is Clase.AMARILLO
    assert amarillo.iloc[0].real == "amarillo"
    assert rojo.iloc[0].clase is Clase.ROJO
    assert rojo.iloc[0].real == "rojo"
