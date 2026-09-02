/* =============================================================================
   app.js — Dashboard de validación de pruebas (React sin paso de build).
   React 18 UMD + htm (vendorizados en vendor/): funciona sin internet.
   Vistas: Resumen (KPIs + distribución), Tabla (filtro + buscador + teclado),
   Detalle (imagen original + OCR etiqueta vs referencia lado a lado).
   La paleta del semáforo llega de /api/config → idéntica al Excel.
   Ruta de migración a Vite + Tremor: docs/fase4_dashboard.md.
   ============================================================================= */

const { useState, useEffect, useMemo, useRef, useCallback } = React;
const html = htm.bind(React.createElement);

/* ----------------------------- Utilidades ----------------------------- */

async function pedirJSON(url, signal) {
  const r = await fetch(url, { signal });
  if (r.status === 404) return null; // sin datos procesados aún
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

async function enviarJSON(url, datos) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(datos),
  });
  const cuerpo = await r.json().catch(() => ({}));
  if (!r.ok) {
    const detalle = cuerpo.detail;
    const mensaje = typeof detalle === "string" ? detalle
      : detalle?.mensaje
        ? `${detalle.mensaje}${detalle.faltantes?.length ? ` Faltan: ${detalle.faltantes.join(", ")}.` : ""}`
        : `HTTP ${r.status}`;
    throw new Error(mensaje);
  }
  return cuerpo;
}

function useApi(ruta, deps) {
  const [datos, setDatos] = useState(undefined); // undefined = cargando
  const [error, setError] = useState(null);
  useEffect(() => {
    const controlador = new AbortController();
    setDatos(undefined);
    setError(null);
    pedirJSON(ruta, controlador.signal)
      .then(setDatos)
      .catch((e) => {
        if (e.name !== "AbortError") {
          setError(e);
          setDatos(null);
        }
      });
    return () => controlador.abort();
  }, deps || []);
  return [datos, setDatos, error];
}

function useDebounce(valor, demora = 250) {
  const [estable, setEstable] = useState(valor);
  useEffect(() => {
    const id = setTimeout(() => setEstable(valor), demora);
    return () => clearTimeout(id);
  }, [valor, demora]);
  return estable;
}

function usarTema() {
  const [tema, setTema] = useState(() =>
    localStorage.getItem("tema") ||
    (matchMedia("(prefers-color-scheme: dark)").matches ? "oscuro" : "claro"));
  useEffect(() => {
    document.documentElement.dataset.tema = tema;
    localStorage.setItem("tema", tema);
  }, [tema]);
  return [tema, () => setTema((t) => (t === "claro" ? "oscuro" : "claro"))];
}

