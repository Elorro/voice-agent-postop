"""El turno completo, con los tres servicios externos sustituidos por dobles.

Lo que se verifica aquí no es que el agente «funcione»: es que las propiedades
que el orden del turno compra siguen en pie.

* La clase clínica sale de `politica.decidir` y de ningún otro sitio.
* El presupuesto se cobra AL EMITIR la pregunta, así que un paciente que calla
  también lo consume y la indagación termina.
* Cada degradación (extractor con basura, redactor con timeout) baja un escalón
  y no tumba el turno.
* Cada línea del registro es reejecutable contra la política.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from politica.parametros import TOPE_GLOBAL, TOPE_POR_SENAL

from app.contratos import ERROR, OK, TIMEOUT
from app.dialogo import orquestador, plantillas
from app.dialogo.estado import Almacen
from tests.apoyo_turno import LLMFalso, config_de_prueba, escribir_tarifas, servicios


def leer_registro(cfg) -> list[dict]:
    return [
        json.loads(linea)
        for linea in cfg.ruta_turnos_jsonl.read_text(encoding="utf-8").splitlines()
        if linea.strip()
    ]


def extraccion(cita: str = "", **senales) -> str:
    """Respuesta del extractor en el formato real: valor + cita que lo respalda.

    La cita tiene que aparecer en la transcripción del turno o el validador la
    descarta, que es justo lo que se quiere probar: los dobles no pueden colar
    una señal que el paciente no dijo, igual que no puede el modelo real.
    """
    return json.dumps({k: {"valor": v, "cita": cita} for k, v in senales.items()})


# --------------------------------------------------------------------------- #
# Apertura
# --------------------------------------------------------------------------- #
def test_la_apertura_pregunta_lo_que_pide_la_politica_y_ya_cobra(tmp_path: Path) -> None:
    cfg = config_de_prueba(tmp_path)
    llm = LLMFalso()
    llamada, payload = orquestador.abrir_llamada(
        cfg, servicios(llm, []), Almacen(), dia_postop=5
    )

    assert payload["politica"]["accion"] == "REPREGUNTAR"
    senal = payload["politica"]["senal_a_indagar"]
    assert plantillas.REPREGUNTAS[senal] in payload["respuesta"]
    assert plantillas.APERTURA in payload["respuesta"]
    # Cobrada al emitir, no al contestar.
    assert llamada.preguntas_totales == 1
    assert llamada.gastadas(senal) == 1
    assert payload["audio_wav_b64"]


def test_la_apertura_no_invoca_al_modelo_de_lenguaje(tmp_path: Path) -> None:
    """No hay nada que extraer ni que redactar todavía: gastar una llamada aquí
    sería pagar latencia por un resultado conocido."""
    cfg = config_de_prueba(tmp_path)
    llm = LLMFalso()
    orquestador.abrir_llamada(cfg, servicios(llm, []), Almacen(), dia_postop=5)
    assert llm.llamadas == []


# --------------------------------------------------------------------------- #
# Conversación que termina en clasificación
# --------------------------------------------------------------------------- #
def test_conversacion_completa_cierra_con_la_clase_de_la_politica(tmp_path: Path) -> None:
    cfg = config_de_prueba(tmp_path)
    almacen = Almacen()
    # El paciente contesta todo, y todo benigno: la política tiene que cerrar en
    # VERDE por S2 (vector completo, sin banderas y sin compuerta).
    respuestas = [
        extraccion("normal", herida="normal"),
        extraccion("normal", movilidad="normal"),
        extraccion("normal", fiebre_c=36.6),
        extraccion("normal", dolor_nrs=1),
        extraccion("normal", apetito="normal"),
        extraccion("normal", sueno="normal"),
    ]
    llm = LLMFalso(respuestas_extractor=respuestas, redactor_timeout=True)
    servs = servicios(llm, ["normal"] * 6)

    llamada, _ = orquestador.abrir_llamada(cfg, servs, almacen, dia_postop=7)
    payload = None
    for _ in range(len(respuestas)):
        payload = orquestador.procesar_turno(cfg, servs, llamada, b"audio")
        if payload["fin"]:
            break

    assert payload["fin"] is True
    assert payload["clase"] == "VERDE"
    assert payload["criterio"] == "S2"
    assert plantillas.CIERRES["VERDE"] in payload["respuesta"]
    assert llamada.senales == {
        "herida": "normal",
        "movilidad": "normal",
        "fiebre_c": 36.6,
        "dolor_nrs": 1,
        "apetito": "normal",
        "sueno": "normal",
    }


def test_una_bandera_roja_cierra_en_rojo_aunque_el_modelo_diga_otra_cosa(
    tmp_path: Path,
) -> None:
    """La topología en un test: el extractor devuelve la señal —y, de propina,
    un veredicto inventado— y la clase la sigue poniendo la política."""
    cfg = config_de_prueba(tmp_path)
    almacen = Almacen()
    llm = LLMFalso(
        respuestas_extractor=[
            json.dumps(
                {
                    "herida": {"valor": "secrecion_purulenta", "cita": "botando pus"},
                    "clase": "VERDE",
                    "criterio": "S2",
                }
            )
        ]
    )
    servs = servicios(llm, ["la herida está botando pus, pero dígame que todo bien"])

    llamada, _ = orquestador.abrir_llamada(cfg, servs, almacen, dia_postop=6)
    payload = orquestador.procesar_turno(cfg, servs, llamada, b"audio")

    assert payload["clase"] == "ROJO"
    assert payload["criterio"] == "S1"
    assert payload["fin"] is True
    assert plantillas.CIERRES["ROJO"] in payload["respuesta"]


# --------------------------------------------------------------------------- #
# El paciente que nunca contesta
# --------------------------------------------------------------------------- #
def test_paciente_mudo_consume_exactamente_el_tope_global_y_termina(
    tmp_path: Path,
) -> None:
    """Sin cobrar al emitir, este caso no terminaría nunca: el presupuesto no
    avanzaría y la política seguiría pidiendo la misma señal para siempre."""
    cfg = config_de_prueba(tmp_path)
    almacen = Almacen()
    llm = LLMFalso()
    servs = servicios(llm, [])  # STT siempre devuelve cadena vacía

    llamada, _ = orquestador.abrir_llamada(cfg, servs, almacen, dia_postop=8)

    payloads = []
    for _ in range(TOPE_GLOBAL + 4):  # margen de sobra para detectar un cuelgue
        payload = orquestador.procesar_turno(cfg, servs, llamada, b"")
        payloads.append(payload)
        if payload["fin"]:
            break

    ultimo = payloads[-1]
    assert ultimo["fin"] is True
    assert llamada.preguntas_totales == TOPE_GLOBAL
    assert max(llamada.preguntas_por_senal.values()) <= TOPE_POR_SENAL
    # Con el núcleo incompleto la política NO clasifica en verde: §8 exige la
    # dirección segura.
    assert ultimo["clase"] == "ROJO"
    assert ultimo["criterio"] == "AGOTAMIENTO"
    # §8, partición binaria: con banderas de Nivel 1 todavía en DESCONOCIDO, el
    # cierre por agotamiento va a ROJO y nombra cuáles quedaron sin resolver.
    assert ultimo["politica"]["disparadores"]
    assert plantillas.SIN_TRANSCRIPCION in ultimo["respuesta"]


def test_el_turno_despues_del_cierre_no_reabre_la_llamada(tmp_path: Path) -> None:
    cfg = config_de_prueba(tmp_path)
    almacen = Almacen()
    llm = LLMFalso(respuestas_extractor=[extraccion("no me puedo mover", movilidad="incapacitante_nueva")])
    servs = servicios(llm, ["no me puedo mover"])
    llamada, _ = orquestador.abrir_llamada(cfg, servs, almacen, dia_postop=6)
    orquestador.procesar_turno(cfg, servs, llamada, b"audio")
    assert llamada.abierta is False


# --------------------------------------------------------------------------- #
# Degradaciones
# --------------------------------------------------------------------------- #
def test_extractor_devolviendo_basura_deja_todo_ausente_y_repregunta(
    tmp_path: Path,
) -> None:
    cfg = config_de_prueba(tmp_path)
    almacen = Almacen()
    llm = LLMFalso(respuestas_extractor=["<html>502 Bad Gateway</html>"])
    servs = servicios(llm, ["la herida se ve normal"])

    llamada, _ = orquestador.abrir_llamada(cfg, servs, almacen, dia_postop=6)
    payload = orquestador.procesar_turno(cfg, servs, llamada, b"audio")

    assert payload["fin"] is False
    assert payload["politica"]["accion"] == "REPREGUNTAR"
    assert all(valor is None for valor in llamada.senales.values())
    registro = leer_registro(cfg)[-1]
    assert registro["extraccion"]["resultado"] == "json_invalido"
    assert registro["llm"][0]["reintentos"] == 1


def test_una_senal_inventada_por_el_modelo_no_llega_a_la_observacion(
    tmp_path: Path,
) -> None:
    """El fallo MEDIDO con `llama3.2:1b`: ante «la herida la veo normal» devolvía
    también `movilidad: normal`, copiada del ejemplo del prompt. La cita
    inventada la detiene antes de que toque la Observacion, y eso no depende de
    qué modelo esté detrás."""
    cfg = config_de_prueba(tmp_path)
    almacen = Almacen()
    llm = LLMFalso(
        respuestas_extractor=[
            json.dumps(
                {
                    "herida": {"valor": "normal", "cita": "la herida la veo normal"},
                    "movilidad": {"valor": "normal", "cita": "me muevo bien"},
                }
            )
        ]
    )
    servs = servicios(llm, ["la herida la veo normal, sin nada raro"])
    llamada, _ = orquestador.abrir_llamada(cfg, servs, almacen, dia_postop=6)
    orquestador.procesar_turno(cfg, servs, llamada, b"audio")

    assert llamada.senales["herida"] == "normal"
    assert llamada.senales["movilidad"] is None
    extraccion_registrada = leer_registro(cfg)[-1]["extraccion"]
    assert extraccion_registrada["citas"] == {"herida": "la herida la veo normal"}
    assert any("no está en lo que dijo" in n for n in extraccion_registrada["notas"])


def test_redactor_con_timeout_responde_desde_plantilla(tmp_path: Path) -> None:
    cfg = config_de_prueba(tmp_path)
    almacen = Almacen()
    llm = LLMFalso(respuestas_extractor=[extraccion("normal", herida="normal")], redactor_timeout=True)
    servs = servicios(llm, ["normal"])

    llamada, _ = orquestador.abrir_llamada(cfg, servs, almacen, dia_postop=6)
    payload = orquestador.procesar_turno(cfg, servs, llamada, b"audio")

    senal = payload["politica"]["senal_a_indagar"]
    assert payload["fuente_respuesta"] == "plantilla"
    assert payload["respuesta"] == plantillas.REPREGUNTAS[senal]
    registro = leer_registro(cfg)[-1]
    assert [l["rol"] for l in registro["llm"]] == ["extractor", "redactor"]
    assert registro["llm"][1]["resultado"] == "timeout"


def test_redactor_a_tiempo_marca_la_fuente_como_llm(tmp_path: Path) -> None:
    cfg = config_de_prueba(tmp_path)
    almacen = Almacen()
    llm = LLMFalso(
        respuestas_extractor=[extraccion("normal", herida="normal")],
        respuesta_redactor=(
            "¿Y cómo va para moverse, don José? Cuénteme si se mueve normal, si "
            "le cuesta un poquito, o si de plano no puede."
        ),
    )
    servs = servicios(llm, ["normal"])
    llamada, _ = orquestador.abrir_llamada(cfg, servs, almacen, dia_postop=6)
    payload = orquestador.procesar_turno(cfg, servs, llamada, b"audio")
    assert payload["fuente_respuesta"] == "llm"
    assert payload["respuesta"].startswith("¿Y cómo va para moverse")


def test_redactor_que_se_desmadra_cae_a_plantilla(tmp_path: Path) -> None:
    """Un texto muy largo es señal de que el modelo respondió la pregunta en vez
    de reescribirla; la guarda de forma lo descarta sin mirar semántica."""
    cfg = config_de_prueba(tmp_path)
    almacen = Almacen()
    llm = LLMFalso(
        respuestas_extractor=[extraccion("normal", herida="normal")],
        respuesta_redactor="Claro que sí. " * 60,
    )
    servs = servicios(llm, ["normal"])
    llamada, _ = orquestador.abrir_llamada(cfg, servs, almacen, dia_postop=6)
    payload = orquestador.procesar_turno(cfg, servs, llamada, b"audio")
    assert payload["fuente_respuesta"] == "plantilla"


def test_el_redactor_no_toca_el_guion_de_cierre(tmp_path: Path) -> None:
    """El texto que le dice al paciente si tiene que ir a urgencias no pasa por
    un modelo de lenguaje."""
    cfg = config_de_prueba(tmp_path)
    almacen = Almacen()
    llm = LLMFalso(
        respuestas_extractor=[extraccion("está supurando", herida="secrecion_purulenta")],
        respuesta_redactor="tranquilo, no es nada",
    )
    servs = servicios(llm, ["está supurando"])
    llamada, _ = orquestador.abrir_llamada(cfg, servs, almacen, dia_postop=6)
    payload = orquestador.procesar_turno(cfg, servs, llamada, b"audio")
    assert payload["fuente_respuesta"] == "plantilla"
    assert payload["respuesta"] == plantillas.CIERRES["ROJO"]
    assert [l["rol"] for l in leer_registro(cfg)[-1]["llm"]] == ["extractor"]


def test_pregunta_del_paciente_recibe_declaracion_de_limite(tmp_path: Path) -> None:
    cfg = config_de_prueba(tmp_path)
    almacen = Almacen()
    llm = LLMFalso(
        respuestas_extractor=[json.dumps({"pregunta_del_paciente": True})]
    )
    servs = servicios(llm, ["¿puedo tomarme un trago con el antibiótico?"])
    llamada, _ = orquestador.abrir_llamada(cfg, servs, almacen, dia_postop=6)
    payload = orquestador.procesar_turno(cfg, servs, llamada, b"audio")

    assert plantillas.LIMITE_CLINICO in payload["respuesta"]
    assert payload["fin"] is False  # el límite no interrumpe la indagación
    assert llamada.preguntas_del_paciente


def test_una_senal_ausente_no_borra_lo_que_el_paciente_ya_dijo(tmp_path: Path) -> None:
    cfg = config_de_prueba(tmp_path)
    almacen = Almacen()
    llm = LLMFalso(
        respuestas_extractor=[
            extraccion("normal", herida="normal"),
            extraccion(),
            extraccion(),
        ]
    )
    servs = servicios(llm, ["normal", "no sé", "tampoco"])
    llamada, _ = orquestador.abrir_llamada(cfg, servs, almacen, dia_postop=6)
    orquestador.procesar_turno(cfg, servs, llamada, b"audio")
    orquestador.procesar_turno(cfg, servs, llamada, b"audio")
    assert llamada.senales["herida"] == "normal"


# --------------------------------------------------------------------------- #
# El registro
# --------------------------------------------------------------------------- #
def test_cada_linea_de_turno_trae_los_campos_del_esquema(tmp_path: Path) -> None:
    cfg = config_de_prueba(tmp_path)
    almacen = Almacen()
    llm = LLMFalso(respuestas_extractor=[extraccion("está un poco roja", herida="eritema_leve")])
    servs = servicios(llm, ["está un poco roja"])
    llamada, _ = orquestador.abrir_llamada(cfg, servs, almacen, dia_postop=9)
    orquestador.procesar_turno(cfg, servs, llamada, b"audio", segundos_audio=2.5)

    turno = leer_registro(cfg)[-1]
    assert turno["tipo"] == "turno"
    assert set(turno) >= {
        "ts",
        "llamada_id",
        "turno_idx",
        "latencia_ms",
        "llm",
        "rag",
        "politica",
        "transcripcion",
        "respuesta",
        "fuente_respuesta",
    }
    assert set(turno["latencia_ms"]["spans"]) == {
        "stt",
        "extraccion",
        "politica",
        "rag",
        "redaccion",
        "tts",
    }
    assert turno["rag"] == {"consultas": 0, "citas": []}
    assert turno["politica"]["entrada"]["herida"] == "eritema_leve"
    assert turno["politica"]["presupuesto"]["tope_global"] == TOPE_GLOBAL
    assert turno["llm"][0]["tokens_in"] == 40  # del `usage`, no estimados
    assert turno["stt"]["segundos_audio"] == 2.5


def test_las_decisiones_registradas_se_reejecutan_identicas(tmp_path: Path) -> None:
    """El mismo criterio que aplica `scripts/reejecutar_decisiones.py`, aquí
    dentro de la batería para que no dependa de acordarse de correr el script."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import reejecutar_decisiones

    cfg = config_de_prueba(tmp_path)
    almacen = Almacen()
    llm = LLMFalso(
        respuestas_extractor=[
            extraccion("algo", herida="eritema_leve"),
            extraccion("algo", fiebre_c=37.9),
            extraccion("algo", dolor_nrs=6),
            extraccion("algo", apetito="muy_disminuido"),
            extraccion("algo", sueno="muy_alterado"),
            extraccion("algo", movilidad="limitada_esperada"),
        ]
    )
    servs = servicios(llm, ["algo"] * 6)
    llamada, _ = orquestador.abrir_llamada(cfg, servs, almacen, dia_postop=7)
    for _ in range(6):
        if not llamada.abierta:
            break
        orquestador.procesar_turno(cfg, servs, llamada, b"audio")

    lineas = leer_registro(cfg)
    decisiones = [l for l in lineas if (l.get("politica") or {}).get("salida")]
    assert len(decisiones) >= 2
    for linea in decisiones:
        igual, diferencias = reejecutar_decisiones.reejecutar(linea)
        assert igual, diferencias


