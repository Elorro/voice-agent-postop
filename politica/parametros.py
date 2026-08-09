"""Único lugar del código donde vive un valor de la política.

Cada constante transcribe una fila de `docs/diseno/parametros_politica.md`. Si un
valor aparece duplicado en cualquier otro archivo del repo, es un bug (§0, regla 1).
Nada de este archivo se decide aquí: se copia de la spec, con su sección al lado.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from .tipos import Regimen

__all__ = [
    "CORTE_ENRUTADOR",
    "DIA_POSTOP_MINIMO",
    "VENTANA_CORPUS_DIAS",
    "DOLOR_NRS_MINIMO",
    "DOLOR_NRS_MAXIMO",
    "UMBRAL_FIEBRE_FRANCA",
    "UMBRAL_DOLOR_SEVERO",
    "UMBRAL_G_FIEBRE",
    "UMBRAL_G_DOLOR",
    "UMBRAL_S_FIEBRE",
    "UMBRAL_S_DOLOR",
    "UMBRAL_CONTEO_AMARILLO",
    "TOPE_POR_SENAL",
    "TOPE_GLOBAL",
    "HERIDA_NORMAL",
    "HERIDA_ERITEMA_LEVE",
    "HERIDA_SECRECION_PURULENTA",
    "MOVILIDAD_NORMAL",
    "MOVILIDAD_LIMITADA_ESPERADA",
    "MOVILIDAD_INCAPACITANTE_NUEVA",
    "APETITO_NORMAL",
    "APETITO_LEVEMENTE_DISMINUIDO",
    "APETITO_MUY_DISMINUIDO",
    "SUENO_NORMAL",
    "SUENO_LEVEMENTE_ALTERADO",
    "SUENO_MUY_ALTERADO",
    "DOMINIOS_CATEGORICOS",
]

# --- §2 Nivel 0, enrutador temporal ---------------------------------------- #
CORTE_ENRUTADOR: int = 4
"""§2. `dia_postop >= 4` -> TARDÍO. [INFERENCIA] ancla externa al dataset (D6)."""

DIA_POSTOP_MINIMO: int = 0
"""§2.1. Día 0 (mismo día de la cirugía) es válido; por debajo es error de invocación."""

VENTANA_CORPUS_DIAS: int = 30
"""§2.1. Borde de la ventana que cubre el corpus. [ESPECULACIÓN] pendiente RAG."""

# --- §1 Dominio numérico de las señales ------------------------------------ #
DOLOR_NRS_MINIMO: int = 0
DOLOR_NRS_MAXIMO: int = 10
"""§1. Escala NRS declarada 0-10 (el dominio observado {0..6,9} es del generador)."""

# --- §3 Nivel 1, banderas rojas -------------------------------------------- #
UMBRAL_FIEBRE_FRANCA: float = 38.0
"""§3 `fiebre_franca`. [INFERENCIA] ancla externa al dataset: umbral febril clínico."""

UMBRAL_DOLOR_SEVERO: Mapping[Regimen, int] = MappingProxyType(
    {
        Regimen.TARDIO: 7,
        Regimen.TEMPRANO: 9,
    }
)
"""§3 `dolor_severo`. Umbral INDEXADO por régimen, no conjunción con el régimen (§3.1).

TARDÍO = 7: [INFERENCIA] ancla externa al dataset, tercil severo de la NRS (7-10).
TEMPRANO = 9: [ESPECULACIÓN] la banda severa no tiene observaciones en temprano
(`max = 6`), así que nada medido lo fija y cualquier valor en {7,8,9,10} cuesta cero
sobre los 160. Se fija por dirección segura bajo la matriz de costos (§9) y por dejar
dos puntos de margen sobre el techo verde observado. Deuda de anclaje al corpus,
ítem propio (§10).
"""

# --- §4 Nivel 1.5, compuerta de no-verde ----------------------------------- #
UMBRAL_G_FIEBRE: float = 37.8
"""§4 `g_fiebre`. [INFERENCIA] selección sobre el dev set, declarada (0/58 verdes)."""

UMBRAL_G_DOLOR: int = 5
"""§4 `g_dolor`. [INFERENCIA] selección sobre el dev set: `verde_max` tardío (4) + 1.

Comparte valor y procedencia con `UMBRAL_S_DOLOR` (§10, deuda de convergencia):
son dos parámetros con semántica distinta y **no deben editarse por separado**.
"""

# --- §5 Nivel 2, señales blandas ------------------------------------------- #
UMBRAL_S_FIEBRE: float = 37.5
"""§5.1 `s_fiebre`. Febrícula sin «sostenida» (H1). Origen del valor: deuda menor abierta."""

UMBRAL_S_DOLOR: int = 5
"""§5.1 `s_dolor`. Mismo valor y procedencia que `UMBRAL_G_DOLOR` — ver allí."""

UMBRAL_CONTEO_AMARILLO: Mapping[Regimen, int] = MappingProxyType(
    {
        Regimen.TARDIO: 1,
        Regimen.TEMPRANO: 2,
    }
)
"""§5.2. `n_total >= umbral` -> AMARILLO. Asimétrico por régimen (H4)."""

# --- §7.2 Topes de indagación ---------------------------------------------- #
TOPE_POR_SENAL: int = 2
"""§7.2 profundidad. [ESPECULACIÓN] pendiente de calibración en Fase 3 (rango 2-3)."""

TOPE_GLOBAL: int = 6
"""§7.2 amplitud. [ESPECULACIÓN] pendiente de calibración en Fase 3 (rango 6-8)."""

# --- §1 Dominios categóricos ----------------------------------------------- #
HERIDA_NORMAL: str = "normal"
HERIDA_ERITEMA_LEVE: str = "eritema_leve"
HERIDA_SECRECION_PURULENTA: str = "secrecion_purulenta"

MOVILIDAD_NORMAL: str = "normal"
MOVILIDAD_LIMITADA_ESPERADA: str = "limitada_esperada"
MOVILIDAD_INCAPACITANTE_NUEVA: str = "incapacitante_nueva"

APETITO_NORMAL: str = "normal"
APETITO_LEVEMENTE_DISMINUIDO: str = "levemente_disminuido"
APETITO_MUY_DISMINUIDO: str = "muy_disminuido"

SUENO_NORMAL: str = "normal"
SUENO_LEVEMENTE_ALTERADO: str = "levemente_alterado"
SUENO_MUY_ALTERADO: str = "muy_alterado"

DOMINIOS_CATEGORICOS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "herida": (HERIDA_NORMAL, HERIDA_ERITEMA_LEVE, HERIDA_SECRECION_PURULENTA),
        "movilidad": (
            MOVILIDAD_NORMAL,
            MOVILIDAD_LIMITADA_ESPERADA,
            MOVILIDAD_INCAPACITANTE_NUEVA,
        ),
        "apetito": (APETITO_NORMAL, APETITO_LEVEMENTE_DISMINUIDO, APETITO_MUY_DISMINUIDO),
        "sueno": (SUENO_NORMAL, SUENO_LEVEMENTE_ALTERADO, SUENO_MUY_ALTERADO),
    }
)
"""§1. Valor fuera del dominio declarado -> error de invocación (§8.2)."""
