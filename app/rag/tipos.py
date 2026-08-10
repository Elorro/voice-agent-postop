"""Tipos de frontera del RAG. Solo librería estándar, a propósito.

`app/dialogo/orquestador.py` habla de fragmentos y citas sin importar chromadb
ni pypdf: si estos tipos vivieran junto al almacén vectorial, cualquier test del
turno arrastraría 90 MB de ONNX y la suite dejaría de correr en una máquina con
solo pytest.

Los metadatos de `Fragmento` son **la trazabilidad**, no adorno. Cada uno tiene
que poder resolverse contra el material entregado: `ruta_relativa` + `pagina`
identifican un punto concreto de un PDF de `dataset/textos/`, y el jurado puede
abrirlo. Un fragmento sin ellos es una afirmación sin fuente.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["Pagina", "Trozo", "Fragmento", "Cita", "ORIGEN_CORPUS", "ORIGEN_SUBIDO"]

ORIGEN_CORPUS = "corpus"
"""Documento del material entregado por el reto (`dataset/textos/`)."""

ORIGEN_SUBIDO = "subido"
"""Documento cargado por la consola de administración, en el volumen de subidas."""


@dataclass(frozen=True, slots=True)
class Pagina:
    """Texto extraído de UNA página, con su número tal como lo ve el lector.

    `numero` es 1-based: es el número que el evaluador teclea en el visor de PDF
    para comprobar la cita. Un índice 0-based ahorraría una resta y haría que
    cada cita apuntara una página antes de donde está.
    """

    numero: int
    texto: str


@dataclass(frozen=True, slots=True)
class Trozo:
    """Unidad que se indexa: texto + los metadatos que lo hacen citable."""

    id: str
    texto: str
    ruta_relativa: str
    pagina: int
    escenario: str
    idioma: str
    origen: str
    hash_documento: str
    documento_id: str
    indice: int

    def a_metadatos(self) -> dict[str, Any]:
        """Metadatos para ChromaDB. Solo str/int/float/bool: no acepta más."""
        return {
            "ruta_relativa": self.ruta_relativa,
            "pagina": self.pagina,
            "escenario": self.escenario,
            "idioma": self.idioma,
            "origen": self.origen,
            "hash_documento": self.hash_documento,
            "documento_id": self.documento_id,
            "indice": self.indice,
        }


@dataclass(frozen=True, slots=True)
class Fragmento:
    """Un resultado de la recuperación: el texto, su score y su procedencia.

    `score` es **similitud coseno** en [-1, 1], no una distancia: mayor es mejor.
    La colección se crea con `hnsw:space=cosine` y el score se calcula como
    `1 - distancia` (ver `app/rag/indice.py`). Se guarda la similitud y no la
    distancia porque el umbral de suficiencia se lee mejor así —«por debajo de
    0,X no hay respuesta»— y porque invertir el sentido de la comparación es un
    error de signo que nadie ve al leer el código.
    """

    texto: str
    score: float
    ruta_relativa: str
    pagina: int
    escenario: str
    idioma: str
    origen: str
    documento_id: str = ""
    hash_documento: str = ""

    score_denso: float = 0.0
    """Similitud coseno cruda, antes de fundir con el canal léxico."""

    score_lexico: float = 0.0
    """Cobertura IDF de la consulta en este fragmento, en [0, 1].

    Los dos componentes viajan además del score fundido porque son lo que hace
    auditable una recuperación híbrida: sin ellos, un fragmento con score 0,55 no
    se distingue de otro con el mismo 0,55 obtenido por la mitad contraria, y no
    hay forma de saber, leyendo el registro, cuál de los dos canales sostuvo la
    respuesta que se le dio al paciente.
    """

    def a_cita(self, max_caracteres: int) -> dict[str, Any]:
        """La forma que viaja al bloque `rag` de `turnos.jsonl`.

        El texto se recorta: el registro tiene que seguir siendo un archivo que
        una persona abre y lee. Un trozo entero por cita convertiría cada turno
        en varios kilobytes de PDF pegado.
        """
        texto = " ".join(self.texto.split())
        if len(texto) > max_caracteres:
            texto = texto[: max_caracteres - 1].rstrip() + "…"
        return {
            "ruta_relativa": self.ruta_relativa,
            "pagina": self.pagina,
            "texto_citado": texto,
            "score": round(self.score, 4),
            "score_denso": round(self.score_denso, 4),
            "score_lexico": round(self.score_lexico, 4),
            "origen": self.origen,
        }


Cita = dict
"""Alias documental: una cita es el dict que produce `Fragmento.a_cita`."""
