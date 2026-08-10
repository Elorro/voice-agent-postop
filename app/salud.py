"""Verificación de estado: `GET /salud`.

Por qué existe esta página y no basta un `200 OK`
-------------------------------------------------
Un 200 global no distingue «el proceso está arriba» de «el proceso está arriba
y mudo»: el servidor responde igual con el modelo de voz ausente, el índice
corrupto o sin clave del LLM. Esta ruta responde **siempre 200** y pone el
veredicto en el cuerpo, componente por componente.

El HTML es el verificador principal, no un adorno: un navegador es la única
herramienta garantizada en Linux, macOS y Windows. `curl` no está en Windows
antiguo, `jq` no está en ninguno de los tres por defecto.

El `healthcheck` de Docker consulta esta misma ruta, pero solo puede leer el
código HTTP: mide *proceso vivo*, no *sistema listo*. El veredicto lo da la
página. Están documentados como cosas distintas a propósito.
"""

from __future__ import annotations

import html
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import Config, obtener_config

_log = logging.getLogger(__name__)

router = APIRouter()

Estado = Literal["ok", "aviso", "fallo"]

_ETIQUETA_ESTADO: dict[Estado, str] = {
    "ok": "OK",
    "aviso": "AVISO",
    "fallo": "FALLO",
}


@dataclass(slots=True)
class Componente:
    """Resultado de sondear un componente."""

    clave: str
    nombre: str
    estado: Estado
    detalle: str
    bloqueante: bool = True
    datos: dict[str, Any] = field(default_factory=dict)

    @property
    def hunde_el_veredicto(self) -> bool:
        return self.bloqueante and self.estado == "fallo"

    def a_json(self) -> dict[str, Any]:
        return {
            "componente": self.clave,
            "nombre": self.nombre,
            "estado": self.estado,
            "detalle": self.detalle,
            "bloqueante": self.bloqueante,
            **({"datos": self.datos} if self.datos else {}),
        }


# ---------------------------------------------------------------------------
# Recursos pesados: se cargan una vez por proceso y se reutilizan.
#
# Un solo worker de uvicorn (ver compose.yaml y entrypoint.sh), así que este
# candado protege el único proceso que hay. El embedder son ~90 MB de ONNX y el
# modelo de voz ~63 MB: cargarlos en cada petición haría inusable la página.
# ---------------------------------------------------------------------------

_candado = threading.Lock()
_recursos: dict[str, Any] = {}


def _cargar_embedder() -> Any:
    """Instancia el embedder por defecto de ChromaDB.

    El modelo ONNX está vendorizado en la imagen bajo el directorio de caché
    de ChromaDB, que cuelga del home del proceso y la imagen fija en
    `/opt/cache_modelos` (ver Dockerfile). Si esta llamada intentara descargar
    algo, el arranque en
    una máquina sin red —o con red lenta— fallaría delante del jurado.
    """
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

    return DefaultEmbeddingFunction()


def _cargar_voz(cfg: Config) -> Any:
    """Devuelve el sintetizador del turno, no una sesión ONNX aparte.

    Es el MISMO objeto que usa `app/dialogo/orquestador.py`. Cargar aquí una
    segunda sesión duplicaría 63 MB en memoria y, peor, permitiría que la
    página de estado dijera OK sobre una voz distinta de la que habla.
    """
    from app.audio import tts

    return tts.obtener_sintetizador(cfg)


def _recurso(nombre: str, constructor: Any) -> Any:
    """Memoiza un recurso pesado; recuerda también el fallo, para no reintentar
    una carga costosa en cada petición cuando el recurso no existe."""
    with _candado:
        if nombre not in _recursos:
            try:
                _recursos[nombre] = (constructor(), None)
            except Exception as exc:  # noqa: BLE001 - la sonda reporta, no propaga
                _log.warning("no se pudo cargar %s: %s", nombre, exc)
                _recursos[nombre] = (None, exc)
        valor, error = _recursos[nombre]
    if error is not None:
        raise error
    return valor


def precargar(cfg: Config) -> None:
    """Carga embedder y voz al arrancar, no en la primera petición.

    Los errores quedan registrados en `_recursos` y los reporta `/salud`: un
    modelo que no carga no debe impedir que la página de diagnóstico se sirva,
    que es justo cuando más se necesita.
    """
    for nombre, constructor in (
        ("embedder", _cargar_embedder),
        ("voz", lambda: _cargar_voz(cfg)),
    ):
        try:
            _recurso(nombre, constructor)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Sondas
