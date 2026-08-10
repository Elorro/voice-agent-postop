"""Inventario e ingesta de documentos subidos. Sin chromadb: el almacén es doble.

Lo que se fija aquí es el indicador que exige el reto: que «procesado y
disponible» signifique **fragmentos contados dentro del índice**, y no «el bucle
terminó sin excepción». Son cosas distintas y la segunda es la que miente.
"""

from __future__ import annotations

from pathlib import Path

from app.rag import documentos as doc


class AlmacenFalso:
    """Doble del almacén vectorial: guarda trozos en un diccionario."""

    def __init__(self, *, falla: bool = False, traga: bool = False) -> None:
        self.trozos: dict[str, list] = {}
        self.falla = falla
        self.traga = traga  # acepta el `add` y no deja nada dentro

    def agregar(self, trozos, **_):
        if self.falla:
            raise RuntimeError("índice de solo lectura")
        if not self.traga:
            for t in trozos:
                self.trozos.setdefault(t.documento_id, []).append(t)
        return len(trozos)

    def contar_documento(self, documento_id: str) -> int:
        return len(self.trozos.get(documento_id, []))

    def borrar_documento(self, documento_id: str) -> int:
        return len(self.trozos.pop(documento_id, []))


def registro_en(tmp_path: Path) -> doc.Registro:
    return doc.Registro(tmp_path / "inventario.json")


def escribir(tmp_path: Path, nombre: str, texto: str) -> Path:
    ruta = tmp_path / nombre
    ruta.write_text(texto, encoding="utf-8")
    return ruta


TEXTO = (
    "Después de la apendicectomía debe mantener la herida limpia y seca. "
    "Consulte con su equipo quirúrgico si aparece fiebre o si la herida supura. "
) * 6


# --------------------------------------------------------------------------- #
# Inventario
# --------------------------------------------------------------------------- #
def test_el_documento_nace_pendiente_y_persiste(tmp_path: Path) -> None:
    registro = registro_en(tmp_path)
    documento = registro.crear("guía.pdf", 1234, ".pdf")
    assert documento.estado == doc.PENDIENTE
    assert documento.archivo.endswith(".pdf")
    # El archivo en disco se llama por el identificador, nunca por el nombre del
    # cliente: es lo que hace que un «../../app/main.py» no construya una ruta.
    assert documento.id in documento.archivo

    otro = registro_en(tmp_path)
    assert [d.id for d in otro.listar()] == [documento.id]


def test_el_nombre_se_limpia_pero_se_conserva_para_mostrar(tmp_path: Path) -> None:
    registro = registro_en(tmp_path)
    documento = registro.crear("../../etc/passwd", 10, ".txt")
    assert documento.nombre == "passwd"


def test_reconciliar_marca_en_error_lo_que_quedo_a_medias(tmp_path: Path) -> None:
    """Un contenedor reiniciado a mitad de ingesta dejaría el indicador girando
    para siempre; ahí el indicador pasa de informar a mentir."""
    registro = registro_en(tmp_path)
    a = registro.crear("a.pdf", 1, ".pdf")
    registro.actualizar(a.id, estado=doc.PROCESANDO)
    b = registro.crear("b.pdf", 1, ".pdf")
    registro.actualizar(b.id, estado=doc.DISPONIBLE)

    releido = registro_en(tmp_path)
    assert releido.reconciliar() == 1
    assert releido.obtener(a.id).estado == doc.ERROR
    assert releido.obtener(b.id).estado == doc.DISPONIBLE


def test_un_inventario_corrupto_no_tumba_el_proceso(tmp_path: Path) -> None:
    (tmp_path / "inventario.json").write_text("{no es json", encoding="utf-8")
    assert registro_en(tmp_path).listar() == []


# --------------------------------------------------------------------------- #
# Ingesta
# --------------------------------------------------------------------------- #
def test_ingesta_completa_deja_el_documento_disponible(tmp_path: Path) -> None:
    registro = registro_en(tmp_path)
    almacen = AlmacenFalso()
    documento = registro.crear("plan.txt", len(TEXTO), ".txt")
    ruta = escribir(tmp_path, documento.archivo, TEXTO)

    doc.ingerir(registro, almacen, documento, ruta, trozo_caracteres=200, solape_caracteres=50)

    final = registro.obtener(documento.id)
    assert final.estado == doc.DISPONIBLE
    assert final.trozos == almacen.contar_documento(documento.id) > 0
    assert final.idioma == "es"
    assert final.procesado_en


