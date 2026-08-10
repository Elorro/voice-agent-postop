"""Troceo con solape. El tamaño NO es un número mágico: sale del embedder.

El criterio, en dos restricciones duras
---------------------------------------

**1. El techo lo fija el truncamiento del embedder, no el gusto.**
El modelo por defecto de ChromaDB (`all-MiniLM-L6-v2`, ONNX) se carga con

    tokenizer.enable_truncation(max_length=256)
    tokenizer.enable_padding(..., length=256)

(verificable: `docker exec voice-agent-postop python -c "import inspect,
chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 as m;
print(inspect.getsource(m.ONNXMiniLM_L6_V2._init_model_and_tokenizer))"`). Un
trozo más largo que 256 tokens **no se indexa entero: se corta en silencio** y la
cola del texto queda fuera del vector. No es una pérdida de calidad gradual; es
texto que deja de existir para el buscador.

Así que el tamaño en caracteres tiene que traducirse a ≤ 256 tokens, y la tasa
`caracteres/token` hay que **medirla sobre este corpus**, no suponerla: el
vocabulario de MiniLM es mayoritariamente inglés y el español se fragmenta más
(«apendicectomía» → varias piezas). La medición está en
`scripts/calibrar_troceo.py` y su salida en `docs/calibracion_rag.md`.

**2. El piso lo fija la unidad de sentido clínico.**
Un trozo demasiado corto parte la frase que contiene el dato («consulte si la
temperatura supera 38 °C» / «...durante las primeras 48 horas») y ninguna mitad
responde la pregunta. Por eso el solape se dimensiona contra la **longitud de
oración** del corpus, también medida: con solape ≥ P95 de la longitud de oración,
cualquier oración cabe entera en al menos un trozo aunque caiga sobre un borde.

Lo que este módulo NO hace
--------------------------
No parte por tokens. Partir por tokens obligaría a cargar el tokenizador —y con
él onnxruntime— dentro del troceo, que es código puro y se prueba sin
dependencias. Se parte por caracteres con un techo calibrado **por debajo** del
límite de tokens, y el indexador **verifica a posteriori** cuántos trozos
superaron los 256 tokens reales. Si esa cuenta no es cero, el margen está mal
elegido y el indexador lo dice.

Página de la cita
-----------------
Un trozo puede cruzar un salto de página. La página que viaja en el metadato es
la del **comienzo** del trozo: es donde el evaluador empieza a leer para
comprobar la cita. Elegir la página con más caracteres del trozo sería más
«representativo» y menos útil: mandaría a buscar el texto a una página donde la
cita no empieza.
"""

from __future__ import annotations

import re
from typing import Iterable, Sequence

from app.rag.tipos import Pagina

__all__ = [
    "normalizar",
    "trocear",
    "oraciones",
    "TrozoCrudo",
]

# --------------------------------------------------------------------------- #
# Normalización del texto extraído
# --------------------------------------------------------------------------- #

_GUION_FIN_LINEA = re.compile(r"(\w)[-­]\n(\w)")
_ESPACIOS = re.compile(r"[ \t   ]+")
_SALTOS = re.compile(r"\n{2,}")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalizar(texto: str) -> str:
    """Limpieza mínima y reversible en sentido: no reescribe, solo junta.

    Tres arreglos, y ninguno más. Cada transformación extra es una diferencia
    entre lo que dice el PDF y lo que se cita, y la trazabilidad se paga en esa
    moneda.

    1. **Palabra partida por guion al final de línea.** El extractor de PDF
       entrega «apendicec-\\ntomía»; sin unirla, la palabra clave del documento
       no existe para el buscador.
    2. **Espacios repetidos.** La maquetación en columnas produce corridas de
       espacios que no significan nada.
    3. **Caracteres de control.** Basura de la capa de texto de algunos PDFs.

    Los saltos de línea simples SE CONSERVAN: en un documento maquetado son el
    único indicio de dónde termina un renglón de tabla o un ítem de lista.
    """
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    texto = _CONTROL.sub(" ", texto)
    texto = _GUION_FIN_LINEA.sub(r"\1\2", texto)
    texto = _ESPACIOS.sub(" ", texto)
    texto = _SALTOS.sub("\n\n", texto)
    return texto.strip()


# --------------------------------------------------------------------------- #
# Oraciones
# --------------------------------------------------------------------------- #

# Corte tras `.`, `?`, `!`, `;` o salto de párrafo. La abreviatura («Dr.», «pág.»,
# «Fig. 2») produce cortes de más; es el error barato: un trozo con una oración
# de más no pierde información, y el empaquetado vuelve a juntarlas enseguida.
_FIN_ORACION = re.compile(r"(?<=[.!?;])\s+|\n{2,}")


def oraciones(texto: str) -> list[tuple[int, str]]:
    """Devuelve `(desplazamiento, oración)` sobre el texto dado.

    Se conserva el desplazamiento porque es lo que permite saber en qué página
    empieza cada trozo sin volver a buscar la cadena.
    """
    salida: list[tuple[int, str]] = []
    inicio = 0
    for corte in _FIN_ORACION.finditer(texto):
        fin = corte.start()
        fragmento = texto[inicio:fin]
        if fragmento.strip():
            salida.append((inicio, fragmento))
        inicio = corte.end()
    resto = texto[inicio:]
    if resto.strip():
        salida.append((inicio, resto))
    return salida