# ---------------------------------------------------------------------------


def sondear_indice(cfg: Config) -> Componente:
    """Abre el almacén de ChromaDB y cuenta documentos.

    Cero documentos **no** es un fallo hoy: el indexador todavía no existe y el
    directorio de semilla (`/opt/indice_base`) está vacío. El fallo es no poder
    abrir o no poder escribir el almacén.
    """
    datos: dict[str, Any] = {"ruta": str(cfg.almacen_indice)}
    try:
        import chromadb

        cfg.almacen_indice.mkdir(parents=True, exist_ok=True)
        cliente = chromadb.PersistentClient(path=str(cfg.almacen_indice))
        colecciones = [c.name for c in cliente.list_collections()]
        datos["colecciones"] = colecciones
        if cfg.coleccion_rag in colecciones:
            n = cliente.get_collection(cfg.coleccion_rag).count()
        else:
            n = 0
        datos["documentos"] = n
        datos["coleccion"] = cfg.coleccion_rag
        marcador = cfg.dir_indice / ".version_semilla"
        if marcador.is_file():
            datos["semilla"] = marcador.read_text(encoding="utf-8").strip()
        detalle = (
            f"{n} documentos en «{cfg.coleccion_rag}»"
            if n
            else "0 documentos (vacío: el indexador aún no existe)"
        )
        return Componente("indice", "Índice vectorial", "ok", detalle, datos=datos)
    except Exception as exc:  # noqa: BLE001
        return Componente(
            "indice",
            "Índice vectorial",
            "fallo",
            f"no se pudo abrir el almacén: {exc}",
            datos=datos,
        )


def sondear_embedder(cfg: Config) -> Componente:
    """Verifica que el embedder está cargado y produce vectores."""
    datos: dict[str, Any] = {
        "modelo": "all-MiniLM-L6-v2 (ONNX, CPU)",
        "cache": os.path.join(os.path.expanduser("~"), ".cache", "chroma"),
    }
    try:
        ef = _recurso("embedder", _cargar_embedder)
        vector = ef(["verificación de estado"])[0]
        datos["dimension"] = len(vector)
        return Componente(
            "embedder",
            "Embedder",
            "ok",
            f"cargado, {len(vector)} dimensiones",
            datos=datos,
        )
    except Exception as exc:  # noqa: BLE001
        return Componente(
            "embedder", "Embedder", "fallo", f"no carga: {exc}", datos=datos
        )


def sondear_voz(cfg: Config) -> Componente:
    """Verifica que el modelo de voz de Piper está en la imagen y carga."""
    datos: dict[str, Any] = {
        "modelo": cfg.modelo_voz,
        "ruta": str(cfg.ruta_modelo_voz),
    }
    if not cfg.ruta_modelo_voz.is_file():
        return Componente(
            "voz",
            "Voz (Piper)",
            "fallo",
            f"no existe el modelo en {cfg.ruta_modelo_voz}",
            datos=datos,
        )
    datos["tamano_mb"] = round(cfg.ruta_modelo_voz.stat().st_size / 1_048_576, 1)
    if cfg.ruta_config_voz.is_file():
        try:
            import json

            meta = json.loads(cfg.ruta_config_voz.read_text(encoding="utf-8"))
            datos["idioma"] = meta.get("language", {}).get("code")
            datos["frecuencia_hz"] = meta.get("audio", {}).get("sample_rate")
        except Exception:  # noqa: BLE001 - metadatos, no bloquean
            pass
    try:
        sintetizador = _recurso("voz", lambda: _cargar_voz(cfg))
        # El modelo de Piper no recibe texto sino identificadores de fonema, y
        # los suyos son los de espeak-ng. Comprobar solo que el .onnx carga
        # dejaría pasar el fallo real —biblioteca de fonemización ausente— hasta
        # el primer turno del paciente, que es cuando no se puede arreglar.
        ids, desconocidos = sintetizador.identificadores("prueba de voz")
        datos["voz_espeak"] = sintetizador.fonemizador.voz
        datos["fonemas_de_prueba"] = len(ids)
        if desconocidos:
            datos["simbolos_desconocidos"] = sorted(set(desconocidos))
        detalle = f"{cfg.modelo_voz} cargado"
        if datos.get("idioma"):
            detalle += f" ({datos['idioma']}, {datos.get('frecuencia_hz')} Hz)"
        detalle += f"; fonemizador espeak-ng «{sintetizador.fonemizador.voz}» responde"
        return Componente("voz", "Voz (Piper)", "ok", detalle, datos=datos)
    except OSError as exc:  # la biblioteca de espeak-ng no está en la imagen
        return Componente(
            "voz",
            "Voz (Piper)",
            "fallo",
            f"falta el fonemizador ({cfg.voz_biblioteca_espeak}): {exc}. "
            "La imagen debe instalar libespeak-ng1 y espeak-ng-data "
            "(ver Dockerfile); sin eso el modelo de voz no recibe entrada",
            datos=datos,
        )
    except Exception as exc:  # noqa: BLE001
        return Componente(
            "voz", "Voz (Piper)", "fallo", f"no carga: {exc}", datos=datos
        )


