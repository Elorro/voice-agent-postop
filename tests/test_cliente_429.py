"""El reintento ante HTTP 429 y, sobre todo, su presupuesto de espera.

Lo que estos tests protegen no es «que reintente»: es que NO reintente cuando
esperar costaría más latencia de la que el turno puede pagar. Un backoff sin
tope es indistinguible de un cuelgue desde el lado del paciente.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.contratos import ERROR, OK
from app.llm.cliente import ClienteLLM
from tests.apoyo_turno import config_de_prueba


def _respuesta_429(cabeceras: dict[str, str] | None = None, cuerpo: dict | None = None):
    return httpx.Response(
        429,
        headers=cabeceras or {},
        json=cuerpo if cuerpo is not None else {"error": {"message": "rate limit"}},
    )


def _respuesta_ok(texto: str = "listo"):
    return httpx.Response(
        200,
        json={
            "model": "modelo-de-prueba",
            "choices": [{"message": {"content": texto}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7},
        },
    )


def _cliente(tmp_path: Path, respuestas: list[httpx.Response], **cambios: str):
    """Cliente real con el transporte sustituido. No se toca `completar`."""
    cfg = config_de_prueba(tmp_path, LLM_BASE_URL="http://proveedor/v1", **cambios)
    cliente = ClienteLLM(cfg)
    pendientes = list(respuestas)
    vistas: list[httpx.Request] = []

    def manejador(peticion: httpx.Request) -> httpx.Response:
        vistas.append(peticion)
        return pendientes.pop(0)

    cliente._http = httpx.Client(transport=httpx.MockTransport(manejador))
    return cliente, vistas


def _sin_dormir(monkeypatch) -> list[float]:
    """Captura las esperas en vez de pagarlas: el test mide la decisión."""
    dormidas: list[float] = []
    monkeypatch.setattr("app.llm.cliente.time.sleep", lambda s: dormidas.append(s))
    return dormidas


def test_429_seguido_de_exito_reintenta_y_lo_registra(tmp_path, monkeypatch) -> None:
    dormidas = _sin_dormir(monkeypatch)
    cliente, vistas = _cliente(tmp_path, [_respuesta_429(), _respuesta_ok()])

    salida = cliente.completar([{"role": "user", "content": "x"}], timeout_ms=2500)

    assert salida.resultado == OK
    assert salida.reintentos_429 == 1
    assert len(vistas) == 2
    assert salida.espera_reintento_ms == pytest.approx(dormidas[0] * 1000)
    # El backoff sin `Retry-After` sale de la base con jitter de ±25%.
    assert 0.1875 <= dormidas[0] <= 0.3125


def test_se_agotan_los_intentos_y_devuelve_error(tmp_path, monkeypatch) -> None:
    _sin_dormir(monkeypatch)
    cliente, vistas = _cliente(tmp_path, [_respuesta_429() for _ in range(3)])

    salida = cliente.completar([{"role": "user", "content": "x"}], timeout_ms=2500)

    assert salida.resultado == ERROR
    # 3 intentos = 2 esperas. El tercer 429 no se espera, se reporta.
    assert len(vistas) == 3
    assert salida.reintentos_429 == 2


def test_retry_after_que_no_cabe_en_el_presupuesto_abandona_sin_dormir(
    tmp_path, monkeypatch
) -> None:
    """El caso del nivel gratuito: `Retry-After: 31` con 2000 ms de presupuesto.

    Es el test que justifica todo el diseño. Dormir 31 s dentro del turno es
    peor que degradar a plantilla, y recortar la espera a 2 s solo garantiza
    volver a chocar. La única respuesta correcta es rendirse en el acto.
    """
    dormidas = _sin_dormir(monkeypatch)
    cliente, vistas = _cliente(
        tmp_path, [_respuesta_429({"Retry-After": "31"}), _respuesta_ok()]
    )

    salida = cliente.completar([{"role": "user", "content": "x"}], timeout_ms=2500)

    assert salida.resultado == ERROR
    assert dormidas == []
    assert salida.reintentos_429 == 0
    assert len(vistas) == 1  # no hubo segunda petición


def test_retry_after_que_si_cabe_se_respeta_tal_cual(tmp_path, monkeypatch) -> None:
    dormidas = _sin_dormir(monkeypatch)
    cliente, _ = _cliente(
        tmp_path, [_respuesta_429({"Retry-After": "1"}), _respuesta_ok()]
    )

    salida = cliente.completar([{"role": "user", "content": "x"}], timeout_ms=2500)

    assert salida.resultado == OK
    # Sin jitter: el número lo puso el proveedor.
    assert dormidas == [1.0]


def test_retry_delay_del_cuerpo_de_google_tambien_se_lee(tmp_path, monkeypatch) -> None:
    """Google manda el retraso en `error.details`, no en la cabecera, aunque el
    endpoint sea el compatible con OpenAI."""
    dormidas = _sin_dormir(monkeypatch)
    cliente, _ = _cliente(
        tmp_path,
        [
            _respuesta_429(
                cuerpo={
                    "error": {
                        "message": "quota",
                        "details": [
                            {"@type": "type.googleapis.com/google.rpc.RetryInfo",
                             "retryDelay": "1.5s"},
                        ],
                    }
                }
            ),
            _respuesta_ok(),
        ],
    )

    salida = cliente.completar([{"role": "user", "content": "x"}], timeout_ms=2500)

    assert salida.resultado == OK
    assert dormidas == [1.5]


def test_el_error_envuelto_en_array_de_gemini_tambien_se_lee(
    tmp_path, monkeypatch
) -> None:
    """Regresión medida contra el endpoint real el 2026-08-10.

    Gemini devuelve `[{"error": {...}}]`, no `{"error": {...}}`. Con el parser
    dando por hecho el objeto, el `retryDelay: 33s` no se encontraba y el
    cliente dormía ~750 ms de backoff por invocación para volver a chocar.
    """
    dormidas = _sin_dormir(monkeypatch)
    cuerpo_gemini = [
        {
            "error": {
                "code": 429,
                "message": "You exceeded your current quota",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.Help", "links": []},
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo",
                     "retryDelay": "33s"},
                ],
            }
        }
    ]
    cliente, vistas = _cliente(
        tmp_path, [httpx.Response(429, json=cuerpo_gemini), _respuesta_ok()]
    )

    salida = cliente.completar([{"role": "user", "content": "x"}], timeout_ms=2500)

    # 33 s no caben en el presupuesto: se abandona sin dormir ni un ms.
    assert salida.resultado == ERROR
    assert dormidas == []
    assert len(vistas) == 1


def test_la_espera_cuenta_dentro_del_ms_del_span(tmp_path, monkeypatch) -> None:
    """`ms` es reloj de pared. Si la espera no contara, el span mentiría sobre
    lo que el paciente aguantó."""
    cliente, _ = _cliente(
        tmp_path, [_respuesta_429({"Retry-After": "0.2"}), _respuesta_ok()]
    )

    salida = cliente.completar([{"role": "user", "content": "x"}], timeout_ms=2500)

    assert salida.resultado == OK
    assert salida.ms >= 200.0
    assert salida.espera_reintento_ms == pytest.approx(200.0)


def test_los_tokens_de_razonamiento_se_derivan_del_total(tmp_path) -> None:
    """`completion_tokens` NO incluye el razonamiento; `total_tokens` sí.

    Medido el 2026-08-10 en `models/gemini-3.5-flash`: 13 + 9 declarados contra
    un total de 229. Reportar 9 tokens de salida donde se generaron 216 es
    subestimar el consumo veinte veces, y el costo con él.
    """
    respuesta = httpx.Response(
        200,
        json={
            "model": "modelo-que-razona",
            "choices": [{"message": {"content": "Here is"}}],
            "usage": {"prompt_tokens": 13, "completion_tokens": 9, "total_tokens": 229},
        },
    )
    cliente, _ = _cliente(tmp_path, [respuesta])

    salida = cliente.completar([{"role": "user", "content": "x"}], timeout_ms=2500)

    assert salida.tokens_in == 13
    assert salida.tokens_out == 9
    assert salida.tokens_razonamiento == 207
    assert salida.a_registro("extractor")["tokens_razonamiento"] == 207


def test_sin_razonamiento_el_campo_queda_en_none_y_no_se_inventa(tmp_path) -> None:
    """`total == prompt + completion` significa que no hubo razonamiento. No es
    lo mismo que «el proveedor no lo dijo», pero en ninguno de los dos casos se
    estima un número."""
    cliente, _ = _cliente(tmp_path, [_respuesta_ok()])

    salida = cliente.completar([{"role": "user", "content": "x"}], timeout_ms=2500)

    assert salida.tokens_razonamiento is None


def test_reasoning_effort_viaja_en_el_cuerpo_y_se_puede_omitir(tmp_path) -> None:
    cliente, vistas = _cliente(tmp_path, [_respuesta_ok()], LLM_RAZONAMIENTO="none")
    cliente.completar([{"role": "user", "content": "x"}], timeout_ms=2500)
    assert json.loads(vistas[0].content)["reasoning_effort"] == "none"

    # `omitir` = no se manda el campo, para proveedores que lo rechacen con 400.
    # Tiene que ser una palabra y no la cadena vacía: `_texto` colapsa el vacío
    # al valor por defecto, así que dejar la variable en blanco mandaría «none».
    cliente, vistas = _cliente(tmp_path, [_respuesta_ok()], LLM_RAZONAMIENTO="omitir")
    cliente.completar([{"role": "user", "content": "x"}], timeout_ms=2500)
    assert "reasoning_effort" not in json.loads(vistas[0].content)


def test_un_error_que_no_es_429_no_reintenta(tmp_path, monkeypatch) -> None:
    _sin_dormir(monkeypatch)
    cliente, vistas = _cliente(tmp_path, [httpx.Response(500, json={"error": "x"})])

    salida = cliente.completar([{"role": "user", "content": "x"}], timeout_ms=2500)

    assert salida.resultado == ERROR
    assert len(vistas) == 1
    assert salida.reintentos_429 == 0
