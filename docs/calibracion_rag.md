# Calibración del RAG — mediciones, no elecciones

Fecha de todas las corridas: **2026-08-10**. Máquina: Fedora Linux (x86_64),
Docker 29.6.0. Índice: 16 424 fragmentos de 104 documentos.

Este documento existe porque tres números del sistema —tamaño de trozo, solape y
umbral de suficiencia— podrían haberse elegido a ojo y no se eligieron. Cada uno
tiene su medición, su comando y su consecuencia. Y una de esas mediciones dice
que el embedder no sirve para lo que se le pide; eso también está aquí.

---

## 1. Troceo: el tamaño lo fija el embedder

```
docker compose --profile herramientas run --rm indexador scripts/calibrar_troceo.py
```

El modelo por defecto de ChromaDB (`all-MiniLM-L6-v2`, ONNX) se carga con
`tokenizer.enable_truncation(max_length=256)`. Un trozo más largo **no se indexa
entero: se corta en silencio**. Así que el tamaño en caracteres tiene que
traducirse a ≤ 256 tokens, y la tasa hay que medirla sobre este corpus, porque el
vocabulario del modelo es mayoritariamente inglés y el español se fragmenta más.

**Caracteres por token** (ventanas de 1 200 caracteres, 107 documentos):

| idioma | ventanas | media | P05 | mínimo |
|---|---|---|---|---|
| en | 1 953 | 4,126 | 2,697 | 1,420 |
| es | 1 393 | 3,080 | **2,537** | 1,043 |

Techo real a 256 tokens con el peor caso del español (P05): **649 caracteres**.

**Longitud de oración** (n = 51 780): media 105,5 · P50 **69** · P75 147 ·
P90 235 · P95 309 · P99 590 · máx 3 259.

**Decisión.** `RAG_TROZO_CARACTERES=600` (8 % por debajo del techo de 649) y
`RAG_SOLAPE_CARACTERES=150` (≈ 2 oraciones medianas). El solape no existe para
que las oraciones no se partan —el troceo empaqueta oraciones enteras y ya lo
garantiza— sino para conservar la oración que *introduce* la respuesta.

**Verificación a posteriori** (la imprime el indexador en cada corrida): tokens
por trozo P50 = 154, P95 = 213, P99 = 283, máx = 583. **222 trozos de 16 424
(1,35 %) superan los 256 tokens** y el embedder les corta la cola. Con 150
caracteres de solape, la cola cortada de un trozo reaparece al principio del
siguiente salvo en los casos extremos (tablas sin puntuación, listados de
referencias). Queda declarado, no escondido.

---

## 2. Duplicados: el hash exacto no los ve

El README del reto avisa de documentos repetidos. Con hash SHA-256 del texto
extraído se encontraron **cero**. Midiendo similitud de Jaccard sobre shingles de
7 palabras entre los 5 565 pares posibles:

| Jaccard | par |
|---|---|
| 0,9819 | `total joint replacement/Orthopaedic Surgery - 2019 - Li - Postoperative Pain Management in Total Knee Arthroplasty.pdf` ≡ `…/Postoperative Pain Management in Total Knee Arthroplasty.pdf` |
| 0,9709 | `colorectal cancer/Recommendations for follow-up of colorectal cancer survivors.pdf` ≡ `…/ecommendations for follow-up of colorectal cancer survivors.pdf` |
| < 0,30 | **todos los demás pares del corpus** |

Son el mismo artículo exportado dos veces. Lo que los diferencia es el encabezado
del editor: `Vol.:(0123456789)1 3` contra `Vol:.(1234567890)`. Dos caracteres de
maquetación y el SHA-256 deja de coincidir.

**Decisión.** Umbral de duplicado en **0,90**, dentro de un hueco que va de 0,30 a
0,97 y en el que no cae ni un par. Ver `app/rag/duplicados.py`.

---

## 3. Documentos descartados, por nombre

| Documento | Motivo |
|---|---|
| `Appendicitis/REVISIÓN DE LA LITERATURA SOBRE LAAPENDICITIS AGUDA PEDIATRICA NO ESPECIFICADA EN EL PERI000 2000-2021.pdf` | Escaneado, **0,0 caracteres por página**. Se descarta explícitamente; no se le hace OCR (razonamiento en `app/rag/extraccion.py`) |
| `colorectal cancer/ecommendations for follow-up…pdf` | Duplicado por solapamiento (0,9709) |
| `total joint replacement/Postoperative Pain Management in Total Knee Arthroplasty.pdf` | Duplicado por solapamiento (0,9819) |

