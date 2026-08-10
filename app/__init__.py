"""Capa de aplicación: FastAPI, turno de voz, configuración y estado.

No contiene lógica clínica. La decisión clínica vive en `politica/`, que es
stdlib pura, y se importa desde **un único** archivo de este paquete:
`app/dialogo/orquestador.py`. Que sea uno solo no es estética: es lo que hace
imposible que otra parte del agente clasifique por su cuenta.
"""
