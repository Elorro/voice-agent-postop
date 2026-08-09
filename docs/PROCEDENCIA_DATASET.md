# Procedencia del dataset

Este documento declara de dónde sale cada cosa que hay en `dataset/`, bajo qué
condiciones se incluye y qué NO se puede concluir de ella. Se escribe antes de
usar los datos, no después.

## Origen

`dataset/` es el material entregado a los participantes del **Tech Sphere
Challenge 2026** como insumo del reto. No lo produjo este proyecto: se recibió
ya armado y se incorpora sin modificarlo.

Contiene dos clases de material, con estatus legal y epistémico distinto:

| Contenido | Qué es | Estatus |
|---|---|---|
| Corpus de PDFs (107 documentos) | Literatura clínica de referencia sobre cuidado postoperatorio, complicaciones e infección de sitio quirúrgico | Obra de terceros. Derechos de sus autores y editoriales |
| Casos clínicos (`.xlsx`) | Pacientes y registros de seguimiento postoperatorio | **Sintéticos.** Generados para el reto |

## Derechos sobre los PDFs

**Los PDFs conservan íntegramente los derechos de autor de sus autores y
editoriales.** Se incluyen aquí únicamente como material de referencia del reto,
para construir el índice de recuperación (RAG) que sustenta las respuestas del
agente.

**Se incluyen en el repositorio**, y esa es una decisión deliberada, no un
descuido. La rúbrica exige trazabilidad de las citas del RAG: una cita solo es
verificable si el evaluador puede abrir el documento citado y leer el pasaje. Un
repositorio que se clona sin corpus deja toda cita como una afirmación que hay
que creer. Entre no redistribuir y ser verificable, se eligió ser verificable
para el alcance evaluativo del reto, con el aviso de derechos delante.

En consecuencia:

- Los 107 PDFs **viajan por git**, dentro de `dataset/`, y se montan en el
  contenedor como bind de solo lectura. `.gitignore` **no** los excluye:
  excluirlos era la política anterior, y la línea que lo hacía se retiró el
  2026-08-09.
- **No** se publican como parte de la imagen Docker. `.dockerignore` excluye
  `dataset/` completo: el corpus no debe viajar dentro de un artefacto
  publicable, y además haría cruzar los mismos bytes dos veces por la red del
  jurado.
- El uso es el evaluativo del reto. Cualquier uso posterior —producto,
  publicación, despliegue— exige revisar la licencia de cada documento por
  separado. No se ha hecho esa revisión.
- Un PDF del corpus está **escaneado sin capa de texto**. Está registrado como
  deuda abierta en `docs/bitacora.md`: se decidirá entre aplicar OCR o
  descartarlo explícitamente. No se deja como hueco silencioso.

## Los datos clínicos son sintéticos

> **AVISO. Los datos clínicos de este dataset son sintéticos y no están
> validados clínicamente.**

Qué significa, con precisión:

1. **No hay pacientes reales.** No hay información de salud protegida ni
   consentimiento informado de por medio, porque no hay nadie de quien
   obtenerlo.
2. **No sabemos si la distribución es realista.** Que un generador produzca
   casos plausibles no dice nada sobre si sus frecuencias, correlaciones y
   valores extremos se parecen a los de una cohorte postoperatoria real.
   Ninguna verificación de este proyecto puede establecerlo: para eso haría
   falta una cohorte real con la que comparar.
3. **El rendimiento medido sobre estos datos no transfiere.** Todo número que
   este proyecto reporte —recall de banderas rojas, tasas de escalamiento,
   cobertura— es rendimiento **sobre el dev set sintético**. Es evidencia de que
   el sistema hace lo que su especificación dice, no de que sea seguro en
   producción.
4. **Nada de esto es dispositivo médico ni sustituye criterio clínico.** El
   sistema es una demostración técnica para una evaluación.

Los intervalos de confianza asociados son estrechos por construcción: el dev set
tiene **6 pacientes** en la clase crítica, y la unidad de remuestreo válida es el
paciente, no el caso. El detalle está en `docs/bitacora.md` y en
`docs/diseno/parametros_politica.md`.

## Cómo llega el dataset al contenedor

Por **bind mount de solo lectura**, nunca dentro de la imagen:

```
./dataset  ->  /app/dataset   (:ro)
```

Dos razones. La primera es de derechos: los PDFs no viajan en un artefacto
publicable. La segunda es de peso: la imagen ya cruza la red del jurado una vez;
duplicar el corpus dentro de ella lo haría cruzar dos veces.

El servicio **arranca sin el dataset**. Si el directorio no existe, `/salud` lo
reporta como AVISO no bloqueante y el resto del sistema funciona.