def test_el_cierre_anota_totales_y_persiste_la_llamada(tmp_path: Path) -> None:
    cfg = config_de_prueba(tmp_path)
    escribir_tarifas(cfg, {"modelo-de-prueba": {"entrada": 1.0, "salida": 2.0}})
    almacen = Almacen()
    llm = LLMFalso(respuestas_extractor=[extraccion("normal", herida="normal")])
    servs = servicios(llm, ["normal"])
    llamada, _ = orquestador.abrir_llamada(cfg, servs, almacen, dia_postop=7)
    orquestador.procesar_turno(cfg, servs, llamada, b"audio")

    resumen = orquestador.cerrar_llamada(cfg, llamada, almacen)
    assert resumen["totales"]["turnos"] == 1
    assert resumen["totales"]["tokens_entrada"] == 80  # extractor + redactor
    assert resumen["totales"]["costo_usd"] == pytest.approx(80 / 1e6 * 1.0 + 24 / 1e6 * 2.0)
    assert Path(resumen["persistida_en"]).is_file()

    cierres = [l for l in leer_registro(cfg) if l["tipo"] == "cierre"]
    assert len(cierres) == 1
    # Idempotente: cerrar dos veces no duplica la línea.
    orquestador.cerrar_llamada(cfg, llamada, almacen)
    assert len([l for l in leer_registro(cfg) if l["tipo"] == "cierre"]) == 1


