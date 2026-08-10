#!/usr/bin/env python3
"""Mide el embedder en español y calibra el umbral de suficiencia. No los supone.

Las dos preguntas que responde
------------------------------

**1. ¿Sirve el embedder para consultas en español?**
El modelo por defecto de ChromaDB (`all-MiniLM-L6-v2`) es **monolingüe inglés**.
Se heredó al decidir «onnxruntime, no torch», que era una decisión sobre el peso
de la imagen y no sobre el idioma. El corpus es mayoritariamente español y las
preguntas del paciente son todas en español. Nadie había medido cuánto cuesta
eso, y sin ese número no se puede decidir si hay que cambiar de modelo.

El guion son consultas clínicas reales en español cuya respuesta está en el
corpus. Para cada una se reporta el top-5 con documento, página y score. El
criterio objetivo que se automatiza es el **escenario** del que sale cada
fragmento: es un proxy, no la verdad —un fragmento del escenario correcto puede
no responder la pregunta— y por eso se imprime también el texto, para que la
pertinencia la juzgue una persona leyendo, que es la única forma honesta.

**2. ¿Dónde va el umbral?**
Un buscador de vecinos siempre devuelve k resultados. El umbral es lo que separa
«hay respuesta» de «no tengo el dato», y calibrarlo necesita **dos poblaciones**:
consultas cubiertas por el corpus y consultas ajenas a él. El umbral se pone en
el hueco entre las dos distribuciones; si no hay hueco, no hay umbral que valga y
eso también es un resultado que hay que reportar.

Uso:

    docker compose --profile herramientas run --rm indexador scripts/calibrar_umbral.py

Por defecto consulta la semilla (`/opt/indice_base`), que es el índice recién
construido. Con `--indice` se apunta a otro.
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
from app.rag import indice  # noqa: E402

# --------------------------------------------------------------------------- #
# El guion. Español, clínicas, y con la respuesta dentro del corpus.
# --------------------------------------------------------------------------- #
# `escenario` es la carpeta de `dataset/textos/` donde debería estar la
# respuesta. Varias preguntas son transversales (cuidado de herida, signos de
# infección) y aceptan más de una: forzar una sola carpeta habría medido la
# taxonomía del corpus, no el embedder.
EN_CORPUS: list[tuple[str, tuple[str, ...]]] = [
    ("¿Cuánto dolor es normal después de una apendicectomía?", ("Appendicitis",)),
    (
        "¿Qué signos de infección debo vigilar en la herida quirúrgica?",
        ("Appendicitis", "cholecystitis", "colorectal cancer", "total joint replacement"),
    ),
    ("Tengo fiebre después de la apendicectomía, ¿qué debo hacer?", ("Appendicitis",)),
    (
        "¿Cómo debo cuidar la herida en casa después de la cirugía?",
        ("Appendicitis", "cholecystitis", "colorectal cancer", "total joint replacement"),
    ),
    (
        "¿Cuándo puedo empezar a caminar después del reemplazo total de rodilla?",
        ("total joint replacement",),
    ),
    (
        "¿Qué seguimiento necesito después de una colecistectomía?",
        ("cholecystitis",),
    ),
    (
        "¿Qué complicaciones son frecuentes después de una apendicectomía?",
        ("Appendicitis",),
    ),
    (
        "¿Qué debo comer después de una cirugía de cáncer de colon?",
        ("colorectal cancer",),
    ),
    (
        "¿Cuándo debo ir a urgencias después de la cirugía?",
        ("Appendicitis", "cholecystitis", "colorectal cancer", "total joint replacement"),
    ),
    (
        "¿Cómo se maneja el dolor después de una artroplastia de rodilla?",
        ("total joint replacement",),
    ),
]

# CONTROL EN INGLÉS. Las mismas diez preguntas, traducidas, y las mismas ocho
# ajenas. No es adorno: el corpus es bilingüe y el embedder es monolingüe inglés,
# así que correr las dos versiones sobre el MISMO índice aísla el idioma como
# variable. Si el inglés separa las dos poblaciones y el español no, la causa no
# es «el corpus no cubre el tema» —el corpus es el mismo— sino el embedder.
EN_CORPUS_INGLES: list[tuple[str, tuple[str, ...]]] = [
    ("How much pain is normal after an appendectomy?", ("Appendicitis",)),
    (
        "What signs of infection should I watch for in the surgical wound?",
        ("Appendicitis", "cholecystitis", "colorectal cancer", "total joint replacement"),
    ),
    ("I have a fever after my appendectomy, what should I do?", ("Appendicitis",)),
    (
        "How should I care for the wound at home after surgery?",
        ("Appendicitis", "cholecystitis", "colorectal cancer", "total joint replacement"),
    ),
    (
        "When can I start walking after a total knee replacement?",
        ("total joint replacement",),
    ),
    ("What follow-up do I need after a cholecystectomy?", ("cholecystitis",)),
    ("What complications are common after an appendectomy?", ("Appendicitis",)),
    ("What should I eat after colon cancer surgery?", ("colorectal cancer",)),
    (
        "When should I go to the emergency room after surgery?",
        ("Appendicitis", "cholecystitis", "colorectal cancer", "total joint replacement"),
    ),
    (
        "How is pain managed after knee arthroplasty?",
        ("total joint replacement",),
    ),
]

FUERA_DE_CORPUS_INGLES: list[str] = [
    "How much does a bus ticket to Bogota cost?",
    "Who won the last football world cup?",
    "How do you cook a traditional chicken soup?",
    "What is the capital of Australia?",
    "Can you help me with my tax return?",
    "Which phone should I buy this year?",
    "What time does the sun rise tomorrow?",
    "How do I change a flat tyre?",
]

FUERA_DE_CORPUS: list[str] = [
    "¿Cuánto cuesta el pasaje de bus a Bogotá?",
    "¿Quién ganó el último mundial de fútbol?",
    "¿Cómo se prepara un ajiaco santafereño?",
    "¿Cuál es la capital de Australia?",
    "¿Me ayuda con mi declaración de renta?",
    "¿Qué celular me recomienda comprar este año?",
    "¿A qué hora sale el sol mañana en Medellín?",
    "¿Cómo cambio una llanta pinchada?",
]


def _recorte(texto: str, n: int = 110) -> str:
    plano = " ".join(texto.split())
    return plano[: n - 1] + "…" if len(plano) > n else plano


def main() -> int:
    cfg = obtener_config()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--indice", type=Path, default=cfg.dir_indice_semilla)
    parser.add_argument("--coleccion", default=cfg.coleccion_rag)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--pool", type=int, default=cfg.rag_pool)
    parser.add_argument(
        "--alfa",
        type=float,
        default=cfg.rag_alfa,
        help="peso del canal denso en la fusión; 1.0 = denso puro (el de antes)",
    )
    parser.add_argument("--detalle", action="store_true", help="imprime el texto de cada fragmento")
    args = parser.parse_args()

    almacen = indice.abrir(args.indice, args.coleccion, crear=False)
    consultar = lambda q, k, a=None: almacen.consultar(  # noqa: E731
        q, k, pool=args.pool, alfa=args.alfa if a is None else a
    )
    print(f"índice     : {args.indice}")
    print(f"colección  : {args.coleccion}  ({almacen.contar()} fragmentos)")
    print(f"embedder   : all-MiniLM-L6-v2 (ONNX, 384 dim) · espacio {indice.ESPACIO}")
    print(f"k          : {args.k}   pool denso: {args.pool}   α (peso denso): {args.alfa}")
    print(f"canal léxico: {'FTS5 accesible' if almacen.total_fragmentos_fts() else 'NO DISPONIBLE'}\n")

    # ------------------------------------------------------------------ #
    # 1. Consultas cubiertas por el corpus
    # ------------------------------------------------------------------ #
    print("=" * 100)
    print("CONSULTAS CLÍNICAS EN ESPAÑOL CUYA RESPUESTA ESTÁ EN EL CORPUS")
    print("=" * 100)
    print(
        f"{'#':>2}  {'consulta':<62}{'esc. en top-5':>14}{'mejor':>8}{'score@5':>9}"
    )
    print("-" * 100)

    mejores_dentro: list[float] = []
    aciertos = 0
    detalles: list[tuple[str, list]] = []

    for i, (consulta, escenarios) in enumerate(EN_CORPUS, 1):
        fragmentos = consultar(consulta, args.k)
        detalles.append((consulta, fragmentos))
        if not fragmentos:
            print(f"{i:>2}  {consulta[:62]:<62}{'—':>14}{'—':>8}{'—':>9}")
            continue
        acierto = any(f.escenario in escenarios for f in fragmentos)
        aciertos += int(acierto)
        mejores_dentro.append(fragmentos[0].score)
        print(
            f"{i:>2}  {consulta[:62]:<62}"
            f"{('sí' if acierto else 'NO'):>14}"
            f"{fragmentos[0].score:>8.3f}{fragmentos[-1].score:>9.3f}"
        )

    print("-" * 100)
    print(
        f"escenario esperado presente en el top-{args.k}: {aciertos}/{len(EN_CORPUS)}"
    )
    if mejores_dentro:
        orden = sorted(mejores_dentro)
        print(
            f"mejor score por consulta — mín {orden[0]:.3f}  P25 {orden[len(orden)//4]:.3f}  "
            f"mediana {statistics.median(orden):.3f}  máx {orden[-1]:.3f}"
        )

    print("\n" + "=" * 100)
    print("TOP-5 POR CONSULTA (documento · página · score) — la pertinencia la juzga quien lee")
    print("=" * 100)
    for i, (consulta, fragmentos) in enumerate(detalles, 1):
        print(f"\n{i}. {consulta}")
        for puesto, f in enumerate(fragmentos, 1):
            print(
                f"   {puesto}. {f.score:.3f}  p.{f.pagina:<4} [{f.idioma}] "
                f"{f.ruta_relativa[:78]}"
            )
            print(f"      «{_recorte(f.texto, 150)}»")

    # ------------------------------------------------------------------ #
    # 2. Consultas ajenas al corpus
    # ------------------------------------------------------------------ #
    print("\n" + "=" * 100)
    print("CONSULTAS AJENAS AL CORPUS (la población que el umbral tiene que rechazar)")
    print("=" * 100)
    print(f"{'#':>2}  {'consulta':<62}{'mejor':>8}  documento del mejor")
    print("-" * 100)

    mejores_fuera: list[float] = []
    for i, consulta in enumerate(FUERA_DE_CORPUS, 1):
        fragmentos = consultar(consulta, args.k)
        if not fragmentos:
            continue
        mejores_fuera.append(fragmentos[0].score)
        print(
            f"{i:>2}  {consulta[:62]:<62}{fragmentos[0].score:>8.3f}  "
            f"{fragmentos[0].ruta_relativa[:40]}"
        )

    # ------------------------------------------------------------------ #
    # 3. El hueco
    # ------------------------------------------------------------------ #
    print("\n" + "=" * 100)
    print("SEPARACIÓN ENTRE LAS DOS POBLACIONES  →  UMBRAL")
    print("=" * 100)
    if not mejores_dentro or not mejores_fuera:
        print("no hay datos suficientes para calibrar.")
        return 1

    piso_dentro = min(mejores_dentro)
    techo_fuera = max(mejores_fuera)
    print(f"peor  de las consultas CUBIERTAS  : {piso_dentro:.3f}")
    print(f"mejor de las consultas AJENAS     : {techo_fuera:.3f}")
    if piso_dentro > techo_fuera:
        umbral = round((piso_dentro + techo_fuera) / 2, 2)
        print(f"hueco                             : {piso_dentro - techo_fuera:.3f}")
        print(f"\nUMBRAL propuesto (punto medio del hueco): {umbral:.2f}")
        print(
            "Punto medio y no el borde: pegarlo al peor caso cubierto deja el "
            "sistema sin margen ante una consulta nueva algo peor, y pegarlo al "
            "mejor ajeno deja pasar la siguiente pregunta ajena que puntúe algo más."
        )
    else:
        umbral = round(techo_fuera + 0.02, 2)
        print(
            f"\nLAS DOS POBLACIONES SE SOLAPAN ({techo_fuera - piso_dentro:.3f} de solape).\n"
            "No hay umbral que acepte todas las cubiertas y rechace todas las ajenas.\n"
            f"Con umbral {umbral:.2f} se rechazan todas las ajenas al precio de "
            "perder las consultas cubiertas que puntúen por debajo.\n"
            "La dirección de ese error es la segura: el agente declara su límite "
            "de más, nunca inventa de más."
        )
    # ------------------------------------------------------------------ #
    # 4. Control en inglés: aísla el idioma como variable
    # ------------------------------------------------------------------ #
    print("\n" + "=" * 100)
    print("CONTROL EN INGLÉS — mismas preguntas, mismo índice, otro idioma")
    print("=" * 100)

    def _poblacion(consultas, esperados=None):
        mejores, aciertos = [], 0
        for j, elemento in enumerate(consultas):
            texto = elemento[0] if esperados is None else elemento[0]
            fragmentos = consultar(texto, args.k)
            if not fragmentos:
                continue
            mejores.append(fragmentos[0].score)
            if esperados is not None:
                aciertos += int(any(f.escenario in elemento[1] for f in fragmentos))
        return mejores, aciertos

    dentro_en, aciertos_en = _poblacion(EN_CORPUS_INGLES, esperados=True)
    fuera_en, _ = _poblacion([(c,) for c in FUERA_DE_CORPUS_INGLES])

    print(f"{'población':<34}{'n':>4}{'mín':>9}{'mediana':>10}{'máx':>9}")
    print("-" * 100)
    for etiqueta, valores in (
        ("español · cubiertas", mejores_dentro),
        ("español · ajenas", mejores_fuera),
        ("inglés  · cubiertas", dentro_en),
        ("inglés  · ajenas", fuera_en),
    ):
        if valores:
            print(
                f"{etiqueta:<34}{len(valores):>4}{min(valores):>9.3f}"
                f"{statistics.median(valores):>10.3f}{max(valores):>9.3f}"
            )
    print(f"\nescenario esperado en el top-{args.k}: español {aciertos}/{len(EN_CORPUS)} · "
          f"inglés {aciertos_en}/{len(EN_CORPUS_INGLES)}")
    if dentro_en and fuera_en:
        hueco_es = piso_dentro - techo_fuera
        hueco_en = min(dentro_en) - max(fuera_en)
        print(f"hueco entre poblaciones:  español {hueco_es:+.3f} · inglés {hueco_en:+.3f}")

    # ------------------------------------------------------------------ #
    # 5. Barrido de α: cuánto separa cada mezcla de los dos canales
    # ------------------------------------------------------------------ #
    # UNA sola corrida, no una iteración: el hueco se mide para varios pesos a la
    # vez y el valor se elige leyendo la tabla, en vez de probar-y-repetir. α=1,0
    # es el régimen denso puro, es decir la medición anterior, recalculada aquí
    # con el mismo código para que las dos columnas sean comparables de verdad.
    print("\n" + "=" * 100)
    print("BARRIDO DE α  —  α=1,0 es denso puro (el régimen anterior)")
    print("=" * 100)
    print(
        f"{'α':>5}{'es cub. mín':>13}{'es ajena máx':>14}{'hueco es':>11}"
        f"{'en cub. mín':>13}{'en ajena máx':>14}{'hueco en':>11}"
    )
    print("-" * 100)
    mejor_alfa, mejor_hueco = None, -9.0
    for a in (1.0, 0.75, 0.6, 0.5, 0.4, 0.25, 0.0):
        d_es = [consultar(c, args.k, a)[0].score for c, _ in EN_CORPUS]
        f_es = [consultar(c, args.k, a)[0].score for c in FUERA_DE_CORPUS]
        d_en = [consultar(c, args.k, a)[0].score for c, _ in EN_CORPUS_INGLES]
        f_en = [consultar(c, args.k, a)[0].score for c in FUERA_DE_CORPUS_INGLES]
        h_es, h_en = min(d_es) - max(f_es), min(d_en) - max(f_en)
        print(
            f"{a:>5.2f}{min(d_es):>13.3f}{max(f_es):>14.3f}{h_es:>+11.3f}"
            f"{min(d_en):>13.3f}{max(f_en):>14.3f}{h_en:>+11.3f}"
        )
        if h_es > mejor_hueco:
            mejor_alfa, mejor_hueco = a, h_es

    print(f"\nmayor hueco en español: α = {mejor_alfa:.2f}  →  {mejor_hueco:+.3f}")

    # ------------------------------------------------------------------ #
    # 6. Top-1 antes y después, en TEXTO
    # ------------------------------------------------------------------ #
    # El «10/10 por escenario» del régimen denso era un proxy que mentía: el
    # escenario acertaba y el fragmento no respondía la pregunta. Aquí va el texto
    # para que la pertinencia se juzgue leyendo, que es la única forma honesta.
    print("\n" + "=" * 100)
    print("TOP-1 DE CADA CONSULTA CUBIERTA — DENSO PURO (α=1,0) frente a HÍBRIDO")
    print("=" * 100)
    for i, (consulta, _) in enumerate(EN_CORPUS, 1):
        antes = consultar(consulta, 1, 1.0)
        despues = consultar(consulta, 1, args.alfa)
        print(f"\n{i}. {consulta}")
        for etiqueta, lista in (("ANTES  (denso)", antes), ("DESPUÉS(híbrido)", despues)):
            if not lista:
                print(f"   {etiqueta}: —")
                continue
            f = lista[0]
            print(
                f"   {etiqueta}  score {f.score:.3f} "
                f"(denso {f.score_denso:.3f} · léxico {f.score_lexico:.3f})  "
                f"p.{f.pagina} {f.ruta_relativa[:60]}"
            )
            print(f"      «{_recorte(f.texto, 200)}»")

    print(f"\nConfigurado hoy: RAG_UMBRAL={cfg.rag_umbral:g}  RAG_ALFA={cfg.rag_alfa:g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
