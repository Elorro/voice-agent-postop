# voice-agent-postop — imagen única del servicio.
#
# Objetivo de tamaño: <= 400 MB comprimida (lo que el jurado descarga de verdad).
# El tamaño real medido está reportado en README.md, con el comando del que sale.
#
# Dos decisiones que fijan todo lo demás:
#
#   1. NUNCA torch. El embedder corre sobre onnxruntime (CPU, ~58 MB). Con
#      torch la imagen se va a 2-5 GB y el reto se pierde en la descarga.
#   2. Los modelos se VENDORIZAN en tiempo de build, no en el primer arranque.
#      Un modelo que se descarga al arrancar es una dependencia de red en la
#      máquina del jurado, en el peor momento posible. Este build falla si
#      cualquiera de los dos no carga.

# --- Elección de la voz, compartida por las dos etapas ------------------------
# Declarados antes del primer FROM para que ambas etapas los vean. Cambiar la
# voz es cambiar estos tres valores y reconstruir; nada más los referencia.
ARG VOZ_MODELO=es_MX-ald-medium.onnx
ARG VOZ_RUTA=es/es_MX/ald/medium
ARG VOZ_URL_BASE=https://huggingface.co/rhasspy/piper-voices/resolve/main

# =============================================================================
# Etapa 1 — constructor: resuelve dependencias y baja los modelos.
# =============================================================================
FROM python:3.12-slim AS constructor

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY requirements.txt /tmp/requirements.txt
RUN pip install --require-virtualenv -r /tmp/requirements.txt

# --- Auditoría: lo instalado debe coincidir con lo fijado --------------------
# requirements.txt afirma ser el resultado de un `pip freeze` real. Esto lo
# comprueba: si alguien inventó una versión, el build se cae aquí y no en la
# máquina del jurado.
RUN python - <<'PY'
import re, subprocess, sys

IGNORAR = {"pip", "setuptools", "wheel", "distribute", "pkg-resources"}
norm = lambda n: re.sub(r"[-_.]+", "-", n).lower()

def leer(texto):
    d = {}
    for linea in texto.splitlines():
        linea = linea.split("#", 1)[0].strip()
        if not linea or "==" not in linea:
            continue
        nombre, version = linea.split("==", 1)
        if norm(nombre) in IGNORAR:
            continue
        d[norm(nombre)] = version.strip()
    return d

fijado = leer(open("/tmp/requirements.txt", encoding="utf-8").read())
instalado = leer(subprocess.run(
    [sys.executable, "-m", "pip", "freeze", "--all"],
    capture_output=True, text=True, check=True).stdout)

faltan = {k: v for k, v in fijado.items() if k not in instalado}
sobran = {k: v for k, v in instalado.items() if k not in fijado}
difieren = {k: (v, instalado[k]) for k, v in fijado.items()
            if k in instalado and instalado[k] != v}

if faltan or sobran or difieren:
    print("requirements.txt NO refleja el entorno instalado:")
    for k, v in sorted(faltan.items()):   print(f"  fijado y no instalado: {k}=={v}")
    for k, v in sorted(sobran.items()):   print(f"  instalado y no fijado: {k}=={v}")
    for k, (a, b) in sorted(difieren.items()):
        print(f"  versión distinta: {k} fijado {a}, instalado {b}")
    raise SystemExit(1)

print(f"requirements.txt verificado: {len(fijado)} paquetes, coincidencia exacta.")
PY

# --- Vendorizado del embedder por defecto de ChromaDB ------------------------
# ChromaDB resuelve su caché como `Path.home()/.cache/chroma/onnx_models`, así
# que HOME es la palanca: se fija aquí y se vuelve a fijar idéntico en la etapa
# final. Mismo HOME en build y en runtime => el modelo ya está donde se busca y
# el primer arranque no toca la red.
#
# Con reintentos: son ~79 MB desde S3 y un corte a mitad de descarga tumba el
# build entero. Observado una vez durante el desarrollo. Importa sobre todo en
# la ruta alternativa del README (`docker compose build` en la máquina del
# jurado, cuando ghcr.io no es alcanzable): ahí un fallo transitorio de red no
# puede costar la evaluación.
ENV HOME=/opt/cache_modelos
RUN mkdir -p /opt/cache_modelos && python - <<'PY'
import pathlib, shutil, time
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

