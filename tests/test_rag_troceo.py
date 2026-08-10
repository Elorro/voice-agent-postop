"""Troceo, normalización y detección de idioma. Sin chromadb y sin modelo.

Lo que se verifica aquí es lo que hace CITABLE un fragmento: que no exceda el
techo del embedder (o sería texto que se pierde en silencio), que no parta una
oración por la mitad, y que la página que viaja en el metadato sea la página
donde el fragmento empieza de verdad.
"""

from __future__ import annotations

import pytest

from app.rag import idioma, troceo
from app.rag.tipos import Pagina


def paginas(*textos: str) -> list[Pagina]:
    return [Pagina(i, t) for i, t in enumerate(textos, 1)]


# --------------------------------------------------------------------------- #
# Normalización
# --------------------------------------------------------------------------- #
def test_une_la_palabra_partida_por_guion_al_final_de_linea() -> None:
    """Sin esto, la palabra clave del documento no existe para el buscador."""
    assert "apendicectomía" in troceo.normalizar("apendicec-\ntomía del paciente")


def test_colapsa_espacios_pero_conserva_el_salto_de_linea_simple() -> None:
    salida = troceo.normalizar("uno    dos\ntres")
    assert salida == "uno dos\ntres"


def test_descarta_caracteres_de_control() -> None:
    assert "\x00" not in troceo.normalizar("texto\x00con basura")


# --------------------------------------------------------------------------- #
# Oraciones
# --------------------------------------------------------------------------- #
def test_corta_por_punto_interrogacion_y_punto_y_coma() -> None:
    texto = "Primera. ¿Segunda? Tercera; cuarta."
    encontradas = [o.strip() for _, o in troceo.oraciones(texto)]
    assert encontradas == ["Primera.", "¿Segunda?", "Tercera;", "cuarta."]


def test_los_desplazamientos_apuntan_al_texto_real() -> None:
    texto = "Uno. Dos. Tres."
    for desplazamiento, oracion in troceo.oraciones(texto):
        assert texto[desplazamiento : desplazamiento + len(oracion)] == oracion


# --------------------------------------------------------------------------- #
# Troceo
# --------------------------------------------------------------------------- #
def test_ningun_trozo_supera_el_tope() -> None:
    """El tope no es estético: por encima, el embedder trunca y el texto sobrante
    deja de existir para el buscador."""
    texto = " ".join(f"Oración número {i} del documento de prueba." for i in range(200))
    trozos = troceo.trocear(paginas(texto), max_caracteres=300, solape_caracteres=60)
    assert trozos
    assert all(len(t.texto) <= 300 for t in trozos)


def test_hay_solape_entre_trozos_consecutivos() -> None:
    texto = " ".join(f"Frase {i} con algo de contenido clínico." for i in range(60))
    trozos = troceo.trocear(paginas(texto), max_caracteres=300, solape_caracteres=80)
    assert len(trozos) >= 3
    # La cola de un trozo tiene que reaparecer al comienzo del siguiente.
    for anterior, siguiente in zip(trozos, trozos[1:]):
        cola = anterior.texto.split()[-4:]
        assert " ".join(cola) in siguiente.texto


def test_sin_solape_no_se_repite_nada() -> None:
    texto = " ".join(f"Frase {i} corta." for i in range(40))
    trozos = troceo.trocear(paginas(texto), max_caracteres=200, solape_caracteres=0)
    unido = " ".join(t.texto for t in trozos)
    # Cada frase aparece una sola vez.
    assert unido.count("Frase 7 corta.") == 1


def test_una_oracion_normal_nunca_queda_partida() -> None:
    """El troceo empaqueta oraciones enteras: es lo que evita que la frase con el
    dato clínico quede a medias en todos los trozos donde aparece."""
    clave = "Consulte de inmediato si la temperatura supera treinta y ocho grados."
    relleno = " ".join(f"Relleno {i}." for i in range(40))
    trozos = troceo.trocear(
        paginas(f"{relleno} {clave} {relleno}"), max_caracteres=300, solape_caracteres=80
    )
    assert any(clave in t.texto for t in trozos)


def test_una_oracion_mas_larga_que_el_tope_se_parte_por_espacios() -> None:
    larga = "palabra " * 200
    trozos = troceo.trocear(paginas(larga), max_caracteres=120, solape_caracteres=20)
    assert trozos
    assert all(len(t.texto) <= 120 for t in trozos)
    assert all(not t.texto.startswith("abra") for t in trozos)  # no parte palabras


def test_la_pagina_es_la_del_comienzo_del_trozo() -> None:
    p1 = "Alfa. " * 30
    p2 = "Beta. " * 30
    trozos = troceo.trocear(paginas(p1, p2), max_caracteres=200, solape_caracteres=0)
    assert trozos[0].pagina == 1
    assert trozos[-1].pagina == 2
    # Ningún trozo se atribuye a una página inexistente.
    assert all(t.pagina in (1, 2) for t in trozos)


def test_las_paginas_vacias_no_rompen_la_atribucion() -> None:
    trozos = troceo.trocear(
        paginas("", "Contenido de la segunda página. " * 10, ""),
        max_caracteres=200,
        solape_caracteres=0,
    )
    assert trozos and all(t.pagina == 2 for t in trozos)


def test_documento_sin_texto_no_produce_trozos() -> None:
    assert troceo.trocear(paginas("", "   "), max_caracteres=200, solape_caracteres=0) == []


def test_parametros_incoherentes_fallan_ruidoso() -> None:
    with pytest.raises(ValueError):
        troceo.trocear(paginas("hola"), max_caracteres=100, solape_caracteres=100)
    with pytest.raises(ValueError):
        troceo.trocear(paginas("hola"), max_caracteres=0, solape_caracteres=0)


def test_el_troceo_es_determinista() -> None:
    """Reejecutar el indexador tiene que reproducir el mismo índice."""
    texto = " ".join(f"Oración {i} del corpus." for i in range(120))
    a = troceo.trocear(paginas(texto), max_caracteres=400, solape_caracteres=100)
    b = troceo.trocear(paginas(texto), max_caracteres=400, solape_caracteres=100)
    assert a == b


# --------------------------------------------------------------------------- #
# Idioma
# --------------------------------------------------------------------------- #
def test_detecta_español_e_ingles() -> None:
    assert idioma.detectar(
        "El paciente debe consultar con su equipo quirúrgico si aparece fiebre "
        "durante los primeros días después de la cirugía."
    ) == idioma.ES
    assert idioma.detectar(
        "The patient should contact the surgical team if fever appears during "
        "the first days after the operation."
    ) == idioma.EN


def test_sin_palabras_funcion_el_idioma_es_indeterminado() -> None:
    """Se declara, no se adivina: una tabla de números no tiene idioma."""
    assert idioma.detectar("12345 67890 ---") == idioma.INDETERMINADO
    assert idioma.detectar("") == idioma.INDETERMINADO


def test_las_tildes_no_cambian_el_conteo() -> None:
    con, _ = idioma.contar_funcionales("según el protocolo")
    sin, _ = idioma.contar_funcionales("segun el protocolo")
    assert con == sin == 2
