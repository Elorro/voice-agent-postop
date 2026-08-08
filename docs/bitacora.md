# Bitácora del proyecto — Voice Agent Post-Op

**Propósito.** Este archivo es el puente entre el repositorio local y el Project de claude.ai que actúa como arquitecto. Toda decisión técnica queda registrada aquí para que cualquier chat futuro del Project se sincronice leyendo un solo archivo. Alimenta además el informe final del reto (evidencia de proceso — criterio de 15 pts de repositorio/proceso).

**Convención epistemológica** (heredada de los documentos de diseño):
- `[HECHO]` — verificado sobre el dataset, los .md del reto o exploración reproducible.
- `[INFERENCIA]` — deducción a partir de hechos + razonamiento de diseño o clínico.
- `[ESPECULACIÓN]` — supuesto o parámetro sin medición directa. Declarado como tal.

**Documentos de diseño asociados** (entregados como .docx, fuente de detalle):
- Política de Decisión Clínica (Fase 1, punto 2).
- Protocolo de Validación (Fase 1, punto 3).

---

## Convenciones de trabajo del repositorio

### Flujo de git — trunk-based con ramas de spike efímeras
- `[INFERENCIA]` Se eligió **trunk-based development** sobre git-flow (main/develop/feature). Razón: git-flow resuelve coordinación multi-dev y separación de releases concurrentes, y este es un reto INDIVIDUAL con entrega única (10 ago) — ninguno de esos problemas aplica. La revisión de código ya ocurre en fase de diseño en el Project, antes de escribir código; un PR self-approved sería teatro.
- `[INFERENCIA]` **main es la línea de trabajo, siempre levantable.** Protege la compuerta G2 (el jurado clona main y lo levanta en ≤15 min): mantener una develop paralela arriesga que main quede desfasado de lo documentado y probado, modo de fallo inaceptable a días del cierre.
- `[INFERENCIA]` **Ramas `spike/*` solo para riesgo real** (algo que puede romper lo que funciona o que podría no cuajar). Viven horas o pocos días y se borran al integrar. El disparador es "voy a arriesgar algo que ya funciona", no "empieza una fase". Primer candidato: `spike/gpu-local` (ruta GPU de disponibilidad incierta).
- `[INFERENCIA]` **Las fases se mapean a tags y a commits, no a ramas.** Una fase es unidad de diseño/decisión (vive en el Project y esta bitácora), no de aislamiento de código. Al cerrar una fase con código se crea un tag anotado (`fase-1-cerrada`, etc.) como punto de restauración y trazabilidad para el informe.
- `[INFERENCIA]` **Convención de commits con prefijo de fase** para la trazabilidad fase→código: `[F2] feat(policy): ...`, `[F3] test(voice): ...`. Da el hilo que el informe y esta bitácora necesitan sin topología de ramas.

---

## Fase 1 — Diseño de la política de decisión clínica
**Estado: CERRADA.** Fecha de cierre: 2026-08-08.

Entregables: exploración de datos (punto 1), documento de política (punto 2), protocolo de validación (punto 3). Los tres validados por el arquitecto.

### Jerarquía de prioridades (derivada de la rúbrica)
- `[HECHO]` El núcleo que decide finalistas es RAG (20 pts) + Lógica de decisión y escalamiento (20 pts) = 40 pts, y es el primer desempate.
- `[INFERENCIA]` La voz (15 pts puntuables, pero compuerta eliminatoria G4) debe llegar a "funciona y fluye" sin eliminar; el esfuerzo diferencial va al motor de decisión y al RAG con trazabilidad. No sobre-invertir en voz a costa del núcleo.

### Arquitectura de la política — tres niveles
- `[INFERENCIA]` La estructura emergió de los datos, no se impuso. Orden de precedencia:
  1. **Nivel 0 — Enrutador temporal.** `dia_postop` particiona en régimen temprano (días 1,3) y tardío (días 7,14) ANTES de aplicar cualquier umbral. No es una feature más: es un nodo de enrutamiento previo.
  2. **Nivel 1 — Banderas rojas categóricas (piso de seguridad).** Señales de pureza 1.0 que fuerzan ROJO en cualquier régimen. Ancladas al corpus clínico, no a la distribución del dataset.
  3. **Nivel 2 — Agregación de señales blandas.** Separa verde de amarillo por conteo de señales de preocupación, con umbrales condicionados al régimen. Solo se evalúa si no disparó Nivel 1.