def test_los_trozos_llevan_origen_subido_y_su_documento_id(tmp_path: Path) -> None:
    """`origen` es lo que permite distinguir en el índice —y en /salud— lo que
    trajo el corpus de lo que subió alguien por la consola."""
    registro = registro_en(tmp_path)
    almacen = AlmacenFalso()
    documento = registro.crear("plan.txt", len(TEXTO), ".txt")
    ruta = escribir(tmp_path, documento.archivo, TEXTO)

    doc.ingerir(registro, almacen, documento, ruta, trozo_caracteres=200, solape_caracteres=50)

    trozos = almacen.trozos[documento.id]
    assert all(t.origen == "subido" for t in trozos)
    assert all(t.documento_id == documento.id for t in trozos)
    # La cita tiene que decir de qué documento salió, con el nombre que el
    # operador ve en la consola.
    assert all(t.ruta_relativa == "plan.txt" for t in trozos)
    assert all(t.pagina >= 1 for t in trozos)


def test_un_pdf_sin_capa_de_texto_termina_en_error_con_su_motivo(tmp_path: Path) -> None:
    """No se indexa vacío: quedaría listado como disponible y no respondería
    nunca, que es el fallo silencioso que este proyecto no admite."""
    registro = registro_en(tmp_path)
    documento = registro.crear("escaneado.txt", 5, ".txt")
    ruta = escribir(tmp_path, documento.archivo, "   ")

    doc.ingerir(registro, AlmacenFalso(), documento, ruta, trozo_caracteres=200, solape_caracteres=50)

    final = registro.obtener(documento.id)
    assert final.estado == doc.ERROR
    assert "capa de texto" in final.mensaje


def test_un_archivo_inexistente_termina_en_error_y_no_lanza(tmp_path: Path) -> None:
    registro = registro_en(tmp_path)
    documento = registro.crear("fantasma.txt", 5, ".txt")
    doc.ingerir(
        registro,
        AlmacenFalso(),
        documento,
        tmp_path / "no-existe.txt",
        trozo_caracteres=200,
        solape_caracteres=50,
    )
    assert registro.obtener(documento.id).estado == doc.ERROR


def test_si_el_indice_rechaza_el_documento_no_se_declara_disponible(tmp_path: Path) -> None:
    registro = registro_en(tmp_path)
    documento = registro.crear("plan.txt", len(TEXTO), ".txt")
    ruta = escribir(tmp_path, documento.archivo, TEXTO)

    doc.ingerir(
        registro,
        AlmacenFalso(falla=True),
        documento,
        ruta,
        trozo_caracteres=200,
        solape_caracteres=50,
    )
    final = registro.obtener(documento.id)
    assert final.estado == doc.ERROR
    assert "índice" in final.mensaje


def test_disponible_se_afirma_contando_lo_que_quedo_dentro(tmp_path: Path) -> None:
    """El almacén acepta la inserción y no deja nada. Sin la relectura, el
    documento se declararía disponible y el agente nunca lo citaría."""
    registro = registro_en(tmp_path)
    documento = registro.crear("plan.txt", len(TEXTO), ".txt")
    ruta = escribir(tmp_path, documento.archivo, TEXTO)

    doc.ingerir(
        registro,
        AlmacenFalso(traga=True),
        documento,
        ruta,
        trozo_caracteres=200,
        solape_caracteres=50,
    )
    assert registro.obtener(documento.id).estado == doc.ERROR


def test_el_estado_pasa_por_procesando(tmp_path: Path) -> None:
    """El estado intermedio es requisito literal del reto: sin él, «espere» y
    «falló» se ven igual desde la consola."""
    registro = registro_en(tmp_path)
    documento = registro.crear("plan.txt", len(TEXTO), ".txt")
    ruta = escribir(tmp_path, documento.archivo, TEXTO)

    vistos: list[str] = []
    original = registro.actualizar

    def espia(documento_id, **campos):
        if "estado" in campos:
            vistos.append(campos["estado"])
        return original(documento_id, **campos)

    registro.actualizar = espia  # type: ignore[method-assign]
    doc.ingerir(registro, AlmacenFalso(), documento, ruta, trozo_caracteres=200, solape_caracteres=50)
    assert vistos == [doc.PROCESANDO, doc.DISPONIBLE]


def test_la_etiqueta_de_estado_es_la_que_ve_el_operador(tmp_path: Path) -> None:
    registro = registro_en(tmp_path)
    documento = registro.crear("plan.txt", 10, ".txt")
    assert registro.obtener(documento.id).a_json()["etiqueta_estado"] == "en cola"
    registro.actualizar(documento.id, estado=doc.DISPONIBLE)
    datos = registro.obtener(documento.id).a_json()
    assert datos["etiqueta_estado"] == "procesado y disponible"
    assert datos["disponible"] is True
