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

### Nota de contagio en los .docx
- `politica_decision.docx` §1.4 y §6 contienen ahora frases insostenibles —en particular «el escalamiento se
  apoya en anclas categóricas, no en la fiebre sola»— que D2 contradice de frente.
- `protocolo_validacion.docx` §1.2 **no cambia en su conclusión** (los 12 siguen siendo «claros» por unión
  de banderas) **pero sí en su lectura**: 11 de los 12 lo son por fiebre.
- Ambos conservan su cuerpo sin corregir, como registro histórico, con el aviso de superación al inicio.

---

## Deudas y pendientes abiertos

> **Actualizado 2026-08-08** tras la auditoría de Fase 1. Los dos .docx de diseño quedan **superados por
> `docs/diseno/enmienda_auditoria_fase1.md` en todo punto de conflicto**; los parámetros operativos vigentes
> están en `docs/diseno/parametros_politica.md`. Ningún valor de política se codifica fuera de ese archivo.

- **[BLOQUEANTE · antes de la sesión de evaluación] Anclaje al corpus de las CUATRO banderas y del corte
  temporal.** *(Elevada de «diferida a fase RAG» y ampliada — antes cubría solo la bandera de dolor.)*
  Localizar en los 107 PDFs: (a) partición de severidad NRS 7–10; (b) umbral febril postquirúrgico de
  38.0 °C; (c) criterios de ISQ para secreción purulenta; (d) deterioro funcional agudo para movilidad
  incapacitante nueva; (e) ventana de presentación de la ISQ que sostiene el corte en día 4. Citarlas en el
  registro de escalamiento (`citas_RAG`, hoy vacío para las cuatro). Riesgo: si el corpus no sustenta (a),
  la cobertura defendible del Nivel 1 cae a 11/12.
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
- **[Fase 2 · menor] Clasificar el origen de los dos umbrales de señal blanda.** `fiebre ≥ 37.5` y
  `dolor ≥ 5` (`parametros_politica.md` §5.1) **heredan su valor de los .docx sin reexaminar**: H1 y H3
  corrigieron su predicado, no su umbral. Falta determinar si son ancla externa o selección sobre el dev
  set — es la única casilla de la tabla de trazabilidad §10 que queda sin familia teniendo valor numérico.
- **[Protocolo] Añadir el par de colisión a la batería de casos-frontera.** `…00012_7` (amarillo) vs
  `…00017_7` (rojo), ambos con fiebre 37.9 y eritema al día 7. Es el test de que la política discrimina por
  vector y no por termómetro (D5).
