"""Motor de la política: `decidir()` y sus niveles.

Módulo PURO: sin estado, sin I/O, sin dependencias de voz ni de RAG, sin pandas.
Determinista. El validador y el agente de producción importan exactamente este
módulo; si divergen, se valida una cosa y se entrega otra.

Toda referencia `§x` apunta a `docs/diseno/parametros_politica.md`, y toda `HD#`
al contrato fijado en la bitácora / prompt de Fase 2.1.
"""

from __future__ import annotations

import math
from typing import Mapping

from . import kleene
from .kleene import D, F, V
from .parametros import (
    APETITO_MUY_DISMINUIDO,
    CORTE_ENRUTADOR,
    DIA_POSTOP_MINIMO,
    DOLOR_NRS_MAXIMO,
    DOLOR_NRS_MINIMO,
    DOMINIOS_CATEGORICOS,
    HERIDA_ERITEMA_LEVE,
    HERIDA_SECRECION_PURULENTA,
    MOVILIDAD_INCAPACITANTE_NUEVA,
    SUENO_MUY_ALTERADO,
    TOPE_GLOBAL,
    TOPE_POR_SENAL,
    UMBRAL_CONTEO_AMARILLO,
    UMBRAL_DOLOR_SEVERO,
    UMBRAL_FIEBRE_FRANCA,
    UMBRAL_G_DOLOR,
    UMBRAL_G_FIEBRE,
    UMBRAL_S_DOLOR,
    UMBRAL_S_FIEBRE,
    VENTANA_CORPUS_DIAS,
)
from .tipos import (
    Accion,
    Clase,
    Criterio,
    Decision,
    ErrorDeInvocacion,
    Observacion,
    Presupuesto,
    Regimen,
    Trivalor,
)

__all__ = ["decidir", "NUCLEO", "PRESUPUESTO_VACIO"]

# --------------------------------------------------------------------------- #
# Qué señal lee cada regla. De aquí se DERIVA el núcleo (§1.2): «el núcleo es el
# conjunto de señales que aparecen en algún predicado de §3, §4 o §5». No se
# enumera en ningún sitio; si mañana una regla cambia de señales, el núcleo se
# ajusta solo y no queda un segundo lugar donde vive un parámetro.
# --------------------------------------------------------------------------- #
SENALES_NIVEL_1: Mapping[str, tuple[str, ...]] = {
    "purulenta": ("herida",),
    "movilidad_incapacitante": ("movilidad",),
    "fiebre_franca": ("fiebre_c",),
    "dolor_severo": ("dolor_nrs",),
}

SENALES_NIVEL_1_5: Mapping[str, tuple[str, ...]] = {
    "g_fiebre": ("fiebre_c",),
    "g_dolor": ("dolor_nrs",),
    "g_constitucional": ("apetito", "sueno"),
}

SENALES_NIVEL_2: Mapping[str, tuple[str, ...]] = {
    "s_fiebre": ("fiebre_c",),
    "s_eritema": ("herida",),
    "s_apetito": ("apetito",),
    "s_sueno": ("sueno",),
    "s_dolor": ("dolor_nrs",),
}


def _derivar_nucleo() -> tuple[str, ...]:
    """§1.2 — unión de las señales de §3, §4 y §5, sin repetir, en orden de aparición."""
    nucleo: list[str] = []
    for reglas in (SENALES_NIVEL_1, SENALES_NIVEL_1_5, SENALES_NIVEL_2):
        for senales in reglas.values():
            for senal in senales:
                if senal not in nucleo:
                    nucleo.append(senal)
    return tuple(nucleo)


NUCLEO: tuple[str, ...] = _derivar_nucleo()
"""§1.2. Las seis señales indagables. `dia_postop` NO está: no es indagable."""

# Adyacencia señal -> banderas de Nivel 1 que esa señal resolvería (HD6, nivel 1).
BANDERAS_POR_SENAL: Mapping[str, tuple[str, ...]] = {
    senal: tuple(b for b, ss in SENALES_NIVEL_1.items() if senal in ss) for senal in NUCLEO
}

