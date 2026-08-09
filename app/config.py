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
    coleccion_rag: str

    # --- voz ---
    dir_voces: Path
    modelo_voz: str

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
        coleccion_rag=_texto("COLECCION_RAG", "corpus_postop"),
        dir_voces=_ruta("VOCES_DIR", "/opt/voces"),
        modelo_voz=_texto("VOZ_MODELO", "es_MX-ald-medium.onnx"),
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
        salud_timeout_s=_flotante("SALUD_TIMEOUT_S", 6.0),
        salud_cache_s=_flotante("SALUD_CACHE_S", 10.0),
        salud_comprobar_red=_booleano("SALUD_COMPROBAR_RED", True),
        nivel_log=_texto("NIVEL_LOG", "INFO").upper(),
    )


@lru_cache(maxsize=1)
def obtener_config() -> Config:
    """Configuración del proceso, memoizada. Punto de acceso único."""
    return cargar_config()
