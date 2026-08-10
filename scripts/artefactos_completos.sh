#!/bin/sh
#
# Falla si un directorio que DEBE viajar completo por git no viaja completo.
#
# Por qué existe, y por qué no basta con leer `.gitignore`
# --------------------------------------------------------
# Este mecanismo nos ha mordido DOS veces, y las dos con la misma forma:
#
#   D1 (2026-08-09)   `dataset/textos/` en `.gitignore`, heredado de cuando el
#                     corpus vivía fuera del repositorio. `git add dataset/`
#                     no commiteaba los 107 PDFs y no avisaba de nada.
#   F3.12 (2026-08-10) `*.sqlite3`, patrón genérico de la plantilla de Python,
#                     se tragaba `indice_base/chroma.sqlite3` —el catálogo de
#                     ChromaDB—. Los otros 6 archivos del índice sí viajaban,
#                     así que un clon limpio arrancaba con **0 fragmentos**: el
#                     agente declaraba su límite ante toda pregunta y G5 caía,
#                     sin un solo error visible en el arranque.
#
# En los dos casos la regla era **genérica** y estaba a doscientas líneas del
# artefacto que rompía. Leer `.gitignore` buscando el nombre del artefacto no
# encuentra nada: `*.sqlite3` no dice `chroma`, ni `indice_base`, ni `RAG`.
#
# La comprobación que sí vale es **contar archivos en disco contra los que git
# ve**. No depende de entender la regla, ni de que alguien recuerde revisarla:
# si los dos números difieren, algo no va a llegar al clon del jurado.
#
# Los dos fallos comparten además el peor síntoma posible: **el sistema arranca
# igual**. No hay excepción, ni log, ni fila roja en `/salud` —el índice es no
# bloqueante a propósito—. Solo un agente que responde «no tengo información
# sobre eso en mis fuentes» a todo. Por eso la compuerta va aquí, en el commit,
# y no en el arranque.
#
# Uso:
#   sh scripts/artefactos_completos.sh        # comprueba
#   sh scripts/artefactos_completos.sh -v     # además, el detalle por directorio
#
# Códigos de salida:  0 completo · 1 falta algo · 2 no pudo ejecutarse.

set -eu

# --- Los directorios que deben viajar completos -------------------------------
# Uno por línea: RUTA seguida del motivo. El motivo no es decoración: es lo que
# permite decidir, cuando esto falle dentro de seis meses, si la respuesta es
# añadir el archivo o sacar el directorio de esta lista.
#
#   dataset/      Corpus del reto (107 PDFs) y casos sintéticos. Viaja por git y
#                 NO dentro de la imagen: la rúbrica exige trazabilidad, y una
#                 cita del RAG solo es verificable si el evaluador puede abrir el
#                 documento citado. Sin él, `tests/test_dev_set.py` hace skip y
#                 el criterio de aceptación clínica no se puede reproducir.
#
#   indice_base/  Semilla del índice vectorial, YA CONSTRUIDA. Viaja por git y NO
#                 dentro de la imagen (`.dockerignore` la excluye) para que el
#                 jurado no descargue los mismos bytes dos veces. El entrypoint
#                 la siembra en el volumen al arrancar. Reconstruirla cuesta
#                 1 274 s de CPU, así que un clon sin ella no es «un poco peor»:
#                 es un clon sin RAG y sin G5.
ARTEFACTOS='dataset
indice_base'

# --- Umbrales de tamaño -------------------------------------------------------
# GitHub avisa a partir de 50 MiB y RECHAZA el push a partir de 100 MiB. Se falla
# en 95 para no descubrirlo con el push a medias; el margen es deliberado.
# Hoy `indice_base/chroma.sqlite3` son ~71,7 MiB: sale como AVISO, no como fallo.
AVISO_MIB=50
FALLO_MIB=95

VERBOSO=0
[ "${1:-}" = "-v" ] && VERBOSO=1

command -v git >/dev/null 2>&1 || { echo "error: hace falta git" >&2; exit 2; }
git rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    || { echo "error: esto no es un repositorio git" >&2; exit 2; }

cd "$(git rev-parse --show-toplevel)"

en_disco="$(mktemp)"
en_git="$(mktemp)"
faltan="$(mktemp)"
sobran="$(mktemp)"
hallazgos="$(mktemp)"
avisos="$(mktemp)"
trap 'rm -f "$en_disco" "$en_git" "$faltan" "$sobran" "$hallazgos" "$avisos"' \
     EXIT INT TERM

hubo_fallo=0

# Tamaño en MiB, con una cifra decimal, sin depender de `stat` (que difiere
# entre GNU y BSD). `wc -c` es POSIX y lee el archivo una vez.
mib() {
    bytes="$(wc -c < "$1" | tr -d ' ')"
    awk -v b="$bytes" 'BEGIN { printf "%.1f", b / 1048576 }'
}

for dir in $ARTEFACTOS; do
    if [ ! -d "$dir" ]; then
        echo "FALLO: el directorio «$dir» no existe en el árbol de trabajo." >&2
        echo "    Está declarado como artefacto que debe viajar completo." >&2
        hubo_fallo=1
        continue
    fi

    # Un salto de línea dentro de un nombre rompería la comparación línea a
    # línea de abajo. Antes que reportar mal, se para: es patológico y no ha
    # pasado nunca, pero un falso OK aquí es exactamente lo que esto evita.
    if find "$dir" -type f -name '*
