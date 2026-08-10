"""La política se importa desde UN solo archivo del árbol de producción.

Por qué merece un test propio: la separación que sostiene todo el diseño —«la
clase clínica no sale del LLM, sale de `politica.decidir`»— es cierta mientras
ningún otro módulo pueda decidir por su cuenta. Un `import politica` nuevo en
`app/api.py` para «resolver rapidito» un caso particular no rompería ninguna
prueba de comportamiento, y sin embargo abriría un segundo punto de decisión.
Esto lo convierte en un fallo visible.

Alcance: los archivos que git conoce —rastreados **más** los no rastreados que no
estén ignorados (`git ls-files -c -o --exclude-standard`, el mismo criterio que
`scripts/sin_rutas_absolutas.sh`)—. Incluir los segundos es deliberado: un
archivo recién escrito y todavía sin commit es justo el que más probabilidad
tiene de traer el import de más, y mirar solo lo ya rastreado lo dejaría pasar
hasta después del commit, que es cuando ya nadie vuelve a mirar.

`tests/` y `scripts/` quedan fuera, y no por comodidad: son las herramientas que
verifican la política, y una herramienta de verificación tiene que poder
importar lo que verifica (`scripts/reejecutar_decisiones.py` no existiría si no).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
ARCHIVO_AUTORIZADO = "app/dialogo/orquestador.py"

# `import politica`, `import politica as x`, `from politica import y`,
# `from politica.motor import z`. No cuenta dentro de comentarios ni de cadenas.
PATRON = re.compile(r"^\s*(?:import\s+politica\b|from\s+politica(?:\.\w+)*\s+import\b)")


def archivos_rastreados(prefijo: str) -> list[Path]:
    salida = subprocess.run(
        ["git", "-C", str(RAIZ), "ls-files", "-c", "-o", "--exclude-standard", "--", prefijo],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\n")
    return [RAIZ / linea for linea in salida if linea.endswith(".py")]


def importan_politica(archivos: list[Path]) -> set[str]:
    culpables = set()
    for archivo in archivos:
        texto = archivo.read_text(encoding="utf-8")
        if any(PATRON.match(linea) for linea in texto.splitlines()):
            culpables.add(archivo.relative_to(RAIZ).as_posix())
    return culpables


def test_git_conoce_el_arbol_de_la_aplicacion() -> None:
    """Si git no devuelve nada, el test de abajo pasaría vacío y no probaría nada."""
    assert archivos_rastreados("app"), "git no rastrea ningún .py bajo app/"


def test_solo_el_orquestador_importa_politica() -> None:
    assert importan_politica(archivos_rastreados("app")) == {ARCHIVO_AUTORIZADO}


def test_el_orquestador_sigue_existiendo_y_expone_el_turno() -> None:
    """Que el import esté en el archivo correcto no sirve si el archivo cambió
    de papel: el punto de decisión tiene que seguir siendo el del turno."""
    from app.dialogo import orquestador

    assert hasattr(orquestador, "procesar_turno")
    assert hasattr(orquestador, "abrir_llamada")


@pytest.mark.parametrize("prefijo", ["politica", "configuracion"])
def test_el_resto_del_arbol_no_importa_politica(prefijo: str) -> None:
    """Ni la propia política (se importa a sí misma por rutas relativas) ni la
    configuración pueden traer un import absoluto del módulo."""
    assert not importan_politica(archivos_rastreados(prefijo))
