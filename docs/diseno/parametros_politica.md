# Parámetros operativos de la política de decisión

**Fecha:** 2026-08-08 · **Estado:** vigente · **Versión:** 1.0

---

## 0. Qué es este archivo

Fuente **única, diffable y legible por máquina** de los parámetros operativos de la política de decisión
clínica. De aquí deriva el módulo puro de Fase 2 (`politica/` — sin estado, sin dependencias de voz ni de
RAG, importado idénticamente por el validador y por el agente de producción).

Tres reglas de uso:

1. **Ningún valor de este archivo se codifica en otro lado.** Si un umbral aparece duplicado en código, en
   un prompt o en un `.docx`, este archivo gana y el duplicado es un bug.
2. **Si un parámetro no está aquí, el módulo no se puede escribir.** Este documento se considera incompleto
   —no el código— cuando la implementación tenga que decidir algo por su cuenta.
3. **Precedencia documental:** este archivo y `enmienda_auditoria_fase1.md` superseden a
   `politica_decision.docx` y `protocolo_validacion.docx` en todo punto de conflicto. Los `.docx` son
   registro histórico.

**Convención epistemológica:** `[HECHO]` verificado sobre el dataset o los `.md` del reto, reproducible con
`scripts/auditoria_fase1.py` · `[INFERENCIA]` deducción a partir de hechos + razonamiento clínico o de
diseño · `[ESPECULACIÓN]` supuesto sin medición directa, declarado.

---

## 1. Dominios de las señales

`[HECHO]` Verificado sobre `trayectorias_postop_silver.xlsx` (hoja `result`, 160 filas, 0 nulos en las
**siete columnas de la tabla**). Reproducible: aserción de nulos en `cargar()` de
`scripts/verificacion_hd1.py`.

| Señal | Tipo | Dominio declarado | Observado en el dev set |
|---|---|---|---|
| `dia_postop` | entero ≥ 0 | días desde la cirugía | **{1, 3, 7, 14}** |
| `dolor_nrs` | entero | **0–10** (escala NRS) | **{0,1,2,3,4,5,6,9}** — 7 y 8 **no existen** |
| `fiebre_c` | float, °C | temperatura corporal | 36.2 – 39.5 |
| `herida` | categórica | `normal` \| `eritema_leve` \| `secrecion_purulenta` | las 3 |
| `movilidad` | categórica | `normal` \| `limitada_esperada` \| `incapacitante_nueva` | las 3 |
| `apetito` | categórica | `normal` \| `levemente_disminuido` \| `muy_disminuido` | las 3 |
| `sueno` | categórica | `normal` \| `levemente_alterado` \| `muy_alterado` | las 3 |

**Notas de dominio.**

- `[INFERENCIA]` `dolor_nrs` se declara **0–10**, no {0,…,6,9}. El dominio observado es una propiedad del
  generador sintético; la escala NRS es 0–10 y el paciente puede reportar 7 u 8 en la evaluación en vivo.
  El módulo acepta cualquier entero 0–10. Un valor fuera de 0–10 es error de invocación (§8).
- `[HECHO]` El hueco {7,8} es lo que vació la afirmación de pureza de la bandera de dolor
  (`enmienda_auditoria_fase1.md` D3). El umbral ≥ 7 se sostiene por la partición estándar de severidad de
  la NRS (1–3 leve, 4–6 moderado, 7–10 severo), no por el dataset.
- `arquetipo_trayectoria` **no es una señal**. `[HECHO]` `recuperacion_normal` → 98.7 % verde;
  `complicacion_real` contiene el 100 % de los rojos. Es variable latente del generador que el agente no
  observa. Usarla sería *data leakage*. **Excluida del módulo de runtime**; el módulo no la recibe siquiera
  como argumento.

### 1.1 Ausencia — el cuarto valor de toda señal

`[INFERENCIA]` **Toda señal puede además estar AUSENTE** (no indagada todavía, o indagada y evadida). Esto
no es un caso de error: en capa 2 es la norma. Se modela explícitamente.

```
Valor(señal) ::= <valor del dominio> | AUSENTE
```

**El módulo evalúa en lógica trivaluada.** Todo predicado sobre una señal devuelve
`VERDADERO` | `FALSO` | `DESCONOCIDO`:

```
evaluar(P, señal):
    si Valor(señal) == AUSENTE  ->  DESCONOCIDO
    si no                       ->  VERDADERO | FALSO  según el predicado
```

`[INFERENCIA]` **Por qué trivaluada y no `AUSENTE → FALSO`.** Colapsar ausencia en falso hace que
«no sé si la herida supura» se comporte igual que «la herida no supura». Ese colapso convierte silenciosamente
un `DESCONOCIDO` en un descarte de bandera roja, que es exactamente el modo de fallo que
`politica_decision.docx` §4.1 quiere impedir con «amarillo no es clase terminal con bandera roja pendiente».
La distinción `FALSO` vs `DESCONOCIDO` **es** el mecanismo de «bandera pendiente»: sin ella, ese criterio no
es implementable.

**Reglas de composición** (Kleene fuerte, para la conjunción del Nivel 1.5 y para la disyunción de banderas):

| A | B | A ∧ B | A ∨ B |
|---|---|---|---|
| V | cualquiera | B | **V** |
| F | cualquiera | **F** | B |
| D | V | D | **V** |
| D | F | **F** | D |
| D | D | D | D |

### 1.2 El núcleo — definición intensional

`[INFERENCIA]` **«Núcleo» se reserva de aquí en adelante para el conjunto de señales de la política.** La
tabla de §1 lista las **siete columnas** que el join debe traer completas — un hecho sobre el dataset, no un
conjunto de la política: incluye `dia_postop`, que es dato del seguimiento y no señal indagable. El núcleo
son las **seis señales** que el agente debe cosechar. Los dos conjuntos difieren exactamente en `dia_postop`
y no deben confundirse: uno gobierna la integridad del dataset, el otro gobierna S2 y el invariante duro de
§8.1.

`[INFERENCIA]` **El núcleo es el conjunto de señales que aparecen en algún predicado de §3, §4 o §5.** No se
enumera: se deriva. Hoy esa unión es exactamente

```
nucleo = { herida, movilidad, fiebre_c, dolor_nrs, apetito, sueno }
```

y ninguna sobra: si falta cualquiera de las seis, o una bandera de Nivel 1 queda en `DESCONOCIDO`, o la
compuerta de Nivel 1.5 queda en `DESCONOCIDO`, o el conteo de §5 queda incompleto.

`[INFERENCIA]` **`dia_postop` NO pertenece al núcleo.** §2 ya lo establece: es dato del seguimiento, no algo
a inferir del paciente — **no es indagable**. El papel del núcleo en S2 (§7.1) y en el invariante duro
(§8.1) es «ya se preguntó todo lo que se podía preguntar»; incluir en ese conjunto algo que no se pregunta
rompe la definición desde dentro. Su ausencia tiene tratamiento propio y suficiente en §2.1: régimen TARDÍO
más `marca_incertidumbre`.