# --------------------------------------------------------------------------- #
# HD6 — orden total de indagación. §7.3 da tres niveles de prioridad pero no
# ordena dentro de cada uno; el orden adoptado es el de declaración en la spec,
# filtrado por nivel. Decidido en el contrato de 2.1: no se reabre aquí.
# --------------------------------------------------------------------------- #
ORDEN_ADYACENTES_A_BANDERA: tuple[str, ...] = ("herida", "movilidad", "fiebre_c", "dolor_nrs")
"""Nivel 1 de §7.3, en orden de declaración de las banderas en §3."""

ORDEN_COMPUERTA: tuple[str, ...] = ("apetito", "sueno")
"""Nivel 2 de §7.3, en orden de declaración de las condiciones en §4."""

ORDEN_DISCRIMINADORES: tuple[str, ...] = ("fiebre_c", "herida", "apetito", "sueno", "dolor_nrs")
"""Nivel 3 de §7.3, en orden de declaración de las señales blandas en **§5.1**.

El contrato de 2.1 citaba «la tabla de §1»; el arquitecto confirmó que es errata por
§5.1 (BLOQUEO_2_1.md O2). La lista literal era y sigue siendo lo normativo: son
discriminadores verde↔amarillo, o sea señales blandas, y §5.1 es donde se declaran.
"""

PRESUPUESTO_VACIO = Presupuesto({}, 0)
"""Presupuesto inicial: ninguna repregunta gastada. Inmutable (ver `Presupuesto`)."""

# Marcas que viajan al registro de escalamiento de la capa de arriba.
MARCA_DIA_DESCONOCIDO = "dia_postop_desconocido"
MARCA_FUERA_DE_ALCANCE = "fuera_de_alcance"
MARCA_CONFIANZA_BAJA = "confianza_baja"


# --------------------------------------------------------------------------- #
# §8.2 — Errores de invocación. Falla ruidoso, no clasifica.
# --------------------------------------------------------------------------- #
def _validar_observacion(obs: Observacion) -> None:
    """§8.2. Ausencia (`None`) NO es error: es un valor legítimo de toda señal (§1.1)."""
    dia = obs.dia_postop
    if dia is not None:
        # bool es subclase de int: `True` como día es un bug del llamador, no un día 1.
        if isinstance(dia, bool) or not isinstance(dia, int):
            raise ErrorDeInvocacion(f"dia_postop no entero: {dia!r} (§2.1)")
        if dia < DIA_POSTOP_MINIMO:
            raise ErrorDeInvocacion(f"dia_postop negativo: {dia!r} (§2.1)")

    dolor = obs.dolor_nrs
    if dolor is not None:
        if isinstance(dolor, bool) or not isinstance(dolor, int):
            raise ErrorDeInvocacion(f"dolor_nrs no entero: {dolor!r} (§8.2)")
        if not DOLOR_NRS_MINIMO <= dolor <= DOLOR_NRS_MAXIMO:
            raise ErrorDeInvocacion(
                f"dolor_nrs fuera de {DOLOR_NRS_MINIMO}-{DOLOR_NRS_MAXIMO}: {dolor!r} (§8.2)"
            )

    fiebre = obs.fiebre_c
    if fiebre is not None:
        if isinstance(fiebre, bool) or not isinstance(fiebre, (int, float)):
            raise ErrorDeInvocacion(f"fiebre_c no numérico: {fiebre!r} (§8.2)")
        if not math.isfinite(fiebre):
            # NaN es un float que hace FALSO todo predicado de comparación: dejarlo
            # pasar convertiría silenciosamente «no sé» en «no tiene fiebre», que es
            # el colapso que §1.1 prohíbe. NaN/inf entran por §8.2, no por §1.1.
            raise ErrorDeInvocacion(f"fiebre_c no numérico: {fiebre!r} (§8.2)")

    for campo, dominio in DOMINIOS_CATEGORICOS.items():
        valor = getattr(obs, campo)
        if valor is not None and valor not in dominio:
            raise ErrorDeInvocacion(f"{campo} fuera del dominio declarado: {valor!r} (§1, §8.2)")


