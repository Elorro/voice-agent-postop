# Enmienda de auditoría — Fase 1

**Fecha:** 2026-08-08
**Autor:** Luis A. Araque Ovalle
**Estado:** vigente. Documento de errata y corrección.

---

## Alcance y precedencia

Este documento **supersede a `politica_decision.docx` y a `protocolo_validacion.docx` en todo punto de
conflicto**. Los dos `.docx` se conservan sin corregir su cuerpo, como registro histórico del diseño
original y de su revisión; ambos llevan un aviso de superación insertado como primer párrafo. Cuando una
afirmación de un `.docx` contradiga a este documento, gana este documento. Los parámetros operativos
vigentes —los que se implementan— viven en `parametros_politica.md`, no aquí ni en los `.docx`.

**Reproducibilidad.** Todo número marcado `[HECHO]` en este documento sale de:

```bash
DATASET_DIR=/ruta/a/ParticipantArtifacts/dataset python3 scripts/auditoria_fase1.py
```

El script es determinista, idempotente, sin red, y falla ruidoso si el join no cierra. Las referencias
`(A1)…(A10)` apuntan a sus secciones. Dos tablas de este documento (la de Nivel 1.5 y el desagregado de
eritema) requieren desagregaciones por régimen que el script imprime parcialmente; se anota en cada caso.

**Convención epistemológica.**

| Etiqueta | Significado |
|---|---|
| `[HECHO]` | Verificado sobre el dataset o los `.md` del reto. Reproducible. |
| `[INFERENCIA]` | Deducción a partir de hechos + razonamiento clínico o de diseño. |
| `[ESPECULACIÓN]` | Supuesto sin medición directa. Declarado como tal. |

**Base de la auditoría.** Los 160 casos del dev set (123 verde / 25 amarillo / 12 rojo), join íntegro
160/160 vía `caso_id = "caso_" + trayectoria_id` (A1). Ese desbalance y el join sí se confirman, igual que
la pureza de `secrecion_purulenta` (n=3, 3 rojos) y `movilidad = incapacitante_nueva` (n=4, 4 rojos), y los
8 ambiguos de Q4 (los 8 con eritema_leve). Lo que sigue es lo que **no** se confirmó.

---

## D1 — `[HECHO]` falso: la pureza de apetito y sueño no existe

**Qué decía el documento.** `politica_decision.docx` §1.2, tabla de anclas categóricas:
`apetito = muy_disminuido` → «29 casos, cero verdes»; `sueno = muy_alterado` → «32 casos, cero verdes».

**Qué dicen los datos.** `[HECHO]` (A2). Los conteos totales son correctos; la lectura de pureza es falsa.

| Señal | n | amarillo | rojo | **verde** |
|---|---|---|---|---|
| `apetito = muy_disminuido` | 29 | 12 | 12 | **5** |
| `sueno = muy_alterado` | 32 | 16 | 12 | **4** |

Los cinco verdes de apetito son `…00015_7`, `…00017_1`, `…00027_1`, `…00028_3`, `…00030_1`.
Los cuatro de sueño son `…00000_7`, `…00002_7`, `…00026_3`, `…00037_7`.
`[HECHO]` **Los dos conjuntos de verdes son disjuntos: intersección = 0.**

**Qué queda.** No son anclas puras. Son **señales de alta sensibilidad y baja especificidad sobre verde**:
capturan los 12/12 rojos, pero 9 verdes distintos se cuelan por ellas. Su lugar correcto no es el Nivel 1
(bandera roja) ni una afirmación de pureza; es el Nivel 2 como señal blanda —donde ya estaban en la
práctica— y, en conjunción, el Nivel 1.5 que este documento introduce más abajo. La disyunción de las dos
arrastra 9 verdes; la conjunción, ninguno. Esa diferencia es todo el hallazgo constructivo.

---

## D2 — El Nivel 1 no tiene la redundancia que su diseño supone

