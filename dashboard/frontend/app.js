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
const fmtFecha = (v) => {
  if (!v) return "—";
  const fecha = new Date(v);
  if (Number.isNaN(fecha.getTime())) return v;
  return new Intl.DateTimeFormat("es-MX", {
    dateStyle: "medium", timeStyle: "short"
  }).format(fecha);
};

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
  const [ruta, setRuta] = useState("");
  const [estado, setEstado] = useState(undefined);
  const [errorEstado, setErrorEstado] = useState(null);
  const [enviando, setEnviando] = useState(false);
  const [errorEnvio, setErrorEnvio] = useState(null);
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
      await enviarJSON("/api/pipeline", { ruta: ruta.trim() });
      refrescar();
    } catch (e) {
      setErrorEnvio(e.message);
    } finally {
      setEnviando(false);
    }
  };

  const procesando = estado?.estado === "procesando";
  const noLista = capacidad && !capacidad.listo;
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
        ${capacidad.listo ? "Entorno OCR listo" : "Entorno OCR incompleto"}
      </span>
    </section>

    ${noLista && html`<div class="aviso aviso-error" role="alert">
      <strong>No es posible iniciar todavía.</strong>
      <span>Faltan dependencias en el Python que ejecuta el dashboard: ${capacidad.faltantes.join(", ")}.</span>
    </div>`}

    <form class="tarjeta formulario-carga" onSubmit=${procesar}>
      <label for="ruta-carpeta"><strong>Dirección de la carpeta raíz</strong></label>
      <p class="subtitulo-seccion">Pega una ruta absoluta o una ruta relativa a la carpeta del proyecto.</p>
      <div class="fila-ruta">
        <input id="ruta-carpeta" class="campo" type="text" required
          placeholder="/Users/usuario/lotes/Lote_Pruebas"
          value=${ruta} onInput=${(e) => setRuta(e.target.value)}
          disabled=${procesando || enviando} />
        <button type="button" class="boton" onClick=${usarActual} disabled=${procesando || enviando}>
          Usar carpeta actual
        </button>
      </div>
      <div class="nota-local">
        <span aria-hidden="true">🔒</span>
        <span>Los archivos permanecen en su ubicación. Para lotes de 8 GB, esto evita una copia innecesaria.</span>
      </div>
      <button class="boton boton-primario" type="submit"
        disabled=${procesando || enviando || !ruta.trim() || noLista}>
        ${procesando ? "Procesando…" : enviando ? "Iniciando…" : "Procesar carpeta"}
      </button>
      ${errorEnvio && html`<p class="mensaje-error" role="alert">${errorEnvio}</p>`}
    </form>

    <div class="tarjeta panel-progreso" aria-live="polite">
      <div class="progreso-titulo">
        <h3>Estado del procesamiento</h3>
        <span class=${`estado-ejecucion estado-${estado.estado}`}>${estado.estado}</span>
      </div>
      ${procesando && html`<div class="progreso-indeterminado"><span></span></div>`}
      <dl class="ficha">
        <dt>Fase actual</dt><dd>${estado.fase || "—"}</dd>
        <dt>Mensaje</dt><dd>${estado.mensaje || "Aún no se ha iniciado una ejecución."}</dd>
        <dt>Carpeta</dt><dd class="mono">${estado.ruta || "—"}</dd>
        <dt>Inicio</dt><dd>${fmtFecha(estado.iniciado_en)}</dd>
        ${estado.finalizado_en && html`<dt>Finalización</dt><dd>${fmtFecha(estado.finalizado_en)}</dd>`}
      </dl>
      ${estado.error && html`<div class="mensaje-error" role="alert">
        <strong>Error:</strong> ${estado.error}
        ${estado.bitacora && html`<div class="mono">Bitácora: ${estado.bitacora}</div>`}
      </div>`}
      ${estado.estado === "completado" && html`<a class="boton boton-primario" href="#/resumen">
        Ver resultados actualizados →</a>`}
    </div>
  `;
}

function VistaTabla() {
  const [consulta, setConsulta] = useState("");
  const [estado, setEstado] = useState("");
  const [pagina, setPagina] = useState(0);
  const consultaEstable = useDebounce(consulta);
  const limite = 100;
  const [config, , errorConfig] = useApi("/api/config");
  const [filas, , errorFilas] = useApi(
    `/api/pruebas?q=${encodeURIComponent(consultaEstable)}&estado=${encodeURIComponent(estado)}&limit=${limite}&offset=${pagina * limite}`,
    [consultaEstable, estado, pagina]);
  const colores = (config && config.colores) || {};
  const refTabla = useRef(null);

  const alPulsarTecla = useCallback((ev) => {
    if (ev.key !== "ArrowDown" && ev.key !== "ArrowUp" && ev.key !== "Enter") return;
    if (ev.target.tagName === "SELECT") return;
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

  return html`
    <div ref=${refTabla} onKeyDown=${alPulsarTecla}>
    <div class="barra-filtros">
      <input class="campo" type="search" placeholder="Buscar por identificador o nomenclatura…"
        aria-label="Buscar en la tabla"
        value=${consulta} onInput=${(e) => { setConsulta(e.target.value); setPagina(0); }} />
      <select class="campo" aria-label="Filtrar por estado" value=${estado}
        onChange=${(e) => { setEstado(e.target.value); setPagina(0); }}>
        <option value="">Todos los estados</option>
        <option value="verde">Verde</option>
        <option value="amarillo">Amarillo</option>
        <option value="rojo">Rojo</option>
        <option value="sin_clasificar">Sin clasificar</option>
      </select>
      <span class="subtitulo-seccion" style=${{ margin: "auto 0 auto auto" }}>
        ${filas.total} ${filas.total === 1 ? "carpeta" : "carpetas"}</span>
    </div>

    <div class="contenedor-tabla">
      <table aria-label="Resultados de validación por carpeta">
        <thead><tr>
          <th>Identificador</th><th>Lote</th><th>Resultado</th><th>Confianza OCR</th>
          <th>QR</th><th>Estado</th>
        </tr></thead>
        <tbody>
          ${filas.items.map((f) => html`<tr key=${f.nombre} tabIndex=${0}
            aria-label=${`Abrir detalle de ${f.identificador || f.nombre}`}
            onClick=${() => { location.hash = `#/detalle/${encodeURIComponent(f.id)}`; }}>
            <td data-etiqueta="Identificador"><strong>${f.identificador || f.nombre}</strong></td>
            <td data-etiqueta="Lote">${celda(f.lote)}</td>
            <td data-etiqueta="Resultado">${f.resultado}</td>
            <td data-etiqueta="Confianza" class="numero">${fmtPct(f.confianza_ocr_pct)}</td>
            <td data-etiqueta="QR">${f.qr_detectado ? "Sí" : "No"}</td>
            <td data-etiqueta="Estado"><${ChipSemaforo} color=${f.semaforo} colores=${colores}>
              ${f.semaforo || "sin clasificar"}</${ChipSemaforo}></td>
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

function PanelImagen({ titulo, item, vacio }) {
  return html`<div class="tarjeta">
    <h3 class="titulo-seccion" style=${{ marginTop: 0 }}>${titulo}</h3>
    ${item
      ? html`<div class="imagen-marco">
          <img src=${item.ruta_api} alt=${`Imagen: ${item.ruta}`} loading="lazy" />
        </div>
        <ul class="tokens-lista">
          ${((item.resultado_ocr || {}).tokens || []).map((t, i) => html`<li key=${i} class="token-fila">
            <span class="mono">${t.texto}</span>
            <span class="conf">${(t.confianza * 100).toFixed(1)}%</span>
          </li>`)}
        </ul>`
      : html`<p style=${{ color: "var(--texto-3)" }}>${vacio}</p>`}
  </div>`;
}

function VistaDetalle({ nombre }) {
  const [detalle, , errorDetalle] = useApi(`/api/pruebas/${encodeURIComponent(nombre)}`, [nombre]);
  const [config, , errorConfig] = useApi("/api/config");
  const colores = (config && config.colores) || {};
  if (detalle === undefined || config === undefined) {
    return html`<div class="tarjeta" style=${{ marginTop: 16 }}><div class="esqueleto"></div></div>`;
  }
  if (errorDetalle || errorConfig) return html`<${EstadoError} mensaje="No fue posible abrir este detalle." />`;
  if (!detalle) return html`<${EstadoVacio} />`;
  const comp = detalle.comparacion;
  return html`
    <div style=${{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginTop: 18 }}>
      <h2 style=${{ margin: 0, fontSize: 20 }}>${detalle.identificador || detalle.nombre}</h2>
      <${ChipSemaforo} color=${detalle.semaforo} colores=${colores}>
        ${detalle.semaforo || "sin clasificar"}</${ChipSemaforo}>
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

    <div class="detalle-grid">
      <${PanelImagen} titulo="Etiqueta (imagen original + tokens OCR)"
        item=${detalle.etiqueta} vacio="Sin fotografía de etiqueta en esta carpeta." />
      <${PanelImagen} titulo="Referencia (imagen original + tokens OCR)"
        item=${detalle.referencia} vacio="Sin imagen de referencia en esta carpeta." />
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
        : vista === "detalle" ? html`<${VistaDetalle} nombre=${decodeURIComponent(arg || "")} />`
        : html`<${VistaResumen} />`}
    </main>
  `;
}

ReactDOM.createRoot(document.getElementById("raiz")).render(html`<${App} />`);
