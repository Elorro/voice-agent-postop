"""`reasoning_effort`: cuándo viaja en el cuerpo y cuándo NO.

Por qué merece un archivo propio. El parámetro entró en F3.3 para apagar el
razonamiento de Gemini —sin él, el modelo se comía `max_tokens` pensando y el
extractor devolvía JSON cortado en TODAS las extracciones— y quedó en `low` en
F3.4. Ollama lo rechaza:

    POST /v1/chat/completions  {"model": "llama3.2:3b", "reasoning_effort": "low"}
    -> HTTP 400 {"error": {"message": "\"llama3.2:3b\" does not support thinking"}}

Es decir: **el arreglo del perfil A rompió el perfil C**, y no se detectó porque
desde entonces solo se midió con Gemini. Estos tests fijan la regla que lo
impide en las dos direcciones — que el campo viaje cuando se pide, y que **no**
viaje cuando se deja la variable vacía— para que ningún perfil vuelva a romper al
otro en silencio.

Medido contra el Ollama del perfil C el 2026-08-10: `low` da 400, `none` da 200
y ausente da 200. El valor que rompe es `low`, no el parámetro en sí; por eso la
defensa es poder suprimirlo desde `.env` y no confiar en que `none` se acepte.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.config import cargar_config
from app.llm.cliente import ClienteLLM
from tests.apoyo_turno import config_de_prueba

VARIABLE = "LLM_RAZONAMIENTO"


def _cuerpo_enviado(tmp_path: Path, **cambios: str) -> dict:
    """Manda una invocación real y devuelve el JSON que salió por el transporte."""
    cfg = config_de_prueba(
        tmp_path,
        LLM_BASE_URL="http://proveedor/v1",
        LLM_MODELO="modelo-de-prueba",
        **cambios,
    )
    cliente = ClienteLLM(cfg)
    vistas: list[httpx.Request] = []

    def manejador(peticion: httpx.Request) -> httpx.Response:
        vistas.append(peticion)
        return httpx.Response(
            200,
            json={
                "model": "modelo-de-prueba",
                "choices": [{"message": {"content": "OK"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            },
        )

    cliente._http = httpx.Client(transport=httpx.MockTransport(manejador))
    cliente.completar([{"role": "user", "content": "x"}], timeout_ms=2500)
    assert len(vistas) == 1
    return json.loads(vistas[0].content)


# --------------------------------------------------------------------------- #
# La regla que pide el perfil C
# --------------------------------------------------------------------------- #
def test_con_la_variable_vacia_la_clave_no_aparece_en_el_cuerpo(tmp_path) -> None:
    """`LLM_RAZONAMIENTO=` en `.env` -> el campo NO viaja. Es el perfil C."""
    cuerpo = _cuerpo_enviado(tmp_path, LLM_RAZONAMIENTO="")

    assert "reasoning_effort" not in cuerpo
    # Y el resto del cuerpo sigue completo: suprimir el campo no es mandar menos.
    assert cuerpo["model"] and cuerpo["messages"] and cuerpo["max_tokens"]


def test_solo_espacios_cuenta_como_vacio(tmp_path) -> None:
    """`LLM_RAZONAMIENTO=   ` es lo mismo que vacía, no un valor con espacios."""
    assert "reasoning_effort" not in _cuerpo_enviado(tmp_path, LLM_RAZONAMIENTO="   ")


def test_omitir_sigue_funcionando_como_alias(tmp_path) -> None:
    """Está publicado en docs/DECLARACION_MODELO.md §5 y en .env.example.

    Romperlo obligaría a quien siguió esa tabla a descubrirlo con un 400 delante
    del jurado, que es exactamente el fallo que este cambio existe para evitar.
    """
    assert "reasoning_effort" not in _cuerpo_enviado(tmp_path, LLM_RAZONAMIENTO="omitir")


# --------------------------------------------------------------------------- #
# La regla que pide el perfil A: el campo tiene que seguir viajando
# --------------------------------------------------------------------------- #
def test_con_un_valor_explicito_la_clave_viaja_tal_cual(tmp_path) -> None:
    cuerpo = _cuerpo_enviado(tmp_path, LLM_RAZONAMIENTO="low")
    assert cuerpo["reasoning_effort"] == "low"


def test_sin_la_variable_en_el_entorno_el_default_sigue_siendo_none(
    tmp_path, monkeypatch
) -> None:
    """Ausente ≠ vacía, y la diferencia es deliberada.

    Ausente conserva el default histórico `none`, que es lo que el perfil A
    necesita y lo que ya estaba entregado. Solo escribir la variable en blanco
    —un acto explícito del operador— suprime el campo.
    """
    monkeypatch.delenv(VARIABLE, raising=False)
    cfg = cargar_config()
    assert cfg.llm_razonamiento == "none"


def test_la_variable_vacia_y_la_ausente_dan_configuraciones_distintas(
    tmp_path, monkeypatch
) -> None:
    """El bug de F3.9 en una línea: antes las dos daban `none`.

    `_texto` colapsa la cadena vacía al default, así que `LLM_RAZONAMIENTO=` no
    servía para pedir «ninguno» y no había forma de configurar el perfil C sin
    depender de que el proveedor tolerase `none`.
    """
    monkeypatch.delenv(VARIABLE, raising=False)
    ausente = cargar_config().llm_razonamiento

    monkeypatch.setenv(VARIABLE, "")
    vacia = cargar_config().llm_razonamiento

    assert ausente == "none"
    assert vacia == ""
    assert ausente != vacia
