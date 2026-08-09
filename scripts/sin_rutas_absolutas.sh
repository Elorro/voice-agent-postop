#!/bin/sh
#
# Falla si alguna ruta absoluta del HOST se coló en los archivos del repositorio.
#
# Por qué importa: el jurado sigue el README al pie de la letra en SU máquina.
# Un `/home/luis/...` en un comando, en `.env.example` o en el compose es un
# paso que allí no puede funcionar, y el operador no tiene forma de saber por
# qué falla. Este script es la compuerta que impide que vuelva a colarse.
#
# Uso:
#   sh scripts/sin_rutas_absolutas.sh        # lista los hallazgos
#   sh scripts/sin_rutas_absolutas.sh -v     # además, cuántos archivos revisó
#
# Códigos de salida:  0 limpio · 1 hay rutas absolutas · 2 no pudo ejecutarse.
#
# Alcance: archivos rastreados por git MÁS los no rastreados que no estén
# ignorados (`git ls-files -c -o --exclude-standard`). Incluir los segundos es
# deliberado: si solo mirara lo ya rastreado, un archivo recién creado —justo
# el que más probabilidad tiene de traer una ruta de la máquina donde se
# escribió— pasaría sin revisar hasta después del commit.
#
# NO se buscan rutas absolutas del CONTENEDOR (/app, /opt/voces,
# /opt/indice_base): son destinos de montaje, absolutos por obligación —Docker
# no admite destinos relativos en un bind— y no existen fuera del contenedor.

set -eu

VERBOSO=0
[ "${1:-}" = "-v" ] && VERBOSO=1

command -v git >/dev/null 2>&1 || { echo "error: hace falta git" >&2; exit 2; }
git rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    || { echo "error: esto no es un repositorio git" >&2; exit 2; }

cd "$(git rev-parse --show-toplevel)"

# Home de Linux, home de macOS, y la variable en sus dos formas de escritura.
PATRONES='(/home/|/Users/|\$\{HOME\}|\$HOME)'

# --- Exclusión dura: no se revisan y no se reportan ---------------------------
# REGISTRO FECHADO: archivos que documentan qué se corrió y dónde, incluida la
# ruta de la máquina donde se corrió. Editarlos a posteriori sería falsear el
# registro, y el jurado no ejecuta ni un comando de ahí.
#
#   docs/bitacora.md, docs/diseno/       — decisiones y diseño, fechados.
#   scripts/verificacion_hd1_salida.txt  — SALIDA CAPTURADA de una corrida del
#       oráculo. Estuvo hasta el 2026-08-09 en la lista de deuda, y era una
#       clasificación equivocada: la deuda es lo que hay que arreglar, y este
#       archivo no se va a arreglar nunca porque corregirlo sería reescribir
#       una salida que ya ocurrió. Es la misma categoría que la bitácora.
#
# Este script se excluye a sí mismo porque contiene los patrones que busca.

# --- Deuda registrada: se revisan, se reportan, NO bloquean -------------------
# VACÍA desde el 2026-08-09. La deuda de la Fase 2.1 quedó saldada:
# `tests/README.md` y `scripts/verificacion_hd1.py` usan `./dataset`, que además
# pasó a ser la ruta correcta al entrar el dataset al repositorio por git.
#
# El mecanismo se conserva aunque no tenga clientes hoy: si vuelve a aparecer un
# archivo con una ruta absoluta que no se pueda corregir de inmediato, va aquí y
# se reporta en cada corrida en vez de excluirse en silencio, que es lo que
# convertiría esta compuerta en un adorno.
DEUDA=""

listado="$(mktemp)"
hallazgos="$(mktemp)"
avisos="$(mktemp)"
trap 'rm -f "$listado" "$hallazgos" "$avisos"' EXIT INT TERM

# Las pathspec se arman en los parámetros posicionales, no por interpolación en
# una cadena: así los `:(exclude)…` llegan a git como argumentos íntegros.
set -- ':(exclude)docs/bitacora.md' \
       ':(exclude)docs/diseno' \
       ':(exclude)scripts/verificacion_hd1_salida.txt' \
       ':(exclude)scripts/sin_rutas_absolutas.sh'
for archivo_en_deuda in $DEUDA; do
    set -- "$@" ":(exclude)${archivo_en_deuda}"
done

git ls-files -c -o --exclude-standard -z -- "$@" > "$listado"

if [ ! -s "$listado" ]; then
    echo "error: git no devolvió ningún archivo que revisar" >&2
    exit 2
fi

# -I omite binarios: los .docx y .xlsx del dataset darían falsos positivos.
# `|| true` porque grep sale 1 cuando no encuentra nada, que aquí es el éxito.
xargs -0 grep -nIE "$PATRONES" -- < "$listado" > "$hallazgos" 2>/dev/null || true

for d in $DEUDA; do
    [ -f "$d" ] || continue
    grep -nIE "$PATRONES" -- "$d" 2>/dev/null | sed "s|^|$d:|" >> "$avisos" || true
done

if [ "$VERBOSO" -eq 1 ]; then
    n_archivos="$(tr -dc '\0' < "$listado" | wc -c | tr -d ' ')"
    echo "revisados $n_archivos archivos (más $(echo $DEUDA | wc -w) en deuda registrada)."
fi

if [ -s "$avisos" ]; then
    echo "AVISO: deuda registrada de la Fase 2.1, no bloquea esta compuerta."
    sed 's/^/    /' "$avisos"
    echo ""
fi

if [ -s "$hallazgos" ]; then
    echo "FALLO: rutas absolutas del host en archivos del repositorio."
    echo ""
    sed 's/^/    /' "$hallazgos"
    echo ""
    echo "Sustitúyalas por una variable de entorno con default relativo a la"
    echo "raíz del repo (ver app/config.py y .env.example)."
    exit 1
fi

echo "OK: ningún archivo del repositorio contiene rutas absolutas del host."
exit 0