destino = pathlib.Path(ONNXMiniLM_L6_V2.DOWNLOAD_PATH)
assert str(destino).startswith("/opt/cache_modelos"), destino

INTENTOS = 4
for intento in range(1, INTENTOS + 1):
    try:
        ef = DefaultEmbeddingFunction()
        vector = ef(["verificación de vendorizado del embedder"])[0]
        break
    except Exception as exc:
        print(f"intento {intento}/{INTENTOS} falló: {type(exc).__name__}: {exc}")
        if intento == INTENTOS:
            raise
        # Una descarga a medias envenena el intento siguiente: se borra entera.
        shutil.rmtree(destino, ignore_errors=True)
        time.sleep(5 * intento)

assert len(vector) == 384, len(vector)

modelo = destino / ONNXMiniLM_L6_V2.EXTRACTED_FOLDER_NAME / "model.onnx"
assert modelo.is_file(), f"no quedó el modelo en {modelo}"
print(f"embedder vendorizado: {modelo} ({modelo.stat().st_size/1e6:.0f} MB), dim={len(vector)}")

# El .tar.gz solo se usa para extraer; el cargador comprueba model.onnx y
# tokenizer.json, no el archivo. Son ~79 MB que no tienen por qué viajar.
tar = destino / ONNXMiniLM_L6_V2.ARCHIVE_FILENAME
if tar.is_file():
    tamano = tar.stat().st_size
    tar.unlink()
    print(f"descartado el tarball de descarga ({tamano/1e6:.0f} MB)")
PY

# --- Vendorizado de la voz de Piper ------------------------------------------
# Elección: es_MX-ald-medium. No existe voz colombiana en Piper. La variante más
# cercana es el español latinoamericano: su fonética (`espeak: es-419`) tiene
# seseo y yeísmo, como el colombiano. Las voces es_ES usan `espeak: es`, que
# distingue /s/ de /θ/ ("sien" vs "cien") — a un paciente colombiano le suena
# extranjera. Calidad `medium` (22.05 kHz) por equilibrio peso/inteligibilidad;
# el mismo locutor tiene `x_low` (21 MB) si hubiera que recortar la imagen sin
# cambiarle la voz al agente. Justificación completa en README.md.
ARG VOZ_MODELO
ARG VOZ_RUTA
ARG VOZ_URL_BASE

RUN mkdir -p /opt/voces && python - <<PY
import pathlib, time, urllib.request

base = "${VOZ_URL_BASE}".rstrip("/") + "/" + "${VOZ_RUTA}".strip("/")
destino = pathlib.Path("/opt/voces")
INTENTOS = 4

for sufijo in ("", ".json"):
    nombre = "${VOZ_MODELO}" + sufijo
    url = f"{base}/{nombre}"
    salida = destino / nombre
    for intento in range(1, INTENTOS + 1):
        try:
            urllib.request.urlretrieve(url, salida)
            break
        except Exception as exc:
            print(f"{nombre}: intento {intento}/{INTENTOS} falló: {exc}")
            salida.unlink(missing_ok=True)
            if intento == INTENTOS:
                raise
            time.sleep(5 * intento)
    print(f"descargado {nombre}: {salida.stat().st_size/1e6:.1f} MB")
PY

RUN python - <<PY
import json, pathlib, onnxruntime

modelo = pathlib.Path("/opt/voces/${VOZ_MODELO}")
opciones = onnxruntime.SessionOptions()
opciones.log_severity_level = 3
sesion = onnxruntime.InferenceSession(
    str(modelo), sess_options=opciones, providers=["CPUExecutionProvider"])
entradas = [e.name for e in sesion.get_inputs()]
meta = json.loads(pathlib.Path(f"{modelo}.json").read_text(encoding="utf-8"))
print("voz cargada:", modelo.name,
      "| idioma", meta["language"]["code"],
      "|", meta["audio"]["sample_rate"], "Hz",
      "| entradas", entradas)