**Qué decía el documento.** `politica_decision.docx` §1.2: «Las anclas categóricas puras son más robustas
que cualquier umbral numérico… Por eso **forman la columna vertebral del escalamiento forzado**». Y §6:
«el escalamiento se apoya en anclas categóricas y en indagación, **no en la fiebre sola**».

**Qué dicen los datos.** `[HECHO]` (A3). Cobertura de cada bandera de Nivel 1 sobre los 12 rojos, y en
cuántos de ellos es la **única** que dispara:

| Bandera | captura | única que dispara |
|---|---|---|
| fiebre ≥ 38.0 | **11/12** | **3** |
| movilidad `incapacitante_nueva` | 4/12 | **0** |
| herida `secrecion_purulenta` | 3/12 | **0** |
| dolor ≥ 7 (tardío) | 2/12 | **1** |

Con Nivel 1 completo: 0 falsos positivos sobre los 148 no-rojos, 0 rojos sin bandera. La cobertura es
real; la **redundancia** no.

**Las dos anclas categóricas no capturan ni un solo rojo que la fiebre no capture ya.** La columna
vertebral real del escalamiento es el umbral numérico de fiebre — exactamente el mismo que §1.4 declara
frágil. La afirmación de §6 está invertida: el escalamiento **sí** se apoya en la fiebre casi sola.

`[INFERENCIA]` **Qué queda.** Las anclas categóricas son **confirmatorias, no portantes**. Su valor no es
que amplíen cobertura —no lo hacen sobre esta muestra—, sino que un escalamiento apoyado en ellas es
defendible ante el jurado **sin depender de una frontera numérica**: «la herida supura» no admite discusión
de 0.1 °C. Se conservan en el Nivel 1 por esa razón y porque un rojo con purulenta y sin fiebre es
clínicamente posible aunque no esté en la muestra. Pero no se puede seguir diciendo que sostienen el
sistema.

`[HECHO]` **El umbral de fiebre no admite holgura en ninguna dirección** (A7, régimen tardío):

| umbral | rojos | amarillos | verdes tardíos |
|---|---|---|---|
| 37.5 | 12/12 | 4/10 | 4/58 |
| 37.7 | 12/12 | 2/10 | 1/58 |
| 37.8 | 12/12 | 1/10 | 0/58 |
| 37.9 | 12/12 | 1/10 | 0/58 |
| **38.0** | **11/12** | **0/10** | **0/58** |
| 38.1 | 7/12 | 0/10 | 0/58 |

Bajarlo a 37.9 **globalmente** atrapa un verde de día 3 (`caso_tray_pac_42_00002_3`, fiebre 37.9) —es el
único, pero rompe la pureza sobre verde que justifica la bandera—. Subirlo a 38.1 **pierde 4 rojos que
están exactamente en 38.0** (`…00026_7`, `…00026_14`, `…00027_14`, `…00030_14`). El umbral está encajado
entre dos paredes, con 12 rojos de muestra. Leave-one-patient-out (A7) no lo mueve —`verde_max` tardío se
mantiene en 37.7 sacando cualquiera de los 6 pacientes rojos—, lo que dice que la pared inferior es
estable, no que la superior lo sea.

---

## D3 — Refundación de la bandera de dolor

**Qué decía el documento.** `politica_decision.docx` §3.2 y tabla de banderas: «pureza 1.0:
dolor ∈ {7,8,9} solo en rojo; ningún verde/amarillo tardío lo alcanza».

**Qué dicen los datos.** `[HECHO]` (A3). **El dominio real de `dolor_nrs` en los 160 casos es
{0,1,2,3,4,5,6,9}: los valores 7 y 8 no existen.** La afirmación «dolor ∈ {7,8,9} tiene pureza 1.0» es
vacua en dos tercios de su banda y descansa sobre **2 observaciones, ambas con dolor = 9**
(`…00017_7` y `…00026_14`), y una de ellas (`…00026_14`, fiebre 38.0) ya dispara la bandera de fiebre.
Aporte marginal de la bandera: **1 caso**, `caso_tray_pac_42_00017_7`.

