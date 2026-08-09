# G2 — Cronometraje de levantamiento

Plantilla. **No rellenar con estimaciones**: solo con lo que se observó en un
reloj durante una corrida real.

Cómo se usa: una persona que **no** haya trabajado en el repositorio sigue
`README.md` al pie de la letra, en una máquina limpia, sin ayuda. Quien
cronometra no interviene ni responde preguntas: anota la duda y sigue mirando.
Una duda respondida en voz alta es un dato destruido — es justo lo que el jurado
no va a tener.

---

## Identificación de la corrida

| Campo | Valor |
|---|---|
| Fecha | |
| Hora de inicio | |
| Operador (quien ejecuta) | |
| Cronometrador (quien observa) | |
| Commit / tag del repositorio | |
| Etiqueta de la imagen usada | |

## Máquina

| Campo | Valor |
|---|---|
| Sistema operativo y versión | |
| Arquitectura (x86_64 / arm64) | |
| RAM | |
| Docker: versión (`docker --version`) | |
| Compose: versión (`docker compose version`) | |
| ¿Docker ya estaba instalado? | |
| Ancho de banda de bajada medido | |
| ¿Red corporativa, VPN o proxy? | |

## Tiempos por etapa

Reloj de pared, minuto y segundo. Si una etapa no aplica, escribir «no aplica»,
no «0».

| # | Etapa | Inicio | Fin | Duración | Notas |
|---|---|---|---|---|---|
| 1 | Instalar Docker (si hacía falta) | | | | |
| 2 | `git clone` del repositorio | | | | |
| 3 | Crear `.env` y pegar `LLM_API_KEY` y `STT_API_KEY` | | | | |
| 4 | `docker compose pull` | | | | |
| 5 | `docker compose up -d` | | | | |
| 6 | Arranque del contenedor hasta responder | | | | |
| 7 | Abrir `/salud` y leer el veredicto | | | | |
| 8 | Primer turno de voz completo | | | | |
| | **TOTAL hasta veredicto LISTO** | | | | |
| | **TOTAL hasta primer turno útil** | | | | |

## Veredicto observado en `/salud`

| Componente | Estado observado | Detalle mostrado |
|---|---|---|
| Índice vectorial | | |
| Embedder | | |
| Voz (Piper) | | |
| LLM (modelo de lenguaje) | | |
| STT (transcripción) | | |
| Directorios de escritura | | |
| Dataset | | |
| **VEREDICTO** | | |

## Dudas del operador

La columna del medio va **literal**: la frase que dijo, no su interpretación.
La de la derecha es la prueba de si el README ya lo resolvía o no.

| # | Duda, textual | Línea o sección del README que la resuelve | ¿Existía ya? |
|---|---|---|---|
| 1 | | | |
| 2 | | | |
| 3 | | | |
| 4 | | | |
| 5 | | | |

## Errores y bloqueos

| # | Qué pasó | Mensaje exacto en pantalla | Cómo se salió | Minutos perdidos |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |

## Correcciones que esta corrida obliga a hacer

Una fila por cambio concreto en el README, el compose o el código. Una duda del
operador que el README no resolvía es un defecto del README, no del operador.

| # | Archivo | Cambio | ¿Aplicado? |
|---|---|---|---|
| 1 | | | |
| 2 | | | |
