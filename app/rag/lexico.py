"""Canal léxico de la recuperación híbrida. Código puro: se prueba sin chromadb.

Por qué hay un segundo canal
----------------------------
El embedder por defecto (`all-MiniLM-L6-v2`) es **monolingüe inglés** y el corpus
y las preguntas son mayoritariamente españoles. Medido sobre este índice
(2026-08-10, `scripts/calibrar_umbral.py`), con las MISMAS preguntas y el MISMO
índice, cambiando solo el idioma:

    población               n     mín   mediana    máx
    español · cubiertas    10   0,638     0,706  0,783
    español · ajenas        8   0,482     0,576  0,617   ← hueco 0,021
    inglés  · cubiertas    10   0,595     0,682  0,808
    inglés  · ajenas        8   0,209     0,275  0,455   ← hueco 0,141

Las preguntas ajenas en inglés («what is the capital of Australia») caen a 0,21;
las ajenas en español («cuál es la capital de Australia») se quedan en 0,48. Mismo
contenido, mismo índice, mismo modelo. **El coseno denso en español está midiendo
sobre todo «esto es texto en español», no «esto habla de lo que pregunto».** Los
vectores del español caen en un cono estrecho del espacio y las distancias dentro
de ese cono casi no discriminan.

De ahí el canal léxico. Su virtud aquí no es que sea mejor —no lo es en general—,
sino que **su modo de fallo es ortogonal al del denso**:

* El denso falla por *degeneración de idioma*: representa mal el español y todo lo
  español se le parece.
* El léxico **no modela idioma en absoluto**: cuenta apariciones de cadenas. La
  palabra «ajiaco» no aparece en un corpus quirúrgico, y eso es verdad
  independientemente de en qué idioma esté entrenado nadie. Por construcción, el
  fallo que hunde al denso no puede tocarlo.

Cuándo el léxico deja de valer, dicho por delante
-------------------------------------------------
1. **Sinonimia y paráfrasis.** «me sale pus» contra «secreción purulenta» no
   comparte ni una palabra. Ahí el denso es el que salva la consulta, y por eso
   esto es una fusión y no un reemplazo.
2. **Morfología.** El español flexiona por sufijo («camina / caminar / caminando»).
   Se ataja truncando a un prefijo (ver `PREFIJO`), que es una decisión con falsos
   positivos declarados, no un stemmer de verdad.
3. **Preguntas sin ninguna palabra del corpus.** Un paciente que pregunta «¿esto
   es normal?» no aporta término alguno con contenido: el canal léxico se queda en
   cero y la consulta la decide el denso, con la debilidad que ya se midió.

El método de fusión, y por qué NO es RRF
-----------------------------------------
La tentación obvia es *Reciprocal Rank Fusion*: `Σ 1/(k + rango)`. Es lo estándar
cuando dos rankings no son comparables, y aquí **no sirve**, por una razón que
tiene que ver con lo que este sistema necesita:

> **RRF descarta la magnitud y solo conserva el orden.** Una consulta ajena al
> corpus también tiene un resultado en el puesto 1, así que su score RRF es el
> mismo que el de una consulta perfectamente cubierta. Con RRF **no existe umbral
> de suficiencia posible**: no hay ningún número por debajo del cual se pueda
> decir «esto no lo cubre el corpus».

Y ese umbral no es un adorno: es lo que hace que el agente declare su límite en
vez de improvisar una respuesta clínica. La fusión tiene que conservar magnitud.

Por la misma razón se descarta la **normalización min-max sobre el pool**: el
mejor resultado de un pool malo se normalizaría a 1,0. Cualquier normalización
relativa a la consulta destruye justo la señal que hay que preservar.

Queda entonces una combinación convexa de dos scores **absolutos** —cada uno
significa lo mismo consulta a consulta—:

    fusion = α · denso + (1 − α) · lexico          con  α ∈ [0, 1]

* `denso` es la similitud coseno, ya absoluta en [0, 1] tras recortar negativos
  (con vectores normalizados y textos reales nunca baja de 0).
* `lexico` es **cobertura de la consulta ponderada por IDF**: qué fracción de la
  información de la pregunta aparece en el fragmento.

        lexico(q, d) = Σ_{t ∈ q ∩ d} idf(t)  /  Σ_{t ∈ q} idf(t)

  Está en [0, 1] por construcción, vale 1 cuando el fragmento contiene todos los
  términos con contenido de la pregunta y 0 cuando no contiene ninguno. Y es
  absoluto: no depende de qué más haya en el pool.

Se usa cobertura y no BM25 precisamente por eso: **BM25 no está acotado ni es
comparable entre consultas** —depende de la longitud de la consulta y del corpus—,
así que serviría para ordenar y no para umbralizar, que es el mismo defecto de RRF
por otro camino.

El IDF sale del corpus entero (`log(N / df)`), no del pool: es lo que hace que
«herida» (df = 111 sobre 16.424) pese menos que «apendicectomía» (df = 104) y
mucho menos que un término que no aparece nunca.
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Iterable, Mapping, Sequence

from app.rag.idioma import _EN, _ES  # las mismas listas de palabras función

__all__ = [
    "PREFIJO",
    "MINIMO_CARACTERES_TERMINO",
    "fundir",
    "cobertura",
    "idf",
    "normalizar_termino",
    "terminos_de_consulta",
]

PREFIJO = 6
"""Caracteres a los que se trunca un término para comparar.

