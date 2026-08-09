"""Contrato del módulo: HD6 (orden de indagación), HD7 (presupuesto), pureza e invariantes."""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest

import politica
from apoyo import BASE_TARDIO, barrido, obs, obs_temprano, presupuesto_agotado, vacia
from politica import (
    Accion,
    Clase,
    Criterio,
    Decision,
    Observacion,
    Presupuesto,
    Regimen,
    Trivalor,
    decidir,
)
from politica.motor import NUCLEO, contar, nivel_1_5, nivel_2, senal_a_indagar
from politica.parametros import (
    TOPE_GLOBAL,
    TOPE_POR_SENAL,
    UMBRAL_G_DOLOR,
    UMBRAL_G_FIEBRE,
    UMBRAL_S_DOLOR,
    UMBRAL_S_FIEBRE,
)

V, F, D = Trivalor.VERDADERO, Trivalor.FALSO, Trivalor.DESCONOCIDO


# --------------------------------------------------------------------------- #
# §1.2 — el núcleo se deriva, no se enumera
# --------------------------------------------------------------------------- #
def test_nucleo_son_las_seis_senales_y_no_incluye_dia_postop() -> None:
    assert set(NUCLEO) == {"herida", "movilidad", "fiebre_c", "dolor_nrs", "apetito", "sueno"}
    assert "dia_postop" not in NUCLEO
    assert len(NUCLEO) == 6


# --------------------------------------------------------------------------- #
# HD6 — orden determinista de indagación (§7.3)
# --------------------------------------------------------------------------- #
def test_nivel_1_tiene_prioridad_y_su_orden_es_el_de_la_spec() -> None:
    """Adyacentes a bandera en DESCONOCIDO, en orden §3: herida, movilidad, fiebre, dolor."""
    d = decidir(vacia())
    assert d.senal_a_indagar == "herida"
    assert decidir(vacia(herida="normal")).senal_a_indagar == "movilidad"
    assert decidir(vacia(herida="normal", movilidad="normal")).senal_a_indagar == "fiebre_c"
    assert (
        decidir(vacia(herida="normal", movilidad="normal", fiebre_c=36.6)).senal_a_indagar
        == "dolor_nrs"
    )


def test_el_dolor_entra_al_nivel_1_tambien_en_temprano() -> None:
    """Con umbral por régimen (§3.1) la bandera de dolor queda pendiente en temprano.

    Antes de esa decisión el dolor colapsaba a `FALSO` en temprano y caía al último
    nivel de §7.3, detrás de apetito y sueño.
    """
    parcial = obs_temprano(dolor_nrs=None, apetito=None, sueno=None)
    assert decidir(parcial).senal_a_indagar == "dolor_nrs"


def test_nivel_3_cuando_no_hay_bandera_pendiente() -> None:
    """Con las cuatro señales de bandera conocidas mandan los discriminadores de §5.1."""
    assert decidir(obs_temprano(apetito=None, sueno=None)).senal_a_indagar == "apetito"
    assert decidir(obs_temprano(sueno=None)).senal_a_indagar == "sueno"


def test_nivel_1_5_precede_a_los_discriminadores() -> None:
    """HD6 nivel 2: señales que resolverían la compuerta en DESCONOCIDO, antes que §5.

    Estado no alcanzable hoy desde `decidir` —si `fiebre_c` está AUSENTE su bandera
    queda en DESCONOCIDO y el nivel 1 se la lleva—, así que se prueba directamente
    sobre la función de orden: es la regla lo que se fija, no su alcance actual.
    """
    banderas_descartadas = dict.fromkeys(
        ("purulenta", "movilidad_incapacitante", "fiebre_franca", "dolor_severo"), F
    )
    elegida = senal_a_indagar(
        obs(fiebre_c=None, apetito=None),
        banderas_descartadas,
        D,
        Presupuesto({}, 0),
    )
    assert elegida == "apetito"


def test_tope_por_senal_descarta_la_senal_no_la_pregunta() -> None:
    gastado = Presupuesto({"herida": TOPE_POR_SENAL}, TOPE_POR_SENAL)
    assert decidir(vacia(), gastado).senal_a_indagar == "movilidad"


def test_tope_global_cierra_en_vez_de_repreguntar() -> None:
    d = decidir(vacia(), Presupuesto({}, TOPE_GLOBAL))
    assert d.accion is Accion.CLASIFICAR
    assert d.criterio is Criterio.AGOTAMIENTO


def test_topes_son_inyectables() -> None:
    """§7.2 es [ESPECULACIÓN] pendiente de Fase 3: no se hornea en la lógica."""
    assert decidir(vacia(), tope_global=0).accion is Accion.CLASIFICAR
    holgado = decidir(vacia(), Presupuesto({}, TOPE_GLOBAL), tope_global=TOPE_GLOBAL + 1)
    assert holgado.accion is Accion.REPREGUNTAR


def test_los_tres_niveles_cubren_las_seis_senales() -> None:
    """Si una señal AUSENTE no fuera elegible por ningún nivel, sería inindagable."""
    for senal in NUCLEO:
        entrada = obs(**{senal: None})
        elegida = decidir(entrada).senal_a_indagar
        assert elegida == senal, f"{senal} ausente y el módulo pregunta por {elegida}"


