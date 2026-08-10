"""Tipos de frontera entre las piezas del turno. Solo librería estándar.

Existe para que `app/dialogo/orquestador.py` pueda hablar de la salida del STT,
del LLM y del TTS sin importar los módulos que los implementan: importarlos
arrastraría `httpx`, `numpy` y `onnxruntime` a cualquier proceso que solo
quisiera razonar sobre el diálogo —los tests, entre otros— y ataría la
orquestación a un proveedor concreto.

Las tres salidas comparten forma a propósito: texto o bytes, milisegundos
medidos, y un `resultado` que dice cómo terminó. Ese `resultado` es lo que
acaba en el registro; sin él, un turno lento y un turno con timeout se ven
iguales al leer el log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

__all__ = [
    "SalidaSTT",
    "SalidaLLM",
    "SalidaTTS",
    "Servicios",
    "OK",
    "TIMEOUT",
    "JSON_INVALIDO",
    "ERROR",
    "NO_INVOCADO",
]

OK = "ok"
TIMEOUT = "timeout"
JSON_INVALIDO = "json_invalido"
ERROR = "error"
NO_INVOCADO = "no_invocado"


@dataclass(frozen=True)
class SalidaSTT:
    texto: str
    ms: float
    resultado: str = OK
    segundos_audio: float | None = None
    detalle: str = ""


@dataclass(frozen=True)
class SalidaLLM:
    """Una invocación del modelo de lenguaje, con lo que hay que registrar.

    `tokens_in`/`tokens_out` salen del campo `usage` de la respuesta del
    proveedor y valen `None` si el proveedor no lo manda. NUNCA se estiman: un
    número estimado en la columna de consumo es indistinguible de uno medido.
    """

    texto: str
    ms: float
    resultado: str = OK
    modelo: str = ""
    tokens_in: int | None = None
    tokens_out: int | None = None
    reintentos: int = 0
    detalle: str = ""
    # Reintentos por HTTP 429, contados aparte de `reintentos` a propósito: son
    # dos fenómenos distintos y mezclarlos arruina el análisis. `reintentos` es
    # «el modelo devolvió algo que no parsea» (culpa del modelo, sin espera).
    # `reintentos_429` es «el proveedor nos frenó» (culpa de la cuota, CON
    # espera). Un P50 que no distingue los dos no es el mismo número.
    reintentos_429: int = 0
    espera_reintento_ms: float = 0.0
    # Tokens de razonamiento: los que el modelo genera y NO aparecen en
    # `completion_tokens`. Se derivan de `total_tokens - prompt - completion`,
    # que es aritmética sobre lo que el proveedor manda, no una estimación.
    # Medido el 2026-08-10 en `models/gemini-3.5-flash`: 13 de prompt, 9 de
    # completion, 229 de total. Ignorarlos reporta 9 donde se generaron 216.
    tokens_razonamiento: int | None = None

    def a_registro(self, rol: str) -> dict[str, Any]:
        return {
            "rol": rol,
            "modelo": self.modelo,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "ms": round(self.ms, 1),
            "reintentos": self.reintentos,
            "reintentos_429": self.reintentos_429,
            "espera_reintento_ms": round(self.espera_reintento_ms, 1),
            "tokens_razonamiento": self.tokens_razonamiento,
            "resultado": self.resultado,
        }


@dataclass(frozen=True)
class SalidaTTS:
    wav: bytes
    ms: float
    segundos: float
    muestreo_hz: int
    resultado: str = OK
    detalle: str = ""


@dataclass(frozen=True)
class Servicios:
    """Las tres dependencias externas del turno, inyectadas.

    `app/api.py` las construye contra los proveedores reales; los tests las
    construyen contra dobles. La orquestación no distingue entre ambos casos, y
    por eso las rutas de degradación (extractor que devuelve basura, redactor
    que se pasa del timeout) se pueden ejercitar sin red.
    """

    transcribir: Callable[[bytes, str], SalidaSTT]
    completar: Callable[..., SalidaLLM]
    sintetizar: Callable[[str], SalidaTTS]
    metadatos: dict[str, Any] = field(default_factory=dict)

    consultar_rag: Callable[[str, int], Any] | None = None
    """Recuperación sobre el corpus. `None` = sin índice disponible.

    Entró en el sub-paso 3.2 y es **opcional a propósito**, con dos consecuencias
    deliberadas:

    * El turno funciona sin ella. Un índice que no abre degrada a «declaro mi
      límite», no a llamada caída, y `/salud` dice por qué.
    * La suite de tests sigue corriendo sin chromadb ni el modelo de embeddings:
      quien quiera ejercitar el RAG inyecta una función que devuelve fragmentos
      fijos, que además es la única forma de provocar a voluntad el caso que más
      importa —el corpus no cubre la pregunta—.

    La firma devuelve `Sequence[app.rag.tipos.Fragmento]`; se anota `Any` para no
    importar el paquete `app.rag` desde aquí, que es el módulo de frontera y no
    debe depender de nada.
    """