### Hallazgo estructural — el eje temporal reorganiza el espacio
- `[HECHO]` Los 12 casos rojos no existen antes del día 7 (0 rojos en días 1 y 3; 6 rojos en día 7 y 6 en día 14). Los amarillos desaparecen en día 14 (0 amarillos ese día).
- `[INFERENCIA]` Lógica clínica: una complicación postoperatoria real necesita tiempo para manifestarse. En día 14 el caso ya se resolvió hacia un extremo (verde o rojo); el amarillo intermedio se disipa.
- `[INFERENCIA]` Decisión (Opción B): los umbrales se ajustan por régimen, PERO las banderas rojas categóricas escalan en cualquier día. El agente nunca razona "es día 2, imposible que sea rojo". La ausencia de rojos tempranos es del generador sintético, no una ley clínica; anclarse a ella sería overfitting al dataset.

### Matriz de costos (asimetría formalizada, no ad hoc)
- `[HECHO]` Con desbalance 123/25/12, optimizar accuracy es una métrica basura: predecir siempre "verde" da 76.9% y recall-rojo = 0.
- `[INFERENCIA]` Orden final de costos: **C_FN ≫ c₃ ≫ c₁ > c₄ > c₅ > c₂**.
  - Corrección de c₃: amarillo NO llega a un humano (es vigilancia/seguimiento, no escalamiento). Por tanto un rojo cerrado en amarillo es funcionalmente un FALSO NEGATIVO de escalamiento, casi tan grave como cerrarlo en verde. La columna `real=rojo` tiene DOS celdas catastróficas: (verde,rojo) y (amarillo,rojo).
  - Empates rotos: c₁ > c₅ (perder un amarillo deja al paciente sin vigilancia; sobre-escalarlo solo cuesta una revisión). c₄ > c₂ (distancia 2 > distancia 1; c₄ no es despreciable: escalar verdes lee como agente alarmista, y el jurado prueba verdes).
- `[INFERENCIA]` Decisión óptima bayesiana: d*(e) = argmin_d Σ_y C(d,y)·P(y|e). Con dos celdas ≈ C_FN en la columna rojo, el umbral de P(rojo|e) para NO escalar se vuelve casi cero: en la frontera amarillo-vs-rojo, la duda resuelve a rojo siempre. La sensibilidad sobre rojo cae de la matriz, no se impone.
- `[ESPECULACIÓN]` C_FN no se calibra numéricamente. Se operacionaliza con dos mecanismos discretos: el piso de banderas rojas (P(rojo|e)=1 efectivo) y la compuerta de indagación (ante P(rojo|e) intermedia, no clasificar: preguntar).

### Criterio "amarillo no es clase terminal con bandera roja pendiente"
- `[INFERENCIA]` Si el vector es compatible con amarillo pero queda una bandera roja sin descartar, el caso NO cierra en amarillo: o se indaga hasta descartarla, o se escala a rojo. Solo cierra en amarillo cuando toda bandera roja quedó activamente descartada.
- `[INFERENCIA]` Corolario — qué es el "AMARILLO con escalamiento" que genera registro: NO es el amarillo-con-bandera-pendiente (ese nunca es terminal), sino el amarillo cerrado por AGOTAMIENTO del presupuesto de indagación, con un discriminador verde↔amarillo irresuelto y todas las banderas rojas ya descartadas. Carga incertidumbre residual → registro con campo confianza/incertidumbre marcado. Un amarillo con evidencia completa (S3) es terminal y no requiere registro.

### Política de indagación (separa clasificador de un turno de agente que indaga)
- `[INFERENCIA]` Criterio de suficiencia de evidencia (basta uno para clasificar):
  - S1 — Bandera roja confirmada → ROJO inmediato.
  - S2 — Verde robusto: todas las señales del núcleo obtenidas, ninguna de preocupación → VERDE.
  - S3 — Amarillo saturado: ≥2 señales de preocupación confirmadas, ninguna bandera roja pendiente → AMARILLO terminal.
  - Si ninguno se cumple → REPREGUNTAR (evidencia insuficiente).
- `[ESPECULACIÓN]` Doble tope de indagación (a calibrar en prototipo, Fase 3):
  - Por señal (profundidad): 2–3 repreguntas máximo sobre una misma señal.
  - Global de llamada (amplitud): 6–8 turnos de repregunta máximo. Es la restricción que muerde (peor caso sin tope global ≈ 18 turnos). Coherente con los 6 turnos de paciente por caso observados en el dataset.
- `[INFERENCIA]` Prioridad bajo presupuesto escaso: indagar primero las señales adyacentes a una bandera roja (colapsan P(rojo|e) hacia 0 ó 1). Los discriminadores verde↔amarillo se indagan solo si sobra presupuesto.
- `[INFERENCIA]` Escalamiento graduado al agotar presupuesto: señal irresuelta adyacente a bandera roja → ROJO; señal irresuelta solo discriminador V↔A → AMARILLO (nunca verde).
- `[INFERENCIA]` Invariante duro (no se gradúa): nunca cerrar en verde con evidencia insuficiente.

