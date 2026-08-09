# Bitácora del proyecto — Voice Agent Post-Op

**Propósito.** Este archivo es el puente entre el repositorio local y el Project de claude.ai que actúa como arquitecto. Toda decisión técnica queda registrada aquí para que cualquier chat futuro del Project se sincronice leyendo un solo archivo. Alimenta además el informe final del reto (evidencia de proceso — criterio de 15 pts de repositorio/proceso).

**Convención epistemológica** (heredada de los documentos de diseño):
- `[HECHO]` — verificado sobre el dataset, los .md del reto o exploración reproducible.
- `[INFERENCIA]` — deducción a partir de hechos + razonamiento de diseño o clínico.
- `[ESPECULACIÓN]` — supuesto o parámetro sin medición directa. Declarado como tal.

**Documentos de diseño asociados**:
- `docs/diseno/enmienda_auditoria_fase1.md` — **fuente vigente**. Supersede a los dos .docx en todo punto
  de conflicto (2026-08-08).
- `docs/diseno/parametros_politica.md` — **fuente única de parámetros operativos**. De aquí deriva el
  módulo puro de Fase 2; ningún valor se codifica en otro lado.
- Política de Decisión Clínica, .docx (Fase 1, punto 2) — **registro histórico, superado parcialmente**.
- Protocolo de Validación, .docx (Fase 1, punto 3) — **registro histórico, superado parcialmente**.

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

## 2026-08-08 · Reapertura y re-cierre de Fase 1

**Estado: Fase 1 RE-CERRADA.** La Fase 1 se había cerrado esa misma fecha; se reabrió el mismo día tras
someter los dos documentos de diseño a una auditoría de reproducibilidad contra el dev set. La auditoría
encontró **seis defectos**, uno de ellos en un parámetro que nunca se había especificado.

**Documentos que salen de esta reapertura** (los dos .docx NO se corrigen en su cuerpo):
- `docs/diseno/enmienda_auditoria_fase1.md` — errata; supersede a ambos .docx en todo punto de conflicto.
- `docs/diseno/parametros_politica.md` — fuente única de parámetros operativos, completa y sin ambigüedad.
- Aviso de superación insertado como primer párrafo de cada .docx.

### La auditoría y su script
- `[HECHO]` `scripts/auditoria_fase1.py` verifica uno por uno los `[HECHO]` declarados en
  `politica_decision.docx` y `protocolo_validacion.docx` contra los 160 casos. Determinista, idempotente,
  sin red, falla ruidoso si el join no cierra. Secciones A1–A10.
  ```bash
  DATASET_DIR=/ruta/a/ParticipantArtifacts/dataset python3 scripts/auditoria_fase1.py
  ```
- `[HECHO]` **Lo que sí se confirmó** (A1): join 160/160, desbalance 123/25/12, pureza de
  `secrecion_purulenta` (n=3) y de `movilidad = incapacitante_nueva` (n=4), los 8 ambiguos de Q4, la
  distribución día × clase, y `recall_rojo = 1.000` con `c₁ = 0` de la política literal sobre vector
  completo (A9).

### Los seis defectos
- **D1 — La pureza de apetito y sueño no existe.** `[HECHO]` (A2) `apetito = muy_disminuido`: n=29 → 12
  amarillo, 12 rojo, **5 verde**. `sueno = muy_alterado`: n=32 → 16 amarillo, 12 rojo, **4 verde**. Los dos
  conjuntos de verdes son **disjuntos**. Los conteos totales del .docx eran correctos; la lectura de pureza
  era falsa. No son anclas puras: son señales de alta sensibilidad y baja especificidad sobre verde.
- **D2 — El Nivel 1 no tiene la redundancia que su diseño supone.** `[HECHO]` (A3) Cobertura sobre los 12
  rojos: fiebre ≥ 38.0 → 11/12 (única en 3); movilidad → 4/12 (única en **0**); purulenta → 3/12 (única en
  **0**); dolor ≥ 7 → 2/12 (única en 1). **Las dos anclas categóricas no capturan ni un rojo que la fiebre
  no capture ya.** La columna vertebral real es el umbral numérico de fiebre — el mismo que §1.4 declara
  frágil. `[INFERENCIA]` Las anclas categóricas son confirmatorias, no portantes. `[HECHO]` (A7) El umbral
  no admite holgura: a 37.9 atrapa un verde de día 3; a 38.1 pierde 4 rojos que están exactamente en 38.0.
- **D3 — Refundación de la bandera de dolor.** `[HECHO]` El dominio real de `dolor_nrs` es
  {0,1,2,3,4,5,6,9}: **7 y 8 no existen**. La «pureza 1.0 en {7,8,9}» es vacua en dos tercios de su banda y
  descansa sobre 2 observaciones (ambas dolor=9), una de las cuales ya dispara fiebre. Aporte marginal: 1
  caso (`caso_tray_pac_42_00017_7`). `[INFERENCIA]` **La justificación se refunda, el umbral no cambia**: el
  7 es el tercil severo de la propia escala NRS (1–3 leve, 4–6 moderado, 7–10 severo), no un artefacto del
  dataset. El dato se degrada de justificación a verificación de consistencia. `[HECHO]` (A4) La bandera es
  **portante**: sin ella `recall_rojo` cae de 1.000 a 0.917 con un c₃.
- **D4 — El intervalo de confianza está mal construido.** `[HECHO]` (A5) Los 12 rojos son **6 pacientes × 2
  días**, y los seis son rojos en ambos días: Wilson asume independencia y no la hay. Wilson 95 % con n=12
  casos → [0.757, 1.000]; con **n=6 pacientes → [0.610, 1.000]**. El intervalo publicado es ~15 puntos
  optimista en su cota inferior. **El intervalo a nivel paciente pasa a ser el principal**; la unidad de
  remuestreo en cualquier bootstrap futuro es el paciente, no el caso. Se corrige «un error mueve el recall
  ~8 puntos»: a nivel paciente son **~17**.
- **D5 — Se reportó el margen barato y se omitió el caro.** `[HECHO]` (A6) §1.4 reporta el gap verde↔rojo
  (0.2 °C al día 7) y omite que al día 7 **amarillo y rojo colisionan exactamente en 37.9 °C**:
  `…00012_7` (dolor 4, eritema) es amarillo y `…00017_7` (dolor 9, eritema) es rojo. Se documentó la
  frontera cuyo error es c₂ y se omitió la cuyo error es c₃. `[INFERENCIA]` El par es un **test de
  discriminación, no de umbral**: la fiebre no los separa; los separan dolor y apetito/sueño. Entra a la
  batería de casos-frontera.
- **D6 — Corte del enrutador temporal, nunca especificado.** `[HECHO]` El dev set no tiene ninguna
  observación en días 4, 5 y 6 (días presentes: {1,3,7,14}). Cualquier corte en ese intervalo es igualmente
  consistente con los datos: **no es decidible por datos**. Ver decisión abajo.

### Nivel 1.5 — compuerta de no-verde (hallazgo constructivo)
- `[HECHO]` En régimen tardío, **tres condiciones independientes cubren cada una los 12/12 rojos con cero
  verdes sobre los 58 verdes tardíos**: `fiebre_c ≥ 37.8` (arrastra 1/10 amarillos), `dolor_nrs ≥ 5`
  (6/10), y `apetito = muy_disminuido ∧ sueno = muy_alterado` (3/10).
