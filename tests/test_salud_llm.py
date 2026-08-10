"""`sondear_llm`: listar un modelo no es servirlo, y un parpadeo no es una caída.

Dos defectos distintos, los dos con el mismo síntoma —fila roja en `/salud`— y
consecuencias opuestas para quien la lee con el cronómetro corriendo:

* **F3.8.** Todo lo que no fuera 401/403 se reportaba como «el proveedor no es
  alcanzable». Un `429`, un `503` o un timeout de 6 s salían con la misma frase
  que un proveedor muerto. Medido sobre `datos/logs/app.log` del 2026-08-10:
  **12 de 456 sondeos (2,6 %)** no obtuvieron respuesta y el siguiente sí.
* **F3.9, el grave.** La sonda comprobaba que el proveedor **lista** el modelo.
  El 2026-08-10 eso dio LISTO, el contenedor `healthy`, y el LLM rechazaba el
  **100 %** de las inferencias con `HTTP 400 "llama3.2:3b" does not support
  thinking`. Comprobar presencia en vez de capacidad — el mismo patrón de la voz
  de Piper que cargaba y no podía hablar.

La distinción que estos tests fijan es la que decide qué hace el operador:
`transitorio` -> recargue; `no_infiere` y `modelo_inexistente` -> recargar no
sirve, hay algo que corregir.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app import salud
from tests.apoyo_turno import config_de_prueba

MODELO = "modelo-de-prueba"


@pytest.fixture(autouse=True)
def _sin_memoria_de_inferencia():
    """La verificación se memoiza por proceso; cada test parte de cero."""
    salud._inferencia_verificada.clear()
    yield
    salud._inferencia_verificada.clear()


def _cfg(tmp_path: Path, **cambios: str):
    base = {
        "LLM_BASE_URL": "http://proveedor/v1",
        "LLM_MODELO": MODELO,
        "LLM_API_KEY": "clave-de-prueba",
        "LLM_PERFIL": "remoto",
        "SALUD_COMPROBAR_RED": "1",
    }
    return config_de_prueba(tmp_path, **{**base, **cambios})


def _con_listado(monkeypatch, modelos: list[str]) -> None:
    monkeypatch.setattr(
        salud,
        "_listar_modelos",
        lambda *a, **k: (modelos, {"latencia_ms": 12, "n_modelos": len(modelos)}),
    )


def _con_inferencia(monkeypatch, respuesta) -> list[httpx.Request]:
    """Sustituye el POST de la inferencia de prueba. Devuelve lo que se envió.

    Se parchea `httpx.post` y no un atributo del módulo porque `salud` importa
    `httpx` perezosamente, dentro de la función: no hay nada que parchear en el
    espacio de nombres del módulo hasta que la sonda corre.
    """
    vistas: list[httpx.Request] = []

    def falso_post(url, *, json=None, headers=None, timeout=None):
        vistas.append(httpx.Request("POST", url, json=json, headers=headers))
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta

    monkeypatch.setattr(httpx, "post", falso_post)
    return vistas


def _respuesta_ok():
    return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})


# --------------------------------------------------------------------------- #
# F3.9 — la inferencia real
# --------------------------------------------------------------------------- #
def test_un_modelo_listado_que_rechaza_la_inferencia_hunde_el_veredicto(
    tmp_path, monkeypatch
) -> None:
    """El caso exacto del perfil C: `/models` 200, inferencia 400."""
    _con_listado(monkeypatch, [MODELO])
    _con_inferencia(
        monkeypatch,
        httpx.Response(
            400,
            json={"error": {"message": f'"{MODELO}" does not support thinking'}},
        ),
    )

    componente = salud.sondear_llm(_cfg(tmp_path, LLM_RAZONAMIENTO="low"))

    assert componente.estado == "fallo"
    assert componente.hunde_el_veredicto
    assert componente.datos["diagnostico"] == "no_infiere"
    # El mensaje del proveedor es lo único que dice qué pasó: tiene que llegar.
    assert "does not support thinking" in componente.detalle
    # Y la frase que separa este caso de un parpadeo.
    assert "recargar no lo arregla" in componente.detalle.lower()
    # La pista accionable, porque la causa es un parámetro del propio .env.
    assert "LLM_RAZONAMIENTO" in componente.detalle


def test_la_inferencia_de_prueba_manda_el_mismo_reasoning_effort_que_el_turno(
    tmp_path, monkeypatch
) -> None:
    """Sin esto la sonda no habría cazado nada.

    El parámetro que el proveedor rechazaba era justamente `reasoning_effort`.
    Una inferencia de prueba que no lo mandara pasaría con un LLM que el turno
    no puede usar, que es el defecto original con un paso más.
    """
    _con_listado(monkeypatch, [MODELO])
    vistas = _con_inferencia(monkeypatch, _respuesta_ok())

    salud.sondear_llm(_cfg(tmp_path, LLM_RAZONAMIENTO="low"))

    import json as _json

    cuerpo = _json.loads(vistas[0].content)
    assert cuerpo["reasoning_effort"] == "low"
    assert cuerpo["model"] == MODELO
    # Y el resto de los campos opcionales del extractor, por la misma razón: uno
    # que la sonda no replique es uno que el proveedor puede rechazar en el turno
    # después de haber aprobado la comprobación.
    assert cuerpo["response_format"] == {"type": "json_object"}


def test_con_la_variable_vacia_la_inferencia_de_prueba_tampoco_manda_la_clave(
    tmp_path, monkeypatch
) -> None:
    _con_listado(monkeypatch, [MODELO])
    vistas = _con_inferencia(monkeypatch, _respuesta_ok())

    salud.sondear_llm(_cfg(tmp_path, LLM_RAZONAMIENTO=""))

    import json as _json

    assert "reasoning_effort" not in _json.loads(vistas[0].content)


def test_un_200_sin_choices_no_cuenta_como_inferencia(tmp_path, monkeypatch) -> None:
    """El modo de falla del turno 5 de F3.4, un nivel más abajo."""
    _con_listado(monkeypatch, [MODELO])
    _con_inferencia(monkeypatch, httpx.Response(200, json={"choices": []}))

    componente = salud.sondear_llm(_cfg(tmp_path))

    assert componente.estado == "fallo"
    assert componente.datos["diagnostico"] == "no_infiere"


def test_la_inferencia_pasa_y_el_componente_queda_ok(tmp_path, monkeypatch) -> None:
    _con_listado(monkeypatch, [MODELO])
    _con_inferencia(monkeypatch, _respuesta_ok())

    componente = salud.sondear_llm(_cfg(tmp_path))

    assert componente.estado == "ok"
    assert componente.datos["diagnostico"] == "ok"
    assert "inferencia de prueba" in componente.detalle


def test_en_modo_arranque_la_inferencia_no_se_repite_tras_el_primer_exito(
    tmp_path, monkeypatch
) -> None:
    """El coste está acotado: una inferencia por proceso en el camino feliz."""
    _con_listado(monkeypatch, [MODELO])
    vistas = _con_inferencia(monkeypatch, _respuesta_ok())
    cfg = _cfg(tmp_path, SALUD_INFERENCIA="arranque")

    for _ in range(5):
        assert salud.sondear_llm(cfg).estado == "ok"

    assert len(vistas) == 1


def test_un_fallo_de_inferencia_si_se_reintenta_en_cada_sondeo(
    tmp_path, monkeypatch
) -> None:
    """Es el estado del que se quiere salir: no se puede memoizar el fallo."""
    _con_listado(monkeypatch, [MODELO])
    vistas = _con_inferencia(
        monkeypatch, httpx.Response(400, json={"error": {"message": "no"}})
    )
    cfg = _cfg(tmp_path, SALUD_INFERENCIA="arranque")

    for _ in range(3):
        assert salud.sondear_llm(cfg).estado == "fallo"

    assert len(vistas) == 3


def test_se_puede_desactivar(tmp_path, monkeypatch) -> None:
    """`SALUD_INFERENCIA=0` para quien no quiera pagar ni un token."""
    _con_listado(monkeypatch, [MODELO])
    vistas = _con_inferencia(monkeypatch, _respuesta_ok())

    componente = salud.sondear_llm(_cfg(tmp_path, SALUD_INFERENCIA="0"))

    assert componente.estado == "ok"
    assert vistas == []


def test_sin_red_no_se_intenta_ninguna_inferencia(tmp_path, monkeypatch) -> None:
    vistas = _con_inferencia(monkeypatch, _respuesta_ok())

    componente = salud.sondear_llm(_cfg(tmp_path, SALUD_COMPROBAR_RED="0"))

    assert componente.estado == "aviso"
    assert vistas == []


def test_un_timeout_de_la_inferencia_es_transitorio_no_un_modelo_roto(
    tmp_path, monkeypatch
) -> None:
    """En el perfil C la PRIMERA inferencia carga el modelo: eso son segundos.

    Reportarlo como «este modelo no sirve» mandaría a cambiar `.env` cuando lo
    único que pasa es que Ollama está cargando pesos.
    """
    _con_listado(monkeypatch, [MODELO])
    _con_inferencia(
        monkeypatch,
        httpx.ReadTimeout("timed out", request=httpx.Request("POST", "http://x")),
    )

    componente = salud.sondear_llm(_cfg(tmp_path))

    assert componente.estado == "fallo"
    assert componente.datos["diagnostico"] == "transitorio"
    assert "recargue" in componente.detalle.lower()


# --------------------------------------------------------------------------- #
# F3.8 — el sondeo de /models
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "excepcion",
    [
        httpx.ReadTimeout("timed out", request=httpx.Request("GET", "http://x")),
        httpx.ConnectError("dns", request=httpx.Request("GET", "http://x")),
        httpx.HTTPStatusError(
            "429",
            request=httpx.Request("GET", "http://x"),
            response=httpx.Response(429, request=httpx.Request("GET", "http://x")),
        ),
        httpx.HTTPStatusError(
            "503",
            request=httpx.Request("GET", "http://x"),
            response=httpx.Response(503, request=httpx.Request("GET", "http://x")),
        ),
    ],
)
def test_los_fallos_pasajeros_se_reportan_como_transitorios(
    tmp_path, monkeypatch, excepcion
) -> None:
    def falla(*a, **k):
        raise excepcion

    monkeypatch.setattr(salud, "_listar_modelos", falla)

    componente = salud.sondear_llm(_cfg(tmp_path))

    assert componente.estado == "fallo"
    assert componente.datos["diagnostico"] == "transitorio"
    assert "no se pudo verificar ahora" in componente.detalle
    # Lo que NO puede decir: que el modelo no exista.
    assert "NO dice que" in componente.detalle


def test_una_clave_rechazada_no_es_transitoria(tmp_path, monkeypatch) -> None:
    peticion = httpx.Request("GET", "http://x")

    def falla(*a, **k):
        raise httpx.HTTPStatusError(
            "401", request=peticion, response=httpx.Response(401, request=peticion)
        )

    monkeypatch.setattr(salud, "_listar_modelos", falla)

    componente = salud.sondear_llm(_cfg(tmp_path))

    assert componente.datos["diagnostico"] == "clave"


def test_un_modelo_que_el_proveedor_no_lista_dice_que_recargar_no_sirve(
    tmp_path, monkeypatch
) -> None:
    _con_listado(monkeypatch, ["otro-modelo", "modelo-parecido-de-prueba"])

    componente = salud.sondear_llm(_cfg(tmp_path))

    assert componente.estado == "fallo"
    assert componente.datos["diagnostico"] == "modelo_inexistente"
    assert "recargar no lo arregla" in componente.detalle.lower()
