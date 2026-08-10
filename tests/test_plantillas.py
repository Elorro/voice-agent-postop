"""El piso está completo: hay texto para cada señal y para cada clase.

La cobertura se comprueba **contra la política**, no contra una lista escrita en
el test. Si mañana el núcleo gana una séptima señal, esto falla antes de que un
paciente se encuentre con un agente que no sabe qué preguntar.
"""

from __future__ import annotations

import pytest

from politica import Clase
from politica.motor import NUCLEO

from app.dialogo import plantillas


@pytest.mark.parametrize("senal", NUCLEO)
def test_cada_senal_del_nucleo_tiene_repregunta(senal: str) -> None:
    assert plantillas.REPREGUNTAS.get(senal)
    assert plantillas.REPREGUNTAS_INSISTENCIA.get(senal)


@pytest.mark.parametrize("clase", [c.name for c in Clase])
def test_cada_clase_tiene_guion_de_cierre(clase: str) -> None:
    assert plantillas.CIERRES.get(clase)


def test_no_sobran_plantillas() -> None:
    """Una repregunta para una señal que la política no indaga es texto muerto:
    nadie la va a emitir nunca y confunde a quien lea el módulo."""
    assert set(plantillas.REPREGUNTAS) == set(NUCLEO)
    assert set(plantillas.REPREGUNTAS_INSISTENCIA) == set(NUCLEO)


def test_la_insistencia_es_mas_corta_que_la_primera_pregunta() -> None:
    """Repetir la misma frase a quien no la entendió gasta el segundo intento
    sin comprar nada."""
    for senal in NUCLEO:
        assert len(plantillas.REPREGUNTAS_INSISTENCIA[senal]) < len(
            plantillas.REPREGUNTAS[senal]
        )


def test_repregunta_elige_segun_los_intentos_previos() -> None:
    assert plantillas.repregunta("herida", 0) == plantillas.REPREGUNTAS["herida"]
    assert plantillas.repregunta("herida", 1) == plantillas.REPREGUNTAS_INSISTENCIA["herida"]
    assert plantillas.repregunta("herida", 5) == plantillas.REPREGUNTAS_INSISTENCIA["herida"]


def test_una_senal_sin_texto_falla_ruidoso() -> None:
    """Devolver una pregunta genérica sería peor: el agente preguntaría por una
    cosa y anotaría la respuesta en otra."""
    with pytest.raises(KeyError):
        plantillas.repregunta("presion_arterial")
    with pytest.raises(KeyError):
        plantillas.cierre("NARANJA")


def test_el_cierre_por_agotamiento_avisa_de_la_evidencia_incompleta() -> None:
    texto = plantillas.cierre("ROJO", "AGOTAMIENTO")
    assert plantillas.CIERRES["ROJO"] in texto
    assert texto != plantillas.CIERRES["ROJO"]
    assert plantillas.cierre("VERDE", "S2") == plantillas.CIERRES["VERDE"]


def test_las_repreguntas_enuncian_el_dominio_cerrado() -> None:
    """Una pregunta abierta le traslada al LLM la tarea de inventar la
    categoría, que es justo lo que el contrato del extractor prohíbe. Las
    categóricas tienen que ofrecer tres alternativas, y las numéricas, pedir un
    número."""
    for senal in ("herida", "movilidad", "apetito", "sueno"):
        texto = plantillas.REPREGUNTAS[senal]
        assert texto.count(",") >= 2, texto
    assert "cero" in plantillas.REPREGUNTAS["dolor_nrs"]
    assert "grados" in plantillas.REPREGUNTAS["fiebre_c"]


def test_la_declaracion_de_limite_no_promete_una_respuesta() -> None:
    texto = plantillas.LIMITE_CLINICO.lower()
    assert "no puedo" in texto
    assert "automatizado" in texto