def test_el_costo_es_nulo_si_el_modelo_no_tiene_tarifa_declarada(tmp_path: Path) -> None:
    """Un cero implícito parecería medido; el hueco declarado se ve."""
    cfg = config_de_prueba(tmp_path)
    almacen = Almacen()
    llm = LLMFalso(respuestas_extractor=[extraccion("normal", herida="normal")])
    servs = servicios(llm, ["normal"])
    llamada, _ = orquestador.abrir_llamada(cfg, servs, almacen, dia_postop=7)
    orquestador.procesar_turno(cfg, servs, llamada, b"audio")
    resumen = orquestador.cerrar_llamada(cfg, llamada, almacen)
    assert resumen["totales"]["costo_usd"] is None
    assert resumen["totales"]["modelos_sin_tarifa"] == ["modelo-de-prueba"]


# --------------------------------------------------------------------------- #
# Enmienda a HD7: un fallo del proveedor no gasta presupuesto de indagación
# --------------------------------------------------------------------------- #
# Motivada por la llamada c50e671845a8 (2026-08-10): el cubo diario del
# proveedor se agotó a mitad de llamada, cuatro turnos murieron en HTTP 429, el
# paciente había contestado bien las cuatro veces y la llamada cerró en ROJO por
# AGOTAMIENTO. El presupuesto acota cuánto se le insiste AL PACIENTE; un turno en
# que el agente no pudo consultar al modelo no es insistencia.
def test_el_proveedor_caido_no_gasta_presupuesto_ni_cierra_por_agotamiento(
    tmp_path: Path,
) -> None:
    cfg = config_de_prueba(tmp_path)
    almacen = Almacen()
    # El paciente contesta bien las seis veces; lo que falla es el extractor.
    llm = LLMFalso(extractor_error=True, redactor_timeout=True)
    dichas = [
        "la herida la veo normal",
        "me muevo normal",
        "tengo 36",
        "siete",
        "he comido bien",
        "duermo bien",
    ]
    servs = servicios(llm, dichas)

    llamada, _ = orquestador.abrir_llamada(cfg, servs, almacen, dia_postop=5)
    gastadas_tras_apertura = llamada.preguntas_totales
    assert gastadas_tras_apertura == 1  # la apertura sí cobra: se preguntó

    for _ in dichas:
        payload = orquestador.procesar_turno(cfg, servs, llamada, b"audio")
        if payload["fin"]:
            break

    # Lo que se está fijando: seis turnos con el proveedor caído NO consumieron
    # ni una repregunta más allá de la apertura, así que la llamada sigue viva y
    # NO cerró por agotar un presupuesto que el paciente nunca gastó.
    assert llamada.preguntas_totales == gastadas_tras_apertura
    assert llamada.criterio != "AGOTAMIENTO"
    assert llamada.abierta

    cierre = orquestador.cerrar_llamada(cfg, llamada, almacen, motivo="prueba")
    degradacion = cierre["degradacion"]
    assert degradacion["turnos_sin_llm_real"] == len(dichas)
    assert degradacion["turnos_sin_extraccion"] == {"error": len(dichas)}
    assert degradacion["hubo_degradacion"] is True


