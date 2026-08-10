/* Consola de llamada — JS plano, sin build, sin dependencias.
 *
 * EL RELOJ AUTORITATIVO VIVE AQUÍ. La rúbrica mide «desde que el paciente
 * termina de hablar hasta que suena el audio del agente», y los dos extremos de
 * ese intervalo son eventos del navegador: el servidor no ve la subida, ni la
 * decodificación, ni el arranque de la reproducción. Un P50 medido en el
 * servidor subestima por construcción el número que el jurado contrasta con su
 * propia percepción.
 *
 * Dos decisiones de medición, dichas explícitamente porque ambas nos perjudican
 * y aun así son las correctas:
 *
 *   1. t0 NO es el instante en que el detector decide que el paciente calló:
 *      es el instante del último fragmento con voz. Entre los dos hay una
 *      ventana de silencio (VAD_SILENCIO_MS) que es tiempo real de espera del
 *      paciente. Tomar el instante de la decisión regalaría esos milisegundos.
 *   2. t1 no es la llamada a start(): es cuando el primer sample suena de
 *      verdad, así que se le suma la latencia de salida que reporta el propio
 *      AudioContext (baseLatency + outputLatency).
 *
 * Y lo que viaja al servidor es un DELTA en milisegundos, nunca un timestamp:
 * comparar el reloj del navegador con el del servidor metería el desfase entre
 * las dos máquinas dentro de la métrica.
 */
"use strict";

const CFG = JSON.parse(document.getElementById("configuracion").textContent);

const els = {
  iniciar: document.getElementById("iniciar"),
  colgar: document.getElementById("colgar"),
  dia: document.getElementById("dia_postop"),
  paciente: document.getElementById("paciente_id"),
  estado: document.getElementById("estado"),
  nivel: document.getElementById("nivel"),
  dialogo: document.getElementById("dialogo"),
  resumen: document.getElementById("resumen"),
};

let audioCtx = null;
let micro = null;
let analizador = null;
let grabadora = null;
let trozos = [];
let temporizador = null;
let inicioGrabacion = 0;

let llamadaId = null;
let turnoActual = 0;       // índice del último turno que el servidor contestó
let pendiente = null;      // { turno_idx, ms } medición aún no adjuntada a un turno
let escuchando = false;
let terminada = false;

// ---------------------------------------------------------------------------
// Utilidades
// ---------------------------------------------------------------------------
function estado(texto) {
  els.estado.textContent = texto;
}

function anotarDialogo(quien, texto, extra) {
  const li = document.createElement("li");
  const cabecera = document.createElement("span");
  cabecera.className = "quien";
  cabecera.textContent = extra ? `${quien} · ${extra}` : quien;
  li.appendChild(cabecera);
  li.appendChild(document.createTextNode(texto));
  els.dialogo.appendChild(li);
  li.scrollIntoView({ block: "nearest" });
}

function base64ABuffer(b64) {
  const binario = atob(b64);
  const bytes = new Uint8Array(binario.length);
  for (let i = 0; i < binario.length; i++) bytes[i] = binario.charCodeAt(i);
  return bytes.buffer;
}

function extensionDe(mime) {
  if (!mime) return "webm";
  if (mime.includes("ogg")) return "ogg";
  if (mime.includes("mp4")) return "mp4";
  return "webm";
}

// ---------------------------------------------------------------------------
// Reproducción: aquí se cierra el cronómetro
// ---------------------------------------------------------------------------
function reproducir(b64, t0) {
  return new Promise((resolve) => {
    if (!b64) { resolve(null); return; }
    audioCtx.decodeAudioData(base64ABuffer(b64)).then((buffer) => {
      const fuente = audioCtx.createBufferSource();
      fuente.buffer = buffer;
      fuente.connect(audioCtx.destination);
      fuente.start();
      // Latencia de salida declarada por el navegador: el sonido no sale en el
      // instante de start(), sale cuando el búfer llega a la tarjeta.
      const salidaMs = ((audioCtx.baseLatency || 0) + (audioCtx.outputLatency || 0)) * 1000;
      const t1 = performance.now() + salidaMs;
      const medicion = t0 === null ? null : Math.round((t1 - t0) * 10) / 10;
      if (medicion !== null) {
        estado(`Agente hablando · ${medicion} ms desde que usted terminó de hablar`);
      }
      // Se resuelve al TERMINAR de sonar: en 3.1 no hay barge-in, así que el
      // micrófono no vuelve a abrirse mientras el agente habla.
      fuente.onended = () => resolve(medicion);
    }).catch((err) => {
      console.error("no se pudo decodificar el audio", err);
      resolve(null);
    });
  });
}