def _validar_presupuesto(presupuesto: Presupuesto, tope_por_senal: int, tope_global: int) -> None:
    """Extensión de §8.2 a la contabilidad de HD7: un presupuesto imposible es un bug.

    [INFERENCIA] La spec no tipifica estos casos porque §8.2 se escribió sobre el
    vector clínico. Se aplica el mismo criterio: una clave que no es señal del
    núcleo o un conteo negativo solo puede venir de un llamador roto, y tragarlo
    silenciaría un error de contabilidad que decide cuándo se deja de indagar.
    """
    if isinstance(presupuesto.preguntas_totales, bool) or not isinstance(
        presupuesto.preguntas_totales, int
    ):
        raise ErrorDeInvocacion(f"preguntas_totales no entero: {presupuesto.preguntas_totales!r}")
    if presupuesto.preguntas_totales < 0:
        raise ErrorDeInvocacion(f"preguntas_totales negativo: {presupuesto.preguntas_totales!r}")
    for senal, gastadas in presupuesto.preguntas_por_senal.items():
        if senal not in NUCLEO:
            raise ErrorDeInvocacion(f"señal fuera del núcleo en el presupuesto: {senal!r} (§1.2)")
        if isinstance(gastadas, bool) or not isinstance(gastadas, int) or gastadas < 0:
            raise ErrorDeInvocacion(f"repreguntas gastadas inválidas en {senal!r}: {gastadas!r}")
    if tope_por_senal < 0 or tope_global < 0:
        raise ErrorDeInvocacion(f"topes negativos: por_senal={tope_por_senal}, global={tope_global}")


# --------------------------------------------------------------------------- #
# §2 — Nivel 0, enrutador temporal
# --------------------------------------------------------------------------- #
def nivel_0(dia_postop: int | None) -> tuple[Regimen, tuple[str, ...]]:
    """§2.1. Deriva el régimen antes de aplicar cualquier umbral, y sus marcas.

    Los seis casos de borde de §2.1: día 0 -> TEMPRANO; 1-3 -> TEMPRANO;
    4-30 -> TARDÍO; ausente -> TARDÍO + marca; negativo o no entero -> excepción
    (ya lanzada en la validación); > 30 -> TARDÍO + `fuera_de_alcance`.
    """
    if dia_postop is None:
        return Regimen.TARDIO, (MARCA_DIA_DESCONOCIDO,)
    if dia_postop > VENTANA_CORPUS_DIAS:
        return Regimen.TARDIO, (MARCA_FUERA_DE_ALCANCE,)
    if dia_postop >= CORTE_ENRUTADOR:
        return Regimen.TARDIO, ()
    return Regimen.TEMPRANO, ()


# --------------------------------------------------------------------------- #
# §3 — Nivel 1, banderas rojas. Precedencia absoluta.
# --------------------------------------------------------------------------- #
def nivel_1(obs: Observacion, regimen: Regimen) -> dict[str, Trivalor]:
    """§3. Cuatro banderas en trivaluado. `DESCONOCIDO` queda pendiente (§7.1, §8)."""
    umbral_dolor = UMBRAL_DOLOR_SEVERO[regimen]
    return {
        "purulenta": kleene.evaluar(obs.herida, lambda h: h == HERIDA_SECRECION_PURULENTA),
        "movilidad_incapacitante": kleene.evaluar(
            obs.movilidad, lambda m: m == MOVILIDAD_INCAPACITANTE_NUEVA
        ),
        "fiebre_franca": kleene.evaluar(obs.fiebre_c, lambda t: t >= UMBRAL_FIEBRE_FRANCA),
        # §3.1: la asimetría del dolor se expresa como umbral INDEXADO por régimen
        # (7 tardío / 9 temprano), no como conjunción con el régimen. Consecuencia
        # deliberada: con el dolor AUSENTE la bandera queda en DESCONOCIDO en AMBOS
        # regímenes, en vez de colapsar a FALSO por `D ∧ F = F`.
        "dolor_severo": kleene.evaluar(obs.dolor_nrs, lambda p: p >= umbral_dolor),
    }


