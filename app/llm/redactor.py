"""LLM #2 — adapta la repregunta al habla local. Opcional por construcción.

La plantilla es el piso y esto es el techo. El redactor recibe una repregunta ya
escrita y la devuelve en registro más natural para un paciente colombiano. Todo
lo que puede salir mal aquí termina en la plantilla original:

* **Timeout duro (~600 ms).** No hay reintento. Si el proveedor tarda, el agente
  emite la plantilla y el paciente no nota nada más que un fraseo más formal.
  Esto es lo que acota la cola del P95 y lo que mantiene el turno en pie durante
  un incidente del proveedor.
* **Guardas de forma.** Un texto vacío, mucho más largo o mucho más corto que la
  plantilla es señal de que el modelo hizo otra cosa (respondió la pregunta,
  agregó consejos, se disculpó). Se descarta y sale la plantilla.

Lo que este módulo NO toca, y es deliberado: **los guiones de cierre**. Ese texto
comunica una clase clínica decidida por la política, y pasarlo por un modelo para
que suene mejor sería ponerle al LLM la mano encima justo en la frase que le dice
al paciente si tiene que ir a urgencias.
"""

from __future__ import annotations

from typing import Callable

from app.contratos import OK, SalidaLLM

__all__ = ["FUENTE_PLANTILLA", "FUENTE_LLM", "PROMPT_SISTEMA", "redactar"]

FUENTE_PLANTILLA = "plantilla"
FUENTE_LLM = "llm"

PROMPT_SISTEMA = (
    "Reescribes preguntas de un seguimiento telefónico postoperatorio para que "
    "suenen naturales a un paciente colombiano, tratándolo de usted.\n"
    "REGLAS ESTRICTAS:\n"
    "1. Conserva exactamente la misma pregunta y las mismas opciones. No "
    "agregues, no quites, no cambies el sentido.\n"
    "2. No des consejos médicos, no interpretes, no saludes, no te disculpes.\n"
    "3. Una o dos frases, más cortas que el original si puedes.\n"
    "4. Responde solo con la pregunta reescrita, sin comillas ni explicación."
)


def redactar(
    completar: Callable[..., SalidaLLM],
    plantilla: str,
    *,
    timeout_ms: int,
    activo: bool = True,
) -> tuple[str, str, SalidaLLM]:
    """Devuelve `(texto, fuente, salida)`. `fuente` es «plantilla» o «llm».

    El valor de `fuente` acaba en el registro de cada turno: es lo que permite
    saber, leyendo el log, cuántas veces el techo estuvo disponible y cuántas
    habló el piso.
    """
    if not activo:
        return plantilla, FUENTE_PLANTILLA, SalidaLLM("", 0.0, "no_invocado", "")

    salida = completar(
        [
            {"role": "system", "content": PROMPT_SISTEMA},
            {"role": "user", "content": plantilla},
        ],
        timeout_ms=timeout_ms,
        max_tokens=120,
        temperatura=0.3,
    )

    if salida.resultado != OK:
        return plantilla, FUENTE_PLANTILLA, salida

    texto = salida.texto.strip().strip('"').strip()
    if not _aceptable(texto, plantilla):
        return plantilla, FUENTE_PLANTILLA, salida
    return texto, FUENTE_LLM, salida


def _aceptable(texto: str, plantilla: str) -> bool:
    """Guardas de forma. No verifican semántica: para eso está el piso."""
    if not texto:
        return False
    if "\n" in texto.strip("\n"):  # varias líneas => el modelo hizo otra cosa
        return False
    largo = len(texto)
    return 0.4 * len(plantilla) <= largo <= 1.6 * len(plantilla)