Un cuarto documento estuvo a punto de perderse en silencio:
`breast_cancer/Herramientas-Tecnica-Cancer-cuello-uterino-2018.pdf` viene cifrado
con AES y contraseña de usuario vacía. Sin `cryptography`, `pypdf` falla y sus 14
páginas quedan fuera del índice sin aviso. Se añadió la dependencia (4,52 MB) en
vez de perder el documento.

**Resultado: 104 de 107 documentos indexados**, 16 424 fragmentos, 1 274 s de
indexación, `indice_base/` de 99,3 MB con el archivo mayor en 71,71 MB (límite
duro declarado: 90 MB).

---

## 4. El embedder en español: la medición que decide

```
docker compose --profile herramientas run --rm indexador scripts/calibrar_umbral.py
```

`all-MiniLM-L6-v2` es **monolingüe inglés**. Se heredó al decidir «onnxruntime, no
torch», que era una decisión sobre el peso de la imagen y no sobre el idioma. El
corpus es mayoritariamente español y las preguntas del paciente son todas en
español. Esto es cuánto cuesta.

Dos poblaciones: 10 consultas clínicas en español cuya respuesta está en el
corpus, y 8 consultas ajenas a él. Y el mismo par traducido al inglés, contra el
**mismo índice**, para aislar el idioma como variable.

### 4.1 Régimen denso puro (α = 1,0)

| población | n | mín | mediana | máx |
|---|---|---|---|---|
| español · cubiertas | 10 | 0,638 | 0,706 | 0,783 |
| español · ajenas | 8 | 0,482 | 0,576 | 0,617 |
| inglés · cubiertas | 10 | 0,595 | 0,682 | 0,808 |
| inglés · ajenas | 8 | 0,209 | 0,275 | 0,455 |

Escenario esperado en el top-5: español **10/10**, inglés **10/10**.
Hueco entre poblaciones: **español +0,021 · inglés +0,141**.

Las preguntas ajenas en inglés («what is the capital of Australia») caen a 0,21;
las mismas en español se quedan en 0,48. Mismo contenido, mismo índice, mismo
modelo. El coseno en español está midiendo sobre todo «esto es texto en español».

### 4.2 El 10/10 por escenario es un proxy que miente

El criterio automatizable —«¿sale el fragmento del escenario correcto?»— da 10/10.
Leyendo los fragmentos, la pertinencia es otra cosa:

| consulta | top-1 denso | ¿responde? |
|---|---|---|
| ¿Cuánto dolor es normal tras apendicectomía? | «Las mujeres tienen mayor probabilidad de apendicectomía… el 16 % fue laparoscópica» | no |
| ¿Qué signos de infección debo vigilar? | «• Utilice calzado cerrado. Consultas por otros especialistas…» | no |
| Tengo fiebre tras apendicectomía, ¿qué hago? | «Entre 2017 y 2021 se diagnosticaron 345.618 casos (51,8 % mujeres)…» | no |
| ¿Cómo cuido la herida en casa? | «Zonas comunes • Asegurar que las áreas de la casa estén libres de obstáculos…» | no |
| ¿Cuándo puedo caminar tras el reemplazo de rodilla? | «Boca abajo, en una superficie firme, doblar la rodilla…» | parcial |

En la consulta 5, el puesto 3 (score 0,676, **por encima de todas las ajenas**) es
propaganda corporativa: «Somos parte del grupo Quirónsalud, una compañía líder en
España…». El score no lleva casi información sobre pertinencia.

### 4.3 Recuperación híbrida: se probó y no arregla el español

Se implementó fusión de coseno con **cobertura léxica ponderada por IDF**
(`app/rag/lexico.py`), con IDF tomado del índice FTS5 que ChromaDB ya construye.
Se descartó RRF por una razón de primeros principios: RRF conserva el orden y
descarta la magnitud, y una consulta ajena también tiene un puesto 1 — con RRF
**no existe umbral de suficiencia posible**. Lo mismo vale para cualquier
normalización relativa a la consulta (min-max sobre el pool).

Barrido de α (peso del canal denso), hueco entre poblaciones:

| α | hueco español | hueco inglés |
|---|---|---|
| 1,00 | **+0,021** | +0,141 |
| 0,75 | +0,002 | **+0,205** |
| 0,60 | −0,056 | +0,156 |
| 0,50 | −0,094 | +0,100 |
| 0,25 | −0,191 | −0,039 |
| 0,00 | −0,303 | −0,179 |