PY

# --- Poda ---------------------------------------------------------------------
# `kubernetes` (83 MB descomprimidos, ~25 MB comprimidos) SE QUEDA, aunque
# chromadb solo lo use en su modo servidor sobre un clúster y aquí se use
# `PersistentClient` en proceso. Se probó desinstalarlo y se revirtió el
# 2026-08-09 por asimetría de riesgo:
#
#   - Beneficio MEDIDO: 19,8 MB comprimidos (300,2 MB con `kubernetes` contra
#     280,4 MB sin él, ambos por `docker save … | wc -c`) sobre un presupuesto
#     de 400 MB. La imagen entregada deja ~100 MB de holgura sin la poda. No
#     compra nada que haga falta.
#   - Costo: un `ImportError` posible en cualquier ruta de chromadb que la
#     prueba de abajo no ejercita. La prueba cubre cliente, colección, embedder
#     y consulta; no cubre todo chromadb, y una poda solo es segura hasta donde
#     llega la prueba.
#   - Además, `requirements.txt` afirma ser un `pip freeze` real y la auditoría
#     de arriba lo verifica. Desinstalar después de auditar hacía que el archivo
#     dejara de describir la imagen entregada, justo lo que la auditoría existe
#     para impedir.
#
# La poda de `pip` y `setuptools` sí se conserva: no son dependencias de nadie
# en runtime, y la auditoría ya los ignora explícitamente (lista IGNORAR).
#
# Lo que queda aquí es la prueba de humo de chromadb, que se conserva por sí
# misma: comprueba en el build que el cliente en proceso funciona.
RUN python - <<'PY'
import chromadb, tempfile
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

ef = DefaultEmbeddingFunction()
with tempfile.TemporaryDirectory() as tmp:
    cliente = chromadb.PersistentClient(path=tmp)
    col = cliente.get_or_create_collection("prueba_de_build", embedding_function=ef)
    col.add(ids=["1"], documents=["control postoperatorio de prueba"])
    assert col.count() == 1
    assert col.query(query_texts=["control"], n_results=1)["ids"][0] == ["1"]
print("chromadb en proceso: cliente, colección, embedding y consulta OK")
PY

# pip y setuptools no hacen falta en runtime.
RUN pip uninstall -y pip setuptools 2>/dev/null || true

# =============================================================================
# Etapa 2 — runtime.
# =============================================================================
FROM python:3.12-slim

LABEL org.opencontainers.image.title="voice-agent-postop" \
      org.opencontainers.image.description="Agente de voz para seguimiento postoperatorio (Tech Sphere Challenge 2026)" \
      org.opencontainers.image.source="https://github.com/Elorro/voice-agent-postop" \
      org.opencontainers.image.licenses="MIT"

ARG VOZ_MODELO

# HOME idéntico al de la etapa constructora: es lo que hace que ChromaDB
# encuentre el modelo vendorizado en vez de salir a descargarlo.
ENV HOME=/opt/cache_modelos \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DIR_APP=/app \
    PUERTO=8080 \
    DIRECCION_BIND=0.0.0.0 \
    DATASET_DIR=./dataset \
    INDICE_DIR=./datos/indice \
    SUBIDOS_DIR=./datos/subidos \
    LOGS_DIR=./datos/logs \
    LLAMADAS_DIR=./datos/llamadas \
    INDICE_SEMILLA_DIR=/opt/indice_base \
    VOCES_DIR=/opt/voces \
    VOZ_MODELO=${VOZ_MODELO}

COPY --from=constructor /opt/venv /opt/venv
COPY --from=constructor /opt/cache_modelos /opt/cache_modelos
COPY --from=constructor /opt/voces /opt/voces