# --------------------------------------------------------------------------- #
# §4 — Nivel 1.5, compuerta de no-verde. Prohíbe salidas, no fuerza clases.
# --------------------------------------------------------------------------- #
def condiciones_compuerta(obs: Observacion, regimen: Regimen) -> dict[str, Trivalor]:
    """§4. SOLO_TARDÍO: en TEMPRANO no hay condiciones que evaluar (dict vacío)."""
    if regimen is not Regimen.TARDIO:
        return {}
    return {
        "g_fiebre": kleene.evaluar(obs.fiebre_c, lambda t: t >= UMBRAL_G_FIEBRE),
        "g_dolor": kleene.evaluar(obs.dolor_nrs, lambda p: p >= UMBRAL_G_DOLOR),
        "g_constitucional": kleene.y(
            kleene.evaluar(obs.apetito, lambda a: a == APETITO_MUY_DISMINUIDO),
            kleene.evaluar(obs.sueno, lambda s: s == SUENO_MUY_ALTERADO),
        ),
    }


def nivel_1_5(obs: Observacion, regimen: Regimen) -> Trivalor:
    """§4. Disyunción de las tres condiciones. Vacía en TEMPRANO -> FALSO."""
    return kleene.alguna(condiciones_compuerta(obs, regimen).values())


def compuerta_activa(compuerta: Trivalor) -> bool:
    """§4.1. `DESCONOCIDO` cuenta como activa: el tercer valor resuelve en la dirección segura."""
    return compuerta is not F


# --------------------------------------------------------------------------- #
# §5 — Nivel 2, agregación de señales blandas.
# --------------------------------------------------------------------------- #
def nivel_2(obs: Observacion, regimen: Regimen) -> dict[str, Trivalor]:
    """§5.1. `s_dolor` queda FUERA de la base y se evalúa contra ella (H3)."""
    base = {
        "s_fiebre": kleene.evaluar(obs.fiebre_c, lambda t: t >= UMBRAL_S_FIEBRE),
        "s_eritema": kleene.evaluar(obs.herida, lambda h: h == HERIDA_ERITEMA_LEVE),
        "s_apetito": kleene.evaluar(obs.apetito, lambda a: a == APETITO_MUY_DISMINUIDO),
        "s_sueno": kleene.evaluar(obs.sueno, lambda s: s == SUENO_MUY_ALTERADO),
    }
    dolor_alto = kleene.evaluar(obs.dolor_nrs, lambda p: p >= UMBRAL_S_DOLOR)
    if regimen is Regimen.TARDIO:
        s_dolor = dolor_alto
    else:
        # `n_base >= 1` en trivaluado es exactamente la disyunción de la base:
        # V si alguna es V, F si todas son F, D si aún podría subir a 1.
        s_dolor = kleene.y(dolor_alto, kleene.alguna(base.values()))
    return {**base, "s_dolor": s_dolor}


def contar(blandas: Mapping[str, Trivalor]) -> int:
    """§5.1. `n_total` cuenta solo VERDADERO: con evidencia parcial es una cota inferior."""
    return sum(1 for valor in blandas.values() if valor is V)


def agregacion(n_total: int, regimen: Regimen) -> Clase:
    """§5.2. Conteo puro: siempre produce una clase candidata, nunca decide si cerrar."""
    return Clase.AMARILLO if n_total >= UMBRAL_CONTEO_AMARILLO[regimen] else Clase.VERDE