- `[INFERENCIA]` Ninguna sirve como bandera roja: las tres arrastran amarillos y forzar ROJO compraría
  hasta 6 c₅. **Su uso correcto es como condición necesaria de rojo**: si alguna se cumple, el caso no puede
  cerrar en verde, y no puede cerrar en amarillo hasta que toda bandera de Nivel 1 quede **activamente**
  descartada. Es la implementación medible del criterio «amarillo no es clase terminal con bandera roja
  pendiente», que hasta ahora era un juicio cualitativo sin disparador.
- `[HECHO]` Ninguna descansa en n pequeño: su afirmación fuerte es «cero verdes» y se apoya sobre los **58
  verdes tardíos**, no sobre los 12 rojos. **Esta es la redundancia que §1.2 afirmaba tener y no tenía
  (D2).** Costo sobre la muestra: cero.
- `[INFERENCIA]` Límite declarado: la conjunción apetito∧sueño es pura sobre verde **en conjunción**, aunque
  cada parte por separado tenga 5 y 4 verdes (D1). Hecho sobre esta muestra, no ley clínica. Por eso la
  compuerta exige **cualquiera** de las tres, no la conjunción de las tres.
- **Nota de método:** el borrador de la enmienda afirmaba `fiebre ≥ 37.5` con «cero verdes» y la conjunción
  con «8/10 amarillos». Ambas cifras son falsas y se corrigieron al verificarlas: `≥ 37.5` atrapa **4 de los
  58 verdes tardíos** (el umbral con cero verdes es **37.8**), y la conjunción arrastra **3** amarillos
  tardíos, no 8 (el 8 es el conteo global sobre ambos regímenes). Es el mismo error de D1 reapareciendo en
  el documento que lo corrige — de ahí el correctivo permanente de abajo.

### Corte del enrutador fijado en el día 4
- `[INFERENCIA]` Si los datos no deciden, decide la matriz de costos. Costo medido de cada dirección (A10,
  con los días adyacentes como proxy):
  - **temprano tratado como tardío** — día 1: 3/37 verdes → amarillo (8.1 %); día 3: 6/28 (21.4 %). **Cero**
    pasan a rojo. Puro **c₂**, disparado **solo por `eritema_leve`**.
  - **tardío tratado como temprano** — `…00017_7` cae de rojo a amarillo, recall 1.000 → 0.833. Es **c₃**.
- `[INFERENCIA]` **Corte fijado: `dia_postop ≤ 3` → TEMPRANO, `≥ 4` → TARDÍO.** El día 4 es el primer día
  clínicamente defendible: la respuesta inflamatoria aguda alcanza su pico en las primeras 48–72 h y luego
  declina, y la ISQ superficial se presenta clásicamente desde el cuarto día. Adelantarlo al 2 sería
  sobre-escalar sin fundamento; retrasarlo al 6 sería elegir comodidad sobre seguridad en el único tramo
  ciego. El costo además **crece con el día** (8.1 % en día 1 → 21.4 % en día 3), lo que refuerza cortar en
  4 y no antes.
- `[INFERENCIA]` **Descartado un tercer régimen de transición para los días 4–6**: exigiría inventar
  umbrales sin una sola observación que los sostenga.

### Alternativa descartada: bajar la fiebre tardía a 37.8 °C
- `[HECHO]` Capturaría 12/12 rojos con 0/58 verdes tardíos, así que a primera vista domina al 38.0.
- `[INFERENCIA]` **Descartada.** (a) Captura 12/12 **solo porque captura el mismo `…00017_7`**: sustituye
  una regla justificada por n=1 por un umbral justificado por el mismo n=1, sin comprar evidencia nueva.
  (b) Pierde el anclaje clínico: 38.0 °C es una definición febril citable, 37.8 °C es un número elegido para
  que un caso quepa. (c) `[HECHO]` No es gratis: arrastra además el amarillo `…00012_7` a ROJO, un c₅ que el
  38.0 no paga. Se documenta el descarte de forma explícita — sirve a la Pregunta 2 del video.

### Deuda de RAG: elevada a BLOQUEANTE y ampliada a las cuatro banderas
- `[INFERENCIA]` La deuda registrada («anclar dolor ≥ 7 al corpus», **diferida**) se amplía a **las cuatro
  banderas más el corte temporal** y pasa a **bloqueante antes de la sesión de evaluación**. Razón: D2
  mostró que la cobertura del Nivel 1 descansa casi por completo en un umbral numérico frágil, y D3 que la
  única bandera que lo complementa se apoya en n=2. **Ninguna bandera tiene hoy cita**; el campo `citas_RAG`
  del registro de escalamiento está vacío para las cuatro.
- Localizar en los 107 PDFs: (a) la partición de severidad NRS 7–10; (b) el umbral febril de 38.0 °C;
  (c) criterios de ISQ para secreción purulenta; (d) deterioro funcional agudo para movilidad
  incapacitante; (e) la ventana de presentación de la ISQ que sostiene el corte en día 4.
- `[INFERENCIA]` Si el corpus no sustenta (a), la cobertura defendible del Nivel 1 cae a **11/12** y
  desaparece el mecanismo de captura del ex-rojo-sutil. El Nivel 1.5 mitiga (ese caso cumple las tres
  condiciones, así que no puede cerrar en verde) pero no resuelve: cerraría en amarillo, que sigue siendo un
  c₃.

### Patrón de fondo y correctivo permanente
- `[INFERENCIA]` **Cinco de los seis defectos son el mismo error: pureza observada sobre un dev set pequeño,
  leída como propiedad estructural.** (D6 es de otra familia: un parámetro nunca especificado.) El mecanismo
  común es que la exploración buscó **confirmación** de una estructura ya intuida en vez de buscar el
  contraejemplo. Cada `[HECHO]` era literalmente verdadero sobre alguna consulta —los conteos de D1 eran
  correctos— pero la consulta que se corrió no era la que la afirmación necesitaba.
- **Correctivo permanente adoptado: toda afirmación de pureza declara su n y su n efectivo.** Ninguna
  afirmación entra a un documento de diseño con etiqueta `[HECHO]` sin (1) el n sobre el que se mide —no el
  del conjunto que la hace ver bien—, (2) el n efectivo cuando las observaciones no son independientes
  (D4: 12 casos → 6 pacientes), (3) la consulta reproducible en `scripts/`, y (4) el contraejemplo buscado
  explícitamente y no encontrado, no solo la confirmación hallada.
- **Extendido el 2026-08-08** por una cláusula general sobre la procedencia de todo `[HECHO]`;
  este correctivo queda como su especialización para afirmaciones sobre muestras. Ver la
  entrada HD1 de Fase 2.

### Nota de contagio en los .docx
- `politica_decision.docx` §1.4 y §6 contienen ahora frases insostenibles —en particular «el escalamiento se
  apoya en anclas categóricas, no en la fiebre sola»— que D2 contradice de frente.
- `protocolo_validacion.docx` §1.2 **no cambia en su conclusión** (los 12 siguen siendo «claros» por unión
  de banderas) **pero sí en su lectura**: 11 de los 12 lo son por fiebre.