`[INFERENCIA]` **Qué se rompía con la lectura contraria.** Si `dia_postop` estuviera en el núcleo, un caso
con día desconocido y las seis señales clínicas obtenidas fallaría S2, declararía `REPREGUNTAR` accionable
por la letra de §7.1 —hay una señal del núcleo `AUSENTE`—, y el agente gastaría el presupuesto entero en una
pregunta sin destinatario, para caer al agotarse en AMARILLO por §8. Todo caso con día desconocido cerraría
en AMARILLO en el mejor de los casos, contradiciendo §2.1, que lo trata como manejable. Es HD1 reapareciendo
por otra puerta: una acción declarada accionable que no puede ejecutarse.

`[INFERENCIA]` **Por qué intensional y no una lista.** Definido como unión de los predicados vigentes, el
núcleo se mantiene solo: si el anclaje al corpus (deuda RAG) añade o retira un predicado, el conjunto se
ajusta sin que nadie recuerde editar una lista en otro archivo. Una lista enumerada sería un segundo lugar
donde vive un parámetro, contra la regla 1 de §0.

`[INFERENCIA]` **Consecuencia declarada, verificable en Fase 3.** Con seis señales en el núcleo y el tope
global en 6 turnos (`[ESPECULACIÓN]`, §7.2), alcanzar S2 exige cosecha perfecta. En capa 2 se espera que
VERDE sea infrecuente y que la tasa de AMARILLO suba. Es el primer sitio donde mirar si los topes resultan
cortos al calibrarlos.

`[HECHO]` No decidible por el dev set: los 160 casos tienen las siete columnas completas, cero ausencias
(`scripts/verificacion_hd1.py`, aserción de nulos en `cargar()`).

---

## 2. Nivel 0 — Enrutador temporal

Primer nodo. Deriva el régimen **antes** de aplicar cualquier umbral. `dia_postop` es dato del seguimiento,
no algo a inferir del paciente.

```yaml
nivel_0_enrutador:
  corte: 4                    # dia_postop >= 4 -> TARDIO
  regla:
    - dia_postop <= 3  -> TEMPRANO
    - dia_postop >= 4  -> TARDIO
```

`[INFERENCIA]` **El corte en 4 no es decidible por datos** — `[HECHO]` el dev set no tiene ninguna
observación en los días 4, 5 y 6. Se fija por matriz de costos y por criterio clínico (ventana de
presentación de la ISQ superficial desde el cuarto día). Derivación completa y costo medido de cada
dirección: `enmienda_auditoria_fase1.md` D6.

### 2.1 Casos de borde del dominio (todos obligatorios)

| Entrada | Salida | Justificación |
|---|---|---|
| `dia_postop = 0` (mismo día de la cirugía) | **TEMPRANO** | `[INFERENCIA]` Es el extremo del régimen inflamatorio agudo. Ningún umbral tardío tiene sentido a las horas de operar. |
| `dia_postop ∈ [1, 3]` | **TEMPRANO** | Regla base. |
| `dia_postop ∈ [4, 30]` | **TARDÍO** | Regla base. |
| `dia_postop` **AUSENTE / desconocido** | **TARDÍO** + `marca_incertidumbre = "dia_postop_desconocido"` | `[INFERENCIA]` Dirección segura: el error temprano→tardío es puro c₂ (celda más barata); el error tardío→temprano es c₃ (D6). Sin dato, se paga la celda barata. La marca es obligatoria y viaja al registro de escalamiento. |
| `dia_postop < 0`, o **no entero** | **ERROR DE INVOCACIÓN** — excepción, no clasificación | `[INFERENCIA]` Un día negativo o fraccionario es un bug del llamador, no una entrada clínica ambigua. **Falla ruidoso, no adivina.** Devolver una clase aquí enmascararía el bug en producción. |
| `dia_postop > 30` | **TARDÍO** + `fuera_de_alcance = true` en el registro | `[INFERENCIA]` Fuera de la ventana de seguimiento que cubre el corpus clínico. Se aplican umbrales tardíos (dirección segura) **y** se declara la salida de alcance en el registro: la decisión se emite, pero se marca como no respaldada por el corpus. No se silencia ni se rechaza. |

`[ESPECULACIÓN]` El límite de 30 días es el borde declarado de la ventana de seguimiento postoperatorio
que el corpus cubre. Se confirma o se ajusta al indexar los 107 PDFs (deuda RAG, ítem (e) de la enmienda).

---

## 3. Nivel 1 — Banderas rojas

Precedencia absoluta. **Si cualquier bandera evalúa `VERDADERO` → ROJO**, en cualquier régimen, sin evaluar
Nivel 1.5 ni Nivel 2. Si alguna evalúa `DESCONOCIDO`, queda **pendiente** (§7.1 y §8).

```yaml
nivel_1_banderas:
  - id: purulenta
    predicado: herida == "secrecion_purulenta"
    regimen: AMBOS
    base_empirica: "n=3, 3/3 rojo (A1). Captura 3/12 rojos, unica en 0 (A3)."
    ancla_rag: PENDIENTE      # criterios de ISQ

  - id: movilidad_incapacitante
    predicado: movilidad == "incapacitante_nueva"
    regimen: AMBOS
    base_empirica: "n=4, 4/4 rojo (A1). Captura 4/12 rojos, unica en 0 (A3)."
    ancla_rag: PENDIENTE      # deterioro funcional agudo

  - id: fiebre_franca
    predicado: fiebre_c >= 38.0
    regimen: AMBOS            # NO condicionada por regimen: es definicion clinica absoluta
    base_empirica: "Captura 11/12 rojos, unica en 3 (A3). 0 verdes en toda la muestra."
    ancla_rag: PENDIENTE      # umbral febril postquirurgico

  - id: dolor_severo
    predimado_nota: "vease predicado"
    predicado: dolor_nrs >= 7  AND  regimen == TARDIO
    regimen: SOLO_TARDIO
    base_empirica: "Captura 2/12 rojos, unica en 1 (A3). Portante: sin ella recall_rojo 1.000 -> 0.917 (A4)."
    justificacion: "Particion de severidad estandar NRS (7-10 = severo), NO pureza en datos."
    ancla_rag: PENDIENTE      # dolor severo tardio como signo de alarma
```

**Estado de anclaje al corpus: las cuatro están `PENDIENTE`.** `[INFERENCIA]` Ninguna bandera tiene hoy
cita del corpus. La deuda es **bloqueante antes de la sesión de evaluación**, no diferida
(`enmienda_auditoria_fase1.md`, sección de deuda de RAG). El campo `citas_RAG` del registro de escalamiento
no se puede emitir hasta que se resuelva.

### 3.1 Asimetría de condicionamiento, declarada