**Qué queda: la justificación se refunda, el umbral no cambia.**

`[INFERENCIA]` El 7 no es un artefacto del dataset. Es la **partición de severidad estándar de la escala
NRS**: 1–3 leve, 4–6 moderado, **7–10 severo**. Es el tercil severo de la propia escala, elegido antes de
mirar los datos y no ajustado a ellos. La justificación válida de la bandera es esa, no la pureza. El dato
se degrada de *justificación* a *verificación de consistencia*: los datos no contradicen el corte, y eso
es todo lo que aportan con n=2.

`[HECHO]` **La bandera es portante** (A4): sin ella, `recall_rojo` cae de **1.000 a 0.917**, con un
c₃ (rojo cerrado en amarillo). No es decorativa. Es el único mecanismo que captura `…00017_7`.

`[INFERENCIA]` **Alternativa evaluada y descartada: bajar el umbral de fiebre tardío a 37.8 °C.** Captura
12/12 rojos con 0/58 verdes (A7), así que a primera vista domina. Se descarta por tres razones:

1. Captura 12/12 **solo porque captura el mismo `…00017_7`** (fiebre 37.9). Sustituye una regla
   justificada por n=1 por un umbral justificado por el mismo n=1 — no compra evidencia, la recicla.
2. Pierde el anclaje clínico. 38.0 °C es una definición febril reconocible y citable; 37.8 °C es un
   número elegido para que un caso quepa. Ante el jurado, el segundo es indefendible.
3. `[HECHO]` No es gratis: fiebre ≥ 37.8 en tardío arrastra además 1 amarillo
   (`caso_tray_pac_42_00012_7`, fiebre 37.9) a ROJO — un c₅ que el umbral 38.0 no paga.

   Se documenta el descarte de forma explícita: sirve a la Pregunta 2 del video (qué se consideró y por
   qué se rechazó).

`[INFERENCIA]` **Asimetría de condicionamiento por régimen, declarada.** La fiebre **no** se condiciona por
régimen (38.0 °C escala cualquier día); el dolor **sí** (≥7 solo en tardío). La asimetría es principiada,
no una inconsistencia:

- 38.0 °C es una **definición clínica absoluta**, independiente del día postoperatorio. Un paciente con
  38.0 °C el día 1 tiene fiebre, punto.
- El dolor agudo de los días 1–3 es **fisiología esperada** de la herida quirúrgica.
  `[HECHO]` En régimen temprano los verdes llegan legítimamente a `dolor_nrs = 6`; en tardío,
  `verde_max = 4`. La misma cifra significa cosas distintas según el día.

Sin esta declaración explícita, la inconsistencia *aparente* («¿por qué una bandera se condiciona y la otra
no?») es un blanco fácil en la sustentación.

---

## D4 — El intervalo de confianza está mal construido

**Qué decía el documento.** `protocolo_validacion.docx` §1.3: IC Wilson sobre n=12 rojos; «un solo error
mueve el recall ~8 puntos (1/12 ≈ 8.3%)».

**Qué dicen los datos.** Wilson asume observaciones independientes y **no las hay**.
`[HECHO]` (A5): **los 12 rojos son 6 pacientes × días {7, 14}, y los seis pacientes son rojos en ambos
días.** No hay ni un paciente rojo en un día y no-rojo en el otro. La unidad independiente es el paciente;
n efectivo = 6, no 12.

| Unidad | n | Wilson 95 % para recall = 1.0 |
|---|---|---|
| caso (publicado) | 12 | [0.757, 1.000] |
| **paciente (correcto)** | **6** | **[0.610, 1.000]** |

**Qué queda.** El intervalo publicado es **~15 puntos optimista en su cota inferior**. Correcciones que
entran en vigor:

- El **intervalo a nivel paciente pasa a ser el principal**. El de caso se puede reportar como referencia,
  siempre etiquetado como optimista por dependencia intra-paciente.
- La **unidad de remuestreo en cualquier bootstrap futuro es el paciente, no el caso**. Remuestrear casos
  fabricaría independencia inexistente y estrecharía el intervalo de forma espuria.
