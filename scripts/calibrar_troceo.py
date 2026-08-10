#!/usr/bin/env python3
"""Mide sobre el corpus los dos números que fijan el troceo. No los supone.

Qué mide y por qué
------------------
1. **Caracteres por token** del tokenizador REAL del embedder
   (`all-MiniLM-L6-v2`, ONNX, el que vendoriza la imagen), separando español e
   inglés. El embedder trunca a 256 tokens; el tamaño de trozo en caracteres
   tiene que quedar por debajo de ese techo **en el idioma que peor se
   tokeniza**, que es el español sobre un vocabulario mayoritariamente inglés.
2. **Longitud de oración** (media, P50, P95, máximo). El solape tiene que cubrir
   al menos el P95 para que ninguna oración quede partida en todos los trozos
   donde aparece.

Uso (dentro del contenedor: ahí están chromadb y el modelo vendorizado):

    docker compose run --rm --no-deps \\
        -v "$(pwd)/scripts:/app/scripts:ro" \\
        agente python scripts/calibrar_troceo.py

`--muestra N` limita el número de documentos: la medición completa sobre 107
PDFs tarda unos minutos y la tasa caracteres/token se estabiliza mucho antes.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from app.config import obtener_config  # noqa: E402
from app.rag import extraccion, idioma, troceo  # noqa: E402


def _tokenizador():
    """El tokenizador exacto del embedder, con su truncamiento desactivado.

    Con `enable_truncation` activo toda medición daría 256 y la pregunta —cuántos
    tokens produce este texto— quedaría sin responder. Se pide una instancia
    limpia y se apaga el truncamiento solo para medir.
    """
    from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2
    from tokenizers import Tokenizer

    ruta = (
        Path(ONNXMiniLM_L6_V2.DOWNLOAD_PATH)
        / ONNXMiniLM_L6_V2.EXTRACTED_FOLDER_NAME
        / "tokenizer.json"
    )
    if not ruta.is_file():
        raise SystemExit(f"no está el tokenizador vendorizado en {ruta}")
    tok = Tokenizer.from_file(str(ruta))
    tok.no_truncation()
    tok.no_padding()
    return tok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--muestra", type=int, default=0, help="0 = todos")
    parser.add_argument("--semilla", type=int, default=7)
    args = parser.parse_args()

    cfg = obtener_config()
    raiz = cfg.dir_dataset / "textos"
    archivos = sorted(
        p for p in raiz.rglob("*") if p.is_file() and p.suffix.lower() in extraccion.SUFIJOS_ACEPTADOS
    )
    if args.muestra:
        import random

        random.Random(args.semilla).shuffle(archivos)
        archivos = sorted(archivos[: args.muestra])

    tok = _tokenizador()
    print(f"documentos a medir: {len(archivos)}\n")

    por_idioma: dict[str, list[tuple[int, int]]] = {}
    longitudes_oracion: list[int] = []
    sin_texto: list[str] = []
    caracteres_por_pagina: list[tuple[str, float]] = []

    for i, ruta in enumerate(archivos, 1):
        relativa = ruta.relative_to(raiz).as_posix()
        try:
            paginas = extraccion.extraer_paginas(ruta)
        except extraccion.ErrorDeExtraccion as exc:
            print(f"  [{i:3d}/{len(archivos)}] ILEGIBLE {relativa}: {exc}")
            continue
        media = (
            sum(len(p.texto.strip()) for p in paginas) / len(paginas) if paginas else 0.0
        )
        caracteres_por_pagina.append((relativa, media))
        if not extraccion.tiene_capa_de_texto(paginas):
            sin_texto.append(f"{relativa} ({media:.1f} car./pág., {len(paginas)} págs.)")
            print(f"  [{i:3d}/{len(archivos)}] SIN CAPA DE TEXTO {relativa} ({media:.1f} car./pág.)")
            continue

        texto = troceo.normalizar("\n".join(p.texto for p in paginas))
        lengua = idioma.detectar(texto)
        for _, oracion in troceo.oraciones(texto):
            recortada = oracion.strip()
            if recortada:
                longitudes_oracion.append(len(recortada))

        # Se miden ventanas de ~1200 caracteres, no el documento entero: es el
        # orden de magnitud del trozo, y la tasa caracteres/token depende de él
        # (un documento entero promedia sobre secciones muy distintas).
        muestras = por_idioma.setdefault(lengua, [])
        for inicio in range(0, min(len(texto), 60_000), 1200):
            ventana = texto[inicio : inicio + 1200]
            if len(ventana) < 600:
                continue
            muestras.append((len(ventana), len(tok.encode(ventana).ids)))
        print(f"  [{i:3d}/{len(archivos)}] {lengua}  {len(paginas):3d} págs.  {relativa[:70]}")

    print("\n" + "=" * 78)
    print("CARACTERES POR TOKEN (tokenizador de all-MiniLM-L6-v2)")
    print("=" * 78)
    print(f"{'idioma':<14}{'ventanas':>10}{'media':>10}{'P05':>10}{'mínimo':>10}")
    peor = None
    for lengua, muestras in sorted(por_idioma.items()):
        tasas = sorted(c / t for c, t in muestras if t)
        if not tasas:
            continue
        p05 = tasas[max(0, int(0.05 * (len(tasas) - 1)))]
        print(
            f"{lengua:<14}{len(tasas):>10}{statistics.fmean(tasas):>10.3f}"
            f"{p05:>10.3f}{tasas[0]:>10.3f}"
        )
        peor = p05 if peor is None else min(peor, p05)

    print("\n" + "=" * 78)
    print("LONGITUD DE ORACIÓN (caracteres)")
    print("=" * 78)
    if longitudes_oracion:
        orden = sorted(longitudes_oracion)
        p = lambda q: orden[min(len(orden) - 1, int(q * (len(orden) - 1)))]  # noqa: E731
        print(
            f"n={len(orden)}  media={statistics.fmean(orden):.1f}  "
            f"P50={p(0.50)}  P75={p(0.75)}  P90={p(0.90)}  P95={p(0.95)}  "
            f"P99={p(0.99)}  máx={orden[-1]}"
        )

    print("\n" + "=" * 78)
    print("CONSECUENCIA PARA LOS PARÁMETROS")
    print("=" * 78)
    if peor:
        print(f"tasa caracteres/token del percentil 5 (el peor caso): {peor:.3f}")
        print(f"techo de caracteres a 256 tokens:                     {peor * 256:.0f}")
        print(f"techo con 20 % de margen:                             {peor * 256 * 0.8:.0f}")
    if sin_texto:
        print(f"\nDocumentos SIN capa de texto ({len(sin_texto)}):")
        for nombre in sin_texto:
            print(f"  - {nombre}")
    else:
        print("\nNingún documento sin capa de texto en esta muestra.")

    flojos = sorted(caracteres_por_pagina, key=lambda par: par[1])[:5]
    print("\nLos 5 documentos con menos caracteres por página (control del umbral):")
    for nombre, media in flojos:
        print(f"  {media:9.1f}  {nombre}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
