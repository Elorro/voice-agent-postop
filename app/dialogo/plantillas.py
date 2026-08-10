"""El PISO de la conversación: todo lo que el agente dice, escrito a mano.

La plantilla es el piso y el LLM es el techo. Son seis señales del núcleo: las
repreguntas caben en un archivo y se pueden escribir en registro clínico, revisar
una por una y dejarlas fijas. El redactor (LLM #2) solo las adapta al regionalismo
y tiene un timeout duro; si no llega, sale esto. Esa asimetría es la que acota la
cola del P95 y la que mantiene el agente hablando durante un incidente del
proveedor.

Dos propiedades que estos textos deben conservar:

1. **La repregunta enuncia el dominio cerrado.** «¿normal, con enrojecimiento
   leve, o supurando?» no es una florituna: es lo que hace que la respuesta del
   paciente caiga dentro del dominio que el extractor puede validar. Una pregunta
   abierta traslada al LLM la tarea de inventar la categoría, que es exactamente
   lo que el contrato del extractor prohíbe.
2. **Ningún texto de aquí decide nada clínico.** La clase la fija
   `politica.decidir`; estos guiones solo la comunican. Por eso este módulo no
   importa `politica` ni conoce sus umbrales: recibe la clase y el criterio ya
   decididos, como cadenas.

Las señales se nombran igual que los campos de `politica.Observacion`. La
cobertura (una repregunta por cada señal del núcleo, un guion por cada clase) la
verifica `tests/test_plantillas.py` contra el propio módulo de política, para que
una señal nueva no pueda quedarse sin texto.
"""

from __future__ import annotations

__all__ = [
    "APERTURA",
    "LIMITE_CLINICO",
    "SIN_TRANSCRIPCION",
    "FALLO_TECNICO",
    "FALLO_DE_INFRAESTRUCTURA",
    "REPREGUNTAS",
    "REPREGUNTAS_INSISTENCIA",
    "CIERRES",
    "COLETILLAS_CRITERIO",
    "apertura",
    "repregunta",
    "cierre",
]

APERTURA = (
    "Buenos días. Le habla el seguimiento automatizado de su cirugía. "
    "Le voy a hacer unas preguntas cortas sobre cómo se ha sentido. "
    "Esto no reemplaza a su médico."
)

LIMITE_CLINICO = (
    "Le respondo con franqueza: soy un asistente automatizado de seguimiento y "
    "no puedo darle indicaciones médicas ni interpretar su caso. Dejo su "
    "pregunta anotada para el equipo que lo operó."
)
"""Respuesta a una pregunta clínica del paciente.

Es una declaración de límite, no una evasiva ni una respuesta improvisada. En
3.1 el agente no tiene con qué responder —el RAG llega en 3.2— y decirlo es la
única salida honesta: improvisar una respuesta clínica con el LLM sería la
misma falla que el diseño entero está construido para impedir.
"""

SIN_TRANSCRIPCION = "No alcancé a escucharlo."
"""Preámbulo cuando el turno llegó sin audio inteligible.

No se cuenta como respuesta: la señal sigue AUSENTE y la política vuelve a
repreguntar (y escala si se agota el presupuesto).
"""

FALLO_TECNICO = (
    "Tuve un problema técnico y no puedo continuar el seguimiento en este "
    "momento. Dejo el caso registrado para que lo revise una persona del equipo."
)
"""Salida cuando la política rechaza la entrada (§8.2) o algo se rompe.

No clasifica. Inventar una clase para no dejar la llamada sin desenlace sería
exactamente la falla que todo el diseño existe para impedir; decir que hubo un
fallo y escalar a una persona es la única salida que no miente.
"""

FALLO_DE_INFRAESTRUCTURA = (
    "Disculpe, estoy teniendo un problema técnico y no logro registrar sus "
    "respuestas, así que no puedo completar el seguimiento por este medio. "
    "Esto es un fallo mío, no algo que usted haya hecho, y no significa que "
    "esté bien ni que esté mal. Dejo el caso marcado para que una persona del "
    "equipo se comunique con usted hoy. Si mientras tanto tiene fiebre, dolor "
    "fuerte o cambios en la herida, comuníquese de una vez con su cirujano."
)
"""Cierre cuando el agente lleva N turnos seguidos sin poder procesar nada.

Tres cosas que este texto tiene que hacer a la vez, y por eso es largo:

1. **No clasificar.** La clase clínica sale de `politica.decidir` y aquí no hubo
   señales que decidir. Decir VERDE sería la falla catastrófica del dominio;
   decir ROJO sería el llamador clasificando por su cuenta, que es lo que el
   único `import politica` existe para impedir.
2. **No dejar al paciente creyendo que se le evaluó.** «Un paciente al que no se
   pudo evaluar no es un paciente sano»: por eso escala a una persona igual.
3. **Dar la salida de seguridad.** Si el agente no puede oírlo, lo mínimo es
   repetirle los tres motivos por los que debe llamar a su cirujano sin esperar.

Es deliberadamente distinto de `AGOTAMIENTO`, que significa «le pregunté y no
logré confirmar lo que me dijo». Aquí no se le llegó a preguntar de verdad.
"""