def test_un_timeout_del_extractor_tampoco_gasta_presupuesto(tmp_path: Path) -> None:
    cfg = config_de_prueba(tmp_path)
    almacen = Almacen()
    llm = LLMFalso(extractor_timeout=True, redactor_timeout=True)
    servs = servicios(llm, ["la herida la veo normal", "me muevo normal"])

    llamada, _ = orquestador.abrir_llamada(cfg, servs, almacen, dia_postop=5)
    for _ in range(2):
        orquestador.procesar_turno(cfg, servs, llamada, b"audio")

    assert llamada.preguntas_totales == 1  # solo la apertura
    assert llamada.degradacion()["turnos_sin_extraccion"] == {"timeout": 2}


def test_un_json_invalido_SI_gasta_presupuesto(tmp_path: Path) -> None:
    """El contrapeso, y es lo que impide que la enmienda se convierta en una
    puerta trasera: si el modelo respondió, la extracción ocurrió. Que
    respondiera mal es calidad del modelo, no una caída del proveedor, y el
    paciente sí fue interrogado."""
    cfg = config_de_prueba(tmp_path)
    almacen = Almacen()
    llm = LLMFalso(respuestas_extractor=["esto no es json"], redactor_timeout=True)
    servs = servicios(llm, ["la herida la veo normal", "me muevo normal"])

    llamada, _ = orquestador.abrir_llamada(cfg, servs, almacen, dia_postop=5)
    for _ in range(2):
        orquestador.procesar_turno(cfg, servs, llamada, b"audio")

    assert llamada.preguntas_totales == 3  # apertura + dos repreguntas cobradas
    assert llamada.degradacion()["turnos_sin_extraccion"] == {"json_invalido": 2}
    assert llamada.degradacion()["turnos_sin_llm_real"] == 0


