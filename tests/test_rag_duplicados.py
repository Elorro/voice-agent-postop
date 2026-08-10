"""Detección de duplicados exactos y casi exactos.

El caso que motivó este módulo está en su docstring y es real: dos exportaciones
del mismo artículo que difieren en el encabezado del editor. El SHA-256 no las
ve, y el buscador terminaba gastando dos de los cinco puestos del top-k en decir
lo mismo.
"""

from __future__ import annotations

from app.rag import duplicados

BASE = (
    "Después de la apendicectomía el paciente debe mantener la herida limpia y "
    "seca durante las primeras cuarenta y ocho horas. Consulte con su equipo "
    "quirúrgico si aparece fiebre, si la herida supura o si el dolor aumenta de "
    "forma sostenida. La movilización temprana reduce el riesgo de complicaciones "
    "respiratorias y trombóticas, y se recomienda desde el primer día. "
) * 4


def test_canonizar_borra_tildes_y_puntuacion() -> None:
    assert duplicados.canonizar("Después, ¡ATENCIÓN!: la herida.") == [
        "despues",
        "atencion",
        "la",
        "herida",
    ]


def test_un_texto_identico_se_detecta_como_exacto() -> None:
    detector = duplicados.Detector()
    assert detector.evaluar("a.pdf", BASE) == (None, 0.0, "")
    gemelo, similitud, motivo = detector.evaluar("b.pdf", BASE)
    assert (gemelo, similitud, motivo) == ("a.pdf", 1.0, "exacto")


def test_el_encabezado_distinto_no_salva_al_duplicado() -> None:
    """El caso real del corpus: `Vol.:(0123456789)1 3` contra `Vol:.(1234567890)`.
    Dos caracteres de maquetación y el hash ya no coincide."""
    detector = duplicados.Detector()
    detector.evaluar("original.pdf", "Vol.:(0123456789)1 3\n" + BASE)
    gemelo, similitud, motivo = detector.evaluar("copia.pdf", "Vol:.(1234567890)\n" + BASE)
    assert gemelo == "original.pdf"
    assert motivo == "solapamiento"
    assert similitud > 0.9


def test_dos_guias_distintas_del_mismo_tema_no_son_duplicados() -> None:
    """El error caro sería el contrario: descartar un documento legítimo porque
    habla de lo mismo que otro. Todo el corpus habla de lo mismo."""
    otra = (
        "El reemplazo total de rodilla exige un programa de rehabilitación "
        "progresivo. La marcha con apoyo se inicia habitualmente en las primeras "
        "veinticuatro horas y la flexión activa se trabaja desde la primera "
        "semana, según tolerancia del paciente y criterio del cirujano tratante. "
    ) * 4
    detector = duplicados.Detector()
    detector.evaluar("apendice.pdf", BASE)
    gemelo, _, _ = detector.evaluar("rodilla.pdf", otra)
    assert gemelo is None


def test_un_texto_muy_corto_no_produce_huella() -> None:
    """Dos textos de veinte palabras pueden coincidir por casualidad; con menos
    del mínimo, el Jaccard no significa nada y no se usa."""
    assert duplicados.huella("tres palabras aquí") == frozenset()
    detector = duplicados.Detector()
    detector.evaluar("a.txt", "una frase corta cualquiera")
    gemelo, _, motivo = detector.evaluar("b.txt", "otra frase corta cualquiera")
    assert gemelo is None


def test_jaccard_es_simetrico_y_acotado() -> None:
    a = duplicados.huella(BASE)
    b = duplicados.huella(BASE + " Un párrafo adicional que no estaba antes. " * 3)
    assert duplicados.jaccard(a, b) == duplicados.jaccard(b, a)
    assert 0.0 < duplicados.jaccard(a, b) < 1.0
    assert duplicados.jaccard(a, a) == 1.0
    assert duplicados.jaccard(a, frozenset()) == 0.0


def test_el_primero_en_orden_es_el_que_se_queda() -> None:
    """Determinismo: el indexador recorre en orden alfabético de ruta, así que
    reejecutarlo descarta siempre el mismo archivo."""
    detector = duplicados.Detector()
    detector.evaluar("aaa.pdf", BASE)
    detector.evaluar("zzz.pdf", BASE)
    gemelo, _, _ = detector.evaluar("mmm.pdf", BASE)
    assert gemelo == "aaa.pdf"
