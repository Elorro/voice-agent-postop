"""La generación desde fragmentos: separación dato/instrucción y guardas.

La propiedad que estos tests fijan es una sola y es la que evita la alucinación
clínica: **no existe ruta en la que el modelo redacte una respuesta clínica sin
fragmentos**. Todo lo demás —delimitación, guardas de forma, marca de «no está en
las fuentes»— es defensa en profundidad detrás de esa propiedad.
"""

from __future__ import annotations

from app.contratos import OK, TIMEOUT, SalidaLLM
from app.rag import respuesta
from app.rag.tipos import Fragmento


def frag(texto: str = "Mantenga la herida limpia y seca.", pagina: int = 4) -> Fragmento:
    return Fragmento(
        texto=texto,
        score=0.7,
        ruta_relativa="Appendicitis/plan de cuidado.pdf",
        pagina=pagina,
        escenario="Appendicitis",
        idioma="es",
        origen="corpus",
    )


class LLMEspia:
    def __init__(self, texto: str = "Mantenga la herida limpia.", resultado: str = OK) -> None:
        self.texto = texto
        self.resultado = resultado
        self.mensajes: list[list[dict[str, str]]] = []

    def __call__(self, mensajes, **kwargs) -> SalidaLLM:
        self.mensajes.append(mensajes)
        return SalidaLLM(self.texto, 5.0, self.resultado, "modelo-de-prueba", 30, 20)


# --------------------------------------------------------------------------- #
# La propiedad central
# --------------------------------------------------------------------------- #
def test_sin_fragmentos_no_se_invoca_al_modelo() -> None:
    llm = LLMEspia()
    texto, fuente, salida = respuesta.responder(llm, "¿me puedo bañar?", [], timeout_ms=1000)
    assert llm.mensajes == []
    assert texto == respuesta.SIN_FUENTE
    assert salida.resultado == "no_invocado"
    assert fuente == respuesta.FUENTE_RAG_SIN_MODELO


def test_la_declaracion_de_limite_dice_que_no_esta_en_las_fuentes() -> None:
    """Es lo que la rúbrica premia: decirlo, no improvisar."""
    texto = respuesta.SIN_FUENTE.lower()
    assert "no tengo información" in texto
    assert "fuentes" in texto


# --------------------------------------------------------------------------- #
# Separación dato / instrucción
# --------------------------------------------------------------------------- #
def test_la_instruccion_va_en_system_y_el_corpus_en_user() -> None:
    mensajes = respuesta.construir_mensajes("¿cómo cuido la herida?", [frag()])
    assert mensajes[0]["role"] == "system"
    assert mensajes[0]["content"] == respuesta.PROMPT_SISTEMA
    assert mensajes[1]["role"] == "user"
    assert len(mensajes) == 2


def test_los_fragmentos_entran_delimitados_y_con_su_procedencia() -> None:
    mensajes = respuesta.construir_mensajes("consulta", [frag(pagina=12)])
    cuerpo = mensajes[1]["content"]
    assert "<fuentes>" in cuerpo and "</fuentes>" in cuerpo
    assert 'documento="Appendicitis/plan de cuidado.pdf"' in cuerpo
    assert 'pagina="12"' in cuerpo


def test_el_prompt_de_sistema_es_distinto_del_redactor_y_del_extractor() -> None:
    from app.dialogo.orquestador import contrato_extraccion
    from app.llm.extractor import prompt_sistema
    from app.llm.redactor import PROMPT_SISTEMA as PROMPT_REDACTOR
    from tests.apoyo_turno import config_de_prueba
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        cfg = config_de_prueba(Path(tmp))
        prompt_extractor = prompt_sistema(contrato_extraccion(cfg))

    assert respuesta.PROMPT_SISTEMA not in (prompt_extractor, PROMPT_REDACTOR)


def test_el_prompt_declara_las_fuentes_como_dato_y_prohibe_diagnosticar() -> None:
    texto = respuesta.PROMPT_SISTEMA.lower()
    assert "dato" in texto and "instrucciones" in texto
    assert "no diagnostiques" in texto


def test_la_primera_regla_del_prompt_es_declarar_el_limite() -> None:
    """La segunda línea de defensa, y la que hace tolerable un umbral bajo: el
    umbral resuelve «el corpus no habla del tema», no «habla del tema y aun así
    no responde ESTA pregunta». Va primera, no como nota al final."""
    reglas = respuesta.PROMPT_SISTEMA.split("\n")
    primera = next(r for r in reglas if r.startswith("1."))
    assert respuesta.MARCA_SIN_RESPUESTA in primera
    minuscula = primera.lower()
    assert "no responden la pregunta" in minuscula
    assert "no" in minuscula and "fuerces" in minuscula


def test_el_prompt_cubre_el_caso_de_fuentes_del_mismo_tema_que_no_contestan() -> None:
    """Es justo el caso que deja pasar un umbral generoso, así que tiene que estar
    dicho y no quedar implícito en «no contienen la respuesta»."""
    texto = respuesta.PROMPT_SISTEMA.lower()
    assert "mismo tema" in texto
    assert "rozan" in texto
    assert "por tu cuenta" in texto


# --------------------------------------------------------------------------- #
# Guardas
# --------------------------------------------------------------------------- #
def test_el_timeout_cae_a_sin_modelo_y_no_a_sin_fuente() -> None:
    """Mentir sobre el corpus sería peor: el registro lleva las citas de esos
    fragmentos y contradiría a la voz."""
    llm = LLMEspia(resultado=TIMEOUT)
    texto, fuente, _ = respuesta.responder(llm, "consulta", [frag()], timeout_ms=100)
    assert texto == respuesta.SIN_MODELO
    assert fuente == respuesta.FUENTE_RAG_SIN_MODELO


def test_la_marca_convenida_devuelve_la_declaracion_de_limite() -> None:
    llm = LLMEspia(texto="NO_ESTA_EN_LAS_FUENTES")
    texto, _, _ = respuesta.responder(llm, "consulta", [frag()], timeout_ms=1000)
    assert texto == respuesta.SIN_FUENTE


def test_una_respuesta_kilometrica_se_descarta() -> None:
    llm = LLMEspia(texto="palabra " * 500)
    texto, fuente, _ = respuesta.responder(
        llm, "consulta", [frag()], timeout_ms=1000, max_caracteres=700
    )
    assert texto == respuesta.SIN_MODELO


def test_una_respuesta_en_lista_se_descarta() -> None:
    llm = LLMEspia(texto="- uno\n- dos\n- tres\n- cuatro")
    texto, _, _ = respuesta.responder(llm, "consulta", [frag()], timeout_ms=1000)
    assert texto == respuesta.SIN_MODELO


def test_una_respuesta_normal_pasa_y_se_marca_como_rag() -> None:
    llm = LLMEspia(texto='"Mantenga la herida limpia y seca. Consulte a su equipo."')
    texto, fuente, salida = respuesta.responder(llm, "consulta", [frag()], timeout_ms=1000)
    assert texto == "Mantenga la herida limpia y seca. Consulte a su equipo."
    assert fuente == respuesta.FUENTE_RAG_LLM
    assert salida.tokens_in == 30
