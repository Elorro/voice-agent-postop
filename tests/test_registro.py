"""El registro y las métricas que salen de él.

`/metricas` lee el mismo archivo que el jurado puede abrir. Estos tests fijan
esa propiedad: los números salen del JSONL, no de un acumulador, y el parche de
telemetría deja una línea completa por turno.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.registro import (
    anotar,
    calcular_metricas,
    leer,
    parchear_latencia_cliente,
    percentil,
)
from tests.apoyo_turno import config_de_prueba, escribir_tarifas


def turno(llamada_id: str, idx: int, **cambios) -> dict:
    base = {
        "tipo": "turno",
        "ts": "2026-08-09T10:00:00-05:00",
        "llamada_id": llamada_id,
        "turno_idx": idx,
        "latencia_ms": {
            "cliente_fin_habla_a_audio": None,
            "servidor_total": 900.0,
            "spans": {"stt": 300, "extraccion": 400, "politica": 0.4, "rag": 0,
                      "redaccion": 0, "tts": 190},
        },
        "llm": [
            {"rol": "extractor", "modelo": "m1", "tokens_in": 100, "tokens_out": 20,
             "ms": 400, "reintentos": 0, "resultado": "ok"}
        ],
        "rag": {"consultas": 0, "citas": []},
        "politica": {"entrada": {}, "presupuesto": {}, "salida": {"accion": "REPREGUNTAR"}},
        "transcripcion": "algo",
        "respuesta": "otra cosa",
        "fuente_respuesta": "plantilla",
        "stt": {"resultado": "ok", "segundos_audio": 2.0, "detalle": ""},
    }
    base.update(cambios)
    return base


# --------------------------------------------------------------------------- #
# Percentiles
# --------------------------------------------------------------------------- #
def test_percentil_sin_muestras_es_nulo_no_cero() -> None:
    assert percentil([], 50) is None
    assert percentil([], 95) is None


def test_percentil_con_una_muestra() -> None:
    assert percentil([1200.0], 95) == 1200.0


def test_percentil_por_interpolacion_lineal() -> None:
    """El método está declarado en la respuesta de /metricas para que quien lea
    el P95 pueda reproducirlo sin adivinar la convención."""
    valores = [100.0, 200.0, 300.0, 400.0]
    assert percentil(valores, 50) == 250.0
    assert percentil(valores, 95) == 385.0
    assert percentil(valores, 0) == 100.0
    assert percentil(valores, 100) == 400.0


# --------------------------------------------------------------------------- #
# Escritura y relectura
# --------------------------------------------------------------------------- #
def test_anotar_y_leer_ida_y_vuelta(tmp_path: Path) -> None:
    cfg = config_de_prueba(tmp_path)
    anotar(cfg, turno("abc", 1))
    anotar(cfg, turno("abc", 2))
    assert [l["turno_idx"] for l in leer(cfg.ruta_turnos_jsonl)] == [1, 2]


def test_una_linea_rota_no_impide_leer_las_demas(tmp_path: Path) -> None:
    cfg = config_de_prueba(tmp_path)
    anotar(cfg, turno("abc", 1))
    with cfg.ruta_turnos_jsonl.open("a", encoding="utf-8") as fh:
        fh.write('{"tipo": "turno", ROTA\n')
    anotar(cfg, turno("abc", 2))
    assert [l["turno_idx"] for l in leer(cfg.ruta_turnos_jsonl)] == [1, 2]


def test_registro_inexistente_se_lee_como_vacio(tmp_path: Path) -> None:
    cfg = config_de_prueba(tmp_path)
    assert list(leer(cfg.ruta_turnos_jsonl)) == []
    assert calcular_metricas(cfg)["n_turnos"] == 0


# --------------------------------------------------------------------------- #
# Telemetría
# --------------------------------------------------------------------------- #
def test_la_telemetria_completa_la_linea_del_turno(tmp_path: Path) -> None:
    cfg = config_de_prueba(tmp_path)
    anotar(cfg, turno("abc", 1))
    anotar(cfg, turno("abc", 2))

    assert parchear_latencia_cliente(cfg, "abc", 2, 1420.4) is True
    lineas = list(leer(cfg.ruta_turnos_jsonl))
    assert lineas[1]["latencia_ms"]["cliente_fin_habla_a_audio"] == 1420.4
    # El otro turno queda intacto: sin medición es `null`, no cero.
    assert lineas[0]["latencia_ms"]["cliente_fin_habla_a_audio"] is None


def test_telemetria_de_un_turno_inexistente_no_inventa_nada(tmp_path: Path) -> None:
    cfg = config_de_prueba(tmp_path)
    anotar(cfg, turno("abc", 1))
    assert parchear_latencia_cliente(cfg, "abc", 99, 500.0) is False
    assert parchear_latencia_cliente(cfg, "otra", 1, 500.0) is False
    assert len(list(leer(cfg.ruta_turnos_jsonl))) == 1


# --------------------------------------------------------------------------- #
# Métricas
# --------------------------------------------------------------------------- #
def test_las_metricas_salen_del_archivo(tmp_path: Path) -> None:
    cfg = config_de_prueba(tmp_path)
    escribir_tarifas(cfg, {"m1": {"entrada": 0.4, "salida": 0.4}})
    for idx, ms in enumerate([1000.0, 1200.0, 1600.0], start=1):
        registro = turno("abc", idx)
        registro["latencia_ms"]["cliente_fin_habla_a_audio"] = ms
        anotar(cfg, registro)
    anotar(cfg, turno("abc", 4))  # sin telemetría

    m = calcular_metricas(cfg)
    cliente = m["latencia_ms"]["cliente_fin_habla_a_audio"]
    assert cliente["n"] == 3
    assert cliente["p50"] == 1200.0
    assert cliente["es_la_cifra_reportada"] is True
    assert cliente["turnos_sin_telemetria"] == 1
    assert m["latencia_ms"]["servidor_total"]["es_la_cifra_reportada"] is False
    assert m["n_turnos"] == 4
    assert m["consumo"]["tokens_entrada"] == 400
    assert m["consumo"]["costo_usd"] == pytest.approx(400 / 1e6 * 0.4 + 80 / 1e6 * 0.4)
    assert m["consumo"]["segundos_audio_transcritos"] == 8.0
    assert (m["rag"]["consultas"], m["rag"]["citas"]) == (0, 0)
    assert str(cfg.ruta_turnos_jsonl) == m["fuente"]


def test_un_modelo_sin_tarifa_deja_el_costo_en_nulo(tmp_path: Path) -> None:
    cfg = config_de_prueba(tmp_path)
    escribir_tarifas(cfg, {})
    anotar(cfg, turno("abc", 1))
    m = calcular_metricas(cfg)
    assert m["consumo"]["costo_usd"] is None
    assert m["consumo"]["modelos_sin_tarifa"] == ["m1"]
    assert m["consumo"]["costo_usd_parcial"] == 0.0


def test_los_tokens_ausentes_no_se_estiman(tmp_path: Path) -> None:
    """Si el proveedor no manda `usage`, el consumo de ese turno no suma. Un
    número estimado en la columna de consumo es indistinguible de uno medido."""
    cfg = config_de_prueba(tmp_path)
    registro = turno("abc", 1)
    registro["llm"][0]["tokens_in"] = None
    registro["llm"][0]["tokens_out"] = None
    anotar(cfg, registro)
    m = calcular_metricas(cfg)
    assert m["consumo"]["tokens_entrada"] == 0
    assert m["consumo"]["invocaciones_llm"] == {"extractor": 1}


def test_una_medicion_sin_reproduccion_no_entra_en_la_cifra_reportada(
    tmp_path: Path,
) -> None:
    """Un cliente headless no puede ver el «primer sample sonando»: su número es
    una cota inferior. Promediarlo con el del navegador daría una cifra que
    parece medida y no lo está."""
    from app.registro import ORIGEN_HEADLESS

    cfg = config_de_prueba(tmp_path)
    anotar(cfg, turno("abc", 1))
    anotar(cfg, turno("abc", 2))
    parchear_latencia_cliente(cfg, "abc", 1, 1500.0)
    parchear_latencia_cliente(cfg, "abc", 2, 300.0, ORIGEN_HEADLESS)

    m = calcular_metricas(cfg)
    cliente = m["latencia_ms"]["cliente_fin_habla_a_audio"]
    assert cliente["n"] == 1 and cliente["p50"] == 1500.0
    otras = m["latencia_ms"]["otras_fuentes"][ORIGEN_HEADLESS]
    assert otras["n"] == 1 and otras["p50"] == 300.0
    assert otras["es_la_cifra_reportada"] is False


def test_la_apertura_no_entra_en_el_percentil_de_los_turnos(tmp_path: Path) -> None:
    """En la apertura no hay «fin de habla del paciente» que cronometrar."""
    cfg = config_de_prueba(tmp_path)
    apertura = turno("abc", 0, tipo="apertura")
    apertura["latencia_ms"]["cliente_fin_habla_a_audio"] = 5000.0
    anotar(cfg, apertura)
    registro = turno("abc", 1)
    registro["latencia_ms"]["cliente_fin_habla_a_audio"] = 900.0
    anotar(cfg, registro)

    m = calcular_metricas(cfg)
    assert m["n_turnos"] == 1
    assert m["latencia_ms"]["cliente_fin_habla_a_audio"]["p95"] == 900.0
