#!/bin/sh
#
# Arranque del contenedor: prepara los directorios de datos, siembra el índice
# desde /opt/indice_base si hace falta, y cede el proceso a uvicorn.
#
# Este archivo DEBE llegar al contenedor con finales de línea LF. Con CRLF, el
# kernel intenta ejecutar el intérprete "/bin/sh\r" y falla con "exec format
# error" o "no such file or directory", sin más pistas. Lo garantiza
# .gitattributes (`*.sh text eol=lf`), que por eso es el primer archivo del
# repositorio.
#
# POSIX sh a propósito: la imagen es Debian slim y /bin/sh es dash, no bash.

set -eu

registrar() {
    printf '%s [arranque] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

# --- Configuración -----------------------------------------------------------
# Los mismos nombres y defaults que app/config.py. Los relativos se resuelven
# contra /app, que es el WORKDIR y donde compose ancla los montajes.

cd "${DIR_APP:-/app}"

INDICE_DIR="${INDICE_DIR:-./datos/indice}"
INDICE_SEMILLA_DIR="${INDICE_SEMILLA_DIR:-/opt/indice_base}"
SUBIDOS_DIR="${SUBIDOS_DIR:-./datos/subidos}"
LOGS_DIR="${LOGS_DIR:-./datos/logs}"
LLAMADAS_DIR="${LLAMADAS_DIR:-./datos/llamadas}"
DIRECCION_BIND="${DIRECCION_BIND:-0.0.0.0}"
PUERTO="${PUERTO:-8080}"

# Subdirectorio que ChromaDB abre de verdad. Ver app/config.py::almacen_indice:
# es un nivel por debajo del volumen para que la siembra se pueda publicar con
# un único `mv` de directorio, que dentro del mismo filesystem sí es atómico.
ALMACEN="${INDICE_DIR}/actual"
MARCADOR="${INDICE_DIR}/.version_semilla"

esta_vacio() {
    # 0 si el directorio no existe o no tiene entradas (incluidas ocultas).
    [ ! -d "$1" ] || [ -z "$(ls -A "$1" 2>/dev/null)" ]
}

# --- Directorios de datos ----------------------------------------------------

mkdir -p "$INDICE_DIR" "$SUBIDOS_DIR" "$LOGS_DIR" "$LLAMADAS_DIR"

# --- Limpieza de un arranque anterior interrumpido ---------------------------
# Un `.siembra.*` sobreviviente significa que una copia previa se cortó a la
# mitad. Nunca se promueve: se borra y se vuelve a copiar desde cero. El
# directorio publicado (`actual`) no puede estar a medias porque solo existe
# tras el `mv`, que es todo-o-nada.

for residuo in "$INDICE_DIR"/.siembra.*; do
    [ -e "$residuo" ] || continue
    registrar "descarto siembra incompleta de un arranque previo: $residuo"
    rm -rf "$residuo"
done

# --- Siembra del índice ------------------------------------------------------

sembrar() {
    if ! esta_vacio "$ALMACEN"; then
        registrar "índice ya presente en ${ALMACEN}; no se siembra"
        if [ -f "$MARCADOR" ]; then
            registrar "marcador: $(cat "$MARCADOR" | tr '\n' ' ')"
        fi
        return 0
    fi

    if esta_vacio "$INDICE_SEMILLA_DIR"; then
        registrar "sin semilla: ${INDICE_SEMILLA_DIR} no existe o está vacío"
        registrar "el índice arranca vacío (0 documentos). Es lo esperado hoy:"
        registrar "el indexador del corpus todavía no existe."
        mkdir -p "$ALMACEN"
        return 0
    fi

    temporal="${INDICE_DIR}/.siembra.$$"
    rm -rf "$temporal"
    mkdir -p "$temporal"

    registrar "sembrando índice desde ${INDICE_SEMILLA_DIR}…"
    # `cp -a … /.` copia el CONTENIDO, no el directorio, y preserva metadatos.
    cp -a "${INDICE_SEMILLA_DIR}/." "${temporal}/"

    # `actual` puede existir vacío (creado por un arranque previo sin semilla).
    # rmdir solo tiene éxito si está vacío: si no lo está, hay un índice real
    # y no se toca.
    rmdir "$ALMACEN" 2>/dev/null || true
    if [ -e "$ALMACEN" ]; then
        registrar "apareció un índice en ${ALMACEN} durante la siembra; la descarto"
        rm -rf "$temporal"
        return 0
    fi

    # Publicación atómica: hasta esta línea, `actual` no existe.
    mv "$temporal" "$ALMACEN"

    bytes="$(du -sk "$ALMACEN" 2>/dev/null | cut -f1 || echo '?')"
    version="sin-version"
    if [ -f "${INDICE_SEMILLA_DIR}/VERSION" ]; then
        version="$(head -n 1 "${INDICE_SEMILLA_DIR}/VERSION")"
    fi
    printf 'version=%s sembrado=%s origen=%s kib=%s\n' \
        "$version" "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$INDICE_SEMILLA_DIR" "$bytes" \
        > "${MARCADOR}.tmp"
    mv "${MARCADOR}.tmp" "$MARCADOR"

    registrar "índice sembrado (${bytes} KiB, versión ${version})"
}

sembrar

# --- Cesión del proceso ------------------------------------------------------
# Un argumento explícito gana, para poder abrir una shell de diagnóstico:
#   docker compose run --rm agente sh

if [ "$#" -gt 0 ]; then
    registrar "ejecutando orden explícita: $*"
    exec "$@"
fi

# UN SOLO WORKER, no negociable: ChromaDB persiste sobre SQLite con
# PersistentClient. Dos workers son dos procesos escribiendo el mismo archivo
# sin coordinación entre ellos; el resultado es corrupción del índice o bloqueo.
registrar "uvicorn en ${DIRECCION_BIND}:${PUERTO} con 1 worker"
exec uvicorn app.main:app \
    --host "$DIRECCION_BIND" \
    --port "$PUERTO" \
    --workers 1 \
    --proxy-headers