En inglés la fusión **mejora**. En español empeora de forma monótona, y la causa
está medida: **el IDF calculado sobre este corpus invierte la informatividad**.
En una colección monotemática de cirugía, `apendi` aparece en 648 fragmentos y
`cuanto` en 194, así que el IDF pesa más «cuánto» que «apendicectomía». Al
reordenar un pool ancho gana el fragmento que comparte las palabras genéricas de
la pregunta.

Es un defecto del **origen** del IDF, no del método de fusión: haría falta
frecuencias de una colección de español general, que es un artefacto nuevo.

Lo que la fusión sí hizo, y quedó medido: en las 8 consultas ajenas la cobertura
léxica del top-1 denso es **0,000**, y en las 10 cubiertas es **≥ 0,087**. Como
compuerta de rechazo el canal léxico separa perfectamente; como reordenador con
IDF interno, no.

### 4.4 Configuración entregada: `RAG_ALFA=0.5` · `RAG_UMBRAL=0.59`

Medición de las cuatro poblaciones **con la fusión activa** (α = 0,5), sobre el
mismo índice y con el mismo guion:

| población | n | mín | mediana | máx |
|---|---|---|---|---|
| español · cubiertas | 10 | 0,442 | 0,658 | 0,710 |
| español · ajenas | 8 | 0,344 | 0,444 | **0,536** |
| inglés · cubiertas | 10 | 0,538 | 0,780 | 0,904 |
| inglés · ajenas | 8 | 0,124 | 0,292 | 0,437 |

Con `RAG_UMBRAL=0.59`:

* **Rechaza las 8 consultas ajenas medidas**, con **0,054 de margen** sobre la
  peor (0,536). En denso puro ese margen era 0,033.
* **Acepta el documento subido de G5** (0,6499), que en denso puro era imposible.
* Acepta 6 de las 10 consultas cubiertas del corpus. Las otras 4 reciben «no
  tengo el dato».

Ese último punto es el precio, y es el lado correcto del error: **declarar un
límite de más es lo que la rúbrica premia; responder desde un fragmento
irrelevante es lo que penaliza.**

#### Por qué esto sustituye al `RAG_ALFA=1.0` / `RAG_UMBRAL=0.65` inicial

La primera entrega usó denso puro con umbral 0,65, argumentando que era «el lado
seguro». Se cambió por dos razones, en este orden:

1. **Fallaba G5, que es compuerta eliminatoria.** Fallar G5 anula el trabajo, no
   lo puntúa menos. Y no era un fallo ajustable: en denso puro la respuesta
   correcta puntúa 0,5988 y una consulta ajena llega a 0,617, así que **ningún
   umbral** sirve (§5).
2. **La seguridad que compraba era nominal.** Se apoyaba en un hueco de **0,021
   medido con n = 18**. Eso está dentro del ruido de muestreo: con dos consultas
   ajenas más el hueco podría ser negativo. Un margen de 0,054 sobre la misma
   muestra es una afirmación más defendible que uno de 0,033 sobre un hueco que
   no se distingue de cero.

El solape de las dos poblaciones del corpus (−0,094) sigue ahí y se declara: no
hay umbral que acepte las 10 cubiertas y rechace las 8 ajenas. Lo que se elige es
en qué dirección fallar.

#### La segunda línea de defensa, que es la que hace tolerable el umbral

Un umbral más bajo deja pasar más fragmentos marginales al modelo. Por eso la
**primera** regla del prompt de generación (`app/rag/respuesta.py`) es declarar el
límite, y cubre explícitamente el caso que el umbral no puede cubrir:

> «SI LAS FUENTES NO RESPONDEN LA PREGUNTA, DECLÁRALO. […] Esto aplica también
> cuando las fuentes hablan del mismo tema pero no contestan lo que se preguntó,
> cuando solo lo rozan, o cuando tendrías que completar con lo que sabes por tu
> cuenta. NO fuerces una respuesta: decir que no está es una respuesta correcta y
> preferible.»

El umbral resuelve «el corpus no habla del tema»; esta regla resuelve «habla del
tema y aun así no responde ESTA pregunta». Son compuertas independientes, y la
tercera —las citas en `turnos.jsonl`— permite auditar las dos.

---

## 5. El caso que decidió la configuración: G5

