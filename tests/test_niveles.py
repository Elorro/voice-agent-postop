"""Niveles 0, 1, 1.5 y 2, cierre forzado (§7.4), escalamiento (§8) y errores (§8.2)."""

from __future__ import annotations

import math

import pytest

from apoyo import obs, obs_temprano, presupuesto_agotado, vacia
from politica import Accion, Clase, Criterio, ErrorDeInvocacion, Observacion, Regimen, Trivalor
from politica.motor import (
    MARCA_CONFIANZA_BAJA,
    MARCA_DIA_DESCONOCIDO,
    MARCA_FUERA_DE_ALCANCE,
    compuerta_activa,
    condiciones_compuerta,
    contar,
    decidir,
    nivel_1,
    nivel_1_5,
    nivel_2,
)

V, F, D = Trivalor.VERDADERO, Trivalor.FALSO, Trivalor.DESCONOCIDO


# --------------------------------------------------------------------------- #
# §2.1 — los seis casos de borde del enrutador temporal
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("dia", [0, 1, 2, 3])
def test_dia_temprano(dia: int) -> None:
    d = decidir(obs(dia_postop=dia))
    assert d.regimen is Regimen.TEMPRANO
    assert d.marcas == ()


@pytest.mark.parametrize("dia", [4, 5, 7, 14, 30])
def test_dia_tardio(dia: int) -> None:
    d = decidir(obs(dia_postop=dia))
    assert d.regimen is Regimen.TARDIO
    assert d.marcas == ()


def test_dia_cero_es_temprano() -> None:
    """§2.1: el mismo día de la cirugía es el extremo del régimen inflamatorio agudo."""
    assert decidir(obs(dia_postop=0)).regimen is Regimen.TEMPRANO


def test_dia_ausente_es_tardio_con_marca() -> None:
    """§2.1: dirección segura (c₂ es la celda barata) + marca obligatoria."""
    d = decidir(obs(dia_postop=None))
    assert d.regimen is Regimen.TARDIO
    assert MARCA_DIA_DESCONOCIDO in d.marcas


def test_dia_fuera_de_ventana_es_tardio_marcado() -> None:
    d = decidir(obs(dia_postop=31))
    assert d.regimen is Regimen.TARDIO
    assert MARCA_FUERA_DE_ALCANCE in d.marcas
    assert d.clase is not None  # la decisión se emite, no se rechaza


@pytest.mark.parametrize("dia", [-1, -14, 3.5, 7.0, True])
def test_dia_invalido_es_excepcion(dia: object) -> None:
    """§2.1: día negativo o no entero es bug del llamador. Falla ruidoso."""
    with pytest.raises(ErrorDeInvocacion):
        decidir(obs(dia_postop=dia))


# --------------------------------------------------------------------------- #
# §3 — Nivel 1, banderas rojas: precedencia absoluta
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "campo,valor,bandera",
    [
        ("herida", "secrecion_purulenta", "purulenta"),
        ("movilidad", "incapacitante_nueva", "movilidad_incapacitante"),
        ("fiebre_c", 38.0, "fiebre_franca"),
    ],
)
def test_bandera_en_ambos_regimenes(campo: str, valor: object, bandera: str) -> None:
    for constructor in (obs, obs_temprano):
        d = decidir(constructor(**{campo: valor}))
        assert d.clase is Clase.ROJO
        assert d.criterio is Criterio.S1
        assert bandera in d.disparadores


def test_fiebre_franca_no_dispara_por_debajo_del_umbral() -> None:
    """§3.2: la frontera no admite holgura; 37.9 no es fiebre franca."""
    assert nivel_1(obs(fiebre_c=37.9), Regimen.TARDIO)["fiebre_franca"] is F
    assert nivel_1(obs(fiebre_c=38.0), Regimen.TARDIO)["fiebre_franca"] is V


def test_dolor_severo_tiene_umbral_por_regimen() -> None:
    """§3.1: la asimetría se **gradúa** (7 tardío / 9 temprano); la bandera no se apaga."""
    assert decidir(obs(dolor_nrs=7)).clase is Clase.ROJO
    assert decidir(obs_temprano(dolor_nrs=7)).clase is not Clase.ROJO
    assert decidir(obs_temprano(dolor_nrs=9)).clase is Clase.ROJO