- Se corrige «un error mueve el recall ~8 puntos»: a nivel paciente son **~17 puntos** (1/6 ≈ 16.7 %).
  La cifra que va al informe y a la sustentación es 17, no 8.

`[INFERENCIA]` Esto refuerza, no debilita, el encuadre ya adoptado en `protocolo_validacion.docx` §1.3:
con n efectivo = 6, ninguna comparación de recall entre variantes de política es concluyente. La
validación sirve para detectar roturas del mecanismo, no para elegir la mejor política por recall.

---

## D5 — Se reportó el margen barato y se omitió el caro

**Qué decía el documento.** `politica_decision.docx` §1.4 reporta el gap **verde↔rojo** en fiebre:
0.2 °C al día 7 (verde_max 37.7, rojo_min 37.9), 0.4 °C al día 14.

**Qué dicen los datos.** El gap verde↔rojo es real, pero es el margen **barato**. `[HECHO]` (A6): al día 7,
**amarillo y rojo colisionan exactamente en 37.9 °C**:

| caso | fiebre | dolor | herida | apetito | sueño | label |
|---|---|---|---|---|---|---|
| `caso_tray_pac_42_00012_7` | 37.9 | 4 | eritema_leve | levemente_disminuido | levemente_alterado | **amarillo** |
| `caso_tray_pac_42_00017_7` | 37.9 | 9 | eritema_leve | muy_disminuido | muy_alterado | **rojo** |

Se documentó la frontera cuyo error cuesta **c₂** (verde clasificado amarillo, la celda más barata de la
matriz) y se omitió la frontera cuyo error cuesta **c₃** (rojo cerrado en amarillo, la celda que §4.1
declara colapsada hacia falso negativo). Se reportó el margen que hacía ver bien al diseño.

**Qué queda.** `[INFERENCIA]` El par es un **test de discriminación, no de umbral**. Ningún ajuste del
umbral de fiebre los separa: tienen la misma fiebre y la misma herida. Los separan **el dolor** (4 vs 9) y
**apetito/sueño** (levemente alterados vs muy alterados) — es decir, exactamente la bandera de dolor de D3
y la conjunción del Nivel 1.5. Esto da una segunda lectura del par: es la evidencia de que el Nivel 1 no
puede descansar solo en fiebre.

El par entra a la **batería de casos-frontera** (`protocolo_validacion.docx` §4) como caso propio:
«dos casos con fiebre idéntica y clases distintas», con comportamiento esperado
`…00012_7 → amarillo`, `…00017_7 → rojo`. Es también el mejor caso para la defensa en vivo: muestra que la
política discrimina por vector, no por termómetro.

---

## D6 — Corte del enrutador temporal, nunca especificado

**Qué decía el documento.** `politica_decision.docx` §1.3 y §2 hablan de «régimen temprano (día 1–3)» y
«régimen tardío (7–14)» y de un enrutador que actúa antes de todo umbral — pero **nunca dicen dónde cae el
corte**. Los días 4, 5 y 6 no están asignados a ningún régimen.

**Qué dicen los datos.** `[HECHO]` **El dev set no contiene ninguna observación en los días 4, 5 y 6.** Los
días presentes son exactamente {1, 3, 7, 14}. Cualquier corte dentro de (3, 7) es **igualmente consistente
con los datos**: no es decidible por datos. Cualquier script o módulo que hoy tenga que clasificar un día 5
está adivinando.

**Qué queda.** `[INFERENCIA]` Si los datos no deciden, decide la **matriz de costos**. Costo medido de cada
dirección de error (A10, acotado usando los días adyacentes como proxy — 3 para «temprano tratado como
tardío», 7 para «tardío tratado como temprano»):

