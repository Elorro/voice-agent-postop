"""Los cuatro endpoints de la consola (G5), contra la aplicación real.

Se ejercita con `TestClient`, no con peticiones simuladas a mano: lo que la
compuerta mide es el contrato HTTP —códigos, formato de la respuesta, el 202 que
declara que el trabajo aún no terminó— y eso solo lo produce el enrutador de
verdad.

El almacén vectorial se sustituye por un doble. Cargar chromadb y 90 MB de ONNX
para comprobar que un DELETE devuelve 404 sobre un identificador inexistente
convertiría esta suite en algo que nadie corre.

`fastapi` está en `requirements-dev.txt` para que estos tests CORRAN, y eso es una
lección aprendida cara: estuvieron escritos y saltándose por `importorskip`
mientras un `TypeError` en el despacho de la ingesta dejaba todo documento subido
congelado en «en cola». El test lo habría atrapado en la primera corrida. Un test
que siempre se salta no es un test.

Se conserva el `importorskip` para que la suite siga corriendo en una máquina que
solo tenga pytest, pero el camino normal es tener las dependencias de desarrollo
instaladas y verlos pasar.
"""

from __future__ import annotations

import io
import time
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi", reason="instale requirements-dev.txt")
from fastapi.testclient import TestClient  # noqa: E402

from app.rag import documentos as doc  # noqa: E402
from tests.apoyo_turno import config_de_prueba  # noqa: E402

TEXTO = (
    "El drenaje de Penrose se retira habitualmente entre el tercer y el quinto "
    "día del postoperatorio, según indique el cirujano. "
) * 8


class AlmacenFalso:
    def __init__(self) -> None:
        self.trozos: dict[str, list] = {}

    def agregar(self, trozos, **_):
        for t in trozos:
            self.trozos.setdefault(t.documento_id, []).append(t)
        return len(trozos)

    def contar_documento(self, documento_id: str) -> int:
        return len(self.trozos.get(documento_id, []))

    def borrar_documento(self, documento_id: str) -> int:
        return len(self.trozos.pop(documento_id, []))

    def consultar(self, texto: str, k: int):
        return []


@pytest.fixture
def cliente(tmp_path: Path, monkeypatch):
    """Aplicación real con el almacén y las rutas de datos sustituidos."""
    import app.api_documentos as api_documentos
    import app.servicios as servicios

    cfg = config_de_prueba(tmp_path, SUBIDOS_DIR=str(tmp_path / "subidos"))
    almacen = AlmacenFalso()
    registro = doc.Registro(cfg.dir_subidos / "inventario.json")

    monkeypatch.setattr(api_documentos, "_cfg", lambda: cfg)
    monkeypatch.setattr(api_documentos, "obtener_almacen", lambda _cfg: almacen)
    monkeypatch.setattr(api_documentos, "obtener_registro_documentos", lambda _cfg: registro)
    monkeypatch.setattr(servicios, "precargar_servicios", lambda _cfg: None)

    aplicacion = fastapi.FastAPI()
    aplicacion.include_router(api_documentos.router)
    with TestClient(aplicacion) as cliente:
        cliente.almacen = almacen  # type: ignore[attr-defined]
        cliente.cfg = cfg  # type: ignore[attr-defined]
        yield cliente


def subir(cliente, nombre: str = "protocolo.txt", contenido: str = TEXTO):
    return cliente.post(
        "/api/documentos",
        files={"archivo": (nombre, io.BytesIO(contenido.encode("utf-8")), "text/plain")},
    )


def esperar(cliente, segundos: float = 5.0) -> list[dict]:
    """Sondea el inventario hasta que ningún documento esté en curso.

    Es lo mismo que hace la consola en el navegador, y por la misma razón: la
    ingesta corre en un HILO y el `POST` devuelve antes de que termine. Un test
    que consultara una sola vez mediría una carrera, no el comportamiento.
    """
    limite = time.monotonic() + segundos
    while True:
        documentos = cliente.get("/api/documentos").json()["documentos"]
        en_curso = [d for d in documentos if d["estado"] in (doc.PENDIENTE, doc.PROCESANDO)]
        if not en_curso or time.monotonic() > limite:
            return documentos
        time.sleep(0.05)