### Enmienda de dolor (partición del umbral, verificada en datos)
- `[HECHO]` En régimen tardío (días 7,14): `dolor_nrs ∈ {7,8,9}` aparece SOLO en rojo (pureza 1.0); ningún verde/amarillo tardío supera 6. La banda {5,6} es zona compartida amarillo/rojo (6 amarillos y 10 rojos).
- `[INFERENCIA]` Partición del umbral:
  - `dolor ≥ 7` en tardío → **bandera roja de Nivel 1** (mismo estatus que purulenta/incapacitante/fiebre). Captura el único rojo-antes-sutil (caso ...42_00017_7, dolor=9) por bandera, no por agregación.
  - `dolor ∈ {5,6}` no resuelto en tardío → **adyacente a bandera** en el escalamiento graduado → ROJO.
- `[HECHO]` La bandera dolor≥7 se restringe a régimen TARDÍO. En día 1 el dolor postquirúrgico agudo llega legítimamente a 6 en verdes; un umbral de dolor bajo ahí sería falso-positivo masivo.
- `[INFERENCIA]` Costo declarado: escalar todo `dolor ≥ 5` habría comprado 6 falsos positivos amarillo→rojo. La partición captura el ex-sutil pagando solo un c₅ residual bajo evasión (amarillo de dolor 5–6 con dolor irresuelto → rojo). Costo ≈ 0 en la muestra para la bandera ≥7.
- `[INFERENCIA]` Honestidad: esto reclasifica el único rojo-sutil como claro (12 claros / 0 sutiles en la muestra), pero NO significa cobertura de rojos-sutiles en general. Un rojo-sutil hipotético sin señal fuerte alguna seguiría siendo un hueco de detección no observado en esta muestra.
- **DEUDA (baja a fase de RAG):** la bandera dolor≥7-tardío se derivó de los 160 casos; su justificación actual es "pureza 1.0 en los datos" — hecho sobre dataset sintético, no argumento clínico. Circularidad parcial: el criterio 1 de validación la valida contra los mismos casos de los que salió. Tarea: localizar en los 107 PDFs el criterio clínico que sustenta dolor severo en recuperación tardía como signo de alarma, y citarlo en el registro de escalamiento como las demás banderas. Si el corpus NO la sustenta, hay que saberlo antes de la sesión de evaluación, no durante.

### Exclusión de arquetipo_trayectoria
- `[HECHO]` `recuperacion_normal` → 98.7% verde; `complicacion_real` contiene el 100% de los rojos. El arquetipo es casi una etiqueta disfrazada.
- `[INFERENCIA]` EXCLUIDO de la política de runtime: es variable latente del generador que el agente no observa (el paciente no la reporta por teléfono). Usarla sería look-ahead / data leakage. Solo sirve para entender la estructura del dataset.

### Registro de escalamiento y comunicación al paciente
- `[INFERENCIA]` Al clasificar ROJO —o AMARILLO cerrado por presupuesto agotado— se emite registro estructurado trazable. Campos mínimos: caso_id/paciente_id, dia_postop/régimen, criticidad, disparador (qué nivel/regla), evidencia (vector observado + señales faltantes), citas_RAG (fundamento del corpus), turnos_indagacion, confianza/incertidumbre.
- `[INFERENCIA]` El campo citas_RAG conecta con los 20 pts de RAG: el escalamiento no es "el modelo dijo rojo" sino "rojo porque [criterio clínico X del documento Y], y la evidencia del paciente es [Z]". Sin cita, el escalamiento no es defendible.
- `[INFERENCIA]` Regla transversal de seguridad: el agente nunca tranquiliza ante un síntoma de alarma ni inventa dosis/medicamento/procedimiento. Si no sabe, declara el límite y escala.