El embedder monolingüe **impide pasar la compuerta G5 en el régimen denso puro**,
y no es una opinión: es aritmética sobre números medidos.

Documento subido a la consola (`scripts/documento_de_prueba.py`, ajeno al corpus),
consulta «¿En qué horario atiende la línea Antares y a qué número debo llamar?»:

| puesto | score denso | fragmento |
|---|---|---|
| 1 | 0,6418 | «Boca abajo, en una superficie firme, doblar la rodilla lo máximo que pueda…» (corpus, ejercicio de rodilla) |
| **2** | **0,5988** | «El numero de la linea Antares es el 604 555 0142 y atiende de lunes a sabado entre las siete de la manana y las nueve de la noche» (**el documento subido, la respuesta literal**) |

El fragmento correcto puntúa **por debajo** de un ejercicio de rodilla sin
relación, y por debajo de la mejor consulta ajena del corpus (0,617). **No existe
ningún umbral sobre el score denso que acepte la respuesta correcta y rechace las
consultas ajenas.**

Con la fusión activa (α = 0,5) el mismo caso se ordena bien: el documento subido
pasa al puesto 1 con **0,6499** —denso 0,5988 · léxico 0,7009— y el ejercicio de
rodilla cae a 0,3255. El término «Antares» tiene `df = 3` sobre 16 424
fragmentos, así que el IDF le da todo el peso: es exactamente el caso en el que
el canal léxico funciona, y el que el barrido de §4.3 no medía porque todas sus
consultas usaban vocabulario común del corpus.

**Las dos configuraciones, sobre la misma muestra:**

| | α = 1,0 · umbral 0,65 | **α = 0,5 · umbral 0,59 (entregado)** |
|---|---|---|
| rechaza las 8 consultas ajenas | sí, margen 0,033 | sí, **margen 0,054** |
| acepta las 10 cubiertas del corpus | 8 de 10 | 6 de 10 |
| acepta el documento subido (G5) | **no** (0,5988 < 0,65) | **sí** (0,6499) |
| ordena bien el caso G5 | no (puesto 2, debajo de un ejercicio de rodilla) | sí (puesto 1, con el doble de margen) |
| hueco entre poblaciones (es) | +0,021 (n = 18: dentro del ruido) | −0,094 (solape declarado) |

Se entrega la segunda. Ninguna de las dos tiene separación limpia entre las
poblaciones del corpus; la diferencia decisiva es que una **pasa** la compuerta
eliminatoria y la otra no, y que su margen de rechazo es mayor sobre la misma
muestra.

El solape que se acepta lo contiene la segunda línea de defensa del prompt
(§4.4): un fragmento del mismo tema que no responde la pregunta se rechaza
después de leerlo, que es donde se puede juzgar.

La salida de fondo sigue siendo cambiar el embedder por uno multilingüe
(`paraphrase-multilingual-MiniLM-L12-v2` o `multilingual-e5-small`, ~120 MB en
ONNX int8). No cabe en la holgura actual de la imagen sin podar, y esa decisión
excede este sub-paso.

---

## 6. Ciclo G5 verificado con la configuración entregada

Documento: `scripts/documento_de_prueba.py` genera un PDF de 2 páginas con datos
ficticios que no existen en ninguno de los 107 del corpus. Consulta: «¿En qué
horario atiende la línea Antares y a qué número debo llamar?».

| fase | respuesta literal del agente | `mejor_score` |
|---|---|---|
| **1. preguntar antes** | «Sobre eso no tengo información en mis fuentes, así que prefiero no responderle de memoria. Dejo su pregunta anotada para el equipo que lo operó.» | 0,3239 (< 0,59) |
| **2. subir** | HTTP 202 · `en cola` → `procesando` → `procesado y disponible`, 2 págs., 3 fragmentos | — |
| **3. preguntar después** | «La Línea Antares atiende de lunes a sabado entre las siete de la mañana y las nueve de la noche. Debe llamar al 604 555 0142.» | **0,6499** (≥ 0,59) |
| **4. eliminar** | `{"eliminado":…,"fragmentos_borrados":3}` · inventario vacío | — |
| **5. preguntar de nuevo** | «Sobre eso no tengo información en mis fuentes, así que prefiero no responderle de memoria. Dejo su pregunta anotada para el equipo que lo operó.» | 0,3239 (< 0,59) |

El `mejor_score` de la fase 5 es **idéntico** al de la fase 1: el índice volvió
exactamente a su estado anterior, no a uno parecido.