# ---------------------------------------------------------------------------
# Sondas de los dos servicios de inferencia.
#
# LLM y STT son servicios SEPARADOS, con su propio `base_url`, su propia clave
# y su propio modelo. Hasta el 2026-08-09 eran una sola sonda `sondear_groq`
# porque ambos corrían en Groq; el día que Groq retiró de su catálogo el modelo
# de lenguaje que exige la lista permitida del reto, esa fusión pasó a ser un
# error de diseño: obligaba a mover los dos servicios para mover uno.
# Ver docs/DECLARACION_MODELO.md.
#
# Ambas sondas hablan el MISMO protocolo (OpenAI-compatible), así que comparten
# el cuerpo: cambia el `base_url`, no el código. Esa es también la razón por la
# que la ruta principal y el fallback local son una sola integración.
# ---------------------------------------------------------------------------


def _listar_modelos(base_url: str, api_key: str, timeout_s: float) -> tuple[list[str], dict[str, Any]]:
    """`GET {base_url}/models` sobre un endpoint OpenAI-compatible.

    Devuelve los identificadores servidos y los datos de diagnóstico. Lanza si
    la respuesta no es 200 o no tiene la forma esperada: quien llama decide cómo
    reportarlo, porque el mismo error significa cosas distintas en el LLM (que
    puede ser local y sin clave) y en el STT (que siempre es remoto).
    """
    import httpx

    datos: dict[str, Any] = {}
    cabeceras = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    inicio = time.monotonic()
    respuesta = httpx.get(
        f"{base_url.rstrip('/')}/models", headers=cabeceras, timeout=timeout_s
    )
    datos["latencia_ms"] = int((time.monotonic() - inicio) * 1000)
    datos["codigo_http"] = respuesta.status_code
    respuesta.raise_for_status()
    cuerpo = respuesta.json()
    # Forma OpenAI: {"data": [{"id": …}, …]}. Algunos servidores locales
    # devuelven la lista pelada; se aceptan las dos.
    bruto = cuerpo.get("data", cuerpo) if isinstance(cuerpo, dict) else cuerpo
    modelos = [
        m.get("id", "") if isinstance(m, dict) else str(m) for m in (bruto or [])
    ]
    datos["n_modelos"] = len(modelos)
    return [m for m in modelos if m], datos