# --------------------------------------------------------------------------- #
# Troceo
# --------------------------------------------------------------------------- #


class TrozoCrudo:
    """Texto de un trozo y la página donde empieza. Sin metadatos todavía."""

    __slots__ = ("texto", "pagina")

    def __init__(self, texto: str, pagina: int) -> None:
        self.texto = texto
        self.pagina = pagina

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return f"TrozoCrudo(pagina={self.pagina}, texto={self.texto[:40]!r}…)"

    def __eq__(self, otro: object) -> bool:
        return (
            isinstance(otro, TrozoCrudo)
            and otro.texto == self.texto
            and otro.pagina == self.pagina
        )


def _unir_paginas(paginas: Sequence[Pagina]) -> tuple[str, list[tuple[int, int]]]:
    """Concatena las páginas y devuelve el mapa `(desplazamiento_inicial, página)`.

    Se trocea sobre el documento entero y no página a página a propósito: un
    párrafo cortado por el salto de página produciría, con troceo por página, dos
    mitades que ninguna responde nada. El precio es tener que reconstruir a qué
    página pertenece cada trozo, que es lo que hace este mapa.
    """
    partes: list[str] = []
    mapa: list[tuple[int, int]] = []
    posicion = 0
    for pagina in paginas:
        texto = normalizar(pagina.texto)
        if not texto:
            continue
        mapa.append((posicion, pagina.numero))
        partes.append(texto)
        posicion += len(texto) + 1  # el "\n" que las une
    return "\n".join(partes), mapa


def _pagina_en(mapa: list[tuple[int, int]], desplazamiento: int) -> int:
    """Página que contiene ese desplazamiento. Búsqueda lineal hacia atrás."""
    pagina = mapa[0][1] if mapa else 1
    for inicio, numero in mapa:
        if inicio > desplazamiento:
            break
        pagina = numero
    return pagina


def _partir_largo(desplazamiento: int, texto: str, tope: int) -> Iterable[tuple[int, str]]:
    """Corta una «oración» que sola ya excede el tope.

    Ocurre de verdad: tablas sin puntuación, listados de referencias, y el texto
    de PDFs cuya capa no tiene separadores. Se corta por el último espacio antes
    del tope para no partir palabras.
    """
    while len(texto) > tope:
        corte = texto.rfind(" ", 0, tope)
        if corte <= 0:
            corte = tope
        yield desplazamiento, texto[:corte]
        desplazamiento += corte
        texto = texto[corte:].lstrip()
    if texto.strip():
        yield desplazamiento, texto


def trocear(
    paginas: Sequence[Pagina],
    *,
    max_caracteres: int,
    solape_caracteres: int,
    minimo_caracteres: int = 80,
) -> list[TrozoCrudo]:
    """Empaquetado goloso de oraciones, con solape por oraciones completas.

    El solape se toma reponiendo oraciones enteras del final del trozo anterior
    hasta cubrir `solape_caracteres`, no cortando N caracteres hacia atrás:
    cortar por carácter produciría trozos que empiezan a mitad de palabra, y ese
    prefijo roto es exactamente lo que el evaluador ve pegado en la cita.

    `minimo_caracteres` descarta la cola residual de un documento (un número de
    página suelto, un pie de figura): no aporta contexto y sí ruido al buscador.
    """
    if max_caracteres <= 0:
        raise ValueError("max_caracteres debe ser positivo")
    if not 0 <= solape_caracteres < max_caracteres:
        raise ValueError("el solape debe estar en [0, max_caracteres)")

    texto, mapa = _unir_paginas(paginas)
    if not texto.strip():
        return []

    unidades: list[tuple[int, str]] = []
    for desplazamiento, oracion in oraciones(texto):
        if len(oracion) > max_caracteres:
            unidades.extend(_partir_largo(desplazamiento, oracion, max_caracteres))
        else:
            unidades.append((desplazamiento, oracion))

    trozos: list[TrozoCrudo] = []
    actual: list[tuple[int, str]] = []
    largo = 0

    def emitir() -> None:
        if not actual:
            return
        cuerpo = " ".join(o.strip() for _, o in actual).strip()
        if len(cuerpo) >= minimo_caracteres or not trozos:
            trozos.append(TrozoCrudo(cuerpo, _pagina_en(mapa, actual[0][0])))

    for unidad in unidades:
        coste = len(unidad[1]) + (1 if actual else 0)
        if actual and largo + coste > max_caracteres:
            emitir()
            # Reposición del solape: oraciones completas desde el final.
            arrastre: list[tuple[int, str]] = []
            acumulado = 0
            for previa in reversed(actual):
                if acumulado >= solape_caracteres:
                    break
                arrastre.insert(0, previa)
                acumulado += len(previa[1]) + 1
            # El arrastre nunca puede dejar el trozo siguiente sin sitio para su
            # propia oración: si lo llenara, el bucle no avanzaría.
            while arrastre and acumulado + len(unidad[1]) > max_caracteres:
                acumulado -= len(arrastre[0][1]) + 1
                arrastre.pop(0)
            actual = arrastre
            largo = acumulado
            coste = len(unidad[1]) + (1 if actual else 0)
        actual.append(unidad)
        largo += coste

    emitir()
    return trozos
