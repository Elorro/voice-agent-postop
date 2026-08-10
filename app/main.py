"""Punto de entrada de la aplicación.

Monta la verificación de estado, el turno de voz (`app/api.py`), la consola de
administración de documentos (`app/api_documentos.py`) y las dos páginas.

Las rutas de las dos páginas, y por qué cambió una en 3.2
---------------------------------------------------------
    /consola   consola de ADMINISTRACIÓN (subir, listar y eliminar documentos)
    /llamada   cliente de la llamada de voz

Hasta 3.1, `/consola` era el cliente de la llamada. El README del reto reserva
`GET /consola` para la consola de administración, y la compuerta G5 se evalúa
sobre esa ruta exacta; mantener ahí el cliente de voz habría hecho fallar la
compuerta por un nombre. El cliente de voz se movió a `/llamada`, que además dice
mejor lo que es. Todos los enlaces del proyecto apuntan ya a la ruta nueva.

Este archivo NO importa `politica`: el único punto del árbol que lo hace es
`app/dialogo/orquestador.py`, y `tests/test_import_unico_politica.py` lo
verifica sobre los archivos rastreados por git.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app import api, api_documentos, salud
from app.config import Config, obtener_config
from app.servicios import precargar_servicios

DIR_ESTATICOS = Path(__file__).resolve().parent / "estaticos"

_log = logging.getLogger("app")


def configurar_logging(cfg: Config) -> None:
    """Log a stdout (lo lee `docker compose logs`) y a archivo rotado.

    El archivo vive en el bind mount `./datos/logs`, para que el jurado pueda
    leerlo con su editor y sin `docker cp`. Si el directorio no fuera
    escribible, el log a archivo se omite y el proceso sigue: quedarse sin
    servicio por no poder escribir un log sería peor que perder el log.
    """
    formato = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    raiz = logging.getLogger()
    raiz.setLevel(cfg.nivel_log)

    consola = logging.StreamHandler()
    consola.setFormatter(formato)
    raiz.addHandler(consola)

    try:
        cfg.dir_logs.mkdir(parents=True, exist_ok=True)
        archivo = logging.handlers.RotatingFileHandler(
            cfg.dir_logs / "app.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        archivo.setFormatter(formato)
        raiz.addHandler(archivo)
    except OSError as exc:
        _log.warning("sin log a archivo en %s: %s", cfg.dir_logs, exc)


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    """Carga los modelos al arrancar, no en la primera petición.

    Vendorizados en la imagen, así que esto es lectura de disco: ~1-3 s. Si se
    hiciera en la primera petición, el jurado vería la página de estado colgada
    justo en el momento en que la está usando para juzgar si el sistema sirve.
    """
    cfg = obtener_config()
    configurar_logging(cfg)
    _log.info("raíz del proyecto: %s", cfg.dir_dataset.parent)
    _log.info("almacén del índice: %s", cfg.almacen_indice)
    _log.info("registro de turnos: %s", cfg.ruta_turnos_jsonl)
    _log.info("precargando embedder, voz y clientes de inferencia…")
    await anyio.to_thread.run_sync(salud.precargar, cfg)
    await anyio.to_thread.run_sync(precargar_servicios, cfg)
    _log.info("listo para atender en el puerto %s", cfg.puerto)
    yield
    _log.info("apagando")


def crear_app() -> FastAPI:
    cfg = obtener_config()
    app = FastAPI(
        title="voice-agent-postop",
        summary="Agente de voz para seguimiento postoperatorio (esqueleto).",
        version="0.1.0",
        lifespan=ciclo_de_vida,
    )
    app.include_router(salud.router)
    app.include_router(api.router)
    app.include_router(api_documentos.router)

    DIR_ESTATICOS.mkdir(parents=True, exist_ok=True)
    app.mount("/estaticos", StaticFiles(directory=DIR_ESTATICOS), name="estaticos")

    @app.get("/", response_class=HTMLResponse)
    def inicio() -> HTMLResponse:
        return HTMLResponse(_PORTADA)

    @app.get("/llamada", response_class=HTMLResponse)
    def llamada() -> HTMLResponse:
        """Cliente de la llamada. JS plano, sin build y sin node en la imagen.

        Los parámetros del detector de fin de habla se inyectan en la página
        como JSON en vez de pedirse por una petición aparte: son configuración
        del servidor (`app/config.py`) y un viaje extra antes del primer turno
        es latencia que se paga justo cuando el jurado está mirando el reloj.
        """
        return HTMLResponse(_llamada_html(cfg))

    @app.get("/consola", response_class=HTMLResponse)
    def consola() -> HTMLResponse:
        """Consola de ADMINISTRACIÓN de documentos. La ruta que evalúa G5."""
        return HTMLResponse(_consola_html(cfg))

    return app


def _llamada_html(cfg: Config) -> str:
    configuracion = json.dumps(
        {
            "vad_umbral_rms": cfg.vad_umbral_rms,
            "vad_silencio_ms": cfg.vad_silencio_ms,
            "vad_minimo_habla_ms": cfg.vad_minimo_habla_ms,
            "periodo_ms": 40,
            "maximo_turno_ms": 20000,
        },
        ensure_ascii=False,
    )
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Llamada — voice-agent-postop</title>
<link rel="stylesheet" href="/estaticos/estilo.css"></head>
<body><main class="ancho">
<h1>Seguimiento postoperatorio</h1>
<p class="lema">Hable con el agente. El micrófono se abre solo cuando el agente
termina de hablar: en este sub-paso no hay interrupción (barge-in).</p>

<div class="campos">
  <div><label for="dia_postop">Día postoperatorio</label>
  <input id="dia_postop" type="number" min="0" step="1" placeholder="p. ej. 5"></div>
  <div><label for="paciente_id">Identificador del paciente</label>
  <input id="paciente_id" type="text" placeholder="opcional"></div>
  <button id="iniciar" class="boton">Iniciar llamada</button>
  <button id="colgar" class="boton secundario" disabled>Colgar</button>
</div>

<div class="estado-linea" id="estado">Listo para iniciar.</div>
<div class="medidor"><div id="nivel"></div></div>

<ul class="dialogo" id="dialogo"></ul>
<div id="resumen"></div>

<footer><p class="tenue">El micrófono exige un origen seguro: use
<code>http://localhost:8080/llamada</code> o sirva por HTTPS. Sin eso el
navegador no concede acceso, y no es algo que la aplicación pueda cambiar.</p>
<p><a href="/">Inicio</a> · <a href="/salud">Estado</a> ·
<a href="/consola">Documentos</a> · <a href="/metricas">Métricas</a></p>
</footer>

<script type="application/json" id="configuracion">{configuracion}</script>
<script src="/estaticos/consola.js"></script>
</main></body></html>"""


