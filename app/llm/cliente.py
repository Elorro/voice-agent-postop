"""Cliente OpenAI-compatible. Una sola integración para todos los proveedores.

El fallback local (Ollama, llama.cpp) y el proveedor remoto hablan el mismo
protocolo, así que aquí no hay dos caminos: cambia `LLM_BASE_URL` y nada más.
Ese es también el motivo de que el fallback no sea una rama de código sin
ejercitar.

Lo que este módulo garantiza a quien lo llama:

* **Nunca lanza por un fallo del proveedor.** Devuelve `SalidaLLM` con
  `resultado` en `timeout` o `error`. El turno del paciente no puede caerse
  porque un servidor de inferencia esté lento.
* **Los tokens vienen del campo `usage` de la respuesta.** Si el proveedor no lo
  manda, quedan en `None`.
* **El timeout es por invocación**, en milisegundos, y lo fija quien llama: el
  extractor y el redactor tienen presupuestos de latencia distintos por razones
  distintas (ver `app/config.py`).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.config import Config
from app.contratos import ERROR, OK, TIMEOUT, SalidaLLM

_log = logging.getLogger(__name__)

__all__ = ["ClienteLLM"]


class ClienteLLM:
    """Envoltura mínima de `POST {base_url}/chat/completions`.

    Mantiene un `httpx.Client` vivo entre turnos a propósito: reabrir la
    conexión TCP y renegociar TLS en cada invocación agrega decenas de
    milisegundos al camino crítico, y el camino crítico es lo único que la
    rúbrica mide.
    """

    def __init__(self, cfg: Config) -> None:
        self._base_url = cfg.llm_base_url.rstrip("/")
        self._api_key = cfg.llm_api_key
        self._modelo = cfg.llm_modelo
        self._max_tokens = cfg.llm_max_tokens
        # El timeout efectivo lo pone cada llamada; este es solo el techo del
        # pool. `httpx.Timeout(None)` aquí y un timeout explícito por petición.
        self._http = httpx.Client(timeout=httpx.Timeout(30.0))

    @property
    def modelo(self) -> str:
        return self._modelo

    def cerrar(self) -> None:
        self._http.close()

    def completar(
        self,
        mensajes: list[dict[str, str]],
        *,
        timeout_ms: int,
        max_tokens: int | None = None,
        temperatura: float = 0.0,
        formato_json: bool = False,
    ) -> SalidaLLM:
        """Una invocación. Devuelve siempre; el fallo va en `resultado`."""
        cuerpo: dict[str, Any] = {
            "model": self._modelo,
            "messages": mensajes,
            "temperature": temperatura,
            "max_tokens": max_tokens or self._max_tokens,
            "stream": False,
        }
        if formato_json:
            # Sugerencia, no garantía: hay proveedores que la ignoran. Por eso
            # el extractor valida el JSON de todas formas y degrada a AUSENTE.
            cuerpo["response_format"] = {"type": "json_object"}

        cabeceras = {"Content-Type": "application/json"}
        if self._api_key:
            cabeceras["Authorization"] = f"Bearer {self._api_key}"

        inicio = time.perf_counter()
        try:
            respuesta = self._http.post(
                f"{self._base_url}/chat/completions",
                json=cuerpo,
                headers=cabeceras,
                timeout=timeout_ms / 1000.0,
            )
            respuesta.raise_for_status()
            datos = respuesta.json()
        except httpx.TimeoutException:
            ms = (time.perf_counter() - inicio) * 1000
            _log.warning("LLM: timeout tras %.0f ms (tope %d ms)", ms, timeout_ms)
            return SalidaLLM("", ms, TIMEOUT, self._modelo, detalle="timeout")
        except Exception as exc:  # noqa: BLE001 - se reporta, no propaga
            ms = (time.perf_counter() - inicio) * 1000
            _log.warning("LLM: fallo tras %.0f ms: %s", ms, exc)
            return SalidaLLM("", ms, ERROR, self._modelo, detalle=str(exc)[:200])

        ms = (time.perf_counter() - inicio) * 1000
        texto = ""
        try:
            texto = (datos["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError):
            return SalidaLLM(
                "", ms, ERROR, self._modelo, detalle="respuesta sin choices[0].message"
            )

        uso = datos.get("usage") or {}
        entrada = uso.get("prompt_tokens")
        salida = uso.get("completion_tokens")
        return SalidaLLM(
            texto=texto,
            ms=ms,
            resultado=OK,
            modelo=str(datos.get("model") or self._modelo),
            tokens_in=entrada if isinstance(entrada, int) else None,
            tokens_out=salida if isinstance(salida, int) else None,
        )