`[INFERENCIA]` `fiebre_franca` **no** se condiciona por régimen y `dolor_severo` **sí**. Es principiado:
38.0 °C es una definición clínica absoluta independiente del día postoperatorio, mientras que el dolor
agudo de los días 1–3 es fisiología esperada — `[HECHO]` los verdes tempranos llegan legítimamente a
`dolor_nrs = 6`, mientras que en tardío `verde_max = 4`. Declarar esto es obligatorio: sin la declaración,
la inconsistencia aparente es un blanco fácil en la sustentación.

### 3.2 Fragilidad declarada del umbral de fiebre

`[HECHO]` (A7) El umbral 38.0 °C está encajado entre dos paredes y no admite holgura: a 37.9 global atrapa
un verde de día 3 (`…00002_3`); a 38.1 pierde 4 rojos que están **exactamente** en 38.0. Con 12 rojos de
muestra (n efectivo = 6 pacientes), esta frontera es el punto más frágil del Nivel 1, y sostiene 11 de los
12 rojos. El Nivel 1.5 existe en buena medida para no depender solo de ella.

---

## 4. Nivel 1.5 — Compuerta de no-verde

`[HECHO]` (A7, A8, desagregado por régimen) En régimen tardío, tres condiciones independientes cubren cada
una los **12/12 rojos** sin tocar ni uno de los **58 verdes tardíos**:

| id | Condición | rojos | verdes | amarillos |
|---|---|---|---|---|
| `g_fiebre` | `fiebre_c >= 37.8` | 12/12 | **0/58** | 1/10 |
| `g_dolor` | `dolor_nrs >= 5` | 12/12 | **0/58** | 6/10 |
| `g_constitucional` | `apetito == muy_disminuido` **∧** `sueno == muy_alterado` | 12/12 | **0/58** | 3/10 |

```yaml
nivel_1_5_compuerta:
  regimen: SOLO_TARDIO
  activa_si: CUALQUIERA        # disyuncion, no conjuncion
  condiciones:
    - id: g_fiebre
      predicado: fiebre_c >= 37.8
    - id: g_dolor
      predicado: dolor_nrs >= 5
    - id: g_constitucional
      predicado: apetito == "muy_disminuido" AND sueno == "muy_alterado"
```

### 4.1 Semántica exacta

`[INFERENCIA]` **No fuerza una clase: prohíbe una salida.** Si la compuerta está activa
(cualquier condición `VERDADERO`):

1. El caso **no puede cerrar en VERDE**, bajo ninguna circunstancia, ni siquiera por S2.
2. El caso **no puede cerrar en AMARILLO** hasta que **toda** bandera de Nivel 1 evalúe `FALSO`
   (activamente descartada — `DESCONOCIDO` no descarta).
3. Si al agotar el presupuesto de indagación queda alguna bandera en `DESCONOCIDO` con la compuerta
   activa → **ROJO** (§8, caso «alguna bandera de Nivel 1 en `DESCONOCIDO`»).

`[INFERENCIA]` **La compuerta en `DESCONOCIDO` cuenta como activa** a efectos de prohibir salidas. Bajo
Kleene fuerte la disyunción de §4 puede evaluar `DESCONOCIDO`, y §7.1 (S2) y §8 la nombran en binario; esta
cláusula resuelve el tercer valor en la dirección segura.

`[INFERENCIA]` **Su costo hoy es cero, y conviene saber por qué.** Para alcanzar cualquier salida distinta
de ROJO, todas las banderas deben estar en `FALSO`, luego `herida`, `movilidad`, `fiebre_c` y `dolor_nrs`
son conocidas y `g_fiebre` y `g_dolor` están determinadas. La única condición que puede quedar en
`DESCONOCIDO` es `g_constitucional`, y si la disyunción entera queda en `DESCONOCIDO` es porque las otras
dos son `FALSO` — caso que §8 ya resuelve en AMARILLO, lo mismo que da tratarla como activa. La cláusula se
escribe igual: la neutralidad depende de la estructura actual, no es una ley, y sin declararla alguien
podría eliminarla por «redundante» y reintroducir el hueco cuando esa estructura cambie.

Es la implementación medible del criterio «amarillo no es clase terminal con bandera roja pendiente»
(`politica_decision.docx` §4.1), que hasta ahora era un juicio cualitativo sin disparador.

**Por qué no son banderas rojas.** `[INFERENCIA]` Las tres arrastran amarillos (hasta 6 con `g_dolor`);
forzar ROJO compraría hasta **6 c₅**. Además `g_fiebre` a 37.8 es la alternativa explícitamente descartada
en `enmienda_auditoria_fase1.md` D3. Como compuerta, su costo sobre la muestra es **cero**: no cambia
ninguna clasificación correcta, solo bloquea salidas prematuras bajo evidencia incompleta.

**Por qué son sólidas.** `[HECHO]` Su afirmación fuerte es «cero verdes», y se apoya sobre **58 verdes
tardíos**, no sobre los 12 rojos. El n que las sostiene es el grande.

**Límite declarado.** `[INFERENCIA]` `g_constitucional` es pura sobre verde **en conjunción**, aunque
`apetito = muy_disminuido` tenga 5 verdes y `sueno = muy_alterado` tenga 4 por separado (y esos 9 verdes
sean disjuntos). Es un hecho sobre esta muestra, no una ley clínica: un verde con inapetencia e insomnio
simultáneos es concebible. Por eso la compuerta requiere **cualquiera** de las tres, no la conjunción de
las tres.

**Régimen.** `[INFERENCIA]` La compuerta se restringe a TARDÍO porque sus tres condiciones se midieron
sobre los 58 verdes tardíos. En temprano no aplican: `[HECHO]` 11 verdes tempranos superan 37.5 °C, 6
verdes tempranos tienen `dolor_nrs >= 5`, y hay 5 amarillos tempranos en `g_constitucional`. Extenderla a
temprano sería afirmar sobre datos que no la sostienen — el error de D1.

---

## 5. Nivel 2 — Agregación de señales blandas

Solo se evalúa si **ninguna** bandera de Nivel 1 disparó. Separa VERDE de AMARILLO por conteo.

### 5.1 Conjunto de señales blandas

`[INFERENCIA]` `secrecion_purulenta` e `incapacitante_nueva` **no** aparecen aquí: son banderas de Nivel 1,
y el Nivel 2 solo se alcanza cuando evaluaron `FALSO`. Incluirlas sería código muerto.

```yaml
nivel_2_senales_blandas:
  base:                          # cuentan 1 cada una, en AMBOS regimenes
    - id: s_fiebre     ; predicado: fiebre_c >= 37.5
    - id: s_eritema    ; predicado: herida == "eritema_leve"
    - id: s_apetito    ; predicado: apetito == "muy_disminuido"
    - id: s_sueno      ; predicado: sueno == "muy_alterado"
  condicional:
    - id: s_dolor
      TARDIO:   dolor_nrs >= 5
      TEMPRANO: dolor_nrs >= 5  AND  n_base >= 1
```

```
n_base  = |{ s in base : evaluar(s) == VERDADERO }|
n_total = n_base + (1 si s_dolor == VERDADERO, si no 0)
```