def _consola_html(cfg: Config) -> str:
    """Consola de administración del corpus. JS plano, sin build.

    Los límites (formatos y tamaño máximo) se inyectan como JSON por la misma
    razón que en la página de llamada: son configuración del servidor y pedirlos
    por una petición aparte solo añadiría un viaje. La lista de documentos, en
    cambio, SÍ se pide: es estado que cambia mientras la página está abierta, y
    hornearla en el HTML la dejaría vieja en el primer segundo.
    """
    configuracion = json.dumps(
        {
            "max_mb": cfg.subidos_max_mb,
            "periodo_sondeo_ms": 1500,
        },
        ensure_ascii=False,
    )
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Documentos — voice-agent-postop</title>
<link rel="stylesheet" href="/estaticos/estilo.css"></head>
<body><main class="ancho">
<h1>Consola de administración del corpus</h1>
<p class="lema">Suba guías y protocolos. Un documento indexado queda disponible
para el agente <strong>sin reiniciar nada</strong>; al eliminarlo, el agente deja
de usarlo de inmediato.</p>

<div class="campos">
  <div><label for="archivo">Documento (PDF, TXT o MD)</label>
  <input id="archivo" type="file" accept=".pdf,.txt,.md,.markdown"></div>
  <button id="subir" class="boton">Subir e indexar</button>
</div>

<div class="estado-linea" id="estado">Cargando inventario…</div>

<table class="documentos" id="tabla">
  <thead><tr><th>Estado</th><th>Documento</th><th>Páginas</th>
  <th>Fragmentos en el índice</th><th>Subido</th><th></th></tr></thead>
  <tbody id="filas"></tbody>
</table>

<p class="tenue">El indicador dice <em>en cola</em> → <em>procesando</em> →
<em>procesado y disponible</em>. «Fragmentos en el índice» se lee del índice, no
del inventario: es la comprobación de que el documento está dentro de verdad y no
solo de que el servidor cree haberlo metido.</p>
<p class="tenue">No se hace OCR. Un PDF escaneado sin capa de texto se rechaza con
ese motivo, en vez de indexarse vacío y no responder nunca.</p>

<footer><p><a href="/">Inicio</a> · <a href="/salud">Estado</a> ·
<a href="/llamada">Llamada</a> · <a href="/metricas">Métricas</a></p></footer>

<script type="application/json" id="configuracion">{configuracion}</script>
<script src="/estaticos/administracion.js"></script>
</main></body></html>"""


_PORTADA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>voice-agent-postop</title>
<link rel="stylesheet" href="/estaticos/estilo.css"></head>
<body><main>
<h1>voice-agent-postop</h1>
<p class="lema">Agente de voz para seguimiento postoperatorio &middot;
Tech Sphere Challenge 2026.</p>
<p><strong>Turno de voz completo.</strong> Audio &rarr; transcripción &rarr;
extracción de señales &rarr; <em>decisión de la política</em> &rarr; respuesta
hablada. La clase clínica no la produce el modelo de lenguaje: la produce el
módulo de decisión, y por eso ninguna cosa que diga el paciente puede cambiarla.</p>
<p><strong>Preguntas del paciente, respondidas desde el corpus.</strong> Con cita
—documento y página— en el registro de cada turno. Si el corpus no alcanza, el
agente <em>declara su límite</em> en vez de improvisar. Y el RAG no participa en
la clasificación: no hay ruta por la que una respuesta pueda mover la clase.</p>
<p>Lo que todavía no hay, dicho aquí y no en letra pequeña: interrupción del
agente (barge-in).</p>
<p class="acciones"><a class="boton" href="/llamada">Iniciar una llamada</a>
&nbsp; <a class="boton secundario" href="/consola">Administrar documentos</a>
&nbsp; <a class="boton secundario" href="/salud">Verificación de estado</a>
&nbsp; <a class="boton secundario" href="/metricas">Métricas</a></p>
<p class="tenue">¿La página de estado dice NO LISTO? El detalle de cada
componente aparece ahí mismo, junto con qué hacer.</p>
</main></body></html>
"""

app = crear_app()