function enviarTelemetria(turnoIdx, ms) {
  if (ms === null || ms === undefined) return;
  // `keepalive` para que la medición del último turno llegue aunque la página
  // se cierre justo después. Es el turno que ningún turno siguiente puede
  // llevar a cuestas.
  fetch(`/api/llamada/${llamadaId}/telemetria`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ turno_idx: turnoIdx, delta_fin_habla_ms: ms }),
    keepalive: true,
  }).catch(() => {});
}

// ---------------------------------------------------------------------------
// Detección de fin de habla, por energía
// ---------------------------------------------------------------------------
function escuchar() {
  if (terminada) return;
  trozos = [];
  const tipo = [
    "audio/webm;codecs=opus",
    "audio/ogg;codecs=opus",
    "audio/webm",
  ].find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";
  grabadora = tipo ? new MediaRecorder(micro, { mimeType: tipo }) : new MediaRecorder(micro);
  grabadora.ondataavailable = (e) => { if (e.data.size > 0) trozos.push(e.data); };
  grabadora.start();

  const muestras = new Float32Array(analizador.fftSize);
  const inicio = performance.now();
  inicioGrabacion = inicio;
  let hablaMs = 0;
  let ultimaVoz = null;
  escuchando = true;
  estado("Escuchando… hable cuando quiera");

  temporizador = setInterval(() => {
    analizador.getFloatTimeDomainData(muestras);
    let suma = 0;
    for (let i = 0; i < muestras.length; i++) suma += muestras[i] * muestras[i];
    const rms = Math.sqrt(suma / muestras.length);
    els.nivel.style.width = Math.min(100, (rms / (CFG.vad_umbral_rms * 3)) * 100) + "%";

    const ahora = performance.now();
    if (rms >= CFG.vad_umbral_rms) {
      hablaMs += CFG.periodo_ms;
      ultimaVoz = ahora;
    }
    const hayVoz = hablaMs >= CFG.vad_minimo_habla_ms;
    const callado = ultimaVoz !== null && ahora - ultimaVoz >= CFG.vad_silencio_ms;
    const demasiado = ahora - inicio > CFG.maximo_turno_ms;

    if ((hayVoz && callado) || (demasiado && hayVoz)) {
      // t0 = último fragmento con voz, no este instante: la ventana de silencio
      // que acabamos de esperar es tiempo real del paciente.
      finDeHabla(ultimaVoz);
    } else if (demasiado) {
      finDeHabla(ahora);
    }
  }, CFG.periodo_ms);
}

function finDeHabla(t0) {
  if (!escuchando) return;
  escuchando = false;
  clearInterval(temporizador);
  temporizador = null;
  els.nivel.style.width = "0%";
  estado("Procesando…");
  const tipo = grabadora.mimeType;
  const duracionMs = Math.round(performance.now() - inicioGrabacion);
  grabadora.onstop = () => {
    const blob = new Blob(trozos, { type: tipo });
    enviarTurno(blob, tipo, t0, duracionMs);
  };
  grabadora.stop();
}

// ---------------------------------------------------------------------------
// Turno
// ---------------------------------------------------------------------------
async function enviarTurno(blob, tipo, t0, duracionMs) {
  const formulario = new FormData();
  formulario.append("audio", blob, `turno.${extensionDe(tipo)}`);
  formulario.append("duracion_audio_ms", String(duracionMs));
  // La medición del turno anterior viaja pegada a este: cuando se subió aquel
  // audio, su t1 todavía no existía.
  if (pendiente) {
    formulario.append("delta_fin_habla_ms", String(pendiente.ms));
    formulario.append("turno_medido_idx", String(pendiente.turno_idx));
    pendiente = null;
  }

  let respuesta;
  try {
    respuesta = await fetch(`/api/llamada/${llamadaId}/turno`, {
      method: "POST",
      body: formulario,
    });
  } catch (err) {
    estado("Fallo de red al enviar el turno: " + err);
    return;
  }
  if (!respuesta.ok) {
    const detalle = await respuesta.text();
    estado(`El servidor rechazó el turno (${respuesta.status}). ${detalle.slice(0, 200)}`);
    return;
  }
  const datos = await respuesta.json();
  turnoActual = datos.turno_idx;
  if (datos.transcripcion) anotarDialogo("Paciente", datos.transcripcion);
  anotarDialogo("Agente", datos.respuesta, `turno ${datos.turno_idx} · ${datos.fuente_respuesta}`);

  const ms = await reproducir(datos.audio_wav_b64, t0);
  if (ms !== null && ms !== undefined) {
    pendiente = { turno_idx: datos.turno_idx, ms: ms };
    enviarTelemetria(datos.turno_idx, ms);
  }

  if (datos.fin) {
    terminar(datos);
  } else {
    escuchar();
  }
}