### 5.2 Regla de agregación — ambos regímenes

```yaml
agregacion:
  TARDIO:
    n_total == 0  -> VERDE
    n_total >= 1  -> AMARILLO
  TEMPRANO:
    n_total <= 1  -> VERDE
    n_total >= 2  -> AMARILLO
```

`[INFERENCIA]` **La regla TEMPRANO es diseño nuevo, no hecho.** `politica_decision.docx` §3.3 solo
especifica la rama tardía; la rama temprana nunca existió como regla (el script de auditoría usó una
extensión propia, marcada `[EXTENSION]` en su código). Se declara como `[INFERENCIA]` de diseño.

**Costo medido de la regla sobre el dev set** (vector completo, sin evasión — cota superior):

| Régimen | verde→verde | verde→amarillo (**c₂**) | amarillo→verde (**c₁**) | amarillo→amarillo |
|---|---|---|---|---|
| TEMPRANO (n=80) | 61 | **4** | **0** | 15 |
| TARDÍO (n=80, no-rojos) | 51 | **7** | **0** | 10 |
| **Total** | 112 | **11** | **0** | 25 |

`[HECHO]` Comparación: la política literal de los `.docx` con la extensión temprana del auditor daba
**26 c₂** (19 en temprano + 7 en tardío, A9). Esta regla baja a **11 c₂** manteniendo **c₁ = 0** y
`recall_rojo = 1.000`. La mejora es enteramente de la rama temprana: la tardía se mantiene igual.

`[INFERENCIA]` **Por qué el umbral asimétrico (≥1 en tardío, ≥2 en temprano).** En tardío una sola señal
blanda ya es informativa: `[HECHO]` solo 7 de 58 verdes tardíos tienen alguna. En temprano las señales
blandas son ruido fisiológico: `[HECHO]` 23 de 65 verdes tempranos tienen al menos una. Exigir ≥1 en
temprano compraría 23 c₂ en vez de 4, sin ganar un solo amarillo (los 15 amarillos tempranos ya se capturan
con ≥2).

---

## 6. Resolución de los cuatro huecos de especificación

Los `.docx` dejan cuatro puntos no implementables. Cada resolución se declara aquí y es vinculante.

### H1 — «febrícula ≥ 37.5 **sostenida**» no es evaluable → se elimina «sostenida»

**El problema.** `politica_decision.docx` §3.3 (tabla de señales blandas, régimen temprano) dice «Preocupa
febrícula ≥ 37.5 **sostenida**». Una llamada es **un punto en el tiempo**. El vector del paciente no
contiene historia de temperatura, y el módulo de política es **puro y sin estado** (restricción exportada a
Fase 2). No hay ningún dato del que derivar persistencia.

**Resolución `[INFERENCIA]`: se elimina el calificativo «sostenida».** El predicado operativo es
`fiebre_c >= 37.5` medido en el momento de la llamada, sin más. Razones:

- Las tres vías de obtener persistencia están cerradas o son peores: (a) estado entre llamadas viola la
  pureza del módulo y no existe en Fase 2; (b) auto-reporte del paciente («¿desde cuándo?») es una señal
  distinta, no medida en el dataset, y `[HECHO]` no hay columna que la sostenga; (c) inferirla del
  arquetipo es *leakage*.
- Eliminarla es la dirección segura: `fiebre_c >= 37.5` puntual dispara **más** que «≥37.5 sostenida», y
  sobre-disparar una señal blanda cuesta c₂.

`[ESPECULACIÓN]` Si en una fase futura el agente recibe historia entre llamadas, la persistencia se puede
reinstaurar **como señal separada** (`s_fiebre_sostenida`), nunca como calificativo de la existente. No se
implementa en Fase 2.

### H2 — Contradicción eritema: se elimina la regla especial, gana el conteo

**El problema.** `politica_decision.docx` §3.3 dice a la vez «`eritema_leve` + otra señal → **amarillo**»
(tabla, régimen tardío) y «≥ 2 señales de preocupación → **indagar** antes de fijar clase» (texto de la
regla de agregación). Con eritema + otra señal se cumplen las dos y ordenan cosas distintas: una cierra en
amarillo, la otra prohíbe cerrar.

**Resolución `[INFERENCIA]`: se elimina la regla especial de eritema.** `eritema_leve` es **una señal blanda
más** (`s_eritema`), sin trato especial, y el conteo del §5.2 la gobierna. Razones:

- La regla especial es **redundante**: eritema + otra señal = `n_total >= 2`, que ya da AMARILLO por conteo
  en ambos regímenes. No añade cobertura, solo un caso especial que contradice.
- Se elimina la regla que es **caso especial**, no la que es **general**: un sistema con menos ramas es
  menos superficie de bug y de contradicción futura.

**Aclaración vinculante que acompaña a H2:** «≥2 señales → indagar» **no pertenece a la capa de agregación**.
La agregación es conteo puro y siempre produce una clase candidata (§5.2). Quién indaga y quién cierra lo
decide **exclusivamente** el criterio de suficiencia (§7) más la compuerta de Nivel 1.5. Mezclar ambas capas
fue la causa raíz de la contradicción. Con evidencia completa y `n_total >= 2` sin bandera pendiente, S3
cierra en AMARILLO — mismo resultado que la regla especial pretendía, sin el conflicto.

### H3 — «dolor ≥ 5 con otra señal» es autorreferencial → se reformula excluyendo dolor de la base

**El problema.** `politica_decision.docx` §3.3 (tabla, régimen temprano) dice que el dolor «preocupa solo si
≥ 5 **con otra señal**». Si `dolor` cuenta como señal solo cuando hay otra señal, y «otra señal» incluye a
`dolor`, el conteo depende de sí mismo. No hay punto fijo único y el predicado no es evaluable en un paso.

**Resolución `[INFERENCIA]`: `s_dolor` se excluye del conjunto base y se evalúa contra él.**

```
n_base  = |{ s_fiebre, s_eritema, s_apetito, s_sueno } que son VERDADERO|     # dolor NO participa
s_dolor(TEMPRANO) = (dolor_nrs >= 5) AND (n_base >= 1)                        # depende solo de n_base
n_total = n_base + (1 si s_dolor)
```

No hay autorreferencia: `n_base` no contiene a `s_dolor`, así que `s_dolor` es función de entradas ya
determinadas. Se evalúa en un paso, en orden fijo, y es determinista.

`[HECHO]` **Justificación del trato especial del dolor en temprano:** `dolor_nrs >= 5` en régimen temprano
aparece en 8 amarillos y **6 verdes** — es prácticamente una moneda al aire. En tardío, `dolor_nrs >= 5`
tiene **0 verdes** sobre 58. La misma cifra discrimina en tardío y no discrimina en temprano; por eso en
temprano solo cuenta acompañada. Es el mismo argumento fisiológico del §3.1: el dolor agudo de los días 1–3
es esperado.

