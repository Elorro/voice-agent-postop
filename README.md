# Voice Agent Post-Op — Tech Sphere Challenge 2026

Agente de voz en español para seguimiento postoperatorio. En construcción.

## Estado
Fase 1 cerrada: diseño de la política de decisión clínica
(`docs/diseno/parametros_politica.md`, fuente única de parámetros).
Fase 2, sub-paso 2.1: módulo puro de decisión (`politica/`) y su batería de tests.

## Setup
_Pendiente. Objetivo: levantable en ≤15 min siguiendo solo este README._

### Tests
```bash
pip install --user -r requirements-dev.txt
python3 -m pytest tests/ -v
DATASET_DIR=/home/luis/Projects/ParticipantArtifacts/dataset python3 -m pytest tests/ -v
```

La segunda forma añade el criterio de aceptación sobre los 160 casos del dev set;
sin `DATASET_DIR` ese test hace skip. Detalle en `tests/README.md`.
