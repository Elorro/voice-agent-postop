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

Reintento ante HTTP 429, y por qué lleva presupuesto
----------------------------------------------------
El nivel gratuito de Gemini corta en ~10-15 peticiones por minuto. Sin reintento,
una ráfaga deja al extractor sin extraer y la llamada entera clasifica por
AGOTAMIENTO con las seis señales en `null` — verificado el 2026-08-10.

Pero un reintento con espera está en el camino crítico del paciente. Dormir tres
segundos dentro de un turno es PEOR que degradar a plantilla: el paciente oye
silencio. Por eso el backoff no es «duerme lo que diga el proveedor», sino:

* **Tope de intentos** (`LLM_MAX_INTENTOS`, 3 por defecto): 3 intentos = 2 esperas.
* **Presupuesto total de espera** (`LLM_ESPERA_429_MS`): cuánto se puede dormir en
  TODA la invocación. Si la siguiente espera no cabe, se abandona en el acto y se
  devuelve el 429. No se recorta la espera para que quepa: dormir menos de lo que
  el proveedor pidió es gastar latencia para volver a chocar.
* **`Retry-After` manda sobre el backoff** cuando viene, en cabecera o en el
  `retryDelay` que Google mete en el cuerpo del error. El backoff exponencial es
  el respaldo para cuando el proveedor no dice nada.