def test_dolor_ausente_deja_la_bandera_pendiente_en_ambos_regimenes() -> None:
    """§3.1, efecto colateral buscado: ya no hay colapso `D ∧ F = F` en temprano.

    Es lo que devuelve su verdad a la premisa de §8 («si ninguna bandera está en
    `DESCONOCIDO`, entonces `herida`, `movilidad`, `fiebre_c` y `dolor_nrs` son
    conocidas»), que era el defecto O1 de `docs/BLOQUEO_2_1.md`.
    """
    assert nivel_1(obs_temprano(dolor_nrs=None), Regimen.TEMPRANO)["dolor_severo"] is D
    assert nivel_1(obs(dolor_nrs=None), Regimen.TARDIO)["dolor_severo"] is D


@pytest.mark.parametrize(
    "campo,bandera",
    [
        ("herida", "purulenta"),
        ("movilidad", "movilidad_incapacitante"),
        ("fiebre_c", "fiebre_franca"),
    ],
)
def test_senal_ausente_deja_su_bandera_pendiente(campo: str, bandera: str) -> None:
    assert nivel_1(obs(**{campo: None}), Regimen.TARDIO)[bandera] is D


# --------------------------------------------------------------------------- #
# Fronteras de los umbrales numéricos
# --------------------------------------------------------------------------- #
def test_frontera_de_cada_umbral() -> None:
    """Cada umbral de §3, §4 y §5, fijado en su valor exacto y en el entero/décima previa.

    Los 160 casos NO fijan estas fronteras: `dolor_nrs ∈ {7,8}` no existe en la
    muestra (D3), así que mover `dolor_severo` de 7 a 8 no cambia un solo caso del
    dev set. La única red que atrapa ese cambio son estas aserciones. El umbral se
    sostiene por la partición estándar de la NRS (1-3 leve, 4-6 moderado, 7-10
    severo), no por el dataset, y el test tiene que sostenerlo igual.
    """
    # §3 — banderas de Nivel 1
    assert nivel_1(obs(fiebre_c=38.0), Regimen.TARDIO)["fiebre_franca"] is V
    assert nivel_1(obs(fiebre_c=37.9), Regimen.TARDIO)["fiebre_franca"] is F
    assert nivel_1(obs(dolor_nrs=7), Regimen.TARDIO)["dolor_severo"] is V
    assert nivel_1(obs(dolor_nrs=6), Regimen.TARDIO)["dolor_severo"] is F
    assert nivel_1(obs_temprano(dolor_nrs=9), Regimen.TEMPRANO)["dolor_severo"] is V
    assert nivel_1(obs_temprano(dolor_nrs=8), Regimen.TEMPRANO)["dolor_severo"] is F

    # §4 — condiciones de la compuerta
    def gate(condicion: str, **cambios: object) -> Trivalor:
        return condiciones_compuerta(obs(**cambios), Regimen.TARDIO)[condicion]

    assert gate("g_fiebre", fiebre_c=37.8) is V
    assert gate("g_fiebre", fiebre_c=37.7) is F
    assert gate("g_dolor", dolor_nrs=5) is V
    assert gate("g_dolor", dolor_nrs=4) is F

    # §5 — señales blandas
    assert nivel_2(obs(fiebre_c=37.5), Regimen.TARDIO)["s_fiebre"] is V
    assert nivel_2(obs(fiebre_c=37.4), Regimen.TARDIO)["s_fiebre"] is F
    assert nivel_2(obs(dolor_nrs=5), Regimen.TARDIO)["s_dolor"] is V
    assert nivel_2(obs(dolor_nrs=4), Regimen.TARDIO)["s_dolor"] is F


def test_banda_severa_escala_en_ambos_regimenes() -> None:
    """La banda {7,8,10} no tiene una sola observación (D3) pero es legal en 0-10 (§1).

    Ningún caso del dev set cubre estas aserciones: son la única red que sostiene
    los dos umbrales de `dolor_severo`.
    """
    for dolor in (7, 8, 9, 10):
        d = decidir(obs(dolor_nrs=dolor))
        assert (d.clase, d.criterio) == (Clase.ROJO, Criterio.S1), f"tardío {dolor}"
    assert decidir(obs(dolor_nrs=6)).clase is not Clase.ROJO

    for dolor in (9, 10):
        d = decidir(obs_temprano(dolor_nrs=dolor))
        assert (d.clase, d.criterio) == (Clase.ROJO, Criterio.S1), f"temprano {dolor}"
    for dolor in (7, 8):
        assert decidir(obs_temprano(dolor_nrs=dolor)).clase is not Clase.ROJO, dolor