# --------------------------------------------------------------------------- #
# Listado
# --------------------------------------------------------------------------- #
def test_el_inventario_arranca_vacio_y_declara_sus_limites(cliente) -> None:
    datos = cliente.get("/api/documentos").json()
    assert datos["documentos"] == []
    assert datos["indice_disponible"] is True
    assert ".pdf" in datos["formatos"]
    assert datos["max_mb"] > 0


# --------------------------------------------------------------------------- #
# Subida
# --------------------------------------------------------------------------- #
def test_subir_devuelve_202_y_el_documento_queda_indexado(cliente) -> None:
    """202 y no 201: cuando la respuesta sale, el documento está guardado pero
    todavía no indexado. Un 201 afirmaría lo que la consola desmiente un segundo
    después."""
    respuesta = subir(cliente)
    assert respuesta.status_code == 202
    cuerpo = respuesta.json()
    assert cuerpo["nombre"] == "protocolo.txt"
    assert cuerpo["estado"] in (doc.PENDIENTE, doc.PROCESANDO, doc.DISPONIBLE)

    documentos = esperar(cliente)
    assert len(documentos) == 1
    assert documentos[0]["estado"] == doc.DISPONIBLE
    assert documentos[0]["trozos_en_indice"] > 0
    assert documentos[0]["etiqueta_estado"] == "procesado y disponible"


def test_un_formato_no_aceptado_se_rechaza_con_415(cliente) -> None:
    respuesta = subir(cliente, nombre="hoja.xlsx")
    assert respuesta.status_code == 415
    assert "formato no aceptado" in respuesta.json()["detail"]
    # Y no queda basura en el inventario.
    assert cliente.get("/api/documentos").json()["documentos"] == []


def test_un_archivo_vacio_se_rechaza(cliente) -> None:
    respuesta = subir(cliente, contenido="")
    assert respuesta.status_code == 400
    assert cliente.get("/api/documentos").json()["documentos"] == []


def test_el_archivo_se_guarda_con_el_identificador_y_no_con_el_nombre(cliente) -> None:
    subir(cliente, nombre="../../app/main.py.txt")
    documentos = esperar(cliente)
    archivo = documentos[0]["archivo"]
    assert archivo.startswith("subido-")
    assert (cliente.cfg.dir_subidos / archivo).is_file()


# --------------------------------------------------------------------------- #
# Borrado
# --------------------------------------------------------------------------- #
def test_eliminar_saca_los_fragmentos_del_indice_y_el_archivo_del_disco(cliente) -> None:
    documento_id = subir(cliente).json()["id"]
    esperar(cliente)
    assert cliente.almacen.contar_documento(documento_id) > 0

    respuesta = cliente.delete(f"/api/documentos/{documento_id}")
    assert respuesta.status_code == 200
    assert respuesta.json()["fragmentos_borrados"] > 0
    assert cliente.almacen.contar_documento(documento_id) == 0
    assert cliente.get("/api/documentos").json()["documentos"] == []


def test_eliminar_algo_que_no_existe_es_404(cliente) -> None:
    assert cliente.delete("/api/documentos/subido-inexistente").status_code == 404


def test_si_el_indice_no_borra_el_documento_sigue_listado(cliente) -> None:
    """Dejar el archivo listado con un error es recuperable; quitarlo de la lista
    con sus fragmentos dentro deja al agente citando lo que la consola jura haber
    borrado."""
    documento_id = subir(cliente).json()["id"]
    esperar(cliente)

    def reventar(_id):
        raise RuntimeError("SQLite bloqueado")

    cliente.almacen.borrar_documento = reventar  # type: ignore[method-assign]
    respuesta = cliente.delete(f"/api/documentos/{documento_id}")
    assert respuesta.status_code == 500
    documentos = cliente.get("/api/documentos").json()["documentos"]
    assert [d["id"] for d in documentos] == [documento_id]
    assert documentos[0]["estado"] == doc.ERROR
