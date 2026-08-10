#!/usr/bin/env python3
"""Construye el índice del corpus en `indice_base/`. NUNCA corre en el arranque.

Por qué el índice viaja construido
----------------------------------
Indexar 107 PDFs son minutos de CPU. Un servicio que los gasta al arrancar está
caído durante esos minutos, justo cuando el evaluador acaba de hacer `up -d` y
está mirando `/salud`. Así que el índice se construye **aquí**, entra al
repositorio como `indice_base/` y el entrypoint lo siembra en el volumen con un
`mv` atómico (ver `docker/entrypoint.sh`). El arranque solo copia bytes.

Uso (dentro del contenedor: ahí están chromadb y el embedder vendorizado):

    docker compose --profile herramientas run --rm indexador

El servicio `indexador` comparte imagen con `agente`, y eso no es economía: es
correción. Indexar con un embedder y consultar con otro produce vectores
incomparables — la recuperación devuelve ruido con forma de resultado y nadie lo
nota hasta que lee las citas.

Idempotencia
------------
Por defecto **reconstruye desde cero**: borra el contenido de la salida y vuelve
a indexar. Es la única forma de que reejecutarlo dé el mismo índice y no uno con
sedimentos de una corrida anterior con otros parámetros. Los identificadores de
trozo son deterministas (`hash del texto del documento` + índice del trozo), así
que `--incremental` también converge al mismo contenido; se conserva para
reindexar sin rehacer todo.

Lo que este script decide y declara
-----------------------------------
* **Duplicados**: el corpus los trae (lo dice el README del reto). Se detectan por
  hash del TEXTO EXTRAÍDO y, cuando el hash no basta, por **solapamiento de
  shingles**: los duplicados reales de este corpus no son idénticos —difieren en
  el encabezado del editor— y el SHA-256 no los ve. El criterio y el hueco medido
  que fija su umbral están en `app/rag/duplicados.py`. Se indexa el primero en
  orden alfabético de ruta y se listan los descartados con su gemelo y su
  similitud.
* **PDF escaneado sin capa de texto**: se DESCARTA, no se le hace OCR. Decisión
  tomada; el razonamiento está en `app/rag/extraccion.py`. Se reporta por nombre
  aquí y en el README, porque un documento ausente del que nadie se enteró es
  indistinguible de un bug.
* **Límite duro de 90 MB por archivo**: GitHub avisa a 50 MB y rechaza a 100. Si
  algún archivo de la salida lo supera, el script termina con código 2 y lo dice.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from app.config import obtener_config  # noqa: E402
from app.rag import duplicados, extraccion, idioma, indice, troceo  # noqa: E402
from app.rag.tipos import ORIGEN_CORPUS, Trozo  # noqa: E402

LIMITE_MB_POR_ARCHIVO = 90.0
"""GitHub avisa a 50 MB y RECHAZA a 100. 90 deja margen para que el aviso llegue
aquí, en la consola de quien indexa, y no en el `push` — donde ya no hay nada que
hacer salvo reescribir la historia."""

MAX_TOKENS_EMBEDDER = 256
"""Truncamiento del tokenizador de all-MiniLM-L6-v2. Ver app/rag/troceo.py."""


# --------------------------------------------------------------------------- #
# Utilidades de informe
# --------------------------------------------------------------------------- #
def _tamano(directorio: Path) -> tuple[float, list[tuple[float, str]]]:
    """`(MB totales, [(MB, ruta relativa), …] ordenado de mayor a menor)`."""
    archivos = [p for p in directorio.rglob("*") if p.is_file()]
    detalle = sorted(
        ((p.stat().st_size / 1_048_576, p.relative_to(directorio).as_posix()) for p in archivos),
        reverse=True,
    )
    return sum(mb for mb, _ in detalle), detalle


def _compactar(ruta: Path) -> float | None:
    """`VACUUM` sobre el SQLite del índice. Devuelve los MB liberados.

    No cambia ni un dato: reordena páginas y devuelve al sistema el espacio que
    quedó libre tras las inserciones. `None` si no se pudo —lo normal sería que
    ChromaDB tuviera la base tomada—, y en ese caso se dice y se sigue: un índice
    sin compactar es correcto, solo más grande.
    """
    if not ruta.is_file():
        return None
    import sqlite3

    antes = ruta.stat().st_size
    try:
        conexion = sqlite3.connect(str(ruta))
        try:
            conexion.execute("VACUUM")
        finally:
            conexion.close()
    except sqlite3.Error as exc:
        print(f"AVISO: no se pudo compactar el SQLite ({exc}); el índice es válido igual.")
        return None
    return (ruta.stat().st_size - antes) / 1_048_576


def _tokenizador() -> Any | None:
    """El tokenizador real del embedder, sin truncar. `None` si no está.

    Sirve para la verificación a posteriori: cuántos trozos superan de verdad los
    256 tokens. Si el tokenizador no estuviera, la comprobación se salta y se
    dice — mejor eso que fingir que se hizo.
    """
    try:
        from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2
        from tokenizers import Tokenizer

        ruta = (
            Path(ONNXMiniLM_L6_V2.DOWNLOAD_PATH)
            / ONNXMiniLM_L6_V2.EXTRACTED_FOLDER_NAME
            / "tokenizer.json"
        )
        if not ruta.is_file():
            return None
        tok = Tokenizer.from_file(str(ruta))
        tok.no_truncation()
        tok.no_padding()
        return tok
    except Exception:  # noqa: BLE001 - la verificación es opcional, no el índice
        return None


# --------------------------------------------------------------------------- #
# Programa
# --------------------------------------------------------------------------- #
def main() -> int:
    cfg = obtener_config()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=cfg.dir_dataset / "textos")
    parser.add_argument("--salida", type=Path, default=cfg.dir_indice_semilla)
    parser.add_argument("--coleccion", default=cfg.coleccion_rag)
    parser.add_argument("--trozo", type=int, default=cfg.rag_trozo_caracteres)
    parser.add_argument("--solape", type=int, default=cfg.rag_solape_caracteres)
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="no borra la salida; hace upsert sobre el índice existente",
    )
    parser.add_argument("--limite-mb", type=float, default=LIMITE_MB_POR_ARCHIVO)
    args = parser.parse_args()

    raiz: Path = args.dataset
    salida: Path = args.salida
    if not raiz.is_dir():
        print(f"ERROR: no existe el corpus en {raiz}", file=sys.stderr)
        return 2

    print("=" * 78)
    print("INDEXACIÓN DEL CORPUS")
    print("=" * 78)
    print(f"corpus     : {raiz}")
    print(f"salida     : {salida}")
    print(f"colección  : {args.coleccion}")
    print(f"troceo     : {args.trozo} caracteres, solape {args.solape}")
    print(f"modo       : {'incremental (upsert)' if args.incremental else 'reconstrucción desde cero'}")
    print()

    inicio = time.perf_counter()

    if not args.incremental and salida.exists():
        for hijo in salida.iterdir():
            if hijo.is_dir():
                shutil.rmtree(hijo)
            else:
                hijo.unlink()
        print(f"salida vaciada: {salida}\n")
    salida.mkdir(parents=True, exist_ok=True)

    archivos = sorted(
        (p for p in raiz.rglob("*") if p.is_file() and p.suffix.lower() in extraccion.SUFIJOS_ACEPTADOS),
        key=lambda p: p.relative_to(raiz).as_posix(),
    )
    print(f"archivos candidatos: {len(archivos)}\n")

    detector = duplicados.Detector()
    repetidos: list[tuple[str, str, float, str]] = []
    sin_capa_de_texto: list[tuple[str, int, float]] = []
    ilegibles: list[tuple[str, str]] = []
    indexados: list[tuple[str, str, int, int]] = []  # ruta, idioma, páginas, trozos
    por_idioma: dict[str, int] = {}
    trozos: list[Trozo] = []

    for i, ruta in enumerate(archivos, 1):
        relativa = ruta.relative_to(raiz).as_posix()
        escenario = relativa.split("/", 1)[0] if "/" in relativa else "(raíz)"

        try:
            paginas = extraccion.extraer_paginas(ruta)
        except extraccion.ErrorDeExtraccion as exc:
            ilegibles.append((relativa, str(exc)))
            print(f"[{i:3d}/{len(archivos)}] ILEGIBLE          {relativa}  ({exc})")
            continue

        if not extraccion.tiene_capa_de_texto(paginas):
            media = (
                sum(len(p.texto.strip()) for p in paginas) / len(paginas) if paginas else 0.0
            )
            sin_capa_de_texto.append((relativa, len(paginas), media))
            print(
                f"[{i:3d}/{len(archivos)}] SIN CAPA DE TEXTO {relativa}  "
                f"({len(paginas)} págs., {media:.1f} car./pág. — se descarta, sin OCR)"
            )
            continue

        texto_completo = troceo.normalizar("\n".join(p.texto for p in paginas))
        huella = extraccion.hash_de_texto(texto_completo)
        gemelo, similitud, motivo = detector.evaluar(relativa, texto_completo)
        if gemelo is not None:
            repetidos.append((relativa, gemelo, similitud, motivo))
            print(
                f"[{i:3d}/{len(archivos)}] DUPLICADO         {relativa}  "
                f"== {gemelo}  ({motivo}, Jaccard {similitud:.4f})"
            )
            continue

        lengua = idioma.detectar(texto_completo)
        crudos = troceo.trocear(
            paginas, max_caracteres=args.trozo, solape_caracteres=args.solape
        )
        documento_id = f"corpus-{huella[:16]}"
        for k, crudo in enumerate(crudos):
            trozos.append(
                Trozo(
                    id=f"{documento_id}-{k:05d}",
                    texto=crudo.texto,
                    ruta_relativa=relativa,
                    pagina=crudo.pagina,
                    escenario=escenario,
                    idioma=lengua,
                    origen=ORIGEN_CORPUS,
                    hash_documento=huella,
                    documento_id=documento_id,
                    indice=k,
                )
            )
        indexados.append((relativa, lengua, len(paginas), len(crudos)))
        por_idioma[lengua] = por_idioma.get(lengua, 0) + 1
        print(
            f"[{i:3d}/{len(archivos)}] {lengua:<17} {relativa}  "
            f"({len(paginas)} págs. → {len(crudos)} trozos)"
        )

    print(f"\ntrozos a insertar: {len(trozos)}")
    if not trozos:
        print("ERROR: no hay nada que indexar.", file=sys.stderr)
        return 2

    # --- verificación del troceo contra el truncamiento real del embedder ---- #
    tok = _tokenizador()
    if tok is None:
        print("AVISO: sin tokenizador vendorizado; no se verifica el límite de 256 tokens.")
        excedidos = None
    else:
        longitudes = [len(tok.encode(t.texto).ids) for t in trozos]
        excedidos = sum(1 for n in longitudes if n > MAX_TOKENS_EMBEDDER)
        longitudes.sort()
        p = lambda q: longitudes[min(len(longitudes) - 1, int(q * (len(longitudes) - 1)))]  # noqa: E731
        print(
            f"tokens por trozo: P50={p(0.50)}  P95={p(0.95)}  P99={p(0.99)}  "
            f"máx={longitudes[-1]}  (techo del embedder: {MAX_TOKENS_EMBEDDER})"
        )
        if excedidos:
            print(
                f"AVISO: {excedidos} trozos ({100*excedidos/len(trozos):.2f} %) superan "
                f"{MAX_TOKENS_EMBEDDER} tokens y el embedder los truncará. "
                "Baje RAG_TROZO_CARACTERES."
            )

    # --- inserción ----------------------------------------------------------- #
    print("\ncargando embedder e insertando…")
    almacen = indice.abrir(salida, args.coleccion)
    insertados = almacen.agregar(trozos)
    total_coleccion = almacen.contar()

    # --- compactación --------------------------------------------------------
    # El índice que se construye aquí se COMMITEA y lo descarga el jurado, así
    # que sus páginas libres se pagan en ancho de banda de otra persona. Un
    # VACUUM al final es una línea y no cambia el contenido. Medido en la corrida
    # del 2026-08-10: 78,83 MB → 74,04 MB.
    liberados = _compactar(salida / "chroma.sqlite3")
    if liberados is not None:
        print(f"SQLite compactado: {liberados:+.2f} MB")

    segundos = time.perf_counter() - inicio

    # --- VERSION ------------------------------------------------------------- #
    # El entrypoint lee la primera línea para el marcador de siembra.
    version = time.strftime("%Y-%m-%d")
    (salida / "VERSION").write_text(
        f"corpus-{version} trozos={total_coleccion}\n"
        f"fecha={time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n"
        f"coleccion={args.coleccion}\n"
        f"documentos_indexados={len(indexados)}\n"
        f"descartados_duplicado={len(repetidos)}\n"
        f"descartados_sin_texto={len(sin_capa_de_texto)}\n"
        f"troceo_caracteres={args.trozo} solape={args.solape}\n"
        f"embedder=all-MiniLM-L6-v2 (ONNX, 384 dim, espacio {indice.ESPACIO})\n",
        encoding="utf-8",
    )

    # --- informe ------------------------------------------------------------- #
    total_mb, detalle = _tamano(salida)
    print("\n" + "=" * 78)
    print("RESULTADO")
    print("=" * 78)
    print(f"documentos procesados        : {len(indexados)} de {len(archivos)} candidatos")
    for lengua, n in sorted(por_idioma.items()):
        print(f"    idioma {lengua:<16}: {n}")
    print(f"descartados por duplicado    : {len(repetidos)}")
    for relativa, gemelo, similitud, motivo in repetidos:
        print(f"    {relativa}\n        {motivo} de: {gemelo}  (Jaccard {similitud:.4f})")
    print(f"descartados por falta de texto: {len(sin_capa_de_texto)}")
    for relativa, paginas_n, media in sin_capa_de_texto:
        print(f"    {relativa}  ({paginas_n} págs., {media:.1f} car./pág.) — escaneado, NO se le hace OCR")
    if ilegibles:
        print(f"ilegibles                    : {len(ilegibles)}")
        for relativa, motivo in ilegibles:
            print(f"    {relativa}: {motivo}")
    print(f"trozos totales               : {insertados} insertados, {total_coleccion} en la colección")
    if excedidos is not None:
        print(f"trozos truncados por el embedder: {excedidos}")
    print(f"tiempo                       : {segundos:.1f} s")
    print(f"tamaño de {salida.name}/          : {total_mb:.1f} MB en {len(detalle)} archivos")
    print("archivos más grandes:")
    for mb, nombre in detalle[:5]:
        print(f"    {mb:8.2f} MB  {nombre}")

    grandes = [(mb, nombre) for mb, nombre in detalle if mb > args.limite_mb]
    if grandes:
        print("\n" + "!" * 78, file=sys.stderr)
        print(
            f"LÍMITE DURO SUPERADO: {len(grandes)} archivo(s) por encima de "
            f"{args.limite_mb:.0f} MB. NO se debe commitear este índice: GitHub "
            "avisa a 50 MB y rechaza a 100.",
            file=sys.stderr,
        )
        for mb, nombre in grandes:
            print(f"    {mb:.2f} MB  {nombre}", file=sys.stderr)
        print("!" * 78, file=sys.stderr)
        return 2

    print(f"\nOK: ningún archivo supera {args.limite_mb:.0f} MB. Índice listo para viajar por git.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