# --------------------------------------------------------------------------- #
# HD6 — orden determinista de indagación (§7.3)
# --------------------------------------------------------------------------- #
def _elegible(obs: Observacion, senal: str, presupuesto: Presupuesto, tope_por_senal: int) -> bool:
    """Una señal solo es elegible si está AUSENTE y no ha agotado su tope por señal."""
    return getattr(obs, senal) is None and presupuesto.gastadas(senal) < tope_por_senal


def senal_a_indagar(
    obs: Observacion,
    banderas: Mapping[str, Trivalor],
    compuerta: Trivalor,
    presupuesto: Presupuesto,
    tope_por_senal: int = TOPE_POR_SENAL,
) -> str | None:
    """HD6. Primera señal elegible recorriendo los tres niveles de §7.3 en orden.

    Devuelve `None` si no hay ninguna: eso es lo que hace que `REPREGUNTAR` no sea
    accionable y el módulo cierre (§7.4 / §8).
    """
    # Nivel 1: señales adyacentes a una bandera de Nivel 1 en DESCONOCIDO.
    for senal in ORDEN_ADYACENTES_A_BANDERA:
        if _elegible(obs, senal, presupuesto, tope_por_senal) and any(
            banderas[bandera] is D for bandera in BANDERAS_POR_SENAL[senal]
        ):
            return senal
    # Nivel 1.5: señales que resolverían la compuerta si está en DESCONOCIDO.
    if compuerta is D:
        for senal in ORDEN_COMPUERTA:
            if _elegible(obs, senal, presupuesto, tope_por_senal):
                return senal
    # Nivel 2: discriminadores verde<->amarillo restantes.
    for senal in ORDEN_DISCRIMINADORES:
        if _elegible(obs, senal, presupuesto, tope_por_senal):
            return senal
    return None