# --------------------------------------------------------------------------- #
# O3 — decisión del arquitecto del 2026-08-09 (umbral de dolor por régimen)
# --------------------------------------------------------------------------- #
def test_o3_dia_uno_con_dolor_nueve_escala_a_rojo() -> None:
    """El caso que motivó la decisión. **Antes cerraba VERDE por S2, sin indagar.**"""
    d = decidir(obs_temprano(dolor_nrs=9))
    assert (d.clase, d.criterio) == (Clase.ROJO, Criterio.S1)
    assert "dolor_severo" in d.disparadores


def test_o3_dia_uno_con_dolor_ocho_no_escala_por_esa_bandera() -> None:
    d = decidir(obs_temprano(dolor_nrs=8))
    assert d.banderas["dolor_severo"] is F
    assert d.clase is not Clase.ROJO


def test_o3_dolor_ausente_en_temprano_agota_en_rojo() -> None:
    """§3.1, costo en runtime aceptado: antes AMARILLO por §8, ahora ROJO.

    Simetría con la herida: un paciente temprano que no describe su herida ya salía
    ROJO al agotar el presupuesto. La diferencia era un artefacto del `SOLO_TARDIO`.
    """
    d = decidir(obs_temprano(dolor_nrs=None), presupuesto_agotado())
    assert (d.clase, d.criterio) == (Clase.ROJO, Criterio.AGOTAMIENTO)
    assert "dolor_severo" in d.disparadores


def test_umbral_de_conteo_por_regimen() -> None:
    """§5.2: TARDÍO cierra AMARILLO con 1 señal; TEMPRANO exige 2."""
    assert decidir(obs(fiebre_c=37.6)).clase is Clase.AMARILLO  # n_total = 1
    assert decidir(obs_temprano(fiebre_c=37.6)).clase is Clase.VERDE  # n_total = 1
    assert decidir(obs_temprano(fiebre_c=37.6, herida="eritema_leve")).clase is Clase.AMARILLO


# --------------------------------------------------------------------------- #
# §4 — Nivel 1.5, compuerta de no-verde
# --------------------------------------------------------------------------- #
def test_compuerta_no_aplica_en_temprano() -> None:
    """§4: SOLO_TARDÍO. Las tres condiciones se midieron sobre los 58 verdes tardíos."""
    for cambios in ({"fiebre_c": 37.8}, {"dolor_nrs": 5}, {"apetito": "muy_disminuido"}):
        assert nivel_1_5(obs_temprano(**cambios), Regimen.TEMPRANO) is F


@pytest.mark.parametrize(
    "cambios",
    [
        {"fiebre_c": 37.8},
        {"dolor_nrs": 5},
        {"apetito": "muy_disminuido", "sueno": "muy_alterado"},
    ],
)
def test_compuerta_es_disyuncion(cambios: dict[str, object]) -> None:
    """§4: `activa_si: CUALQUIERA`. Cada condición basta por sí sola."""
    assert nivel_1_5(obs(**cambios), Regimen.TARDIO) is V


def test_constitucional_exige_las_dos_partes() -> None:
    """§4: por separado apetito y sueño arrastran 5 y 4 verdes; la conjunción, ninguno."""
    assert nivel_1_5(obs(apetito="muy_disminuido"), Regimen.TARDIO) is F
    assert nivel_1_5(obs(sueno="muy_alterado"), Regimen.TARDIO) is F


def test_compuerta_desconocida_cuenta_como_activa() -> None:
    """§4.1: el tercer valor resuelve en la dirección segura.

    Hoy su costo es cero por estructura, no por ley (§4.1): para llegar a una
    salida distinta de ROJO hacen falta las cuatro banderas en FALSO, y entonces
    la única condición que puede quedar en DESCONOCIDO es `g_constitucional`.
    La cláusula se implementa igual, para que su eliminación por «redundante»
    tenga que romper este test.
    """
    incompleta = obs(apetito=None, sueno="muy_alterado")
    assert nivel_1_5(incompleta, Regimen.TARDIO) is D
    assert compuerta_activa(D) is True
    assert compuerta_activa(V) is True
    assert compuerta_activa(F) is False