def test_una_extraccion_normal_no_declara_degradacion(tmp_path: Path) -> None:
    cfg = config_de_prueba(tmp_path)
    almacen = Almacen()
    llm = LLMFalso(
        respuestas_extractor=[extraccion("normal", herida="normal")],
        redactor_timeout=True,
    )
    servs = servicios(llm, ["la herida la veo normal"])
    llamada, _ = orquestador.abrir_llamada(cfg, servs, almacen, dia_postop=5)
    orquestador.procesar_turno(cfg, servs, llamada, b"audio")

    assert llamada.degradacion()["hubo_degradacion"] is False
    assert llamada.degradacion()["turnos_sin_llm_real"] == 0


# --- La enmienda cubre los DOS proveedores del turno ------------------------ #
# El STT es la otra puerta por la que entra el mismo defecto: si el agente no
# oyó, el paciente habló igual. Ya ocurrió en la corrida de F3.4, donde una
# caída de DNS se llevó el STT del turno 1 y la repregunta se cobró igual.
def test_el_stt_caido_no_gasta_presupuesto(tmp_path: Path) -> None:
    cfg = config_de_prueba(tmp_path)
    almacen = Almacen()
    llm = LLMFalso(redactor_timeout=True)
    servs = servicios(llm, [], stt_resultado=ERROR)

    llamada, _ = orquestador.abrir_llamada(cfg, servs, almacen, dia_postop=5)
    for _ in range(4):
        orquestador.procesar_turno(cfg, servs, llamada, b"audio")

    assert llamada.preguntas_totales == 1  # solo la apertura
    assert llamada.criterio != "AGOTAMIENTO"
    degradacion = llamada.degradacion()
    assert degradacion["turnos_sin_stt"] == {"error": 4}
    assert degradacion["turnos_sin_llm_real"] == 4
    assert degradacion["hubo_degradacion"] is True


