#!/usr/bin/env python3
"""BANCO DE PRUEBAS del turno: un STT falso que habla el protocolo de OpenAI.

**No es parte de la aplicación y nunca se importa desde `app/`.** Es una
herramienta de verificación, del mismo tipo que `reejecutar_decisiones.py`.

Para qué existe
---------------
El turno de voz necesita un servicio de transcripción, y el proveedor real exige
una clave que no está en este repositorio (ver `.env.example`). Sin una forma de
sustituirlo, el camino completo —audio real subido por multipart, extracción,
política, plantilla, TTS, registro, métricas— solo se podría ejercitar con
credenciales, y no se podría ejercitar en absoluto en una máquina sin red.

Este servidor implementa los dos endpoints que usa `app/audio/stt.py`:

    GET  /v1/models                 para que la sonda de /salud lo reconozca
    POST /v1/audio/transcriptions   devuelve la siguiente línea del guion

Lo que SÍ verifica: que el cliente HTTP arma bien el multipart, que el audio
llega entero, que los tiempos se miden, y todo lo que viene después. Lo que NO
verifica, y hay que decirlo: la calidad de transcripción del proveedor real.
Cambiar `STT_BASE_URL` a Groq y volver a correr es la diferencia entre las dos
cosas.

Uso:

    python3 scripts/stt_de_prueba.py --puerto 8099 --guion guion.txt

`guion.txt` lleva una respuesta del paciente por línea. Agotado el guion,
devuelve cadena vacía, que es exactamente lo que ve el agente cuando el paciente
se queda callado.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_candado = threading.Lock()
_guion: list[str] = []
_recibidos: list[int] = []


class Manejador(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _responder(self, codigo: int, cuerpo: dict) -> None:
        datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self) -> None:  # noqa: N802 - nombre impuesto por la librería
        if self.path.rstrip("/").endswith("/models"):
            self._responder(
                200,
                {
                    "object": "list",
                    "data": [
                        {"id": "whisper-large-v3", "object": "model"},
                        {"id": "whisper-large-v3-turbo", "object": "model"},
                    ],
                },
            )
        else:
            self._responder(404, {"error": {"message": f"sin ruta {self.path}"}})

    def do_POST(self) -> None:  # noqa: N802
        largo = int(self.headers.get("Content-Length", "0"))
        cuerpo = self.rfile.read(largo)
        if not self.path.rstrip("/").endswith("/audio/transcriptions"):
            self._responder(404, {"error": {"message": f"sin ruta {self.path}"}})
            return
        with _candado:
            _recibidos.append(len(cuerpo))
            texto = _guion.pop(0) if _guion else ""
            indice = len(_recibidos)
        print(
            f"[stt-de-prueba] turno {indice}: {len(cuerpo)} bytes de audio -> {texto!r}",
            flush=True,
        )
        self._responder(200, {"text": texto})

    def log_message(self, formato: str, *args: object) -> None:
        return  # el servidor ya imprime lo que importa


def main(argv: list[str]) -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--puerto", type=int, default=8099)
    analizador.add_argument("--direccion", default="0.0.0.0")
    analizador.add_argument("--guion", type=Path, default=None)
    opciones = analizador.parse_args(argv[1:])

    if opciones.guion:
        _guion.extend(
            linea for linea in opciones.guion.read_text(encoding="utf-8").splitlines()
        )
        print(f"[stt-de-prueba] guion de {len(_guion)} respuestas", flush=True)

    servidor = ThreadingHTTPServer((opciones.direccion, opciones.puerto), Manejador)
    print(
        f"[stt-de-prueba] escuchando en {opciones.direccion}:{opciones.puerto} "
        "(protocolo OpenAI: /v1/models y /v1/audio/transcriptions)",
        flush=True,
    )
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
