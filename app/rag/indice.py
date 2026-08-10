"""El almacén vectorial. Único punto del árbol que importa `chromadb`.

Tres decisiones que este módulo fija, y por qué
-----------------------------------------------

**1. Espacio coseno, explícito.** ChromaDB usa L2 por defecto. El embedder
devuelve vectores ya normalizados (`ONNXMiniLM_L6_V2._normalize`), así que L2 y
coseno ordenan igual —L2² = 2(1 − cos)—, pero no *miden* igual: la distancia L2
vive en [0, 2] con una escala que no es interpretable y el umbral de suficiencia
tendría que calibrarse sobre un número sin significado. Con `hnsw:space=cosine`,
`score = 1 − distancia` es la similitud coseno y el umbral se puede leer, discutir
y comparar con la literatura.

**2. Un candado, y solo sobre las ESCRITURAS.** La ingesta de un documento subido
corre en un hilo (la consola no puede bloquear el turno de voz) mientras el turno
consulta desde el hilo del servidor. Las escrituras se serializan entre sí con un
candado de módulo; las consultas no lo toman. La razón de no meter las lecturas
bajo el mismo candado es de latencia: una ingesta de 200 trozos tarda decenas de
segundos y dejaría al paciente esperando en medio de la llamada. El precio es que
una consulta puede caer entre dos lotes de una ingesta y ver el documento a
medias — visible como «el documento aún no responde del todo», nunca como
corrupción, porque `add` de un lote es atómico para ChromaDB.

**3. Ingesta por lotes.** Por eso mismo: el candado se toma y se suelta por lote,
así el turno nunca espera más que un lote y no la ingesta entera.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Iterable, Sequence

from app.rag import lexico
from app.rag.tipos import Fragmento, Trozo

_log = logging.getLogger(__name__)

__all__ = ["ESPACIO", "TAMANO_LOTE", "POOL", "ALFA", "Almacen", "abrir"]

POOL = 60
"""Candidatos que pide el canal denso antes de reordenar.

Ni 5 ni 500. El pool tiene que ser lo bastante ancho para que el fragmento
pertinente esté dentro aunque el denso lo haya puesto en el puesto 30 —que es
exactamente lo que pasa en español— y lo bastante estrecho para que la fusión
siga costando microsegundos: reordenar 60 textos es comparar 60 cadenas.

60 no es arbitrario: es ~0,4 % de los 16.424 fragmentos, y la medición del
2026-08-10 mostró que el escenario correcto aparecía en el top-5 denso en 10 de
10 consultas, así que la señal está muy por encima del puesto 60. Subirlo no
compra recuperación y sí latencia.
"""

ALFA = 0.5
"""Peso del canal denso en la fusión. `1,0` la apagaría; `0,5` es lo que se usa.

El barrido de `scripts/calibrar_umbral.py` sobre este índice (2026-08-10) da el
hueco entre consultas cubiertas y ajenas para cada peso:

        α      hueco español    hueco inglés
      1,00          +0,021          +0,141
      0,75          +0,002          +0,205
      0,60          −0,056          +0,156
      0,50          −0,094          +0,100
      0,25          −0,191          −0,039
      0,00          −0,303          −0,179

En inglés la fusión **mejora** (de +0,141 a +0,205 en α = 0,75). En español
empeora de forma monótona, y la causa está medida: **el IDF calculado sobre este
corpus invierte la informatividad**. En una colección monotemática de cirugía,
«apendi» aparece en 648 fragmentos y «cuanto» en 194, así que el IDF le da más
peso a «cuánto» que a «apendicectomía». Al reordenar un pool ancho, gana el
fragmento que comparte las palabras genéricas de la pregunta, no el que comparte
el término clínico.

Eso es un defecto del **origen** del IDF, no del método de fusión: haría falta
frecuencias de una colección de español general, que es un artefacto nuevo. Queda
declarado como deuda, no como algo que aquí se pueda arreglar bajando un número.

Entonces ¿por qué α = 0,5 y no 1,0?
------------------------------------
Porque la tabla de arriba mide el hueco **sobre 18 consultas del corpus**, y esa
no es la única propiedad que hay que comprar. Con α = 1,0:

* La compuerta **G5 es imposible**, y eso es aritmética, no opinión: el fragmento
  con la respuesta literal de un documento subido puntúa 0,5988, por debajo de un
  ejercicio de rodilla sin relación (0,6418) y por debajo de la mejor consulta
  ajena (0,617). Ningún umbral denso acepta lo correcto y rechaza lo ajeno.
* El «hueco de +0,021» que justificaba α = 1,0 se midió con n = 18. Está dentro
  del ruido de muestreo, así que la seguridad que compraba era nominal.

