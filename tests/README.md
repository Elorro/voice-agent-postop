# Tests: política (2.1), turno de voz (3.1) y RAG (3.2)

## Cómo se corre

```bash
python3 -m pytest tests/ -v
DATASET_DIR=./dataset python3 -m pytest tests/ -v
```

La primera corrida omite `tests/test_dev_set.py` (skip, no falla): es el único test
que lee el dataset. La segunda lo incluye y es la que verifica el **criterio de
aceptación** sobre los 160 casos.

Dependencias: `pip install --user -r requirements-dev.txt`. El módulo `politica/`
no depende de ninguna: solo librería estándar.

## Qué verifica cada archivo

| Archivo | Cubre |
|---|---|
| `test_kleene.py` | §1.1 — tablas de Kleene fuerte, neutros de las operaciones n-arias, `AUSENTE` nunca colapsa a `FALSO`. |
| `test_niveles.py` | §2.1 casos de borde del enrutador · §3 banderas y precedencia · §4 compuerta (incl. `DESCONOCIDO` como activa) · §5 conteo y umbral asimétrico · §7.1 suficiencia · §7.4 cierre forzado · §8 escalamiento · §8.2 errores de invocación · par de colisión (D5). |
| `test_contrato.py` | HD5 consistencia de `Decision` · HD6 orden de indagación · HD7 contabilidad del presupuesto · pureza (idempotencia, no mutación, solo stdlib) · property test §4↔§5 · invariante duro §8.1 sobre el espacio de entradas. |
| `test_dev_set.py` | Criterio de aceptación sobre los 160 casos y equivalencia caso a caso con el oráculo `scripts/verificacion_hd1.py`. |
| `test_extraccion.py` | LLM #1: contrato de dominio cerrado, «cita o no cuenta», y las degradaciones (JSON roto, timeout, valores fuera de dominio) que terminan en AUSENTE y nunca en un valor plausible. |
| `test_plantillas.py` | Cobertura: una repregunta por señal del núcleo y un guion por clase, verificado **contra `politica/`** para que una señal nueva no pueda quedarse muda. |
| `test_registro.py` | `turnos.jsonl`: escritura, parcheo de la telemetría, percentiles y consumo leídos del archivo. |
| `test_turno.py` | El turno completo con los tres servicios externos sustituidos por dobles: orden de etapas, presupuesto cobrado al emitir, y cada degradación bajando un escalón sin tumbar la llamada. |
| `test_import_unico_politica.py` | Un solo `import politica` en todo el árbol, sobre los archivos rastreados por git. |
| `test_llm_razonamiento.py` | Cuándo viaja `reasoning_effort` y cuándo NO. Con `LLM_RAZONAMIENTO` vacía la clave **no aparece en el cuerpo** (es lo que el perfil C necesita); con un valor explícito sí (es lo que el perfil A necesita). Ausente ≠ vacía. |
| `test_salud_llm.py` | La sonda del LLM. **Listar un modelo no es servirlo**: una inferencia real con los mismos parámetros del turno, y su fallo distinguible de «no alcanzable». Más las categorías de diagnóstico: `transitorio` → recargue; `no_infiere` y `modelo_inexistente` → recargar no sirve. |
| `test_rag_troceo.py` | Troceo y solape contra el techo de 256 tokens del embedder, atribución de página, determinismo, y detección de idioma. |
| `test_rag_duplicados.py` | Duplicados **exactos y casi exactos**: el corpus trae de los dos y el SHA-256 solo ve los primeros. |
| `test_rag_recuperacion.py` | **Umbral de suficiencia.** Por debajo del umbral la recuperación devuelve vacío; el umbral se aplica fragmento a fragmento, no solo al mejor. |
| `test_rag_respuesta.py` | Separación dato/instrucción, y la propiedad central: **sin fragmentos no se invoca al modelo**. No existe ruta en la que redacte una respuesta clínica sin fuentes. |
| `test_rag_no_altera_clase.py` | **Ninguna salida del RAG mueve la clase.** El mismo turno con y sin un RAG adversario, exigiendo la misma decisión, más la reejecución de `politica.decidir` sobre la entrada anotada. |
| `test_rag_documentos.py` | Ciclo de vida de un documento subido: `pendiente → procesando → disponible`/`error`, y que «disponible» se afirme **contando fragmentos dentro del índice**. |
| `test_consola_documentos.py` | Los cuatro endpoints de G5 contra la aplicación real. Hace `skip` sin `fastapi` instalado (es dependencia de runtime, no de test). |

## Criterio de aceptación (`test_dev_set.py`)

```
recall_rojo = 1.000   C_FN = 0   c₁ = 0   c₃ = 0   c₂ = 11   (4 temprano + 7 tardío)
criterio de cierre:   S1 = 12   S2 = 93   S3 = 36   CIERRE_FORZADO = 19
los 19 forzados:      régimen temprano, n_total == 1, clase VERDE, todos verde real
```

Los números salen de `scripts/verificacion_hd1_salida.txt`. La spec ya está
verificada: si el módulo no los reproduce, el módulo está mal.

## Sobre el oráculo

`scripts/verificacion_hd1.py` es una reimplementación **independiente** de la spec,
escrita antes de que existiera `politica/`. Se importa **solo** en
`tests/test_dev_set.py`, para el test de equivalencia. Ni el módulo ni los tests de
unidad lo importan: si salieran del mismo código, el test no probaría nada.