REPREGUNTAS: dict[str, str] = {
    "herida": (
        "¿Cómo ve la herida hoy? Dígame si la ve normal, con un enrojecimiento "
        "leve alrededor, o si le está saliendo pus."
    ),
    "movilidad": (
        "¿Cómo está para moverse? Dígame si se mueve normal, si le cuesta un "
        "poco pero puede, o si hay algo nuevo que no lo deja moverse."
    ),
    "fiebre_c": (
        "¿Se ha tomado la temperatura? Si se la tomó, dígame el número en grados."
    ),
    "dolor_nrs": (
        "De cero a diez, ¿cuánto dolor tiene en este momento? Cero es ningún "
        "dolor y diez es el peor dolor que se imagine."
    ),
    "apetito": (
        "¿Cómo ha estado el apetito? Dígame si come normal, si come un poco "
        "menos de lo habitual, o si casi no está comiendo."
    ),
    "sueno": (
        "¿Cómo ha dormido? Dígame si duerme normal, si duerme algo peor de lo "
        "habitual, o si prácticamente no está durmiendo."
    ),
}

REPREGUNTAS_INSISTENCIA: dict[str, str] = {
    "herida": "Sobre la herida, en una palabra: ¿normal, enrojecida, o con pus?",
    "movilidad": "Sobre moverse, en una palabra: ¿normal, le cuesta, o no puede?",
    "fiebre_c": "Sobre la temperatura: ¿qué número le marcó el termómetro?",
    "dolor_nrs": "Sobre el dolor: deme solo un número de cero a diez.",
    "apetito": "Sobre la comida: ¿come normal, come menos, o casi no come?",
    "sueno": "Sobre el sueño: ¿duerme normal, duerme mal, o no duerme?",
}
"""Segundo intento sobre la misma señal: más corto y con el dominio desnudo.

Repetir la misma frase a alguien que ya no la entendió es cómo se gastan los dos
intentos de `TOPE_POR_SENAL` sin obtener nada.
"""

CIERRES: dict[str, str] = {
    "VERDE": (
        "Por lo que me cuenta, su recuperación va dentro de lo esperado. "
        "Siga con las indicaciones que le dio su cirujano. Si aparece fiebre, "
        "dolor fuerte, o cambios en la herida, comuníquese con su equipo. "
        "Gracias por su tiempo."
    ),
    "AMARILLO": (
        "Por lo que me cuenta, hay cosas que conviene que revise su equipo "
        "quirúrgico. Comuníquese hoy con ellos para que lo valoren. Dejo "
        "registrado todo lo que me dijo."
    ),
    "ROJO": (
        "Por lo que me describe, usted necesita valoración médica ahora. "
        "Comuníquese de inmediato con su cirujano o acuda al servicio de "
        "urgencias más cercano. Dejo este contacto registrado para su equipo."
    ),
}
"""Guion de cierre por clase clínica. La clase la decide `politica.decidir`."""

COLETILLAS_CRITERIO: dict[str, str] = {
    "AGOTAMIENTO": (
        " No logré confirmar algunos datos en esta llamada, así que dejo el "
        "caso marcado para que lo revise una persona."
    ),
    "CIERRE_FORZADO": (
        " Con esto termino el seguimiento de hoy."
    ),
}
"""Añadido según POR QUÉ se cerró. S1/S2/S3 no llevan coletilla: son cierres
con evidencia suficiente y el guion de la clase ya dice todo lo que hay que decir.
"""


def apertura(senal: str) -> str:
    """Saludo + la primera repregunta que pidió la política."""
    return f"{APERTURA} {repregunta(senal, 0)}"


def repregunta(senal: str, intentos_previos: int = 0) -> str:
    """Texto para indagar `senal`. Falla ruidoso si la señal no tiene texto.

    Devolver una cadena genérica sería peor: el agente preguntaría algo que no
    corresponde a la señal que la política pidió, y la respuesta del paciente se
    anotaría en el campo equivocado.
    """
    if senal not in REPREGUNTAS:
        raise KeyError(f"sin plantilla de repregunta para la señal {senal!r}")
    if intentos_previos >= 1:
        return REPREGUNTAS_INSISTENCIA[senal]
    return REPREGUNTAS[senal]


def cierre(clase: str, criterio: str | None = None) -> str:
    """Guion de cierre para una clase, con la coletilla del criterio si aplica."""
    if clase not in CIERRES:
        raise KeyError(f"sin guion de cierre para la clase {clase!r}")
    return CIERRES[clase] + COLETILLAS_CRITERIO.get(criterio or "", "")