# --------------------------------------------------------------------------- #
# Función pública
# --------------------------------------------------------------------------- #
def decidir(
    obs: Observacion,
    presupuesto: Presupuesto = PRESUPUESTO_VACIO,
    *,
    tope_por_senal: int = TOPE_POR_SENAL,
    tope_global: int = TOPE_GLOBAL,
) -> Decision:
    """Decide qué hacer con una observación: clasificar o repreguntar.

    Función pura y determinista. No muta nada, no lee entorno, no toca disco.

    Contrato del presupuesto (HD7) — el módulo NUNCA lo muta, lo lee:

    * Tras una `Decision` con `accion == REPREGUNTAR`, el llamador incrementa en 1
      `preguntas_por_senal[senal_a_indagar]` y en 1 `preguntas_totales`.
    * Si una pregunta resuelve dos señales, solo se cobra la nombrada en
      `senal_a_indagar`.
    * `preguntas_totales` cuenta turnos de repregunta emitidos, no preguntas del guion.

    Los topes (§7.2) son `[ESPECULACIÓN]` pendiente de calibración en Fase 3: viven
    en `parametros.py` y se inyectan por argumento, no se hornean en la lógica.

    Orden de evaluación: §2 (régimen) -> §3 (banderas) -> §4 (compuerta) ->
    §5 (conteo) -> §7.1 (S1/S2/S3) -> REPREGUNTAR si es accionable ->
    §7.4 (cierre forzado) o §8 (agotamiento).

    Raises:
        ErrorDeInvocacion: §8.2, entrada imposible de un llamador correcto.
    """
    _validar_observacion(obs)
    _validar_presupuesto(presupuesto, tope_por_senal, tope_global)

    regimen, marcas = nivel_0(obs.dia_postop)
    banderas = nivel_1(obs, regimen)
    compuerta = nivel_1_5(obs, regimen)
    blandas = nivel_2(obs, regimen)
    n_total = contar(blandas)

    def cerrar(
        clase: Clase, criterio: Criterio, disparadores: tuple[str, ...], extra: tuple[str, ...] = ()
    ) -> Decision:
        return Decision(
            accion=Accion.CLASIFICAR,
            clase=clase,
            criterio=criterio,
            senal_a_indagar=None,
            regimen=regimen,
            banderas=banderas,
            compuerta=compuerta,
            n_total=n_total,
            disparadores=disparadores,
            marcas=marcas + extra,
        )

    banderas_verdaderas = tuple(b for b, valor in banderas.items() if valor is V)
    banderas_desconocidas = tuple(b for b, valor in banderas.items() if valor is D)
    blandas_verdaderas = tuple(s for s, valor in blandas.items() if valor is V)

    # --- §7.1 S1: bandera roja confirmada. Precedencia absoluta (§3). --------- #
    if banderas_verdaderas:
        return cerrar(Clase.ROJO, Criterio.S1, banderas_verdaderas)

    nucleo_completo = all(getattr(obs, senal) is not None for senal in NUCLEO)
    todas_descartadas = all(valor is F for valor in banderas.values())
    activa = compuerta_activa(compuerta)

    # --- §7.1 S2: verde robusto. -------------------------------------------- #
    if nucleo_completo and not blandas_verdaderas and todas_descartadas and not activa:
        return cerrar(Clase.VERDE, Criterio.S2, ())

    # --- §7.1 S3: amarillo saturado. ---------------------------------------- #
    if (
        n_total >= UMBRAL_CONTEO_AMARILLO[regimen]
        and not banderas_desconocidas
        and (not activa or todas_descartadas)
    ):
        return cerrar(Clase.AMARILLO, Criterio.S3, blandas_verdaderas)

    # --- §7.1 REPREGUNTAR, si es accionable (§7.2, §7.3, HD6). --------------- #
    senal = (
        senal_a_indagar(obs, banderas, compuerta, presupuesto, tope_por_senal)
        if presupuesto.preguntas_totales < tope_global
        else None
    )
    if senal is not None:
        return Decision(
            accion=Accion.REPREGUNTAR,
            clase=None,
            criterio=None,
            senal_a_indagar=senal,
            regimen=regimen,
            banderas=banderas,
            compuerta=compuerta,
            n_total=n_total,
            disparadores=(),
            marcas=marcas,
        )

    # --- Cierre. Dos situaciones y solo dos (§7.4). -------------------------- #
    if nucleo_completo:
        # §7.4 — vector completo: la candidata de §5.2, filtrada. El filtro
        # prohíbe salidas, no fuerza clases (misma semántica de §4.1).
        if banderas_desconocidas:
            # Inalcanzable con vector completo; se implementa igual (§7.4 paso 1).
            return cerrar(Clase.ROJO, Criterio.CIERRE_FORZADO, banderas_desconocidas)
        candidata = agregacion(n_total, regimen)
        if activa and candidata is Clase.VERDE:
            return cerrar(
                Clase.AMARILLO,
                Criterio.CIERRE_FORZADO,
                blandas_verdaderas + ("compuerta_no_verde",),
            )
        return cerrar(candidata, Criterio.CIERRE_FORZADO, blandas_verdaderas)

    # §8 — presupuesto agotado con alguna señal AUSENTE. Partición binaria.
    #
    # Las dos premisas se VERIFICAN, no se asumen. §8 demuestra que la segunda se
    # cumple sola —si ninguna bandera está en DESCONOCIDO, las únicas señales que
    # pueden faltar son `apetito` y `sueno`—, y con el umbral de dolor indexado por
    # régimen (§3.1) esa demostración es correcta. La verificación se mantiene
    # igual, por defensa: es correcta hoy POR §3, pero no depende de §3. Si un
    # predicado futuro volviera a hacer que una bandera colapse a FALSO con su
    # señal AUSENTE, este ramal sigue eligiendo bien y no hay que acordarse de nada.
    if banderas_desconocidas:
        return cerrar(Clase.ROJO, Criterio.AGOTAMIENTO, banderas_desconocidas)
    # §8.1, invariante duro: con evidencia insuficiente la clase mínima es AMARILLO.
    return cerrar(
        Clase.AMARILLO,
        Criterio.AGOTAMIENTO,
        blandas_verdaderas + ("nucleo_incompleto",),
        extra=(MARCA_CONFIANZA_BAJA,),
    )