# --------------------------------------------------------------------------- #
# §5 — Nivel 2, conteo
# --------------------------------------------------------------------------- #
def test_purulenta_e_incapacitante_no_cuentan_como_blandas() -> None:
    """§5.1: son banderas de Nivel 1; incluirlas aquí sería código muerto."""
    blandas = nivel_2(obs(herida="secrecion_purulenta", movilidad="incapacitante_nueva"),
                      Regimen.TARDIO)
    assert contar(blandas) == 0


def test_conteo_de_la_base() -> None:
    completa = obs(fiebre_c=37.5, herida="eritema_leve", apetito="muy_disminuido",
                   sueno="muy_alterado", dolor_nrs=0)
    assert contar(nivel_2(completa, Regimen.TARDIO)) == 4


def test_s_dolor_fuera_de_la_base_en_temprano() -> None:
    """§5.1 / H3: en TEMPRANO el dolor solo cuenta acompañado. Sin autorreferencia."""
    solo_dolor = obs_temprano(dolor_nrs=6)
    assert nivel_2(solo_dolor, Regimen.TEMPRANO)["s_dolor"] is F
    assert contar(nivel_2(solo_dolor, Regimen.TEMPRANO)) == 0

    acompanado = obs_temprano(dolor_nrs=6, herida="eritema_leve")
    assert nivel_2(acompanado, Regimen.TEMPRANO)["s_dolor"] is V
    assert contar(nivel_2(acompanado, Regimen.TEMPRANO)) == 2


def test_s_dolor_cuenta_solo_en_tardio() -> None:
    assert contar(nivel_2(obs(dolor_nrs=5), Regimen.TARDIO)) == 1
    assert contar(nivel_2(obs(dolor_nrs=4), Regimen.TARDIO)) == 0


def test_s_dolor_pendiente_si_la_base_puede_subir() -> None:
    """H3 en trivaluado: `n_base >= 1` es DESCONOCIDO mientras la base pueda crecer."""
    parcial = obs_temprano(dolor_nrs=6, herida=None, fiebre_c=36.6,
                           apetito="normal", sueno="normal")
    assert nivel_2(parcial, Regimen.TEMPRANO)["s_dolor"] is D


def test_umbral_asimetrico_por_regimen() -> None:
    """§5.2 / H4: el eritema aislado basta en TARDÍO y no en TEMPRANO."""
    tardio = decidir(obs(herida="eritema_leve"))
    assert tardio.clase is Clase.AMARILLO and tardio.criterio is Criterio.S3

    temprano = decidir(obs_temprano(herida="eritema_leve"))
    assert temprano.clase is Clase.VERDE


# --------------------------------------------------------------------------- #
# §7.1 — suficiencia
# --------------------------------------------------------------------------- #
def test_s2_verde_robusto() -> None:
    d = decidir(obs())
    assert (d.clase, d.criterio, d.accion) == (Clase.VERDE, Criterio.S2, Accion.CLASIFICAR)


def test_s2_exige_nucleo_completo() -> None:
    """§7.1: con una señal AUSENTE, S2 es inalcanzable por construcción."""
    d = decidir(obs(apetito=None))
    assert d.criterio is not Criterio.S2
    assert d.accion is Accion.REPREGUNTAR


def test_s3_amarillo_saturado() -> None:
    d = decidir(obs(fiebre_c=37.6))
    assert (d.clase, d.criterio) == (Clase.AMARILLO, Criterio.S3)
    assert "s_fiebre" in d.disparadores


def test_s3_no_cierra_con_bandera_pendiente() -> None:
    """§4.1 punto 2: amarillo no es clase terminal con bandera roja pendiente."""
    d = decidir(obs(fiebre_c=37.6, herida=None))
    assert d.accion is Accion.REPREGUNTAR
    assert d.senal_a_indagar == "herida"


# --------------------------------------------------------------------------- #
# §7.4 — cierre forzado
# --------------------------------------------------------------------------- #
def test_cierre_forzado_temprano_con_una_senal() -> None:
    """§7.4: el patrón exacto de los 19 casos del dev set."""
    d = decidir(obs_temprano(fiebre_c=37.6))
    assert d.accion is Accion.CLASIFICAR
    assert d.criterio is Criterio.CIERRE_FORZADO
    assert d.clase is Clase.VERDE
    assert d.n_total == 1


