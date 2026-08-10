"""El umbral de suficiencia: la compuerta que impide la alucinación clínica.

Un buscador de vecinos más cercanos SIEMPRE devuelve k resultados. Sobre una
pregunta que el corpus no cubre devolverá los cinco trozos menos lejanos, y si
esos trozos llegan a un modelo con el encargo de responder, el modelo redacta
algo. Estos tests fijan que ese camino no existe.
"""

from __future__ import annotations

from app.rag import recuperacion
from app.rag.tipos import Fragmento


def frag(score: float, texto: str = "texto", pagina: int = 3) -> Fragmento:
    return Fragmento(
        texto=texto,
        score=score,
        ruta_relativa="Appendicitis/guia.pdf",
        pagina=pagina,
        escenario="Appendicitis",
        idioma="es",
        origen="corpus",
    )


def consultar_con(fragmentos):
    def consultar(consulta: str, k: int):
        return fragmentos[:k]

    return consultar


# --------------------------------------------------------------------------- #
# Umbral
# --------------------------------------------------------------------------- #
def test_por_debajo_del_umbral_devuelve_vacio() -> None:
    resultado = recuperacion.recuperar(
        consultar_con([frag(0.21), frag(0.19)]), "¿cuánto cuesta el pasaje?", k=5, umbral=0.35
    )
    assert resultado.fragmentos == ()
    assert resultado.suficiente is False
    # El mejor score rechazado se conserva: sin él, un umbral mal puesto es
    # indistinguible de un corpus que no cubre el tema.
    assert resultado.mejor_score == 0.21
    assert resultado.examinados == 2


def test_el_umbral_se_aplica_fragmento_a_fragmento() -> None:
    """No basta con que el mejor pase: el acompañante flojo es de donde el modelo
    saca la frase que nadie escribió."""
    resultado = recuperacion.recuperar(
        consultar_con([frag(0.80), frag(0.31), frag(0.72)]), "consulta", k=5, umbral=0.35
    )
    assert [f.score for f in resultado.fragmentos] == [0.80, 0.72]


def test_conserva_el_orden_del_indice() -> None:
    resultado = recuperacion.recuperar(
        consultar_con([frag(0.9, "a"), frag(0.5, "b"), frag(0.7, "c")]),
        "consulta",
        k=5,
        umbral=0.4,
    )
    assert [f.texto for f in resultado.fragmentos] == ["a", "b", "c"]


def test_respeta_k() -> None:
    resultado = recuperacion.recuperar(
        consultar_con([frag(0.9) for _ in range(10)]), "consulta", k=3, umbral=0.5
    )
    assert len(resultado.fragmentos) == 3


def test_consulta_vacia_no_toca_el_indice() -> None:
    llamadas = []

    def consultar(consulta, k):
        llamadas.append(consulta)
        return [frag(0.99)]

    resultado = recuperacion.recuperar(consultar, "   ", k=5, umbral=0.1)
    assert resultado.fragmentos == ()
    assert llamadas == []


def test_un_indice_que_revienta_no_tumba_el_turno() -> None:
    def consultar(consulta, k):
        raise RuntimeError("SQLite bloqueado")

    resultado = recuperacion.recuperar(consultar, "fiebre", k=5, umbral=0.3)
    assert resultado.fragmentos == ()
    assert "SQLite bloqueado" in resultado.error


# --------------------------------------------------------------------------- #
# Bloque de registro
# --------------------------------------------------------------------------- #
def test_el_bloque_de_registro_trae_las_citas_resolubles() -> None:
    resultado = recuperacion.recuperar(
        consultar_con([frag(0.71, "Mantenga la herida limpia y seca.", pagina=12)]),
        "¿cómo cuido la herida?",
        k=5,
        umbral=0.35,
    )
    bloque = resultado.a_registro(400)
    assert bloque["consultas"] == 1
    assert bloque["suficiente"] is True
    cita = bloque["citas"][0]
    assert cita["ruta_relativa"] == "Appendicitis/guia.pdf"
    assert cita["pagina"] == 12
    assert cita["texto_citado"] == "Mantenga la herida limpia y seca."
    assert cita["score"] == 0.71


def test_el_texto_citado_se_recorta_para_que_el_registro_siga_siendo_legible() -> None:
    largo = "palabra " * 200
    resultado = recuperacion.recuperar(
        consultar_con([frag(0.9, largo)]), "consulta", k=1, umbral=0.1
    )
    citado = resultado.a_registro(100)["citas"][0]["texto_citado"]
    assert len(citado) == 100
    assert citado.endswith("…")


def test_el_bloque_registra_tambien_la_consulta_rechazada() -> None:
    """Una pregunta sin respuesta tiene que quedar contada: es la métrica de
    cobertura del corpus."""
    resultado = recuperacion.recuperar(
        consultar_con([frag(0.10)]), "algo ajeno", k=5, umbral=0.35
    )
    bloque = resultado.a_registro(400)
    assert bloque["consultas"] == 1
    assert bloque["citas"] == []
    assert bloque["suficiente"] is False
    assert bloque["mejor_score"] == 0.1
    assert bloque["umbral"] == 0.35