### H4 — ACOPLAMIENTO: el eritema es todo el costo del corte en día 4

**El problema.** `[HECHO]` (D6/A10) Todo el costo medido de fijar el corte en el día 4 es c₂ y está
disparado **solo por `eritema_leve`**: los 6 verdes del día 3 y los 3 del día 1 que se sobre-clasificarían
tienen eritema y ninguna otra señal. H4 no se puede resolver sin resolver H2/H3 y viceversa: si el eritema
cuenta o no como señal suficiente decide el precio del enrutador.

**El desagregado que resuelve.** `[HECHO]` (verificado sobre los 160; el script imprime el agregado en A1 y
A10, el corte por régimen es desagregación directa del mismo join):

| `herida = eritema_leve` | n | verde | amarillo | rojo |
|---|---|---|---|---|
| **Global** | 39 | **11** | 19 | 9 |
| **TEMPRANO** | 21 | **10** | 11 | 0 |
| **TARDÍO** | 18 | **1** | 8 | 9 |

El eritema es **dos señales distintas según el régimen**. En tardío es fuertemente informativo: 1 verde
contra 17 no-verdes, y su costo como señal es un **c₂ sobre un único caso** — la celda más barata de la
matriz. En temprano es casi puro ruido: 10 verdes contra 11 amarillos, cerca de una moneda al aire. **Los
otros 10 de los 11 verdes con eritema están en temprano**, y por eso allí el eritema aislado no puede
bastar.

**Resolución `[INFERENCIA]`, coherente con H2 y H3:** `s_eritema` es una señal blanda **en ambos regímenes,
sin trato especial** (H2), y la asimetría se resuelve **enteramente en el umbral de conteo** (§5.2):

- En **TARDÍO**, `n_total >= 1` → AMARILLO: el eritema aislado **sí** basta. Cuesta 1 c₂ y captura 8 de los
  10 amarillos tardíos.
- En **TEMPRANO**, `n_total >= 2` → AMARILLO: el eritema aislado **no** basta. Evita 10 c₂ y no pierde
  ningún amarillo (los 15 amarillos tempranos tienen `n_total >= 2`).

**Consecuencia declarada sobre el corte del enrutador.** Con esta resolución, el precio del corte en el día
4 queda explícito y acotado: un verde de día 4–6 con eritema aislado y nada más se clasifica AMARILLO en
vez de VERDE. Es **exactamente un c₂ por caso, nunca un c₄** (`[HECHO]`, A10: cero casos pasan a ROJO al
mover el corte). Se acepta ese precio a cambio de no exponer los días 4–6 a la dirección c₃. Es una
decisión de matriz de costos, tomada con el desagregado a la vista, no un efecto colateral.

---

## 7. Criterio de suficiencia e indagación

La compuerta que separa un clasificador de un turno de un agente que indaga. Se evalúa **antes** de emitir
cualquier clase.

### 7.1 Criterio de suficiencia (basta uno)

```yaml
suficiencia:
  S1:  # bandera roja confirmada
    condicion: alguna bandera de Nivel 1 == VERDADERO
    emite: ROJO
    nota: no se indaga mas sobre criticidad

  S2:  # verde robusto
    condicion: >
      TODAS las senales del nucleo obtenidas (ninguna AUSENTE)
      AND ninguna senal blanda VERDADERA
      AND todas las banderas de Nivel 1 == FALSO
      AND compuerta Nivel 1.5 NO activa
    emite: VERDE

  S3:  # amarillo saturado
    condicion: >
      n_total suficiente para AMARILLO segun regimen (§5.2)
      AND ninguna bandera de Nivel 1 en DESCONOCIDO
      AND (compuerta 1.5 no activa  OR  todas las banderas de Nivel 1 == FALSO)
    emite: AMARILLO terminal
    nota: mas indagacion no cambiaria la decision de vigilar

  ninguno_se_cumple:
    accion: REPREGUNTAR
    condicion_de_accionabilidad: >
      existe al menos una senal del nucleo AUSENTE
      AND queda presupuesto (tope por senal y tope global, §7.2)
    si_no_es_accionable: CIERRE FORZADO (§7.4)
```

`[INFERENCIA]` **S2 se endurece respecto a `politica_decision.docx` §4.2** con dos cláusulas nuevas:
«todas las banderas en `FALSO`» (no `DESCONOCIDO`) y «compuerta 1.5 no activa». Sin la primera, S2 podía
emitir VERDE con una bandera sin descartar — el modo de fallo más caro del sistema. La segunda es el
punto 1 de §4.1.

**Casos que caen en REPREGUNTAR:** vector incompleto (falta ≥1 señal del núcleo, típico de capa 2);
señal borderline (fiebre 37.5–37.9, dolor en zona de cruce del régimen); contradicción entre señales
(numéricos normales con apetito/sueño muy alterados — los 8 ambiguos de Q4).

### 7.2 Topes de indagación

```yaml
topes:
  por_senal_profundidad:   2       # rango declarado 2-3
  global_llamada_amplitud: 6       # rango declarado 6-8
```

`[ESPECULACIÓN]` **Ambos valores son especulación pendiente de calibración en Fase 3.** No hay medición que
los sostenga. Se fijan en el extremo conservador de su rango declarado. Justificación del orden de
magnitud, no del valor exacto:

- El tope **global es el que muerde**: sin él, el peor caso es 6 señales × 3 repreguntas ≈ 18 turnos, que
  destruye la conducción (15 pts de voz) e infla el consumo de tokens del README.
- El 6 es coherente con `[HECHO]` los 6 turnos de paciente por caso observados en el dataset.
- Se calibran **midiendo sobre capa 2, no capa 1** — capa 1 es un problema más fácil que el real y daría
  topes optimistas.

### 7.3 Prioridad bajo presupuesto escaso

`[INFERENCIA]` Qué preguntas sobreviven cuando el presupuesto es el cuello de botella, en orden estricto:

1. **Señales adyacentes a una bandera de Nivel 1 en `DESCONOCIDO`** (¿la herida supura?, ¿la fiebre subió?,
   ¿puede moverse?). Colapsan `P(rojo|e)` hacia 0 o 1 — máxima reducción de incertidumbre sobre la frontera
   cara.
2. **Señales que resolverían la compuerta de Nivel 1.5** si está en `DESCONOCIDO`. Deciden si el caso puede
   cerrar en verde.
3. **Discriminadores verde↔amarillo** (apetito, sueño, eritema con banderas ya descartadas). Solo si sobra
   presupuesto: su error cuesta c₂ o c₁, no c₃.

### 7.4 Cierre forzado — cuando `REPREGUNTAR` no es accionable

`[INFERENCIA]` `REPREGUNTAR` es una **acción**, no una clase, y solo existe si hay una
señal `AUSENTE` que indagar y presupuesto para hacerlo. Cuando ninguna de las dos cosas
se cumple, el módulo **cierra**. Dos situaciones, y solo dos:

| Situación | Resolución |
|---|---|
| **Vector del núcleo completo** (ninguna señal `AUSENTE`) y ninguna S se cumple | Clase de §5.2, **filtrada** (abajo) |
| **Presupuesto agotado** con alguna señal `AUSENTE` | §8, escalamiento graduado |

**El filtro.** La clase candidata de §5.2 se somete a las prohibiciones ya declaradas,
en este orden:

1. Si alguna bandera de Nivel 1 está en `DESCONOCIDO` → no puede cerrar en AMARILLO ni
   en VERDE (§4.1 punto 2) → **ROJO**. *(Inalcanzable con vector completo; se implementa
   igual.)*
2. Si la compuerta de Nivel 1.5 está activa y la candidata es VERDE → **AMARILLO**
   (§4.1 punto 1).
3. En otro caso, la candidata es la clase terminal.

El filtro **prohíbe salidas, no fuerza clases** — es la misma semántica del §4.1,
aplicada al punto de cierre.

`[INFERENCIA]` **Por qué esto no viola el invariante duro de §8.1.** El invariante
prohíbe cerrar en VERDE con evidencia **insuficiente**. Aquí la evidencia está completa:
se obtuvieron todas las señales del núcleo y no queda pregunta que pudiera cambiar la
decisión. El invariante sigue mordiendo, sin excepción, en el caso «presupuesto agotado
con alguna señal `AUSENTE`».

`[INFERENCIA]` **Alternativa descartada:** promover esos casos a AMARILLO («nunca verde
con una señal blanda activa»). `[HECHO]` Cuesta 19 c₂ adicionales en régimen temprano
(4 → 23) y deshace en silencio la decisión de §5.2 de elegir el umbral ≥2 sobre ≥1, que
se tomó con esa misma comparación de costo a la vista (H4).

`[HECHO]` Sobre el dev set con vector completo, el cierre forzado se activa en **19 de
160 casos** (11.9 %), todos de régimen temprano con `n_total == 1` exactamente, y los 19
son verde real. La salida terminal reproduce `recall_rojo = 1.000`, `c₁ = 0`, `c₃ = 0`,
`c₂ = 11` (4 temprano + 7 tardío). Reproducible con `scripts/verificacion_hd1.py`.

`[INFERENCIA]` **Invariante de consistencia entre §4 y §5** (property test obligatorio):
en régimen tardío, compuerta 1.5 activa ⟹ `n_total ≥ 1`. Se deriva de que cada condición
de la compuerta implica una señal blanda: `g_fiebre (37.8) ≥ s_fiebre (37.5)`,
`g_dolor (5) = s_dolor tardío (5)`, `g_constitucional ⟹ s_apetito ∧ s_sueno`.
**Depende de los valores actuales, no de la estructura**: si el anclaje al corpus (deuda
RAG) mueve cualquiera de esos cuatro umbrales, la implicación puede romperse. El paso 2
del filtro mantiene la salida correcta aunque se rompa; el test existe para que la
ruptura sea visible en vez de silenciosa.

**Límite declarado.** `[INFERENCIA]` El modelo de valores de §1.1 no distingue «señal no
obtenida» de «señal obtenida y no confirmada», así que el cierre forzado no puede gastar
presupuesto en **verificar** la única señal blanda positiva de un caso temprano (p. ej.
repreguntar si la fiebre se midió con termómetro). Reintroducirlo exigiría un cuarto
estado por señal. Fuera de alcance de Fase 2; se registra como opción de Fase 3.

---

## 8. Escalamiento graduado al agotar presupuesto

`[INFERENCIA]` No todo agotamiento resuelve a ROJO — eso sobre-escalaría masivamente en capa 2, donde la
evasión es la norma. La graduación depende de **qué** quedó irresuelto:

| ¿Alguna bandera de Nivel 1 en `DESCONOCIDO`? | ¿Falta alguna señal del núcleo (§1.2)? | Resolución |
|---|---|---|
| **Sí** | — | **ROJO** |
| No | **Sí** | **AMARILLO** con `confianza = baja` y registro de escalamiento (nunca VERDE) |
| No | No | **No es agotamiento** → §7.4, caso «vector del núcleo completo» |

`[INFERENCIA]` **La tabla es una partición, y es exhaustiva por construcción.** Si ninguna bandera está en
`DESCONOCIDO`, entonces `herida`, `movilidad`, `fiebre_c` y `dolor_nrs` son conocidas, así que las únicas
señales del núcleo que pueden faltar son `apetito` y `sueno` — ambas discriminadores verde↔amarillo. La
premisa del caso «falta alguna señal del núcleo» no hay que verificarla: se cumple sola.

`[INFERENCIA]` **Dos filas eliminadas por redundancia, no por cambio de política:**
- «Compuerta 1.5 activa **y** alguna bandera en `DESCONOCIDO` → ROJO» está subsumida por el caso «alguna
  bandera de Nivel 1 en `DESCONOCIDO`»: la bandera en `DESCONOCIDO` ya basta.
- «`dolor_nrs ∈ {5,6}` sin resolver en tardío → ROJO» **no era expresable**: §1.1 declara
  `Valor(señal) ::= <dominio> | AUSENTE`, sin intervalos, así que «saber que está entre 5 y 6» no tiene
  representación. Si `dolor` está `AUSENTE` en tardío, `dolor_severo` queda en `DESCONOCIDO` y el caso
  «alguna bandera de Nivel 1 en `DESCONOCIDO`» ya resuelve ROJO — mismo resultado. Representar conocimiento parcial exigiría un valor de intervalo
  por señal, que se descarta para Fase 2 (emparentado con la deuda menor «no existe el estado señal obtenida
  sin confirmar»).

`[INFERENCIA]` **Riesgo que esta tabla concentra, y dónde se contiene.** El caso «alguna bandera de Nivel 1
en `DESCONOCIDO`» convierte cualquier señal de bandera sin resolver en ROJO: un paciente verde que evade la pregunta sobre la herida y agota el
presupuesto sale escalado — c₄, la celda del «agente alarmista», y el jurado prueba verdes. Lo único que
impide que esto sea un cañón de escalamientos es el orden de prioridad de §7.3, que manda indagar primero
las señales adyacentes a bandera. **§7.3 es por tanto portante de costo, no solo de seguridad**, y su orden
tiene que ser determinista y tener test propio cuando se fije el contrato del módulo (HD6).

### 8.1 Invariante duro (no se gradúa)

> **Nunca cerrar en VERDE con evidencia insuficiente.**

`[INFERENCIA]` Este invariante no admite excepción, tope de presupuesto ni graduación. Operativamente: si
alguna señal del núcleo es `AUSENTE` al agotar el presupuesto, S2 es inalcanzable por construcción (§7.1) y
la clase mínima emitible es AMARILLO. Es el criterio 4 del protocolo de aprobación y se verifica en el 100 %
de las corridas, sin tolerancia.

### 8.2 Errores de invocación (falla ruidoso)

