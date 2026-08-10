"""Endpoints del turno de voz.

    POST /api/llamada                  crea la llamada; devuelve llamada_id +
                                       audio de apertura
    POST /api/llamada/{id}/turno       multipart: audio + delta_fin_habla_ms
    POST /api/llamada/{id}/telemetria  beacon del cliente con la latencia real
    POST /api/llamada/{id}/cierre      resumen estructurado + totales
    GET  /metricas                     P50/P95 y consumo, leyendo el JSONL

Sobre `delta_fin_habla_ms` en el turno: es la medición del turno **anterior**.
Tiene que ser así. En el instante en que el cliente sube el audio conoce su `t0`
(el fin de habla que acaba de ocurrir) pero todavía no su `t1` (el primer sample
sonando), que es un evento futuro. El beacon de `/telemetria` cubre el último
turno, cuando ya no habrá otro que lleve la medición a cuestas.

Y siempre un DELTA, nunca un instante: comparar el reloj del navegador con el
del servidor metería el desfase entre las dos máquinas dentro de la métrica.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app import registro
from app.config import Config, obtener_config
from app.dialogo import orquestador
from app.dialogo.estado import Almacen
from app.servicios import obtener_servicios

_log = logging.getLogger(__name__)

router = APIRouter()

ALMACEN = Almacen()
"""Estado de las llamadas en curso. Un servicio, un proceso, un worker."""


def _cfg() -> Config:
    return obtener_config()


def _llamada_o_404(llamada_id: str):
    llamada = ALMACEN.obtener(llamada_id)
    if llamada is None:
        raise HTTPException(status_code=404, detail=f"llamada desconocida: {llamada_id}")
    return llamada


@router.post("/api/llamada")
async def crear_llamada(request: Request) -> JSONResponse:
    """Abre la llamada y devuelve el audio de apertura.

    `dia_postop` es dato del seguimiento, no señal indagable: entra aquí y no se
    pregunta nunca. Si no viene, la política lo trata por su cuenta (régimen
    TARDÍO más una marca), y eso es decisión suya, no de este endpoint.
    """
    cfg = _cfg()
    try:
        cuerpo = await request.json()
    except Exception:  # noqa: BLE001 - cuerpo vacío es un caso legítimo
        cuerpo = {}
    if not isinstance(cuerpo, dict):
        cuerpo = {}

    dia = cuerpo.get("dia_postop")
    if dia is not None:
        if isinstance(dia, bool) or not isinstance(dia, (int, str)):
            raise HTTPException(status_code=400, detail="dia_postop debe ser un entero")
        try:
            dia = int(dia)
        except ValueError:
            raise HTTPException(status_code=400, detail="dia_postop debe ser un entero")
        if dia < 0:
            raise HTTPException(status_code=400, detail="dia_postop no puede ser negativo")

    paciente = cuerpo.get("paciente_id")
    llamada, payload = orquestador.abrir_llamada(
        cfg,
        obtener_servicios(cfg),
        ALMACEN,
        paciente_id=str(paciente) if paciente else None,
        dia_postop=dia,
    )
    _log.info("llamada %s abierta (dia_postop=%s)", llamada.id, dia)
    return JSONResponse(payload)


@router.post("/api/llamada/{llamada_id}/turno")
def turno(
    llamada_id: str,
    audio: UploadFile = File(...),
    delta_fin_habla_ms: float | None = Form(default=None),
    turno_medido_idx: int | None = Form(default=None),
    duracion_audio_ms: float | None = Form(default=None),
    origen_medicion: str = Form(default=registro.ORIGEN_NAVEGADOR),
) -> JSONResponse:
    """Un turno: audio del paciente, audio del agente."""
    cfg = _cfg()
    llamada = _llamada_o_404(llamada_id)

    # La medición que viene pegada al turno es la del turno anterior.
    if delta_fin_habla_ms is not None and delta_fin_habla_ms > 0:
        idx = turno_medido_idx if turno_medido_idx is not None else llamada.turno_idx
        registro.parchear_latencia_cliente(
            cfg, llamada_id, idx, delta_fin_habla_ms, origen_medicion
        )

    if not llamada.abierta:
        raise HTTPException(
            status_code=409,
            detail=f"la llamada {llamada_id} ya está cerrada ({llamada.criterio})",
        )
    if llamada.turno_idx >= cfg.max_turnos_llamada:
        # Salvaguarda, no política: la política termina sola al agotar
        # TOPE_GLOBAL. Si esto salta, hay un bug de contabilidad, y es mejor
        # cerrar la llamada que dejarla girando delante del paciente.
        resumen = orquestador.cerrar_llamada(
            cfg, llamada, ALMACEN, motivo="tope_de_turnos"
        )
        raise HTTPException(status_code=409, detail={"tope_de_turnos": resumen})

    contenido = audio.file.read()
    payload = orquestador.procesar_turno(
        cfg,
        obtener_servicios(cfg),
        llamada,
        contenido,
        nombre_archivo=audio.filename or "turno.webm",
        segundos_audio=(duracion_audio_ms / 1000.0) if duracion_audio_ms else None,
    )
    if not llamada.abierta:
        payload["cierre"] = orquestador.cerrar_llamada(
            cfg, llamada, ALMACEN, motivo="clasificada"
        )
    return JSONResponse(payload)


@router.post("/api/llamada/{llamada_id}/telemetria")
async def telemetria(llamada_id: str, request: Request) -> JSONResponse:
    """Beacon del cliente con la latencia real hasta el primer sample sonando.

    Se lee el cuerpo crudo en vez de declarar un modelo porque
    `navigator.sendBeacon` manda `text/plain` (o un Blob) y no negocia
    `Content-Type`: exigir `application/json` haría que el beacon del último
    turno —justo el que no tiene un turno siguiente que lo lleve— se perdiera.
    """
    cfg = _cfg()
    crudo = await request.body()
    try:
        datos = json.loads(crudo.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="cuerpo no es JSON")
    if not isinstance(datos, dict):
        raise HTTPException(status_code=400, detail="cuerpo no es un objeto JSON")

    try:
        turno_idx = int(datos["turno_idx"])
        delta = float(datos["delta_fin_habla_ms"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=400, detail="se esperan turno_idx y delta_fin_habla_ms"
        )
    if delta <= 0:
        raise HTTPException(status_code=400, detail="delta_fin_habla_ms debe ser > 0")

    # Quién midió importa tanto como el número: un cliente sin reproducción de
    # audio no puede ver el «primer sample sonando» y su medición es una cota
    # inferior. Se anota aparte y no entra en el P50/P95 reportado.
    origen = str(datos.get("origen") or registro.ORIGEN_NAVEGADOR)
    anotado = registro.parchear_latencia_cliente(
        cfg, llamada_id, turno_idx, delta, origen
    )
    return JSONResponse(
        {"anotado": anotado, "turno_idx": turno_idx, "ms": delta, "origen": origen}
    )


@router.post("/api/llamada/{llamada_id}/cierre")
def cierre(llamada_id: str) -> JSONResponse:
    """Resumen estructurado de la llamada + totales. Idempotente."""
    cfg = _cfg()
    llamada = _llamada_o_404(llamada_id)
    resumen = orquestador.cerrar_llamada(
        cfg, llamada, ALMACEN, motivo="solicitado" if llamada.abierta else "clasificada"
    )
    return JSONResponse(resumen)


@router.get("/api/llamada/{llamada_id}")
def estado_llamada(llamada_id: str) -> JSONResponse:
    """Estado en curso. Útil para depurar sin abrir el registro."""
    return JSONResponse(_llamada_o_404(llamada_id).a_json())


# --------------------------------------------------------------------------- #
# Métricas
# --------------------------------------------------------------------------- #
@router.get("/metricas", response_class=HTMLResponse, response_model=None)
def metricas(request: Request) -> Response:
    """P50/P95 y consumo, calculados LEYENDO el JSONL, no desde memoria.

    Que la página lea el mismo archivo que el jurado puede abrir elimina por
    construcción la posibilidad de que el número reportado y el registro
    discrepen.
    """
    cfg = _cfg()
    datos = registro.calcular_metricas(cfg)
    quiere_json = (
        request.query_params.get("formato") == "json"
        or "application/json" in request.headers.get("accept", "").lower()
    )
    if quiere_json:
        return JSONResponse(datos)
    return HTMLResponse(_metricas_a_html(datos))


def _celda(resumen: dict[str, Any]) -> str:
    def fmt(valor: Any) -> str:
        return "—" if valor is None else f"{valor:g}"

    return (
        f"<td>{resumen.get('n', 0)}</td><td><strong>{fmt(resumen.get('p50'))}</strong></td>"
        f"<td><strong>{fmt(resumen.get('p95'))}</strong></td>"
        f"<td>{fmt(resumen.get('min'))}</td><td>{fmt(resumen.get('max'))}</td>"
    )


def _metricas_a_html(d: dict[str, Any]) -> str:
    import html

    lat = d["latencia_ms"]
    cliente = lat["cliente_fin_habla_a_audio"]
    servidor = lat["servidor_total"]
    filas_spans = "".join(
        f"<tr><td>{html.escape(nombre)}</td>{_celda(resumen)}</tr>"
        for nombre, resumen in lat["spans"].items()
    )
    filas_otras = "".join(
        f'<tr><td>{html.escape(nombre)} <span class="opcional">(no comparable)</span></td>'
        f"{_celda(resumen)}</tr>"
        for nombre, resumen in lat.get("otras_fuentes", {}).items()
    )
    consumo = d["consumo"]
    costo = consumo["costo_usd"]
    costo_txt = (
        f"{costo:.6f} USD"
        if costo is not None
        else (
            f"sin tarifa declarada para: "
            f"{html.escape(', '.join(consumo['modelos_sin_tarifa']))} "
            f"(parcial: {consumo['costo_usd_parcial']:.6f} USD)"
        )
    )
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Métricas — voice-agent-postop</title>
<link rel="stylesheet" href="/estaticos/estilo.css"></head><body><main>
<h1>Métricas del turno de voz</h1>
<p class="lema">Calculadas leyendo <code>{html.escape(d["fuente"])}</code>, el
mismo archivo que usted puede abrir. Percentiles por {html.escape(d["metodo_percentil"])}.</p>

<h2>Latencia — la cifra que manda</h2>
<p class="tenue">{html.escape(cliente["medido_por"])}.</p>
<table><thead><tr><th>Medida</th><th>n</th><th>P50 (ms)</th><th>P95 (ms)</th>
<th>mín</th><th>máx</th></tr></thead><tbody>
<tr><td><strong>cliente: fin de habla → audio sonando</strong></td>{_celda(cliente)}</tr>
<tr><td>servidor: total del turno <span class="opcional">(desglose)</span></td>{_celda(servidor)}</tr>
{filas_spans}
{filas_otras}
</tbody></table>
<p class="tenue">Turnos sin telemetría de navegador: {cliente["turnos_sin_telemetria"]} de {d["n_turnos"]}.
Las filas «no comparables» vienen de un cliente sin reproducción de audio (banco de
pruebas): su t1 es «audio recibido», no «primer sample sonando», así que son cota
inferior y quedan fuera del P50/P95 reportado.
Los spans del servidor son desglose explicativo: no incluyen subida, decodificación
ni arranque de la reproducción.</p>

<h2>Consumo</h2>
<table><tbody>
<tr><td>Llamadas / turnos</td><td>{d["n_llamadas"]} ({d["n_llamadas_cerradas"]} cerradas) / {d["n_turnos"]}</td></tr>
<tr><td>Tokens entrada / salida</td><td>{consumo["tokens_entrada"]} / {consumo["tokens_salida"]}</td></tr>
<tr><td>Invocaciones del LLM</td><td>{html.escape(json.dumps(consumo["invocaciones_llm"], ensure_ascii=False))}</td></tr>
<tr><td>Resultados</td><td>{html.escape(json.dumps(consumo["resultados_llm"], ensure_ascii=False))}</td></tr>
<tr><td>Reintentos</td><td>{consumo["reintentos_llm"]}</td></tr>
<tr><td>Costo</td><td>{costo_txt}</td></tr>
<tr><td>Audio transcrito</td><td>{consumo["segundos_audio_transcritos"]} s (costo no calculado: tarifa no declarada)</td></tr>
<tr><td>Fuente de la respuesta</td><td>{html.escape(json.dumps(d["fuente_respuesta"], ensure_ascii=False))}</td></tr>
<tr><td>RAG</td><td>{d["rag"]["consultas"]} consultas, {d["rag"]["citas"]} citas;
{d["rag"]["respondidas_con_fuente"]} respondidas con fuente y
{d["rag"]["limite_declarado"]} con límite declarado —
{html.escape(d["rag"]["nota"])}</td></tr>
</tbody></table>
<footer><p><a href="/">Inicio</a> · <a href="/salud">Estado</a> ·
<a href="/metricas?formato=json">esta página en JSON</a></p></footer>
</main></body></html>"""