def test_cierre_forzado_no_repregunta_con_vector_completo() -> None:
    """`REPREGUNTAR` es una acción: sin señal AUSENTE no existe, aunque sobre presupuesto."""
    d = decidir(obs_temprano(herida="eritema_leve"))
    assert d.accion is Accion.CLASIFICAR
    assert d.criterio is Criterio.CIERRE_FORZADO


# --------------------------------------------------------------------------- #
# §8 — escalamiento graduado al agotar presupuesto
# --------------------------------------------------------------------------- #
def test_agotamiento_con_bandera_pendiente_es_rojo() -> None:
    d = decidir(vacia(), presupuesto_agotado())
    assert d.clase is Clase.ROJO
    assert d.criterio is Criterio.AGOTAMIENTO
    assert set(d.disparadores) >= {"purulenta", "movilidad_incapacitante", "fiebre_franca"}


def test_agotamiento_sin_banderas_pendientes_es_amarillo() -> None:
    """§8: si ninguna bandera está en DESCONOCIDO, lo que puede faltar es apetito/sueño."""
    d = decidir(obs(apetito=None, sueno=None), presupuesto_agotado())
    assert d.clase is Clase.AMARILLO
    assert d.criterio is Criterio.AGOTAMIENTO
    assert MARCA_CONFIANZA_BAJA in d.marcas


def test_agotamiento_nunca_cierra_en_verde() -> None:
    """§8.1, caso concreto. El property test general está en test_contrato.py."""
    d = decidir(obs(apetito=None), presupuesto_agotado())
    assert d.clase is not Clase.VERDE


# --------------------------------------------------------------------------- #
# §8.2 — errores de invocación
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "cambios",
    [
        {"dolor_nrs": 11},
        {"dolor_nrs": -1},
        {"dolor_nrs": 4.5},
        {"dolor_nrs": "cinco"},
        {"dolor_nrs": True},
        {"fiebre_c": "38.0"},
        {"fiebre_c": float("nan")},
        {"fiebre_c": math.inf},
        {"herida": "roja"},
        {"movilidad": "normal_"},
        {"apetito": "poco"},
        {"sueno": "MUY_ALTERADO"},
    ],
)
def test_entradas_imposibles_lanzan(cambios: dict[str, object]) -> None:
    with pytest.raises(ErrorDeInvocacion):
        decidir(obs(**cambios))


def test_error_de_invocacion_es_valueerror() -> None:
    assert issubclass(ErrorDeInvocacion, ValueError)


def test_ausencia_no_es_error() -> None:
    """§8.2: AUSENTE es valor legítimo de toda señal; se maneja por §1.1, no por excepción."""
    assert decidir(vacia()).accion is Accion.REPREGUNTAR


# --------------------------------------------------------------------------- #
# Par de colisión (D5) — la política discrimina por vector, no por termómetro
# --------------------------------------------------------------------------- #
COLISION_AMARILLO = Observacion(
    dia_postop=7, dolor_nrs=4, fiebre_c=37.9, herida="eritema_leve",
    movilidad="normal", apetito="levemente_disminuido", sueno="levemente_alterado",
)
COLISION_ROJO = Observacion(
    dia_postop=7, dolor_nrs=9, fiebre_c=37.9, herida="eritema_leve",
    movilidad="normal", apetito="muy_disminuido", sueno="muy_alterado",
)


def test_par_de_colision() -> None:
    """`…00012_7` vs `…00017_7`: misma fiebre (37.9) y misma herida al día 7.

    `movilidad` no consta en la tabla de D5; se fija en `normal` porque ninguno de
    los dos casos dispara la bandera de movilidad — cualquier valor distinto de
    `incapacitante_nueva` da el mismo resultado. El dev set los verifica con su
    vector real en `test_dev_set.py`.
    """
    amarillo = decidir(COLISION_AMARILLO)
    rojo = decidir(COLISION_ROJO)

    assert amarillo.clase is Clase.AMARILLO
    assert rojo.clase is Clase.ROJO
    assert rojo.criterio is Criterio.S1
    assert "dolor_severo" in rojo.disparadores
    # Ningún umbral de fiebre los separa: la fiebre es idéntica.
    assert COLISION_AMARILLO.fiebre_c == COLISION_ROJO.fiebre_c
    assert amarillo.banderas["fiebre_franca"] is rojo.banderas["fiebre_franca"] is F