`[INFERENCIA]` El módulo lanza excepción —no clasifica— ante: `dia_postop` negativo o no entero (§2.1);
`dolor_nrs` fuera de 0–10 o no entero; valor categórico fuera del dominio declarado (§1); `fiebre_c` no
numérico. Estas son entradas imposibles de un llamador correcto. Devolver una clase enmascararía el bug en
producción, que es peor que caerse en validación.

**Ausencia no es error.** `AUSENTE` es un valor legítimo de toda señal (§1.1) y se maneja por la vía de la
lógica trivaluada, nunca por excepción. La única señal cuya ausencia tiene tratamiento propio es
`dia_postop` (§2.1: TARDÍO + marca de incertidumbre).

---

## 9. Matriz de costos

```
C(d, y),  d = clase predicha,  y = clase real
```

|  | real = **verde** | real = **amarillo** | real = **rojo** |
|---|---|---|---|
| **pred = verde** | 0 | **c₁** | **C_FN** |
| **pred = amarillo** | **c₂** | 0 | **c₃** |
| **pred = rojo** | **c₄** | **c₅** | 0 |

**Cada subíndice, definido por su celda:**

| Símbolo | Celda (predicho, real) | Qué significa clínicamente |
|---|---|---|
| `C_FN` | (verde, rojo) | Complicación real cerrada como normal. Catastrófico. Anula los 20 pts de decisión. |
| `c₃` | (amarillo, rojo) | Complicación real cerrada en vigilancia. **Amarillo no llega a un humano** — funcionalmente es un falso negativo de escalamiento. |
| `c₁` | (verde, amarillo) | Paciente que necesitaba vigilancia queda sin ninguna. |
| `c₄` | (rojo, verde) | Verde escalado a humano. Distancia 2. Lee como agente alarmista, y el jurado prueba verdes. |
| `c₅` | (rojo, amarillo) | Amarillo sobre-escalado. Cuesta una revisión humana innecesaria. |
| `c₂` | (amarillo, verde) | Verde puesto en vigilancia. **La celda más barata.** |

**Orden vigente:**

```
C_FN  ≫  c₃  ≫  c₁  >  c₄  >  c₅  >  c₂
```

`[INFERENCIA]` Justificación de cada relación:

- `C_FN ≫ c₃`: ambas son falsos negativos de escalamiento, pero (verde, rojo) además tranquiliza al
  paciente activamente.
- `c₃ ≫ c₁`: la columna `real = rojo` tiene **dos** celdas catastróficas, no una. Amarillo es
  vigilancia/seguimiento, no escalamiento a humano.
- `c₁ > c₅`: perder un amarillo deja al paciente sin vigilancia; sobre-escalarlo solo cuesta una revisión.
  Dirección FN > FP, coherente con todo el diseño.
- `c₄ > c₂`: distancia 2 > distancia 1. `c₄` no es despreciable: escalar verdes lee como agente alarmista.
- `c₅ > c₂`: sobre-escalar a rojo cuesta tiempo humano; poner un verde en vigilancia solo cuesta un
  seguimiento.

`[ESPECULACIÓN]` **`C_FN` no se calibra numéricamente** — no hay base para un valor exacto. Se
operacionaliza con tres mecanismos discretos: (a) el piso de banderas rojas (§3), que es `P(rojo|e) = 1`
efectivo; (b) la compuerta de no-verde (§4), que prohíbe la salida barata bajo evidencia parcial; (c) la
compuerta de indagación (§7), que ante `P(rojo|e)` intermedia no clasifica sino que pregunta.

`[INFERENCIA]` **Consecuencia formal.** Con dos celdas ≈ `C_FN` en la columna `real = rojo`, la decisión
bayesiana `d*(e) = argmin_d Σ_y C(d,y)·P(y|e)` deja el umbral de `P(rojo|e)` para **no** escalar en casi
cero. En la frontera amarillo↔rojo, la duda resuelve a ROJO siempre. La sensibilidad sobre rojo **cae de la
matriz, no se impone** por decreto.

---

## 10. Trazabilidad de cada parámetro

| Parámetro | Valor | Origen | Evidencia |
|---|---|---|---|
| Corte del enrutador | día 4 | `[INFERENCIA]` **ancla externa al dataset**: ventana de presentación de la ISQ, más matriz de costos para elegir la dirección del error. No decidible por datos — el dev set no tiene días 4–6 | D6 / A10 |
| Fiebre franca | ≥ 38.0 °C | `[INFERENCIA]` **ancla externa al dataset**: umbral febril clínico estándar, fijado antes de mirar los datos. El valor **no se barrió sobre la muestra** — es lo que lo distingue de las tres compuertas de abajo, y el argumento más fuerte a su favor | 0 verdes **y** 0 amarillos con ≥ 38.0 en toda la muestra (11 casos, los 11 rojos, 6 pacientes) · A3 / A7 |
| Dolor severo tardío | ≥ 7 | `[INFERENCIA]` **ancla externa al dataset**: partición NRS estándar, tercil severo 7–10. El valor tampoco se barrió sobre la muestra | D3 / A3 / A4 |
| Purulenta / incapacitante | presencia | `[INFERENCIA]` **promoverlas a Nivel 1 es decisión de diseño**: se conservan por defendibilidad (presencia/ausencia, sin frontera numérica que discutir), **no por cobertura** — D2 mostró que no aportan ninguna | pureza n=3 y n=4; **n efectivo = 3 y 4 pacientes** (sin repetición intra-bandera). Ninguna captura un rojo que la fiebre no capture ya: los 7 casos tienen fiebre ≥ 38.0 (38.1/38.0/38.4 y 38.2/38.0/38.1/38.0) · A1 / A3 |
| Compuerta `g_fiebre` | ≥ 37.8 °C | `[INFERENCIA]` **primer umbral con cero verdes tardíos en el barrido de A7** (37.7 deja 1, 37.8 deja 0) — selección sobre el dev set, declarada | 0/58 verdes tardíos · A7 |
| Compuerta `g_dolor` | ≥ 5 | `[INFERENCIA]` **primer entero por encima de `verde_max` tardío = 4** — selección sobre el dev set, declarada | 0/58 verdes tardíos · A7 / A9 |
| Compuerta `g_constitucional` | conjunción | `[INFERENCIA]` **forma mínima con cero verdes entre las combinaciones de las dos señales**: cada parte por separado deja 5 y 4 verdes, disjuntos (D1) — selección sobre el dev set, declarada | 0/58 verdes tardíos · A8 / A2 |
| Señal blanda fiebre | ≥ 37.5 °C | `[INFERENCIA]` febrícula, sin «sostenida» (H1) | §6 H1 |
| Señal blanda dolor | ≥ 5 (cond. en temprano) | `[INFERENCIA]` H3 reformuló el **predicado** (no autorreferencial); el **valor** es el mismo de `g_dolor` y sale del mismo hecho: primer entero por encima de `verde_max` tardío = 4 — selección sobre el dev set, declarada | 0/58 verdes tardíos con dolor ≥ 5; en temprano se condiciona porque ahí hay 6 verdes con ≥ 5 · §6 H3 / A7 |
| Umbral de conteo TARDÍO | ≥ 1 | `[INFERENCIA]` **mínimo posible del conteo**; se adopta porque en tardío la señal blanda aislada ya discrimina y el error que compra es c₂, la celda más barata — selección sobre el dev set, declarada | 7/58 verdes tardíos con ≥1 señal; captura 10/10 amarillos tardíos · §5.2 |
| Umbral de conteo TEMPRANO | ≥ 2 | `[INFERENCIA]` **regla nueva, no existía en los `.docx`**; ≥2 se elige por comparación de costo contra ≥1 sobre la muestra — selección sobre el dev set, declarada | 4 c₂ con ≥2 vs 23 c₂ con ≥1, ambos con c₁ = 0 y los 15 amarillos tempranos capturados · §5.2 / H4 |
| Tope por señal | 2 | `[ESPECULACIÓN]` pendiente Fase 3 | §7.2 |
| Tope global | 6 | `[ESPECULACIÓN]` pendiente Fase 3 | §7.2 |
| Ventana del corpus | 30 días | `[ESPECULACIÓN]` pendiente RAG | §2.1 |
| Anclas RAG (×4) | PENDIENTE | deuda **bloqueante** | Enmienda, §Deuda |

