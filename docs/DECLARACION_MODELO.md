# Declaración del modelo de lenguaje — compuerta G3

Este documento existe para que la verificación de G3 no dependa de reconstruir
el razonamiento desde el código. Se lee en dos minutos.

---

## 1. Qué modelo usa la solución

| | Identificador exacto | Dónde corre |
|---|---|---|
| **Ruta principal (A)** | `meta-llama/llama-3.1-70b-instruct` | Proveedor con API OpenAI-compatible. En `.env.example`: `https://openrouter.ai/api/v1` |
| **Fallback (C)** | `llama3.2:3b` (o `llama3.2:1b`) | Local, CPU, servidor OpenAI-compatible (Ollama / llama.cpp) |

Es **Llama 3.1 70B**, el modelo de la lista permitida, con el identificador que
el proveedor sirve de verdad. El fallback es **Llama 3.2**, celda «Local, CPU»
de la misma lista.

Los dos hablan el **mismo protocolo**. La integración es una sola: cambia
`LLM_BASE_URL` y nada más. No hay dos clientes, y por eso el fallback no es una
rama de código sin ejercitar.

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

La lista permitida nombra el **modelo**: Llama 3.1 70B. «Vía Groq» está en la
columna de *dónde corre*, y el reto declara libre el resto del stack.

Esta solución **conserva el modelo exigido precisamente porque el proveedor
sugerido lo retiró**. La alternativa —quedarse en Groq— habría obligado a usar
un modelo que no está en la lista, que es el incumplimiento real de G3.

Sin reproche a nadie: el reto se escribió antes del apagado del 16/08/2026. Esto
es información nueva, no un error de quien redactó las bases.

### Lo que no cambia

La compuerta G3 restringe el modelo de **lenguaje**. El **STT** no está
afectado y se queda donde estaba: `whisper-large-v3` en Groq, que **no aparece
en la tabla de deprecaciones** consultada el 2026-08-09. Son dos servicios
distintos y en esta versión se configuran por separado (`LLM_*` y `STT_*`),
justamente para que mover uno no arrastre al otro.

---

## 4. El fallback local, que no admite discusión

Si la vía remota resulta discutible por cualquier razón —G3, red, cuota,
presupuesto— la solución corre con **Llama 3.2 local**, celda «Local, CPU» de la
misma lista permitida. Cero ambigüedad: el modelo está en la lista y corre en la
máquina del evaluador.

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
```

`llama3.2:1b` si la máquina va justa de RAM. Contra un `llama.cpp` u `ollama`
que el evaluador ya tenga corriendo en su host, basta con
`LLM_BASE_URL=http://host.docker.internal:11434/v1` y **no hace falta levantar
el perfil**: es el mismo protocolo.

El servicio `llm-local` de `compose.yaml` lleva `profiles: ["local"]`, así que
`docker compose up -d` a secas lo ignora por completo. La ruta principal no paga
nada por su existencia.

---

## 5. Alcance de lo verificado

Para que nadie tenga que fiarse de este documento:

| Afirmación | Cómo se verificó |
|---|---|
| Fechas de apagado de Groq | Consulta a <https://console.groq.com/docs/deprecations>, 2026-08-09 |
| Apagado de Gemini 1.5 | Notas de versión de <https://ai.google.dev/gemini-api/docs/changelog>, 2026-08-09 |
| `whisper-large-v3` no está deprecado | Ausencia en la misma tabla de Groq, 2026-08-09 |
| El proveedor remoto sirve `meta-llama/llama-3.1-70b-instruct` | `curl -s https://openrouter.ai/api/v1/models \| grep llama-3.1-70b-instruct`, 2026-08-09 |
| `llama3.2:1b` y `llama3.2:3b` existen | <https://ollama.com/library/llama3.2/tags>, 2026-08-09 |
| La sonda `sondear_llm` reconoce el modelo servido y detecta el apagado | Corrida contra el proveedor real, 2026-08-09. Con `meta-llama/llama-3.1-70b-instruct` → `[OK] servido y alcanzable (202 ms)`. Con `llama-3.3-70b-versatile` → `[FALLO] el proveedor no sirve «llama-3.3-70b-versatile» (responde con 400 modelos)` |
| El **fallback local funciona end-to-end** | `docker compose --profile local up -d` + `ollama pull llama3.2:1b`, 2026-08-09. Sonda: `[OK] «llama3.2:1b» servido y alcanzable (33 ms) · perfil «local»`. Inferencia real por `POST /v1/chat/completions` desde el contenedor del agente: respuesta `'OK.'` |

El fallback local está **empaquetado y probado**, no solo documentado. Lo
probado fue `llama3.2:1b`; `llama3.2:3b` es el mismo modelo en otro tamaño y el
mismo camino de código, pero **no se ejecutó**.

**Lo que NO está verificado, y se dice aquí y no en letra pequeña:** la ruta
remota (perfil A) no ha ejecutado ninguna inferencia real —solo la comprobación
de que el modelo está servido—, porque el cliente del LLM del agente todavía no
está implementado: el repositorio está en el esqueleto de Fase 3. De ninguna de
las dos rutas se ha medido calidad ni latencia de respuesta. Los números del
README §9 siguen marcados como PENDIENTE DE MEDICIÓN por esa misma razón.
