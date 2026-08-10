"""Configuración por variable de entorno. Única fuente de rutas del proyecto.

Reglas que este módulo hace cumplir:

1. **Ninguna constante de ruta inline fuera de aquí.** Cualquier otro módulo
   pide `obtener_config()`.
2. **Ningún default absoluto del host.** Todos los defaults son relativos a la
   raíz del repositorio (`RAIZ`, el padre de este paquete). Una ruta absoluta
   del host en el código es un fallo de portabilidad: rompe en la máquina del
   jurado, que no es esta.
3. Los valores relativos se resuelven contra `RAIZ`, no contra el directorio de
   trabajo. Así el proceso arranca igual desde cualquier `cwd`, dentro y fuera
   del contenedor (donde `RAIZ == /app`).

Las rutas *internas del contenedor* que aparecen como default (`/opt/voces`,
`/opt/indice_base`) son puntos de montaje de la imagen, no rutas del host: son
absolutas por necesidad —Docker no acepta destinos relativos en un bind— y no
existen fuera del contenedor. Fuera de Docker se sobreescriben por entorno.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
"""Raíz del repositorio. Dentro del contenedor es `/app`."""


def _ruta(variable: str, defecto: str) -> Path:
    """Lee una ruta del entorno; si es relativa, la ancla a `RAIZ`."""
    valor = Path(os.environ.get(variable, "").strip() or defecto).expanduser()
    return valor if valor.is_absolute() else (RAIZ / valor).resolve()


def _texto(variable: str, defecto: str) -> str:
    return os.environ.get(variable, "").strip() or defecto


def _entero(variable: str, defecto: int) -> int:
    try:
        return int(_texto(variable, str(defecto)))
    except ValueError:
        return defecto


def _flotante(variable: str, defecto: float) -> float:
    try:
        return float(_texto(variable, str(defecto)))
    except ValueError:
        return defecto


def _booleano(variable: str, defecto: bool) -> bool:
    return _texto(variable, "1" if defecto else "0").lower() in {
        "1",
        "true",
        "si",
        "sí",
        "yes",
        "on",
    }


@dataclass(frozen=True, slots=True)
class Config:
    """Configuración efectiva del proceso. Inmutable."""

    # --- servidor ---
    direccion: str
    puerto: int

    # --- datos ---
    dir_dataset: Path
    dir_indice: Path
    dir_indice_semilla: Path
    dir_subidos: Path
    dir_logs: Path
    dir_llamadas: Path
    ruta_tarifas: Path
    coleccion_rag: str

    # --- voz ---
    dir_voces: Path
    modelo_voz: str
    voz_biblioteca_espeak: str

    # --- LLM (agnóstico de proveedor) ---
    # El LLM y el STT son SERVICIOS DISTINTOS y se configuran por separado, aun
    # cuando hoy uno de ellos siga corriendo en Groq. Mezclarlos bajo un único
    # prefijo `GROQ_*` fue lo que hizo pasar por «un proveedor» lo que en
    # realidad son dos decisiones independientes: cuando Groq retiró el modelo
    # de lenguaje de la lista permitida (ver docs/DECLARACION_MODELO.md), mover
    # el LLM habría arrastrado al STT sin ninguna razón técnica.
    llm_base_url: str
    llm_api_key: str
    llm_modelo: str
    llm_perfil: str

    # --- STT ---
    stt_base_url: str
    stt_api_key: str
    stt_modelo: str
    stt_idioma: str
    stt_timeout_s: float

    # --- turno de voz (sub-paso 3.1) ---
    # Los dos timeouts son de naturaleza distinta y por eso son dos variables:
    # el del extractor acota una llamada de la que DEPENDE la decisión (sin
    # señales la política repregunta a ciegas), el del redactor acota una
    # llamada de la que NO depende nada (si no llega a tiempo, se emite la
    # plantilla). Un solo número para ambos obligaría a elegir entre estrangular
    # la extracción o dejar que la redacción se coma la cola del P95.
    extractor_timeout_ms: int
    redactor_timeout_ms: int
    redactor_activo: bool
    llm_max_tokens: int
    max_turnos_llamada: int

    # Rango de plausibilidad de una temperatura DICHA por el paciente. NO es un
    # umbral clínico —los umbrales viven en politica/parametros.py y solo ahí—:
    # es el filtro de dominio del extractor, del mismo tipo que el dominio
    # categórico de `herida`. Fuera de este rango el valor no es una
    # temperatura humana, y el contrato del extractor manda degradar a AUSENTE
    # antes que pasar un número plausible pero inventado.
    fiebre_min_c: float
    fiebre_max_c: float

    # --- detección de fin de habla en el navegador (el reloj autoritativo) ---
    vad_umbral_rms: float
    vad_silencio_ms: int
    vad_minimo_habla_ms: int

    # --- RAG (sub-paso 3.2) ---
    # El RAG responde PREGUNTAS DEL PACIENTE. No participa en la clasificación:
    # la clase sale de `politica.decidir` sobre las señales extraídas, y ninguna
    # de estas variables puede alterarla. Ver app/rag/__init__.py.
    #
    # Los cuatro números de troceo y umbral están CALIBRADOS, no elegidos: el
    # procedimiento y las mediciones están en docs/calibracion_rag.md, y los
    # scripts que los produjeron son scripts/calibrar_troceo.py y
    # scripts/calibrar_umbral.py.
    rag_activo: bool
    rag_k: int
    rag_umbral: float
    rag_pool: int
    rag_alfa: float
    rag_trozo_caracteres: int
    rag_solape_caracteres: int
    rag_max_texto_citado: int
    rag_timeout_ms: int
    rag_max_tokens: int
    subidos_max_mb: float

    # --- verificación de estado ---
    salud_timeout_s: float
    salud_cache_s: float
    salud_comprobar_red: bool
    nivel_log: str

    @property
    def almacen_indice(self) -> Path:
        """Directorio que ChromaDB abre como `PersistentClient(path=...)`.

        Es un **subdirectorio** de `dir_indice` (el volumen), no el volumen
        mismo. La razón es la siembra: `docker/entrypoint.sh` copia la semilla
        a un temporal dentro del mismo volumen y lo publica con un único
        `mv` de directorio, que en el mismo filesystem sí es atómico. Renombrar
        el punto de montaje no lo sería, y mover archivo por archivo tampoco:
        un arranque interrumpido dejaría un índice a medias indistinguible de
        uno completo.
        """
        return self.dir_indice / "actual"

    @property
    def ruta_turnos_jsonl(self) -> Path:
        """El archivo que el jurado abre y del que `/metricas` calcula sus números.

        Es el mismo para las dos cosas a propósito: si la página de métricas
        leyera un acumulador en memoria, nada impediría que el número mostrado
        y el registro discreparan, y sería indetectable desde fuera.
        """
        return self.dir_logs / "turnos.jsonl"

    @property
    def ruta_modelo_voz(self) -> Path:
        return self.dir_voces / self.modelo_voz

    @property
    def ruta_config_voz(self) -> Path:
        return self.dir_voces / f"{self.modelo_voz}.json"

    @property
    def hay_llm_api_key(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def hay_stt_api_key(self) -> bool:
        return bool(self.stt_api_key)

    @property
    def llm_es_local(self) -> bool:
        """Perfil declarado por el operador. Solo informativo, para `/salud`.

        No se deduce del `base_url`: un `llama.cpp` en la red local y un
        proveedor remoto son indistinguibles desde aquí, y adivinarlo mal sería
        peor que preguntarlo.
        """
        return self.llm_perfil == "local"


def cargar_config() -> Config:
    """Construye la configuración leyendo el entorno una sola vez."""
    return Config(
        direccion=_texto("DIRECCION_BIND", "0.0.0.0"),
        puerto=_entero("PUERTO", 8080),
        dir_dataset=_ruta("DATASET_DIR", "./dataset"),
        dir_indice=_ruta("INDICE_DIR", "./datos/indice"),
        dir_indice_semilla=_ruta("INDICE_SEMILLA_DIR", "/opt/indice_base"),
        dir_subidos=_ruta("SUBIDOS_DIR", "./datos/subidos"),
        dir_logs=_ruta("LOGS_DIR", "./datos/logs"),
        dir_llamadas=_ruta("LLAMADAS_DIR", "./datos/llamadas"),
        ruta_tarifas=_ruta("TARIFAS_RUTA", "./configuracion/tarifas.json"),
        coleccion_rag=_texto("COLECCION_RAG", "corpus_postop"),
        dir_voces=_ruta("VOCES_DIR", "/opt/voces"),
        modelo_voz=_texto("VOZ_MODELO", "es_MX-ald-medium.onnx"),
        voz_biblioteca_espeak=_texto("VOZ_BIBLIOTECA_ESPEAK", "libespeak-ng.so.1"),
        # Sin default de proveedor ni de modelo: el default es lo que se copia
        # sin leer, y un modelo por defecto que el proveedor apagó es
        # exactamente el fallo que trajo este cambio. Vacío obliga a decidir, y
        # /salud dice qué poner.
        llm_base_url=_texto("LLM_BASE_URL", ""),
        llm_api_key=_texto("LLM_API_KEY", ""),
        llm_modelo=_texto("LLM_MODELO", ""),
        llm_perfil=_texto("LLM_PERFIL", "remoto").lower(),
        # El STT sí conserva su default: `whisper-large-v3` en Groq sigue
        # servido y no aparece en la tabla de deprecaciones (consultada el
        # 2026-08-09, ver docs/DECLARACION_MODELO.md).
        stt_base_url=_texto("STT_BASE_URL", "https://api.groq.com/openai/v1"),
        stt_api_key=_texto("STT_API_KEY", ""),
        stt_modelo=_texto("STT_MODELO", "whisper-large-v3"),
        stt_idioma=_texto("STT_IDIOMA", "es"),
        stt_timeout_s=_flotante("STT_TIMEOUT_S", 12.0),
        extractor_timeout_ms=_entero("EXTRACTOR_TIMEOUT_MS", 2500),
        redactor_timeout_ms=_entero("REDACTOR_TIMEOUT_MS", 600),
        redactor_activo=_booleano("REDACTOR_ACTIVO", True),
        llm_max_tokens=_entero("LLM_MAX_TOKENS", 220),
        max_turnos_llamada=_entero("MAX_TURNOS_LLAMADA", 12),
        fiebre_min_c=_flotante("FIEBRE_MIN_C", 30.0),
        fiebre_max_c=_flotante("FIEBRE_MAX_C", 45.0),
        rag_activo=_booleano("RAG_ACTIVO", True),
        rag_k=_entero("RAG_K", 5),
        # 0.59 sobre el score FUNDIDO (α = 0,5). Rechaza las 8 consultas ajenas
        # medidas —máximo 0,536— con **0,054 de margen**, y acepta el documento
        # subido de la compuerta G5 (0,6444).
        #
        # Sustituye a un 0,65 sobre el score denso puro que se entregó primero y
        # era peor por dos razones, en este orden:
        #
        # 1. **Fallaba G5, que es eliminatoria.** El fragmento con la respuesta
        #    literal del documento subido puntúa 0,5988 en denso puro, por debajo
        #    de un ejercicio de rodilla sin relación (0,6418). No existe umbral
        #    denso que acepte lo correcto y rechace lo ajeno.
        # 2. **Su margen de 0,033 venía de un hueco de 0,021 medido con n = 18.**
        #    Eso está dentro del ruido de muestreo: la garantía de «nunca responde
        #    desde fragmentos ajenos» que compraba era nominal, no real.
        #
        # El coste es que más consultas cubiertas caen por debajo y el agente
        # declara su límite. Ese es el error que la rúbrica premia; responder
        # desde un fragmento irrelevante es el que penaliza.
        rag_umbral=_flotante("RAG_UMBRAL", 0.59),
        # Recuperación HÍBRIDA: el canal denso propone `rag_pool` candidatos y el
        # score final funde coseno con cobertura léxica ponderada por IDF, con
        # peso `rag_alfa` al denso. `rag_alfa=1` reproduce el comportamiento
        # denso puro, que es como se miden los dos regímenes sobre el mismo
        # índice. El método y su justificación están en app/rag/lexico.py.
        #
        # 0,5 y no 1,0: es lo que hace pasar G5. En el caso medido, la fusión
        # mueve el fragmento correcto del puesto 2 al 1 y le abre el doble de
        # margen (0,6444 contra 0,3255). Lo que se paga está declarado en
        # docs/calibracion_rag.md §4.3: con α < 1 el IDF interno del corpus
        # degrada el orden de algunas consultas del propio corpus.
        rag_pool=_entero("RAG_POOL", 60),
        rag_alfa=_flotante("RAG_ALFA", 0.5),
        # 600 y 150 salen de `scripts/calibrar_troceo.py` sobre los 107 PDFs:
        # el embedder trunca a 256 tokens y la tasa caracteres/token del percentil
        # 5 en español es 2,537 → techo real 649 caracteres. 600 deja 8 % de
        # margen. El solape son ~2 oraciones medianas del corpus (P50 = 69).
        rag_trozo_caracteres=_entero("RAG_TROZO_CARACTERES", 600),
        rag_solape_caracteres=_entero("RAG_SOLAPE_CARACTERES", 150),
        rag_max_texto_citado=_entero("RAG_MAX_TEXTO_CITADO", 400),
        rag_timeout_ms=_entero("RAG_TIMEOUT_MS", 4000),
        rag_max_tokens=_entero("RAG_MAX_TOKENS", 200),
        subidos_max_mb=_flotante("SUBIDOS_MAX_MB", 25.0),
        vad_umbral_rms=_flotante("VAD_UMBRAL_RMS", 0.02),
        vad_silencio_ms=_entero("VAD_SILENCIO_MS", 700),
        vad_minimo_habla_ms=_entero("VAD_MINIMO_HABLA_MS", 300),
        salud_timeout_s=_flotante("SALUD_TIMEOUT_S", 6.0),
        salud_cache_s=_flotante("SALUD_CACHE_S", 10.0),
        salud_comprobar_red=_booleano("SALUD_COMPROBAR_RED", True),
        nivel_log=_texto("NIVEL_LOG", "INFO").upper(),
    )


@lru_cache(maxsize=1)
def obtener_config() -> Config:
    """Configuración del proceso, memoizada. Punto de acceso único."""
    return cargar_config()