### Protocolo de validación
- `[HECHO]` Los 160 casos son conjunto de DESARROLLO, no de test. La rúbrica evalúa con escenarios interpretados por el jurado, entradas adversas y material no visto; la final del 5 sep prohíbe demo pregrabado.
- `[INFERENCIA]` Por tanto el protocolo mide TRANSFERIBILIDAD por mecanismo, no "el recall que sacaré en la evaluación". Reportar recall-en-muestra como si predijera la nota se leería como sobreajuste.
- `[HECHO]` No existe columna estructurada de señal por turno en `dataset_final`: la señal clínica vive solo en `texto`. El único ground-truth de señal estructurada es `trayectorias_silver` (estado del caso, no lo dicho por turno).
- `[INFERENCIA]` Simulación de indagación (Opción 1): el simulador revela señales DESDE la trayectoria cuando la política pregunta. Extraer del texto (Opción 2) sería hacer la extracción de Fase 3 y contamina la separación política/extracción; queda diferida a Fase 3 como validación end-to-end.
- `[INFERENCIA]` Modelo de evasión de capa 2 (calibración C): revelación probabilística `p̂_revelación` por estilo de paciente. Se estima con un keyword-matcher determinista y auditable FUERA del lazo de validación (solo mide disponibilidad temporal, nunca criticidad); el número entra como constante al validador, que nunca toca texto.
- `[ESPECULACIÓN]` El keyword-matcher subestima revelación (sinónimos regionales no listados) → p̂ sesgado a la baja → el simulador asume más evasión de la real. Sesgo conservador: erra hacia sobre-indagar. Se reporta sensibilidad sobre un rango de p̂, no un único valor.
- `[INFERENCIA]` Separación estricta de dos errores: error de POLÍTICA (regla decide mal con señal disponible) se mide aquí; error de EXTRACCIÓN (no captó la señal del habla) se mide en Fase 3. En este protocolo, cuando la política pregunta por una señal la recibe correcta — la única incertidumbre es si la recibe (evasión), no qué recibe (extracción).
- `[INFERENCIA]` Métrica: recall-rojo como restricción dura (objetivo 1.0), orden lexicográfico sobre accuracy. Desagregado en rojos-claros (12, con bandera pura) vs rojos-sutiles (0 en la muestra tras la enmienda de dolor).
- `[HECHO]` IC: n=12 rojos → un error mueve el recall ~8 pt. Se reporta intervalo Wilson (no Wald, inválido con n pequeño cerca de 1).
- `[INFERENCIA]` Criterio de aprobación §8, criterio 2 reestructurado en tres piezas para no mezclar fuentes de error:
  - 2a — Nunca-verde: 100% de corridas, tolerancia cero. Bug, no ruido, si falla.
  - 2b — Compuerta condicional (la que bloquea): en toda corrida donde la evidencia revelada satisface el criterio de agregación o una bandera, la clasificación es ROJO en el 100%. Determinista, 100% atribuible a la política.
  - 2c — Tasa incondicional de ROJO: se reporta con sensibilidad sobre p̂, NO bloquea. Mide el techo de información bajo evasión; sirve a la defensa.
- `[INFERENCIA]` Batería de casos-frontera (validación + defensa en vivo): el ex-rojo-sutil, fiebre en 37.9, los 8 ambiguos de Q4, bandera pura en día temprano, evasión total de una señal.

### Restricciones exportadas a Fase 2
- `[INFERENCIA]` La política de decisión debe implementarse como MÓDULO PURO importable, sin estado ni dependencias de voz/RAG, testeable en aislamiento. El validador y el agente de producción importan EXACTAMENTE el mismo módulo — si divergen, se valida una cosa y se entrega otra.
- `[INFERENCIA]` Separación de canales dato/instrucción (anti prompt-injection): la transcripción del paciente es DATO, no INSTRUCCIÓN. La política consume señales estructuradas extraídas del habla, nunca texto libre como comando. Caer en injection anula el apartado de voz.

### Decisiones de infraestructura (fijadas)
- `[INFERENCIA]` Ruta de producción (voz en tiempo real): CLOUD-FIRST con Groq (Whisper Large V3 + Llama 3.1 70B). Razones: menor latencia (LPUs) y portabilidad a la máquina del jurado (la sesión corre en su hardware; asumir GPU específica arriesga G2).
- `[INFERENCIA]` La GPU (disponibilidad incierta) es banco de medición y palanca de preprocesamiento, NO ruta de producción. Usos: indexar el corpus RAG y persistir el índice como artefacto; OCR del PDF escaneado una sola vez; medir la ruta local para comparar en el informe; fallback local declarado si resulta estable.
- `[INFERENCIA]` Todo en Docker desde el commit 1 (protege G2 frente a divergencias Fedora/Windows). Lo que la GPU acelera se congela en artefactos persistidos en el repo.

---

## Deudas y pendientes abiertos
- **[Fase RAG] Anclaje de la bandera de dolor al corpus.** Localizar en los 107 PDFs el criterio clínico que sustenta dolor severo (≥7) en recuperación tardía como signo de alarma. Citarlo en el registro de escalamiento. Si el corpus no lo sustenta, resolverlo antes de la sesión de evaluación. Riesgo: la bandera es hoy un hecho sobre dataset sintético, no un argumento clínico.
- **[Fase 3] Calibración de los topes de indagación.** Los valores 2–3 por señal y 6–8 global son ESPECULACIÓN. Calibrar en prototipo midiendo sobre capa 2 (no capa 1).
- **[Fase 2/RAG] OCR del PDF escaneado de Appendicitis/.** Un PDF del corpus está escaneado sin capa de texto. Decidir: OCR (persistido como artefacto) o descartar explícitamente. No dejarlo como hueco silencioso.