| Dirección del error | Costo medido |
|---|---|
| **temprano tratado como tardío** (sobre-escalar) | día 1: 3/37 verdes → amarillo (**8.1 %**). día 3: 6/28 (**21.4 %**). **Cero** pasan a rojo. Puro **c₂**, disparado **solo por `eritema_leve`** (los 6 casos del día 3 y los 3 del día 1 tienen todos eritema y ninguna otra señal). |
| **tardío tratado como temprano** (sub-escalar) | `caso_tray_pac_42_00017_7` cae de rojo a amarillo. Recall 1.000 → **0.833**. Es un **c₃**. (Día 14: sin efecto, recall se mantiene en 1.000.) |

`[INFERENCIA]` **Corte fijado: `dia_postop ≤ 3` → TEMPRANO; `dia_postop ≥ 4` → TARDÍO.**

El día 4 es el primer día clínicamente defendible:

- La respuesta inflamatoria aguda alcanza su pico en las primeras 48–72 h y luego declina. Hasta el día 3,
  dolor y febrícula son la fisiología esperada de una herida quirúrgica, no señal de alarma.
- La infección de sitio quirúrgico superficial se presenta clásicamente **desde el cuarto día**
  postoperatorio. El día 4 es donde la interpretación clínica de las mismas cifras cambia de signo.

Adelantar el corte al día 2 sería sobre-escalar sin fundamento: metería en régimen estricto el pico
inflamatorio normal. Retrasarlo al día 6 sería **elegir comodidad sobre seguridad en el único tramo ciego**
— compraría 0 % de c₂ a cambio de exponer tres días a la dirección c₃. Dado el orden C_FN ≫ c₃ ≫ c₁ > c₄ >
c₅ > c₂, la dirección barata es la correcta cuando no hay datos.

El costo además **crece con el día** (8.1 % en día 1 → 21.4 % en día 3), lo que refuerza cortar en 4 y no
antes: el c₂ que se paga en el día 4 será mayor que el del día 3, así que cada día que se adelante el corte
es más caro que el anterior. Cortar en 4 paga el mínimo compatible con no exponer días a c₃.

`[INFERENCIA]` **Se descartó un tercer régimen de transición para los días 4–6.** Definirlo exigiría
inventar umbrales intermedios sin una sola observación que los sostenga — sería `[ESPECULACIÓN]` disfrazada
de diseño, y triplicaría la superficie de reglas a validar sin ningún dato con el que validarlas.

---

## Hallazgo constructivo — Nivel 1.5, compuerta de no-verde

La auditoría no solo restó. `[HECHO]` En régimen tardío existen **tres condiciones independientes que
cubren cada una los 12/12 rojos sin tocar ni uno de los 58 verdes tardíos**:

| Condición (régimen tardío) | rojos | verdes | amarillos |
|---|---|---|---|
| `fiebre_c ≥ 37.8` | **12/12** | **0/58** | 1/10 |
| `dolor_nrs ≥ 5` | **12/12** | **0/58** | 6/10 |
| `apetito = muy_disminuido` **∧** `sueno = muy_alterado` | **12/12** | **0/58** | 3/10 |

> **Corrección respecto al borrador de esta enmienda.** El borrador daba `fiebre ≥ 37.5` con «0/58 verdes»
> y la conjunción con «8/10 amarillos». Ambas cifras son falsas y se corrigen arriba:
> `fiebre ≥ 37.5` en tardío **sí atrapa 4 verdes** (`…00000_7` 37.7, `…00037_7` 37.6, `…00012_14` 37.5,
> `…00038_14` 37.6) — el umbral con cero verdes es **37.8** (A7). Y la conjunción apetito∧sueño arrastra
> **3** amarillos tardíos, no 8: el 8 es el conteo **global** sobre ambos regímenes (A8 reporta n=20 →
> 12 rojo + 8 amarillo sin desagregar por régimen; los otros 5 amarillos son tempranos). El resultado
> corregido es mejor que el afirmado: el arrastre máximo baja de 8 a 6 amarillos.

`[INFERENCIA]` **Ninguna de las tres sirve como bandera roja.** Las tres arrastran amarillos (hasta 6 con
`dolor ≥ 5`); forzar ROJO compraría hasta **6 c₅**, y en el caso de `fiebre ≥ 37.8` sería además la
alternativa ya descartada en D3.