Con los valores por defecto (250 ms de base, 2000 ms de presupuesto) este
mecanismo NO salva una cuota por minuto agotada: un `Retry-After: 31` no cabe en
2000 ms y se abandona de inmediato. Eso es deliberado. Salva la ráfaga corta —dos
peticiones que se pisan— y para la cuota agotada la respuesta correcta no es
esperar dentro del turno, es espaciar las llamadas (`--pausa-ms`) o cambiar de
perfil.
"""

from __future__ import annotations

import email.utils
import logging
import random
import time
from typing import Any

import httpx

from app.config import Config
from app.contratos import ERROR, OK, TIMEOUT, SalidaLLM

_log = logging.getLogger(__name__)

__all__ = ["ClienteLLM"]

# Proporción de jitter sobre la espera calculada. Sin jitter, varios turnos que
# chocan con el mismo 429 reintentan sincronizados y vuelven a chocar juntos.
# No se aplica a `Retry-After`: ahí el número lo puso el proveedor.
_JITTER = 0.25


def _segundos_de_retry_after(valor: str) -> float | None:
    """`Retry-After` admite segundos o fecha HTTP (RFC 9110 §10.2.3)."""
    valor = valor.strip()
    try:
        return max(0.0, float(valor))
    except ValueError:
        pass
    fecha = email.utils.parsedate_to_datetime(valor)
    if fecha is None:
        return None
    return max(0.0, fecha.timestamp() - time.time())


def _mensaje_del_cuerpo(respuesta: httpx.Response | None) -> str:
    """`error.message` del cuerpo, en las dos formas que usan los proveedores.

    Objeto `{"error": {...}}` (OpenAI, Ollama) y ARRAY `[{"error": {...}}]`
    (Gemini). Devuelve cadena vacía si no hay nada legible: esto es diagnóstico,
    nunca contrato, y no puede lanzar.
    """
    if respuesta is None:
        return ""
    try:
        cuerpo = respuesta.json()
    except Exception:  # noqa: BLE001
        return (getattr(respuesta, "text", "") or "").strip()[:200]
    if isinstance(cuerpo, list):
        cuerpo = next((e for e in cuerpo if isinstance(e, dict) and "error" in e), {})
    if not isinstance(cuerpo, dict):
        return ""
    error = cuerpo.get("error")
    if isinstance(error, dict):
        return str(error.get("message", ""))[:200]
    return str(error or "")[:200]


def _espera_pedida(respuesta: httpx.Response) -> float | None:
    """Segundos que el proveedor pide esperar, o `None` si no lo dice.

    Se miran dos sitios porque los proveedores no coinciden: la cabecera
    estándar, y el `retryDelay` que Google adjunta en `error.details` de su
    respuesta 429 aunque el endpoint sea el compatible con OpenAI.

    OJO con la forma del cuerpo: Gemini devuelve el error envuelto en un ARRAY
    (`[{"error": {...}}]`), no en el objeto que devuelve todo el mundo. Medido
    el 2026-08-10 contra `v1beta/openai`, y no es un detalle cosmético: dar por
    hecho el objeto hacía que el `retryDelay: 33s` no se encontrara nunca y que
    el cliente cayera al backoff exponencial, durmiendo ~750 ms por invocación
    para volver a chocar con un 429 que pedía 33 s. Nunca se envía cabecera
    `Retry-After`, así que este camino es el único que hay.
    """
    cabecera = respuesta.headers.get("Retry-After")
    if cabecera:
        segundos = _segundos_de_retry_after(cabecera)
        if segundos is not None:
            return segundos
    try:
        cuerpo = respuesta.json()
    except Exception:  # noqa: BLE001 - el cuerpo de un error no es contrato
        return None
    if isinstance(cuerpo, list):
        cuerpo = next((e for e in cuerpo if isinstance(e, dict) and "error" in e), None)
    if not isinstance(cuerpo, dict):
        return None
    detalles = ((cuerpo.get("error") or {}) if isinstance(cuerpo.get("error"), dict) else {}).get("details")
    if not isinstance(detalles, list):
        return None
    for detalle in detalles:
        retraso = (detalle or {}).get("retryDelay") if isinstance(detalle, dict) else None
        if isinstance(retraso, str) and retraso.endswith("s"):
            try:
                return max(0.0, float(retraso[:-1]))
            except ValueError:
                continue
    return None


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
        self._max_intentos = max(1, cfg.llm_max_intentos)
        self._espera_429_ms = max(0, cfg.llm_espera_429_ms)
        self._backoff_base_ms = max(1, cfg.llm_backoff_base_ms)
        self._razonamiento = cfg.llm_razonamiento.strip()
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
        if self._razonamiento:
            # `reasoning_effort: none` apaga el razonamiento de los modelos que
            # lo traen encendido. NO es una optimización opcional: con Gemini 3.5
            # Flash el razonamiento consume `max_tokens` SIN aparecer en
            # `completion_tokens`, así que con los 220 del proyecto se comía 207
            # y dejaba 13 para la respuesta. Resultado: `finish_reason: length`,
            # un JSON cortado a medias y `json_invalido` en TODAS las
            # extracciones (medido el 2026-08-10). El extractor no necesita que
            # el modelo piense: necesita que copie valores y citas del texto.
            #
            # Se omite el campo si la variable va vacía, para no mandarle un
            # parámetro desconocido a un proveedor que lo rechace con 400.
            cuerpo["reasoning_effort"] = self._razonamiento

        cabeceras = {"Content-Type": "application/json"}
        if self._api_key:
            cabeceras["Authorization"] = f"Bearer {self._api_key}"

        inicio = time.perf_counter()
        # `ms` de la SalidaLLM mide RELOJ DE PARED, esperas incluidas. Es lo que
        # el paciente aguanta, y por tanto lo único que puede entrar en un span.
        reintentos_429 = 0
        espera_total_ms = 0.0
        presupuesto_restante_ms = float(self._espera_429_ms)

        for intento in range(1, self._max_intentos + 1):
            try:
                respuesta = self._http.post(
                    f"{self._base_url}/chat/completions",
                    json=cuerpo,
                    headers=cabeceras,
                    timeout=timeout_ms / 1000.0,
                )
                if respuesta.status_code == 429 and intento < self._max_intentos:
                    pedida = _espera_pedida(respuesta)
                    if pedida is not None:
                        espera_ms = pedida * 1000.0
                        origen = "Retry-After"
                    else:
                        base = self._backoff_base_ms * (2 ** (intento - 1))
                        espera_ms = base * (1.0 + random.uniform(-_JITTER, _JITTER))
                        origen = "backoff"
                    if espera_ms > presupuesto_restante_ms:
                        # No se recorta: dormir menos de lo pedido es gastar
                        # latencia del turno para volver a chocar con el 429.
                        _log.warning(
                            "LLM: 429 en intento %d/%d; %s pide %.0f ms y solo quedan "
                            "%.0f ms de presupuesto — se abandona",
                            intento, self._max_intentos, origen, espera_ms,
                            presupuesto_restante_ms,
                        )
                    else:
                        _log.info(
                            "LLM: 429 en intento %d/%d; espera %.0f ms (%s)",
                            intento, self._max_intentos, espera_ms, origen,
                        )
                        time.sleep(espera_ms / 1000.0)
                        espera_total_ms += espera_ms
                        presupuesto_restante_ms -= espera_ms
                        reintentos_429 += 1
                        continue
                respuesta.raise_for_status()
                datos = respuesta.json()
            except httpx.TimeoutException:
                ms = (time.perf_counter() - inicio) * 1000
                _log.warning("LLM: timeout tras %.0f ms (tope %d ms)", ms, timeout_ms)
                return SalidaLLM(
                    "", ms, TIMEOUT, self._modelo, detalle="timeout",
                    reintentos_429=reintentos_429, espera_reintento_ms=espera_total_ms,
                )
            except Exception as exc:  # noqa: BLE001 - se reporta, no propaga
                ms = (time.perf_counter() - inicio) * 1000
                # El cuerpo del error, cuando lo hay, es lo ÚNICO que dice qué
                # pasó: httpx solo aporta «Client error '400 Bad Request'». El
                # caso que lo obligó (F3.9): Ollama respondía `"llama3.2:3b" does
                # not support thinking` y esa frase no llegaba a ningún log, así
                # que el perfil C aparecía roto sin causa visible.
                motivo = _mensaje_del_cuerpo(getattr(exc, "response", None))
                detalle = f"{exc}"
                if motivo:
                    detalle = f"{exc} — el proveedor dice: {motivo}"
                _log.warning("LLM: fallo tras %.0f ms: %s", ms, detalle)
                return SalidaLLM(
                    "", ms, ERROR, self._modelo, detalle=detalle[:300],
                    reintentos_429=reintentos_429, espera_reintento_ms=espera_total_ms,
                )
            break

        ms = (time.perf_counter() - inicio) * 1000
        texto = ""
        try:
            texto = (datos["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError):
            return SalidaLLM(
                "", ms, ERROR, self._modelo, detalle="respuesta sin choices[0].message",
                reintentos_429=reintentos_429, espera_reintento_ms=espera_total_ms,
            )

        uso = datos.get("usage") or {}
        entrada = uso.get("prompt_tokens")
        salida = uso.get("completion_tokens")
        total = uso.get("total_tokens")
        # Los tokens de razonamiento no vienen en `completion_tokens` pero sí
        # están dentro de `total_tokens`, y sí se cobran. La resta es aritmética
        # sobre lo que manda el proveedor, no una estimación: si `total` no
        # viene, esto queda en None y nadie inventa un número.
        razonamiento: int | None = None
        if (
            isinstance(total, int)
            and isinstance(entrada, int)
            and isinstance(salida, int)
            and total > entrada + salida
        ):
            razonamiento = total - entrada - salida
        return SalidaLLM(
            texto=texto,
            ms=ms,
            resultado=OK,
            modelo=str(datos.get("model") or self._modelo),
            tokens_in=entrada if isinstance(entrada, int) else None,
            tokens_out=salida if isinstance(salida, int) else None,
            reintentos_429=reintentos_429,
            espera_reintento_ms=espera_total_ms,
            tokens_razonamiento=razonamiento,
        )