- Ambos conservan su cuerpo sin corregir, como registro histórico, con el aviso de superación al inicio.

---

## Fase 2 — Implementación del módulo de política
**Estado: ABIERTA.** Sub-paso 2.1 (módulo puro de decisión) en curso.

### 2026-08-08 · HD1 — `REPREGUNTAR` no accionable con vector completo

**Estado: cerrado por especificación** (`parametros_politica.md` §7.1 enmendado + §7.4 nueva + nota en §8).
El módulo de 2.1 **todavía no se ha escrito**: este parche es documental y precede al código a propósito.

#### Qué era HD1 y cómo apareció
- `[HECHO]` El arquitecto sometió `parametros_politica.md` a una **auditoría de la spec previa a
  implementar** — leerla como si fuera el módulo y ejecutarla mentalmente sobre los 160 casos, antes de
  escribir una línea de `politica/`. HD1 es el primero de los huecos que salieron de ahí.
- `[HECHO]` Con vector del núcleo completo, **19 de los 160 casos (11.9 %)** no cumplen S1, S2 ni S3 y caen
  por §7.1 en `ninguno_se_cumple → REPREGUNTAR`. Los 19 son de régimen temprano con `n_total == 1`
  exactamente, y los 19 son **verde real**.
- `[INFERENCIA]` `REPREGUNTAR` ahí es una **acción imposible**: no queda ninguna señal `AUSENTE` que
  preguntar. §8 tampoco los cubre — su tabla está indexada por *qué quedó irresuelto*, y en estos casos no
  quedó nada irresuelto. La spec dejaba **comportamiento indefinido** en el 11.9 % del dev set.

#### Diagnóstico de raíz
- `[INFERENCIA]` El defecto no es un umbral mal puesto: es que **`REPREGUNTAR` estaba definido como residuo
  («ninguno se cumple») y no como condición positiva**. Un residuo hereda todo lo que las condiciones
  explícitas no atrapan, incluidos casos donde la acción que nombra no puede ejecutarse. La corrección es
  darle a `REPREGUNTAR` su condición de accionabilidad (señal `AUSENTE` **y** presupuesto) y declarar qué
  pasa cuando no se cumple.

#### Decisión adoptada y alternativa descartada
- `[INFERENCIA]` **Cierre forzado (§7.4).** Con vector completo y ninguna S satisfecha, el módulo cierra con
  la clase candidata de §5.2 **filtrada** por las prohibiciones ya declaradas en §4.1 — el filtro prohíbe
  salidas, no fuerza clases. No entra ningún parámetro nuevo al repo: §7.4 es semántica, no números.
- `[INFERENCIA]` **Alternativa descartada:** promover los 19 a AMARILLO («nunca verde con una señal blanda
  activa»). `[HECHO]` Cuesta **19 c₂ adicionales** en temprano (4 → 23) y deshace en silencio la decisión de
  §5.2 de elegir el umbral ≥ 2 sobre ≥ 1 — que se tomó con esa misma comparación de costo a la vista (H4).
  Habría sido reintroducir por la puerta de atrás la regla que §5.2 rechaza por la de adelante.
- `[INFERENCIA]` El invariante duro de §8.1 (nunca VERDE con evidencia insuficiente) **no se toca**: aquí la
  evidencia está completa. Sigue mordiendo sin excepción en el caso de presupuesto agotado.

#### El criterio de aceptación de 2.1 no era reproducible antes de este parche
- `[INFERENCIA]` Hallazgo colateral y más incómodo que HD1 mismo. El criterio de aceptación de 2.1
  (`recall_rojo = 1.000`, `c₁ = 0`, `c₃ = 0`, `c₂ = 11`) estaba enunciado sobre la **capa de agregación**
  (§5.2), pero §7.1 **nunca declaraba que la salida de esa capa fuera la salida terminal del módulo** — en
  19 casos la salida terminal era `REPREGUNTAR`, que no es una clase y no entra en ninguna matriz de
  confusión. El módulo, implementado literalmente contra la spec vigente, **no podía reproducir su propio
  criterio de aceptación**. Con §7.4 la salida terminal queda definida para los 160 casos y el criterio pasa
  a ser verificable sobre lo que el módulo realmente emite.

#### Invariante §4↔§5 y su fragilidad declarada
- `[INFERENCIA]` **Property test obligatorio para 2.1:** en régimen tardío, compuerta 1.5 activa ⟹
  `n_total ≥ 1`. Se deriva de que cada condición de la compuerta implica una señal blanda
  (`g_fiebre 37.8 ≥ s_fiebre 37.5`; `g_dolor 5 = s_dolor` tardío; `g_constitucional ⟹ s_apetito ∧ s_sueno`).
- `[INFERENCIA]` **Depende de los valores actuales, no de la estructura.** Si el anclaje al corpus
  (deuda BLOQUEANTE de RAG, y la deuda «Convergencia de `dolor ≥ 5`») mueve cualquiera de esos cuatro
  umbrales, la implicación puede romperse. El paso 2 del filtro de §7.4 mantiene la salida correcta aunque
  se rompa; el test existe para que **la ruptura sea ruidosa en vez de silenciosa**. Es una atadura directa
  entre la deuda de RAG y el módulo de Fase 2: no se puede tocar un umbral de §4 o §5 sin re-correr esto.

#### Evidencia y su estatus
- `[HECHO]` `scripts/verificacion_hd1.py` es **reimplementación independiente** de la spec: escrita desde el
  texto de `parametros_politica.md`, sin mirar `scripts/auditoria_fase1.py` ni el módulo de Fase 2 (que no
  existe aún), y por el arquitecto, no por el ejecutor. Verifica V1 (criterio de aceptación sobre la salida
  terminal), V2 (desglose del cierre forzado + salida definida para los 160), V3 (invariante §4↔§5) y V4
  (el hueco: §7.1 literal deja 19 en `REPREGUNTAR`).
  ```bash
  DATASET_DIR=/ruta/a/ParticipantArtifacts/dataset python3 scripts/verificacion_hd1.py
  ```
- `[INFERENCIA]` **El módulo de 2.1 debe REPRODUCIR sus números, no importarlo.** Si el implementado y su
  oráculo salen del mismo código, el test no prueba nada — es la misma razón por la que la auditoría de
  Fase 1 se escribió aparte de los documentos que auditaba.
- `[HECHO]` La salida de la corrida queda **versionada como evidencia** en
  `scripts/verificacion_hd1_salida.txt`, con fecha, host, versión de Python y de pandas en
  la cabecera. Los nueve valores se reproducen idénticos en dos entornos: **Python 3.12.3 /
  pandas 3.0.2** (entorno efímero del arquitecto, no reproducible por terceros) y **Python
  3.14.6 / pandas 3.0.3** (Fedora 44, la corrida versionada).
- `[INFERENCIA]` Eso da independencia frente a la versión **menor** de pandas y frente a la
  de Python. **No** frente a la mayor: ambos entornos corren pandas 3.x.

#### Convención de espacios de nombres (permanente)
- `[HECHO]` Al documentar HD1 aparecieron **dos «H1» distintos en el mismo repo**: la armonización H1 de
  `parametros_politica.md` §6 («febrícula sostenida» no es evaluable) y este hueco de diseño. La colisión no
  era solo con H1 sino con toda la familia H1–H4.
