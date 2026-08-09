"""Pone la raíz del repo en `sys.path` para que `tests/` importe `politica`.

Sin esto, pytest solo inserta el directorio de los tests. No hay paquete
instalable todavía (Fase 2.1 entrega el módulo, no el empaquetado).
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
