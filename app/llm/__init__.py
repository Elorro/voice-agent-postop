"""Integración con el modelo de lenguaje: un cliente, dos roles.

`cliente.py` habla el protocolo OpenAI-compatible y no sabe para qué se le
llama. `extractor.py` (LLM #1) y `redactor.py` (LLM #2) son los dos roles, con
contratos deliberadamente distintos: el extractor produce datos y degrada a
AUSENTE; el redactor produce estilo y degrada a la plantilla.
"""