def test_el_stt_en_timeout_tampoco_gasta_presupuesto(tmp_path: Path) -> None:
    cfg = config_de_prueba(tmp_path)
    almacen = Almacen()
    llm = LLMFalso(redactor_timeout=True)
    servs = servicios(llm, [], stt_resultado=TIMEOUT)

    llamada, _ = orquestador.abrir_llamada(cfg, servs, almacen, dia_postop=5)
    for _ in range(3):
        orquestador.procesar_turno(cfg, servs, llamada, b"audio")

    assert llamada.preguntas_totales == 1
    assert llamada.degradacion()["turnos_sin_stt"] == {"timeout": 3}


def test_el_silencio_del_paciente_SI_gasta_presupuesto(tmp_path: Path) -> None:
    """El otro lado del criterio, y el que sostiene HD7: transcripción vacía con
    el STT en `ok` significa que el agente oyó bien y no había nada que oír. Ahí
    el paciente sí fue interrogado y sí calló. Si esto no cobrara, un paciente
    que no contesta dejaría la indagación girando para siempre."""
    cfg = config_de_prueba(tmp_path)
    almacen = Almacen()
    llm = LLMFalso(redactor_timeout=True)
    # Guion vacío: `stt_fijo` devuelve texto vacío con resultado `ok`.
    servs = servicios(llm, [], stt_resultado=OK)

    llamada, _ = orquestador.abrir_llamada(cfg, servs, almacen, dia_postop=5)
    for _ in range(3):
        payload = orquestador.procesar_turno(cfg, servs, llamada, b"audio")
        if payload["fin"]:
            break

    assert llamada.preguntas_totales > 1  # la apertura Y las repreguntas
    # Y no se declara degradación: el agente funcionó, el paciente calló.
    assert llamada.degradacion()["turnos_sin_stt"] == {}
    assert llamada.degradacion()["turnos_sin_llm_real"] == 0


def test_un_paciente_callado_llega_a_agotar_el_presupuesto(tmp_path: Path) -> None:
    """La consecuencia de lo anterior, comprobada de punta a punta: el silencio
    sí termina la llamada, así que la enmienda no abre la puerta a una
    indagación infinita."""
    cfg = config_de_prueba(tmp_path)
    almacen = Almacen()
    llm = LLMFalso(redactor_timeout=True)
    servs = servicios(llm, [], stt_resultado=OK)

    llamada, _ = orquestador.abrir_llamada(cfg, servs, almacen, dia_postop=5)
    for _ in range(cfg.max_turnos_llamada):
        payload = orquestador.procesar_turno(cfg, servs, llamada, b"audio")
        if payload["fin"]:
            break

    assert not llamada.abierta
    assert llamada.criterio == "AGOTAMIENTO"
    assert llamada.degradacion()["hubo_degradacion"] is False