def _parecidos(modelo: str, disponibles: list[str], tope: int = 5) -> list[str]:
    """Modelos servidos que comparten algún fragmento con el pedido.

    Sirve para el caso real: el identificador está bien salvo por el sufijo del
    proveedor (`…-Instruct-Turbo` frente a `…-instruct`). Sin esta pista el
    operador solo sabe que falló, no qué escribir.
    """
    piezas = [t for t in modelo.lower().replace("/", "-").split("-") if len(t) > 2]
    if not piezas:
        return []
    puntuados = sorted(
        ((sum(p in d.lower() for p in piezas), d) for d in disponibles),
        key=lambda par: (-par[0], par[1]),
    )
    return [d for n, d in puntuados[:tope] if n >= max(2, len(piezas) // 2)]


def sondear_llm(cfg: Config) -> Componente:
    """Modelo de lenguaje: configuración, alcance y **existencia del modelo**.

    Comprobar que la clave es válida NO basta, y ese es el punto de esta sonda.
    El modo de falla que obligó a reescribirla fue exactamente «clave buena,
    modelo inexistente»: el proveedor responde 200 a `/models`, la clave es
    correcta, y la primera petición de inferencia falla con
    `model_decommissioned` — en la demostración, delante del jurado. Por eso se
    verifica que `LLM_MODELO` está en la lista que el proveedor sirve de verdad.
    """
    nombre = "LLM (modelo de lenguaje)"
    datos: dict[str, Any] = {
        "perfil": cfg.llm_perfil,
        "base_url": cfg.llm_base_url or "(sin definir)",
        "modelo": cfg.llm_modelo or "(sin definir)",
    }
    sufijo = f" · perfil «{cfg.llm_perfil}»"

    if not cfg.llm_modelo:
        return Componente(
            "llm",
            nombre,
            "fallo",
            "LLM_MODELO está vacío. Ponga en .env el identificador exacto del "
            "modelo: perfil remoto → LLM_MODELO=meta-llama/llama-3.1-70b-instruct; "
            "perfil local → LLM_MODELO=llama3.2:3b. No hay default a propósito: "
            "el que había apuntaba a un modelo que el proveedor apagó "
            "(docs/DECLARACION_MODELO.md)" + sufijo,
            datos=datos,
        )
    if not cfg.llm_base_url:
        return Componente(
            "llm",
            nombre,
            "fallo",
            "LLM_BASE_URL está vacío. Ponga la URL del endpoint "
            "OpenAI-compatible que sirve el modelo (ver .env.example)" + sufijo,
            datos=datos,
        )
    # Un servidor local (llama.cpp, Ollama) no pide clave; uno remoto sí. La
    # ausencia de clave solo es un fallo en el perfil remoto.
    if not cfg.hay_llm_api_key:
        if not cfg.llm_es_local:
            return Componente(
                "llm",
                nombre,
                "fallo",
                "LLM_API_KEY ausente: cree .env a partir de .env.example y "
                "pegue la clave del proveedor" + sufijo,
                datos=datos,
            )
        datos["clave"] = "no requerida (servidor local)"
    else:
        datos["clave"] = f"presente ({len(cfg.llm_api_key)} caracteres)"

    if not cfg.salud_comprobar_red:
        return Componente(
            "llm",
            nombre,
            "aviso",
            f"configurado con «{cfg.llm_modelo}»; sin verificar contra el "
            "proveedor (SALUD_COMPROBAR_RED=0)" + sufijo,
            datos=datos,
        )

    try:
        modelos, extra = _listar_modelos(
            cfg.llm_base_url, cfg.llm_api_key, cfg.salud_timeout_s
        )
        datos.update(extra)
    except Exception as exc:  # noqa: BLE001
        codigo = getattr(getattr(exc, "response", None), "status_code", None)
        datos["codigo_http"] = codigo
        if codigo in (401, 403):
            detalle = (
                f"el proveedor rechaza la clave (HTTP {codigo}): revísela en .env"
            )
        elif cfg.llm_es_local:
            detalle = (
                f"no se alcanza el servidor local en {cfg.llm_base_url}: {exc}. "
                "¿Está corriendo? `docker compose --profile local up -d`"
            )
        else:
            detalle = f"el proveedor no es alcanzable: {exc}"
        return Componente("llm", nombre, "fallo", detalle + sufijo, datos=datos)

    if cfg.llm_modelo in modelos:
        return Componente(
            "llm",
            nombre,
            "ok",
            f"«{cfg.llm_modelo}» servido y alcanzable "
            f"({datos.get('latencia_ms')} ms)" + sufijo,
            datos=datos,
        )

    pistas = _parecidos(cfg.llm_modelo, modelos)
    datos["coincidencias"] = pistas
    coincidencias = ", ".join(pistas) if pistas else "ninguna"
    return Componente(
        "llm",
        nombre,
        "fallo",
        f"el proveedor no sirve «{cfg.llm_modelo}» (responde con "
        f"{len(modelos)} modelos); modelos disponibles que coinciden: "
        f"{coincidencias}" + sufijo,
        datos=datos,
    )


def sondear_stt(cfg: Config) -> Componente:
    """Transcripción de voz. Servicio distinto del LLM, y sin afectar por G3.

    La compuerta G3 del reto restringe el modelo de **lenguaje**, no el de
    transcripción. `whisper-large-v3` en Groq sigue servido y no aparece en la
    tabla de deprecaciones del proveedor (consultada el 2026-08-09), así que
    este servicio se queda donde está.
    """
    nombre = "STT (transcripción)"
    datos: dict[str, Any] = {
        "base_url": cfg.stt_base_url,
        "modelo": cfg.stt_modelo,
    }
    sufijo = f" · {cfg.stt_modelo} en {cfg.stt_base_url}"

    if not cfg.hay_stt_api_key:
        return Componente(
            "stt",
            nombre,
            "fallo",
            "STT_API_KEY ausente: cree .env a partir de .env.example y pegue "
            "la clave de Groq" + sufijo,
            datos=datos,
        )
    datos["clave"] = f"presente ({len(cfg.stt_api_key)} caracteres)"

    if not cfg.salud_comprobar_red:
        return Componente(
            "stt",
            nombre,
            "aviso",
            "clave presente; sin verificar contra el proveedor "
            "(SALUD_COMPROBAR_RED=0)" + sufijo,
            datos=datos,
        )

    try:
        modelos, extra = _listar_modelos(
            cfg.stt_base_url, cfg.stt_api_key, cfg.salud_timeout_s
        )
        datos.update(extra)
    except Exception as exc:  # noqa: BLE001
        codigo = getattr(getattr(exc, "response", None), "status_code", None)
        datos["codigo_http"] = codigo
        detalle = (
            f"el proveedor rechaza la clave (HTTP {codigo}): revísela en .env"
            if codigo in (401, 403)
            else f"clave presente pero el proveedor no es alcanzable: {exc}"
        )
        return Componente("stt", nombre, "fallo", detalle + sufijo, datos=datos)

    if cfg.stt_modelo in modelos:
        return Componente(
            "stt",
            nombre,
            "ok",
            f"«{cfg.stt_modelo}» servido y alcanzable "
            f"({datos.get('latencia_ms')} ms)" + sufijo,
            datos=datos,
        )

    pistas = _parecidos(cfg.stt_modelo, modelos)
    datos["coincidencias"] = pistas
    coincidencias = ", ".join(pistas) if pistas else "ninguna"
    return Componente(
        "stt",
        nombre,
        "fallo",
        f"el proveedor no sirve «{cfg.stt_modelo}»; modelos disponibles que "
        f"coinciden: {coincidencias}" + sufijo,
        datos=datos,
    )


def sondear_dataset(cfg: Config) -> Componente:
    """Informativo y NO bloqueante: el dataset se monta `:ro` y puede faltar.

    El esqueleto tiene que arrancar sin él —hoy es el caso normal— así que su
    ausencia se reporta, no tumba el veredicto.
    """
    datos: dict[str, Any] = {"ruta": str(cfg.dir_dataset)}
    if not cfg.dir_dataset.is_dir():
        return Componente(
            "dataset",
            "Dataset (montaje ./dataset)",
            "aviso",
            "no montado; el esqueleto arranca igual",
            bloqueante=False,
            datos=datos,
        )
    try:
        entradas = sorted(p.name for p in cfg.dir_dataset.iterdir())
        datos["entradas"] = entradas[:20]
        datos["n_entradas"] = len(entradas)
        # Directorio vacío es AVISO, no OK: bajo Docker el bind siempre existe
        # —lo crea el runtime si falta—, así que «existe» no prueba nada. Lo
        # que distingue «el dataset está» de «se olvidó» es el contenido.
        if not entradas:
            return Componente(
                "dataset",
                "Dataset (montaje ./dataset)",
                "aviso",
                "montado pero vacío; el esqueleto arranca igual",
                bloqueante=False,
                datos=datos,
            )
        return Componente(
            "dataset",
            "Dataset (montaje ./dataset)",
            "ok",
            f"montado, {len(entradas)} entradas en la raíz",
            bloqueante=False,
            datos=datos,
        )
    except Exception as exc:  # noqa: BLE001
        return Componente(
            "dataset",
            "Dataset (montaje ./dataset)",
            "aviso",
            f"montado pero ilegible: {exc}",
            bloqueante=False,
            datos=datos,
        )


def sondear_escritura(cfg: Config) -> Componente:
    """Verifica que los directorios de escritura existen y aceptan escritura.

    Es el fallo silencioso clásico del bind mount de logs: el contenedor
    arranca, la página responde, y no se escribe ni una línea al disco del
    jurado.
    """
    problemas: list[str] = []
    datos: dict[str, Any] = {}
    for etiqueta, ruta in (
        ("logs", cfg.dir_logs),
        ("subidos", cfg.dir_subidos),
        ("indice", cfg.dir_indice),
        ("llamadas", cfg.dir_llamadas),
    ):
        datos[etiqueta] = str(ruta)
        try:
            ruta.mkdir(parents=True, exist_ok=True)
            prueba = ruta / ".escritura_prueba"
            prueba.write_text("ok", encoding="utf-8")
            prueba.unlink()
        except Exception as exc:  # noqa: BLE001
            problemas.append(f"{etiqueta}: {exc}")
    if problemas:
        return Componente(
            "escritura",
            "Directorios de escritura",
            "fallo",
            "; ".join(problemas),
            datos=datos,
        )
    return Componente(
        "escritura",
        "Directorios de escritura",
        "ok",
        "logs, subidos, índice y llamadas son escribibles",
        datos=datos,
    )


_SONDAS = (
    sondear_indice,
    sondear_embedder,
    sondear_voz,
    sondear_llm,
    sondear_stt,
    sondear_escritura,
    sondear_dataset,
)


# ---------------------------------------------------------------------------
# Informe
# ---------------------------------------------------------------------------

_cache: dict[str, Any] = {"t": 0.0, "informe": None}


def construir_informe(cfg: Config, *, forzar: bool = False) -> dict[str, Any]:
    """Corre todas las sondas y arma el informe.

    Memoizado unos segundos: el `healthcheck` de Docker pega cada 30 s y las
    sondas del LLM y del STT salen a la red. Sin caché, recargar la página
    varias veces dispararía otras tantas llamadas HTTP externas.
    """
    ahora = time.monotonic()
    if (
        not forzar
        and _cache["informe"] is not None
        and ahora - _cache["t"] < cfg.salud_cache_s
    ):
        return _cache["informe"]

    componentes = [sonda(cfg) for sonda in _SONDAS]
    listo = not any(c.hunde_el_veredicto for c in componentes)
    informe = {
        "veredicto": "LISTO" if listo else "NO LISTO",
        "listo": listo,
        "servicio": "voice-agent-postop",
        "instante": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "componentes": [c.a_json() for c in componentes],
        "_objetos": componentes,
    }
    _cache["t"] = ahora
    _cache["informe"] = informe
    return informe


# ---------------------------------------------------------------------------
# Presentación
# ---------------------------------------------------------------------------

_CSS = """
:root{--fondo:#f5f6f8;--tarjeta:#fff;--texto:#14171c;--tenue:#5b6472;
--borde:#dfe3e9;--ok:#0f7a3d;--ok-f:#e6f4ec;--aviso:#8a6100;--aviso-f:#fdf3e0;
--fallo:#a71d2a;--fallo-f:#fdecee;}
@media (prefers-color-scheme:dark){:root{--fondo:#0e1116;--tarjeta:#161b22;
--texto:#e6edf3;--tenue:#9aa4b2;--borde:#2b323c;--ok:#4ec97f;--ok-f:#10251a;
--aviso:#e3b341;--aviso-f:#2a2213;--fallo:#ff7b72;--fallo-f:#2d1618;}}
*{box-sizing:border-box}
body{margin:0;padding:2rem 1rem;background:var(--fondo);color:var(--texto);
font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:56rem;margin:0 auto}
h1{font-size:1.1rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;
color:var(--tenue);margin:0 0 1rem}
.veredicto{border-radius:14px;padding:2rem 1.5rem;text-align:center;
border:2px solid;margin-bottom:1.5rem}
.veredicto strong{display:block;font-size:clamp(3rem,14vw,6rem);line-height:1;
font-weight:800;letter-spacing:-.02em}
.veredicto span{display:block;margin-top:.75rem;font-size:1rem}
.listo{background:var(--ok-f);border-color:var(--ok);color:var(--ok)}
.nolisto{background:var(--fallo-f);border-color:var(--fallo);color:var(--fallo)}
table{width:100%;border-collapse:collapse;background:var(--tarjeta);
border:1px solid var(--borde);border-radius:12px;overflow:hidden}
th,td{padding:.75rem 1rem;text-align:left;border-bottom:1px solid var(--borde);
vertical-align:top}
th{font-size:.78rem;text-transform:uppercase;letter-spacing:.06em;color:var(--tenue)}
tr:last-child td{border-bottom:none}
.marca{display:inline-block;padding:.15rem .6rem;border-radius:999px;
font-size:.75rem;font-weight:700;letter-spacing:.04em}
.m-ok{background:var(--ok-f);color:var(--ok)}
.m-aviso{background:var(--aviso-f);color:var(--aviso)}
.m-fallo{background:var(--fallo-f);color:var(--fallo)}
.detalle{color:var(--tenue);font-size:.92rem}
.nombre{font-weight:600}
.opcional{font-size:.72rem;color:var(--tenue);font-weight:400}
footer{margin-top:1.5rem;color:var(--tenue);font-size:.85rem}
footer code{background:var(--tarjeta);border:1px solid var(--borde);
padding:.1rem .35rem;border-radius:5px}
a{color:inherit}
"""


def _fila(componente: Componente) -> str:
    e = html.escape
    opcional = (
        ' <span class="opcional">(no bloqueante)</span>'
        if not componente.bloqueante
        else ""
    )
    return (
        "<tr>"
        f'<td><span class="marca m-{componente.estado}">'
        f"{_ETIQUETA_ESTADO[componente.estado]}</span></td>"
        f'<td><span class="nombre">{e(componente.nombre)}</span>{opcional}</td>'
        f'<td class="detalle">{e(componente.detalle)}</td>'
        "</tr>"
    )


def informe_a_html(informe: dict[str, Any]) -> str:
    listo = informe["listo"]
    clase = "listo" if listo else "nolisto"
    subtitulo = (
        "Todos los componentes bloqueantes respondieron."
        if listo
        else "Al menos un componente bloqueante falló. Detalle abajo."
    )
    filas = "".join(_fila(c) for c in informe["_objetos"])
    e = html.escape
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Estado — voice-agent-postop</title>
<style>{_CSS}</style></head><body><main>
<h1>voice-agent-postop &middot; verificación de estado</h1>
<div class="veredicto {clase}"><strong>{e(informe["veredicto"])}</strong>
<span>{e(subtitulo)}</span></div>
<table><thead><tr><th>Estado</th><th>Componente</th><th>Detalle</th></tr></thead>
<tbody>{filas}</tbody></table>
<footer>
<p>Comprobado el {e(informe["instante"])}. Recargue la página para volver a sondear.</p>
<p>Versión en JSON: <code>curl -H "Accept: application/json"
http://localhost:8080/salud</code> o <a href="/salud?formato=json">/salud?formato=json</a>.</p>
<p><a href="/">Inicio</a></p>
</footer></main></body></html>"""


# `response_model=None`: el retorno es HTML o JSON según lo que pida el cliente,
# y FastAPI no puede derivar un modelo de respuesta de esa unión. La respuesta
# se construye a mano, así que no hay nada que validar.
@router.get("/salud", response_class=HTMLResponse, response_model=None)
def salud(request: Request) -> Response:
    """Devuelve HTML por defecto y JSON si el cliente lo pide.

    Siempre 200: el veredicto va en el cuerpo. Un 503 haría que `curl` sin
    `-f` no mostrara nada útil y que el navegador enseñara una página de error
    del propio navegador en vez de este diagnóstico.
    """
    cfg = obtener_config()
    forzar = request.query_params.get("refrescar") in {"1", "true", "si"}
    informe = construir_informe(cfg, forzar=forzar)
    publico = {k: v for k, v in informe.items() if not k.startswith("_")}

    quiere_json = (
        request.query_params.get("formato") == "json"
        or "application/json" in request.headers.get("accept", "").lower()
    )
    if quiere_json:
        return JSONResponse(publico)
    return HTMLResponse(informe_a_html(informe))