def test_orden_de_indagacion_es_determinista() -> None:
    entrada = vacia(fiebre_c=37.6)
    assert decidir(entrada).senal_a_indagar == decidir(entrada).senal_a_indagar


# --------------------------------------------------------------------------- #
# HD7 — contabilidad del presupuesto: el módulo lee, el llamador cobra
# --------------------------------------------------------------------------- #
def test_el_modulo_no_muta_el_presupuesto() -> None:
    gastos = {"herida": 1}
    presupuesto = Presupuesto(gastos, 1)
    decidir(vacia(), presupuesto)
    assert gastos == {"herida": 1}
    assert dict(presupuesto.preguntas_por_senal) == {"herida": 1}
    assert presupuesto.preguntas_totales == 1


def test_presupuesto_copia_en_la_frontera() -> None:
    """Mutar el dict del llamador después no puede alterar un presupuesto ya construido."""
    gastos = {"herida": 1}
    presupuesto = Presupuesto(gastos, 1)
    gastos["herida"] = 99
    assert presupuesto.gastadas("herida") == 1
    with pytest.raises(TypeError):
        presupuesto.preguntas_por_senal["herida"] = 2  # type: ignore[index]


def _conversar(entrada: Observacion, respuestas: dict[str, object]) -> list[str]:
    """Aplica el contrato de HD7 turno a turno hasta que el módulo cierra."""
    actual, presupuesto, preguntadas = entrada, Presupuesto({}, 0), []
    for _ in range(TOPE_GLOBAL * len(NUCLEO) + 5):  # cota dura: si no cierra, es bug
        d = decidir(actual, presupuesto)
        if d.accion is Accion.CLASIFICAR:
            assert d.clase is not None
            return preguntadas
        senal = d.senal_a_indagar
        assert senal is not None
        preguntadas.append(senal)
        gastos = dict(presupuesto.preguntas_por_senal)
        gastos[senal] = gastos.get(senal, 0) + 1
        presupuesto = Presupuesto(gastos, presupuesto.preguntas_totales + 1)
        if senal in respuestas:
            actual = replace(actual, **{senal: respuestas[senal]})
    raise AssertionError("el módulo no cerró: la indagación no termina")


def test_paciente_evasivo_termina_en_cierre() -> None:
    """Nadie responde nunca: el presupuesto tiene que morder y el módulo cerrar."""
    preguntadas = _conversar(vacia(), respuestas={})
    assert len(preguntadas) == TOPE_GLOBAL
    # Con tope por señal 2 y tope global 6, las tres primeras señales de §7.3 se
    # agotan antes de que la conversación llegue a los discriminadores.
    assert preguntadas == ["herida", "herida", "movilidad", "movilidad", "fiebre_c", "fiebre_c"]
    final = decidir(vacia(), Presupuesto({s: TOPE_POR_SENAL for s in NUCLEO[:3]}, TOPE_GLOBAL))
    assert final.clase is Clase.ROJO  # queda bandera en DESCONOCIDO (§8)


def test_paciente_cooperativo_converge() -> None:
    respuestas = {senal: BASE_TARDIO[senal] for senal in NUCLEO}
    preguntadas = _conversar(vacia(dia_postop=7), respuestas)
    assert preguntadas == list(NUCLEO)  # una pregunta por señal, sin repetir
    assert decidir(obs()).clase is Clase.VERDE


# --------------------------------------------------------------------------- #
# Pureza
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "entrada,presupuesto",
    [
        (obs(), Presupuesto({}, 0)),
        (vacia(), Presupuesto({"herida": 1}, 1)),
        (obs_temprano(fiebre_c=37.6), presupuesto_agotado()),
    ],
)
def test_dos_llamadas_iguales_dan_resultados_iguales(
    entrada: Observacion, presupuesto: Presupuesto
) -> None:
    primera = decidir(entrada, presupuesto)
    segunda = decidir(entrada, presupuesto)
    assert primera == segunda
    assert primera.banderas == segunda.banderas


def test_la_decision_es_inmutable() -> None:
    d = decidir(obs())
    with pytest.raises(Exception):
        d.clase = Clase.ROJO  # type: ignore[misc]
    with pytest.raises(TypeError):
        d.banderas["purulenta"] = V  # type: ignore[index]


def test_el_modulo_solo_importa_libreria_estandar_inocua() -> None:
    """Sin estado, sin I/O, sin voz, sin RAG, sin pandas (restricción de Fase 1)."""
    permitidos = {"__future__", "math", "typing", "dataclasses", "enum", "types"}
    raiz = Path(politica.__file__).parent
    for archivo in sorted(raiz.glob("*.py")):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                nombres = {alias.name.split(".")[0] for alias in nodo.names}
            elif isinstance(nodo, ast.ImportFrom):
                if nodo.level > 0:  # import relativo dentro del paquete
                    continue
                nombres = {(nodo.module or "").split(".")[0]}
            else:
                continue
            prohibidos = nombres - permitidos
            assert not prohibidos, f"{archivo.name} importa {prohibidos}"


