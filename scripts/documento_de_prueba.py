#!/usr/bin/env python3
"""BANCO DE PRUEBAS de la consola: genera un PDF ajeno al corpus.

**No es parte de la aplicación y nunca se importa desde `app/`.** Es una
herramienta de verificación, del mismo tipo que `scripts/stt_de_prueba.py`.

Para qué existe
---------------
La compuerta G5 se prueba con un documento que **no está en el corpus**: subir uno
de los 107 PDFs del reto no demostraría nada, porque el agente ya podía
responderlo antes de subirlo. Hace falta un documento con un dato que solo él
contenga, para que el ciclo

    preguntar → «no tengo el dato» → subir → preguntar → responde citándolo
              → eliminar → preguntar → «no tengo el dato»

signifique algo.

Por qué un PDF de verdad y no un `.txt`
---------------------------------------
El endpoint acepta las dos cosas, pero el reto pide PDF y el camino del PDF es el
que tiene partes móviles: `pypdf`, la extracción por página, y la detección del
documento sin capa de texto. Un `.txt` saltaría justo lo que hay que verificar.

Se escribe el PDF a mano —unos objetos y un flujo de texto— en vez de traer una
biblioteca de generación: sería una dependencia nueva en `requirements-dev.txt`
para producir un archivo de dos páginas.

Uso:

    python3 scripts/documento_de_prueba.py --salida /tmp/protocolo.pdf
"""

from __future__ import annotations

import argparse
from pathlib import Path

# El contenido es FICTICIO y deliberadamente específico: un nombre de protocolo,
# un número de teléfono y unos horarios que no existen en ninguno de los 107 PDFs
# del corpus. Así, «¿el agente sabe esto?» tiene una respuesta binaria y
# comprobable, en vez de depender de si el corpus lo cubría un poco.
PAGINAS: list[list[str]] = [
    [
        "PROTOCOLO ANTARES DE SEGUIMIENTO DOMICILIARIO",
        "Clinica Ficticia de Verificacion - documento de prueba",
        "",
        "1. LINEA DE ATENCION ANTARES",
        "",
        "La linea Antares atiende a los pacientes operados durante los",
        "primeros treinta dias del postoperatorio. El numero de la linea",
        "Antares es el 604 555 0142 y atiende de lunes a sabado entre",
        "las siete de la manana y las nueve de la noche.",
        "",
        "Fuera de ese horario el paciente debe acudir al servicio de",
        "urgencias mas cercano y no esperar a la linea Antares.",
    ],
    [
        "2. CONTROL ANTARES A LOS ONCE DIAS",
        "",
        "El protocolo Antares fija un control presencial a los once dias",
        "de la cirugia, distinto del control habitual. En ese control se",
        "revisa la herida, se retiran los puntos si procede y se entrega",
        "la tarjeta Antares de seguimiento.",
        "",
        "El paciente debe llevar a ese control la tarjeta Antares y la",
        "lista de medicamentos que este tomando.",
    ],
]


def _flujo(lineas: list[str]) -> bytes:
    """Un flujo de contenido PDF: fuente, posición y una línea por `Tj`."""
    cuerpo = ["BT", "/F1 12 Tf", "14 TL", "56 760 Td"]
    for linea in lineas:
        texto = linea.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        cuerpo.append(f"({texto}) Tj T*")
    cuerpo.append("ET")
    return "\n".join(cuerpo).encode("latin-1", "replace")


def construir(paginas: list[list[str]]) -> bytes:
    """PDF mínimo pero válido: catálogo, páginas, fuente y un flujo por página."""
    objetos: list[bytes] = []

    def agregar(cuerpo: bytes) -> int:
        objetos.append(cuerpo)
        return len(objetos)  # los números de objeto son 1-based

    n_paginas = len(paginas)
    # Reserva de números: 1 catálogo, 2 árbol de páginas, 3 fuente,
    # luego (página, flujo) por cada una.
    id_catalogo, id_arbol, id_fuente = 1, 2, 3
    ids_pagina = [4 + 2 * i for i in range(n_paginas)]
    ids_flujo = [5 + 2 * i for i in range(n_paginas)]

    agregar(f"<< /Type /Catalog /Pages {id_arbol} 0 R >>".encode())
    hijos = " ".join(f"{i} 0 R" for i in ids_pagina)
    agregar(f"<< /Type /Pages /Kids [{hijos}] /Count {n_paginas} >>".encode())
    agregar(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    for lineas, id_pagina, id_flujo in zip(paginas, ids_pagina, ids_flujo):
        agregar(
            (
                f"<< /Type /Page /Parent {id_arbol} 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {id_fuente} 0 R >> >> "
                f"/Contents {id_flujo} 0 R >>"
            ).encode()
        )
        flujo = _flujo(lineas)
        agregar(b"<< /Length " + str(len(flujo)).encode() + b" >>\nstream\n" + flujo + b"\nendstream")

    salida = bytearray(b"%PDF-1.4\n")
    desplazamientos: list[int] = []
    for numero, cuerpo in enumerate(objetos, 1):
        desplazamientos.append(len(salida))
        salida += f"{numero} 0 obj\n".encode() + cuerpo + b"\nendobj\n"

    inicio_xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n".encode()
    salida += b"0000000000 65535 f \n"
    for desplazamiento in desplazamientos:
        salida += f"{desplazamiento:010d} 00000 n \n".encode()
    salida += (
        f"trailer\n<< /Size {len(objetos) + 1} /Root {id_catalogo} 0 R >>\n"
        f"startxref\n{inicio_xref}\n%%EOF\n"
    ).encode()
    return bytes(salida)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--salida", type=Path, required=True)
    args = parser.parse_args()
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_bytes(construir(PAGINAS))
    print(f"escrito {args.salida} ({args.salida.stat().st_size} bytes, {len(PAGINAS)} páginas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
