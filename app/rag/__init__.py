"""Recuperación sobre el corpus. NO decide nada clínico.

Lo que este paquete hace y lo que NO hace, porque la diferencia es la propiedad
central del sistema:

* **Hace**: responder preguntas del paciente citando el corpus, y declarar su
  límite cuando el corpus no alcanza.
* **NO hace**: producir, alterar ni influir la clase clínica. Esa sale de
  `politica.decidir` sobre las señales extraídas, y de ningún otro sitio. El
  texto que devuelve el RAG entra en la respuesta hablada como preámbulo y nunca
  toca `politica.Observacion`. Lo verifica `tests/test_rag_no_altera_clase.py`.

El paquete está partido en dos mitades por una razón operativa, no estética:

* **Puras** (`tipos`, `troceo`, `idioma`, `respuesta`): solo librería estándar.
  Se pueden importar —y probar— sin chromadb, sin onnxruntime y sin el modelo de
  embeddings. Son las que importa `app/dialogo/orquestador.py`.
* **Con dependencias** (`extraccion` → pypdf, `indice` → chromadb): se importan
  de forma diferida, dentro de la función que las usa. Así la suite de tests
  corre en una máquina que solo tiene pytest, igual que hasta 3.1.
"""

from __future__ import annotations

from app.rag.tipos import Cita, Fragmento, Pagina, Trozo

__all__ = ["Cita", "Fragmento", "Pagina", "Trozo"]
