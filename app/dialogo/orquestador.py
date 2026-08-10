"""El turno completo. Único punto del árbol que importa `politica`.

    audio -> STT -> transcripción
          -> EXTRACTOR (LLM #1) -> señales de dominio cerrado
          -> [si hubo pregunta del paciente] RAG: recuperar + responder (LLM #3)
          -> Observacion acumulada
          -> politica.decidir(obs, presupuesto)   <- ÚNICO punto de decisión
          -> REPREGUNTAR: plantilla [+ REDACTOR (LLM #2), opcional]
             CLASIFICAR:  guion de cierre por clase
          -> TTS local -> audio

El RAG entró en el sub-paso 3.2 y su sitio en este diagrama es la propiedad que
hay que mirar: está **fuera** del camino que produce la decisión. Responde la
pregunta del paciente y su texto se antepone como preámbulo a lo que la política
mandó decir. No escribe en `llamada.senales`, no entra en `Observacion` y no
puede llegar a `politica.decidir` por ninguna ruta. Lo verifica
`tests/test_rag_no_altera_clase.py` reejecutando la política sobre las mismas
señales con y sin RAG.

El orden no es negociable, y las tres propiedades que compra están sostenidas
por código de este archivo:

1. **La clase clínica nunca sale del LLM.** Sale de `politica.decidir`. Ninguna
   cosa que diga el paciente —ni una inyección de prompt— puede producir un
   «todo normal» cuando la política dice ROJO, porque la rama no la elige el
   modelo: la elige `decision.accion`. La separación dato/instrucción deja de
   ser una frase en el prompt y pasa a ser una propiedad de la topología.
2. **El extractor degrada a AUSENTE, nunca a un valor plausible.** Lo garantiza
   `app/llm/extractor.py`; aquí se respeta la otra mitad: una señal que llega
   `None` **no borra** lo que el paciente ya había dicho, y ninguna señal se
   infiere de otra.
3. **La plantilla es el piso, el LLM es el techo.** El redactor solo interviene
   sobre repreguntas, con timeout duro y caída a plantilla. Los guiones de
   cierre no pasan por él: comunican una clase clínica y no se retocan.

Contabilidad del presupuesto (HD7): el módulo de política LEE, el llamador
COBRA. Y se cobra **al emitir la pregunta**, no al recibir la respuesta.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import politica

from app.config import Config
from app.contratos import SalidaTTS, Servicios
from app.dialogo import plantillas
from app.dialogo.estado import Almacen, Llamada, ahora_iso
from app.llm import redactor
from app.llm.extractor import ContratoExtraccion, extraer
from app.rag import recuperacion, respuesta as respuesta_rag
from app.registro import anotar

_log = logging.getLogger(__name__)

__all__ = [
    "contrato_extraccion",
    "abrir_llamada",
    "procesar_turno",
    "cerrar_llamada",
    "senales_vacias",
    "TOPE_GLOBAL",
    "TOPE_POR_SENAL",
]

# Al importar el paquete queda registrado también el submódulo
# `politica.parametros` (el motor lo usa), así que se lee de ahí sin una segunda
# línea de importación —que además haría fallar la compuerta de arriba—. Los
# dominios y los topes se LEEN de la política; no se copian. Una copia aquí
# sería un segundo lugar donde vive un parámetro, que es justo lo que el §0 de
# la spec prohíbe.
TOPE_GLOBAL: int = politica.parametros.TOPE_GLOBAL
TOPE_POR_SENAL: int = politica.parametros.TOPE_POR_SENAL


def senales_vacias() -> dict[str, Any]:
    """Las seis señales del núcleo, todas AUSENTE."""
    return {senal: None for senal in politica.NUCLEO}


def contrato_extraccion(cfg: Config) -> ContratoExtraccion:
    """El dominio que el extractor puede producir, tomado de la política."""
    return ContratoExtraccion(
        dominios=politica.parametros.DOMINIOS_CATEGORICOS,
        senales=tuple(politica.NUCLEO),
        dolor_min=politica.parametros.DOLOR_NRS_MINIMO,
        dolor_max=politica.parametros.DOLOR_NRS_MAXIMO,
        fiebre_min_c=cfg.fiebre_min_c,
        fiebre_max_c=cfg.fiebre_max_c,
    )


# --------------------------------------------------------------------------- #
# Traducciones a JSON. La entrada y la salida de la política viajan enteras al
# registro: es lo que hace la decisión reejecutable.
# --------------------------------------------------------------------------- #
def _observacion(llamada: Llamada) -> politica.Observacion:
    return politica.Observacion(
        dia_postop=llamada.dia_postop,
        dolor_nrs=llamada.senales.get("dolor_nrs"),
        fiebre_c=llamada.senales.get("fiebre_c"),
        herida=llamada.senales.get("herida"),
        movilidad=llamada.senales.get("movilidad"),
        apetito=llamada.senales.get("apetito"),
        sueno=llamada.senales.get("sueno"),
    )


def _presupuesto(llamada: Llamada) -> politica.Presupuesto:
    return politica.Presupuesto(
        preguntas_por_senal=dict(llamada.preguntas_por_senal),
        preguntas_totales=llamada.preguntas_totales,
    )


def _observacion_a_json(obs: politica.Observacion) -> dict[str, Any]:
    return {
        "dia_postop": obs.dia_postop,
        "dolor_nrs": obs.dolor_nrs,
        "fiebre_c": obs.fiebre_c,
        "herida": obs.herida,
        "movilidad": obs.movilidad,
        "apetito": obs.apetito,
        "sueno": obs.sueno,
    }


def _presupuesto_a_json(presupuesto: politica.Presupuesto) -> dict[str, Any]:
    return {
        "preguntas_por_senal": dict(presupuesto.preguntas_por_senal),
        "preguntas_totales": presupuesto.preguntas_totales,
        "tope_por_senal": TOPE_POR_SENAL,
        "tope_global": TOPE_GLOBAL,
    }


def _decision_a_json(decision: politica.Decision) -> dict[str, Any]:
    return {
        "accion": decision.accion.name,
        "senal_a_indagar": decision.senal_a_indagar,
        "clase": decision.clase.name if decision.clase else None,
        "criterio": decision.criterio.name if decision.criterio else None,
        "regimen": decision.regimen.name,
        "n_total": decision.n_total,
        "banderas": {k: v.name for k, v in decision.banderas.items()},
        "compuerta": decision.compuerta.name,
        "disparadores": list(decision.disparadores),
        "marcas": list(decision.marcas),
    }


# --------------------------------------------------------------------------- #
# Apertura
# --------------------------------------------------------------------------- #
def abrir_llamada(
    cfg: Config,
    servicios: Servicios,
    almacen: Almacen,
    *,
    paciente_id: str | None = None,
    dia_postop: int | None = None,
) -> tuple[Llamada, dict[str, Any]]:
    """Crea la llamada y produce el audio de apertura.

    La apertura **ya es una decisión de la política**: con el vector vacío,
    `decidir` devuelve REPREGUNTAR sobre la primera señal de su orden de
    indagación, y esa es la pregunta que se emite tras el saludo. Elegir aquí
    por qué señal empezar sería una segunda política, escrita en otro sitio.
    """
    llamada = almacen.crear(
        senales_vacias(), paciente_id=paciente_id, dia_postop=dia_postop
    )
    inicio = time.perf_counter()

    obs = _observacion(llamada)
    presupuesto = _presupuesto(llamada)
    t_politica = time.perf_counter()
    decision = politica.decidir(obs, presupuesto)
    ms_politica = (time.perf_counter() - t_politica) * 1000

    if decision.accion is politica.Accion.REPREGUNTAR and decision.senal_a_indagar:
        senal = decision.senal_a_indagar
        texto = plantillas.apertura(senal)
        llamada.cobrar_pregunta(senal)
        llamada.senal_pendiente = senal
    else:
        # Inalcanzable con el vector vacío y presupuesto cero, pero si la
        # política cambiara de opinión, el agente la obedece en vez de imponer
        # su propio guion.
        texto = f"{plantillas.APERTURA} {_texto_de_cierre(decision)}"
        _aplicar_cierre(llamada, decision)

    audio = servicios.sintetizar(texto)
    ms_total = (time.perf_counter() - inicio) * 1000

    registro = {
        "tipo": "apertura",
        "ts": ahora_iso(),
        "llamada_id": llamada.id,
        "turno_idx": 0,
        "latencia_ms": {
            "cliente_fin_habla_a_audio": None,
            "servidor_total": round(ms_total, 1),
            "spans": {
                "stt": 0,
                "extraccion": 0,
                "politica": round(ms_politica, 3),
                "rag": 0,
                "redaccion": 0,
                "tts": round(audio.ms, 1),
            },
        },
        "llm": [],
        "rag": {"consultas": 0, "citas": []},
        "politica": {
            "entrada": _observacion_a_json(obs),
            "presupuesto": _presupuesto_a_json(presupuesto),
            "salida": _decision_a_json(decision),
        },
        "transcripcion": "",
        "respuesta": texto,
        "fuente_respuesta": redactor.FUENTE_PLANTILLA,
        "audio": {
            "segundos": round(audio.segundos, 2),
            "muestreo_hz": audio.muestreo_hz,
            "resultado": audio.resultado,
        },
    }
    anotar(cfg, registro)
    llamada.historial.append(
        {"turno_idx": 0, "transcripcion": "", "respuesta": texto, "rol": "apertura"}
    )

    return llamada, _payload(llamada, decision, texto, redactor.FUENTE_PLANTILLA, audio, registro)


# --------------------------------------------------------------------------- #
# Turno
# --------------------------------------------------------------------------- #
def procesar_turno(
    cfg: Config,
    servicios: Servicios,
    llamada: Llamada,
    audio_entrada: bytes,
    *,
    nombre_archivo: str = "turno.webm",
    segundos_audio: float | None = None,
) -> dict[str, Any]:
    """Un turno de punta a punta. El orden de las etapas es el del módulo."""
    inicio = time.perf_counter()
    llamada.turno_idx += 1
    registros_llm: list[dict[str, Any]] = []

    # --- 1. STT ------------------------------------------------------------ #
    stt = servicios.transcribir(audio_entrada, nombre_archivo)

    # --- 2. Extractor (LLM #1) --------------------------------------------- #
    extraccion = extraer(
        servicios.completar,
        contrato_extraccion(cfg),
        stt.texto,
        llamada.senal_pendiente,
        timeout_ms=cfg.extractor_timeout_ms,
    )
    if extraccion.salida.resultado != "no_invocado":
        registros_llm.append(extraccion.salida.a_registro("extractor"))

    # --- 3. Observación acumulada ------------------------------------------ #
    # Un valor nuevo pisa al anterior (el paciente puede corregirse); un AUSENTE
    # nunca borra lo ya dicho. Y ninguna señal se infiere de otra: lo que se
    # escribe aquí es exactamente lo que el extractor validó contra el dominio.
    for senal, valor in extraccion.senales.items():
        if valor is not None:
            llamada.senales[senal] = valor
    if extraccion.pregunta_del_paciente and stt.texto:
        llamada.preguntas_del_paciente.append(stt.texto)

    # --- 4. RAG: responder la pregunta del paciente, si la hubo ------------ #
    # Fuera del camino de la decisión, a propósito: lo que salga de aquí es texto
    # que se antepone a la respuesta, y no toca `llamada.senales` ni `obs`.
    texto_rag = ""
    bloque_rag: dict[str, Any] = {"consultas": 0, "citas": []}
    ms_rag = 0.0
    if extraccion.pregunta_del_paciente and stt.texto.strip():
        texto_rag, bloque_rag, ms_rag, registro_llm_rag = _responder_pregunta(
            cfg, servicios, stt.texto
        )
        if registro_llm_rag is not None:
            registros_llm.append(registro_llm_rag)

    # --- 5. Política: el único punto de decisión --------------------------- #
    obs = _observacion(llamada)
    presupuesto = _presupuesto(llamada)
    t_politica = time.perf_counter()
    try:
        decision: politica.Decision | None = politica.decidir(obs, presupuesto)
    except politica.ErrorDeInvocacion as exc:
        # §8.2: entrada imposible de un llamador correcto. Que llegue aquí
        # significa que el filtro de dominio del extractor tiene un hueco: es un
        # bug del agente, no un caso clínico. No se clasifica —inventar una
        # clase sería exactamente lo que este diseño existe para impedir— y la
        # llamada termina marcada para revisión humana.
        decision = None
        _log.error("politica.decidir rechazó la entrada: %s", exc)
    ms_politica = (time.perf_counter() - t_politica) * 1000

    # --- 6. Respuesta: plantilla (+ redactor) o guion de cierre ------------- #
    preambulo: list[str] = []
    if not stt.texto.strip():
        preambulo.append(plantillas.SIN_TRANSCRIPCION)
    if extraccion.pregunta_del_paciente:
        # Con RAG, la respuesta sale del corpus o declara su límite. Sin RAG
        # —índice no disponible, o `RAG_ACTIVO=0`— queda la declaración de rol de
        # 3.1, que sigue siendo cierta: el agente no da indicaciones médicas.
        preambulo.append(texto_rag or plantillas.LIMITE_CLINICO)

    ms_redaccion = 0.0
    fuente = redactor.FUENTE_PLANTILLA

    if decision is None:
        cuerpo = plantillas.FALLO_TECNICO
        llamada.abierta = False
        llamada.criterio = "ERROR_TECNICO"
    elif decision.accion is politica.Accion.REPREGUNTAR and decision.senal_a_indagar:
        senal = decision.senal_a_indagar
        base = plantillas.repregunta(senal, llamada.gastadas(senal))
        # Se cobra AL EMITIR: el turno que sigue verá el presupuesto ya gastado
        # aunque el paciente no conteste.
        llamada.cobrar_pregunta(senal)
        llamada.senal_pendiente = senal
        cuerpo, fuente, salida_redactor = redactor.redactar(
            servicios.completar,
            base,
            timeout_ms=cfg.redactor_timeout_ms,
            activo=cfg.redactor_activo,
        )
        ms_redaccion = salida_redactor.ms
        if salida_redactor.resultado != "no_invocado":
            registros_llm.append(salida_redactor.a_registro("redactor"))
    else:
        cuerpo = _texto_de_cierre(decision)
        _aplicar_cierre(llamada, decision)

    respuesta = " ".join([*preambulo, cuerpo]).strip()

    # --- 7. TTS local ------------------------------------------------------- #
    audio_salida = servicios.sintetizar(respuesta)
    ms_total = (time.perf_counter() - inicio) * 1000

    registro = {
        "tipo": "turno",
        "ts": ahora_iso(),
        "llamada_id": llamada.id,
        "turno_idx": llamada.turno_idx,
        "latencia_ms": {
            # Lo rellena el beacon del cliente: el número autoritativo lo mide
            # el navegador y solo existe después de que el audio suena.
            "cliente_fin_habla_a_audio": None,
            "servidor_total": round(ms_total, 1),
            "spans": {
                "stt": round(stt.ms, 1),
                "extraccion": round(extraccion.salida.ms, 1),
                "politica": round(ms_politica, 3),
                "rag": round(ms_rag, 1),
                "redaccion": round(ms_redaccion, 1),
                "tts": round(audio_salida.ms, 1),
            },
        },
        "llm": registros_llm,
        "rag": bloque_rag,
        "politica": {
            "entrada": _observacion_a_json(obs),
            "presupuesto": _presupuesto_a_json(presupuesto),
            "salida": _decision_a_json(decision) if decision else None,
        },
        "transcripcion": stt.texto,
        "respuesta": respuesta,
        "fuente_respuesta": fuente,
        "stt": {
            "resultado": stt.resultado,
            "segundos_audio": segundos_audio if segundos_audio is not None else stt.segundos_audio,
            "detalle": stt.detalle,
        },
        "extraccion": {
            "resultado": extraccion.resultado,
            "pregunta_del_paciente": extraccion.pregunta_del_paciente,
            "notas": list(extraccion.notas),
            # El fragmento de la transcripción que respalda cada señal anotada.
            # Es la auditoría del «por qué el agente escribió esto»: sin citas,
            # la única forma de revisar una extracción sería creerle al modelo.
            "citas": dict(extraccion.evidencias),
        },
        "audio": {
            "segundos": round(audio_salida.segundos, 2),
            "muestreo_hz": audio_salida.muestreo_hz,
            "resultado": audio_salida.resultado,
        },
    }
    anotar(cfg, registro)
    llamada.historial.append(
        {
            "turno_idx": llamada.turno_idx,
            "transcripcion": stt.texto,
            "respuesta": respuesta,
            "fuente_respuesta": fuente,
        }
    )

    return _payload(llamada, decision, respuesta, fuente, audio_salida, registro)


def _responder_pregunta(
    cfg: Config, servicios: Servicios, consulta: str
) -> tuple[str, dict[str, Any], float, dict[str, Any] | None]:
    """Recupera del corpus y redacta la respuesta. Devuelve el bloque `rag`.

    Tres salidas posibles, y las tres son honestas:

    * **Sin índice** (`consultar_rag is None`, o `RAG_ACTIVO=0`): no hay bloque
      que registrar y el llamador cae en la declaración de rol de 3.1.
    * **Índice sin nada por encima del umbral**: se declara el límite
      (`respuesta.SIN_FUENTE`) y el bloque queda con `suficiente: false` y el
      `mejor_score` que se rechazó. Ese número es lo que permite después
      distinguir «el umbral está mal puesto» de «el corpus no cubre el tema».
    * **Fragmentos suficientes**: los redacta el modelo, y sus citas —ruta,
      página, texto citado y score— viajan al registro.

    El presupuesto de preguntas de la política NO se toca aquí: responder una
    duda del paciente no consume ninguno de los `TOPE_GLOBAL` intentos de
    indagación, porque no es una indagación.
    """
    if not cfg.rag_activo or servicios.consultar_rag is None:
        return "", {"consultas": 0, "citas": []}, 0.0, None

    inicio = time.perf_counter()
    resultado = recuperacion.recuperar(
        servicios.consultar_rag, consulta, k=cfg.rag_k, umbral=cfg.rag_umbral
    )
    texto, fuente, salida = respuesta_rag.responder(
        servicios.completar,
        consulta,
        resultado.fragmentos,
        timeout_ms=cfg.rag_timeout_ms,
        max_tokens=cfg.rag_max_tokens,
    )
    bloque = resultado.a_registro(cfg.rag_max_texto_citado)
    bloque["fuente"] = fuente
    bloque["k"] = cfg.rag_k
    ms = (time.perf_counter() - inicio) * 1000
    registro_llm = salida.a_registro("rag") if salida.resultado != "no_invocado" else None
    return texto, bloque, ms, registro_llm


def _texto_de_cierre(decision: politica.Decision) -> str:
    clase = decision.clase.name if decision.clase else "AMARILLO"
    criterio = decision.criterio.name if decision.criterio else None
    return plantillas.cierre(clase, criterio)


def _aplicar_cierre(llamada: Llamada, decision: politica.Decision) -> None:
    llamada.abierta = False
    llamada.clase = decision.clase.name if decision.clase else None
    llamada.criterio = decision.criterio.name if decision.criterio else None
    llamada.marcas = tuple(decision.marcas)
    llamada.senal_pendiente = None


def _payload(
    llamada: Llamada,
    decision: politica.Decision | None,
    respuesta: str,
    fuente: str,
    audio: SalidaTTS,
    registro: dict[str, Any],
) -> dict[str, Any]:
    import base64

    return {
        "llamada_id": llamada.id,
        "turno_idx": llamada.turno_idx,
        "transcripcion": registro.get("transcripcion", ""),
        "respuesta": respuesta,
        "fuente_respuesta": fuente,
        "fin": not llamada.abierta,
        "clase": llamada.clase,
        "criterio": llamada.criterio,
        "senal_a_indagar": decision.senal_a_indagar if decision else None,
        "politica": registro["politica"]["salida"],
        "presupuesto": {
            "preguntas_por_senal": dict(llamada.preguntas_por_senal),
            "preguntas_totales": llamada.preguntas_totales,
            "tope_global": TOPE_GLOBAL,
            "tope_por_senal": TOPE_POR_SENAL,
        },
        "latencia_ms": registro["latencia_ms"],
        "audio_wav_b64": base64.b64encode(audio.wav).decode("ascii"),
        "audio": registro.get("audio", {}),
    }


# --------------------------------------------------------------------------- #
# Cierre
# --------------------------------------------------------------------------- #
def cerrar_llamada(
    cfg: Config, llamada: Llamada, almacen: Almacen, *, motivo: str = "solicitado"
) -> dict[str, Any]:
    """Anota la línea `cierre` con los totales y persiste la llamada.

    Idempotente: llamarlo dos veces no duplica la línea. La rúbrica pide el
    consumo por turno **y** por llamada, y los totales se calculan releyendo el
    registro, no acumulando en memoria, por la misma razón que `/metricas`.
    """
    from app.registro import leer

    llamada.abierta = False
    resumen = _totales_de_llamada(cfg, llamada.id, leer(cfg.ruta_turnos_jsonl))

    if not llamada.cierre_anotado:
        anotar(
            cfg,
            {
                "tipo": "cierre",
                "ts": ahora_iso(),
                "llamada_id": llamada.id,
                "paciente_id": llamada.paciente_id,
                "dia_postop": llamada.dia_postop,
                "motivo": motivo,
                "clase": llamada.clase,
                "criterio": llamada.criterio,
                "marcas": list(llamada.marcas),
                "senales": dict(llamada.senales),
                "presupuesto": {
                    "preguntas_por_senal": dict(llamada.preguntas_por_senal),
                    "preguntas_totales": llamada.preguntas_totales,
                    "tope_global": TOPE_GLOBAL,
                    "tope_por_senal": TOPE_POR_SENAL,
                },
                "totales": resumen,
            },
        )
        llamada.cierre_anotado = True

    destino = almacen.persistir(llamada, cfg.dir_llamadas)
    return {
        "llamada_id": llamada.id,
        "clase": llamada.clase,
        "criterio": llamada.criterio,
        "marcas": list(llamada.marcas),
        "senales": dict(llamada.senales),
        "presupuesto": {
            "preguntas_por_senal": dict(llamada.preguntas_por_senal),
            "preguntas_totales": llamada.preguntas_totales,
            "tope_global": TOPE_GLOBAL,
            "tope_por_senal": TOPE_POR_SENAL,
        },
        "totales": resumen,
        "historial": llamada.historial,
        "preguntas_del_paciente": llamada.preguntas_del_paciente,
        "persistida_en": str(destino) if destino else None,
    }


def _totales_de_llamada(cfg: Config, llamada_id: str, lineas: Any) -> dict[str, Any]:
    """Totales de una llamada, releídos del registro."""
    from app.registro import cargar_tarifas

    tarifas = cargar_tarifas(cfg)
    turnos = 0
    tokens_in = 0
    tokens_out = 0
    invocaciones: dict[str, int] = {}
    por_modelo: dict[str, dict[str, int]] = {}
    consultas_rag = 0
    citas_rag = 0
    latencias: list[float] = []

    for linea in lineas:
        if linea.get("llamada_id") != llamada_id:
            continue
        if linea.get("tipo") not in ("turno", "apertura"):
            continue
        if linea.get("tipo") == "turno":
            turnos += 1
        for llamado in linea.get("llm") or []:
            rol = str(llamado.get("rol", "?"))
            invocaciones[rol] = invocaciones.get(rol, 0) + 1
            modelo = str(llamado.get("modelo") or "(sin modelo)")
            acumulado = por_modelo.setdefault(modelo, {"in": 0, "out": 0})
            if isinstance(llamado.get("tokens_in"), int):
                tokens_in += llamado["tokens_in"]
                acumulado["in"] += llamado["tokens_in"]
            if isinstance(llamado.get("tokens_out"), int):
                tokens_out += llamado["tokens_out"]
                acumulado["out"] += llamado["tokens_out"]
        rag = linea.get("rag") or {}
        consultas_rag += int(rag.get("consultas") or 0)
        citas_rag += len(rag.get("citas") or [])
        valor = (linea.get("latencia_ms") or {}).get("cliente_fin_habla_a_audio")
        if isinstance(valor, (int, float)):
            latencias.append(float(valor))

    costo = 0.0
    sin_tarifa: list[str] = []
    for modelo, uso in por_modelo.items():
        tarifa = tarifas.get(modelo)
        if not tarifa:
            sin_tarifa.append(modelo)
            continue
        costo += uso["in"] / 1e6 * float(tarifa.get("entrada", 0.0))
        costo += uso["out"] / 1e6 * float(tarifa.get("salida", 0.0))

    from app.registro import percentil

    return {
        "turnos": turnos,
        "tokens_entrada": tokens_in,
        "tokens_salida": tokens_out,
        "invocaciones_llm": invocaciones,
        "por_modelo": por_modelo,
        "consultas_rag": consultas_rag,
        "citas_rag": citas_rag,
        "costo_usd": round(costo, 6) if not sin_tarifa else None,
        "costo_usd_parcial": round(costo, 6),
        "modelos_sin_tarifa": sorted(sin_tarifa),
        "latencia_cliente_ms": {
            "n": len(latencias),
            "p50": percentil(latencias, 50),
            "p95": percentil(latencias, 95),
        },
    }
