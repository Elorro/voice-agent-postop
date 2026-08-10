"""El registro JSONL de turnos: escritura, relectura y métricas.

Una línea por turno en `datos/logs/turnos.jsonl`, más una línea `cierre` por
llamada. Este archivo es **la** fuente: `/metricas` no acumula nada en memoria,
vuelve a leer el mismo archivo que el jurado puede abrir con su editor. Un
acumulador en proceso sería más rápido y permitiría que el número mostrado y el
registro discreparan sin que nadie pudiera notarlo desde fuera.

Dos consecuencias de diseño que conviene tener a la vista:

* **La entrada y la salida de la política viajan en cada línea.** Eso es lo que
  hace la decisión reejecutable: `scripts/reejecutar_decisiones.py` recorre el
  registro, vuelve a llamar a `politica.decidir` con la entrada anotada y exige
  igualdad con la salida anotada. «El agente decidió bien» deja de ser una
  afirmación y pasa a ser una verificación.
* **Los tokens se leen del campo `usage` del proveedor.** Nunca se estiman. Si
  el proveedor no lo manda, el campo queda en `null` y se ve que falta.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Iterator, Mapping

from app.config import Config

__all__ = [
    "anotar",
    "leer",
    "parchear_latencia_cliente",
    "calcular_metricas",
    "percentil",
    "cargar_tarifas",
    "costo_de_uso",
]

# Un solo worker (ver docker/entrypoint.sh), pero uvicorn atiende peticiones en
# un pool de hilos: dos escrituras simultáneas podrían entrelazar líneas.
_candado = threading.Lock()


def _abrir_para_anexar(ruta: Path):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    return ruta.open("a", encoding="utf-8")


def anotar(cfg: Config, registro: dict[str, Any]) -> None:
    """Anexa un registro como una línea JSON. Nunca lanza hacia el turno.

    Perder el log es malo; tumbar la llamada del paciente por no poder escribir
    el log es peor. El fallo se reporta por el log de la aplicación.
    """
    linea = json.dumps(registro, ensure_ascii=False, separators=(",", ":"))
    try:
        with _candado, _abrir_para_anexar(cfg.ruta_turnos_jsonl) as fh:
            fh.write(linea + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as exc:  # noqa: BLE001 - se reporta, no propaga
        import logging

        logging.getLogger(__name__).error(
            "no se pudo anotar en %s: %s", cfg.ruta_turnos_jsonl, exc
        )


def leer(ruta: Path) -> Iterator[dict[str, Any]]:
    """Recorre el registro saltando líneas ilegibles.

    Una línea rota (un proceso muerto a mitad de escritura) no puede impedir
    leer las 300 anteriores.
    """
    if not ruta.is_file():
        return
    with ruta.open("r", encoding="utf-8") as fh:
        for linea in fh:
            linea = linea.strip()
            if not linea:
                continue
            try:
                registro = json.loads(linea)
            except json.JSONDecodeError:
                continue
            if isinstance(registro, dict):
                yield registro


ORIGEN_NAVEGADOR = "navegador"
"""Medición completa: t0 en el fin de habla del VAD, t1 con el audio sonando.

Es la única población que entra en el P50/P95 que se reporta.
"""

ORIGEN_HEADLESS = "cliente_headless"
"""Medición de un cliente sin reproducción de audio (`scripts/llamada_de_prueba.py`).

