// Consola de administración del corpus. JS plano: sin build, sin node en la
// imagen y sin una sola dependencia que descargar en la máquina del jurado.
//
// El sondeo (`GET /api/documentos` cada 1,5 s) es lo que hace visible el estado
// intermedio que pide el reto. Se enciende SOLO mientras hay algo en cola o
// procesándose y se apaga en cuanto todo terminó: un intervalo permanente
// golpearía el servidor cada segundo y medio durante toda la evaluación, y el
// servidor es el mismo proceso que atiende la llamada del paciente.
"use strict";

(function () {
  const cfg = JSON.parse(document.getElementById("configuracion").textContent);
  const $ = (id) => document.getElementById(id);
  const entrada = $("archivo");
  const boton = $("subir");
  const estado = $("estado");
  const filas = $("filas");

  let temporizador = null;

  const ETIQUETAS = {
    pendiente: "en cola",
    procesando: "procesando",
    disponible: "procesado y disponible",
    error: "error",
  };

  function decir(texto, esError) {
    estado.textContent = texto;
    estado.style.color = esError ? "var(--fallo, #a71d2a)" : "";
  }

  function fecha(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    return isNaN(d) ? iso : d.toLocaleString();
  }

  function fila(doc) {
    const tr = document.createElement("tr");

    const tdEstado = document.createElement("td");
    const marca = document.createElement("span");
    marca.className = "marca marca-" + doc.estado;
    if (doc.estado === "procesando" || doc.estado === "pendiente") {
      const punto = document.createElement("span");
      punto.className = "latido";
      marca.appendChild(punto);
    }
    marca.appendChild(
      document.createTextNode(doc.etiqueta_estado || ETIQUETAS[doc.estado] || doc.estado)
    );
    tdEstado.appendChild(marca);
    tr.appendChild(tdEstado);

    const tdNombre = document.createElement("td");
    // textContent y nunca innerHTML: el nombre lo eligió quien subió el archivo.
    tdNombre.textContent = doc.nombre;
    if (doc.mensaje) {
      const motivo = document.createElement("span");
      motivo.className = "motivo";
      motivo.textContent = doc.mensaje;
      tdNombre.appendChild(motivo);
    }
    tr.appendChild(tdNombre);

    const tdPaginas = document.createElement("td");
    tdPaginas.textContent = doc.paginas || "—";
    tr.appendChild(tdPaginas);

    const tdTrozos = document.createElement("td");
    tdTrozos.textContent =
      doc.trozos_en_indice === null || doc.trozos_en_indice === undefined
        ? "—"
        : String(doc.trozos_en_indice);
    tr.appendChild(tdTrozos);

    const tdFecha = document.createElement("td");
    tdFecha.textContent = fecha(doc.subido_en);
    tr.appendChild(tdFecha);

    const tdAcciones = document.createElement("td");
    const borrar = document.createElement("button");
    borrar.className = "enlace";
    borrar.textContent = "eliminar";
    // Mientras se procesa no se puede borrar: el hilo de ingesta está
    // escribiendo fragmentos de ese mismo documento y el borrado los perdería
    // de vista, dejando en el índice lo que se insertara después.
    borrar.disabled = doc.estado === "procesando" || doc.estado === "pendiente";
    borrar.addEventListener("click", () => eliminar(doc));
    tdAcciones.appendChild(borrar);
    tr.appendChild(tdAcciones);

    return tr;
  }

  async function refrescar() {
    let datos;
    try {
      const r = await fetch("/api/documentos", { headers: { Accept: "application/json" } });
      datos = await r.json();
    } catch (err) {
      decir("no se pudo consultar el inventario: " + err, true);
      return;
    }

    filas.replaceChildren();
    const documentos = datos.documentos || [];
    if (!documentos.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 6;
      td.className = "vacia";
      td.textContent =
        "No hay documentos subidos. El corpus del reto ya está indexado aparte; " +
        "lo que suba aquí se suma a él.";
      tr.appendChild(td);
      filas.appendChild(tr);
    } else {
      documentos.forEach((d) => filas.appendChild(fila(d)));
    }

    const enCurso = documentos.filter(
      (d) => d.estado === "procesando" || d.estado === "pendiente"
    ).length;
    const listos = documentos.filter((d) => d.estado === "disponible").length;

    if (!datos.indice_disponible) {
      decir("El índice vectorial no está disponible; consulte /salud.", true);
    } else if (enCurso) {
      decir(`${enCurso} documento(s) procesándose · ${listos} disponible(s).`);
    } else {
      decir(
        `${listos} documento(s) subido(s) y disponible(s) para el agente. ` +
          `Formatos: ${(datos.formatos || []).join(", ")} · máximo ${datos.max_mb} MB.`
      );
    }

    programar(enCurso > 0);
  }

  function programar(hayTrabajo) {
    if (temporizador) {
      clearTimeout(temporizador);
      temporizador = null;
    }
    if (hayTrabajo) {
      temporizador = setTimeout(refrescar, cfg.periodo_sondeo_ms || 1500);
    }
  }

  async function subir() {
    const archivo = entrada.files && entrada.files[0];
    if (!archivo) {
      decir("Elija un archivo primero.", true);
      return;
    }
    const cuerpo = new FormData();
    cuerpo.append("archivo", archivo, archivo.name);

    boton.disabled = true;
    decir(`Subiendo «${archivo.name}»…`);
    try {
      const r = await fetch("/api/documentos", { method: "POST", body: cuerpo });
      if (!r.ok) {
        let detalle = r.statusText;
        try {
          detalle = (await r.json()).detail || detalle;
        } catch (_) {}
        decir(`No se pudo subir: ${detalle}`, true);
        return;
      }
      entrada.value = "";
      decir("Recibido. Indexando en segundo plano…");
    } catch (err) {
      decir("No se pudo subir: " + err, true);
      return;
    } finally {
      boton.disabled = false;
    }
    refrescar();
  }

  async function eliminar(doc) {
    if (!confirm(`¿Eliminar «${doc.nombre}»? El agente dejará de usarlo.`)) return;
    try {
      const r = await fetch("/api/documentos/" + encodeURIComponent(doc.id), {
        method: "DELETE",
      });
      const datos = await r.json();
      if (!r.ok) {
        decir("No se pudo eliminar: " + (datos.detail || r.statusText), true);
      } else {
        decir(
          `Eliminado «${datos.nombre}»: ${datos.fragmentos_borrados} fragmento(s) ` +
            "fuera del índice."
        );
      }
    } catch (err) {
      decir("No se pudo eliminar: " + err, true);
    }
    refrescar();
  }

  boton.addEventListener("click", subir);
  refrescar();
})();