function terminar(datos) {
  terminada = true;
  escuchando = false;
  if (temporizador) clearInterval(temporizador);
  if (micro) micro.getTracks().forEach((t) => t.stop());
  els.colgar.disabled = true;
  els.iniciar.disabled = false;
  estado("Llamada terminada.");

  const clase = datos.clase || "—";
  const criterio = datos.criterio || "—";
  const totales = (datos.cierre && datos.cierre.totales) || {};
  els.resumen.innerHTML =
    `<h2>Cierre</h2><p>Clase <span class="clase clase-${clase}">${clase}</span> ` +
    `por criterio <code>${criterio}</code>.</p>` +
    `<p class="tenue">Preguntas emitidas: ${datos.presupuesto.preguntas_totales} de ` +
    `${datos.presupuesto.tope_global} · turnos: ${totales.turnos ?? "—"} · ` +
    `tokens: ${totales.tokens_entrada ?? "—"} entrada / ${totales.tokens_salida ?? "—"} salida.</p>` +
    `<p><a href="/metricas">Ver métricas de todas las llamadas</a></p>`;
}

// ---------------------------------------------------------------------------
// Arranque y colgado
// ---------------------------------------------------------------------------
async function iniciar() {
  els.iniciar.disabled = true;
  els.resumen.innerHTML = "";
  els.dialogo.innerHTML = "";
  terminada = false;
  pendiente = null;

  try {
    micro = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  } catch (err) {
    estado("Sin micrófono: " + err + ". El navegador solo lo concede en HTTPS o en localhost.");
    els.iniciar.disabled = false;
    return;
  }

  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  await audioCtx.resume();
  analizador = audioCtx.createAnalyser();
  analizador.fftSize = 1024;
  audioCtx.createMediaStreamSource(micro).connect(analizador);

  estado("Abriendo la llamada…");
  const t0 = performance.now();
  const cuerpo = {};
  if (els.dia.value !== "") cuerpo.dia_postop = Number(els.dia.value);
  if (els.paciente.value !== "") cuerpo.paciente_id = els.paciente.value;

  let datos;
  try {
    const respuesta = await fetch("/api/llamada", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cuerpo),
    });
    if (!respuesta.ok) throw new Error(await respuesta.text());
    datos = await respuesta.json();
  } catch (err) {
    estado("No se pudo abrir la llamada: " + err);
    els.iniciar.disabled = false;
    return;
  }

  llamadaId = datos.llamada_id;
  turnoActual = 0;
  els.colgar.disabled = false;
  anotarDialogo("Agente", datos.respuesta, "apertura");
  const ms = await reproducir(datos.audio_wav_b64, t0);
  // La apertura se anota, pero no entra en el P50/P95: no hubo «fin de habla»
  // del paciente que cronometrar, solo un clic.
  if (ms !== null && ms !== undefined) enviarTelemetria(0, ms);
  escuchar();
}

async function colgar() {
  if (!llamadaId) return;
  if (temporizador) clearInterval(temporizador);
  escuchando = false;
  terminada = true;
  if (micro) micro.getTracks().forEach((t) => t.stop());
  estado("Cerrando…");
  try {
    const respuesta = await fetch(`/api/llamada/${llamadaId}/cierre`, { method: "POST" });
    const datos = await respuesta.json();
    terminar({
      clase: datos.clase,
      criterio: datos.criterio || "colgada_por_el_operador",
      presupuesto: datos.presupuesto,
      cierre: { totales: datos.totales },
    });
  } catch (err) {
    estado("Fallo al cerrar: " + err);
  }
}

els.iniciar.addEventListener("click", iniciar);
els.colgar.addEventListener("click", colgar);