- **Convención adoptada, vinculante de aquí en adelante:**

  | Prefijo | Qué numera |
  |---|---|
  | `A#`  | Secciones de `scripts/auditoria_fase1.py` (A1–A10) |
  | `D#`  | Defectos encontrados por la auditoría de Fase 1 (D1–D6) |
  | `H#`  | Armonizaciones de `parametros_politica.md` §6 (H1–H4) |
  | `HD#` | **Huecos de diseño** detectados sobre la spec antes de implementar (HD1–HD7 hasta la fecha; rango abierto) |

- `[INFERENCIA]` El «(H4)» que cita §7.4 al descartar la alternativa **se refiere a la armonización de §6 y
  no se renombra**: con esta convención ya no es ambiguo. El artefacto de evidencia se renombró a
  `scripts/verificacion_hd1.py` por coherencia; su lógica y sus valores esperados no se tocaron.

#### Errata de referencias (hallazgo colateral)
- `[HECHO]` Dos cross-refs rotos en `parametros_politica.md`, **ambos preexistentes** a este parche y de la
  misma familia — apuntan a secciones que no tratan lo que la frase promete:
  - §4.1 punto 3 remitía a «(§6.2)», que **no existe**: §6 son las armonizaciones H1–H4 y no tiene
    subsecciones. Corregido a **«(§8, fila 2)»**, que es donde vive la resolución a ROJO por bandera en
    `DESCONOCIDO` con la compuerta activa.
  - §3 remitía el manejo de banderas `DESCONOCIDO` («queda **pendiente** (§5.2)») a la **regla de
    agregación**, que no dice nada de banderas pendientes. Corregido a **«(§7.1 y §8)»**: la compuerta de
    suficiencia y el escalamiento graduado.
- `[INFERENCIA]` **No cambian ninguna semántica ni ningún número**: la conducta descrita ya estaba
  correctamente especificada en su sección real, y las cuatro secciones involucradas se leyeron al verificar
  §7.4 contra §4.1, §5.2 y §8.1. Se corrigen aquí porque un cross-ref roto en la fuente única de parámetros
  es una trampa para quien implemente 2.1 leyendo la spec de corrido.

#### Errata de este mismo parche
- `[HECHO]` La primera redacción de la viñeta anterior decía «Python 3.12 / pandas 2.x» y lo
  etiquetaba `[HECHO]`. El dato salió de la memoria del arquitecto, no de una consulta: la
  versión real era pandas 3.0.2. Arrastraba además la conclusión «el resultado no depende de
  la versión de pandas», que ninguno de los dos entornos sostiene. Se detectó al verificar
  antes de aprobar el diff.
- `[INFERENCIA]` Es el mismo mecanismo del «Patrón de fondo» de
  `enmienda_auditoria_fase1.md` —afirmar como hecho lo que no se midió— reaparecido en el
  documento que establece el correctivo, y cometido por el arquitecto, no por el ejecutor.
  Se registra en vez de corregirse en silencio: el correctivo permanente aplica a quien lo
  escribió.
- `[HECHO]` Bug relacionado, ya corregido por el ejecutor: el snippet de captura del
  arquitecto estampaba `# exit: $?` después de un `print` intermedio, así que el campo daba
  0 siempre, incluso con el script fallando. Fabricaba evidencia tranquilizadora. Corregido
  guardando `rc=$?` inmediatamente tras la llamada a Python.

#### Extensión del correctivo permanente (2026-08-08)

- `[INFERENCIA]` El correctivo de Fase 1 —toda afirmación de pureza declara su n y su n
  efectivo, su consulta reproducible y el contraejemplo buscado— **no cubrió este fallo**.
  D1–D5 fueron consultas mal formuladas sobre datos que existían: el dato se consultó mal.
  La errata de pandas fue **no consultar nada**. `pandas.__version__` no tiene n ni muestra
  que declarar; solo hay que mirarlo, y no se miró.
- `[INFERENCIA]` **Cláusula general adoptada, vinculante para toda etiqueta `[HECHO]` del
  proyecto:** un `[HECHO]` declara el **procedimiento que lo produjo** — el comando, el
  archivo y línea, o la consulta. Si no hay procedimiento que declarar, no es `[HECHO]`: es
  `[INFERENCIA]` o `[ESPECULACIÓN]`. El correctivo de Fase 1 pasa a ser la **especialización**
  de esta cláusula para afirmaciones sobre muestras, no una regla paralela.
- `[INFERENCIA]` **Proporcionalidad, para que la regla se cumpla en vez de decorar:** el
  procedimiento va inline cuando la comprobación es un comando (`python3 -c 'import pandas;
  print(pandas.__version__)'`); va a `scripts/` cuando la afirmación es sobre el dataset y
  un tercero tiene que poder re-correrla. Lo que no admite excepción es que exista.
- `[INFERENCIA]` **Por qué la cláusula general y no una regla de metadatos de entorno:** la
  estructura del fallo no es el objeto de la afirmación, es su procedencia. Una regla por
  tipo de objeto deja fuera el siguiente tipo. Se prefiere la regla general, con el mismo
  criterio de H2: menos ramas es menos superficie de contradicción futura.

### 2026-08-08 · HD2, HD3 y HD4 — núcleo, compuerta en `DESCONOCIDO` y partición de §8

**Estado: cerrados por especificación** (`parametros_politica.md` §1.2 nueva + §4.1 ampliada + §8 tabla
reescrita). Como el parche de HD1, es documental y **precede al código a propósito**: el módulo de 2.1 sigue
sin escribirse.

- `[INFERENCIA]` **Los tres son semánticos.** Ningún parámetro nuevo, ningún valor modificado, ninguna fila
  de §10 tocada. Lo que cambia es qué significa la spec donde antes admitía dos lecturas.
- `[HECHO]` **Ninguno es decidible por el dev set:** los 160 casos tienen las siete columnas completas, cero
  ausencias (`scripts/verificacion_hd1.py`, aserción de nulos en `cargar()`). Los tres huecos viven en el
  régimen de evidencia parcial, que es capa 2 y no existe en capa 1.

#### HD2 — el núcleo no estaba definido en ninguna parte

- `[HECHO]` «Todas las señales del núcleo» aparece en S2 (§7.1), en la condición de accionabilidad de
  `REPREGUNTAR`, en §7.4 y en el invariante duro (§8.1). El conjunto al que se refiere **no estaba escrito**.
- `[INFERENCIA]` **Definición intensional, no lista:** el núcleo es el conjunto de señales que aparecen en
  algún predicado de §3, §4 o §5. Hoy la unión es exactamente
  `{herida, movilidad, fiebre_c, dolor_nrs, apetito, sueno}` — seis, y ninguna sobra. Una lista enumerada
  sería un segundo lugar donde vive un parámetro, contra la regla 1 de §0; definido como unión, si el
  anclaje al corpus añade o retira un predicado el conjunto se ajusta solo.
- `[INFERENCIA]` **`dia_postop` queda fuera.** §2 ya lo establecía como dato del seguimiento, **no
  indagable**. El papel del núcleo en S2 y en §8.1 es «ya se preguntó todo lo que se podía preguntar»;
  meter ahí algo que no se pregunta rompe la definición desde dentro.