Su t1 es «audio recibido», no «primer sample sonando»: le falta la
decodificación y el arranque de la reproducción, así que es una COTA INFERIOR
del número de la rúbrica y no es comparable con el del navegador. Se registra
aparte por eso, y `/metricas` no la mezcla: promediar las dos poblaciones daría
un número que parece medido y no lo está.
"""


def parchear_latencia_cliente(
    cfg: Config,
    llamada_id: str,
    turno_idx: int,
    ms: float,
    origen: str = ORIGEN_NAVEGADOR,
) -> bool:
    """Rellena `latencia_ms.cliente_fin_habla_a_audio` de un turno ya anotado.

    Por qué hay que reescribir una línea en vez de anexar otra: el número
    autoritativo lo mide el navegador y solo existe **después** de que el audio
    suena, es decir después de que el servidor ya respondió y anotó el turno.
    Las dos alternativas eran peores:

    * Anexar una línea `telemetria` aparte y unirla al leer: el registro deja de
      tener una línea completa por turno, que es justo lo que lo hace auditable
      a ojo.
    * Retener el turno en memoria hasta que llegue la telemetría: un fallo del
      proceso se lleva turnos que ya ocurrieron, y la telemetría puede no llegar
      nunca (pestaña cerrada).

    El costo es reescribir el archivo entero por cada medición. Con el orden de
    magnitud de una demostración (decenas de líneas) es irrelevante, y la
    publicación es atómica (`os.replace`), así que un corte no deja el registro
    a medias.
    """
    ruta = cfg.ruta_turnos_jsonl
    with _candado:
        if not ruta.is_file():
            return False
        lineas = ruta.read_text(encoding="utf-8").splitlines()
        tocado = False
        for i, linea in enumerate(lineas):
            if not linea.strip():
                continue
            try:
                registro = json.loads(linea)
            except json.JSONDecodeError:
                continue
            if (
                # También la apertura: tiene su propia latencia medida en el
                # navegador, aunque `/metricas` solo promedie los turnos (en la
                # apertura no hay «fin de habla del paciente» que cronometrar).
                registro.get("tipo") in ("turno", "apertura")
                and registro.get("llamada_id") == llamada_id
                and registro.get("turno_idx") == turno_idx
            ):
                registro.setdefault("latencia_ms", {})
                registro["latencia_ms"]["cliente_fin_habla_a_audio"] = round(ms, 1)
                registro["latencia_ms"]["cliente_origen"] = origen
                lineas[i] = json.dumps(
                    registro, ensure_ascii=False, separators=(",", ":")
                )
                tocado = True
        if not tocado:
            return False
        temporal = ruta.with_suffix(ruta.suffix + ".tmp")
        temporal.write_text("\n".join(lineas) + "\n", encoding="utf-8")
        os.replace(temporal, ruta)
        return True


# --------------------------------------------------------------------------- #
# Métricas — se calculan LEYENDO el archivo, nunca desde memoria.
# --------------------------------------------------------------------------- #


def percentil(valores: list[float], p: float) -> float | None:
    """Percentil por interpolación lineal entre los dos vecinos del rango.

    Es el método declarado en la respuesta de `/metricas`, y el mismo que usan
    `numpy.percentile` y `statistics.quantiles(method="inclusive")` por defecto.
    Se implementa a mano por una razón: con 4 muestras cualquier definición da
    un número distinto, y quien lea el P95 tiene que poder reproducirlo sin
    adivinar qué convención se usó.
    """
    if not valores:
        return None
    orden = sorted(valores)
    if len(orden) == 1:
        return round(float(orden[0]), 1)
    posicion = (len(orden) - 1) * (p / 100.0)
    bajo = int(posicion)
    alto = min(bajo + 1, len(orden) - 1)
    peso = posicion - bajo
    return round(float(orden[bajo] * (1 - peso) + orden[alto] * peso), 1)


def _resumen(valores: list[float]) -> dict[str, Any]:
    return {
        "n": len(valores),
        "p50": percentil(valores, 50),
        "p95": percentil(valores, 95),
        "min": round(min(valores), 1) if valores else None,
        "max": round(max(valores), 1) if valores else None,
    }


def costo_de_uso(uso: Mapping[str, int], tarifa: Mapping[str, Any]) -> float:
    """USD de un `{in, out, razonamiento}` contra una entrada de la tabla.

    **Los tokens de razonamiento se facturan como salida.** No es una decisión
    nuestra: la tabla de precios de Google titula esa columna «Precio de salida
    (incluidos los tokens de pensamiento)». El proveedor no los mete en
    `completion_tokens`, así que cobrarlos exige sumarlos aquí a mano.

    Es el mismo error de contabilidad que F3.3 corrigió un nivel más abajo —allí
    `tokens_out` reportaba menos tokens de los generados; aquí el costo cobraría
    menos dinero del facturado—. Con la llamada medida el 2026-08-10 (433 de
    salida y 338 de razonamiento) ignorarlos subestima el costo de salida un
    **44 %**.

    Vive aquí, y no en cada sitio que calcula costos, porque hay dos —el cierre
    por llamada y `/metricas`— y una regla de facturación duplicada es una regla
    que acaba divergiendo.
    """
    salida_facturable = int(uso.get("out", 0)) + int(uso.get("razonamiento", 0))
    return (
        int(uso.get("in", 0)) / 1e6 * float(tarifa.get("entrada", 0.0))
        + salida_facturable / 1e6 * float(tarifa.get("salida", 0.0))
    )


def cargar_tarifas(cfg: Config) -> dict[str, Any]:
    """Lee la tabla de tarifas. Ausente o ilegible => sin tarifas, no cero."""
    try:
        datos = json.loads(cfg.ruta_tarifas.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    modelos = datos.get("modelos")
    return modelos if isinstance(modelos, dict) else {}


def calcular_metricas(cfg: Config) -> dict[str, Any]:
    """P50/P95 y consumo, releyendo `turnos.jsonl`.

    El número que manda es el del cliente (`cliente_fin_habla_a_audio`): mide lo
    que la rúbrica pide, desde que el paciente calla hasta que suena el audio.
    Los spans del servidor van al lado como DESGLOSE, subordinados a él, porque
    el servidor no ve la subida, ni la decodificación, ni el arranque de la
    reproducción, y un P50 medido ahí subestima el número por construcción.
    """
    tarifas = cargar_tarifas(cfg)

    cliente: list[float] = []
    otras_fuentes: dict[str, list[float]] = {}
    servidor: list[float] = []
    spans: dict[str, list[float]] = {}
    turnos_sin_telemetria = 0
    n_turnos = 0
    llamadas: set[str] = set()
    llamadas_cerradas: set[str] = set()

    tokens_in = 0
    tokens_out = 0
    tokens_razonamiento = 0
    invocaciones: dict[str, int] = {}
    reintentos = 0
    reintentos_429 = 0
    espera_429_ms = 0.0
    turnos_con_429 = 0
    resultados: dict[str, int] = {}
    modelos_vistos: dict[str, dict[str, int]] = {}
    consultas_rag = 0
    citas_rag = 0
    rag_suficientes = 0
    rag_sin_fuente = 0
    fuentes_rag: dict[str, int] = {}
    segundos_audio = 0.0
    fuentes: dict[str, int] = {}
    extraccion_fallida: dict[str, int] = {}
    stt_fallido: dict[str, int] = {}

    for registro in leer(cfg.ruta_turnos_jsonl):
        tipo = registro.get("tipo")
        if tipo == "cierre":
            llamadas_cerradas.add(str(registro.get("llamada_id")))
            continue
        if tipo != "turno":
            continue

        n_turnos += 1
        llamadas.add(str(registro.get("llamada_id")))
        lat = registro.get("latencia_ms") or {}
        valor_cliente = lat.get("cliente_fin_habla_a_audio")
        origen = lat.get("cliente_origen", ORIGEN_NAVEGADOR)
        if isinstance(valor_cliente, (int, float)):
            if origen == ORIGEN_NAVEGADOR:
                cliente.append(float(valor_cliente))
            else:
                otras_fuentes.setdefault(str(origen), []).append(float(valor_cliente))
                turnos_sin_telemetria += 1
        else:
            turnos_sin_telemetria += 1
        if isinstance(lat.get("servidor_total"), (int, float)):
            servidor.append(float(lat["servidor_total"]))
        for nombre, valor in (lat.get("spans") or {}).items():
            if isinstance(valor, (int, float)):
                spans.setdefault(nombre, []).append(float(valor))

        # Un turno «contaminado» es el que esperó a un 429. Su latencia no es
        # comparable con la de un turno limpio, así que el conteo va aparte para
        # que el P50/P95 se pueda leer sabiendo cuántos turnos lo ensucian.
        turno_espero_429 = False

        for llamado in registro.get("llm") or []:
            if int(llamado.get("reintentos_429") or 0):
                turno_espero_429 = True
            rol = str(llamado.get("rol", "?"))
            invocaciones[rol] = invocaciones.get(rol, 0) + 1
            resultado = str(llamado.get("resultado", "?"))
            resultados[resultado] = resultados.get(resultado, 0) + 1
            reintentos += int(llamado.get("reintentos") or 0)
            reintentos_429 += int(llamado.get("reintentos_429") or 0)
            espera_429_ms += float(llamado.get("espera_reintento_ms") or 0.0)
            modelo = str(llamado.get("modelo") or "(sin modelo)")
            acumulado = modelos_vistos.setdefault(
                modelo, {"in": 0, "out": 0, "razonamiento": 0}
            )
            entrada = llamado.get("tokens_in")
            salida = llamado.get("tokens_out")
            if isinstance(entrada, int):
                tokens_in += entrada
                acumulado["in"] += entrada
            if isinstance(salida, int):
                tokens_out += salida
                acumulado["out"] += salida
            razonados = llamado.get("tokens_razonamiento")
            if isinstance(razonados, int):
                tokens_razonamiento += razonados
                acumulado["razonamiento"] += razonados

        if turno_espero_429:
            turnos_con_429 += 1

        rag = registro.get("rag") or {}
        consultas_rag += int(rag.get("consultas") or 0)
        citas_rag += len(rag.get("citas") or [])
        if rag.get("consultas"):
            if rag.get("suficiente"):
                rag_suficientes += 1
            else:
                rag_sin_fuente += 1
            fuente_rag = str(rag.get("fuente") or "?")
            fuentes_rag[fuente_rag] = fuentes_rag.get(fuente_rag, 0) + 1

        stt = registro.get("stt") or {}
        if isinstance(stt.get("segundos_audio"), (int, float)):
            segundos_audio += float(stt["segundos_audio"])

        fuente = str(registro.get("fuente_respuesta") or "?")
        fuentes[fuente] = fuentes.get(fuente, 0) + 1

        # Turnos cuya extracción no produjo señales, por causa. Es lo que impide
        # leer un AGOTAMIENTO como si fuera un paciente que no supo contestar.
        res_extraccion = str((registro.get("extraccion") or {}).get("resultado") or "")
        if res_extraccion and res_extraccion not in ("ok", "no_invocado"):
            extraccion_fallida[res_extraccion] = (
                extraccion_fallida.get(res_extraccion, 0) + 1
            )
        res_stt = str((registro.get("stt") or {}).get("resultado") or "")
        if res_stt and res_stt != "ok":
            stt_fallido[res_stt] = stt_fallido.get(res_stt, 0) + 1

    costo = 0.0
    sin_tarifa: list[str] = []
    for modelo, uso in modelos_vistos.items():
        tarifa = tarifas.get(modelo)
        if not tarifa:
            sin_tarifa.append(modelo)
            continue
        costo += costo_de_uso(uso, tarifa)

    return {
        "fuente": str(cfg.ruta_turnos_jsonl),
        "metodo_percentil": "interpolación lineal entre vecinos del rango (igual que numpy.percentile)",
        "n_llamadas": len(llamadas),
        "n_llamadas_cerradas": len(llamadas_cerradas),
        "n_turnos": n_turnos,
        "latencia_ms": {
            "cliente_fin_habla_a_audio": {
                **_resumen(cliente),
                "es_la_cifra_reportada": True,
                "turnos_sin_telemetria": turnos_sin_telemetria,
                "medido_por": "el navegador: t0 en el fin de habla del VAD, t1 cuando suena el primer sample",
            },
            "servidor_total": {
                **_resumen(servidor),
                "es_la_cifra_reportada": False,
                "nota": "desglose explicativo; no incluye subida, decodificación ni arranque de reproducción",
            },
            "otras_fuentes": {
                nombre: {
                    **_resumen(valores),
                    "es_la_cifra_reportada": False,
                    "nota": (
                        "medición de un cliente sin reproducción de audio: cota "
                        "inferior, NO comparable con la del navegador y por eso "
                        "fuera del P50/P95 reportado"
                    ),
                }
                for nombre, valores in sorted(otras_fuentes.items())
            },
            "spans": {nombre: _resumen(vals) for nombre, vals in sorted(spans.items())},
        },
        "consumo": {
            "tokens_entrada": tokens_in,
            "tokens_salida": tokens_out,
            # Generados por el modelo y NO incluidos en `tokens_salida`, porque
            # el proveedor no los pone en `completion_tokens`. Se cobran igual.
            # Si esto no es cero, `tokens_salida` NO es el consumo de salida.
            "tokens_razonamiento": tokens_razonamiento,
            "invocaciones_llm": invocaciones,
            "reintentos_llm": reintentos,
            "reintentos_429_llm": reintentos_429,
            "espera_429_ms": round(espera_429_ms, 1),
            # Cuántos turnos del P50/P95 llevan una espera de 429 dentro. Si no
            # es cero, la latencia reportada mide la cuota del proveedor tanto
            # como mide el sistema.
            "turnos_con_espera_429": turnos_con_429,
            "resultados_llm": resultados,
            "por_modelo": modelos_vistos,
            "costo_usd": round(costo, 6) if not sin_tarifa else None,
            "costo_usd_parcial": round(costo, 6),
            "modelos_sin_tarifa": sorted(sin_tarifa),
            "segundos_audio_transcritos": round(segundos_audio, 1),
            "costo_transcripcion_usd": None,
            "nota_costo": (
                "El costo del STT no se calcula: se factura por segundo de audio y esa "
                "tarifa no está declarada en configuracion/tarifas.json. Se reportan los "
                "segundos, que es el insumo verificable."
            ),
        },
        "rag": {
            "consultas": consultas_rag,
            "citas": citas_rag,
            "respondidas_con_fuente": rag_suficientes,
            "limite_declarado": rag_sin_fuente,
            "fuentes": fuentes_rag,
            "nota": (
                "«límite declarado» son las preguntas en las que ningún fragmento "
                "alcanzó el umbral de suficiencia y el agente dijo que no tenía el "
                "dato. Es una salida correcta, no un fallo: la alternativa era "
                "improvisar una respuesta clínica."
            ),
        },
        "fuente_respuesta": fuentes,
        "extraccion": {
            "turnos_sin_extraccion": extraccion_fallida,
            "turnos_sin_stt": stt_fallido,
            # `error` y `timeout` de CUALQUIERA de los dos proveedores son
            # fallos del agente; `json_invalido` es el modelo respondiendo mal, y
            # una transcripción vacía con el STT en `ok` es el paciente callando.
            # Se separan porque solo los primeros eximen de cobrar la repregunta
            # (HD7, enmienda del 2026-08-10).
            "turnos_sin_llm_real": (
                extraccion_fallida.get("error", 0)
                + extraccion_fallida.get("timeout", 0)
                + stt_fallido.get("error", 0)
                + stt_fallido.get("timeout", 0)
            ),
        },
    }