`[INFERENCIA]` **Su uso correcto es como condición necesaria de rojo — una compuerta de no-verde:**

> Si alguna de las tres condiciones se cumple, el caso **no puede cerrar en verde**, y **no puede cerrar en
> amarillo hasta que toda bandera de Nivel 1 quede activamente descartada**.

No fuerza una clase: prohíbe una salida. Encaja exactamente con el criterio ya establecido en
`politica_decision.docx` §4.1 («amarillo no es clase terminal con bandera roja pendiente») y le da, por fin,
un disparador medible en vez de un juicio cualitativo sobre qué cuenta como «bandera pendiente».

`[HECHO]` **Ninguna de las tres descansa en n pequeño.** Su afirmación fuerte es «cero verdes», y se apoya
sobre **58 verdes tardíos**, no sobre los 12 rojos. Es la diferencia estructural con todo lo que D1–D3
tumbaron: aquí el n que sostiene la afirmación es el grande, no el chico.

`[INFERENCIA]` **Esta es la redundancia que §1.2 afirmaba tener y no tenía** (D2). Tres mecanismos
independientes —termométrico, álgico y constitucional— cubren cada uno el 100 % de los rojos. Que fallen
los tres a la vez requiere un rojo sin fiebre, sin dolor moderado y sin deterioro de apetito ni de sueño.
**Costo sobre la muestra: cero.**

`[INFERENCIA]` **Límite declarado.** La conjunción `apetito ∧ sueño` es pura sobre verde **en conjunción**,
aunque cada parte por separado tenga 5 y 4 verdes respectivamente (D1) y esos 9 verdes sean disjuntos. Eso
es precisamente por qué la conjunción funciona: ningún verde de la muestra tiene ambos deterioros a la vez.
Es un **hecho sobre esta muestra, no una ley clínica**. Un paciente verde con inapetencia e insomnio
simultáneos es perfectamente concebible; no está en los 160. Se implementa, y se declara como el supuesto
más frágil del Nivel 1.5 — por eso la compuerta requiere **cualquiera** de las tres, no la conjunción.

---

## Deuda de RAG, elevada a bloqueante

`[INFERENCIA]` La deuda registrada en la bitácora («anclar dolor ≥ 7 al corpus», **diferida** a la fase de
RAG) se **amplía a las cuatro banderas y al corte temporal**, y pasa de **diferida a BLOQUEANTE antes de la
sesión de evaluación**.

Razón del cambio de estatus: D2 mostró que la cobertura del Nivel 1 descansa casi por completo en un umbral
numérico frágil (D3 mostró que la única bandera que lo complementa se apoya en n=2). Un Nivel 1 sin
anclaje al corpus es un conjunto de números derivados de un dataset sintético defendido con estadística de
n=6. El campo `citas_RAG` del registro de escalamiento (`politica_decision.docx` §5.1) **está hoy vacío para
las cuatro banderas**.

Hay que localizar en los 107 PDFs del corpus:

| # | Qué anclar | Bandera / parámetro que sostiene |
|---|---|---|
| a | Partición de severidad de la escala NRS (7–10 = severo) | dolor ≥ 7 (tardío) |
| b | Umbral febril postquirúrgico de 38.0 °C | fiebre ≥ 38.0 |
| c | Criterios de infección de sitio quirúrgico (ISQ) para secreción purulenta | herida = `secrecion_purulenta` |
| d | Deterioro funcional agudo como signo de alarma | movilidad = `incapacitante_nueva` |
| e | Ventana de presentación de la ISQ (desde el día 4) | corte del enrutador temporal (D6) |

`[INFERENCIA]` **Consecuencia si el corpus no sustenta (a):** la cobertura defendible del Nivel 1 cae a
**11/12** y desaparece el mecanismo que captura `caso_tray_pac_42_00017_7`. La bandera se puede sostener
igual sobre la escala NRS estándar, pero sin cita se defiende como convención, no como criterio del corpus,
y hay que decirlo así en la sustentación. **Esto hay que saberlo antes de la sesión de evaluación, no
durante.**

