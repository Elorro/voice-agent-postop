# Bloqueos y defectos de spec detectados al implementar 2.1

**Fecha:** 2026-08-09 · **Estado:** los tres **resueltos** el mismo día · **Autor:** ejecutor (Claude Code)

> **Resolución del arquitecto (2026-08-09).** Los tres hallazgos se confirmaron correctos.
> **O3** se resuelve con un cambio de política —`dolor_severo` pasa a umbral por régimen,
> 7 tardío / 9 temprano (`parametros_politica.md` §3 y §3.1)—, que **cierra O1 en su raíz**
> como efecto colateral buscado. **O2** era errata del contrato de 2.1. El registro de la
> decisión, con sus alternativas descartadas, está en `docs/bitacora.md` (2026-08-09).
> Este archivo se conserva como el **diagnóstico** que la produjo; su texto original no se
> reescribe, solo se le añade la resolución de cada ítem.

> **No hubo bloqueo.** Ninguna de las tres observaciones de abajo impidió implementar,
> ninguna exigió decidir un parámetro por cuenta propia y **no queda ningún
> `TODO(BLOQUEO)` en el código**. Se registran aquí porque son defectos de
> `parametros_politica.md` que conviene corregir en el documento, no en el módulo.
> Las tres son de redacción o de justificación: **ninguna cambia una salida**.

---

## O1 — §8: la premisa de la partición **no** «se cumple sola» en régimen temprano

**Qué dice la spec.** §8, párrafo posterior a la tabla:

> «La tabla es una partición, y es exhaustiva por construcción. Si ninguna bandera está
> en `DESCONOCIDO`, entonces `herida`, `movilidad`, `fiebre_c` y `dolor_nrs` son
> conocidas, así que las únicas señales del núcleo que pueden faltar son `apetito` y
> `sueno` […]. La premisa del caso «falta alguna señal del núcleo» no hay que
> verificarla: se cumple sola.»

**Por qué es falso.** La bandera `dolor_severo` es `dolor_nrs >= 7 AND regimen == TARDIO`
(§3). En régimen **temprano** la conjunción de Kleene fuerte da `D ∧ F = F` (§1.1): la
bandera queda **descartada**, no pendiente, aunque `dolor_nrs` esté `AUSENTE`. Luego
«ninguna bandera en `DESCONOCIDO`» **no** implica que `dolor_nrs` sea conocida.

Verificado sobre el módulo:

```python
decidir(Observacion(1, None, 36.6, "normal", "normal", "normal", "normal"),
        Presupuesto({s: 2 for s in NUCLEO}, 6))
# banderas: las cuatro en FALSO  ·  clase: AMARILLO  ·  criterio: AGOTAMIENTO
```

**Qué se implementó.** La tabla de §8 **tal como está escrita**: la premisa «falta alguna
señal del núcleo» se **verifica**, no se asume. La partición sigue siendo exhaustiva y la
resolución del caso es la misma (AMARILLO, `confianza = baja`), así que el defecto es de
la *justificación*, no de la regla. Si se hubiera implementado la justificación en vez de
la tabla —dando por supuesto que solo `apetito` y `sueno` pueden faltar— un caso temprano
con `dolor_nrs` ausente habría caído en el ramal equivocado (§7.4, «vector completo»)
y podría cerrar en VERDE, violando §8.1.

**Corrección sugerida al documento:** sustituir «no hay que verificarla: se cumple sola»
por la enumeración correcta —en tardío pueden faltar `apetito` y `sueno`; en temprano,
además, `dolor_nrs`— y dejar dicho que la premisa **se verifica**.

> **RESUELTO (2026-08-09) — en la raíz, no con la corrección sugerida.** La tabla de §8 era
> correcta; lo falso era su justificación. Con el umbral de dolor indexado por régimen (O3),
> el dolor `AUSENTE` deja la bandera en `DESCONOCIDO` en **ambos** regímenes, así que la
> premisa vuelve a ser verdadera y **§8 no se tocó**. El módulo sigue **verificando** la
> premisa en vez de asumirla: es correcta hoy por §3, pero no depende de §3 — si un predicado
> futuro reintroduce un colapso `D ∧ F = F`, ese ramal sigue eligiendo bien sin que nadie
> tenga que acordarse. Anotado como verificación defensiva en el docstring de `decidir`.

---

## O2 — HD6 nivel 3: la referencia de sección no coincide con la lista

**Qué dice el contrato de 2.1.** «3. Discriminadores verde↔amarillo restantes, en orden de
la tabla de §1: `fiebre_c`, `herida`, `apetito`, `sueno`, `dolor_nrs`».