# --- Fonemizador de la voz ----------------------------------------------------
# El modelo de Piper NO recibe texto: recibe identificadores de fonema, y su
# `.json` declara `phoneme_type: espeak` con `espeak.voice: es-419`. Es decir,
# fue entrenado con los fonemas que produce espeak-ng para español
# latinoamericano; con otro fonemizador los identificadores no significarían lo
# mismo que en el entrenamiento y la voz saldría en otro idioma imaginario.
#
# Se instalan la BIBLIOTECA y los DATOS, no el ejecutable `espeak-ng`: el
# sintetizador la llama por ctypes (app/audio/tts.py), lo que evita un
# fork+exec por turno en el camino crítico. Los datos son ~25 MB sin comprimir
# y no se podan: el diccionario de una lengua no es un archivo por idioma que
# se pueda recortar a ojo, y el presupuesto de la imagen tiene holgura de sobra.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libespeak-ng1 espeak-ng-data \
    && rm -rf /var/lib/apt/lists/*

# Punto de montaje de la semilla del índice. Existe vacío a propósito: hoy no
# hay indexador, y el entrypoint tiene que distinguir "no hay semilla" (arranca
# vacío) de "la semilla falló" (sería un error).
RUN mkdir -p /opt/indice_base /app/datos/indice /app/datos/subidos /app/datos/logs \
             /app/datos/llamadas

WORKDIR /app
COPY app ./app
# El módulo de decisión clínica. Hasta 3.1 no estaba en la imagen porque nadie
# lo importaba; ahora `app/dialogo/orquestador.py` lo importa y sin esta línea
# el contenedor arranca y se cae en el primer turno. Es stdlib pura: no agrega
# ni una dependencia.
COPY politica ./politica
# Tabla de tarifas: ningún precio vive en el código (ver configuracion/tarifas.json).
COPY configuracion ./configuracion
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh

# --- Verificación final: la imagen que se entrega es capaz de dar un turno ----
# No basta con que los modelos cargaran en la etapa constructora: aquí se
# comprueba que sobrevivieron al COPY, que HOME sigue apuntando al mismo sitio,
# y —desde 3.1— que el camino texto -> fonemas -> audio funciona y que la
# política está dentro de la imagen. Los dos fallos que esto atrapa (la voz sin
# fonemizador, `politica/` fuera del COPY) se manifestarían, si no, en el primer
# turno del paciente.
RUN python - <<'PY'
import os, pathlib
assert os.environ["HOME"] == "/opt/cache_modelos"

from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2
modelo = pathlib.Path(ONNXMiniLM_L6_V2.DOWNLOAD_PATH) / ONNXMiniLM_L6_V2.EXTRACTED_FOLDER_NAME / "model.onnx"
assert modelo.is_file(), f"el embedder NO está vendorizado: falta {modelo}"

from app.config import obtener_config
from app import salud

cfg = obtener_config()
assert cfg.ruta_modelo_voz.is_file(), f"falta el modelo de voz: {cfg.ruta_modelo_voz}"
assert cfg.ruta_tarifas.is_file(), f"falta la tabla de tarifas: {cfg.ruta_tarifas}"

for sonda in (salud.sondear_embedder, salud.sondear_voz):
    c = sonda(cfg)
    print(f"  {c.clave}: {c.estado} — {c.detalle}")
    assert c.estado == "ok", c.detalle

import politica
d = politica.decidir(politica.Observacion(7, 2, 36.8, "normal", "normal", "normal", "normal"))
assert (d.clase.name, d.criterio.name) == ("VERDE", "S2"), d
print(f"  politica: en la imagen, {len(politica.NUCLEO)} señales de núcleo, humo OK")

from app.audio import tts
sintetizador = tts.obtener_sintetizador(cfg)
audio = sintetizador.sintetizar("Prueba de voz del seguimiento postoperatorio.")
assert audio.resultado == "ok" and len(audio.wav) > 10_000, audio
print(f"  voz: {len(audio.wav)} bytes de WAV, {audio.segundos:.2f} s, en {audio.ms:.0f} ms")

print("verificación final OK: embedder, voz sintetizando y política dentro de la imagen")
PY

EXPOSE 8080

# Réplica del healthcheck de compose, para quien arranque con `docker run`.
# Solo mide "el proceso responde"; el veredicto LISTO/NO LISTO está en el
# cuerpo de /salud, que es lo que hay que mirar.
HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
    CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PUERTO','8080')+'/salud',timeout=8).status==200 else 1)"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