Con α = 0,5 el mismo caso de G5 se ordena bien —el documento sube al puesto 1 con
0,6444 y el ejercicio de rodilla cae a 0,3255— y el margen de rechazo contra las
consultas ajenas pasa de 0,033 a **0,054**. Lo que se paga es que más consultas
cubiertas del corpus caen por debajo del umbral y el agente declara su límite. Ese
es el error que la rúbrica premia.

Lo que la medición dejó para el sucesor: la cobertura léxica sobre el top-1 denso
separa **perfectamente** las dos poblaciones —0,000 en las 8 consultas ajenas,
≥ 0,087 en las 10 cubiertas—. Como compuerta de rechazo el canal léxico funciona;
como reordenador con IDF interno del corpus, a medias.
"""

ESPACIO = "cosine"
TAMANO_LOTE = 64
"""Trozos por llamada a `add`. Compromiso medido en el orden de magnitud del
embedder: ~64 textos por lote mantienen la CPU ocupada sin retener el candado
más de uno o dos segundos."""

_candado_escritura = threading.Lock()


def _embedder() -> Any:
    """El embedder por defecto de ChromaDB, vendorizado en la imagen.

    Se instancia aquí y no se recibe por parámetro para que **el indexador y la
    consulta usen exactamente el mismo**: dos instancias de modelos distintos
    producirían vectores incomparables y la recuperación devolvería ruido con
    aspecto de resultado.
    """
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

    return DefaultEmbeddingFunction()


class Almacen:
    """Envoltorio delgado sobre una colección de ChromaDB.

    Delgado a propósito: todo lo que no necesita chromadb —trocear, detectar
    idioma, decidir si el score alcanza— vive fuera, en módulos que se prueban
    sin instalar nada.
    """

    def __init__(self, coleccion: Any, ruta: Path) -> None:
        self.coleccion = coleccion
        self.ruta = ruta
        # `False` = todavía no se intentó abrir; `None` = se intentó y no hay.
        # Distinguir los dos estados evita reintentar en cada turno una conexión
        # que ya se sabe que no existe.
        self._fts: Any = False
        self._df: dict[str, int] = {}
        # `check_same_thread=False` deja usar la conexión desde el pool de hilos
        # de uvicorn, pero SQLite no serializa por su cuenta dos consultas
        # simultáneas sobre la misma conexión. Este candado lo hace. Es barato:
        # las consultas de frecuencia son de milisegundos y van memoizadas.
        self._candado_fts = threading.Lock()

    # -- lectura ------------------------------------------------------------ #

    def contar(self) -> int:
        return int(self.coleccion.count())

    # -- frecuencias documentales (canal léxico) ---------------------------- #

    def _conexion_fts(self) -> Any:
        """Conexión de SOLO LECTURA al SQLite del índice, para el FTS5.

        ChromaDB construye un índice de texto completo (`embedding_fulltext_search`,
        tokenizador de **trigramas**) y no expone su `bm25()` por la API: solo el
        filtro `$contains`, que devuelve un booleano y no un ranking. Lo que sí se
        puede sacar de él —y es lo único que hace falta— son **frecuencias
        documentales sobre la colección entera**, que es el insumo del IDF.

        Ese índice ya existe y ya se paga (25 MB del archivo). Construir un
        segundo índice léxico propio sería duplicar en disco lo que está ahí.

        Se abre en modo `ro` y aparte del cliente de ChromaDB a propósito: leer
        por la conexión de escritura del cliente mezclaría esta consulta con las
        transacciones de una ingesta en curso.
        """
        if self._fts is not False:
            return self._fts
        import sqlite3

        ruta = self.ruta / "chroma.sqlite3"
        try:
            conexion = sqlite3.connect(
                f"file:{ruta}?mode=ro", uri=True, timeout=0.5, check_same_thread=False
            )
            conexion.execute(
                "SELECT count(*) FROM embedding_fulltext_search WHERE "
                "embedding_fulltext_search MATCH ?",
                ('"herida"',),
            ).fetchone()
            self._fts = conexion
        except Exception as exc:  # noqa: BLE001
            # Esquema distinto (otra versión de chromadb) o base inaccesible. Se
            # degrada a recuperación densa pura y se dice, en vez de fallar: el
            # canal léxico es una mejora del ranking, no un requisito del turno.
            _log.warning("sin canal léxico (FTS5 no accesible): %s", exc)
            self._fts = None
        return self._fts

    def frecuencias(self, terminos: Sequence[str]) -> dict[str, int]:
        """`término -> nº de fragmentos que lo contienen`. Memoizado por proceso.

        La caché importa: los pacientes repiten palabras («herida», «dolor»,
        «fiebre») y cada consulta al FTS cuesta entre 2 y 14 ms medidos. Sin
        caché, una llamada de seis turnos pagaría el mismo `df` seis veces.
        """
        conexion = self._conexion_fts()
        if conexion is None:
            return {}
        salida: dict[str, int] = {}
        for termino in terminos:
            if termino in self._df:
                salida[termino] = self._df[termino]
                continue
            if len(termino) < 3:  # el tokenizador de trigramas no admite menos
                self._df[termino] = 0
                salida[termino] = 0
                continue
            try:
                with self._candado_fts:
                    fila = conexion.execute(
                        "SELECT count(*) FROM embedding_fulltext_search WHERE "
                        "embedding_fulltext_search MATCH ?",
                        (f'"{termino}"',),
                    ).fetchone()
                n = int(fila[0]) if fila else 0
            except Exception as exc:  # noqa: BLE001
                _log.debug("df(%s) falló: %s", termino, exc)
                n = 0
            self._df[termino] = n
            salida[termino] = n
        return salida

    def total_fragmentos_fts(self) -> int:
        """`N` del IDF. Se relee porque la consola puede haber añadido documentos."""
        conexion = self._conexion_fts()
        if conexion is None:
            return 0
        try:
            with self._candado_fts:
                fila = conexion.execute(
                    "SELECT count(*) FROM embedding_fulltext_search"
                ).fetchone()
            return int(fila[0])
        except Exception:  # noqa: BLE001
            return 0

    def consultar(
        self,
        texto: str,
        k: int,
        *,
        pool: int | None = None,
        alfa: float | None = None,
    ) -> list[Fragmento]:
        """Recuperación **híbrida**: recupera denso, reordena fundiendo con léxico.

        El canal denso propone un pool amplio (`pool`, por defecto `POOL`) y la
        fusión decide el orden y el score final. Se recupera de más y se reordena
        porque el hallazgo que motivó la híbrida es que **el orden del denso está
        roto en español**: pedirle directamente los 5 mejores sería confiar en
        justo lo que se midió que falla.

        Con `alfa=1.0` el comportamiento es exactamente el denso de antes, lo que
        permite medir los dos regímenes sobre el mismo índice y con el mismo
        código (ver `scripts/calibrar_umbral.py`).
        """
        if not texto.strip() or k <= 0:
            return []
        alfa = ALFA if alfa is None else alfa
        # Con α = 1 la fusión es la identidad sobre el denso: pedir un pool de 60
        # para descartar 55 sería latencia regalada en el camino crítico del
        # turno. Se paga el pool solo cuando hay algo que reordenar.
        n_pool = k if alfa >= 1.0 else max(k, pool if pool is not None else POOL)
        crudo = self.coleccion.query(
            query_texts=[texto],
            n_results=n_pool,
            include=["documents", "metadatas", "distances"],
        )
        documentos = (crudo.get("documents") or [[]])[0]
        metadatos = (crudo.get("metadatas") or [[]])[0]
        distancias = (crudo.get("distances") or [[]])[0]

        # --- canal léxico: IDF sobre la colección entera --------------------- #
        terminos = lexico.terminos_de_consulta(texto)
        if alfa < 1.0 and terminos:
            total = self.total_fragmentos_fts()
            pesos = lexico.pesos_idf(terminos, self.frecuencias(terminos), total)
        else:
            pesos = {}

        salida: list[Fragmento] = []
        for doc, meta, distancia in zip(documentos, metadatos, distancias):
            meta = meta or {}
            cuerpo = doc or ""
            denso = 1.0 - float(distancia)
            if pesos:
                cobertura = lexico.cobertura(terminos, pesos, cuerpo)
                score = lexico.fundir(denso, cobertura, alfa)
            else:
                cobertura = 0.0
                score = max(0.0, min(1.0, denso))
            salida.append(
                Fragmento(
                    texto=cuerpo,
                    score=round(score, 6),
                    ruta_relativa=str(meta.get("ruta_relativa", "")),
                    pagina=int(meta.get("pagina", 0) or 0),
                    escenario=str(meta.get("escenario", "")),
                    idioma=str(meta.get("idioma", "")),
                    origen=str(meta.get("origen", "")),
                    documento_id=str(meta.get("documento_id", "")),
                    hash_documento=str(meta.get("hash_documento", "")),
                    score_denso=round(denso, 6),
                    score_lexico=round(cobertura, 6),
                )
            )
        # Orden estable por score fundido. `sorted` conserva el orden del denso
        # entre empates, que es la desempate correcta: ante dos fragmentos
        # igualmente cubiertos, el más cercano en el espacio vectorial primero.
        salida.sort(key=lambda f: f.score, reverse=True)
        return salida[:k]

    def contar_documento(self, documento_id: str) -> int:
        """Trozos de un documento concreto. Es el indicador de «ya está dentro»."""
        try:
            resultado = self.coleccion.get(
                where={"documento_id": documento_id}, include=[]
            )
        except Exception as exc:  # noqa: BLE001
            _log.warning("no se pudo contar %s: %s", documento_id, exc)
            return 0
        return len(resultado.get("ids") or [])

    def resumen_por_origen(self) -> dict[str, int]:
        """Trozos por origen (`corpus` / `subido`). Alimenta `/salud`."""
        salida: dict[str, int] = {}
        for origen in ("corpus", "subido"):
            try:
                resultado = self.coleccion.get(where={"origen": origen}, include=[])
                salida[origen] = len(resultado.get("ids") or [])
            except Exception:  # noqa: BLE001 - informativo, no bloquea
                continue
        return salida

    # -- escritura ---------------------------------------------------------- #

    def agregar(self, trozos: Sequence[Trozo], *, lote: int = TAMANO_LOTE) -> int:
        """Inserta (o reemplaza) trozos. Idempotente por el id determinista.

        `upsert` y no `add`: reejecutar el indexador sobre el mismo corpus tiene
        que reproducir el mismo índice, no duplicarlo ni fallar. El id de cada
        trozo se deriva del hash del texto del documento y del índice del trozo,
        así que la segunda pasada sobreescribe exactamente lo mismo.
        """
        total = 0
        for inicio in range(0, len(trozos), lote):
            paquete = trozos[inicio : inicio + lote]
            with _candado_escritura:
                self.coleccion.upsert(
                    ids=[t.id for t in paquete],
                    documents=[t.texto for t in paquete],
                    metadatas=[t.a_metadatos() for t in paquete],
                )
            total += len(paquete)
        return total

    def borrar_documento(self, documento_id: str) -> int:
        """Borra todos los trozos de un documento. Devuelve cuántos había.

        Se cuenta antes de borrar porque `delete` de chromadb no informa cuántos
        eliminó, y «el agente dejó de usar el documento» es justo la afirmación
        que hay que poder verificar en la compuerta G5.
        """
        n = self.contar_documento(documento_id)
        if not n:
            return 0
        with _candado_escritura:
            self.coleccion.delete(where={"documento_id": documento_id})
        return n


def abrir(
    ruta: Path, nombre: str, *, crear: bool = True, embedder: Any | None = None
) -> Almacen:
    """Abre (o crea) la colección persistente en `ruta`.

    `crear=False` para el caso en que abrir un índice inexistente debe ser un
    error visible en vez de una colección vacía silenciosa.
    """
    import chromadb

    ruta.mkdir(parents=True, exist_ok=True)
    cliente = chromadb.PersistentClient(path=str(ruta))
    ef = embedder if embedder is not None else _embedder()
    if crear:
        coleccion = cliente.get_or_create_collection(
            name=nombre, embedding_function=ef, metadata={"hnsw:space": ESPACIO}
        )
    else:
        coleccion = cliente.get_collection(name=nombre, embedding_function=ef)
    return Almacen(coleccion, ruta)


def documentos_indexados(almacen: Almacen) -> dict[str, dict[str, Any]]:
    """Inventario `documento_id -> {ruta_relativa, origen, trozos}`.

    Recorre los metadatos de la colección entera. Es una operación cara y por eso
    no la usa el turno: la usan el indexador (para su informe) y la consola (para
    mostrar qué hay dentro), donde un par de segundos no le cuestan a nadie.
    """
    resultado = almacen.coleccion.get(include=["metadatas"])
    inventario: dict[str, dict[str, Any]] = {}
    for meta in resultado.get("metadatas") or []:
        meta = meta or {}
        clave = str(meta.get("documento_id", ""))
        entrada = inventario.setdefault(
            clave,
            {
                "ruta_relativa": str(meta.get("ruta_relativa", "")),
                "origen": str(meta.get("origen", "")),
                "escenario": str(meta.get("escenario", "")),
                "idioma": str(meta.get("idioma", "")),
                "trozos": 0,
            },
        )
        entrada["trozos"] += 1
    return inventario


def iter_lotes(elementos: Iterable[Any], tamano: int) -> Iterable[list[Any]]:
    """Agrupa un iterable en listas de `tamano`. Utilidad del indexador."""
    lote: list[Any] = []
    for elemento in elementos:
        lote.append(elemento)
        if len(lote) >= tamano:
            yield lote
            lote = []
    if lote:
        yield lote