`[INFERENCIA]` La compuerta de Nivel 1.5 mitiga parcialmente el riesgo: `…00017_7` cumple las tres
condiciones (dolor 9, apetito muy_disminuido ∧ sueño muy_alterado), así que aunque la bandera de dolor
caiga, el caso no puede cerrar en verde. Cerraría en amarillo con bandera descartada, que sigue siendo un
c₃. Mitiga, no resuelve.

---

## Nota de contagio

Afirmaciones de los `.docx` que quedan insostenibles por esta enmienda y que **no** se corrigen en su
cuerpo (se conservan como registro histórico):

- **`politica_decision.docx` §1.2**, tabla de anclas: las celdas «cero verdes» de apetito y sueño son
  falsas (D1). El párrafo que sigue («forman la columna vertebral del escalamiento forzado») es falso
  sobre los datos (D2).
- **`politica_decision.docx` §1.4** reporta el margen barato y omite el caro (D5).
- **`politica_decision.docx` §3.2**, tabla de banderas: la celda «pureza 1.0: dolor ∈ {7,8,9}» es vacua en
  {7,8} (D3).
- **`politica_decision.docx` §6**, tercer límite: «por eso el escalamiento se apoya en anclas categóricas y
  en indagación, **no en la fiebre sola**» — D2 la contradice de frente. Es la frase más expuesta del
  documento en una sustentación técnica. Primer límite: «1 error ≈ ±8 pt» → son ±17 (D4).
- **`protocolo_validacion.docx` §1.2** **no cambia en su conclusión** —los 12 rojos siguen siendo «claros»
  por unión de banderas— pero **sí en su lectura**: 11 de los 12 lo son por fiebre, no por la unión de
  cuatro anclas independientes. La categoría «rojo-claro» es más frágil de lo que su nombre sugiere.
- **`protocolo_validacion.docx` §1.3 y §7**: el IC y la cifra de ±8 pt están mal construidos (D4).

---

## Patrón de fondo (para el informe final)

`[INFERENCIA]` **Cinco de los seis defectos son el mismo error**: *pureza observada sobre un dev set pequeño,
leída como propiedad estructural*.

- D1: «cero verdes» sobre 29 y 32 casos — falso, y aun de ser cierto sería una propiedad de la muestra.
- D2: cobertura leída como redundancia sin medir el solapamiento entre banderas.
- D3: «pureza 1.0» sobre una banda cuyo dominio real tiene 2 observaciones.
- D4: intervalo construido sobre n=12 sin verificar que las 12 observaciones fueran independientes.
- D5: se reportó la frontera limpia y no se buscó la sucia.

(D6 es de otra familia: un parámetro simplemente nunca especificado.)

El mecanismo del error es común: **la exploración buscó confirmación de una estructura ya intuida en vez de
buscar el contraejemplo.** Cada `[HECHO]` era literalmente verdadero sobre alguna consulta —los conteos de
D1 eran correctos— pero la consulta que se corrió no era la que la afirmación necesitaba.

**Correctivo permanente adoptado:** *toda afirmación de pureza declara su n y su n efectivo.*

Operativamente, a partir de hoy ninguna afirmación entra a un documento de diseño con la etiqueta `[HECHO]`
si no viene con:

1. El **n** sobre el que se mide la afirmación (y no el n del conjunto que la hace ver bien).
2. El **n efectivo**, cuando las observaciones no son independientes (D4: 12 casos → 6 pacientes).
3. La **consulta reproducible** que la produce, en `scripts/`, corrible por un tercero.
4. El **contraejemplo buscado explícitamente** y no encontrado — no solo la confirmación hallada.

Este documento se somete a su propia regla: la corrección de la tabla de Nivel 1.5 (recuadro más arriba)
es un defecto encontrado al aplicar el punto 1 al borrador de esta misma enmienda.
