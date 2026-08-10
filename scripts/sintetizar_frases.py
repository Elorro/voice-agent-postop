#!/usr/bin/env python3
"""BANCO DE PRUEBAS: convierte un archivo de frases en los `turno_N.wav` que
consume `llamada_de_prueba.py --audios`.

**No es parte de la aplicación.** Corre DENTRO del contenedor, que es donde
viven las tres piezas necesarias: el `.onnx` de Piper, su `.json`, y
`libespeak-ng` con `espeak-ng-data`. En el host no están, y por eso este script
no se ejecuta desde el host:

    docker compose exec -T agente python3 scripts/sintetizar_frases.py \
        --frases /app/datos/logs/frases.txt --salida /app/datos/logs/audios

Usa el mismo `Sintetizador` que el agente usa para hablar. Eso es deliberado:
la voz del paciente y la del agente salen del mismo modelo, así que el STT
recibe exactamente la distribución acústica sobre la que se va a medir la
latencia. No simula un paciente real —una voz sintética no tiene la
variabilidad de una humana— y por tanto la tasa de acierto del STT medida así
es una COTA SUPERIOR, no una estimación de campo.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import cargar_config
from app.contratos import OK
from app.audio.tts import obtener_sintetizador


def main(argv: list[str]) -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument(
        "--frases",
        type=Path,
        required=True,
        help="una intervención del paciente por línea (mismo archivo que --frases de llamada_de_prueba.py)",
    )
    analizador.add_argument(
        "--salida",
        type=Path,
        required=True,
        help="directorio donde escribir turno_1.wav, turno_2.wav…",
    )
    opciones = analizador.parse_args(argv[1:])

    frases = [
        linea for linea in opciones.frases.read_text(encoding="utf-8").splitlines() if linea
    ]
    if not frases:
        print(f"{opciones.frases}: no hay ninguna frase", file=sys.stderr)
        return 2

    opciones.salida.mkdir(parents=True, exist_ok=True)
    sintetizador = obtener_sintetizador(cargar_config())
    print(f"voz: {sintetizador.ruta.name} @ {sintetizador.muestreo_hz} Hz")

    fallos = 0
    for numero, frase in enumerate(frases, start=1):
        salida = sintetizador.sintetizar(frase)
        destino = opciones.salida / f"turno_{numero}.wav"
        if salida.resultado != OK:
            fallos += 1
            print(f"  turno {numero}: FALLO — {salida.detalle}", file=sys.stderr)
            continue
        destino.write_bytes(salida.wav)
        print(
            f"  turno {numero}: {destino.name} "
            f"({salida.segundos:.2f} s, {len(salida.wav)} bytes, {salida.ms:.0f} ms) "
            f"«{frase}»"
        )

    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