- `[INFERENCIA]` **Modo de fallo evitado — HD1 por otra puerta.** Con `dia_postop` en el núcleo, un caso con
  día desconocido y las seis señales clínicas obtenidas fallaría S2, declararía `REPREGUNTAR` **accionable**
  por la letra de §7.1, y el agente gastaría el presupuesto entero en una pregunta **sin destinatario** para
  caer en AMARILLO por §8. Todo caso con día desconocido cerraría en AMARILLO en el mejor de los casos,
  contra §2.1, que lo trata como manejable con régimen TARDÍO + `marca_incertidumbre`. Es exactamente la
  patología de HD1 —una acción declarada accionable que no puede ejecutarse— reapareciendo en otro punto de
  la spec.
- `[INFERENCIA]` **Consecuencia declarada, no resuelta:** seis señales de núcleo contra un tope global de 6
  turnos (`[ESPECULACIÓN]`, §7.2) significa que alcanzar S2 exige **cosecha perfecta**. En capa 2 se espera
  VERDE infrecuente y AMARILLO al alza. Es el primer indicador de que los topes quedaron cortos, y se mide
  en Fase 3, no se ajusta ahora.

#### HD3 — la compuerta de Nivel 1.5 en `DESCONOCIDO`

- `[HECHO]` Bajo Kleene fuerte (§1.1) la disyunción de §4 puede evaluar `DESCONOCIDO`, pero §7.1 (S2) y §8
  la nombran en binario («activa» / «no activa»). El tercer valor no tenía dirección declarada.
- `[INFERENCIA]` **Se resuelve en la dirección segura: `DESCONOCIDO` cuenta como activa** a efectos de
  prohibir salidas.
- `[INFERENCIA]` **Su costo hoy es cero por estructura, no por decreto** — y eso es lo que había que
  escribir. Para alcanzar cualquier salida distinta de ROJO todas las banderas deben estar en `FALSO`, luego
  `g_fiebre` y `g_dolor` están determinadas y la única condición que puede quedar `DESCONOCIDO` es
  `g_constitucional`; si la disyunción entera queda `DESCONOCIDO` es porque las otras dos son `FALSO`, caso
  que §8 ya resuelve en AMARILLO. La cláusula se escribe **igual**: la neutralidad depende de la estructura
  actual y sin declararla alguien la borra por «redundante» y reabre el hueco cuando esa estructura cambie.

#### HD4 — §8 pasa a partición binaria

- `[INFERENCIA]` La tabla de cinco filas indexadas por «qué quedó irresuelto» no era una partición: dos
  situaciones podían encajar en varias filas y el orden de lectura decidía. Se reemplaza por una tabla de
  **dos preguntas binarias** — ¿alguna bandera en `DESCONOCIDO`? ¿falta alguna señal del núcleo (§1.2)? —
  con tres celdas alcanzables.
- `[INFERENCIA]` **Exhaustiva por construcción, y la premisa de la segunda fila se cumple sola:** si ninguna
  bandera está en `DESCONOCIDO`, entonces `herida`, `movilidad`, `fiebre_c` y `dolor_nrs` son conocidas, así
  que las únicas señales del núcleo que pueden faltar son `apetito` y `sueno` — ambas discriminadores
  verde↔amarillo. No hay que verificarla en el código.
- `[INFERENCIA]` **Dos filas eliminadas por redundancia. No hay cambio de política: el mapa
  situación→resolución es idéntico**, solo cambia la forma.
  - «Compuerta 1.5 activa **y** bandera en `DESCONOCIDO` → ROJO» está **subsumida**: la bandera en
    `DESCONOCIDO` ya basta, con compuerta o sin ella.
  - «`dolor_nrs ∈ {5,6}` sin resolver en tardío → ROJO» **no era expresable**: §1.1 declara
    `Valor(señal) ::= <dominio> | AUSENTE`, sin intervalos, así que «saber que está entre 5 y 6» no tiene
    representación en el modelo de valores. Con `dolor` `AUSENTE` en tardío, `dolor_severo` queda
    `DESCONOCIDO` y la primera fila ya da ROJO — **mismo resultado**. Representar conocimiento parcial
    exigiría un valor de intervalo por señal; se descarta para Fase 2 y queda emparentado con la deuda menor
    «no existe el estado señal obtenida sin confirmar».
- `[INFERENCIA]` **Riesgo de c₄ que la primera fila concentra.** Cualquier señal de bandera sin resolver al
  agotar el presupuesto sale ROJO: un verde que evade la pregunta sobre la herida se escala. Eso es c₄ —la
  celda del «agente alarmista»— y el jurado prueba verdes. Lo único que impide que sea un cañón de
  escalamientos es el orden de §7.3, que manda indagar **primero** las señales adyacentes a bandera.
- `[INFERENCIA]` **§7.3 queda elevada a portante de costo, no solo de seguridad.** Su orden tiene que ser
  determinista y llevar test propio. **HD6 sube de prioridad** en el contrato del módulo por esta razón.

#### Hallazgos colaterales y regla adoptada

- `[HECHO]` **Preexistente:** §1 afirmaba «0 nulos en las **ocho** columnas del núcleo». Son **siete**, y es
  lo que asegura `cargar()` en `scripts/verificacion_hd1.py`. Era un `[HECHO]` que **no reproducía su propia
  aserción** — precisamente lo que prohíbe la cláusula de procedencia adoptada en la entrada de HD1.
  Corregido a «siete columnas de la tabla» **con el procedimiento declarado inline**.
- `[INFERENCIA]` El conteo era el síntoma; el problema era que **«núcleo» nombraba dos objetos distintos**:
  las columnas que el join debe traer sin nulos (7, hecho sobre el dataset) y las señales que el agente debe
  cosechar (6, concepto de la política). Difieren exactamente en `dia_postop`. §1.2 reserva la palabra para
  el segundo y declara la distinción; §1 ya no la usa.
- `[HECHO]` **Referencia rota por segunda vez en dos parches:** el parche de HD1 redirigió §4.1 punto 3 a
  «(§8, fila 2)», y la Edición de HD4 elimina esa fila — el destino habría pasado a decir AMARILLO donde la
  frase afirma ROJO. Detectado al leer §4.1 y §8 antes de editar.
- **Regla adoptada, vinculante de aquí en adelante: las referencias cruzadas citan la condición, no la
  posición.** §4.1 punto 3 pasa a «(§8, caso "alguna bandera de Nivel 1 en `DESCONOCIDO`")»; §8 remite a
  «§7.4, caso "vector del núcleo completo"»; la nota de §7.4 cita «el caso "presupuesto agotado con alguna
  señal `AUSENTE`"». `[INFERENCIA]` Una cita por posición se rompe en silencio cada vez que la tabla cambia
  de forma —ya ocurrió dos veces seguidas— mientras que la condición sobrevive a cualquier reordenamiento.
- `[INFERENCIA]` La regla **no admite excepción por proximidad**. Dos de las tres menciones intra-sección no
  describían la tabla sino que argumentaban sobre ella —la demostración de exhaustividad y el argumento del
  riesgo de c₄—; un reordenamiento no las volvería confusas sino **falsas**, bajo una etiqueta
  `[INFERENCIA]`. Una descripción que envejece mal se nota al leerla; una demostración que envejece mal se
  sigue leyendo bien. Se prefiere la regla sin ramas, mismo criterio que H2.
