# Tests del módulo de política (Fase 2.1)

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
