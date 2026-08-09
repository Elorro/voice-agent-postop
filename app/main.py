"""Punto de entrada de la aplicación. Esqueleto: sin lógica de negocio.

Lo que NO hay aquí todavía, a propósito: turno de voz, STT, LLM, RAG y consola
clínica. Y no se importa `politica/`: ese módulo es stdlib pura, está cerrado y
verificado con su propia batería, y se conectará en el paso siguiente.
"""

from __future__ import annotations

import logging
import logging.handlers
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app import salud
from app.config import Config, obtener_config

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
    _log.info("precargando embedder y voz…")
    await anyio.to_thread.run_sync(salud.precargar, cfg)
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

    DIR_ESTATICOS.mkdir(parents=True, exist_ok=True)
    app.mount("/estaticos", StaticFiles(directory=DIR_ESTATICOS), name="estaticos")

    @app.get("/", response_class=HTMLResponse)
    def inicio() -> HTMLResponse:
        return HTMLResponse(_PORTADA)

    return app


_PORTADA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>voice-agent-postop</title>
<link rel="stylesheet" href="/estaticos/estilo.css"></head>
<body><main>
<h1>voice-agent-postop</h1>
<p class="lema">Agente de voz para seguimiento postoperatorio &middot;
Tech Sphere Challenge 2026.</p>
<p><strong>Esqueleto levantable.</strong> El turno de voz, el LLM, el RAG y la
consola clínica llegan en el paso siguiente. Lo que este contenedor ya hace es
arrancar y decir con exactitud en qué estado está.</p>
<p class="acciones"><a class="boton" href="/salud">Ver verificación de estado</a></p>
<p class="tenue">¿La página de estado dice NO LISTO? El detalle de cada
componente aparece ahí mismo, junto con qué hacer.</p>
</main></body></html>
"""

app = crear_app()
