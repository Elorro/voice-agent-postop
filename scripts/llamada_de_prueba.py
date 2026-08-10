#!/usr/bin/env python3
"""BANCO DE PRUEBAS: recorre una llamada completa contra el servicio levantado.

**No es parte de la aplicación.** Sirve para ejercitar el turno de punta a punta
sin navegador: sube por `multipart/form-data` los WAV del paciente como haría el
cliente real, y va imprimiendo la decisión de la política en cada turno.

Este script NO sintetiza. Los WAV los produce `scripts/sintetizar_frases.py`,
que corre dentro del contenedor porque el modelo de Piper y espeak-ng no existen
en el host. Sin `--audios` el cliente manda **audio vacío**: el agente salta el
STT (`stt 0.0 ms`), la transcripción llega vacía y la llamada entera se ejecuta
contra el silencio sin que nada falle. Eso no es una prueba de nada.

    # con el servicio arriba (docker compose up -d):
    docker compose cp scripts/sintetizar_frases.py agente:/tmp/
    docker compose cp scripts/frases_de_prueba.txt agente:/tmp/frases.txt
    docker compose exec -T -w /app -e PYTHONPATH=/app agente \
        python3 /tmp/sintetizar_frases.py --frases /tmp/frases.txt --salida /tmp/audios
    docker compose cp agente:/tmp/audios ./datos/audios_prueba

    python3 scripts/llamada_de_prueba.py --dia 7 \
        --frases scripts/frases_de_prueba.txt --audios datos/audios_prueba

Lo que este cliente NO puede medir, y por eso lo declara en cada envío
(`origen=cliente_headless`): la latencia hasta que el **primer sample suena**.
No reproduce audio; su t1 es «respuesta recibida». Es una COTA INFERIOR del
número que pide la rúbrica, y `/metricas` la mantiene fuera del P50/P95
reportado precisamente para que nadie la confunda con una medición de verdad.
El número autoritativo solo lo puede producir un navegador (`/consola`).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ORIGEN = "cliente_headless"


def _peticion(url: str, datos: bytes | None, tipo: str | None = None) -> dict:
    peticion = urllib.request.Request(url, data=datos, method="POST" if datos is not None else "GET")
    if tipo:
        peticion.add_header("Content-Type", tipo)
    with urllib.request.urlopen(peticion, timeout=120) as respuesta:
        return json.loads(respuesta.read().decode("utf-8"))


def _multipart(campos: dict[str, str], archivo: tuple[str, bytes]) -> tuple[bytes, str]:
    """Arma un multipart a mano: el banco de pruebas no debe traer dependencias."""
    frontera = f"----banco{uuid.uuid4().hex}"
    partes: list[bytes] = []
    for clave, valor in campos.items():
        partes.append(
            f'--{frontera}\r\nContent-Disposition: form-data; name="{clave}"\r\n\r\n'
            f"{valor}\r\n".encode("utf-8")
        )
    nombre, contenido = archivo
    partes.append(
        f'--{frontera}\r\nContent-Disposition: form-data; name="audio"; '
        f'filename="{nombre}"\r\nContent-Type: audio/wav\r\n\r\n'.encode("utf-8")
    )
    partes.append(contenido)
    partes.append(f"\r\n--{frontera}--\r\n".encode("utf-8"))
    return b"".join(partes), f"multipart/form-data; boundary={frontera}"


def main(argv: list[str]) -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--base", default="http://127.0.0.1:8080")
    analizador.add_argument("--dia", type=int, default=None, help="día postoperatorio")
    analizador.add_argument("--paciente", default=None)
    analizador.add_argument(
        "--frases",
        type=Path,
        required=True,
        help="una intervención del paciente por línea; solo se usan para imprimir el turno",
    )
    analizador.add_argument(
        "--audios",
        type=Path,
        default=None,
        help="directorio con turno_1.wav, turno_2.wav… (sintetizar_frases.py). SIN esto se manda audio vacío",
    )
    analizador.add_argument(
        "--pausa-ms",
        type=int,
        default=4000,
        dest="pausa_ms",
        help=(
            "espera ANTES de cada turno. Una conversación real tiene pausas y el "
            "banco las comprime: sin esto, 7 turnos disparan 14 invocaciones en "
            "~7 s y el nivel gratuito del proveedor responde 429 (default: 4000)"
        ),
    )
    opciones = analizador.parse_args(argv[1:])

    frases = [
        linea for linea in opciones.frases.read_text(encoding="utf-8").splitlines() if linea
    ]

    cuerpo: dict[str, object] = {}
    if opciones.dia is not None:
        cuerpo["dia_postop"] = opciones.dia
    if opciones.paciente:
        cuerpo["paciente_id"] = opciones.paciente

    datos = _peticion(
        f"{opciones.base}/api/llamada",
        json.dumps(cuerpo).encode("utf-8"),
        "application/json",
    )
    llamada_id = datos["llamada_id"]
    print(f"llamada {llamada_id}")
    print(f"  agente: {datos['respuesta']}")
    print(f"  audio de apertura: {len(datos['audio_wav_b64'])} caracteres base64")

    pendiente: tuple[int, float] | None = None

    for numero, frase in enumerate(frases, start=1):
        # ANTES de t0, nunca dentro: esta espera simula el silencio entre
        # intervenciones y no puede contaminar la latencia medida del turno.
        if opciones.pausa_ms > 0:
            time.sleep(opciones.pausa_ms / 1000.0)

        if opciones.audios:
            audio = (opciones.audios / f"turno_{numero}.wav").read_bytes()
        else:
            audio = b""
        campos = {
            "duracion_audio_ms": str(int(len(audio) / (22050 * 2) * 1000)),
            "origen_medicion": ORIGEN,
        }
        if pendiente:
            campos["turno_medido_idx"] = str(pendiente[0])
            campos["delta_fin_habla_ms"] = f"{pendiente[1]:.1f}"
        payload, tipo = _multipart(campos, (f"turno_{numero}.wav", audio))

        # t0: el instante en que este cliente da por terminada la intervención
        # del paciente. Sin reproducción, t1 es «respuesta recibida».
        t0 = time.perf_counter()
        try:
            respuesta = _peticion(
                f"{opciones.base}/api/llamada/{llamada_id}/turno", payload, tipo
            )
        except urllib.error.HTTPError as exc:
            print(f"  turno {numero}: HTTP {exc.code} — {exc.read().decode()[:300]}")
            break
        ms = (time.perf_counter() - t0) * 1000
        pendiente = (respuesta["turno_idx"], ms)

        pol = respuesta["politica"] or {}
        print(f"\n  turno {respuesta['turno_idx']} — «{frase}»")
        print(f"    transcripción: {respuesta['transcripcion']!r}")
        print(
            f"    política: {pol.get('accion')} "
            f"senal={pol.get('senal_a_indagar')} clase={pol.get('clase')} "
            f"criterio={pol.get('criterio')} n_total={pol.get('n_total')}"
        )
        print(f"    agente ({respuesta['fuente_respuesta']}): {respuesta['respuesta']}")
        spans = respuesta["latencia_ms"]["spans"]
        print(
            f"    servidor {respuesta['latencia_ms']['servidor_total']} ms "
            f"(stt {spans['stt']} · extracción {spans['extraccion']} · "
            f"política {spans['politica']} · redacción {spans['redaccion']} · "
            f"tts {spans['tts']}) | cliente headless {ms:.0f} ms"
        )

        # El beacon: aquí sí se manda en el momento, con su origen declarado.
        _peticion(
            f"{opciones.base}/api/llamada/{llamada_id}/telemetria",
            json.dumps(
                {
                    "turno_idx": respuesta["turno_idx"],
                    "delta_fin_habla_ms": round(ms, 1),
                    "origen": ORIGEN,
                }
            ).encode("utf-8"),
            "application/json",
        )

        if respuesta["fin"]:
            print(f"\n  FIN — clase {respuesta['clase']} por {respuesta['criterio']}")
            break

    cierre = _peticion(f"{opciones.base}/api/llamada/{llamada_id}/cierre", b"", "application/json")
    print("\nresumen de cierre:")
    print(json.dumps(cierre["totales"], ensure_ascii=False, indent=2))
    print(f"presupuesto: {cierre['presupuesto']}")
    print(f"persistida en: {cierre['persistida_en']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