- `[INFERENCIA]` **Alcance de la regla: documentos normativos.** Aplica a `parametros_politica.md` y a
  cualquier documento que afirme sobre el estado vigente. **No aplica a esta bitácora ni a
  `enmienda_auditoria_fase1.md`**: son registro fechado, afirman sobre el estado del repo en su fecha, y una
  referencia posicional en ellos describe correctamente algo que ya pasó. Es la misma razón por la que los
  `.docx` conservan su cuerpo con errores conocidos y por la que la enmienda no se reescribe: las decisiones
  nuevas entran con fecha, no reescribiendo lo cerrado.

#### Estado de la spec tras este parche

- `[INFERENCIA]` **Los cuatro huecos bloqueantes de la spec quedan cerrados.** 2.1 puede escribirse sin que
  el implementador tenga que decidir nada por su cuenta sobre política.
- `[INFERENCIA]` Quedan **HD5** (firma y tipo de retorno del módulo), **HD6** (desempate determinista en
  `REPREGUNTAR`) y **HD7** (contabilidad del presupuesto en un módulo sin estado). Los tres son **contrato
  del módulo, no política**: se cierran al escribir 2.1, no antes, y su resolución no toca
  `parametros_politica.md` salvo que revele un hueco de política nuevo.
- `[HECHO]` `scripts/verificacion_hd1.py` vuelve a pasar sin cambios tras las tres ediciones
  (`RESULTADO: todas las verificaciones pasan`, código 0), que es la comprobación de que ninguna alteró
  comportamiento sobre el dev set. La salida versionada de HD1 **no se regeneró**: conserva su contenido y
  su fecha como evidencia de aquel parche.

---

### 2026-08-09 · Sub-paso 2.1 — el módulo puro existe, y la spec cambió una vez al escribirlo

**Estado: cerrado.** `politica/` implementado, 150 tests en verde, criterio de aceptación reproducido
exacto. Una corrección de política (O3, abajo) y dos erratas del contrato de 2.1.

#### Qué se entregó

- `[HECHO]` `politica/` = `tipos.py` (HD5) · `parametros.py` (todos los valores, uno por constante
  nombrada) · `kleene.py` (§1.1, tablas escritas extendidas) · `motor.py` (`decidir()` y los niveles).
  Librería estándar pura: sin estado, sin I/O, sin voz, sin RAG, sin pandas. Un test lee los `import` del
  paquete con `ast` y falla si entra cualquier cosa fuera de `{__future__, math, typing, dataclasses,
  enum, types}`, para que la restricción no dependa de que alguien se acuerde.
- `[HECHO]` **Criterio de aceptación reproducido sobre los 160**: `recall_rojo = 1.000`, `C_FN = c₁ = c₃ =
  0`, `c₂ = 11` (4 temprano + 7 tardío), `S1 = 12`, `S2 = 93`, `S3 = 36`, `CIERRE_FORZADO = 19`, los 19
  forzados de régimen temprano con `n_total == 1` y verde real. Equivalencia **caso a caso** con
  `scripts/verificacion_hd1.py`: 160/160 en clase y en criterio de cierre.
- `[INFERENCIA]` El oráculo se importa **solo** en `tests/test_dev_set.py`, nunca desde `politica/`. Si el
  módulo y su oráculo salieran del mismo código el test no probaría nada; la independencia es el activo.
- `[INFERENCIA]` **HD5, HD6 y HD7 quedan cerrados como contrato del módulo**, sin tocar
  `parametros_politica.md`: `Decision` como valor inmutable, orden total de indagación derivado de §7.3, y
  presupuesto que el módulo **lee y nunca muta** (el llamador cobra; el contrato vive en el docstring de
  `decidir`).
- `[INFERENCIA]` **El núcleo se deriva, no se enumera** (§1.2 lo pedía intensional): `NUCLEO` es la unión de
  las señales que aparecen en los predicados de §3, §4 y §5, calculada en `motor.py`. Si el anclaje al
  corpus añade o retira un predicado, el conjunto se ajusta solo y no hay una lista que actualizar en otro
  archivo.

#### Principio nuevo, y es el hallazgo que más lejos llega

> `[INFERENCIA]` **Todo umbral cuya banda crítica no tenga observaciones necesita un test de frontera sobre
> el dominio declarado, no sobre la muestra.**

- `[HECHO]` Salió de un **mutation testing** sobre `politica/parametros.py`: se muta un parámetro a la vez y
  se corre la suite completa; el mutante debe morir. De 15 mutantes, 14 murieron y **uno sobrevivió**:
  `UMBRAL_DOLOR_SEVERO: 7 → 8` no cambia **ni uno** de los 160 casos, porque `dolor_nrs ∈ {7,8}` no existe
  en el dev set (D3).
- `[INFERENCIA]` **El dev set no puede custodiar un umbral que vive en una banda que no observó.** El
  criterio de aceptación —160/160, todos los números exactos— es compatible con mover ese umbral, así que
  no es red de seguridad ahí. La red tiene que ser una aserción sobre el **dominio declarado** (§1: NRS
  0–10), que es normativo, y no sobre la muestra, que es contingente.
- `[INFERENCIA]` **O3 y el mutante superviviente son el mismo defecto visto desde dos lados.** Uno dice «la
  política decide algo en una banda sin evidencia»; el otro, «los tests no custodian esa decisión». Ambos
  se apoyan en el mismo hecho: cero observaciones en `{7,8,10}`. Por eso el correctivo es doble —decisión
  de política (O3) **y** test de frontera— y por eso queda escrito como principio y no como anécdota.
- `[INFERENCIA]` Emparienta directamente con el correctivo permanente de la enmienda de Fase 1 («toda
  afirmación de pureza declara su n y su n efectivo»): las dos reglas dicen que **la ausencia de
  contraejemplo en la muestra no es evidencia**, una para los documentos y otra para los tests.
- `[HECHO]` Tras añadir `test_frontera_de_cada_umbral` y el test de la banda severa, y tras la decisión de
  O3, **los 17 mutantes de todos los parámetros mueren**, incluidos los cuatro del umbral de dolor en sus
  dos regímenes.

#### O3 — DECISIÓN de política: `dolor_severo` pasa a tener umbral por régimen (7 tardío / 9 temprano)

- `[HECHO]` **El defecto detectado al implementar:** `decidir(día 1, dolor_nrs = 9, resto normal)` cerraba
  en **VERDE por S2, sin indagar**. Sale de aplicar la spec sin desviarse: §3 hacía la bandera
  `SOLO_TARDIO` (predicado `dolor >= 7 ∧ regimen == TARDIO`) y H3 exige `n_base >= 1` para que `s_dolor`
  cuente en temprano. El oráculo daba lo mismo, y el dev set no lo detecta porque `dolor_nrs = 9` solo
  aparece en casos tardíos.
