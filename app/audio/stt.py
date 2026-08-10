"""Transcripción: `POST {STT_BASE_URL}/audio/transcriptions`.

Servicio distinto del LLM, con su propia clave y su propio modelo (ver
`app/config.py`). Habla el protocolo de OpenAI, así que el mismo código sirve
contra Groq, contra OpenAI o contra un `whisper.cpp` local que lo implemente.

El idioma va fijado (`STT_IDIOMA=es`): dejar que el modelo lo detecte agrega
latencia y abre la puerta a que una respuesta corta —«sí», «no»— se transcriba
como otro idioma.
"""

from __future__ import annotations

import logging
import time

import httpx

from app.config import Config
from app.contratos import ERROR, OK, TIMEOUT, SalidaSTT

_log = logging.getLogger(__name__)

__all__ = ["ClienteSTT"]


class ClienteSTT:
    """Cliente de transcripción con conexión persistente entre turnos."""

    def __init__(self, cfg: Config) -> None:
        self._base_url = cfg.stt_base_url.rstrip("/")
        self._api_key = cfg.stt_api_key
        self._modelo = cfg.stt_modelo
        self._idioma = cfg.stt_idioma
        self._timeout_s = cfg.stt_timeout_s
        self._http = httpx.Client(timeout=httpx.Timeout(cfg.stt_timeout_s))

    @property
    def modelo(self) -> str:
        return self._modelo

    def cerrar(self) -> None:
        self._http.close()

    def transcribir(
        self, audio: bytes, nombre: str = "turno.webm", segundos: float | None = None
    ) -> SalidaSTT:
        """Devuelve siempre; el fallo va en `resultado`, no en una excepción.

        Un turno sin transcripción no es un error del sistema: es un turno en el
        que el paciente no dijo nada aprovechable, y la política ya sabe qué
        hacer con eso (repreguntar, y escalar si se agota el presupuesto).
        """
        if not audio:
            return SalidaSTT("", 0.0, OK, segundos, "audio vacío")

        inicio = time.perf_counter()
        try:
            respuesta = self._http.post(
                f"{self._base_url}/audio/transcriptions",
                headers=(
                    {"Authorization": f"Bearer {self._api_key}"}
                    if self._api_key
                    else {}
                ),
                files={"file": (nombre, audio, "application/octet-stream")},
                data={
                    "model": self._modelo,
                    "language": self._idioma,
                    "response_format": "json",
                    "temperature": "0",
                },
                timeout=self._timeout_s,
            )
            respuesta.raise_for_status()
            datos = respuesta.json()
        except httpx.TimeoutException:
            ms = (time.perf_counter() - inicio) * 1000
            _log.warning("STT: timeout tras %.0f ms", ms)
            return SalidaSTT("", ms, TIMEOUT, segundos, "timeout")
        except Exception as exc:  # noqa: BLE001 - se reporta, no propaga
            ms = (time.perf_counter() - inicio) * 1000
            _log.warning("STT: fallo tras %.0f ms: %s", ms, exc)
            return SalidaSTT("", ms, ERROR, segundos, str(exc)[:200])

        ms = (time.perf_counter() - inicio) * 1000
        texto = str(datos.get("text", "")).strip() if isinstance(datos, dict) else ""
        return SalidaSTT(texto, ms, OK, segundos)
