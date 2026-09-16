# voice-agent-postop — Agente de voz para seguimiento postoperatorio

**Qué es.** Agente conversacional de voz, en tiempo real y en español colombiano, que llama
a pacientes recién operados, indaga sobre su recuperación (dolor, fiebre, herida, movilidad),
clasifica la criticidad del caso y decide si escalar a personal clínico. El seguimiento
post-op depende hoy de personal humano: es costoso, no escala, y el paciente describe
síntomas en lenguaje ambiguo y regional ("me duele aquí abajito"). El agente absorbe ese
primer contacto y filtra lo que sí necesita un humano.

**Arquitectura (en esencia).** Aplicación **FastAPI** de un solo contenedor que orquesta el
pipeline de cada turno —STT → recuperación RAG → LLM → TTS— bajo un presupuesto de latencia
pensado para que se sienta conversación.
- *Voz:* STT con **Whisper Large V3 (Groq)**; síntesis con **Piper local** (`es_MX-ald-medium`).
- *Razonamiento:* **Gemini Flash** como LLM primario, restringido a extractor/redactor —**nunca clasifica**—; respaldo local con **llama3.2 vía Ollama**.
- *RAG clínico:* **ChromaDB** embebido con recuperación **híbrida densa+léxica** sobre un corpus de guías y protocolos. Cada respuesta registra el documento que la sustenta (**trazabilidad**) y el agente declara "no tengo esa información" en vez de improvisar.
- *Conocimiento vivo:* el corpus se actualiza en caliente desde una consola —subir un documento lo hace disponible; eliminarlo lo olvida— sin arrastrar versiones previas.
- *Decisión:* módulo `politica/` en **Python puro (stdlib)**, único punto de clasificación (verde/amarillo/rojo); no consume salida del LLM.

**Decisiones de diseño con rigor.**
- **Asimetría clínica como principio rector.** Un falso negativo (no escalar un caso grave) es una falla catastrófica, no un error simétrico; la política **prioriza sensibilidad sobre rojo** por encima de accuracy. El umbral no maximiza aciertos: minimiza el costo esperado bajo una matriz de costos asimétrica.
- **Decisión determinista y auditable.** Separar el clasificador del LLM la hace reproducible y **resistente a prompt injection**: la transcripción del paciente es DATO, no instrucción (separación de canales verificada con ataques en vivo).
- **Incertidumbre explícita.** Ante evidencia insuficiente el agente **repregunta antes de decidir**, no clasifica con un solo turno. Las limitaciones (embedder, tamaño del set de validación, fallo de proveedor) se declaran con mediciones y etiquetas epistémicas en todo el repo.

**Stack:** Python · FastAPI · Docker · ChromaDB · Whisper Large V3 (Groq) · Gemini Flash · Piper TTS · Ollama (llama3.2).