*' -print -quit | grep -q .; then
        echo "error: hay nombres de archivo con saltos de línea en «$dir»;" >&2
        echo "       esta comprobación no puede compararlos con fiabilidad." >&2
        exit 2
    fi

    # `-z` y no la salida normal: `git ls-files` CITA las rutas no ASCII
    # (`"dataset/textos/Recomendaci\303\263n.pdf"`), y el corpus está en
    # español. Comparar eso contra `find` daría diferencias inventadas en cada
    # archivo con tilde. Con `-z` salen crudas.
    #
    # `LC_ALL=C` en el sort Y en el comm: `comm` valida el orden con la
    # colación de su propio locale, así que ordenar con una y comparar con otra
    # aborta con «el fichero no está ordenado».
    find "$dir" -type f -print | LC_ALL=C sort > "$en_disco"
    git ls-files -z -- "$dir" | tr '\0' '\n' | LC_ALL=C sort > "$en_git"

    n_disco="$(wc -l < "$en_disco" | tr -d ' ')"
    n_git="$(wc -l < "$en_git" | tr -d ' ')"

    LC_ALL=C comm -23 "$en_disco" "$en_git" > "$faltan"   # en disco y NO en git
    LC_ALL=C comm -13 "$en_disco" "$en_git" > "$sobran"   # en git y NO en disco

    if [ "$VERBOSO" -eq 1 ]; then
        echo "$dir: $n_disco archivos en disco, $n_git vistos por git."
    fi

    if [ -s "$faltan" ]; then
        hubo_fallo=1
        {
            echo "FALLO: «$dir» NO viaja completo."
            echo "    en disco: $n_disco · que git ve: $n_git · " \
                 "que NO llegarían al clon: $(wc -l < "$faltan" | tr -d ' ')"
            echo ""
            while IFS= read -r archivo; do
                echo "    $archivo"
                # Dos causas distintas, dos arreglos distintos, y distinguirlas
                # es todo el valor de esta compuerta:
                #
                #   ignorado    -> hay que tocar `.gitignore` (caso D1 y F3.12)
                #   sin añadir  -> `.gitignore` ya está bien y falta `git add`
                #
                # La decisión se toma con `-q` y NO con `-v`: **`-v` sale 0
                # también cuando la regla que casa es de NEGACIÓN** (`!…`), es
                # decir cuando el archivo NO está ignorado. Usar `-v` para
                # decidir reporta «ignorado por !indice_base/*.sqlite3», que es
                # justo lo contrario de lo que pasa. Comprobado el 2026-08-10.
                if git check-ignore -q -- "$archivo" 2>/dev/null; then
                    regla="$(git check-ignore -v -- "$archivo" 2>/dev/null || true)"
                    echo "        IGNORADO por: ${regla:-(regla no localizada)}"
                    echo "        arreglo: corrija esa regla en .gitignore, luego \`git add\`"
                else
                    negacion="$(git check-ignore -v -- "$archivo" 2>/dev/null || true)"
                    echo "        SIN AÑADIR: ninguna regla lo ignora."
                    [ -n "$negacion" ] && \
                        echo "        (lo re-incluye: $negacion)"
                    echo "        arreglo: \`git add -- $archivo\`"
                fi
            done < "$faltan"
        } >> "$hallazgos"
    fi

    if [ -s "$sobran" ]; then
        hubo_fallo=1
        {
            echo "FALLO: «$dir» tiene archivos que git conoce y NO están en disco."
            echo "    El clon del jurado los tendría y esta copia no. ¿Borrado sin commitear?"
            echo ""
            sed 's/^/    /' "$sobran"
        } >> "$hallazgos"
    fi

    # --- Tamaños, sobre lo que hay en disco ----------------------------------
    while IFS= read -r archivo; do
        tam="$(mib "$archivo")"
        supera_fallo="$(awk -v t="$tam" -v u="$FALLO_MIB" 'BEGIN{print (t>u)?1:0}')"
        supera_aviso="$(awk -v t="$tam" -v u="$AVISO_MIB" 'BEGIN{print (t>u)?1:0}')"
        if [ "$supera_fallo" = "1" ]; then
            hubo_fallo=1
            {
                echo "FALLO: $archivo pesa ${tam} MiB."
                echo "    GitHub RECHAZA el push por encima de 100 MiB; el tope de"
                echo "    esta compuerta es ${FALLO_MIB} para no descubrirlo a mitad del push."
                echo ""
            } >> "$hallazgos"
        elif [ "$supera_aviso" = "1" ]; then
            echo "    $archivo — ${tam} MiB" >> "$avisos"
        fi
    done < "$en_disco"
done

if [ -s "$avisos" ]; then
    echo "AVISO: archivos por encima de ${AVISO_MIB} MiB. GitHub avisa a partir de ahí"
    echo "y rechaza a partir de 100 MiB; estos pasan, pero no hay sitio para otro igual."
    cat "$avisos"
    echo ""
fi

if [ "$hubo_fallo" -ne 0 ]; then
    [ -s "$hallazgos" ] && cat "$hallazgos"
    echo "Un artefacto incompleto NO produce ningún error al arrancar: el sistema"
    echo "levanta igual y se queda sin corpus o sin índice. Por eso se comprueba aquí."
    exit 1
fi

echo "OK: los artefactos declarados viajan completos por git."
exit 0