# --------------------------------------------------------------------------- #
# Property test §4↔§5 — invariante de consistencia (§7.4)
# --------------------------------------------------------------------------- #
REJILLA_COMPLETA_TARDIO: dict[str, tuple[object, ...]] = {
    "dia_postop": (7,),
    "dolor_nrs": tuple(range(0, 11)),
    "fiebre_c": (36.0, 37.4, 37.5, 37.7, 37.8, 37.9, 38.0, 39.5),
    "herida": ("normal", "eritema_leve", "secrecion_purulenta"),
    "movilidad": ("normal", "limitada_esperada", "incapacitante_nueva"),
    "apetito": ("normal", "levemente_disminuido", "muy_disminuido"),
    "sueno": ("normal", "levemente_alterado", "muy_alterado"),
}


def test_invariante_compuerta_implica_conteo() -> None:
    """§7.4: en régimen tardío, compuerta 1.5 activa ⟹ `n_total >= 1`.

    Depende de los VALORES actuales, no de la estructura: si el anclaje al corpus
    (deuda RAG bloqueante) mueve cualquiera de los cuatro umbrales, la implicación
    se rompe. El paso 2 del filtro de §7.4 mantiene la salida correcta aunque se
    rompa; este test existe para que la ruptura sea ruidosa en vez de silenciosa.
    """
    assert UMBRAL_G_FIEBRE >= UMBRAL_S_FIEBRE, (
        "g_fiebre bajó por debajo de s_fiebre: la implicación §4⟹§5 ya no se sostiene"
    )
    assert UMBRAL_G_DOLOR >= UMBRAL_S_DOLOR, (
        "g_dolor bajó por debajo de s_dolor: la implicación §4⟹§5 ya no se sostiene"
    )

    contraejemplos = []
    for entrada in barrido(REJILLA_COMPLETA_TARDIO):
        if nivel_1_5(entrada, Regimen.TARDIO) is V:
            if contar(nivel_2(entrada, Regimen.TARDIO)) < 1:
                contraejemplos.append(entrada)
    assert not contraejemplos, f"{len(contraejemplos)} contraejemplos, p.ej. {contraejemplos[:1]}"


# --------------------------------------------------------------------------- #
# Property test §8.1 — invariante duro
# --------------------------------------------------------------------------- #
PRESUPUESTOS = (
    Presupuesto({}, 0),
    Presupuesto({senal: TOPE_POR_SENAL for senal in NUCLEO}, TOPE_GLOBAL),
)


def test_invariante_duro_nunca_verde_con_evidencia_insuficiente() -> None:
    """§8.1. Property sobre el espacio de entradas, no sobre los 160 casos."""
    fallos = []
    for entrada in barrido():
        if all(getattr(entrada, senal) is not None for senal in NUCLEO):
            continue
        for presupuesto in PRESUPUESTOS:
            d = decidir(entrada, presupuesto)
            if d.clase is Clase.VERDE:
                fallos.append((entrada, presupuesto))
    assert not fallos, f"{len(fallos)} cierres en VERDE con núcleo incompleto: {fallos[:2]}"


def test_contrato_de_la_decision_sobre_el_espacio_de_entradas() -> None:
    """Los campos de `Decision` son consistentes en todo el barrido (HD5)."""
    for entrada in barrido():
        for presupuesto in PRESUPUESTOS:
            d = decidir(entrada, presupuesto)
            repregunta = d.accion is Accion.REPREGUNTAR
            assert (d.clase is None) is repregunta
            assert (d.criterio is None) is repregunta
            assert (d.senal_a_indagar is not None) is repregunta
            if repregunta:
                assert d.senal_a_indagar in NUCLEO
                assert getattr(entrada, d.senal_a_indagar) is None
                assert presupuesto.gastadas(d.senal_a_indagar) < TOPE_POR_SENAL
                assert presupuesto.preguntas_totales < TOPE_GLOBAL
            assert set(d.banderas) == {
                "purulenta", "movilidad_incapacitante", "fiebre_franca", "dolor_severo"
            }
            assert d.n_total >= 0
            if d.regimen is Regimen.TEMPRANO:
                assert d.compuerta is F  # §4: SOLO_TARDÍO


def test_s1_tiene_precedencia_absoluta() -> None:
    """§3: bandera VERDADERA ⟹ ROJO por S1, en cualquier régimen y con cualquier presupuesto."""
    for entrada in barrido():
        for presupuesto in PRESUPUESTOS:
            d = decidir(entrada, presupuesto)
            if any(valor is V for valor in d.banderas.values()):
                assert (d.clase, d.criterio) == (Clase.ROJO, Criterio.S1)


def test_bandera_pendiente_al_cerrar_es_rojo() -> None:
    """§4.1 punto 2 / §7.4 paso 1 / §8: no se cierra en AMARILLO con bandera sin descartar."""
    for entrada in barrido():
        d = decidir(entrada, PRESUPUESTOS[1])
        if d.accion is Accion.CLASIFICAR and any(v is D for v in d.banderas.values()):
            assert d.clase is Clase.ROJO