**La discrepancia.** El orden de la tabla de §1 es `dia_postop, dolor_nrs, fiebre_c,
herida, movilidad, apetito, sueno`. La lista dada es el orden de **§5.1** (base
`s_fiebre, s_eritema, s_apetito, s_sueno` más `s_dolor` al final), que es además el
orden con sentido: son discriminadores verde↔amarillo, o sea señales blandas.

**Qué se implementó.** La **lista literal**, que es lo normativo («orden total adoptado»).
La referencia «§1» se lee como errata por «§5.1».

> **RESUELTO (2026-08-09).** El arquitecto confirma la errata: debía decir **§5.1**. La
> referencia quedó corregida en el docstring de `ORDEN_DISCRIMINADORES` (`politica/motor.py`),
> que es el único sitio del repo donde se citaba. Sin efecto sobre el comportamiento.

---

## O3 — Consecuencia declarable: dolor 9 aislado en régimen temprano cierra en VERDE por S2

**No es un defecto de coherencia**: sale de aplicar §3 (la bandera de dolor es
`SOLO_TARDIO`, §3.1) y H3 (`s_dolor` en temprano exige `n_base >= 1`) al mismo caso.

```python
decidir(Observacion(1, 9, 36.6, "normal", "normal", "normal", "normal"))
# clase: VERDE  ·  criterio: S2  ·  n_total: 0
```

Un paciente de día 1 que reporta NRS 9 y nada más cierra en **VERDE robusto**, sin
indagar. El oráculo `scripts/verificacion_hd1.py` da exactamente lo mismo, y el dev set
no lo detecta porque `dolor_nrs = 9` solo aparece en casos tardíos.

**Por qué se registra.** La justificación de §3.1 —«el dolor agudo de los días 1–3 es
fisiología esperada; los verdes tempranos llegan legítimamente a `dolor_nrs = 6`»— está
medida hasta 6, `[HECHO]`, y **no dice nada sobre 7–10 en temprano**, porque esos valores
no existen en la muestra (D3: el dominio observado es {0..6, 9}). La política extiende a
`{7,8,9,10}` un permiso que solo se verificó en `{0..6}`. Es un blanco directo en la
sustentación: «¿su agente le dice a un paciente con dolor 9 al día siguiente de operarse
que todo está normal?».

**Qué se implementó.** La spec, sin desviación. No se tocó ningún umbral.

**Opciones para el arquitecto** (decisión de política, no de implementación):

1. Dejarlo, y declararlo explícitamente en §3.1 como consecuencia aceptada.
2. Hacer que `s_dolor` en temprano cuente sin acompañamiento a partir de un umbral
   severo (p. ej. `dolor_nrs >= UMBRAL_DOLOR_SEVERO`), lo que llevaría el caso a
   `n_total = 1` y, con el umbral temprano en ≥2, a CIERRE_FORZADO en VERDE igual:
   no cambia nada sin tocar también §5.2.
3. Extender la bandera `dolor_severo` a ambos regímenes. Rompe la asimetría declarada
   en §3.1 y compra c₂/c₄ no medidos: **no** es la opción conservadora barata.

Ninguna es implementable hoy sin un parámetro nuevo en `parametros_politica.md`, que es
justamente lo que la regla 2 de §0 prohíbe decidir desde el código.

> **RESUELTO (2026-08-09) — decisión del arquitecto: umbral por régimen.** Ninguna de las
> tres opciones tal cual: `dolor_severo` deja de ser `SOLO_TARDIO` y pasa a
> `dolor_nrs >= umbral[régimen]` con **7 en tardío y 9 en temprano** (§3, §3.1, §10).
>
> - La opción 2 se descartó por la razón que este archivo ya anticipaba: no basta, seguiría
>   cerrando VERDE por cierre forzado sin tocar también §5.2.
> - Argumento decisivo: **dejar la banda sin cubrir no era la opción neutra**. El permiso a
>   `{7,8,9,10}` en temprano era una decisión activa tomada con cero observaciones, solo que
>   invisible; bajo §9 la dirección segura con cero evidencia es escalar.
> - El `9` es `[ESPECULACIÓN]` declarada y entra a la deuda de anclaje al corpus como ítem
>   propio. Costo en runtime aceptado: el paciente temprano que no informa su dolor y agota
>   el presupuesto pasa de AMARILLO a ROJO.
> - **Los números del criterio de aceptación no se movieron** (la banda no tiene
>   observaciones): la salida re-versionada del oráculo difiere de la anterior solo en la
>   línea de fecha.
>
> Detalle completo, con alternativas descartadas y costo declarado, en `docs/bitacora.md`
> (2026-08-09).