El español flexiona por **sufijo**: «camina / caminar / caminando / caminata»
comparten los seis primeros caracteres. Truncar al prefijo captura la familia
morfológica sin un stemmer y sin una dependencia nueva.

Coste declarado: falsos positivos entre familias que comparten prefijo y no
significado («colon» → «colonia», «capital» → «capitación»). El IDF los acota —un
término que aparece en media colección pesa casi nada— y el canal denso los
contrapesa. Un stemmer real (Snowball) los evitaría a cambio de una dependencia y
de un comportamiento que ya no se puede leer de un vistazo.
"""

MINIMO_CARACTERES_TERMINO = 4
"""Por debajo de esto un «término» es ruido: preposiciones, siglas de una letra,
números sueltos. Además, el FTS5 de ChromaDB usa tokenizador de trigramas y no
admite patrones de menos de tres caracteres."""

_PALABRA = re.compile(r"[a-z0-9ñ]+")
_VACIAS = _ES | _EN


def normalizar_termino(palabra: str) -> str:
    """Minúsculas, sin tildes, truncado al prefijo.

    Quitar tildes es obligatorio aquí y no cosmético: el corpus escribe
    «infección» e «infeccion» en documentos distintos (187 y 56 fragmentos
    respectivamente, medido sobre el índice), y un paciente dictado por STT puede
    producir cualquiera de las dos.
    """
    plano = unicodedata.normalize("NFD", palabra.lower())
    plano = "".join(c for c in plano if unicodedata.category(c) != "Mn")
    return plano[:PREFIJO]


def terminos_de_consulta(consulta: str) -> list[str]:
    """Términos con contenido de la pregunta, normalizados y sin repetir.

    Se descartan las palabras función con las mismas listas que usa la detección
    de idioma (`app/rag/idioma.py`): no hay una segunda lista de vacías que
    mantener sincronizada.
    """
    plano = unicodedata.normalize("NFD", consulta.lower())
    plano = "".join(c for c in plano if unicodedata.category(c) != "Mn")
    vistos: list[str] = []
    for palabra in _PALABRA.findall(plano):
        if len(palabra) < MINIMO_CARACTERES_TERMINO or palabra in _VACIAS:
            continue
        termino = palabra[:PREFIJO]
        if termino not in vistos:
            vistos.append(termino)
    return vistos


def idf(df: int, total: int) -> float:
    """`log(1 + N / (1 + df))`. Positivo siempre, y decreciente en `df`.

    La variante con el `1 +` de fuera evita el IDF negativo del BM25 clásico
    para términos que aparecen en más de la mitad de la colección: aquí un
    término muy común tiene que pesar **poco**, nunca en contra.
    """
    if total <= 0:
        return 0.0
    return math.log(1.0 + total / (1.0 + max(0, df)))


def cobertura(
    terminos: Sequence[str], pesos: Mapping[str, float], texto: str
) -> float:
    """Fracción del IDF de la consulta presente en el fragmento. En [0, 1].

    La presencia se comprueba por **subcadena** del término ya truncado al
    prefijo, sobre el texto normalizado igual. Es lo mismo que hace el índice de
    trigramas de ChromaDB y por eso las frecuencias documentales que alimentan el
    IDF y esta comprobación miden lo mismo — si una usara palabras enteras y la
    otra subcadenas, el peso y la presencia no hablarían del mismo evento.
    """
    total = sum(pesos.get(t, 0.0) for t in terminos)
    if total <= 0:
        return 0.0
    plano = unicodedata.normalize("NFD", texto.lower())
    plano = "".join(c for c in plano if unicodedata.category(c) != "Mn")
    presente = sum(pesos.get(t, 0.0) for t in terminos if t in plano)
    return presente / total


def fundir(denso: float, lexico: float, alfa: float) -> float:
    """`α · denso + (1 − α) · léxico`, con el denso recortado a [0, 1].

    El recorte no es defensivo por gusto: un coseno negativo significa
    «apuntando al lado contrario», y dejarlo entrar en negativo permitiría que un
    fragmento con cobertura léxica alta compensara un denso absurdo.
    """
    return alfa * max(0.0, min(1.0, denso)) + (1.0 - alfa) * max(0.0, min(1.0, lexico))


def pesos_idf(terminos: Iterable[str], frecuencias: Mapping[str, int], total: int) -> dict[str, float]:
    """`término -> idf`. Un término sin frecuencia conocida se trata como df = 0.

    Tratarlo como raro y no como desconocido es la dirección segura: un término
    que el corpus no tiene («ajiaco») debe pesar mucho en el denominador, para que
    su ausencia hunda la cobertura de esa consulta.
    """
    return {t: idf(frecuencias.get(t, 0), total) for t in terminos}