- `[HECHO]` La banda severa no es decidible por el dev set: máximo de `dolor_nrs` en temprano = **6**;
  `dolor >= 7` solo existe en tardío (2 casos, ambos dolor 9, ambos ROJO); la banda `{7, 8, 10}` no tiene
  una sola observación en ningún régimen. **Cualquier umbral temprano en `{7,8,9,10}` cuesta cero sobre los
  160.**
- `[INFERENCIA]` **Dejar la banda sin cubrir no era la opción neutra.** La justificación de §3.1 —el dolor
  agudo de los días 1–3 es fisiología esperada— está medida **hasta 6** y no dice nada sobre 7–10. Extender
  ese permiso a la banda severa era una decisión activa, tomada con las mismas cero observaciones, solo que
  invisible. Bajo la matriz de costos (`C_FN` ≫ todo; `c₄`/`c₅` son las baratas), con cero evidencia la
  dirección segura es escalar.
- `[INFERENCIA]` **La asimetría de §3.1 no se rompe: se gradúa.** Sigue siendo cierto que el dolor severo
  significa menos en temprano que en tardío; lo que cambia es que la diferencia se expresa como **dos
  umbrales** y no como presencia/ausencia de bandera.
- `[ESPECULACIÓN]` **El valor 9**, sobre 7: el 7 queda a un punto del techo verde observado en temprano (6)
  y en capa 2 un paciente que redondea al alza se volvería ROJO; el 9 deja dos puntos de margen y es la
  única banda severa con observaciones, ambas ROJO (**n = 2, ambas tardías** — anclaje débil, declarado).
- `[INFERENCIA]` **Alternativas descartadas.** (a) *Dejarlo y declararlo*: el permiso seguía sin respaldo y
  es un blanco directo en la sustentación («¿su agente le dice a un paciente con dolor 9 al día siguiente
  de operarse que todo está normal?»). (b) *Que `s_dolor` cuente sin acompañamiento en temprano*: no
  alcanza — lleva el caso a `n_total = 1`, que con el umbral temprano ≥ 2 sigue cerrando VERDE, ahora por
  cierre forzado en vez de por S2; habría que tocar §5.2 también, deshaciendo la decisión de H4.
- `[INFERENCIA]` **Costo en runtime, aceptado y declarado:** un paciente temprano que no informa su dolor y
  agota el presupuesto pasa de AMARILLO a **ROJO**. Se acepta por simetría — un paciente temprano que no
  describe su herida ya salía ROJO por §8 —, y porque esa diferencia era un artefacto del `SOLO_TARDIO`
  filtrándose al mecanismo de banderas pendientes, no una decisión clínica.
- `[HECHO]` **Los números del criterio de aceptación no se mueven.** La salida re-versionada del oráculo
  difiere de la anterior **solo en la línea de fecha**: cuerpo byte a byte idéntico.
- **Deuda nueva:** el umbral temprano `9` entra a la deuda de anclaje al corpus como **ítem propio** (ver
  abajo). La enmienda de Fase 1 no se edita —es registro fechado—: la lista vigente de esa deuda vive aquí.

#### O1 — error del arquitecto: una demostración que contradecía un colapso de Kleene ya derivado

- `[HECHO]` §8 afirmaba: «si ninguna bandera está en `DESCONOCIDO`, entonces `herida`, `movilidad`,
  `fiebre_c` y `dolor_nrs` son conocidas […] la premisa no hay que verificarla: **se cumple sola**». Era
  **falso en régimen temprano**: con el predicado `dolor >= 7 ∧ regimen == TARDIO`, el dolor `AUSENTE` daba
  `D ∧ F = F` por Kleene fuerte (§1.1), o sea bandera **descartada**, no pendiente.
- `[INFERENCIA]` **La tabla de §8 nunca estuvo mal; lo falso era su justificación.** La resolución del caso
  es la misma (AMARILLO con `confianza = baja`), así que ninguna salida cambiaba. Por eso el defecto es
  peligroso: una descripción que envejece mal se nota al leerla, una **demostración** que envejece mal se
  sigue leyendo bien. Es literalmente el argumento que esta bitácora ya había registrado al prohibir las
  citas por posición, aplicado ahora a una premisa en vez de a una referencia.
- `[INFERENCIA]` **Mecanismo del error, para que no se repita:** el arquitecto escribió la demostración de
  exhaustividad **tres parches después** de haber derivado él mismo el colapso `D ∧ F = F` para la bandera
  de dolor. El colapso estaba en la spec y la demostración lo contradecía sin citarlo. No fue un descuido
  de lectura: fue razonar sobre las señales («¿qué puede faltar?») en vez de sobre los predicados («¿qué
  evalúa cada bandera cuando falta?»), que es exactamente el nivel en el que vive el tercer valor.
- `[INFERENCIA]` **Resuelto en su raíz por O3**, no por parche: con umbral indexado por régimen, el dolor
  `AUSENTE` deja la bandera en `DESCONOCIDO` en **ambos** regímenes y la premisa de §8 vuelve a ser
  verdadera. La tabla no se tocó.
- `[INFERENCIA]` El módulo **verifica** la premisa en vez de asumirla, y se deja así **por defensa**: es
  correcta hoy por §3, pero no depende de §3. Si un predicado futuro vuelve a hacer que una bandera colapse
  a `FALSO` con su señal ausente, ese ramal sigue eligiendo bien sin que nadie tenga que acordarse.

#### O2 — errata de referencia en el contrato de 2.1

- `[HECHO]` El contrato decía que el tercer nivel de prioridad de §7.3 va «en orden de la tabla de §1»,
  pero la lista literal que daba (`fiebre_c, herida, apetito, sueno, dolor_nrs`) es el orden de **§5.1**.
  La lista era y sigue siendo lo normativo; la referencia estaba mal. Corregida en el docstring de
  `ORDEN_DISCRIMINADORES`.
- `[INFERENCIA]` Sin consecuencia sobre el comportamiento: el implementador siguió la lista, no la
  referencia. Se registra porque el próximo lector podría hacer lo contrario.

#### Nota de proceso

- `[INFERENCIA]` Los tres hallazgos salieron de **implementar**, no de leer. La auditoría de spec previa a
  2.1 (HD1–HD4) era necesaria y no fue suficiente: hay defectos que solo aparecen cuando alguien tiene que
  escribir el `if`. Vale como argumento para la sustentación —el diseño se validó ejecutándolo— y como
  criterio para el resto de Fase 2: **implementar es un método de auditoría, no solo su consecuencia.**

---

## Deudas y pendientes abiertos

> **Actualizado 2026-08-09** tras el cierre de 2.1. Los dos .docx de diseño quedan **superados por
> `docs/diseno/enmienda_auditoria_fase1.md` en todo punto de conflicto**; los parámetros operativos vigentes
> están en `docs/diseno/parametros_politica.md`. Ningún valor de política se codifica fuera de ese archivo.
> **Esta lista es la vigente**: la tabla de deuda de RAG de la enmienda es registro fechado y no se edita,
> así que los ítems añadidos después del 2026-08-08 existen solo aquí.