### Nota al pie de §10 — el `[HECHO]` de la columna «Evidencia» no propaga a la columna «Origen»

`[INFERENCIA]` Las dos columnas responden a preguntas distintas y **no comparten etiqueta**:

- **Evidencia** = qué se midió sobre el dev set. Ahí sí hay `[HECHO]`: «0/58 verdes tardíos» es una
  observación reproducible con `scripts/auditoria_fase1.py`.
- **Origen** = por qué el parámetro vale lo que vale. Eso es siempre una **elección de diseño**, aunque esté
  anclada en un hecho. Que `fiebre_c ≥ 37.8` deje 0/58 verdes es un hecho; **elegir 37.8 como el valor de la
  compuerta es una inferencia** — otro diseñador podría elegir 37.7 aceptando 1 verde, o 38.0 alineándolo
  con la bandera. El dato acota el espacio de opciones; no selecciona el punto.

Por eso **ninguna fila de «Origen» lleva `[HECHO]`** —no queda una sola en la tabla— y por eso cada
parámetro elegido sobre el dev set declara **su procedimiento de selección**, no solo su respaldo. La
etiqueta correcta del Origen depende de qué fija el valor: `[INFERENCIA]` si lo fija un razonamiento
(clínico, de costos o de selección sobre datos), `[ESPECULACIÓN]` si no lo fija nada medido todavía.

`[INFERENCIA]` **Dentro de `[INFERENCIA]` hay dos familias, y la distinción es la que importa para
transferibilidad:**

| Familia | Parámetros | Riesgo de sobreajuste al dev set |
|---|---|---|
| **Ancla externa al dataset** — el valor viene de una definición clínica o de una escala estándar, fijada antes de mirar los datos; la muestra solo lo confirma | `fiebre_franca ≥ 38.0`, `dolor_severo ≥ 7`, corte del enrutador en día 4 | **Bajo.** Un contraejemplo en la muestra refutaría el parámetro, pero su ausencia no es lo que lo sostiene |
| **Selección sobre el dev set** — el valor se eligió barriendo la muestra hasta encontrar el punto que optimiza un criterio | `g_fiebre ≥ 37.8`, `g_dolor ≥ 5`, `g_constitucional`, señal blanda `dolor ≥ 5`, conteo TARDÍO ≥ 1, conteo TEMPRANO ≥ 2 | **Alto.** El valor **es** el resultado del barrido: no hay evidencia independiente de la que lo produjo |

Esta es la única distinción de la tabla que sobrevive al cambio de muestra. **De las filas etiquetadas
`[INFERENCIA]`, dos no llevan familia** (las `[ESPECULACIÓN]` y la fila de anclas RAG quedan fuera de esta
taxonomía por construcción: no hay valor fijado que clasificar). Las dos son:

- **`Purulenta / incapacitante`** es decisión de diseño pura: no tiene valor numérico que ajustar, y su
  justificación es de defendibilidad ante el jurado, no de cobertura medida.
- **`Señal blanda fiebre ≥ 37.5`** sí tiene umbral, pero **lo hereda de los `.docx` originales sin haber
  sido reexaminado en esta auditoría**: H1 corrigió su *predicado* —quitar «sostenida»— **no su valor**.
  `[ESPECULACIÓN]` declarada: es plausible que 37.5 sea ancla externa (febrícula convencional), pero no se
  verificó. **Deuda menor, abierta:** clasificarlo antes de cerrar Fase 2.

`[INFERENCIA]` **`dolor ≥ 5` aparece dos veces con el mismo valor y el mismo origen** — como `g_dolor`
(compuerta) y como señal blanda tardía. Ambas filas se clasifican igual: *selección sobre el dev set*,
`verde_max` tardío + 1. Se dejan como dos filas porque son dos parámetros con semántica distinta (una
prohíbe cerrar en verde, la otra cuenta para el agregado) y podrían divergir si el corpus fija uno de los
dos. **Deuda abierta (fase RAG):** al resolver el anclaje, ambas convergen o se justifica por qué difieren.
Hoy **no deben editarse por separado**: cambiar una sin la otra es un bug silencioso.

**Marcadores literales en la columna «Origen»** (para que un `grep` sobre esta tabla no se equivoque):
`ancla externa al dataset` y `selección sobre el dev set, declarada`. Son mutuamente excluyentes y ninguna
fila lleva las dos. Las negaciones se redactan como «el valor no se barrió sobre la muestra» y **nunca**
negando el marcador positivo, para que buscar la cadena `selección sobre el dev set, declarada` devuelva
exactamente las seis filas ajustadas a la muestra y ninguna más.

`[INFERENCIA]` **Consecuencia de honestidad, no cosmética.** Los **seis** parámetros marcados «selección
sobre el dev set, declarada» comparten un riesgo que la etiqueta `[HECHO]` ocultaba: **están ajustados a los
160 casos**. Para los cinco de régimen tardío, su cero-verdes no es una garantía transferible: es la
ausencia de contraejemplo en una muestra de 58 verdes tardíos con **n efectivo de 34 pacientes** (los 58
casos son 34 pacientes distintos; 39 es el conteo de pacientes verdes en toda la muestra, no en régimen
tardío). Para el conteo TEMPRANO, la base es 65 verdes tempranos y el criterio no es cero-verdes sino
mínimo costo c₂, lo que lo hace igual de ajustado aunque por otra métrica. Es exactamente el error de
lectura que la auditoría encontró cinco veces (`enmienda_auditoria_fase1.md`, «Patrón de fondo»), y el
correctivo permanente —toda afirmación de pureza declara su n y su n efectivo— aplica a esta tabla como a
cualquier otra.
