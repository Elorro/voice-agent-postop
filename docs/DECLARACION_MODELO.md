# Declaración del modelo de lenguaje — compuerta G3

Este documento existe para que la verificación de G3 no dependa de reconstruir
el razonamiento desde el código. Se lee en dos minutos.

---

## 1. Qué modelo usa la solución

| | Identificador exacto | Dónde corre | Estatus frente a G3 |
|---|---|---|---|
| **Principal (A)** | `models/gemini-3.6-flash` — sucesor de Gemini 1.5 Flash, *identificador **verificado** contra el endpoint el 2026-08-10, ver §5* | Google, endpoint OpenAI-compatible: `https://generativelanguage.googleapis.com/v1beta/openai` | **Autorizado por escrito** por la organización el 2026-08-09 (§3) |
| **Alterna (B)** | `meta-llama/llama-3.1-70b-instruct` | Proveedor con API OpenAI-compatible. En `.env.example`: `https://openrouter.ai/api/v1` | El modelo **literal** de la lista permitida |
| **Fallback (C)** | `llama3.2:3b` (o `llama3.2:1b`) | Local, CPU, servidor OpenAI-compatible (Ollama / llama.cpp) | Celda **«Local, CPU»** de la misma lista |

Los tres hablan el **mismo protocolo**. La integración es una sola: cambian
`LLM_BASE_URL`, `LLM_MODELO` y el timeout del extractor, y nada más. No hay dos
clientes, y por eso ningún perfil es una rama de código sin ejercitar.

**Por qué A y no B**, en el orden en que pesa:

1. **Latencia, y está medido.** `llama3.2:3b` en CPU tarda **7-15 s por
   extracción** (48 s la primera, cargando el modelo). Con eso el presupuesto de
   latencia de la rúbrica no se alcanza por ningún camino. El perfil A, **ya
   medido contra Gemini el 2026-08-10**, deja la extracción en **1,1-1,6 s** y el
   turno completo en **P50 3 777 ms** sobre los 4 turnos limpios de 6 (§5).
   **Contra:** el nivel gratuito concede **20 peticiones por día y por modelo**,
   y una llamada de 6 turnos gasta 11.
2. **Lo que el jurado descarga.** El perfil A no necesita Ollama ni pesos:
   **~2 GB menos** que levantar el fallback.
3. **B cuesta dinero.** El proveedor de la ruta alterna cobra por token y no
   tiene nivel gratuito para ese modelo: hay que cargar saldo antes de la primera
   petición. Un evaluador sin saldo ve fallar la ruta principal sin que nada esté
   mal en el repositorio.

Que B siga documentada y a un descomentado de distancia es deliberado: es el
modelo literal de la lista, y si la autorización de §3 se discutiera, la
solución no se queda sin ruta remota.

Dónde está en el repositorio, para verificarlo sin ejecutar nada:

- `app/config.py` → `llm_base_url`, `llm_modelo`, `llm_perfil`. Ningún default
  apunta a un modelo concreto.
- `app/salud.py` → `sondear_llm`, que comprueba contra el proveedor que el
  modelo configurado **existe** (no solo que la clave sirve).
- `.env.example` → perfil A activo, perfil C comentado al lado.

---

## 2. Por qué no es Groq

Los modelos de la lista permitida servidos por Groq y por Google fueron
retirados **por sus proveedores**. Tres hechos verificados:

| Modelo | Estado | Fecha de apagado | Fuente |
|---|---|---|---|
| `llama-3.1-70b-versatile` (Groq) | Apagado | **24/01/2025** (`01/24/25`) | [console.groq.com/docs/deprecations](https://console.groq.com/docs/deprecations) |
| `llama-3.3-70b-versatile` (Groq) | Apagado | **16/08/2026** (`08/16/26`) | [console.groq.com/docs/deprecations](https://console.groq.com/docs/deprecations) |
| Familia Gemini 1.5 (`gemini-1.5-flash`, `gemini-1.5-pro`, `gemini-1.5-flash-8b`) | Apagada | **29/09/2025** | [ai.google.dev — release notes](https://ai.google.dev/gemini-api/docs/changelog) |

**Fecha de consulta de ambas fuentes: 2026-08-09.**

La segunda fila es la que fuerza la decisión: `llama-3.3-70b-versatile` se apaga
**siete días después** de esta consulta. Una solución entregada apuntando ahí
funciona en la demostración y deja de funcionar dentro de la semana, sin que
nada en el repositorio lo anuncie.

El modo de falla, además, es silencioso: la clave sigue siendo válida y
`GET /models` sigue respondiendo 200. Lo que falla es la primera petición de
inferencia, con `model_decommissioned`. Por eso `sondear_llm` no se conforma con
validar la clave: comprueba que el identificador está en la lista de modelos que
el proveedor sirve. Esa sonda habría cazado este fallo antes de que existiera.

---

## 3. El argumento de cumplimiento

### 3.1 La organización lo autorizó por escrito

Se consultó a la organización qué hacer con los modelos apagados. **Respuesta
recibida el 2026-08-09**, literal:

> «Te aconsejamos migrar directamente hacia las versiones o iteraciones más
> recientes liberadas por los proveedores de dichos modelos (sucesores de los
> modelos), o bien revisar la clasificación actualizada en https://arena.ai»

Eso decide el perfil A y no deja nada que interpretar:

- **Gemini 1.5 Flash estaba en la lista permitida.** Google lo apagó el
  2025-09-29 (§2).
- La respuesta autoriza **el sucesor liberado por el mismo proveedor**, que es
  exactamente lo que configura el perfil A.

La autorización es de la organización, no una lectura propia de las bases. Esa
es la diferencia entre este perfil y cualquier otra sustitución que se hubiera
podido argumentar.

### 3.2 Y por debajo, la lista literal

La posición final tiene dos capas, y la segunda no depende de que nadie acepte
la primera:

| | Cubre G3 por | Si se discutiera |
|---|---|---|
| **A** (activo) | Autorización escrita del 2026-08-09 | Se cae a B o a C comentando cinco líneas de `.env` |
| **B** | Es Llama 3.1 70B, el modelo **literal** de la lista | Requiere saldo, nada más |
| **C** | Es la celda **«Local, CPU»** de la lista, **literal** | Nada: no necesita clave, ni saldo, ni red |

El fallback no es retórica: está empaquetado y probado (§4), y es lo que
convierte esta decisión en reversible en un minuto.

Sobre B, para que quede dicho: la lista nombra el **modelo** —Llama 3.1 70B—, y
«vía Groq» está en la columna de *dónde corre*, que el reto declara parte libre
del stack. Esa ruta **conserva el modelo exigido precisamente porque el proveedor
sugerido lo retiró**; quedarse en Groq habría obligado a usar un modelo que no
está en la lista, que es el incumplimiento real de G3.

Sin reproche a nadie: el reto se escribió antes de los apagados. Esto es
información nueva, no un error de quien redactó las bases.

### Lo que no cambia

La compuerta G3 restringe el modelo de **lenguaje**. El **STT** no está
afectado y se queda donde estaba: `whisper-large-v3` en Groq, que **no aparece
en la tabla de deprecaciones** consultada el 2026-08-09. Son dos servicios
distintos y en esta versión se configuran por separado (`LLM_*` y `STT_*`),
justamente para que mover uno no arrastre al otro.

---

## 4. El fallback local, que no admite discusión

Si la vía remota resulta discutible por cualquier razón —G3, red, cuota,
presupuesto, o una clave que no llega— la solución corre con **Llama 3.2 local**,
celda «Local, CPU» de la misma lista permitida. Cero ambigüedad: el modelo está
en la lista y corre en la máquina del evaluador.

Lo que cuesta usarlo, dicho aquí y no en letra pequeña: **la latencia deja de
cumplir el presupuesto de la rúbrica** (7-15 s por extracción en CPU, medido) y
el evaluador descarga ~2 GB de pesos. Es un fallback de *cumplimiento*, no de
rendimiento.

Dos comandos, más la línea de `.env`:

```bash
docker compose --profile local up -d
docker compose --profile local exec llm-local ollama pull llama3.2:3b
```

y en `.env`:

```
LLM_BASE_URL=http://llm-local:11434/v1
LLM_MODELO=llama3.2:3b
LLM_PERFIL=local
LLM_API_KEY=
EXTRACTOR_TIMEOUT_MS=20000
REDACTOR_TIMEOUT_MS=8000
RAG_TIMEOUT_MS=30000
```

**Los dos timeouts van en el mismo cambio.** Con los 2500 / 4000 ms del perfil A
contra un modelo local, el extractor cae en timeout en *todos* los turnos —
comprobado— y el agente escala por agotamiento sin haber entendido nada. Por eso
`EXTRACTOR_TIMEOUT_MS` y `RAG_TIMEOUT_MS` viven **dentro de cada bloque de perfil**
en `.env.example`, y no en una sección de timeouts al final del archivo: quien
cambie de perfil los tiene delante.

`llama3.2:1b` si la máquina va justa de RAM. Contra un `llama.cpp` u `ollama`
que el evaluador ya tenga corriendo en su host, basta con
`LLM_BASE_URL=http://host.docker.internal:11434/v1` y **no hace falta levantar
el perfil**: es el mismo protocolo.

El servicio `llm-local` de `compose.yaml` lleva `profiles: ["local"]`, así que
`docker compose up -d` a secas lo ignora por completo. La ruta principal no paga
nada por su existencia.

---

## 4.1 Qué hace el proveedor con lo que se le manda

No es una nota legal de relleno: cambia qué perfil es admisible según el dato que
se procese. Términos de la API de Gemini
(<https://ai.google.dev/gemini-api/terms>, consultados el **2026-08-10**):

| Régimen | Texto de los términos |
|---|---|
| **Nivel gratuito** (*Unpaid Services*) | «Google uses the content you submit to the Services and any generated responses to provide, improve, and develop Google products». Revisores humanos pueden leer entradas y salidas |
| **Nivel de pago** (*Paid Services*) | «Google doesn't use your prompts […] or responses to improve our products». Registro breve solo para detectar violaciones de políticas |

**Excepción:** en el EEE, Suiza y Reino Unido se aplican los términos de *Paid
Services* aunque el servicio sea gratuito.

Lo que esto implica para esta solución, dicho sin rodeos:

- **Hoy no hay exposición.** El dataset del reto es **sintético** y las
  conversaciones de prueba también. Nada de lo que sale por la API es dato
  clínico de una persona real.
- **Con voz de pacientes reales, el nivel gratuito quedaría descartado.** Habría
  que facturar —lo que activa *Paid Services*— o irse al **perfil C**, que corre
  en local y no manda nada a ningún tercero. Es una razón de peso para el
  fallback que no aparecía en el argumento original de §4, donde solo pesaban la
  cuota, el saldo y la red.
- El **STT en Groq** es otro proveedor con otros términos, y **no se han
  consultado**. Queda dicho para que nadie deduzca de aquí nada sobre el audio.

---

## 5. Alcance de lo verificado

Para que nadie tenga que fiarse de este documento:

| Afirmación | Cómo se verificó |
|---|---|
| La organización autoriza migrar a los sucesores | Respuesta escrita recibida el **2026-08-09**, citada literal en §3.1 |
| El endpoint OpenAI-compatible de Google existe y responde | `curl` a `https://generativelanguage.googleapis.com/v1beta/openai/models` sin clave, 2026-08-09 → `HTTP 400 {"error":{"message":"Please pass a valid API key"}}`. Responde el API, no un 404 |
| Fechas de apagado de Groq | Consulta a <https://console.groq.com/docs/deprecations>, 2026-08-09 |
| Apagado de Gemini 1.5 | Notas de versión de <https://ai.google.dev/gemini-api/docs/changelog>, 2026-08-09 |
| `whisper-large-v3` no está deprecado | Ausencia en la misma tabla de Groq, 2026-08-09 |
| El proveedor remoto sirve `meta-llama/llama-3.1-70b-instruct` | `curl -s https://openrouter.ai/api/v1/models \| grep llama-3.1-70b-instruct`, 2026-08-09 |
| `llama3.2:1b` y `llama3.2:3b` existen | <https://ollama.com/library/llama3.2/tags>, 2026-08-09 |
| La sonda `sondear_llm` reconoce el modelo servido y detecta el apagado | Corrida contra el proveedor real, 2026-08-09. Con `meta-llama/llama-3.1-70b-instruct` → `[OK] servido y alcanzable (202 ms)`. Con `llama-3.3-70b-versatile` → `[FALLO] el proveedor no sirve «llama-3.3-70b-versatile» (responde con 400 modelos)` |
| El **fallback local funciona end-to-end** | `docker compose --profile local up -d` + `ollama pull llama3.2:1b`, 2026-08-09. Sonda: `[OK] «llama3.2:1b» servido y alcanzable (33 ms) · perfil «local»`. Inferencia real por `POST /v1/chat/completions` desde el contenedor del agente: respuesta `'OK.'` |
| **El identificador del perfil A: `models/gemini-3.6-flash`** | `POST /v1beta/openai/chat/completions` con la clave real, **2026-08-10** → `HTTP 200`, y el campo `model` de la respuesta devuelve `models/gemini-3.6-flash`, es decir el identificador **fijo**, no un alias. Contrato del extractor comprobado en la misma corrida: `fiebre_c=37.2` y `dolor_nrs=3` con sus citas |
| **El nivel gratuito concede 20 peticiones por día y por modelo** | `HTTP 429` con `quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier` y `limit: 20` sobre `gemini-3.5-flash`, **2026-08-10**. Una llamada de 6 turnos gasta 11 peticiones |
| **Latencia del perfil A** | Corrida de 6 turnos con STT real, **2026-08-10**: P50 3 777 ms / P95 4 043 ms de servidor sobre los **4 turnos limpios** de 6. Extractor 1 102–1 643 ms. Detalle y contaminación en README §9.2 |
| **Costo del perfil A: 0,012612 USD por llamada** | Tarifa 1,50 / 7,50 USD por millón (nivel estándar de pago, <https://ai.google.dev/pricing>, **2026-08-10**) sobre los 4 553 / 433 / 338 tokens medidos. **La salida factura `completion_tokens + razonamiento`**, porque la columna de Google dice «Precio de salida (incluidos los tokens de pensamiento)»: el razonamiento aporta el **43,8 %** del costo de salida |
| **Uso del contenido por el proveedor** | Términos de la API de Gemini, **2026-08-10**: el nivel gratuito usa el contenido para mejorar productos de Google; el de pago no. Ver §4.1 |
| `models/gemini-2.0-flash` **no es utilizable** en el nivel gratuito | Mismo `POST`, 2026-08-10 → `HTTP 429 RESOURCE_EXHAUSTED` con `limit: 0` en `generate_content_free_tier_requests` y en `generate_content_free_tier_input_token_count`. **Cuota cero desde la primera petición del día**, no una ráfaga |

El fallback local está **empaquetado y probado**, no solo documentado. Lo
probado fue `llama3.2:1b`; `llama3.2:3b` es el mismo modelo en otro tamaño y el
mismo camino de código, pero **no se ejecutó**.

**Lo que NO está verificado, y se dice aquí y no en letra pequeña:**

1. ~~**El identificador del modelo del perfil A.**~~ **RESUELTO el 2026-08-10.**
   El identificador es **`models/gemini-3.6-flash`**, verificado contra el
   endpoint con la clave real: `HTTP 200` y el campo `model` de la respuesta
   devolviendo el mismo identificador fijo. (`models/gemini-3.5-flash` sirve
   igual y queda como alternativa 1 en `.env.example`; se cambió porque su cubo
   diario de 20 peticiones se había agotado midiendo.) `.env` y `.env.example` ya no llevan
   el marcador `PEGUE_AQUI_...`.

   **El hallazgo que obligó a elegirlo, y que no se esperaba:**
   `models/gemini-2.0-flash` —el identificador que este repositorio traía— es
   **inutilizable en el nivel gratuito**. No por ráfaga ni por cuota agotada por
   uso: la respuesta 429 trae `limit: 0` en las tres métricas del free tier, es
   decir cuota cero desde la primera petición del día. Google lo sacó del nivel
   gratuito. Espaciar las peticiones no lo arregla, y por eso el `--pausa-ms`
   del banco de pruebas y el reintento con backoff de `app/llm/cliente.py`
   —ambos añadidos ese mismo día— **no eran la solución de este problema**,
   aunque siguen siendo correctos para el rate limit de verdad.

   Se descartó `models/gemini-flash-latest`, que también responde 200, por ser
   un **alias**: no se resuelve a una versión fija ni siquiera en el campo
   `model` de la respuesta. Un identificador que Google puede mover sin aviso
   entre hoy y la sustentación rompería esta misma declaración.

   **Alternativas verificadas contra el endpoint el 2026-08-10, en orden.** Para
   cambiar `LLM_MODELO` a mano, en una línea, cuando se agoten las 20 peticiones
   diarias de un modelo — la cuota es **por modelo**, así que el siguiente de la
   lista trae su cubo intacto:

   | # | Identificador | Estado | `LLM_RAZONAMIENTO` |
   |---|---|---|---|
   | 1 | `models/gemini-3.6-flash` | `200`, identificador fijo. **El activo** | `low` (rechaza `none` con 400) |
   | 2 | `models/gemini-3.5-flash` | `200`, identificador fijo | `none` |
   | 3 | `models/gemini-3.5-flash-lite` | `200`, identificador fijo. No razona | `omitir` (rechaza el parámetro) |
   | 4 | `models/gemini-3-flash-preview` | `200`, pero **«preview»**: Google puede cambiarlo o apagarlo sin aviso | `none` |

   **No usar, y queda escrito para que nadie lo reintente:**
   `models/gemini-2.0-flash`, `models/gemini-2.0-flash-lite` y
   `models/gemini-2.0-flash-001` responden `429` con **`limit: 0`** en las tres
   métricas del nivel gratuito — cuota cero desde la primera petición del día.
   `models/gemini-flash-latest` responde `200` pero es un **alias**.

   **No hay cascada automática entre modelos, y es deliberado:** un P50 y un
   costo por llamada de una corrida que saltó de modelo a mitad son una mezcla de
   dos poblaciones y dos tarifas, y un modelo distinto puede degradar el contrato
   del extractor sin que se note. La única cascada del sistema es la que ya
   estaba probada: perfil A → perfil C.

   El comando para rehacer la verificación sigue en `.env.example`:

   ```bash
   curl -s "https://generativelanguage.googleapis.com/v1beta/openai/models" \
     -H "Authorization: Bearer $CLAVE" | grep -o '"id":"[^"]*"'
   ```

   El error, si se pone mal, no es silencioso: `sondear_llm` comprueba que el
   modelo **existe** en el proveedor y `/salud` sale **NO LISTO** nombrando el
   identificador que falló.

2. **La latencia del perfil A.** El argumento de latencia de §1 está medido *del
   lado local* (7-15 s por extracción en CPU) y **estimado** del lado remoto. No
   se ha cronometrado una extracción contra Gemini. La ruta remota tampoco ha
   ejecutado una inferencia real: solo la comprobación de que el modelo está
   servido. Los números del README §9 siguen marcados como PENDIENTE DE MEDICIÓN
   por esa misma razón.

3. **Diagnóstico de clave inválida en el perfil A.** Google responde **400** a
   una clave inválida donde `sondear_llm` espera 401/403
   (`app/salud.py`, rama `codigo in (401, 403)`), así que `/salud` lo reporta
   como «el proveedor no es alcanzable» en vez de «revise la clave». El
   veredicto —NO LISTO— es correcto; el texto que lo acompaña manda a mirar la
   red cuando el problema es la clave.

**Qué imagen corresponde a qué commit:** está en el README, cerca del inicio
(«Correspondencia imagen ↔ repositorio»), con el digest y el comando para
comprobarlo. No se repite aquí a propósito: una sola fuente.