- **[BLOQUEANTE · antes de la sesión de evaluación] Anclaje al corpus de las CUATRO banderas y del corte
  temporal.** *(Elevada de «diferida a fase RAG» y ampliada — antes cubría solo la bandera de dolor.)*
  Localizar en los 107 PDFs, **en este orden de prioridad**:
  1. **(e) Ventana de presentación de la ISQ superficial (desde el día 4)** — sostiene el corte del
     enrutador. **Primera búsqueda**: es la única de las tres anclas externas sin fuente verificada, y si
     el corpus no la sustenta el corte del enrutador queda sin respaldo. Ver la deuda «Confianza desigual
     entre las tres anclas externas» al final de esta sección.
  2. (a) Partición de severidad NRS 7–10 — bandera `dolor ≥ 7`. Convención clínica establecida; se espera
     que el corpus la confirme.
  3. (b) Umbral febril postquirúrgico de 38.0 °C — bandera `fiebre_franca`. Ídem.
  4. (c) Criterios de ISQ para secreción purulenta, y (d) deterioro funcional agudo para movilidad
     incapacitante nueva. Menor urgencia: D2 mostró que ninguna de las dos aporta cobertura que la fiebre
     no dé ya, así que su cita sirve a la defendibilidad, no al recall.
  5. **(f) Dolor severo en régimen TEMPRANO — umbral 9.** *(Ítem añadido el 2026-08-09 por la decisión O3;
     no está en la tabla de la enmienda, que es registro fechado.)* Es el **único parámetro del sistema
     con etiqueta `[ESPECULACIÓN]` en su origen**: la banda severa no tiene ni una observación en régimen
     temprano (`max = 6`), así que nada medido lo fija y el dev set no puede confirmarlo ni refutarlo.
     Prioridad **alta pese a ir de quinto**: es el que menos respaldo tiene de los seis, y a diferencia de
     (e) ni siquiera hay un dato adyacente con el que acotarlo. Si el corpus no dice nada sobre severidad
     del dolor por día postoperatorio, se sustenta como decisión de matriz de costos y **hay que decirlo
     así en la sustentación**.

  Citarlas en el registro de escalamiento (`citas_RAG`, hoy vacío para las cuatro). Riesgo: si el corpus no
  sustenta (a), la cobertura defendible del Nivel 1 cae a 11/12.
- **[Fase 3] Verificar la consecuencia declarada de HD2.** Medir sobre capa 2 la tasa de **S2 alcanzado** y
  la de **AMARILLO por agotamiento**. Con seis señales de núcleo (`parametros_politica.md` §1.2) contra un
  tope global de 6 turnos, S2 exige cosecha perfecta. Si VERDE resulta casi inalcanzable, **el sospechoso es
  el tope global de 6, no la política** — se calibra el tope antes de tocar ningún umbral. Emparentada con la
  deuda de calibración de topes, de la que es el criterio de disparo.
- **[Fase 3] Calibración de los topes de indagación.** Los valores fijados (2 por señal, 6 global) son
  `[ESPECULACIÓN]` dentro de los rangos declarados 2–3 y 6–8. Calibrar en prototipo midiendo sobre capa 2
  (no capa 1).
- **[Fase 2/RAG] OCR del PDF escaneado de Appendicitis/.** Un PDF del corpus está escaneado sin capa de
  texto. Decidir: OCR (persistido como artefacto) o descartar explícitamente. No dejarlo como hueco
  silencioso.
- **[Fase 2] La regla de agregación TEMPRANA es diseño nuevo, sin validar end-to-end.**
  `politica_decision.docx` solo especificaba la rama tardía; la temprana (`n_total ≥ 2 → amarillo`) se
  redactó en `parametros_politica.md` §5.2 como `[INFERENCIA]` de diseño. Medida sobre vector completo da
  4 c₂ y 0 c₁ (contra 19 c₂ de la extensión que usó el auditor), pero no está validada bajo evasión.
- **[Fase 2] Confirmar la ventana de 30 días del corpus.** El borde `dia_postop > 30` → «fuera de alcance»
  (`parametros_politica.md` §2.1) es `[ESPECULACIÓN]`. Se confirma o se ajusta al indexar los 107 PDFs.
- **[Protocolo] Reemitir el IC a nivel paciente.** Todo recall reportado usa Wilson sobre **n=6 pacientes**
  ([0.610, 1.000]), no sobre n=12 casos. La unidad de remuestreo de cualquier bootstrap es el paciente. La
  cifra «un error mueve el recall ~8 pt» que aparece en los .docx es **~17 pt**.
- **[Fase 2 · menor] Clasificar el origen de `fiebre ≥ 37.5` (señal blanda).** El umbral
  (`parametros_politica.md` §5.1) **hereda su valor de los .docx sin reexaminar**: H1 corrigió su predicado
  —quitar «sostenida»— no su valor. Falta determinar si es ancla externa (febrícula convencional) o
  selección sobre el dev set. *(La otra mitad de esta deuda, `dolor ≥ 5`, ya está clasificada: es selección
  sobre el dev set, mismo número y mismo hecho que `g_dolor`. Lo que queda de ella es hacer converger las
  dos filas — ver «Convergencia de `dolor ≥ 5`» al final de esta sección.)*
- **[Protocolo] Añadir el par de colisión a la batería de casos-frontera.** `…00012_7` (amarillo) vs
  `…00017_7` (rojo), ambos con fiebre 37.9 y eritema al día 7. Es el test de que la política discrimina por
  vector y no por termómetro (D5).
- **[Fase RAG] Convergencia de `dolor ≥ 5`.** El valor aparece **dos veces** en
  `parametros_politica.md` §10: como `g_dolor` (compuerta de Nivel 1.5) y como señal blanda
  tardía (Nivel 2). *Se registró originalmente como «dos procedencias distintas»; al alinear se
  verificó que es una sola*: ambas filas son **selección sobre el dev set**, primer entero por
  encima de `verde_max` tardío = 4. Mismo número, mismo hecho, semántica distinta (una prohíbe
  cerrar en verde, la otra cuenta para el agregado). Al resolver el anclaje al corpus, ambas
  filas deben converger o justificar por qué difieren. **Mientras tanto no se editan por
  separado: cambiar una sin la otra es un bug silencioso.**
- **[Fase 3 · menor · NO bloqueante de 2.1] Limitación declarada: no existe el estado «señal obtenida sin
  confirmar».** El modelo de valores de `parametros_politica.md` §1.1 no distingue «señal no obtenida» de
  «señal obtenida y no confirmada», así que el cierre forzado (§7.4) **no puede gastar presupuesto en
  verificar una señal blanda aislada en régimen temprano** (p. ej. repreguntar si la fiebre se midió con
  termómetro) — con vector completo no hay nada `AUSENTE` que indagar, aunque el único positivo del caso sea
  precisamente el que convendría confirmar. Reintroducirlo exigiría un **cuarto estado por señal**. Fuera de
  alcance de Fase 2; se registra como opción de Fase 3.
- **[Fase RAG] Confianza desigual entre las tres anclas externas.** `[INFERENCIA]` El umbral
  febril de 38.0 °C y la partición NRS 7–10 son convenciones clínicas establecidas. La ventana
  de presentación de la ISQ superficial desde el día 4 —que es lo que fija el corte del
  enrutador— es una inferencia del arquitecto, **sin verificar contra fuente alguna**. Si el
  corpus confirma las dos primeras y no la tercera, el parámetro que queda sin sustento es el
  corte del enrutador. **Es lo primero que hay que buscar en los 107 PDFs.**