const fmtPct = (v) => (v === null || v === undefined) ? "—" : `${v.toFixed(1)}%`;
const fmtDuracion = (segundos) => {
  if (segundos === null || segundos === undefined) return "Calculando…";
  const total = Math.max(0, Math.round(segundos));
  if (total < 60) return `${total} s`;
  const minutos = Math.floor(total / 60);
  const resto = total % 60;
  return `${minutos} min ${resto} s`;
};
const normalizarCodigoVista = (texto) => (texto || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
const fmtFecha = (v) => {
  if (!v) return "—";
  const fecha = new Date(v);
  if (Number.isNaN(fecha.getTime())) return v;
  return new Intl.DateTimeFormat("es-MX", {
    dateStyle: "medium", timeStyle: "short"
  }).format(fecha);
};
const etiquetasRevision = {
  por_revisar: "Por revisar",
  parcial: "Revisión parcial",
  casi_listo: "Casi listo",
  completada: "Completada",
};
const etiquetaRevision = (estado) => etiquetasRevision[estado] || "Por revisar";
const CLAVE_RUTAS_RECIENTES = "ocr_rutas_recientes_v1";
function cargarRutasRecientes() {
  try {
    const guardadas = JSON.parse(localStorage.getItem(CLAVE_RUTAS_RECIENTES) || "[]");
    return Array.isArray(guardadas) ? guardadas.filter((item) => item?.ruta).slice(0, 10) : [];
  } catch (_) {
    return [];
  }
}
function persistirRutasRecientes(rutas) {
  try {
    localStorage.setItem(CLAVE_RUTAS_RECIENTES, JSON.stringify(rutas.slice(0, 10)));
  } catch (_) {
    // El modo privado puede impedir localStorage; el procesamiento sigue funcionando.
  }
}
const textoUnidad = (unidad) => unidad?.texto_original || unidad?.texto || "";
const textoVisible = (unidad) => unidad?.texto || unidad?.texto_original || "";
const firmaUnidad = (unidad) => `${textoUnidad(unidad)}|${JSON.stringify(unidad?.bbox || null)}`;
function unidadesOcr(ocr = {}) {
  const lineas = (ocr.lineas_texto || []).map((u) => ({ ...u, tipo_unidad: "renglón" }));
  // Un renglón ya contiene sus tokens: no mostramos ambas representaciones.
  // Los tokens siguen siendo el respaldo para OCR antiguos que no generaron líneas.
  const tokens = lineas.length ? [] : (ocr.tokens || [])
    .map((u) => ({ ...u, tipo_unidad: "token" }));
  const espaciales = lineas.length ? lineas : tokens;
  const vistas = espaciales.filter((unidad, indice, todas) => textoUnidad(unidad)
    && todas.findIndex((otra) => firmaUnidad(otra) === firmaUnidad(unidad)) === indice);
  if (ocr.texto_completo) {
    vistas.push({ texto: ocr.texto_completo, bbox: null, tipo_unidad: "bloque completo" });
  }
  return vistas.map((unidad, indice) => ({
    ...unidad, unidad_id: `${unidad.tipo_unidad}-${indice}-${firmaUnidad(unidad)}`,
  }));
}
function unidadConfirmada(unidad, correcciones = []) {
  return correcciones.some((c) => normalizarCodigoVista(c.texto_ocr) === normalizarCodigoVista(textoUnidad(unidad))
    && JSON.stringify(c.bbox || null) === JSON.stringify(unidad.bbox || null));
}

/* ----------------------------- Componentes ----------------------------- */

function ChipSemaforo({ color, colores, children }) {
  const hex = colores && colores[color];
  return html`<span class=${`chip ${hex ? "" : "neutro"}`}
                     style=${hex ? { "--semaforo": hex } : undefined}>
    <span class="punto"></span>${children}</span>`;
}

function Kpi({ etiqueta, valor, sub, color }) {
  return html`<div class="tarjeta">
    <div class="kpi-etiqueta">${etiqueta}</div>
    <div class="kpi-valor">${valor}</div>
    ${sub && html`<div class="kpi-sub">${sub}</div>`}
    ${color && html`<div class="kpi-franja" style=${{ background: color }}></div>`}
  </div>`;
}

function Dona({ conteo, colores, total }) {
  // Dona SVG pura (sin librería): segmentos proporcionales al semáforo.
  const radio = 62, grosor = 20, cx = 80, cy = 80;
  const circ = 2 * Math.PI * radio;
  const orden = ["verde", "amarillo", "rojo", "sin_clasificar"];
  let acumulado = 0;
  const segmentos = orden.filter((k) => (conteo[k] || 0) > 0).map((k) => {
    const frac = conteo[k] / total;
    const seg = { k, largo: frac * circ, offset: acumulado };
    acumulado += frac * circ;
    return seg;
  });
  return html`<svg viewBox="0 0 160 160" role="img" aria-label="Distribución del semáforo"
      style=${{ maxWidth: 190, margin: "0 auto", display: "block" }}>
    <circle cx=${cx} cy=${cy} r=${radio} fill="none" stroke="var(--borde)" strokeWidth=${grosor} />
    ${segmentos.map((s) => html`
      <circle key=${s.k} cx=${cx} cy=${cy} r=${radio} fill="none"
        stroke=${colores[s.k] || "var(--texto-3)"} strokeWidth=${grosor}
        strokeDasharray=${`${s.largo} ${circ - s.largo}`}
        strokeDashoffset=${-s.offset} transform=${`rotate(-90 ${cx} ${cy})`} />`)}
    <text x=${cx} y=${cy - 4} textAnchor="middle" fontSize="26" fontWeight="700" fill="var(--texto)">${total}</text>
    <text x=${cx} y=${cy + 16} textAnchor="middle" fontSize="10.5" fill="var(--texto-3)">PRUEBAS</text>
  </svg>`;
}

function BarrasLote({ porLote, colores }) {
  const lotes = Object.entries(porLote || {});
  if (!lotes.length) return html`<p class="subtitulo-seccion">Sin lotes para mostrar.</p>`;
  return html`<div style=${{ display: "flex", flexDirection: "column", gap: 14 }}>
    ${lotes.map(([lote, c]) => {
      const total = c.total || 1;
      return html`<div key=${lote}>
        <div style=${{ display: "flex", justifyContent: "space-between", fontSize: 13.5, marginBottom: 5 }}>
          <strong>${lote}</strong><span class="subtitulo-seccion" style=${{ margin: 0 }}>${c.total} carpetas</span>
        </div>
        <div role="img" aria-label=${`Lote ${lote}: ${c.verde} verdes, ${c.amarillo} amarillos, ${c.rojos ?? c.rojo} rojos`}
             style=${{ display: "flex", height: 14, borderRadius: 7, overflow: "hidden", background: "var(--borde)" }}>
          ${["verde", "amarillo", "rojo", "sin_clasificar"].map((k) =>
            (c[k] || 0) > 0 && html`<div key=${k} title=${`${k}: ${c[k]}`}
              style=${{ width: `${(c[k] / total) * 100}%`, background: colores[k] || "var(--texto-3)" }}></div>`)}
        </div>
      </div>`;
    })}
  </div>`;
}

function LeyendaSemaforo({ colores }) {
  return html`<div class="leyenda">
    ${["verde", "amarillo", "rojo"].map((k) => html`<span key=${k} class="item">
      <span class="swatch" style=${{ background: colores[k] }}></span>${k}</span>`)}
    <span class="item"><span class="swatch" style=${{ background: "var(--texto-3)" }}></span>sin clasificar</span>
  </div>`;
}

function CargandoKpis() {
  return html`<div class="rejilla-kpi">
    ${[0, 1, 2, 3, 4].map((i) => html`<div key=${i} class="tarjeta"><div class="esqueleto"></div></div>`)}
  </div>`;
}

function EstadoVacio() {
  return html`<div class="estado-vacio">
    <div class="icono">🗂️</div>
    <h2 style=${{ margin: "0 0 6px" }}>Aún no hay datos procesados</h2>
    <p style=${{ margin: 0 }}>Ejecuta el pipeline sobre una carpeta de lote y vuelve a cargar esta página:</p>
    <p style=${{ margin: "10px 0 0" }}><code>python pipeline.py &lt;ruta_raiz&gt;</code></p>
  </div>`;
}

function EstadoError({ mensaje = "No fue posible cargar el dashboard." }) {
  return html`<div class="estado-vacio estado-error" role="alert">
    <div class="icono">⚠️</div>
    <h2 style=${{ margin: "0 0 6px" }}>Ocurrió un problema al cargar</h2>
    <p style=${{ margin: 0 }}>${mensaje} Comprueba que el backend siga activo y vuelve a intentarlo.</p>
    <button class="boton" style=${{ marginTop: 14 }} onClick=${() => location.reload()}>Reintentar</button>
  </div>`;
}

/* ----------------------------- Vistas ----------------------------- */

function VistaResumen() {
  const [resumen, , errorResumen] = useApi("/api/resumen");
  const [config, , errorConfig] = useApi("/api/config");
  const colores = (config && config.colores) || {};
  if (resumen === undefined || config === undefined) return html`<${CargandoKpis} />`;
  if (errorResumen || errorConfig) return html`<${EstadoError} />`;
  if (!resumen) return html`<${EstadoVacio} />`;
  const s = resumen.semaforo;
  return html`
    <div class="rejilla-kpi">
      <${Kpi} etiqueta="Pruebas procesadas" valor=${resumen.total_procesadas}
        sub=${`${resumen.total_carpetas} carpetas recorridas`} />
      <${Kpi} etiqueta="Verde" valor=${`${resumen.pct.verde ?? 0}%`} sub=${`${s.verde} carpetas`} color=${colores.verde} />
      <${Kpi} etiqueta="Amarillo" valor=${`${resumen.pct.amarillo ?? 0}%`} sub=${`${s.amarillo} carpetas`} color=${colores.amarillo} />
      <${Kpi} etiqueta="Rojo" valor=${`${resumen.pct.rojo ?? 0}%`} sub=${`${s.rojo} carpetas`} color=${colores.rojo} />
      <${Kpi} etiqueta="Confianza OCR promedio" valor=${fmtPct(resumen.confianza_promedio)}
        sub="media del lote (etiquetas)" />
    </div>

    <div class="rejilla-2">
      <div class="tarjeta">
        <h3 class="titulo-seccion" style=${{ marginTop: 0 }}>Distribución del semáforo</h3>
        <${Dona} conteo=${{ ...s }} colores=${colores} total=${resumen.total_carpetas} />
        <div style=${{ marginTop: 12 }}><${LeyendaSemaforo} colores=${colores} /></div>
      </div>
      <div class="tarjeta">
        <h3 class="titulo-seccion" style=${{ marginTop: 0 }}>Semáforo por lote</h3>
        <p class="subtitulo-seccion">Cada barra apila el estado de las carpetas de un lote.</p>
        <${BarrasLote} porLote=${resumen.distribucion_por_lote} colores=${colores} />
      </div>
    </div>

    <div class="aviso ayuda-carga">
      <strong>Para procesar otra carpeta</strong>
      <span>Ahora puedes indicar una carpeta local sin subir ni duplicar sus archivos.</span>
      <a class="boton" href="#/carga">Abrir carga de carpeta →</a>
    </div>

    <p class="subtitulo-seccion pie-datos">
      ${resumen.raiz
        ? html`Datos mostrados desde: <span class="mono">${resumen.raiz}</span>`
        : "La carpeta original ya no está disponible en este equipo."}
      · resultados generados el ${fmtFecha(resumen.generado_en)}
    </p>
  `;
}

function VistaCarga() {
  const [rutasRecientes, setRutasRecientes] = useState(cargarRutasRecientes);
  const [ruta, setRuta] = useState(() => cargarRutasRecientes()[0]?.ruta || "");
  const [nombreExcel, setNombreExcel] = useState(
    () => cargarRutasRecientes()[0]?.nombre_excel || "");
  const [sobrescribirExcel, setSobrescribirExcel] = useState(false);
  const [estado, setEstado] = useState(undefined);
  const [errorEstado, setErrorEstado] = useState(null);
  const [enviando, setEnviando] = useState(false);
  const [errorEnvio, setErrorEnvio] = useState(null);
  const [reloj, setReloj] = useState(Date.now());
  const [capacidad, , errorCapacidad] = useApi("/api/pipeline/capacidad");

  const refrescar = useCallback(() => {
    pedirJSON("/api/pipeline/estado")
      .then((dato) => { setEstado(dato); setErrorEstado(null); })
      .catch((e) => setErrorEstado(e));
  }, []);

  useEffect(() => {
    refrescar();
    const id = setInterval(refrescar, 1200);
    return () => clearInterval(id);
  }, [refrescar]);

  useEffect(() => {
    if (ruta || rutasRecientes.length) return;
    pedirJSON("/api/resumen")
      .then((resumen) => { if (resumen?.raiz) setRuta(resumen.raiz); })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (estado?.estado !== "procesando") return undefined;
    const id = setInterval(() => setReloj(Date.now()), 250);
    return () => clearInterval(id);
  }, [estado?.estado]);

  const usarActual = async () => {
    setErrorEnvio(null);
    try {
      const resumen = await pedirJSON("/api/resumen");
      if (resumen?.raiz) setRuta(resumen.raiz);
      else setErrorEnvio("No hay una carpeta local disponible en los resultados actuales.");
    } catch (e) {
      setErrorEnvio(e.message);
    }
  };

  const procesar = async (ev) => {
    ev.preventDefault();
    setErrorEnvio(null);
    setEnviando(true);
    try {
      await enviarJSON("/api/pipeline", {
        ruta: ruta.trim(), nombre_excel: nombreExcel.trim() || null,
        sobrescribir_excel: sobrescribirExcel,
      });
      const nueva = {
        ruta: ruta.trim(), nombre_excel: nombreExcel.trim(),
        usado_en: new Date().toISOString(),
      };
      const actualizadas = [nueva, ...rutasRecientes.filter((item) => item.ruta !== nueva.ruta)];
      setRutasRecientes(actualizadas);
      persistirRutasRecientes(actualizadas);
      refrescar();
    } catch (e) {
      setErrorEnvio(e.message);
    } finally {
      setEnviando(false);
    }
  };

  const procesando = estado?.estado === "procesando";
  const pausado = estado?.estado === "pausado";
  const activo = procesando || pausado;
  const porcentaje = Math.min(100, Math.max(0, Number(estado?.porcentaje) || 0));
  const parciales = estado?.resultados_parciales || [];
  const transcurridoVivo = procesando && estado.iniciado_en
    ? Math.max(0, (reloj - new Date(estado.iniciado_en).getTime()) / 1000)
    : estado?.transcurrido_segundos;
  const segundosDesdeActualizacion = estado?.actualizado_en
    ? Math.max(0, (reloj - new Date(estado.actualizado_en).getTime()) / 1000) : 0;
  const etaViva = procesando && estado?.eta_segundos !== null && estado?.eta_segundos !== undefined
    ? Math.max(0, estado.eta_segundos - segundosDesdeActualizacion) : estado?.eta_segundos;
  const noLista = capacidad && !capacidad.listo;
  function elegirRutaGuardada(valor) {
    const elegida = rutasRecientes.find((item) => item.ruta === valor);
    if (!elegida) return;
    setRuta(elegida.ruta);
    setNombreExcel(elegida.nombre_excel || "");
  }
  function quitarRutaActual() {
    const actualizadas = rutasRecientes.filter((item) => item.ruta !== ruta);
    setRutasRecientes(actualizadas);
    persistirRutasRecientes(actualizadas);
    const siguiente = actualizadas[0];
    setRuta(siguiente?.ruta || "");
    setNombreExcel(siguiente?.nombre_excel || "");
  }
  async function alternarPausa() {
    setErrorEnvio(null);
    try {
      await enviarJSON(pausado ? "/api/pipeline/reanudar" : "/api/pipeline/pausar", {});
      refrescar();
    } catch (e) {
      setErrorEnvio(e.message);
    }
  }
  if (capacidad === undefined || estado === undefined) {
    return html`<div class="tarjeta" style=${{ marginTop: 20 }}><div class="esqueleto"></div></div>`;
  }
  if (errorCapacidad || errorEstado) return html`<${EstadoError} />`;

  return html`
    <section class="carga-cabecera">
      <div>
        <p class="sobrelinea">FASE 4B</p>
        <h2>Procesar una carpeta local</h2>
        <p>El dashboard usa la carpeta directamente en este equipo. No sube ni copia sus archivos.</p>
      </div>
      <span class=${`estado-entorno ${capacidad.listo ? "listo" : "pendiente"}`}>
        ${capacidad.listo
          ? `OCR listo · ${(capacidad.recursos?.seleccionado || "cpu").toUpperCase()}`
          : "Entorno OCR incompleto"}
      </span>
    </section>

    ${noLista && html`<div class="aviso aviso-error" role="alert">
      <strong>No es posible iniciar todavía.</strong>
      <span>Faltan dependencias en el Python que ejecuta el dashboard: ${capacidad.faltantes.join(", ")}.</span>
    </div>`}

    <form class="tarjeta formulario-carga" onSubmit=${procesar}>
      ${rutasRecientes.length > 0 && html`<div class="rutas-guardadas">
        <label for="ruta-guardada"><strong>Direcciones guardadas</strong></label>
        <p class="subtitulo-seccion">Se conservan en este navegador para reutilizarlas aunque cierres el programa.</p>
        <div class="fila-ruta">
          <select id="ruta-guardada" class="campo" value=${rutasRecientes.some((item) => item.ruta === ruta) ? ruta : ""}
            onChange=${(e) => elegirRutaGuardada(e.target.value)} disabled=${activo || enviando}>
            <option value="">Seleccionar una dirección anterior…</option>
            ${rutasRecientes.map((item) => html`<option key=${item.ruta} value=${item.ruta}>
              ${item.ruta}${item.nombre_excel ? ` → ${item.nombre_excel}` : ""}
            </option>`)}
          </select>
          <button type="button" class="boton boton-peligro" onClick=${quitarRutaActual}
            disabled=${activo || enviando || !rutasRecientes.some((item) => item.ruta === ruta)}>
            Quitar dirección
          </button>
        </div>
      </div>`}
      <label for="ruta-carpeta"><strong>Dirección de la carpeta raíz</strong></label>
      <p class="subtitulo-seccion">Pega una ruta absoluta o una ruta relativa a la carpeta del proyecto.</p>
      <div class="fila-ruta">
        <input id="ruta-carpeta" class="campo" type="text" required
          placeholder="/Users/usuario/lotes/Lote_Pruebas"
          value=${ruta} onInput=${(e) => setRuta(e.target.value)}
          disabled=${activo || enviando} />
        <button type="button" class="boton" onClick=${usarActual} disabled=${activo || enviando}>
          Usar carpeta actual
        </button>
      </div>
      <label for="nombre-excel"><strong>Nombre del Excel de salida</strong></label>
      <p class="subtitulo-seccion">Opcional. Si lo omites se usará <span class="mono">resultado_maestro.xlsx</span>.</p>
      <input id="nombre-excel" class="campo" type="text" maxLength=${128}
        placeholder="resultado_maestro.xlsx" value=${nombreExcel}
        onInput=${(e) => setNombreExcel(e.target.value)} disabled=${activo || enviando} />
      <label class="control-ocultos opcion-sobrescribir">
        <input type="checkbox" checked=${sobrescribirExcel}
          onChange=${(e) => setSobrescribirExcel(e.target.checked)} disabled=${activo || enviando} />
        Sobrescribir el Excel si ya existe
      </label>
      <p class="subtitulo-seccion">Si está desactivado, se conserva el anterior y se crea, por ejemplo,
        <span class="mono"> resultado_maestro_1.xlsx</span>.</p>
      <div class="nota-local">
        <span aria-hidden="true">🔒</span>
        <span>Los archivos permanecen en su ubicación. Para lotes de 8 GB, esto evita una copia innecesaria.</span>
      </div>
      <button class="boton boton-primario" type="submit"
        disabled=${activo || enviando || !ruta.trim() || noLista}>
        ${activo ? "Procesamiento activo" : enviando ? "Iniciando…" : "Procesar carpeta"}
      </button>
      ${errorEnvio && html`<p class="mensaje-error" role="alert">${errorEnvio}</p>`}
    </form>

    <div class="tarjeta panel-progreso" aria-live="polite">
      <div class="progreso-titulo">
        <h3>Estado del procesamiento</h3>
        <span class=${`estado-ejecucion estado-${estado.estado}`}>${estado.estado}</span>
      </div>
      <div class="progreso-resumen">
        <strong>${porcentaje.toFixed(1)}%</strong>
        <span>${estado.procesadas || 0} de ${estado.total || "—"} carpetas listas</span>
        <span>${estado.imagenes_procesadas || 0} de ${estado.imagenes_total || "—"} imágenes</span>
        <span>Tiempo restante estimado: ${pausado ? "En pausa" : etaViva === null || etaViva === undefined
          ? (procesando ? "Calibrando…" : "—")
          : etaViva === 0 && procesando ? "Recalculando…" : fmtDuracion(etaViva)}</span>
      </div>
      <div class="progreso-determinado" role="progressbar" aria-label="Avance total"
        aria-valuemin="0" aria-valuemax="100" aria-valuenow=${porcentaje}>
        <span style=${{ width: `${porcentaje}%` }}></span>
      </div>
      <dl class="ficha">
        <dt>Fase actual</dt><dd>${estado.fase || "—"}</dd>
        <dt>Mensaje</dt><dd>${estado.mensaje || "Aún no se ha iniciado una ejecución."}</dd>
        <dt>Carpeta</dt><dd class="mono">${estado.ruta || "—"}</dd>
        <dt>Excel</dt><dd class="mono">${estado.nombre_excel || "resultado_maestro.xlsx"}</dd>
        <dt>Procesamiento</dt><dd>${estado.recursos
          ? `${estado.recursos.seleccionado.toUpperCase()} para OCR · ${estado.recursos.cpu_hilos} hilos CPU disponibles`
          : "—"}</dd>
        <dt>Inicio</dt><dd>${fmtFecha(estado.iniciado_en)}</dd>
        <dt>Tiempo transcurrido</dt><dd class="reloj-vivo">${fmtDuracion(transcurridoVivo)}</dd>
        ${estado.finalizado_en && html`<dt>Finalización</dt><dd>${fmtFecha(estado.finalizado_en)}</dd>`}
      </dl>
      ${activo && html`<button class=${`boton ${pausado ? "boton-primario" : ""}`}
        onClick=${alternarPausa}>${pausado ? "Continuar procesamiento" : "Pausar después de esta imagen"}</button>`}
      ${estado.error && html`<div class="mensaje-error" role="alert">
        <strong>Error:</strong> ${estado.error}
        ${estado.bitacora && html`<div class="mono">Bitácora: ${estado.bitacora}</div>`}
      </div>`}
      ${estado.estado === "completado" && html`<a class="boton boton-primario" href="#/resumen">
        Ver resultados actualizados →</a>`}
    </div>

    ${parciales.length > 0 && html`<section class="resultados-en-vivo">
      <div class="progreso-titulo">
        <div>
          <h3>Resultados listos</h3>
          <p class="subtitulo-seccion">Aparecen aquí en cuanto termina cada carpeta.</p>
        </div>
        <span class="chip neutro"><span class="punto"></span>${parciales.length} visibles</span>
      </div>
      <div class="contenedor-tabla">
        <table aria-label="Resultados completados durante el procesamiento">
          <thead><tr><th>Identificador</th><th>Lote</th><th>Resultado</th><th>Revisión</th><th>Estado</th></tr></thead>
          <tbody>${parciales.map((fila) => html`<tr key=${fila.id}>
            <td data-etiqueta="Identificador"><strong>${fila.identificador || fila.nombre}</strong></td>
            <td data-etiqueta="Lote">${fila.lote}</td>
            <td data-etiqueta="Resultado">${fila.resultado}</td>
            <td data-etiqueta="Revisión">${etiquetaRevision(fila.revision?.estado)}</td>
            <td data-etiqueta="Estado">${fila.semaforo || "sin clasificar"}</td>
          </tr>`)}</tbody>
        </table>
      </div>
    </section>`}
  `;
}

function TarjetaExterna({ prueba, alActualizarRevision }) {
  const unidades = unidadesOcr(prueba);
  const lecturaSugerida = () => {
    const mejor = unidades.find((t) => normalizarCodigoVista(textoUnidad(t))
      === prueba.mejor_candidato);
    return mejor || unidades.find((t) => /\d/.test(textoUnidad(t))) || unidades[0] || null;
  };
  const [unidadId, setUnidadId] = useState(() => lecturaSugerida()?.unidad_id || "");
  const [textoCorrecto, setTextoCorrecto] = useState(
    prueba.tipo === "codigo" ? (prueba.esperado || "") : textoVisible(lecturaSugerida()));
  const [guardando, setGuardando] = useState(false);
  const [respuesta, setRespuesta] = useState(null);
  const [modoEdicion, setModoEdicion] = useState(false);
  const seleccionada = unidades.find((u) => u.unidad_id === unidadId) || unidades[0];
  const completada = prueba.revision?.estado === "completada";
  useEffect(() => {
    const sugerida = lecturaSugerida();
    setUnidadId(sugerida?.unidad_id || "");
    setTextoCorrecto(prueba.tipo === "codigo" ? (prueba.esperado || "") : textoVisible(sugerida));
    setRespuesta(null);
    if (prueba.revision?.estado === "completada") setModoEdicion(false);
  }, [prueba.mejor_candidato, prueba.esperado, prueba.revision?.estado]);

  function seleccionar(unidad) {
    setUnidadId(unidad.unidad_id);
    setTextoCorrecto(textoVisible(unidad));
    setModoEdicion(true);
  }

  async function corregir(e) {
    e.preventDefault();
    setGuardando(true);
    setRespuesta(null);
    try {
      const resultado = await enviarJSON("/api/externas/correcciones", {
        prueba_id: prueba.id, texto_ocr: textoUnidad(seleccionada),
        texto_correcto: textoCorrecto, bbox: seleccionada?.bbox || null,
      });
      setRespuesta({ ok: true, resultado });
      await alActualizarRevision();
    } catch (error) {
      setRespuesta({ ok: false, mensaje: error.message });
    } finally {
      setGuardando(false);
    }
  }
  async function cambiarRevision(cambios) {
    setGuardando(true);
    setRespuesta(null);
    try {
      await enviarJSON("/api/revisiones", { tipo: "externa", item_id: prueba.id, ...cambios });
      setRespuesta({ ok: true, revision: true });
      await alActualizarRevision();
    } catch (error) {
      setRespuesta({ ok: false, mensaje: error.message });
    } finally {
      setGuardando(false);
    }
  }
  async function rotar(grados) {
    setGuardando(true);
    setRespuesta(null);
    try {
      const resultado = await enviarJSON("/api/aprendizaje/rotaciones", {
        tipo: "externa", prueba_id: prueba.id, imagen_id: null, grados,
      });
      setRespuesta({ ok: true, rotacion: true, resultado });
      await alActualizarRevision();
    } catch (error) {
      setRespuesta({ ok: false, mensaje: error.message });
    } finally {
      setGuardando(false);
    }
  }
  async function atenderAlerta(alerta) {
    setGuardando(true);
    try {
      await enviarJSON("/api/alertas/atender", {
        tipo: "externa", item_id: prueba.id, alerta_id: alerta.id,
      });
      await alActualizarRevision();
    } catch (error) {
      setRespuesta({ ok: false, mensaje: error.message });
    } finally {
      setGuardando(false);
    }
  }
  const preferida = Number(prueba.rotacion_manual_preferida_grados) || 0;
  const base = Number(prueba.orientacion_texto_base_grados ?? prueba.orientacion_base_grados) || 0;
  const ajuste = Number(prueba.deskew_texto_aplicado_grados ?? prueba.deskew_aplicado_grados) || 0;

  return html`<article class="tarjeta tarjeta-externa">
    <div class="externa-cabecera">
      <div><p class="sobrelinea">${prueba.imagen} · ${prueba.tipo}</p>
        <h3>${prueba.tipo === "codigo" ? prueba.esperado : "Texto de escena"}</h3></div>
      <span class=${`chip revision-${prueba.revision?.estado || "por_revisar"}`}>
        <span class="punto"></span>${etiquetaRevision(prueba.revision?.estado)}
      </span>
    </div>
    <div class="imagen-marco externa-imagen">
      <img src=${prueba.ruta_api_visual || prueba.ruta_api}
        alt=${`Placa grabada ${prueba.imagen}`} loading="lazy" />
    </div>
    <div class="estado-rotacion">
      ${(base !== 0 || Math.abs(ajuste) >= 0.05)
        ? html`<span class="chip rotacion-auto">✓ Enderezada automáticamente: ${base}°${Math.abs(ajuste) >= 0.05 ? ` + ajuste ${ajuste.toFixed(1)}°` : ""}</span>`
        : html`<span class="chip neutro">Orientación automática: sin cambio</span>`}
      ${preferida !== 0 && html`<span class="chip rotacion-manual">Rotación manual: ${preferida}°</span>`}
      ${prueba.rotacion_pendiente && html`<span class="subtitulo-seccion">Se usará en el próximo OCR.</span>`}
    </div>
    ${!completada && html`<div class="controles-rotacion">
      <button type="button" class="boton boton-compacto" disabled=${guardando}
        onClick=${() => rotar((preferida + 270) % 360)}>↶ 90°</button>
      <button type="button" class="boton boton-compacto" disabled=${guardando}
        onClick=${() => rotar((preferida + 90) % 360)}>↷ 90°</button>
      <button type="button" class="boton boton-compacto" disabled=${guardando || preferida === 0}
        onClick=${() => rotar(0)}>Restablecer</button>
    </div>`}
    <dl class="ficha ficha-externa">
      <dt>Esperado</dt><dd class="mono"><strong>${prueba.tipo === "codigo" ? prueba.esperado
        : `${(prueba.encontrados || []).length} de ${(prueba.esperados || []).length} fragmentos`}</strong></dd>
      <dt>Resultado</dt><dd>${prueba.tipo === "codigo" ? fmtPct(prueba.similitud_caracteres * 100)
        : `${fmtPct((prueba.cobertura || 0) * 100)} de cobertura`}</dd>
      ${prueba.tipo === "codigo" && prueba.similitud_caracteres_bruta !== undefined && html`
        <dt>OCR bruto</dt><dd>${fmtPct(prueba.similitud_caracteres_bruta * 100)}
          ${prueba.correccion_memorizada ? " · mejorado con memoria confirmada" : ""}</dd>`}
      <dt>Detección</dt><dd>${prueba.variante || "—"} · ${prueba.orientacion_grados || 0}° · ${prueba.intentos} intentos</dd>
      <dt>Tiempo</dt><dd>${fmtDuracion(prueba.segundos)}</dd>
    </dl>
    <div class="texto-detectado">
      <div class="progreso-titulo"><strong>Texto completo detectado</strong>
        <span class="subtitulo-seccion">${(prueba.lineas_texto || []).length} renglones</span></div>
      <pre>${prueba.texto_completo || "Sin texto legible"}</pre>
    </div>
    ${prueba.tipo === "texto" && html`<ul class="fragmentos-esperados">
      ${(prueba.esperados || []).map((fragmento) => {
        const ok = (prueba.encontrados || []).includes(fragmento);
        return html`<li key=${fragmento} class=${ok ? "encontrado" : "faltante"}>
          <span aria-hidden="true">${ok ? "✓" : "○"}</span><span>${fragmento}</span>
        </li>`;
      })}
    </ul>`}
    ${(prueba.alertas || []).map((alerta, i) => html`<div key=${`${alerta.codigo}-${i}`}
      class=${`aviso alerta-${alerta.nivel || "advertencia"}`}>
      <span class="icono-alerta" title=${alerta.mensaje} aria-label=${alerta.mensaje}>⚠</span>
      <strong>${alerta.codigo?.replaceAll("_", " ") || "ADVERTENCIA"}:</strong> ${alerta.mensaje}
      <button type="button" class="boton boton-compacto" onClick=${() => atenderAlerta(alerta)}>
        Marcar atendido</button></div>`)}
    <ul class="tokens-lista lecturas-externas">${unidades.length
      ? unidades.filter((u) => u.tipo_unidad !== "bloque completo").map((token) => html`
        <li key=${token.unidad_id} class=${`token-fila ${unidadConfirmada(token, prueba.correcciones) ? "token-confirmado" : ""}`}>
          <button type="button" class="token-texto-boton mono" disabled=${completada}
            onClick=${() => seleccionar(token)} title="Usar esta lectura en la corrección">
            ${textoVisible(token)}</button>
          <span class="conf">${token.confianza == null ? "—" : `${(token.confianza * 100).toFixed(1)}%`}</span>
        </li>`)
      : html`<li class="subtitulo-seccion">No se detectaron lecturas.</li>`}
    </ul>
    ${modoEdicion && !completada && unidades.length > 0 && html`
      <form class="formulario-correccion formulario-externo" onSubmit=${corregir}>
        <label>Lectura OCR
          <select class="campo" value=${seleccionada?.unidad_id || ""} onChange=${(e) => {
            const unidad = unidades.find((u) => u.unidad_id === e.target.value);
            if (unidad) seleccionar(unidad);
          }}>
            ${unidades.map((token) => html`<option key=${token.unidad_id} value=${token.unidad_id}>
              ${token.tipo_unidad}: ${textoVisible(token).replaceAll("\n", " ↵ ")}</option>`)}
          </select>
        </label>
        <label>Corrección confirmada
          <textarea class="campo mono campo-texto" value=${textoCorrecto} required maxLength=${4096}
            rows=${3} onInput=${(e) => setTextoCorrecto(e.target.value)}></textarea>
        </label>
        <button class="boton boton-primario" disabled=${guardando || !textoCorrecto.trim()}>
          ${guardando ? "Entrenando…" : "Confirmar y entrenar"}
        </button>
      </form>`}
    ${respuesta?.ok && html`<div class="aviso">${respuesta.revision
      ? "Estado de revisión actualizado."
      : respuesta.rotacion ? respuesta.resultado.mensaje
      : html`<strong>Corrección guardada y memorizada para esta imagen.</strong>
        ${respuesta.resultado.entrenamiento?.promovido
          ? " También se activó como regla global para imágenes nuevas."
          : " Se reutilizará en esta imagen; todavía no se generaliza a imágenes nuevas hasta reunir más evidencia."}`}</div>`}
    ${respuesta && !respuesta.ok && html`<div class="mensaje-error">${respuesta.mensaje}</div>`}
    <div class="acciones-revision">
      ${!completada && html`<button class="boton" disabled=${guardando}
        onClick=${() => setModoEdicion((activo) => !activo)}>
        ${modoEdicion ? "Cerrar edición" : "Editar texto"}</button>`}
      <button class="boton" disabled=${guardando} onClick=${() => cambiarRevision({
        estado: completada ? "parcial" : "completada" })}>
        ${completada ? "Reabrir revisión" : "Marcar completada"}
      </button>
      <button class="boton boton-peligro" disabled=${guardando}
        onClick=${() => cambiarRevision({ oculto: !prueba.revision?.oculto })}>
        ${prueba.revision?.oculto ? "Restaurar en listado" : "Quitar del listado"}
      </button>
    </div>
  </article>`;
}

function VistaExternas({ caso }) {
  const [mostrarOcultas, setMostrarOcultas] = useState(false);
  const rutaExternas = `/api/externas?incluir_ocultos=${mostrarOcultas}`;
  const [datos, setDatos, errorCarga] = useApi(rutaExternas, [mostrarOcultas]);
  const [evaluando, setEvaluando] = useState(false);
  const [errorEvaluacion, setErrorEvaluacion] = useState(null);

  async function reevaluar() {
    setEvaluando(true);
    setErrorEvaluacion(null);
    try {
      setDatos(await enviarJSON("/api/externas/evaluar", {}));
    } catch (error) {
      setErrorEvaluacion(error.message);
    } finally {
      setEvaluando(false);
    }
  }
  const refrescarExternas = useCallback(async () => {
    setDatos(await pedirJSON(rutaExternas));
  }, [rutaExternas]);

  if (datos === undefined) return html`<div class="tarjeta" style=${{ marginTop: 20 }}><div class="esqueleto"></div></div>`;
  if (errorCarga) return html`<${EstadoError} mensaje="No fue posible cargar las pruebas complejas." />`;
  const resultados = (datos?.resultados || []).filter((prueba) => !caso || prueba.id === caso);
  return html`
    ${caso && html`<a class="volver volver-superior" href="#/tabla">← Volver al listado</a>`}
    <section class="carga-cabecera">
      <div>
        <p class="sobrelinea">BANCO DE ESTRÉS OCR</p>
        <h2>${caso ? "Detalle de prueba compleja" : "Pruebas complejas y externas"}</h2>
        <p>Placas grabadas, bajo contraste y caracteres ambiguos para inspeccionar y corregir el reconocimiento.</p>
      </div>
      ${!caso && html`<button class="boton boton-primario" disabled=${evaluando} onClick=${reevaluar}>
        ${evaluando ? "Evaluando imágenes…" : "Volver a ejecutar las pruebas"}
      </button>`}
    </section>
    ${!caso && html`<label class="control-ocultos"><input type="checkbox" checked=${mostrarOcultas}
      onChange=${(e) => setMostrarOcultas(e.target.checked)} /> Mostrar elementos quitados</label>
    `}
    ${errorEvaluacion && html`<div class="mensaje-error">${errorEvaluacion}</div>`}
    ${!caso && html`<div class="rejilla-kpi">
      <${Kpi} etiqueta="OCR bruto exacto" valor=${datos.exactitud_ocr_bruta === null || datos.exactitud_ocr_bruta === undefined
        ? "—" : fmtPct(datos.exactitud_ocr_bruta * 100)}
        sub=${`${datos.exactos_ocr_brutos || 0} de ${datos.casos_codigo || 0} sin memoria`} />
      <${Kpi} etiqueta="Resultado efectivo" valor=${datos.exactitud === null
        ? "—" : fmtPct(datos.exactitud * 100)}
        sub=${`${datos.exactos || 0} de ${datos.casos_codigo || 0} con correcciones confirmadas`} />
      <${Kpi} etiqueta="Cobertura de texto completo" valor=${datos.cobertura_texto === null
        ? "—" : fmtPct(datos.cobertura_texto * 100)}
        sub=${`${datos.fragmentos_texto_detectados || 0} de ${datos.fragmentos_texto || 0} fragmentos`} />
      <${Kpi} etiqueta="Última evaluación" valor=${resultados.length ? `${resultados.length} imágenes` : "Pendiente"}
        sub=${fmtFecha(datos.generado_en)} />
    </div>`}
    ${resultados.length ? html`<div class="rejilla-externas">
      ${resultados.map((prueba) => html`<${TarjetaExterna} key=${prueba.id} prueba=${prueba}
        alActualizarRevision=${refrescarExternas} />`)}
    </div>` : html`<div class="estado-vacio">
      <div class="icono">🧪</div><h2>Las imágenes están listas para evaluarse</h2>
      <p>Usa “Volver a ejecutar las pruebas” para generar sus lecturas y métricas.</p>
    </div>`}
    ${!caso && html`<p class="subtitulo-seccion pie-datos">Fuentes: ${(datos.fuentes || []).map((fuente, i) => html`
      <span key=${fuente.url}>${i ? " · " : ""}<a href=${fuente.url} target="_blank" rel="noreferrer">
        ${fuente.nombre}</a> (${fuente.licencia})</span>`)}</p>`}
  `;
}

function VistaTabla() {
  const [consulta, setConsulta] = useState("");
  const [estado, setEstado] = useState("");
  const [pagina, setPagina] = useState(0);
  const [mostrarOcultos, setMostrarOcultos] = useState(false);
  const consultaEstable = useDebounce(consulta);
  const limite = 100;
  const [config, , errorConfig] = useApi("/api/config");
  const rutaFilas = `/api/pruebas?q=${encodeURIComponent(consultaEstable)}&estado=${encodeURIComponent(estado)}&limit=${limite}&offset=${pagina * limite}&incluir_ocultos=${mostrarOcultos}`;
  const [filas, setFilas, errorFilas] = useApi(rutaFilas,
    [consultaEstable, estado, pagina, mostrarOcultos]);
  const colores = (config && config.colores) || {};
  const refTabla = useRef(null);

  const alPulsarTecla = useCallback((ev) => {
    if (ev.key !== "ArrowDown" && ev.key !== "ArrowUp" && ev.key !== "Enter") return;
    if (["SELECT", "BUTTON", "INPUT"].includes(ev.target.tagName)) return;
    const filasDOM = [...refTabla.current.querySelectorAll("tbody tr")];
    const idx = filasDOM.indexOf(document.activeElement);
    if (ev.key === "Enter" && idx >= 0) { filasDOM[idx].click(); return; }
    ev.preventDefault();
    const siguiente = filasDOM[idx + (ev.key === "ArrowDown" ? 1 : -1)];
    if (siguiente) siguiente.focus();
    else if (ev.key === "ArrowUp") refTabla.current.querySelector("input")?.focus();
  }, []);

  if (config === undefined) return html`<${CargandoKpis} />`;
  if (filas === undefined) return html`<div class="tarjeta"><div class="esqueleto"></div></div>`;
  if (errorConfig || errorFilas) return html`<${EstadoError} />`;
  if (filas === null) return html`<${EstadoVacio} />`;

  const celda = (valor, clase) =>
    valor === null || valor === undefined || valor === "" ? "—" : valor;

  async function cambiarRevision(evento, fila, cambios) {
    evento.stopPropagation();
    try {
      await enviarJSON("/api/revisiones", {
        tipo: fila.origen === "externa" ? "externa" : "carpeta",
        item_id: fila.id, ...cambios,
      });
      setFilas(await pedirJSON(rutaFilas));
    } catch (error) {
      alert(`No fue posible actualizar la revisión: ${error.message}`);
    }
  }

  return html`
    <div ref=${refTabla} onKeyDown=${alPulsarTecla}>
    <div class="barra-filtros">
      <input class="campo" type="search" placeholder="Buscar por identificador o nomenclatura…"
        aria-label="Buscar en la tabla"
        value=${consulta} onInput=${(e) => { setConsulta(e.target.value); setPagina(0); }} />
      <select class="campo" aria-label="Filtrar por estado" value=${estado}
        onChange=${(e) => { setEstado(e.target.value); setPagina(0); }}>
        <option value="">Todas las revisiones</option>
        <option value="por_revisar">Por revisar</option>
        <option value="parcial">Revisión parcial</option>
        <option value="casi_listo">Casi listo</option>
        <option value="completada">Completadas</option>
      </select>
      <label class="control-ocultos"><input type="checkbox" checked=${mostrarOcultos}
        onChange=${(e) => { setMostrarOcultos(e.target.checked); setPagina(0); }} /> Mostrar quitados</label>
      <span class="subtitulo-seccion" style=${{ margin: "auto 0 auto auto" }}>
        ${filas.total} ${filas.total === 1 ? "elemento" : "elementos"}</span>
    </div>

    <div class="contenedor-tabla">
      <table aria-label="Bandeja unificada de revisión">
        <thead><tr>
          <th>Identificador</th><th>Grupo</th><th>Origen</th><th>Resultado</th>
          <th>QR</th><th>Estado</th><th>Revisión</th><th>Acciones</th>
        </tr></thead>
        <tbody>
          ${filas.items.map((f) => html`<tr key=${f.nombre} tabIndex=${0}
            aria-label=${`Abrir detalle de ${f.identificador || f.nombre}`}
            onClick=${() => { location.hash = f.enlace || `#/detalle/${encodeURIComponent(f.id)}`; }}>
            <td data-etiqueta="Identificador"><strong>${f.identificador || f.nombre}</strong></td>
            <td data-etiqueta="Grupo">${celda(f.lote)}</td>
            <td data-etiqueta="Origen">${f.origen === "externa" ? "Prueba compleja" : "Carpeta"}</td>
            <td data-etiqueta="Resultado">${f.resultado}
              ${(f.alertas || []).length > 0 && html`<span class="indicador-alerta"
                title=${f.alertas.map((a) => a.mensaje).join("\n")}
                aria-label=${`Advertencias: ${f.alertas.map((a) => a.mensaje).join("; ")}`}>
                ⚠ ${f.alertas.length}</span>`}</td>
            <td data-etiqueta="QR">${f.qr_detectado ? "Sí" : "No"}</td>
            <td data-etiqueta="Estado"><${ChipSemaforo} color=${f.semaforo} colores=${colores}>
              ${f.semaforo || "sin clasificar"}</${ChipSemaforo}></td>
            <td data-etiqueta="Revisión"><span class=${`revision-chip revision-${f.revision.estado}`}>
              ${etiquetaRevision(f.revision.estado)}</span></td>
            <td data-etiqueta="Acciones"><div class="acciones-tabla">
              <button class="boton boton-compacto" onClick=${(e) => cambiarRevision(e, f, {
                estado: f.revision.estado === "completada" ? "parcial" : "completada" })}>
                ${f.revision.estado === "completada" ? "Reabrir" : "Completar"}</button>
              <button class="boton boton-compacto boton-peligro" onClick=${(e) => cambiarRevision(e, f, {
                oculto: !f.revision.oculto })}>
                ${f.revision.oculto ? "Restaurar" : "Quitar"}</button>
            </div></td>
          </tr>`)}
        </tbody>
      </table>
    </div>
    ${filas.total > limite && html`<div class="paginacion" aria-label="Paginación del listado">
      <button class="boton" disabled=${pagina === 0} onClick=${() => setPagina((p) => p - 1)}>← Anterior</button>
      <span>Página ${pagina + 1} de ${Math.ceil(filas.total / limite)}</span>
      <button class="boton" disabled=${(pagina + 1) * limite >= filas.total}
        onClick=${() => setPagina((p) => p + 1)}>Siguiente →</button>
    </div>`}
    ${!filas.items.length && html`<div class="estado-vacio" style=${{ marginTop: 16 }}>
      <div class="icono">🔍</div><h2 style=${{ margin: 0 }}>Sin resultados para el filtro actual</h2>
    </div>`}
    <p class="subtitulo-seccion" style=${{ marginTop: 10 }}>
      Navegación por teclado: <kbd>↑</kbd>/<kbd>↓</kbd> mueve entre filas, <kbd>Enter</kbd> abre el detalle.</p>
    </div>
  `;
}

function SelectorRegion({ item, valor, onChange, onSelectText }) {
  const marcoRef = useRef(null);
  const inicioRef = useRef(null);
  const [vistaPrevia, setVistaPrevia] = useState(null);
  const dimensiones = item?.resultado_ocr?.dimensiones || [1, 1];
  const [anchoImagen, altoImagen] = dimensiones;
  const limitar = (v, minimo, maximo) => Math.max(minimo, Math.min(maximo, v));
  function punto(evento) {
    const rect = marcoRef.current.getBoundingClientRect();
    return {
      x: limitar((evento.clientX - rect.left) / rect.width * anchoImagen, 0, anchoImagen),
      y: limitar((evento.clientY - rect.top) / rect.height * altoImagen, 0, altoImagen),
    };
  }
  function caja(desde, hasta) {
    const x = Math.round(Math.min(desde.x, hasta.x));
    const y = Math.round(Math.min(desde.y, hasta.y));
    return [x, y, Math.round(Math.abs(hasta.x - desde.x)), Math.round(Math.abs(hasta.y - desde.y))];
  }
  function iniciar(evento) {
    if (!item) return;
    evento.preventDefault();
    evento.currentTarget.setPointerCapture(evento.pointerId);
    inicioRef.current = punto(evento);
    setVistaPrevia([inicioRef.current.x, inicioRef.current.y, 0, 0]);
  }
  function mover(evento) {
    if (!inicioRef.current) return;
    setVistaPrevia(caja(inicioRef.current, punto(evento)));
  }
  function terminar(evento) {
    if (!inicioRef.current) return;
    const seleccion = caja(inicioRef.current, punto(evento));
    inicioRef.current = null;
    setVistaPrevia(null);
    if (seleccion[2] >= 2 && seleccion[3] >= 2) onChange(seleccion);
  }
  function estiloCaja(bbox) {
    return {
      left: `${bbox[0] / anchoImagen * 100}%`, top: `${bbox[1] / altoImagen * 100}%`,
      width: `${bbox[2] / anchoImagen * 100}%`, height: `${bbox[3] / altoImagen * 100}%`,
    };
  }
  const ocr = item?.resultado_ocr || {};
  const detectadas = ocr.lineas_texto || ocr.tokens || [];
  return html`<div>
    <div class="selector-region" ref=${marcoRef} onPointerDown=${iniciar}
      onPointerMove=${mover} onPointerUp=${terminar} onPointerCancel=${terminar}
      role="img" aria-label="Arrastra para seleccionar la zona que contiene texto">
      <img src=${item?.ruta_api_orientada || item?.ruta_api}
        alt=${`Seleccionar texto en ${item?.nombre || "imagen"}`} draggable="false" />
      ${detectadas.filter((linea) => linea.bbox).map((linea, i) => html`
        <button type="button" key=${`ocr-${i}`} class="caja-region caja-ocr"
          style=${estiloCaja(linea.bbox)} title=${`Usar OCR: ${textoVisible(linea)}`}
          onPointerDown=${(evento) => evento.stopPropagation()}
          onClick=${() => onSelectText?.(linea)} />`)}
      ${(item?.anotaciones || []).map((anotacion) => html`
        <span key=${`manual-${anotacion.id}`} class="caja-region caja-manual"
          style=${estiloCaja(anotacion.bbox)} title=${`Manual: ${anotacion.texto_correcto}`} />`)}
      ${(vistaPrevia || valor) && html`<span class="caja-region caja-seleccion"
        style=${estiloCaja(vistaPrevia || valor)} />`}
    </div>
    <div class="leyenda-regiones">
      <span><i class="leyenda-caja ocr"></i>Detectado por OCR</span>
      <span><i class="leyenda-caja manual"></i>Confirmado manualmente</span>
      <span><i class="leyenda-caja seleccion"></i>Selección actual</span>
    </div>
  </div>`;
}

function PanelImagen({ titulo, item, vacio, onSelectText, edicionActiva, rotacionActiva, onRotate }) {
  const ocr = item?.resultado_ocr || {};
  const base = Number(ocr.orientacion_texto_base_grados ?? ocr.orientacion_base_grados) || 0;
  const ajuste = Number(ocr.deskew_texto_aplicado_grados ?? ocr.deskew_aplicado_grados) || 0;
  const preferida = Number(item?.rotacion_manual_preferida_grados) || 0;
  const enderezada = base !== 0 || Math.abs(ajuste) >= 0.05;
  return html`<div class="tarjeta">
    <h3 class="titulo-seccion" style=${{ marginTop: 0 }}>${titulo}</h3>
    ${item
      ? html`<div class="imagen-marco">
          <img src=${item.ruta_api_visual || item.ruta_api} alt=${`Imagen: ${item.ruta}`} loading="lazy" />
        </div>
        <div class="estado-rotacion">
          ${enderezada ? html`<span class="chip rotacion-auto">✓ Enderezada automáticamente:
            ${base}°${Math.abs(ajuste) >= 0.05 ? ` + ajuste ${ajuste.toFixed(1)}°` : ""}</span>`
            : html`<span class="chip neutro">Orientación automática: sin cambio</span>`}
          ${preferida !== 0 && html`<span class="chip rotacion-manual">Rotación manual: ${preferida}°</span>`}
          ${item.rotacion_pendiente && html`<span class="subtitulo-seccion">
            Se usará en el próximo OCR; la vista ya está girada.</span>`}
        </div>
        ${rotacionActiva && html`<div class="controles-rotacion" aria-label="Rotar imagen">
          <button type="button" class="boton boton-compacto"
            onClick=${() => onRotate?.(item, (preferida + 270) % 360)}>↶ 90°</button>
          <button type="button" class="boton boton-compacto"
            onClick=${() => onRotate?.(item, (preferida + 90) % 360)}>↷ 90°</button>
          <button type="button" class="boton boton-compacto" disabled=${preferida === 0}
            onClick=${() => onRotate?.(item, 0)}>Restablecer</button>
        </div>`}
        <div class="texto-detectado">
          <div class="progreso-titulo"><strong>Texto completo detectado</strong>
            <span class="subtitulo-seccion">${(ocr.lineas_texto || []).length} renglones</span></div>
          <pre>${ocr.texto_completo || "Sin texto legible"}</pre>
        </div>
        <ul class="tokens-lista">
          ${unidadesOcr(ocr).filter((u) => u.tipo_unidad !== "bloque completo").map((t) => html`
          <li key=${t.unidad_id} class=${`token-fila ${unidadConfirmada(t, item.correcciones) ? "token-confirmado" : ""}`}>
            <button type="button" class="token-texto-boton mono" disabled=${!edicionActiva}
              title=${edicionActiva ? "Usar este texto en la corrección" : "Activa la edición para corregir"}
              onClick=${() => onSelectText?.(item, t)}>${textoVisible(t)}</button>
            <span class="conf">${t.confianza == null ? "—" : `${(t.confianza * 100).toFixed(1)}%`}</span>
          </li>`)}
        </ul>
        ${(item.anotaciones || []).length > 0 && html`<div class="anotaciones-manuales">
          <strong>Texto añadido manualmente</strong>
          ${(item.anotaciones || []).map((a) => html`<div key=${a.id} class="anotacion-manual">
            <span class="mono">${a.texto_correcto}</span>
            <small class="mono">región ${a.bbox.join(", ")}</small>
          </div>`)}
        </div>`}`
      : html`<p style=${{ color: "var(--texto-3)" }}>${vacio}</p>`}
  </div>`;
}

function VistaDetalle({ nombre }) {
  const [detalle, setDetalle, errorDetalle] = useApi(`/api/pruebas/${encodeURIComponent(nombre)}`, [nombre]);
  const [config, , errorConfig] = useApi("/api/config");
  const [aprendizaje, setAprendizaje] = useApi("/api/aprendizaje", [nombre]);
  const [unidadId, setUnidadId] = useState("");
  const [textoCorrecto, setTextoCorrecto] = useState("");
  const [imagenId, setImagenId] = useState("");
  const [modoEdicion, setModoEdicion] = useState(false);
  const [guardandoCorreccion, setGuardandoCorreccion] = useState(false);
  const [resultadoCorreccion, setResultadoCorreccion] = useState(null);
  const [region, setRegion] = useState(null);
  const [textoRegion, setTextoRegion] = useState("");
  const [guardandoRegion, setGuardandoRegion] = useState(false);
  const [resultadoRegion, setResultadoRegion] = useState(null);
  useEffect(() => {
    const imagenes = detalle?.imagenes?.length ? detalle.imagenes
      : [detalle?.etiqueta, detalle?.referencia].filter(Boolean);
    const primeraImagen = imagenes[0];
    const ocr = primeraImagen?.resultado_ocr || {};
    const unidades = unidadesOcr(ocr);
    const primero = unidades[0];
    const valor = textoVisible(primero);
    setImagenId(primeraImagen?.id || "");
    setUnidadId(primero?.unidad_id || "");
    setTextoCorrecto(valor);
    setResultadoCorreccion(null);
    setRegion(null);
    setTextoRegion("");
    setResultadoRegion(null);
    setModoEdicion(false);
  }, [detalle?.id]);
  const colores = (config && config.colores) || {};
  if (detalle === undefined || config === undefined) {
    return html`<div class="tarjeta" style=${{ marginTop: 16 }}><div class="esqueleto"></div></div>`;
  }
  if (errorDetalle || errorConfig) return html`<${EstadoError} mensaje="No fue posible abrir este detalle." />`;
  if (!detalle) return html`<${EstadoVacio} />`;
  const comp = detalle.comparacion;
  const imagenesDetalle = detalle.imagenes?.length ? detalle.imagenes
    : [detalle.etiqueta, detalle.referencia].filter(Boolean);
  const imagenSeleccionada = imagenesDetalle.find((imagen) => imagen.id === imagenId)
    || imagenesDetalle[0];
  const ocrSeleccionado = imagenSeleccionada?.resultado_ocr || {};
  const unidadesCorregibles = unidadesOcr(ocrSeleccionado);
  const unidadSeleccionada = unidadesCorregibles.find((unidad) => unidad.unidad_id === unidadId)
    || unidadesCorregibles[0];
  const revisionCompletada = detalle.revision?.estado === "completada";

  function cambiarImagen(nuevoId) {
    setImagenId(nuevoId);
    const imagen = imagenesDetalle.find((item) => item.id === nuevoId);
    const ocr = imagen?.resultado_ocr || {};
    const primera = unidadesOcr(ocr)[0];
    const valor = textoVisible(primera);
    setUnidadId(primera?.unidad_id || "");
    setTextoCorrecto(valor);
    setResultadoCorreccion(null);
    setRegion(null);
    setTextoRegion("");
    setResultadoRegion(null);
  }
  function seleccionarUnidad(imagen, unidad) {
    const candidatas = unidadesOcr(imagen?.resultado_ocr || {});
    const exacta = candidatas.find((item) => firmaUnidad(item) === firmaUnidad(unidad)) || candidatas[0];
    setImagenId(imagen?.id || "");
    setUnidadId(exacta?.unidad_id || "");
    setTextoCorrecto(textoVisible(exacta));
    setModoEdicion(true);
    setResultadoCorreccion(null);
  }
  async function confirmarCorreccion(e) {
    e.preventDefault();
    setGuardandoCorreccion(true);
    setResultadoCorreccion(null);
    try {
      const resultado = await enviarJSON("/api/aprendizaje/correcciones", {
        prueba_id: detalle.id, campo: "etiqueta", imagen_id: imagenSeleccionada?.id,
        texto_ocr: textoUnidad(unidadSeleccionada),
        texto_correcto: textoCorrecto,
        bbox: unidadSeleccionada?.bbox || null,
      });
      setResultadoCorreccion({ ok: true, resultado });
      const actualizado = await pedirJSON(`/api/pruebas/${encodeURIComponent(nombre)}`);
      setDetalle(actualizado);
      setAprendizaje(await pedirJSON("/api/aprendizaje"));
    } catch (error) {
      setResultadoCorreccion({ ok: false, mensaje: error.message });
    } finally {
      setGuardandoCorreccion(false);
    }
  }
  async function cambiarRevision(estado) {
    try {
      await enviarJSON("/api/revisiones", { tipo: "carpeta", item_id: detalle.id, estado });
      const actualizado = await pedirJSON(`/api/pruebas/${encodeURIComponent(nombre)}`);
      setDetalle(actualizado);
      setModoEdicion(false);
    } catch (error) {
      setResultadoCorreccion({ ok: false, mensaje: error.message });
    }
  }
  async function confirmarRegion(e) {
    e.preventDefault();
    if (!region) return;
    setGuardandoRegion(true);
    setResultadoRegion(null);
    try {
      const resultado = await enviarJSON("/api/aprendizaje/regiones", {
        prueba_id: detalle.id, imagen_id: imagenSeleccionada?.id,
        bbox: region, texto_correcto: textoRegion,
      });
      setResultadoRegion({ ok: true, resultado });
      const actualizado = await pedirJSON(`/api/pruebas/${encodeURIComponent(nombre)}`);
      setDetalle(actualizado);
      setRegion(null);
      setTextoRegion("");
    } catch (error) {
      setResultadoRegion({ ok: false, mensaje: error.message });
    } finally {
      setGuardandoRegion(false);
    }
  }
  async function rotarImagen(imagen, grados) {
    setResultadoCorreccion(null);
    try {
      const resultado = await enviarJSON("/api/aprendizaje/rotaciones", {
        tipo: "carpeta", prueba_id: detalle.id, imagen_id: imagen.id, grados,
      });
      setResultadoCorreccion({ ok: true, rotacion: true, resultado });
      setDetalle(await pedirJSON(`/api/pruebas/${encodeURIComponent(nombre)}`));
      setAprendizaje(await pedirJSON("/api/aprendizaje"));
    } catch (error) {
      setResultadoCorreccion({ ok: false, mensaje: error.message });
    }
  }
  async function atenderAlerta(alerta) {
    try {
      await enviarJSON("/api/alertas/atender", {
        tipo: "carpeta", item_id: detalle.id, alerta_id: alerta.id,
      });
      setDetalle(await pedirJSON(`/api/pruebas/${encodeURIComponent(nombre)}`));
    } catch (error) {
      setResultadoCorreccion({ ok: false, mensaje: error.message });
    }
  }
  const historialAprendizaje = imagenesDetalle.flatMap((imagen) => [
    ...(imagen.correcciones || []).map((item) => ({
      id: `c-${item.id}`, tipo: "Corrección OCR", imagen: imagen.nombre,
      original: item.texto_ocr, correcto: item.texto_correcto, bbox: item.bbox,
    })),
    ...(imagen.anotaciones || []).map((item) => ({
      id: `a-${item.id}`, tipo: "Texto omitido", imagen: imagen.nombre,
      original: null, correcto: item.texto_correcto, bbox: item.bbox,
    })),
  ]);
  return html`
    <a class="volver volver-superior" href="#/tabla">← Volver al listado</a>
    <div style=${{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginTop: 18 }}>
      <h2 style=${{ margin: 0, fontSize: 20 }}>${detalle.identificador || detalle.nombre}</h2>
      <${ChipSemaforo} color=${detalle.semaforo} colores=${colores}>
        ${detalle.semaforo || "sin clasificar"}</${ChipSemaforo}>
      <span class=${`revision-chip revision-${detalle.revision?.estado || "por_revisar"}`}>
        ${etiquetaRevision(detalle.revision?.estado)}</span>
      <span class="espacio"></span>
      ${!revisionCompletada && html`<button class="boton" onClick=${() => setModoEdicion((v) => !v)}>
        ${modoEdicion ? "Cerrar edición" : "Editar y revisar"}</button>`}
      <button class="boton boton-primario" onClick=${() => cambiarRevision(
        revisionCompletada ? "parcial" : "completada")}>
        ${revisionCompletada ? "Reabrir revisión" : "Completar revisión"}</button>
    </div>
    <p class="subtitulo-seccion mono" style=${{ wordBreak: "break-all" }}>${detalle.ruta_mostrada || detalle.ruta}</p>

    <div class="tarjeta" style=${{ marginTop: 12 }}>
      <dl class="ficha">
        <dt>Comparación</dt><dd><strong>${comp.resultado}</strong>${comp.ratio !== null && comp.ratio !== undefined
          ? ` (ratio ${comp.ratio})` : ""}</dd>
        <dt>Confianza OCR</dt><dd>${fmtPct(detalle.confianza_ocr_pct)}</dd>
        <dt>QR detectado</dt><dd>${detalle.qr_detectado ? "Sí" : "No"}</dd>
        <dt>Conforme (Fase 0)</dt><dd>${detalle.es_conforme ? "Sí" : `No (${detalle.anomalia_fase0})`}</dd>
        ${detalle.etiqueta && html`<dt>Motor OCR</dt><dd>${detalle.etiqueta.resultado_ocr.motor || "—"}</dd>`}
        ${(detalle.observaciones || []).length > 0 &&
          html`<dt>Observaciones</dt><dd>${detalle.observaciones.join("; ")}</dd>`}
      </dl>
    </div>

    ${comp.faltantes && comp.faltantes.length > 0 && html`
      <div class="aviso">Tokens de la etiqueta NO encontrados en la referencia:
        ${comp.faltantes.map((t) => html`<code key=${t} class="mono">${t}</code>`)} — revisar.</div>`}

    ${(detalle.alertas || []).map((alerta, i) => html`<div key=${`${alerta.codigo}-${i}`}
      class=${`aviso alerta-${alerta.nivel || "advertencia"}`}>
      <span class="icono-alerta" title=${alerta.mensaje} aria-label=${alerta.mensaje}>⚠</span>
      <strong>${alerta.codigo?.replaceAll("_", " ") || "ADVERTENCIA"}:</strong> ${alerta.mensaje}
      <button type="button" class="boton boton-compacto" onClick=${() => atenderAlerta(alerta)}>
        Marcar atendido</button></div>`)}

    ${modoEdicion && !revisionCompletada ? html`<div class="tarjeta aprendizaje-panel">
      <div>
        <p class="sobrelinea">APRENDIZAJE SUPERVISADO</p>
        <h3 class="titulo-seccion">Corregir una lectura</h3>
        <p class="subtitulo-seccion">La corrección se guarda como verdad confirmada. Una nueva versión
          solo se activa si mejora la evaluación sin introducir regresiones.</p>
      </div>
      ${unidadesCorregibles.length ? html`
        <form class="formulario-correccion" onSubmit=${confirmarCorreccion}>
          <label>Imagen
            <select class="campo" value=${imagenSeleccionada?.id || ""}
              onChange=${(e) => cambiarImagen(e.target.value)}>
              ${imagenesDetalle.map((imagen) => html`<option key=${imagen.id} value=${imagen.id}>
                ${imagen.nombre || imagen.ruta.split(/[\\/]/).pop()} · ${(imagen.rol || "imagen").replaceAll("_", " ")}
              </option>`)}
            </select>
          </label>
          <label>Renglón o bloque OCR
            <select class="campo" value=${unidadSeleccionada?.unidad_id || ""} onChange=${(e) => {
              const unidad = unidadesCorregibles.find((u) => u.unidad_id === e.target.value);
              if (unidad) {
                setUnidadId(unidad.unidad_id); setTextoCorrecto(textoVisible(unidad));
              }
            }}>
              ${unidadesCorregibles.map((t) => html`<option key=${t.unidad_id} value=${t.unidad_id}>
                ${t.tipo_unidad}: ${textoVisible(t).replaceAll("\n", " ↵ ")}</option>`)}
            </select>
          </label>
          <label>Texto correcto (con espacios y saltos)
            <textarea class="campo mono campo-texto" value=${textoCorrecto} required maxLength=${4096}
              rows=${Math.min(8, Math.max(2, textoCorrecto.split("\n").length + 1))}
              onChange=${(e) => setTextoCorrecto(e.target.value)} placeholder="Escribe el texto correcto" />
          </label>
          <button class="boton boton-primario" disabled=${guardandoCorreccion || !textoCorrecto.trim()}>
            ${guardandoCorreccion ? "Evaluando…" : "Confirmar y entrenar"}
          </button>
        </form>`
        : html`<p class="subtitulo-seccion">No hay texto OCR que corregir en esta imagen.</p>`}
      ${aprendizaje && html`<p class="subtitulo-seccion estado-modelo">
        Memorias confirmadas: <strong>${aprendizaje.memorias_imagen ?? aprendizaje.correcciones}</strong> · Modelo global activo:
        <span class="mono">${aprendizaje.modelo_activo?.version || "aún sin evidencia suficiente"}</span>
      </p>`}
      ${resultadoCorreccion?.ok && html`<div class="aviso">
        ${resultadoCorreccion.rotacion
          ? resultadoCorreccion.resultado.mensaje
          : html`<strong>Corrección guardada y memorizada para esta imagen.</strong>
            ${resultadoCorreccion.resultado.entrenamiento?.promovido
              ? ` También se activó una regla global (${resultadoCorreccion.resultado.entrenamiento.version}) para imágenes nuevas.`
              : " Se aplicará automáticamente si vuelve a procesarse esta misma imagen y zona. Por seguridad, todavía no se generaliza a imágenes nuevas hasta que otras correcciones confirmen el mismo patrón."}`}
      </div>`}
      ${resultadoCorreccion && !resultadoCorreccion.ok && html`
        <div class="mensaje-error">${resultadoCorreccion.mensaje}</div>`}

      <div class="separador-panel"></div>
      <div>
        <p class="sobrelinea">TEXTO OMITIDO</p>
        <h3 class="titulo-seccion">Marcar una zona que el OCR no encontró</h3>
        <p class="subtitulo-seccion">Arrastra sobre la imagen, encierra el texto y escribe exactamente
          lo que dice. La región queda asociada a esta carpeta e imagen y se agrega al Excel.</p>
      </div>
      <form class="formulario-region" onSubmit=${confirmarRegion}>
        <${SelectorRegion} item=${imagenSeleccionada} valor=${region} onChange=${setRegion}
          onSelectText=${(unidad) => seleccionarUnidad(imagenSeleccionada, unidad)} />
        <div class="campos-region">
          <label>Región seleccionada
            <input class="campo mono" value=${region ? region.join(", ") : ""} readOnly
              placeholder="Arrastra sobre la imagen" />
          </label>
          <label>Texto real de esa zona
            <textarea class="campo mono campo-texto" value=${textoRegion} required maxLength=${8192}
              rows=${Math.min(10, Math.max(3, textoRegion.split("\n").length + 1))}
              onChange=${(e) => setTextoRegion(e.target.value)}
              placeholder="Escribe todo el texto, respetando espacios y saltos" />
          </label>
          <button class="boton boton-primario"
            disabled=${guardandoRegion || !region || !textoRegion.trim()}>
            ${guardandoRegion ? "Guardando…" : "Guardar región y actualizar Excel"}
          </button>
        </div>
      </form>
      ${resultadoRegion?.ok && html`<div class="aviso">
        Región guardada y agrupada en ${detalle.nombre}.
        ${resultadoRegion.resultado.excel_actualizado
          ? " El Excel maestro fue actualizado."
          : ` La anotación está segura, pero el Excel no pudo actualizarse: ${resultadoRegion.resultado.advertencia_excel || "error desconocido"}.`}
      </div>`}
      ${resultadoRegion && !resultadoRegion.ok && html`
        <div class="mensaje-error">${resultadoRegion.mensaje}</div>`}
      ${historialAprendizaje.length > 0 && html`<div class="historial-aprendizaje">
        <h3 class="titulo-seccion">Lista de aprendizaje supervisado</h3>
        <p class="subtitulo-seccion">Incluye correcciones OCR y textos omitidos guardados manualmente.</p>
        ${historialAprendizaje.map((item) => html`<div key=${item.id} class="evidencia-aprendizaje">
          <span class="chip neutro">${item.tipo}</span>
          <strong class="mono">${item.correcto}</strong>
          ${item.original && item.original !== item.correcto && html`<small class="mono">Antes: ${item.original}</small>`}
          <small>${item.imagen}${item.bbox ? ` · región ${item.bbox.join(", ")}` : ""}</small>
        </div>`)}
      </div>`}
    </div>` : html`<div class="tarjeta modo-lectura">
      <strong>${revisionCompletada ? "Revisión completada" : "Modo de consulta"}</strong>
      <p>${revisionCompletada
        ? "La edición está bloqueada. Reabre la revisión si necesitas cambiar algo."
        : "Activa “Editar y revisar” para corregir texto o marcar una zona omitida."}</p>
    </div>`}

    <div class="detalle-grid detalle-todas-imagenes">
      ${imagenesDetalle.map((imagen) => html`<${PanelImagen} key=${imagen.id || imagen.ruta}
        titulo=${`${(imagen.rol || "imagen").replaceAll("_", " ")} · ${imagen.nombre || imagen.ruta.split(/[\\/]/).pop()}`}
        item=${imagen} vacio="Imagen no disponible." edicionActiva=${modoEdicion && !revisionCompletada}
        rotacionActiva=${!revisionCompletada}
        onSelectText=${seleccionarUnidad} onRotate=${rotarImagen} />`)}
    </div>

    <a class="volver" href="#/tabla">← Volver al listado</a>
  `;
}

/* ----------------------------- App / routing ----------------------------- */

function App() {
  const [ruta, setRuta] = useState(location.hash || "#/resumen");
  const [tema, alternarTema] = usarTema();
  useEffect(() => {
    const alHash = () => setRuta(location.hash || "#/resumen");
    window.addEventListener("hashchange", alHash);
    return () => window.removeEventListener("hashchange", alHash);
  }, []);
  const [vista, arg] = ruta.replace(/^#\//, "").split("/");
  const actual = vista === "tabla" ? "tabla" : vista === "carga" ? "carga"
    : vista === "detalle" ? "" : "resumen";

  return html`
    <header class="cabecera">
      <div class="cabecera-inner">
        <span class="logo"><span class="punto"></span>Validación de pruebas · OCR</span>
        <span class="espacio"></span>
        <button class="btn-tema" onClick=${alternarTema} aria-label="Cambiar tema claro/oscuro">
          ${tema === "claro" ? "🌙 Oscuro" : "☀️ Claro"}</button>
        <nav class="navegacion" aria-label="Vistas">
          <a class="tab" href="#/resumen" aria-current=${actual === "resumen" ? "page" : undefined}>Resumen</a>
          <a class="tab" href="#/tabla" aria-current=${actual === "tabla" ? "page" : undefined}>Listado</a>
          <a class="tab" href="#/carga" aria-current=${actual === "carga" ? "page" : undefined}>Procesar carpeta</a>
        </nav>
      </div>
    </header>
    <main class="contenedor">
      ${vista === "tabla" ? html`<${VistaTabla} />`
        : vista === "carga" ? html`<${VistaCarga} />`
        : vista === "externas" ? html`<${VistaExternas} caso=${decodeURIComponent(arg || "")} />`
        : vista === "detalle" ? html`<${VistaDetalle} nombre=${decodeURIComponent(arg || "")} />`
        : html`<${VistaResumen} />`}
    </main>
  `;
}

ReactDOM.createRoot(document.getElementById("raiz")).render(html`<${App} />`);
