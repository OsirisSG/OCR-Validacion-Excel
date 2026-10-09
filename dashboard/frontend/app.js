/* =============================================================================
   app.js — Dashboard de validación de pruebas (React sin paso de build).
   React 18 UMD + htm (vendorizados en vendor/): funciona sin internet.
   Vistas: Resumen (KPIs + distribución), Tabla (filtro + buscador + teclado),
   Detalle (imagen original + OCR etiqueta vs referencia lado a lado).
   La paleta del semáforo llega de /api/config → idéntica al Excel.
   Ruta de migración a Vite + Tremor: docs/fase4_dashboard.md.
   ============================================================================= */

const { useState, useEffect, useLayoutEffect, useMemo, useRef, useCallback } = React;
const html = htm.bind(React.createElement);
const t = (texto) => window.OCR_I18N?.t?.(texto) || texto;
function Icono({tipo="documento"}) { const paths={documento:"M5 3h9l5 5v13H5z M14 3v6h6 M8 13h8 M8 17h6",grid:"M4 4h6v6H4z M14 4h6v6h-6z M4 14h6v6H4z M14 14h6v6h-6z",lista:"M7 6h13 M7 12h13 M7 18h13 M4 6h.01 M4 12h.01 M4 18h.01",carpeta:"M3 6h7l2 2h9v11H3z",luna:"M18 16a7 7 0 0 1-10-10 8 8 0 1 0 10 10",sol:"M12 4v2 M12 18v2 M4 12h2 M18 12h2 M6.3 6.3l1.4 1.4 M16.3 16.3l1.4 1.4 M17.7 6.3l-1.4 1.4 M7.7 16.3l-1.4 1.4 M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6"};return html`<svg class="icono-svg" viewBox="0 0 24 24" aria-hidden="true"><path d=${paths[tipo]||paths.documento}/></svg>`;}


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
  return new Intl.DateTimeFormat(window.OCR_I18N?.locale?.() || "es-MX", {
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
function imagenSinTexto(imagen) {
  return Boolean(imagen?.revision_sin_datos || imagen?.estado_imagen === "revisada_sin_datos");
}
function imagenesParaRevisar(imagenes, ocultarVerificadas = false, ocultarSinTexto = false) {
  return (imagenes || []).filter((imagen) => {
    if (ocultarSinTexto && imagenSinTexto(imagen)) return false;
    if (ocultarVerificadas && imagen.estado_imagen === "verificada" && !imagenSinTexto(imagen)) return false;
    return true;
  });
}
function useAvisoBorrador(pendiente, ocupado, motivo = "Herramienta activa con cambios pendientes") {
  useEffect(() => {
    const avisar = e => {
      if (!Array.isArray(e.detail.motivos)) e.detail.motivos = [];
      if (!Array.isArray(e.detail.operaciones)) e.detail.operaciones = [];
      if (pendiente) {
        e.detail.pendiente = true;
        if (motivo && !e.detail.motivos.includes(motivo)) e.detail.motivos.push(motivo);
      }
      if (ocupado) {
        e.detail.ocupado = true;
        const operacion = `${motivo}: guardando o procesando`;
        if (!e.detail.operaciones.includes(operacion)) e.detail.operaciones.push(operacion);
      }
    };
    window.addEventListener("ocr-consultar-borradores", avisar);
    return () => window.removeEventListener("ocr-consultar-borradores", avisar);
  }, [pendiente, ocupado, motivo]);
}
// Compatibilidad histórica: Texto no necesario sigue disponible mediante la acción separada “Esto no es texto”.
// V9 mostraba: “Proponer esta región como ejemplo para entrenamiento OCR”; V14.14 lo hace siempre y ya no necesita checkbox.
function AyudaAprendizaje({ texto = "Cada lectura o corrección confirmada aporta una muestra al aprendizaje. Los movimientos provisionales no entrenan." }) {
  return html`<span class="aprendizaje-auto-info">
    <strong>Aprendizaje automático</strong>
    <details class="ayuda-inline-detalle">
      <summary aria-label="Información sobre aprendizaje automático" title="Información sobre aprendizaje automático">ⓘ</summary>
      <span class="ayuda-inline-popover">${texto}</span>
    </details>
  </span>`;
}
function candidatoOrientacionAutomatica(candidatos = []) {
  const lista = Array.isArray(candidatos) ? candidatos : [];
  const marcada = lista.find(c => Boolean(c?.recomendada));
  if (marcada) return marcada;
  return [...lista].sort((a,b) => Number(b?.score_informacion || 0) - Number(a?.score_informacion || 0)
    || Number(b?.confianza || 0) - Number(a?.confianza || 0))[0] || null;
}
function categoriaLectura(candidato = {}) {
  let tipo = String(candidato?.tipo_informacion || (candidato?.probable_codigo ? "codigo" : "texto"));
  let score = Number(candidato?.score_informacion || 0);
  const texto = String(candidato?.texto || "").replace(/\s+/g, "");
  const letras = [...texto].filter(c => /[A-Za-z]/.test(c));
  const mezclaCaso = letras.some(c => c === c.toUpperCase()) && letras.some(c => c === c.toLowerCase()) && /\d/.test(texto);
  const simbolosFuertes = /[%:;,=!?@#$&*()\[\]{}<>\\|"']/.test(texto);
  // Defensa de interfaz: aunque llegue una candidata cacheada de una versión anterior,
  // no mostramos como código una cadena con símbolos fuertes o mezcla de caso sospechosa.
  if (tipo === "codigo" && (simbolosFuertes || mezclaCaso)) { tipo = "ruido"; score = Math.min(score, 35); }
  const etiquetas = {codigo:"Código",fecha:"Fecha",numero:"Valor / medición",texto:"Texto",ruido:"Ruido probable"};
  return {tipo, etiqueta: tipo === "ruido" ? etiquetas.ruido : (candidato?.etiqueta_informacion || etiquetas[tipo] || "Lectura"),
    score, ruido:Boolean(candidato?.es_ruido || tipo === "ruido")};
}
function candidatoEsUtil(candidato, umbral = 45) {
  const c = categoriaLectura(candidato);
  return !c.ruido && c.score >= Number(umbral || 0);
}
function candidatoOrientacionSegunTipo(candidatos = [], tipoEsperado = "auto") {
  const lista = Array.isArray(candidatos) ? candidatos : [];
  if (tipoEsperado === "auto") return candidatoOrientacionAutomatica(lista);
  const compatibles = lista.filter(c => categoriaLectura(c).tipo === tipoEsperado);
  return [...compatibles].sort((a,b) => Number(b?.score_informacion || 0) - Number(a?.score_informacion || 0)
    || Number(b?.consenso || 1) - Number(a?.consenso || 1)
    || Number(b?.confianza || 0) - Number(a?.confianza || 0))[0] || null;
}
function candidatoPasaFiltro(candidato, filtro) {
  const c = categoriaLectura(candidato);
  if (filtro === "codigo") return c.tipo === "codigo";
  if (filtro === "datos") return c.tipo === "fecha" || c.tipo === "numero";
  if (filtro === "texto") return c.tipo === "texto";
  if (filtro === "utiles") return candidatoEsUtil(candidato);
  return true;
}
function propuestaTextoOrientacion(recorte, grados, usarAjusteFino = true) {
  const anguloBase = ((Number(grados) % 360) + 360) % 360;
  const candidatos = recorte?.candidatos_orientacion || [];
  const candidato = candidatos.find(c => ((Number(c.grados) % 360) + 360) % 360 === anguloBase)
    || candidatos.find(c => Math.abs((((Number(c.grados_efectivos ?? c.grados) % 360) + 360) % 360) - anguloBase) < 0.01);
  const ajusteDisponible = Number(candidato?.ajuste_fino_grados || 0);
  const usarFino = Boolean(usarAjusteFino && Math.abs(ajusteDisponible) >= 0.05);
  const efectivo = candidato && usarFino
    ? ((Number(candidato.grados_efectivos ?? candidato.grados) % 360) + 360) % 360
    : anguloBase;
  const textoElegido = usarFino ? candidato?.texto : (candidato?.texto_base ?? candidato?.texto);
  const confianzaElegida = usarFino ? candidato?.confianza : (candidato?.confianza_base ?? candidato?.confianza);
  return { angulo: efectivo, anguloBase, ajusteFino: usarFino ? ajusteDisponible : 0,
    texto: textoElegido ? String(textoElegido) : null, confianza: confianzaElegida,
    usandoAjusteFino: usarFino, candidato };
}
function poligonoRectanguloRotado(bbox, angulo = 0, dimensiones = null) {
  if (!Array.isArray(bbox) || bbox.length !== 4) return null;
  const [x,y,w,h] = bbox.map(Number);
  if (![x,y,w,h].every(Number.isFinite) || w < 2 || h < 2) return null;
  const a = Number(angulo) || 0;
  const rad = a * Math.PI / 180;
  const c = Math.cos(rad), s = Math.sin(rad);
  const cx = x + w/2, cy = y + h/2;
  const pts = [[-w/2,-h/2],[w/2,-h/2],[w/2,h/2],[-w/2,h/2]].map(([dx,dy]) => [
    cx + c*dx - s*dy, cy + s*dx + c*dy,
  ]);
  if (Array.isArray(dimensiones) && dimensiones.length === 2) {
    const [aw,ah] = dimensiones.map(Number);
    if (pts.some(([px,py]) => px < 0 || py < 0 || px > aw-1 || py > ah-1)) return null;
  }
  return pts.map(([px,py]) => [Math.round(px*1000)/1000, Math.round(py*1000)/1000]);
}
function puntosSvg(poligono) {
  return (poligono || []).map(p => `${Number(p[0]).toFixed(2)},${Number(p[1]).toFixed(2)}`).join(" ");
}
function poligonoRectangulo(bbox) {
  if (!Array.isArray(bbox) || bbox.length !== 4) return null;
  const [x,y,w,h] = bbox.map(Number);
  if (![x,y,w,h].every(Number.isFinite) || w < 2 || h < 2) return null;
  return [[x,y],[x+w,y],[x+w,y+h],[x,y+h]];
}
function bboxDesdePoligono(poligono, dimensiones = null) {
  if (!Array.isArray(poligono) || poligono.length !== 4) return null;
  const xs = poligono.map(p=>Number(p?.[0])), ys = poligono.map(p=>Number(p?.[1]));
  if (![...xs,...ys].every(Number.isFinite)) return null;
  let x0=Math.min(...xs), y0=Math.min(...ys), x1=Math.max(...xs), y1=Math.max(...ys);
  if (Array.isArray(dimensiones) && dimensiones.length===2) {
    x0=Math.max(0,x0); y0=Math.max(0,y0); x1=Math.min(Number(dimensiones[0])-1,x1); y1=Math.min(Number(dimensiones[1])-1,y1);
  }
  const x=Math.floor(x0), y=Math.floor(y0), w=Math.ceil(x1)-x, h=Math.ceil(y1)-y;
  return w>=2 && h>=2 ? [x,y,w,h] : null;
}
function moverPoligono(poligono, dx, dy, dimensiones) {
  if (!Array.isArray(poligono) || poligono.length!==4) return null;
  const [aw,ah]=(dimensiones||[0,0]).map(Number);
  const xs=poligono.map(p=>Number(p[0])), ys=poligono.map(p=>Number(p[1]));
  const minX=Math.min(...xs), maxX=Math.max(...xs), minY=Math.min(...ys), maxY=Math.max(...ys);
  const ddx=Math.max(-minX, Math.min(aw-1-maxX, Number(dx)||0));
  const ddy=Math.max(-minY, Math.min(ah-1-maxY, Number(dy)||0));
  return poligono.map(([x,y])=>[Math.round((Number(x)+ddx)*1000)/1000,Math.round((Number(y)+ddy)*1000)/1000]);
}
function dividirPoligonoVertical(poligono) {
  if (!Array.isArray(poligono) || poligono.length!==4) return null;
  const [a,b,c,d]=poligono.map(p=>[Number(p[0]),Number(p[1])]);
  if ([...a,...b,...c,...d].some(v=>!Number.isFinite(v))) return null;
  const sup=[(a[0]+b[0])/2,(a[1]+b[1])/2], inf=[(d[0]+c[0])/2,(d[1]+c[1])/2];
  return [[a,sup,inf,d],[sup,b,c,inf]];
}
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
    vistas.push({ texto: ocr.texto_completo, texto_original: ocr.texto_completo_original || ocr.texto_completo,
      confirmado_manualmente: Boolean(ocr.texto_completo_confirmado), bbox: null, tipo_unidad: "bloque completo" });
  }
  return vistas.map((unidad, indice) => ({
    ...unidad, unidad_id: `${unidad.tipo_unidad}-${indice}-${firmaUnidad(unidad)}`,
  }));
}
function unidadConfirmada(unidad, correcciones = []) {
  if (!unidad) return false;
  if (unidad.confirmado_manualmente || unidad.edicion_zona ||
      unidad.correccion_modelo?.tipo === "memoria_imagen_confirmada") return true;
  return (correcciones || []).some((c) => String(c.texto_ocr || "") === textoUnidad(unidad)
    && String(c.texto_correcto || "") === textoVisible(unidad)
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
    <div class="icono"><${Icono} tipo="carpeta" /></div>
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

function MatrizApertura({ matriz, colores }) {
  if (!matriz?.etapas?.length) return null;
  const paleta = {
    verde: colores.verde || "#22c55e", amarillo: colores.amarillo || "#f59e0b",
    rojo: colores.rojo || "#ef4444", gris: colores.gris || "#9ca3af",
  };
  const abrirEnListado = (item) => {
    if (!item) return;
    try {
      sessionStorage.setItem("foco_listado", JSON.stringify({
        id: item.id, query: String(item.test_number || ""),
      }));
    } catch (_) {}
    location.hash = "#/tabla";
  };
  const textoTiempo = (item) => item?.opening_time_ms === null || item?.opening_time_ms === undefined
    ? "Tiempo de apertura aún no conocido"
    : `Tiempo de apertura: ${item.opening_time_ms} ms`;
  return html`<div class="tarjeta matriz-apertura-tarjeta">
    <div class="matriz-apertura-encabezado">
      <div>
        <h3 class="titulo-seccion" style=${{ margin: 0 }}>Matriz de tiempo de apertura</h3>
        <p class="subtitulo-seccion" style=${{ marginBottom: 0 }}>
          1ST y 2ST en un solo resumen. Haz clic en una prueba para localizar su carpeta en el Listado.
        </p>
      </div>
      <div class="leyenda-apertura" aria-label="Leyenda tiempo de apertura">
        ${Object.entries(matriz.regla || {}).map(([estado, etiqueta]) => html`
          <span key=${estado}><i style=${{ background: paleta[estado] }}></i>${etiqueta}</span>`)}
      </div>
    </div>
    <div class="matrices-apertura">
      ${matriz.etapas.map((etapa) => html`<section class="matriz-etapa" key=${etapa.tipo_st}>
        <div class="matriz-etapa-titulo">Overview results (${etapa.tipo_st})</div>
        <div class="matriz-apertura-grid">
          ${etapa.columnas.map((col) => html`<div class="matriz-apertura-columna" key=${col.id}>
            <div class="matriz-apertura-celdas">
              ${col.celdas.map((item, idx) => item
                ? html`<button key=${item.id || idx} type="button"
                    class=${`matriz-celda estado-${item.estado || "gris"}`}
                    style=${{ background: paleta[item.estado] || paleta.gris }}
                    title=${`${item.test_number} · ${textoTiempo(item)} · abrir en Listado`}
                    onClick=${() => abrirEnListado(item)}>${item.test_number}</button>`
                : html`<span key=${`vacio-${idx}`} class="matriz-celda matriz-celda-vacia" aria-hidden="true"></span>`)}
            </div>
            <div class="matriz-columna-meta"><strong>${col.temperatura}</strong><span>${col.generador}</span></div>
          </div>`)}
        </div>
      </section>`)}
    </div>
  </div>`;
}

function ExportadorExcel() {
  const [idioma,setIdioma]=useState(()=>localStorage.getItem("ocr_export_idioma")||"es");
  const [estado,setEstado]=useState(null); const [enviando,setEnviando]=useState(false);
  useEffect(()=>localStorage.setItem("ocr_export_idioma",idioma),[idioma]);
  async function exportar(){setEnviando(true);setEstado(null);try{const idiomas=idioma==="all"?["es","en","de"]:[idioma];setEstado(await enviarJSON("/api/resultados/exportar",{idiomas}));}catch(e){setEstado({error:e.message});}finally{setEnviando(false);}}
  return html`<div class="tarjeta exportador-excel"><div><h3 class="titulo-seccion" style=${{margin:0}}>Exportar Excel</h3><p class="subtitulo-seccion">Elige el idioma independientemente de la interfaz. Los tres archivos usan la misma instantánea de datos.</p></div><div class="exportador-controles"><label>Idioma de exportación<select class="campo" value=${idioma} onChange=${e=>setIdioma(e.target.value)}><option value="es">Español</option><option value="en">English</option><option value="de">Deutsch</option><option value="all">Los tres idiomas</option></select></label><button class="boton boton-primario" onClick=${exportar} disabled=${enviando}>${enviando?"Exportando…":"Exportar Excel"}</button></div>${estado?.error&&html`<div class="aviso estado-error">${estado.error}</div>`}${estado?.generados?.length&&html`<div class="descargas-exportacion">${estado.generados.map(x=>html`<a class="boton" href=${x.url}>${x.nombre}</a>`)}</div>`}</div>`;
}

function EditorCriteriosApertura({config, onSaved}) {
  const reglas = config.reglas?.tiempo_apertura_ms || {};
  const [verde, setVerde] = useState(() => config.criterios_usuario?.verde_max ??
    (String(reglas.verde || "").match(/^<=\s*([\d.]+)$/)?.[1] || ""));
  const [amarillo, setAmarillo] = useState(() => config.criterios_usuario?.amarillo_max ??
    (String(reglas.rojo || "").match(/^>\s*([\d.]+)$/)?.[1] || ""));
  const [guardando, setGuardando] = useState(false);
  const [mensaje, setMensaje] = useState(null);
  async function guardar(e) {
    e.preventDefault(); setMensaje(null);
    const v = Number(verde), a = Number(amarillo);
    if (verde === "" || amarillo === "" || !Number.isFinite(v) || !Number.isFinite(a) || v < 0 || v >= a) {
      setMensaje({error:true, texto:t("Los límites deben cumplir: 0 ≤ verde < amarillo.")}); return;
    }
    setGuardando(true);
    try {
      await enviarJSON("/api/config/criterios-apertura", {verde_max:v, amarillo_max:a});
      await onSaved();
      setMensaje({texto:t("Límites guardados. La matriz está actualizada; vuelve a exportar el Excel.")});
    } catch (e) { setMensaje({error:true, texto:e.message}); }
    finally { setGuardando(false); }
  }
  return html`<details class="tarjeta"><summary>Definir rangos del tiempo de apertura</summary>
    <p>No se deducen de la guía. Estos límites sólo valoran apertura; no califican FORVIA, inflado completo ni máximo visible.</p>
    <p class="mono">${t("Reglas actuales")}: ${t("Verde")} ${reglas.verde || "—"} · ${t("Amarillo")} ${reglas.amarillo || "—"} · ${t("Rojo")} ${reglas.rojo || "—"}</p>
    <p>El límite verde se incluye en verde; amarillo comienza por encima de él y termina en su límite. Rojo comienza por encima del amarillo.</p>
    ${!config.criterios_usuario && html`<p>Son valores iniciales del YAML, todavía no elegidos en este panel.</p>`}
    ${config.advertencia_criterios && html`<div class="aviso estado-error">${config.advertencia_criterios}</div>`}
    <form class="exportador-controles" onSubmit=${guardar}>
      <label>Verde hasta (ms)<input class="campo" type="number" min="0" step="any" required value=${verde}
        onChange=${e=>setVerde(e.target.value)} disabled=${guardando} /></label>
      <label>Amarillo hasta (ms)<input class="campo" type="number" min="0" step="any" required value=${amarillo}
        onChange=${e=>setAmarillo(e.target.value)} disabled=${guardando} /></label>
      <span>${t("Rojo por encima de")} ${amarillo || "—"} ms</span>
      <button class="boton" disabled=${guardando}>Guardar límites elegidos</button>
    </form>
    ${mensaje && html`<div class=${mensaje.error ? "aviso estado-error" : "aviso"}>${mensaje.texto}</div>`}
  </details>`;
}

function VistaResumen() {
  const [resumen, setResumen, errorResumen] = useApi("/api/resumen");
  const [config, setConfig, errorConfig] = useApi("/api/config");
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

    <${MatrizApertura} matriz=${resumen.matriz_apertura} colores=${colores} />
    <${EditorCriteriosApertura} config=${config} onSaved=${async()=>{
      const [nuevoResumen,nuevaConfig] = await Promise.all([pedirJSON("/api/resumen"),pedirJSON("/api/config")]);
      setResumen(nuevoResumen);setConfig(nuevaConfig);
    }} />
    <${ExportadorExcel} />

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
  const [tipoSt, setTipoSt] = useState("");
  const [modoEjecucion, setModoEjecucion] = useState("completo");
  const [contenido, setContenido] = useState("todo");
  const [perfilRendimiento, setPerfilRendimiento] = useState(() =>
    localStorage.getItem("ocr_perfil_rendimiento") || "alto");
  const [idiomasExportacion, setIdiomasExportacion] = useState(() => {
    try {
      const guardados = JSON.parse(localStorage.getItem("ocr_idiomas_exportacion") || "[\"es\"]");
      const validos = Array.isArray(guardados) ? guardados.filter(x => ["es","en","de"].includes(x)) : [];
      return validos.length ? validos : ["es"];
    } catch (_) { return ["es"]; }
  });
  const [plantillaId, setPlantillaId] = useState("");
  const [plantillas, setPlantillas] = useState([]);
  const [rutaNuevaPlantilla, setRutaNuevaPlantilla] = useState("");
  const [nombreNuevaPlantilla, setNombreNuevaPlantilla] = useState("");
  const [marcadoresNuevaPlantilla, setMarcadoresNuevaPlantilla] = useState("");
  const [registrandoPlantilla, setRegistrandoPlantilla] = useState(false);
  const [dialogoDetencion, setDialogoDetencion] = useState(false);
  const [estado, setEstado] = useState(undefined);
  const [errorEstado, setErrorEstado] = useState(null);
  const [enviando, setEnviando] = useState(false);
  const [errorEnvio, setErrorEnvio] = useState(null);
  const [reloj, setReloj] = useState(Date.now());
  const [capacidad, , errorCapacidad] = useApi("/api/pipeline/capacidad");
  const [reanalisisVideos, setReanalisisVideos] = useState(null);
  const [errorReanalisisVideos, setErrorReanalisisVideos] = useState(null);

  const refrescarPlantillas = useCallback(() => {
    pedirJSON("/api/plantillas").then((dato) => setPlantillas(dato?.plantillas || []))
      .catch(() => setPlantillas([]));
  }, []);

  const refrescar = useCallback(() => {
    pedirJSON("/api/pipeline/estado")
      .then((dato) => { setEstado(dato); setErrorEstado(null); })
      .catch((e) => setErrorEstado(e));
  }, []);

  const refrescarReanalisisVideos = useCallback(() => {
    pedirJSON("/api/video/reanalisis/estado")
      .then((dato) => { setReanalisisVideos(dato); setErrorReanalisisVideos(null); })
      .catch((e) => setErrorReanalisisVideos(e));
  }, []);

  useEffect(() => {
    refrescar();
    refrescarPlantillas();
    refrescarReanalisisVideos();
    const id = setInterval(() => { refrescar(); refrescarReanalisisVideos(); }, 1200);
    return () => clearInterval(id);
  }, [refrescar, refrescarPlantillas, refrescarReanalisisVideos]);

  useEffect(() => {
    try { localStorage.setItem("ocr_idiomas_exportacion", JSON.stringify(idiomasExportacion)); } catch (_) {}
  }, [idiomasExportacion]);
  useEffect(() => {
    try { localStorage.setItem("ocr_perfil_rendimiento", perfilRendimiento); } catch (_) {}
  }, [perfilRendimiento]);
  function alternarIdiomaExportacion(codigo) {
    setIdiomasExportacion(actual => {
      const existe = actual.includes(codigo);
      if (existe && actual.length === 1) return actual;
      return existe ? actual.filter(x => x !== codigo) : [...actual, codigo];
    });
  }

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
        tipo_st: tipoSt || null, ruta_plantilla: null, plantilla_id: plantillaId || null,
        modo_ejecucion: modoEjecucion,
        perfil_rendimiento: perfilRendimiento,
        contenido,
        idiomas_exportacion: idiomasExportacion,
        ruta_inventario: null,
      });
      const nueva = {
        ruta: ruta.trim(), nombre_excel: nombreExcel.trim(),
        idiomas_exportacion: idiomasExportacion, usado_en: new Date().toISOString(),
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
  const pausando = estado?.estado === "pausando";
  const pausado = estado?.estado === "pausado";
  const cancelando = estado?.estado === "cancelando";
  const activo = procesando || pausando || pausado || cancelando;
  const reanalisisVideoActivo = ["preparando", "procesando"].includes(reanalisisVideos?.estado);
  const totalVideosReanalisis = Number(reanalisisVideos?.total_videos || 0);
  const videosReanalizados = Number(reanalisisVideos?.procesados || 0);
  const porcentajeReanalisis = totalVideosReanalisis > 0
    ? Math.min(100, (videosReanalizados / totalVideosReanalisis) * 100) : 0;
  const porcentaje = Math.min(100, Math.max(0, Number(estado?.porcentaje) || 0));
  const parciales = estado?.resultados_parciales || [];
  // El backend entrega tiempo ACTIVO (las pausas no cuentan). Entre sondeos
  // sólo animamos el reloj mientras el pipeline realmente está corriendo.
  const segundosDesdeMedicion = estado?.tiempo_medido_en
    ? Math.max(0, (reloj - new Date(estado.tiempo_medido_en).getTime()) / 1000) : 0;
  const transcurridoBase = Math.max(0, Number(estado?.transcurrido_segundos) || 0);
  const transcurridoVivo = (procesando || pausando || cancelando)
    ? transcurridoBase + segundosDesdeMedicion
    : transcurridoBase;
  const segundosDesdeActualizacion = estado?.actualizado_en
    ? Math.max(0, (reloj - new Date(estado.actualizado_en).getTime()) / 1000) : 0;
  const etaViva = procesando && estado?.eta_segundos !== null && estado?.eta_segundos !== undefined
    ? Math.max(0, estado.eta_segundos - segundosDesdeActualizacion) : estado?.eta_segundos;
  const noLista = capacidad && !capacidad.listo;
  const plantillaDetectada = estado?.resumen?.fases?.fase3?.plantilla
    || estado?.resumen?.fases?.fase0?.plantilla;
  const etiquetaPlantilla = plantillaDetectada
    ? (plantillaDetectada.ruta
      ? `${plantillaDetectada.estilo || "Plantilla detectada"} · ${plantillaDetectada.ruta}`
      : "Formato integrado (no se encontró un XLSX compatible)")
    : null;
  function elegirRutaGuardada(valor) {
    const elegida = rutasRecientes.find((item) => item.ruta === valor);
    if (!elegida) return;
    setRuta(elegida.ruta);
    setNombreExcel(elegida.nombre_excel || "");
    if (Array.isArray(elegida.idiomas_exportacion) && elegida.idiomas_exportacion.length)
      setIdiomasExportacion(elegida.idiomas_exportacion);
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
  async function detener() {
    setDialogoDetencion(true);
  }
  async function confirmarDetencion(accion) {
    setErrorEnvio(null);
    try {
      await enviarJSON("/api/pipeline/cancelar", { accion });
      setDialogoDetencion(false);
      refrescar();
    } catch (e) {
      setErrorEnvio(e.message);
    }
  }
  async function reanudarCheckpoint() {
    setErrorEnvio(null);
    try {
      await enviarJSON("/api/pipeline/reanudar", {});
      refrescar();
    } catch (e) {
      setErrorEnvio(e.message);
    }
  }
  async function reanalizarSoloVideos() {
    setErrorReanalisisVideos(null);
    try {
      await enviarJSON("/api/video/reanalizar", {});
      refrescarReanalisisVideos();
    } catch (e) {
      setErrorReanalisisVideos(e.message);
    }
  }
  async function registrarPlantilla(ev) {
    ev.preventDefault();
    if (!rutaNuevaPlantilla.trim()) return;
    setRegistrandoPlantilla(true);
    setErrorEnvio(null);
    try {
      const nueva = await enviarJSON("/api/plantillas", {
        ruta: rutaNuevaPlantilla.trim(), nombre: nombreNuevaPlantilla.trim() || null,
        tipos_st: tipoSt && tipoSt !== "LEGACY" ? [tipoSt] : [],
        marcadores_ruta: marcadoresNuevaPlantilla.split(",").map((v) => v.trim()).filter(Boolean),
      });
      await refrescarPlantillas();
      setPlantillaId(nueva.id);
      setRutaNuevaPlantilla("");
      setNombreNuevaPlantilla("");
      setMarcadoresNuevaPlantilla("");
    } catch (e) {
      setErrorEnvio(e.message);
    } finally {
      setRegistrandoPlantilla(false);
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
      <label for="tipo-st"><strong>Tipo de proyecto</strong></label>
      <p class="subtitulo-seccion">Déjalo en automático; si la ruta no contiene 1ST/2ST podrás elegirlo aquí.</p>
      <select id="tipo-st" class="campo" value=${tipoSt}
        onChange=${(e) => setTipoSt(e.target.value)} disabled=${activo || enviando}>
        <option value="">Detectar automáticamente</option>
        <option value="1ST">1ST</option><option value="2ST">2ST</option>
        <option value="LEGACY">Usar recorrido tradicional</option>
      </select>
      <label for="modo-ejecucion"><strong>Modo de ejecución</strong></label>
      <p class="subtitulo-seccion">Puedes preparar sólo el inventario o ejecutar el flujo completo.</p>
      <select id="modo-ejecucion" class="campo" value=${modoEjecucion}
        onChange=${(e) => setModoEjecucion(e.target.value)} disabled=${activo || enviando}>
        <option value="completo">Completo: inventario + OCR + Excel</option>
        <option value="inventario">Solo inventario (sin OCR)</option>
      </select>
      <label for="contenido-procesar"><strong>Contenido a procesar</strong></label>
      <p class="subtitulo-seccion">Puedes cargar la carpeta completa: el sistema busca fotos NACH/VOR y videos dentro de VIDEO/VIDEOS en la misma ejecución.</p>
      <select id="contenido-procesar" class="campo" value=${contenido}
        onChange=${(e) => setContenido(e.target.value)} disabled=${activo || enviando || modoEjecucion === "inventario"}>
        <option value="todo">Fotos + videos (recomendado)</option>
        <option value="fotos">Solo fotos</option>
        <option value="videos">Solo videos</option>
      </select>
      <label for="perfil-rendimiento"><strong>Perfil de rendimiento</strong></label>
      <p class="subtitulo-seccion">ALTO es el equilibrio predeterminado. Máximo usa más CPU/RAM y deja menor reserva de VRAM; Estable prioriza margen térmico y memoria.</p>
      <select id="perfil-rendimiento" class="campo" value=${perfilRendimiento}
        onChange=${(e) => setPerfilRendimiento(e.target.value)} disabled=${activo || enviando}>
        <option value="estable">Estable</option>
        <option value="alto">Alto</option>
        <option value="maximo">Máximo</option>
      </select>
      <fieldset class="selector-idiomas-exportacion" disabled=${activo || enviando || modoEjecucion === "inventario"}>
        <legend><strong>Idiomas del Excel</strong></legend>
        <p class="subtitulo-seccion">Independientes del idioma de la interfaz. Si eliges varios, salen de la misma instantánea.</p>
        <div class="opciones-idioma-exportacion">
          ${[["es","Español"],["en","English"],["de","Deutsch"]].map(([codigo,nombre]) => html`
            <label key=${codigo}><input type="checkbox" checked=${idiomasExportacion.includes(codigo)}
              onChange=${() => alternarIdiomaExportacion(codigo)} /> ${nombre}</label>`)}
        </div>
      </fieldset>
      <section class="base-plantillas">
        <label for="plantilla-registrada"><strong>Contrato Excel</strong></label>
        <p class="subtitulo-seccion">Selecciona una plantilla registrada o permite que el sistema elija
          una compatible sin mezclar sus columnas ni catálogos.</p>
        <select id="plantilla-registrada" class="campo" value=${plantillaId}
          onChange=${(e) => setPlantillaId(e.target.value)} disabled=${activo || enviando}>
          <option value="">Detectar automáticamente / formato integrado</option>
          ${plantillas.map((plantilla) => html`<option key=${plantilla.id} value=${plantilla.id}
            disabled=${!plantilla.disponible}>${plantilla.nombre} · ${plantilla.claves} claves
            ${plantilla.tipos_st?.length ? ` · ${plantilla.tipos_st.join("/")}` : ""}</option>`)}
        </select>
        <details class="registro-plantilla">
          <summary>Registrar otra plantilla Excel</summary>
          <div class="registro-plantilla-campos">
            <label>Nombre para identificarla
              <input class="campo" value=${nombreNuevaPlantilla} maxLength=${128}
                onInput=${(e) => setNombreNuevaPlantilla(e.target.value)}
                placeholder="Plantilla cliente / proyecto" disabled=${activo || registrandoPlantilla} />
            </label>
            <label>Ruta del archivo .xlsx
              <input class="campo mono" value=${rutaNuevaPlantilla} maxLength=${4096}
                onInput=${(e) => setRutaNuevaPlantilla(e.target.value)}
                placeholder="C:\\plantillas\\captura.xlsx" disabled=${activo || registrandoPlantilla} />
            </label>
            <label>Identificadores de carpeta (opcionales)
              <input class="campo" value=${marcadoresNuevaPlantilla} maxLength=${512}
                onInput=${(e) => setMarcadoresNuevaPlantilla(e.target.value)}
                placeholder="Cliente A, Proyecto X (separados por coma)"
                disabled=${activo || registrandoPlantilla} />
              <small>Permiten elegirla automáticamente por la estructura de la ruta.</small>
            </label>
            <button type="button" class="boton" onClick=${registrarPlantilla}
              disabled=${activo || registrandoPlantilla || !rutaNuevaPlantilla.trim()}>
              ${registrandoPlantilla ? "Validando contrato…" : "Registrar y seleccionar"}
            </button>
          </div>
        </details>
      </section>
      <label class="control-ocultos opcion-sobrescribir">
        <input type="checkbox" checked=${sobrescribirExcel}
          onChange=${(e) => setSobrescribirExcel(e.target.checked)} disabled=${activo || enviando} />
        Sobrescribir el Excel si ya existe
      </label>
      <p class="subtitulo-seccion">Si está desactivado, se conserva el anterior y se crea, por ejemplo,
        <span class="mono"> resultado_maestro_1.xlsx</span>.</p>
      <div class="nota-local">
        <span aria-hidden="true"><${Icono} tipo="documento" /></span>
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
        <span>Tiempo restante estimado: ${pausando ? "Pausando…" : pausado ? "En pausa" : etaViva === null || etaViva === undefined
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
        <dt>Idiomas Excel</dt><dd>${(estado.idiomas_exportacion || idiomasExportacion).map(x=>x.toUpperCase()).join(" · ")}</dd>
        <dt>Procesamiento</dt><dd>${estado.recursos
          ? `${estado.recursos.seleccionado.toUpperCase()} para OCR · ${estado.recursos.cpu_hilos} hilos CPU disponibles`
          : "—"}</dd>
        <dt>Perfil SOP</dt><dd>${(estado.perfil_rendimiento || perfilRendimiento).toUpperCase()}</dd>
        <dt>GPU / VRAM</dt><dd>${estado.metricas_recursos
          ? `${estado.metricas_recursos.gpu_porcentaje ?? "—"}% GPU · ${estado.metricas_recursos.vram_porcentaje ?? "—"}% VRAM`
          : "—"}</dd>
        <dt>CPU / RAM</dt><dd>${estado.metricas_recursos
          ? `${estado.metricas_recursos.cpu_porcentaje ?? "—"}% CPU · ${estado.metricas_recursos.ram_porcentaje ?? "—"}% RAM`
          : "—"}</dd>
        <dt>Rendimiento</dt><dd>${estado.metricas_recursos
          ? `${estado.metricas_recursos.imagenes_por_minuto ?? 0} img/min · batch ${estado.metricas_recursos.batch_actual ?? "—"} · ${estado.metricas_recursos.workers_activos ?? 0} workers CPU`
          : "—"}</dd>
        <dt>Cola SOP</dt><dd>${estado.metricas_recursos
          ? `${estado.metricas_recursos.cola_pendiente ?? 0} preparadas · ${estado.metricas_recursos.cola_mb ?? 0} MB · OOM ${estado.metricas_recursos.reintentos_cuda_oom ?? 0} · CPU temporal ${estado.metricas_recursos.derivaciones_cpu ?? 0}`
          : "—"}</dd>
        <dt>Persistencia</dt><dd>${estado.persistencia
          ? `${estado.persistencia.estado_persistencia || estado.persistencia.estado || "—"}${estado.persistencia.pendientes ? ` · ${estado.persistencia.pendientes} pendientes` : ""}${estado.persistencia.error_tipo ? ` · ${estado.persistencia.error_tipo}` : ""}`
          : "—"}</dd>
        ${etiquetaPlantilla && html`<dt>Plantilla</dt><dd class="mono">${etiquetaPlantilla}</dd>`}
        <dt>Inicio</dt><dd>${fmtFecha(estado.iniciado_en)}</dd>
        <dt>Tiempo transcurrido</dt><dd class="reloj-vivo">${fmtDuracion(transcurridoVivo)}</dd>
        ${estado.finalizado_en && html`<dt>Finalización</dt><dd>${fmtFecha(estado.finalizado_en)}</dd>`}
      </dl>
      ${(procesando || pausado) && html`<button class=${`boton ${pausado ? "boton-primario" : ""}`}
        onClick=${alternarPausa}>${pausado ? "Continuar procesamiento" : "Pausar después de esta imagen"}</button>`}
      ${pausando && html`<button class="boton" disabled>Pausando después de esta imagen…</button>`}
      ${(procesando || pausando || pausado) && html`<button class="boton boton-peligro" onClick=${detener}>
        Detener o cancelar…</button>`}
      ${estado.reanudable && !activo && html`<button class="boton boton-primario"
        onClick=${reanudarCheckpoint}>Reanudar avance guardado</button>`}
      ${estado.ultimo_id_nombre && html`<p class="aviso checkpoint-aviso">
        Avance confirmado hasta: <strong>${estado.ultimo_id_nombre}</strong>. Las imágenes sin cambios se recuperarán del caché.
      </p>`}
      ${estado.archivo_excel_parcial && html`<div class="aviso checkpoint-aviso">
        <strong>Excel parcial disponible.</strong>
        ${estado.excel_parcial_actualizado_en ? ` Actualizado: ${fmtFecha(estado.excel_parcial_actualizado_en)}.` : ""}
        <span class="acciones-excel-parcial">
          ${Object.keys(estado.archivos_excel_parcial || {}).length
            ? Object.keys(estado.archivos_excel_parcial || {}).map(idioma => html`
              <a key=${idioma} class="boton boton-compacto"
                href=${`/api/pipeline/excel-parcial?idioma=${encodeURIComponent(idioma)}`} target="_blank">
                ${t("Abrir")} ${idioma.toUpperCase()}</a>`)
            : html`<a class="boton boton-compacto" href="/api/pipeline/excel-parcial" target="_blank">
                Abrir Excel parcial</a>`}
        </span>
      </div>`}
      ${estado.advertencia_excel_parcial && html`<div class="aviso alerta-warning" role="alert">
        <strong>El OCR y su checkpoint continúan seguros.</strong> ${estado.advertencia_excel_parcial}
      </div>`}
      ${(estado.advertencias_cache || []).length > 0 && html`<details class="aviso alerta-warning">
        <summary>Advertencias de persistencia (${estado.advertencias_cache.length})</summary>
        ${(estado.advertencias_cache || []).map((mensaje, indice) => html`
          <p key=${indice} class="mono">${mensaje}</p>`)}
      </details>`}
      ${estado.error && html`<div class="mensaje-error" role="alert">
        <strong>Error:</strong> ${estado.error}
        ${estado.bitacora && html`<div class="mono">Bitácora: ${estado.bitacora}</div>`}
      </div>`}
      ${estado.estado === "completado" && html`<div class="acciones-revision-video">
        <a class="boton boton-primario" href="#/resumen">Ver resultados actualizados →</a>
        <button type="button" class="boton" onClick=${reanalizarSoloVideos}
          disabled=${activo || reanalisisVideoActivo}>
          ${reanalisisVideoActivo ? "Reanalizando videos…" : "↻ Reanalizar sólo videos"}
        </button>
        <small>No repite OCR de imágenes y conserva zonas, dataset y revisiones manuales.</small>
      </div>`}
      ${reanalisisVideos && reanalisisVideos.estado !== "inactivo" && html`<div class=${`aviso ${reanalisisVideos.estado === "error" ? "aviso-error" : ""}`}>
        <strong>Reanálisis de video:</strong> ${reanalisisVideos.mensaje || reanalisisVideos.estado}.
        ${totalVideosReanalisis > 0 ? ` ${videosReanalizados}/${totalVideosReanalisis} videos (${porcentajeReanalisis.toFixed(0)}%).` : ""}
        ${reanalisisVideos.video_actual ? html` <span class="mono">${reanalisisVideos.video_actual}</span>` : ""}
        ${reanalisisVideos.algoritmo ? html` <span>· algoritmo ${reanalisisVideos.algoritmo}</span>` : ""}
        ${reanalisisVideos.ultimo_error ? html`<div class="mensaje-error">${reanalisisVideos.ultimo_error}</div>` : ""}
      </div>`}
      ${errorReanalisisVideos && html`<div class="mensaje-error" role="alert">${errorReanalisisVideos}</div>`}
    </div>

    ${dialogoDetencion && html`<div class="modal-fondo" role="presentation"
      onClick=${(e) => { if (e.target === e.currentTarget) setDialogoDetencion(false); }}>
      <section class="modal-detencion" role="dialog" aria-modal="true" aria-labelledby="titulo-detencion">
        <h3 id="titulo-detencion">¿Cómo deseas detener el análisis?</h3>
        <p>Todo resultado terminado y el caché por imagen se conservarán para reanudar sin repetir OCR válido.</p>
        <div class="acciones-modal">
          <button type="button" class="boton" onClick=${() => setDialogoDetencion(false)}>Continuar</button>
          <button type="button" class="boton boton-peligro"
            onClick=${() => confirmarDetencion("conservar_avance")}>Cancelar y conservar avance</button>
          <button type="button" class="boton boton-primario"
            onClick=${() => confirmarDetencion("fin_id")}>Detener al finalizar la carpeta/ID actual</button>
        </div>
      </section>
    </div>`}

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
            <td data-etiqueta="Estado">${fila.estado || fila.semaforo || "sin clasificar"}
              <a class="boton boton-compacto" href=${fila.enlace}>Ver detalle del ID</a></td>
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
  const [accionSupervision, setAccionSupervision] = useState("guardar_sin_entrenar");
  const [region, setRegion] = useState(null);
  const [textoRegion, setTextoRegion] = useState("");
  const [entrenarRegion, setEntrenarRegion] = useState(false);
  const [resultadoRegion, setResultadoRegion] = useState(null);
  const [guardandoRegion, setGuardandoRegion] = useState(false);
  const [motivoSinDatos, setMotivoSinDatos] = useState("");
  const seleccionada = unidades.find((u) => u.unidad_id === unidadId) || unidades[0];
  const completada = prueba.revision?.estado === "completada";
  const itemExterno = {
    id: prueba.id, nombre: prueba.imagen, ruta: prueba.imagen,
    ruta_api: prueba.ruta_api, ruta_api_visual: prueba.ruta_api_visual,
    ruta_api_orientada: prueba.ruta_api_orientada,
    resultado_ocr: prueba, anotaciones: prueba.anotaciones || [],
    correcciones: prueba.correcciones || [],
    rotacion_manual_preferida_grados: prueba.rotacion_manual_preferida_grados,
    rotacion_manual_definida: prueba.rotacion_manual_definida,
    rotacion_pendiente: prueba.rotacion_pendiente,
    revision_sin_datos: prueba.revision_sin_datos,
  };
  useEffect(() => {
    const sugerida = lecturaSugerida();
    setUnidadId(sugerida?.unidad_id || "");
    setTextoCorrecto(prueba.tipo === "codigo" ? (prueba.esperado || "") : textoVisible(sugerida));
    setRespuesta(null);
    if (prueba.revision?.estado === "completada") setModoEdicion(false);
  }, [prueba.id]);

  function seleccionar(unidad) {
    const exacta = unidades.find((item) => firmaUnidad(item) === firmaUnidad(unidad)) || unidad;
    setUnidadId(exacta.unidad_id || "");
    setTextoCorrecto(textoVisible(exacta));
    setModoEdicion(true);
  }

  async function corregir(e, accionForzada = null) {
    e.preventDefault();
    setGuardando(true);
    setRespuesta(null);
    try {
      const resultado = await enviarJSON("/api/externas/correcciones", {
        prueba_id: prueba.id, texto_ocr: textoUnidad(seleccionada),
        texto_correcto: accionForzada === "aceptar" ? textoVisible(seleccionada) : textoCorrecto, bbox: seleccionada?.bbox || null,
        accion: accionForzada || (accionSupervision === "aceptar" && textoCorrecto === textoVisible(seleccionada) ? "aceptar" : "corregir"),
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
  async function confirmarRegion(e) {
    e.preventDefault();
    if (!region) return;
    setGuardandoRegion(true);
    setResultadoRegion(null);
    try {
      const resultado = await enviarJSON("/api/externas/regiones", {
        prueba_id: prueba.id, bbox: region, texto_correcto: textoRegion,
        proponer_entrenamiento: true,
      });
      setResultadoRegion({ ok: true, resultado });
      setRegion(null);
      setTextoRegion("");
      setEntrenarRegion(false);
      await alActualizarRevision();
    } catch (error) {
      setResultadoRegion({ ok: false, mensaje: error.message });
    } finally {
      setGuardandoRegion(false);
    }
  }
  async function rotar(grados, usarAutomatico = false) {
    setGuardando(true);
    setRespuesta(null);
    try {
      const resultado = await enviarJSON("/api/aprendizaje/rotaciones", {
        tipo: "externa", prueba_id: prueba.id, imagen_id: null, grados, usar_automatico: usarAutomatico,
      });
      setRespuesta({ ok: true, rotacion: true, resultado });
      await alActualizarRevision();
    } catch (error) {
      setRespuesta({ ok: false, mensaje: error.message });
    } finally {
      setGuardando(false);
    }
  }
  async function marcarSinDatos(_imagen, restaurar = false) {
    setGuardando(true);
    setRespuesta(null);
    try {
      const resultado = await enviarJSON(restaurar ? "/api/imagenes/con-texto" : "/api/imagenes/sin-datos", {
        tipo: "externa", prueba_id: prueba.id, imagen_id: null,
        motivo: motivoSinDatos.trim() || null,
      });
      setRespuesta({ ok: true, sinDatos: true, resultado });
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
  return html`<article class="tarjeta tarjeta-externa">
    <div class="externa-cabecera">
      <div><p class="sobrelinea">${prueba.imagen} · ${prueba.tipo}</p>
        <h3>${prueba.tipo === "codigo" ? prueba.esperado : "Texto de escena"}</h3></div>
      <span class=${`chip revision-${prueba.revision?.estado || "por_revisar"}`}>
        <span class="punto"></span>${etiquetaRevision(prueba.revision?.estado)}
      </span>
    </div>
    <${PanelImagen} titulo=${`${prueba.tipo} · ${prueba.imagen}`} item=${itemExterno}
      vacio="Imagen compleja no disponible." edicionActiva=${modoEdicion && !completada}
      rotacionActiva=${!completada} onSelectText=${(_item, unidad) => seleccionar(unidad)}
      onRotate=${(_item, grados, usarAutomatico) => rotar(grados, usarAutomatico)} onMarkNoData=${marcarSinDatos} />
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
    ${modoEdicion && !completada && html`<div class="aprendizaje-panel herramientas-externas">
      <div><p class="sobrelinea">APRENDIZAJE SUPERVISADO</p>
        <h3 class="titulo-seccion">Corregir una lectura</h3>
        <p class="subtitulo-seccion">Selecciona un renglón y confirma su texto. Guardarlo
          prepara el dato; el aprendizaje inmediato se usa desde la siguiente imagen similar y el ajuste visual se programa automáticamente.</p>
      </div>
      <${MiniVisorCorreccion} item=${itemExterno} unidad=${seleccionada}
        textoReferencia=${textoCorrecto} onSelectText=${seleccionar} />
      ${unidades.length > 0 ? html`<form class="formulario-correccion formulario-externo" onSubmit=${corregir}>
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
        <select class="campo control-compatibilidad" aria-hidden="true" tabIndex="-1" value=${accionSupervision}
          onChange=${(e) => setAccionSupervision(e.target.value)} style=${{display:"none"}}>
          <option value="guardar_sin_entrenar">Compatibilidad</option><option value="aceptar">Aceptar lectura OCR</option>
        </select>
        <div class="acciones-correccion-simple">
          <button type="button" class="boton" disabled=${guardando || !seleccionada}
            onClick=${(e) => corregir(e, "aceptar")}>${guardando ? "Guardando…" : "Aceptar lectura"}</button>
          <button type="submit" class="boton boton-primario" disabled=${guardando || !textoCorrecto.trim()}>
            ${guardando ? "Guardando…" : "Aplicar corrección"}</button>
          <${AyudaAprendizaje} />
        </div>
      </form>` : html`<p class="subtitulo-seccion">No hay una lectura OCR previa; puedes añadirla como texto omitido.</p>`}

      <div class="separador-panel"></div>
      <label class="motivo-sin-datos"><strong>Motivo opcional para “Imagen sin datos”</strong>
        <input class="campo" value=${motivoSinDatos} maxLength=${512}
          onInput=${(e) => setMotivoSinDatos(e.target.value)}
          placeholder="Ej. fotografía de contexto, sin etiqueta ni código" />
      </label>
      <div class="separador-panel"></div>
      <div><p class="sobrelinea">TEXTO OMITIDO</p>
        <h3 class="titulo-seccion">Marcar una zona que el OCR no encontró</h3>
        <p class="subtitulo-seccion">Arrastra sobre la fotografía y transcribe todo el contenido,
          respetando espacios y saltos. También se agregará al Excel.</p>
      </div>
      <form class="formulario-region" onSubmit=${confirmarRegion}>
        <${SelectorRegion} item=${itemExterno} valor=${region} onChange=${setRegion}
          onSelectText=${seleccionar} />
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
          <${AyudaAprendizaje} texto="El texto nuevo confirmado se incorpora automáticamente al aprendizaje visual y puede ayudar a las siguientes imágenes similares." />
          <button class="boton boton-primario"
            disabled=${guardandoRegion || !region || !textoRegion.trim()}>
            ${guardandoRegion ? "Guardando…" : "Guardar región y actualizar Excel"}
          </button>
        </div>
      </form>
      ${resultadoRegion?.ok && html`<div class="aviso"><strong>Región guardada.</strong>
        ${resultadoRegion.resultado.excel_pendiente
          ? " Actualización del Excel solicitada; consulta su estado arriba."
          : resultadoRegion.resultado.excel_actualizado
          ? " El Excel maestro fue actualizado."
          : ` La anotación está segura; el Excel no pudo actualizarse: ${resultadoRegion.resultado.advertencia_excel || "error desconocido"}.`}
      </div>`}
      ${resultadoRegion && !resultadoRegion.ok && html`<div class="mensaje-error">${resultadoRegion.mensaje}</div>`}

      ${((prueba.correcciones || []).length > 0 || (prueba.anotaciones || []).length > 0) && html`
        <details class="historial-aprendizaje">
          <summary>Lista de aprendizaje supervisado (${(prueba.correcciones || []).length + (prueba.anotaciones || []).length}) · desplegar / ocultar</summary>
          ${(prueba.correcciones || []).map((item) => html`<div key=${`c-${item.id}`} class="evidencia-aprendizaje">
            <span class="chip neutro">Corrección OCR</span><strong class="mono">${item.texto_correcto}</strong>
            ${item.texto_ocr !== item.texto_correcto && html`<small class="mono">Antes: ${item.texto_ocr}</small>`}
            <small>${prueba.imagen}${item.bbox ? ` · región ${item.bbox.join(", ")}` : ""}</small>
          </div>`)}
          ${(prueba.anotaciones || []).map((item) => html`<div key=${`a-${item.id}`} class="evidencia-aprendizaje">
            <span class="chip neutro">Texto omitido</span><strong class="mono">${item.texto_correcto}</strong>
            <small>${prueba.imagen} · región ${item.bbox.join(", ")}</small>
          </div>`)}
        </details>`}
    </div>`}
    ${respuesta?.ok && html`<div class="aviso">${respuesta.revision
      ? "Estado de revisión actualizado."
      : respuesta.rotacion ? respuesta.resultado.mensaje
      : respuesta.sinDatos ? respuesta.resultado.mensaje
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
      <div class="icono"><${Icono} tipo="documento" /></div><h2>Las imágenes están listas para evaluarse</h2>
      <p>Usa “Volver a ejecutar las pruebas” para generar sus lecturas y métricas.</p>
    </div>`}
    ${!caso && html`<p class="subtitulo-seccion pie-datos">Fuentes: ${(datos.fuentes || []).map((fuente, i) => html`
      <span key=${fuente.url}>${i ? " · " : ""}<a href=${fuente.url} target="_blank" rel="noreferrer">
        ${fuente.nombre}</a> (${fuente.licencia})</span>`)}</p>`}
  `;
}

function VistaTabla() {
  const [focoInicial] = useState(() => {
    try { return JSON.parse(sessionStorage.getItem("foco_listado") || "null"); }
    catch (_) { return null; }
  });
  const [focoId, setFocoId] = useState(focoInicial?.id || null);
  const [consulta, setConsulta] = useState(focoInicial?.query || "");
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

  useEffect(() => {
    const id = setInterval(() => {
      pedirJSON(rutaFilas).then(setFilas).catch(() => {});
    }, 1200);
    return () => clearInterval(id);
  }, [rutaFilas]);

  useEffect(() => {
    if (!focoId || !filas?.items?.length || !refTabla.current) return;
    const selector = `tbody tr[data-id="${focoId}"]`;
    const nodo = refTabla.current.querySelector(selector);
    if (!nodo) return;
    nodo.scrollIntoView({ behavior: "smooth", block: "center" });
    nodo.focus();
    try { sessionStorage.removeItem("foco_listado"); } catch (_) {}
    const temporizador = setTimeout(() => setFocoId(null), 3500);
    return () => clearTimeout(temporizador);
  }, [filas, focoId]);

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
      <input class="campo" type="search" placeholder=${t("Buscar por identificador o nomenclatura…")}
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
      <table class="tabla-pruebas" aria-label="Bandeja unificada de revisión">
        <thead><tr>
          <th>Identificador</th><th>Proyecto</th><th>Fotos / videos</th><th>Resultado</th>
          <th>Progreso</th><th>Estado</th><th>Revisión</th><th>Acciones</th>
        </tr></thead>
        <tbody>
          ${filas.items.map((f) => html`<tr key=${f.id} tabIndex=${0} data-id=${f.id}
            class=${focoId === f.id ? "fila-foco-matriz" : ""}
            aria-label=${`Abrir detalle de ${f.identificador || f.nombre}`}
            onClick=${() => { location.hash = f.enlace || `#/detalle/${encodeURIComponent(f.id)}`; }}>
            <td data-etiqueta="Identificador"><strong>${f.identificador || f.nombre}</strong></td>
            <td data-etiqueta="Proyecto">${f.origen === "externa" ? "Prueba compleja" : html`
              <strong>${f.tipo_st || "—"} · ${f.temperature_condition || "—"}</strong><br />
              <small>${f.module_version || "—"} · ${f.inflator_type || "—"}</small>`}</td>
            <td class="celda-fotos" data-etiqueta="Fotos">${f.origen === "externa" ? "1" : html`
              <div class="celda-fotos-contenido">
                <strong>${f.total_imagenes || 0} total</strong>
                <small class="desglose-fotos">
                  <span>NACH ${f.imagenes_nach || 0}</span><span>VOR ${f.imagenes_vor || 0}</span>
                  <span>TOR ${(f.carpetas_tor || []).length}</span><span>VIDEO ${f.total_videos || 0}</span>
                </small>
              </div>`}</td>
            <td data-etiqueta="Resultado">${f.resultado}
              ${(f.alertas || []).length > 0 && html`<span class="indicador-alerta"
                title=${f.alertas.map((a) => a.mensaje).join("\n")}
                aria-label=${`Advertencias: ${f.alertas.map((a) => a.mensaje).join("; ")}`}>
                ⚠ ${f.alertas.length}</span>`}</td>
            <td data-etiqueta="Progreso">${f.origen === "externa" ? "—" : html`
              ${Number(f.progreso?.porcentaje || 0).toFixed(1)}%<br />
              <small>${f.progreso?.con_texto || 0} ${t("con texto")} · ${f.progreso?.sin_texto || 0} ${t("descartadas")}<br />
              ${f.campos_encontrados || 0} ${t("campos")} · ${f.campos_faltantes || 0} ${t("faltantes")} ·
              ${f.conflictos || 0} ${t("conflictos")}</small>`}</td>
            <td data-etiqueta="Estado"><${ChipSemaforo} color=${f.semaforo} colores=${colores}>
              ${f.semaforo || "sin clasificar"}</${ChipSemaforo}>
              ${f.origen !== "externa" && html`<br /><small>${t(f.estado_deteccion || "—")} ·
                ${t(f.estado || "detectada")}</small>`}</td>
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
      <div class="icono"><${Icono} tipo="lista" /></div><h2 style=${{ margin: 0 }}>Sin resultados para el filtro actual</h2>
    </div>`}
    <p class="subtitulo-seccion" style=${{ marginTop: 10 }}>
      Navegación por teclado: <kbd>↑</kbd>/<kbd>↓</kbd> mueve entre filas, <kbd>Enter</kbd> abre el detalle.</p>
    </div>
  `;
}

function MiniVisorCorreccion({ item, unidad, textoReferencia, onSelectText }) {
  const [zoom, setZoom] = useState(100);
  const marcoRef = useRef(null);
  const arrastreRef = useRef(null);
  const ocr = item?.resultado_ocr || {};
  const dimensiones = ocr.dimensiones || [1, 1];
  const detectadas = unidadesOcr(ocr).filter((linea) => linea.bbox);
  const limitar = (valor) => Math.min(500, Math.max(100, Math.round(valor)));
  const cambiarZoom = (valor) => setZoom(limitar(valor));
  function alRueda(evento) {
    evento.preventDefault();
    cambiarZoom(zoom + (evento.deltaY < 0 ? 25 : -25));
  }
  function iniciarArrastre(evento) {
    const marco = marcoRef.current;
    if (!marco || zoom <= 100 || evento.button !== 0 || evento.target.closest("button")) return;
    marco.setPointerCapture(evento.pointerId);
    arrastreRef.current = { x: evento.clientX, y: evento.clientY,
      izquierda: marco.scrollLeft, arriba: marco.scrollTop };
    marco.classList.add("arrastrando");
  }
  function moverArrastre(evento) {
    const marco = marcoRef.current;
    const inicio = arrastreRef.current;
    if (!marco || !inicio) return;
    marco.scrollLeft = inicio.izquierda - (evento.clientX - inicio.x);
    marco.scrollTop = inicio.arriba - (evento.clientY - inicio.y);
  }
  function terminarArrastre() {
    marcoRef.current?.classList.remove("arrastrando");
    arrastreRef.current = null;
  }
  function restablecer() {
    setZoom(100);
    marcoRef.current?.scrollTo({ left: 0, top: 0, behavior: "smooth" });
  }
  function estiloCaja(bbox) {
    return { left: `${bbox[0] / dimensiones[0] * 100}%`,
      top: `${bbox[1] / dimensiones[1] * 100}%`,
      width: `${bbox[2] / dimensiones[0] * 100}%`,
      height: `${bbox[3] / dimensiones[1] * 100}%` };
  }
  return html`<aside class="mini-visor-correccion" aria-label="Previsualización de la corrección">
    <div class="mini-visor-cabecera">
      <div><strong>Imagen asociada</strong><small>${item?.nombre || "Imagen"}</small></div>
      <span class="chip neutro">${zoom}%</span>
      <button type="button" class="boton boton-compacto" aria-label="Alejar previsualización"
        onClick=${() => cambiarZoom(zoom - 50)}>−</button>
      <button type="button" class="boton boton-compacto" aria-label="Acercar previsualización"
        onClick=${() => cambiarZoom(zoom + 50)}>+</button>
      <button type="button" class="boton boton-compacto" onClick=${restablecer}>Restablecer zoom</button>
    </div>
    <div class="mini-visor-marco" ref=${marcoRef} onWheel=${alRueda}
      onPointerDown=${iniciarArrastre} onPointerMove=${moverArrastre}
      onPointerUp=${terminarArrastre} onPointerCancel=${terminarArrastre}>
      <div class="mini-visor-lienzo" style=${{ width: `${zoom}%` }}>
        <img src=${item?.ruta_api_orientada || item?.ruta_api}
          alt=${`Previsualización de ${item?.nombre || "imagen"}`} draggable="false" />
        ${detectadas.map((linea, indice) => html`<button type="button"
          key=${linea.unidad_id || indice}
          class=${`caja-region caja-ocr ${unidadConfirmada(linea, item?.correcciones) ? "caja-corregida" : ""} ${unidad?.unidad_id === linea.unidad_id ? "caja-activa" : ""}`}
          style=${estiloCaja(linea.bbox)} title=${`Seleccionar: ${textoVisible(linea)}`}
          onPointerDown=${(evento) => evento.stopPropagation()}
          onClick=${() => onSelectText?.(linea)}>${unidadConfirmada(linea, item?.correcciones) ? "✓" : ""}</button>`)}
      </div>
    </div>
    <div class="mini-visor-textos">
      <small><strong>OCR original:</strong> ${unidad
        ? (unidad.texto_original || unidad.texto || "—") : "—"}</small>
      <small><strong>Referencia/corrección:</strong> ${textoReferencia || "—"}</small>
    </div>
    <small class="subtitulo-seccion">Rueda para ampliar y arrastra para desplazarte. Las cajas mantienen sus coordenadas reales.</small>
  </aside>`;
}

function EditorUnionZona({ item, pruebaId, valor, poligono = null, onChange, onActualizado, cerrar }) {
  const [propuesta, setPropuesta] = useState(null);
  const [texto, setTexto] = useState("");
  const [entrenarUnion, setEntrenarUnion] = useState(true); // compatibilidad histórica; V14.14 entrena siempre
  const [ocupado, setOcupado] = useState(false);
  useAvisoBorrador(Boolean(propuesta), ocupado, "Unir bloques: hay una propuesta preparada sin confirmar");
  const [mensaje, setMensaje] = useState("");
  const vigente = useRef(0);
  const cajaClave = `${JSON.stringify(valor)}|${JSON.stringify(poligono || null)}`;
  useEffect(() => { vigente.current++; setPropuesta(null); setMensaje(""); setEntrenarUnion(true); }, [item.id, cajaClave]);
  async function preparar(releer = false) {
    if (!valor || ocupado) return;
    const turno = vigente.current;
    setOcupado(true); setMensaje(""); setPropuesta(null);
    try {
      const r = await enviarJSON("/api/aprendizaje/zonas", {
        prueba_id: pruebaId, imagen_id: item.id, bbox: valor, poligono, releer,
      });
      if (turno !== vigente.current) return;
      // La caja propuesta se presenta aparte para no invalidar esta respuesta.
      setPropuesta(r); setTexto(r.texto);
    } catch (e) { if (turno === vigente.current) setMensaje(e.message); }
    finally { setOcupado(false); }
  }
  async function confirmar(deshacer = false) {
    if (ocupado) return;
    setOcupado(true); setMensaje("");
    try {
      let p = propuesta;
      if (deshacer) p = await enviarJSON("/api/aprendizaje/zonas", {
        prueba_id: pruebaId, imagen_id: item.id,
        accion: "estado",
        bbox: valor || [0, 0, ...item.resultado_ocr.dimensiones],
      });
      if (!p) return;
      const resultado = await enviarJSON("/api/aprendizaje/zonas", {
        prueba_id: pruebaId, imagen_id: item.id, bbox: p.bbox, poligono: p.poligono || poligono,
        firma: p.firma, texto, accion: deshacer ? "deshacer" : "guardar",
        proponer_entrenamiento: deshacer ? false : entrenarUnion,
      });
      setPropuesta(null);
      const muestras = Number(resultado?.aprendizaje_union?.nuevas || 0);
      const duplicadas = Number(resultado?.aprendizaje_union?.duplicadas || 0);
      setMensaje(deshacer ? "Última edición deshecha."
        : `Zona guardada. Excel enviado a la cola. Unión incorporada al aprendizaje visual${muestras ? ` (${muestras} muestra${muestras === 1 ? "" : "s"} nueva${muestras === 1 ? "" : "s"})` : duplicadas ? " (ya estaba registrada)" : ""}.`);
      await onActualizado?.();
    } catch (e) { setMensaje(e.message); }
    finally { setOcupado(false); }
  }
  function cerrarEditor() {
    if (ocupado) return;
    if (propuesta && !window.confirm(t("Hay una propuesta sin guardar. ¿Descartarla y cerrar esta herramienta?"))) return;
    setPropuesta(null); setTexto(""); setMensaje("");
    cerrar?.();
  }
  return html`<section class="editor-union-zona">
    <div class="cabecera-editor-herramienta"><h3>Completar o unir texto de una zona</h3>
      <button type="button" class="boton boton-compacto" disabled=${ocupado} onClick=${cerrarEditor}>Cerrar herramienta</button></div>
    ${valor && !propuesta && html`<${HerramientasRegion} key=${cajaClave} item=${item} bbox=${valor} poligono=${poligono} pruebaId=${pruebaId} />`}
    <p>Dibuja una zona o usa “Unir bloques” y pulsa los recuadros. Arrastra las esquinas azules para ajustar el área.</p>
    <div class="acciones-tabla">
      <button class="boton" type="button" disabled=${ocupado || !valor} onClick=${() => preparar(false)}>Unir textos existentes</button>
      <button class="boton" type="button" disabled=${ocupado || !valor} onClick=${() => preparar(true)}>Releer y unir zona</button>
      <button class="boton" type="button" disabled=${ocupado || !item.resultado_ocr?.ediciones_zona?.length}
        onClick=${() => confirmar(true)}>Deshacer última edición</button>
    </div>
    ${ocupado && html`<p role="status">Procesando la zona…</p>`}
    ${propuesta && html`<div>
      <${HerramientasRegion} key=${`${JSON.stringify(propuesta.bbox)}|${JSON.stringify(propuesta.poligono || poligono || null)}`} item=${item} bbox=${propuesta.bbox} poligono=${propuesta.poligono || poligono} pruebaId=${pruebaId} candidatos=${propuesta.candidatos_orientacion || []} onTexto=${setTexto} />
      <p>Se reemplazarán ${propuesta.bloques} bloques al confirmar. Región: ${propuesta.bbox.join(", ")}.</p>
      ${JSON.stringify(propuesta.bbox) !== cajaClave && html`<p class="aviso">El área se amplió para incluir completos los bloques que tocaste. Revisa el alcance antes de confirmar.</p>`}
      <label>Texto anterior<pre class="zona-texto-anterior">${propuesta.anterior || "Sin lectura previa"}</pre></label>
      <label>Propuesta editable — conserva puntos, espacios y saltos
        <textarea class="campo mono" rows="4" maxLength="8192" value=${texto} onChange=${e => setTexto(e.target.value)} />
      </label>
      <${AyudaAprendizaje} texto="Una línea: entrena la zona unida. Varias líneas: intenta separarlas por línea. La unión confirmada siempre se incorpora; los intentos intermedios no." />
      ${/* Compatibilidad histórica: Usar unión para entrenar OCR */ null}
      ${propuesta.orientacion_dudosa && html`<p class="aviso">Orientación dudosa. Compara el texto con la imagen.</p>`}
      <button type="button" class="boton" onClick=${() => setTexto(texto.replace(/\n/g, " "))}>Unir con espacios</button>
      <button type="button" class="boton boton-primario" disabled=${ocupado || !texto.trim()} onClick=${() => confirmar()}>Confirmar reemplazo de bloques</button>
      <button type="button" class="boton" onClick=${() => setPropuesta(null)}>Descartar propuesta</button>
    </div>`}
    ${mensaje && html`<p role="status">${mensaje}</p>`}
  </section>`;
}

// Firma histórica conservada para pruebas/lectores estáticos: function HerramientasRegion({item, bbox, pruebaId = null, onTexto = null, onEstrategia = null, candidatos = []})
function HerramientasRegion({item, bbox, poligono = null, pruebaId = null, onTexto = null, onEstrategia = null, candidatos = []}) {
  const leerPreferencia = (clave, defecto) => { try { return localStorage.getItem(clave) ?? defecto; } catch (_) { return defecto; } };
  const [giroBase, setGiroBase] = useState(0);
  const [usarAjusteFino, setUsarAjusteFino] = useState(true);
  const [filtroLecturas, setFiltroLecturas] = useState("todas");
  const [lecturas, setLecturas] = useState(() => Array.isArray(candidatos) ? candidatos : []);
  const [ocupado, setOcupado] = useState(false);
  const [falloVariantes, setFalloVariantes] = useState(false);
  const [aviso, setAviso] = useState("");
  const [controlAvanzado, setControlAvanzado] = useState(false);
  const [tipoEsperado, setTipoEsperado] = useState(() => leerPreferencia("ocr_tipo_esperado_region", "auto"));
  const [copiarAutomaticamente, setCopiarAutomaticamente] = useState(() => leerPreferencia("ocr_copiar_auto_region", "1") !== "0");
  const [umbralCongruencia, setUmbralCongruencia] = useState(() => Number(leerPreferencia("ocr_umbral_region", "45")) || 45);
  const [ajusteManual, setAjusteManual] = useState(0);
  const [varianteManual, setVarianteManual] = useState("auto");
  const [lecturaManual, setLecturaManual] = useState(null);
  const [ocupadoManual, setOcupadoManual] = useState(false);
  const [vistaManualActiva, setVistaManualActiva] = useState(false);
  const [estrategiaAprendida, setEstrategiaAprendida] = useState(null);
  const [candidataAprendida, setCandidataAprendida] = useState(null);
  const firmaCandidatos = JSON.stringify(Array.isArray(candidatos) ? candidatos : []);
  const poligonoEstable = useDebounce(poligono, 350);
  const clave = `${pruebaId || ""}|${item?.id || ""}|${JSON.stringify(bbox || [])}|${JSON.stringify(poligonoEstable || [])}|${firmaCandidatos}`;

  useEffect(() => {
    try {
      localStorage.setItem("ocr_tipo_esperado_region", tipoEsperado);
      localStorage.setItem("ocr_copiar_auto_region", copiarAutomaticamente ? "1" : "0");
      localStorage.setItem("ocr_umbral_region", String(umbralCongruencia));
    } catch (_) {}
  }, [tipoEsperado, copiarAutomaticamente, umbralCongruencia]);

  useEffect(() => {
    let vivo = true;
    setGiroBase(0);
    setUsarAjusteFino(true);
    setFiltroLecturas("todas");
    setFalloVariantes(false);
    setAviso("");
    setAjusteManual(0);
    setLecturaManual(null);
    setVistaManualActiva(false);
    setEstrategiaAprendida(null);
    setCandidataAprendida(null);
    const recibidas = Array.isArray(candidatos) ? candidatos : [];
    setLecturas(recibidas);
    const tienenCriterioNuevo = recibidas.some(c => Boolean(c?.recomendada));
    if (recibidas.length && tienenCriterioNuevo) {
      const automatica = candidatoOrientacionSegunTipo(recibidas, tipoEsperado) || candidatoOrientacionAutomatica(recibidas);
      const base = ((Number(automatica?.grados || 0) % 360) + 360) % 360;
      const propuesta = propuestaTextoOrientacion({candidatos_orientacion: recibidas}, base, true);
      setGiroBase(base);
      const util = candidatoEsUtil(automatica, umbralCongruencia);
      if (copiarAutomaticamente && util && propuesta.texto && typeof onTexto === "function") onTexto(propuesta.texto);
      setAviso(util
        ? `Orientación sugerida: ${base}°${propuesta.usandoAjusteFino ? ` → ${propuesta.angulo.toFixed(1)}°` : ""}. ${copiarAutomaticamente ? "La orientación se eligió por congruencia antes del ajuste fino. La lectura fue copiada automáticamente a Texto correcto como borrador." : "La copia automática está desactivada; tú decides cuándo usarla."}`
        : `La mejor candidata no alcanza congruencia suficiente con tu mínimo (${umbralCongruencia}/100). Se conserva para revisión sin sustituir Texto correcto.`);
      setOcupado(false);
      return () => { vivo = false; };
    }
    if (!pruebaId || !item?.id || !bbox?.length) {
      if (recibidas.length) {
        const automatica = candidatoOrientacionSegunTipo(recibidas, tipoEsperado) || candidatoOrientacionAutomatica(recibidas);
        const base = ((Number(automatica?.grados || 0) % 360) + 360) % 360;
        setGiroBase(base);
      }
      setOcupado(false);
      return () => { vivo = false; };
    }
    setOcupado(true);
    setFalloVariantes(false);
    enviarJSON("/api/aprendizaje/lecturas-orientacion", {
      prueba_id: pruebaId, imagen_id: item.id, bbox, poligono: poligonoEstable,
    }).then((respuesta) => {
      if (!vivo) return;
      const nuevas = Array.isArray(respuesta.candidatos_orientacion)
        ? respuesta.candidatos_orientacion : [];
      setLecturas(nuevas);
      setEstrategiaAprendida(respuesta.estrategia_aprendida || null);
      setCandidataAprendida(respuesta.candidata_aprendida || null);
      const automatica = candidatoOrientacionSegunTipo(nuevas, tipoEsperado) || candidatoOrientacionAutomatica(nuevas);
      const base = ((Number(automatica?.grados || 0) % 360) + 360) % 360;
      const propuesta = propuestaTextoOrientacion({candidatos_orientacion: nuevas}, base, true);
      setGiroBase(base);
      const util = candidatoEsUtil(automatica, umbralCongruencia);
      if (copiarAutomaticamente && util && propuesta.texto && typeof onTexto === "function") onTexto(propuesta.texto);
      setAviso(nuevas.length
        ? (util
          ? `Orientación sugerida: ${base}°${propuesta.usandoAjusteFino ? ` → ${propuesta.angulo.toFixed(1)}°` : ""}. ${copiarAutomaticamente ? "Lectura copiada automáticamente a Texto correcto como borrador." : "Copia automática desactivada."}`
          : `Hay lecturas, pero ninguna supera tu congruencia mínima (${umbralCongruencia}/100). Revisa o usa la relectura manual.`)
        : "No hubo variantes OCR utilizables; puedes escribir la corrección manualmente.");
    }).catch((error) => {
      if (!vivo) return;
      setLecturas([]);
      setFalloVariantes(true);
      setAviso(`No se pudieron cargar las variantes OCR automáticamente: ${error.message}. Puedes seguir escribiendo la corrección manualmente.`);
    }).finally(() => { if (vivo) setOcupado(false); });
    return () => { vivo = false; };
  }, [clave]);

  const opciones = Array.isArray(lecturas) ? lecturas : [];
  const normalizar = v => ((Number(v) % 360) + 360) % 360;
  const mapa = new Map(opciones.map(c => [normalizar(c.grados), c]));
  const orden = opciones.length ? opciones.map(c => normalizar(c.grados)) : [0, 90, 180, 270];
  [0, 90, 180, 270].forEach(a => { if (!orden.includes(a)) orden.push(a); });
  const tarjetas = orden.slice(0, 4).map(grados => mapa.get(grados) || ({
    grados, grados_efectivos: grados, ajuste_fino_grados: 0, confianza: null, texto: "",
    tipo_informacion:"ruido", etiqueta_informacion:"Sin lectura", score_informacion:0, es_ruido:true
  }));
  const tarjetasVisibles = tarjetas.filter(c => candidatoPasaFiltro(c, filtroLecturas));
  const automaticaPura = candidatoOrientacionAutomatica(opciones);
  const automaticaActual = candidatoOrientacionSegunTipo(opciones, tipoEsperado);
  const candidataResumen = automaticaActual || (tipoEsperado === "auto" ? automaticaPura : null);
  const categoriaAutomatica = categoriaLectura(candidataResumen || {});
  const seleccion = mapa.get(normalizar(giroBase));
  const propuestaSeleccionada = propuestaTextoOrientacion({candidatos_orientacion: opciones}, giroBase, usarAjusteFino);
  const giroVista = vistaManualActiva ? normalizar(giroBase + ajusteManual) : propuestaSeleccionada.angulo;

  function emitirEstrategia(datos) {
    if (typeof onEstrategia !== "function") return;
    if (!datos) { onEstrategia(null); return; }
    onEstrategia({
      orientacion_base: normalizar(datos.orientacion_base ?? giroBase),
      ajuste_manual: Number(datos.ajuste_manual ?? 0),
      variante: datos.variante || "auto", tipo_esperado: datos.tipo_esperado || tipoEsperado,
      texto_resultado: String(datos.texto_resultado || ""),
      confianza: Number(datos.confianza || 0), congruencia: Number(datos.congruencia || 0),
      origen: datos.origen || "revision_humana",
    });
  }

  function estrategiaDesdeCandidata(candidata, propuesta, origen="orientacion_humana") {
    const cat = categoriaLectura(candidata || {});
    return {orientacion_base: normalizar(candidata?.grados ?? giroBase),
      ajuste_manual: Number(propuesta?.ajusteFino || 0), variante:"auto", tipo_esperado:tipoEsperado,
      texto_resultado:String(propuesta?.texto || candidata?.texto || ""), confianza:Number(candidata?.confianza || 0),
      congruencia:Number(cat.score || 0), origen};
  }

  function copiarPropuesta(propuesta, mensaje, estrategia = null) {
    if (propuesta?.texto && typeof onTexto === "function") {
      onTexto(propuesta.texto);
      if (estrategia) emitirEstrategia(estrategia);
      setAviso(mensaje);
      return true;
    }
    setAviso("La lectura elegida está vacía; Texto correcto no se modificó.");
    return false;
  }

  function usarGiroAutomatico() {
    const automatica = candidatoOrientacionSegunTipo(opciones, tipoEsperado) || (tipoEsperado === "auto" ? candidatoOrientacionAutomatica(opciones) : null);
    if (!automatica) {
      setAviso(`No hay una candidata del tipo “${tipoEsperado}”. Cambia “Qué estás buscando” o usa relectura manual.`);
      return;
    }
    const base = normalizar(automatica.grados);
    setUsarAjusteFino(true);
    setVistaManualActiva(false);
    setAjusteManual(0);
    const propuesta = propuestaTextoOrientacion({candidatos_orientacion: opciones}, base, true);
    setGiroBase(base);
    if (candidatoEsUtil(automatica, umbralCongruencia)) {
      copiarPropuesta(propuesta, `Criterio automático aplicado: ${base}°${propuesta.usandoAjusteFino ? ` → ${propuesta.angulo.toFixed(1)}°` : ""}. La lectura quedó como borrador.`,
        estrategiaDesdeCandidata(automatica, propuesta, "criterio_humano"));
    } else {
      setAviso(`La candidata existe, pero su congruencia es menor a ${umbralCongruencia}/100. Puedes usarla manualmente si la imagen confirma que es correcta.`);
    }
  }

  function aplicarModoAjuste(nuevoUsarAjuste) {
    setUsarAjusteFino(nuevoUsarAjuste);
    setVistaManualActiva(false);
    const propuesta = propuestaTextoOrientacion({candidatos_orientacion: opciones}, giroBase, nuevoUsarAjuste);
    copiarPropuesta(propuesta, nuevoUsarAjuste && propuesta.usandoAjusteFino
      ? `Ajuste fino aplicado: ${giroBase}° → ${propuesta.angulo.toFixed(1)}°. La lectura quedó como borrador.`
      : `Se conserva el giro base ${giroBase}° sin ajuste fino. La lectura base quedó como borrador.`,
      estrategiaDesdeCandidata(mapa.get(normalizar(giroBase)), propuesta, "ajuste_humano"));
  }

  function girarBase(grados) {
    const base = normalizar(Math.round(Number(grados) / 90) * 90);
    const propuesta = propuestaTextoOrientacion({candidatos_orientacion: opciones}, base, usarAjusteFino);
    setGiroBase(base);
    setAjusteManual(0);
    setLecturaManual(null);
    setVistaManualActiva(false);
    if (propuesta.texto && typeof onTexto === "function") {
      onTexto(propuesta.texto);
      emitirEstrategia(estrategiaDesdeCandidata(mapa.get(base), propuesta, "giro_humano"));
      const fino = Math.abs(propuesta.ajusteFino) >= 0.05 ? ` (ajuste ${propuesta.ajusteFino > 0 ? "+" : ""}${propuesta.ajusteFino.toFixed(1)}°; vista ${propuesta.angulo.toFixed(1)}°)` : "";
      setAviso(`Tú elegiste ${base}°${fino}. La lectura se copió a Texto correcto como borrador; todavía no se ha guardado.`);
    } else if (ocupado) {
      setAviso(`Vista girada a ${base}°. Las variantes OCR aún se están preparando; Texto correcto no se modificó.`);
    } else {
      setAviso(`Vista girada a ${base}°. No hay lectura utilizable; puedes releer manualmente este ángulo.`);
    }
  }

  function cambiarAjusteManual(valor) {
    const v = Math.max(-45, Math.min(45, Number(valor) || 0));
    setAjusteManual(v);
    setVistaManualActiva(true);
    setLecturaManual(null);
  }

  async function releerAnguloManual() {
    if (!pruebaId || !item?.id || !bbox?.length || ocupadoManual) return;
    setOcupadoManual(true);
    setLecturaManual(null);
    setAviso(`Releyendo exactamente ${normalizar(giroBase + ajusteManual).toFixed(1)}° con ${varianteManual === "auto" ? "comparación de tratamientos" : varianteManual}…`);
    try {
      const r = await enviarJSON("/api/aprendizaje/lectura-angulo-manual", {
        prueba_id: pruebaId, imagen_id: item.id, bbox, poligono,
        orientacion_base: normalizar(giroBase), ajuste_manual: Number(ajusteManual), variante: varianteManual, tipo_esperado: tipoEsperado,
      });
      setLecturaManual(r);
      setVistaManualActiva(true);
      const cat = categoriaLectura(r);
      setAviso(`Relectura manual lista: ${cat.etiqueta}, congruencia ${cat.score.toFixed(0)}/100, confianza OCR ${(Number(r.confianza || 0)*100).toFixed(1)}%. Nada se copió automáticamente.`);
    } catch (e) {
      setAviso(`No se pudo releer este ángulo: ${e.message}`);
    } finally { setOcupadoManual(false); }
  }

  function usarLecturaManual() {
    if (!lecturaManual?.texto) { setAviso("La relectura manual no produjo texto utilizable."); return; }
    onTexto?.(lecturaManual.texto);
    emitirEstrategia({orientacion_base:giroBase, ajuste_manual:Number(lecturaManual.ajuste_manual ?? ajusteManual),
      variante:lecturaManual.variante || varianteManual, tipo_esperado:tipoEsperado,
      texto_resultado:lecturaManual.texto, confianza:lecturaManual.confianza,
      congruencia:categoriaLectura(lecturaManual).score, origen:"relectura_manual"});
    setAviso(`Lectura manual de ${Number(lecturaManual.grados_efectivos || 0).toFixed(1)}° copiada a Texto correcto como borrador. Al aplicar supervisión, esta estrategia también quedará como evidencia de aprendizaje.`);
  }

  function aplicarMejorSegunCriterio() {
    const candidata = candidatoOrientacionSegunTipo(opciones, tipoEsperado);
    if (!candidata) {
      setAviso(`No existe una candidata clasificada como ${tipoEsperado === "auto" ? "útil" : tipoEsperado}. Prueba otro tipo o usa relectura manual.`);
      return;
    }
    const base = normalizar(candidata.grados);
    setGiroBase(base); setVistaManualActiva(false); setAjusteManual(0);
    const propuesta = propuestaTextoOrientacion({candidatos_orientacion: opciones}, base, usarAjusteFino);
    copiarPropuesta(propuesta, `Aplicada la mejor candidata para “${tipoEsperado}”: congruencia ${categoriaLectura(candidata).score.toFixed(0)}/100.`,
      estrategiaDesdeCandidata(candidata, propuesta, "criterio_humano"));
  }

  function usarEstrategiaAprendida() {
    if (!estrategiaAprendida || !candidataAprendida?.texto) {
      setAviso("La estrategia aprendida todavía no produjo una lectura utilizable en esta imagen."); return;
    }
    setGiroBase(normalizar(estrategiaAprendida.orientacion_base || 0));
    setAjusteManual(Number(estrategiaAprendida.ajuste || 0));
    setVarianteManual(estrategiaAprendida.variante || "auto");
    setLecturaManual(candidataAprendida); setVistaManualActiva(true);
    onTexto?.(candidataAprendida.texto);
    emitirEstrategia({orientacion_base:estrategiaAprendida.orientacion_base,
      ajuste_manual:estrategiaAprendida.ajuste, variante:estrategiaAprendida.variante,
      tipo_esperado:estrategiaAprendida.tipo_esperado, texto_resultado:candidataAprendida.texto,
      confianza:candidataAprendida.confianza, congruencia:categoriaLectura(candidataAprendida).score,
      origen:"estrategia_aprendida_reconfirmada"});
    setAviso(`Estrategia aprendida aplicada como borrador (${estrategiaAprendida.soporte} imágenes de soporte). Solo se refuerza si pulsas Aplicar supervisión.`);
  }

  const razonesSeleccion = Array.isArray(seleccion?.razones_congruencia) ? seleccion.razones_congruencia : [];
  const textoBaseSeleccion = String(seleccion?.texto_base ?? seleccion?.texto ?? "");
  const textoFinoSeleccion = String(seleccion?.texto ?? "");

  return html`<section class="herramientas-region herramientas-region-correccion" aria-label="Imagen y variantes de la selección">
    <div class="cabecera-recorte"><div><span class="sobrelinea">SELECCIÓN ACTIVA</span>
      <h3>Revisa la imagen y elige su orientación</h3></div></div>
    <${VistaRecorteZona} item=${item} bbox=${bbox} grados=${giroVista} />
    <div class="acciones-tabla controles-giro-recorte"><button type="button" class="boton" onClick=${()=>girarBase(giroBase-90)}>↶ 90°</button>
      <strong class="angulo-giro-actual">${Math.abs(giroVista - Math.round(giroVista)) < .01 ? Math.round(giroVista) : giroVista.toFixed(1)}°</strong>
      <button type="button" class="boton" onClick=${()=>girarBase(giroBase+90)}>↷ 90°</button>
      <button type="button" class="boton" onClick=${()=>girarBase(0)}>Restablecer giro</button>
      <button type="button" class="boton boton-primario" disabled=${ocupado || !opciones.length}
        onClick=${usarGiroAutomatico}>Usar giro automático según mi criterio</button></div>
    <div class="acciones-tabla selector-ajuste-fino" role="group" aria-label="Elegir ajuste fino">
      <button type="button" class=${`boton ${usarAjusteFino && !vistaManualActiva ? "boton-primario" : ""}`} aria-pressed=${usarAjusteFino && !vistaManualActiva}
        onClick=${()=>aplicarModoAjuste(true)}>Tomar ajuste fino</button>
      <button type="button" class=${`boton ${!usarAjusteFino && !vistaManualActiva ? "boton-primario" : ""}`} aria-pressed=${!usarAjusteFino && !vistaManualActiva}
        onClick=${()=>aplicarModoAjuste(false)}>No tomar ajuste</button>
      ${seleccion && Math.abs(Number(seleccion.ajuste_fino_grados || 0)) >= .05 && html`<small>Base ${normalizar(seleccion.grados)}° · ajuste automático ${Number(seleccion.ajuste_fino_grados) > 0 ? "+" : ""}${Number(seleccion.ajuste_fino_grados).toFixed(1)}°</small>`}
    </div>

    ${estrategiaAprendida && html`<div class=${`aviso estrategia-aprendida nivel-${estrategiaAprendida.nivel || "recordada"}`}>
      <div><strong>Aprendizaje de estrategia OCR</strong>
        <small>${estrategiaAprendida.soporte || 1} imagen(es) de soporte · dominancia ${((Number(estrategiaAprendida.dominancia || 0))*100).toFixed(0)}% · ${estrategiaAprendida.nivel === "automatica" ? "patrón consolidado" : estrategiaAprendida.nivel === "inmediata" ? "aprendizaje inmediato desde la última imagen" : estrategiaAprendida.nivel === "sugerida" ? "patrón sugerido" : "evidencia recordada"}</small>
        <span>Preferencia: ${estrategiaAprendida.orientacion_base || 0}° ${Number(estrategiaAprendida.ajuste || 0) >= 0 ? "+" : ""}${Number(estrategiaAprendida.ajuste || 0).toFixed(1)}° · ${estrategiaAprendida.variante || "auto"} · ${estrategiaAprendida.tipo_esperado || "auto"}</span></div>
      ${candidataAprendida?.texto && html`<button type="button" class="boton" onClick=${usarEstrategiaAprendida}>Probar estrategia aprendida</button>`}
    </div>`}

    <div class="resumen-lectura-inteligente">
      <div><strong>${tipoEsperado === "auto" ? "Mejor opción automática" : `Mejor opción para: ${tipoEsperado}`}</strong>
        ${candidataResumen ? html`<span class=${`chip-tipo-lectura tipo-${categoriaAutomatica.tipo}`}>${categoriaAutomatica.etiqueta}</span>
          <small>Congruencia ${categoriaAutomatica.score.toFixed(0)}/100 · OCR ${(Number(candidataResumen.confianza || 0)*100).toFixed(1)}%${Number(candidataResumen.consenso || 1) > 1 ? ` · consenso ${candidataResumen.consenso}` : ""}</small>` : html`<small>No hay candidata compatible con ese tipo.</small>`}</div>
      <button type="button" class="boton boton-compacto" onClick=${()=>setControlAvanzado(v=>!v)}>${controlAvanzado ? "Ocultar control avanzado" : "Más control sobre OCR"}</button>
    </div>

    ${controlAvanzado && html`<div class="panel-control-ocr-avanzado">
      <div class="control-ocr-grid">
        <label><strong>Qué estás buscando</strong>
          <select class="campo" value=${tipoEsperado} onChange=${e=>setTipoEsperado(e.target.value)}>
            <option value="auto">Automático / no sé</option><option value="codigo">Código</option>
            <option value="fecha">Fecha</option><option value="numero">Número / medición</option><option value="texto">Texto general</option>
          </select></label>
        <label><strong>Congruencia mínima: ${umbralCongruencia}/100</strong>
          <input type="range" min="20" max="90" step="5" value=${umbralCongruencia}
            onChange=${e=>setUmbralCongruencia(Number(e.target.value))} /></label>
        <label class="check-control-ocr"><input type="checkbox" checked=${copiarAutomaticamente}
          onChange=${e=>setCopiarAutomaticamente(e.target.checked)} />
          Copiar automáticamente la sugerencia a Texto correcto</label>
      </div>
      <div class="acciones-tabla"><button type="button" class="boton" disabled=${!candidataResumen}
        onClick=${aplicarMejorSegunCriterio}>Aplicar mejor según este criterio</button></div>

      <div class="separador-control-ocr"></div>
      <strong>Relectura manual — tú mandas el ángulo y el tratamiento</strong>
      <div class="control-angulo-manual">
        <button type="button" class="boton boton-compacto" onClick=${()=>cambiarAjusteManual(ajusteManual-2)}>−2°</button>
        <input type="range" min="-45" max="45" step="1" value=${ajusteManual}
          aria-label="Ajuste angular manual" onChange=${e=>cambiarAjusteManual(e.target.value)} />
        <button type="button" class="boton boton-compacto" onClick=${()=>cambiarAjusteManual(ajusteManual+2)}>+2°</button>
        <strong>${ajusteManual > 0 ? "+" : ""}${Number(ajusteManual).toFixed(0)}°</strong>
        <button type="button" class="boton boton-compacto" onClick=${()=>cambiarAjusteManual(0)}>0°</button>
      </div>
      <small>Vista exacta: base ${giroBase}° ${ajusteManual >= 0 ? "+" : "−"} ${Math.abs(ajusteManual)}° = ${normalizar(giroBase + ajusteManual).toFixed(1)}°. El control manual cubre ±45°; el automático sigue limitado para evitar perseguir ruido.</small>
      <div class="acciones-tabla control-variante-manual">
        <label>Tratamiento visual <select class="campo" value=${varianteManual} onChange=${e=>setVarianteManual(e.target.value)}>
          <option value="auto">Comparar automáticamente</option><option value="original">Original</option>
          <option value="clahe">CLAHE / contraste</option><option value="adaptativa">Binarización adaptativa</option><option value="relieve">Relieve / grabado</option>
        </select></label>
        <button type="button" class="boton boton-primario" disabled=${ocupadoManual || !pruebaId}
          onClick=${releerAnguloManual}>${ocupadoManual ? "Releyendo…" : "Releer este ángulo"}</button>
      </div>
      ${lecturaManual && html`<div class=${`resultado-lectura-manual tipo-${categoriaLectura(lecturaManual).tipo}`}>
        <div><strong>Resultado manual · ${Number(lecturaManual.grados_efectivos || 0).toFixed(1)}° · ${lecturaManual.variante}</strong>
          <small>Congruencia ${categoriaLectura(lecturaManual).score.toFixed(0)}/100 · confianza OCR ${(Number(lecturaManual.confianza || 0)*100).toFixed(1)}%</small></div>
        <pre>${lecturaManual.texto || "Sin lectura"}</pre>
        ${(lecturaManual.razones_congruencia || []).length && html`<small>${lecturaManual.razones_congruencia.join(" · ")}</small>`}
        <div class="acciones-tabla"><button type="button" class="boton boton-primario" disabled=${!lecturaManual.texto} onClick=${usarLecturaManual}>Usar esta lectura</button>
          <button type="button" class="boton" onClick=${()=>setLecturaManual(null)}>Descartar resultado</button></div>
      </div>`}
    </div>`}

    ${seleccion && html`<div class="detalle-candidata-seleccionada">
      <div><strong>Orientación seleccionada: ${normalizar(seleccion.grados)}°</strong>
        <small>Confianza OCR ${(Number(seleccion.confianza || 0)*100).toFixed(1)}% · congruencia ${categoriaLectura(seleccion).score.toFixed(0)}/100</small></div>
      ${razonesSeleccion.length ? html`<small><strong>Por qué:</strong> ${razonesSeleccion.join(" · ")}</small>` : null}
      ${textoBaseSeleccion && textoFinoSeleccion && textoBaseSeleccion !== textoFinoSeleccion && html`<div class="comparacion-base-fino">
        <div><small>Lectura base</small><pre>${textoBaseSeleccion}</pre></div>
        <div><small>Lectura con ajuste</small><pre>${textoFinoSeleccion}</pre></div>
      </div>`}
    </div>`}

    <div class="variantes-orientacion-cabecera">
      <strong>Lecturas por orientación y ajuste fino</strong>
      ${ocupado && html`<small role="status">Calculando 0° / 90° / 180° / 270° y corrigiendo inclinación…</small>`}
    </div>
    <div class="filtros-lectura-inteligente" role="group" aria-label="Filtrar lecturas OCR">
      ${[["todas","Todas"],["utiles","Solo útiles"],["codigo","Códigos"],["datos","Fechas / valores"],["texto","Texto"]].map(([valor,etiqueta]) => html`
        <button type="button" class=${`boton boton-compacto ${filtroLecturas===valor ? "boton-primario" : ""}`}
          aria-pressed=${filtroLecturas===valor} onClick=${()=>setFiltroLecturas(valor)}>${etiqueta}</button>`)}
      <small>${tarjetasVisibles.length} de ${tarjetas.length} orientaciones visibles</small>
    </div>
    <div class="lista-candidatos-orientacion variantes-siempre-visibles">
      ${tarjetasVisibles.map((c) => {
        const disponible = c.confianza !== null && c.confianza !== undefined;
        const base = normalizar(c.grados);
        const efectivo = normalizar(c.grados_efectivos ?? c.grados);
        const fino = Number(c.ajuste_fino_grados || 0);
        const etiquetaAngulo = Math.abs(fino) >= .05 ? `${base}° → ${efectivo.toFixed(1)}°` : `${base}°`;
        return html`<button type="button" class=${`boton candidato-orientacion ${c.recomendada ? "candidato-recomendado" : ""}`}
          disabled=${!disponible} aria-pressed=${giroBase === base && !vistaManualActiva} onClick=${()=>girarBase(base)}
          title=${disponible ? "Elegir esta orientación y copiar su lectura como borrador" : (falloVariantes ? "Lectura no disponible" : "Preparando esta orientación")}>
          <strong>${etiquetaAngulo} · ${disponible ? `${(Number(c.confianza || 0)*100).toFixed(1)}% OCR` : "…"}</strong>
          ${c.recomendada && html`<small class="orientacion-recomendada">★ Recomendada por congruencia</small>`}
          ${(() => { const cat=categoriaLectura(c); return html`<small class=${`chip-tipo-lectura tipo-${cat.tipo}`}>${cat.etiqueta} · congruencia ${cat.score.toFixed(0)}/100</small>`; })()}
          ${categoriaLectura(c).tipo === "codigo" && c.probable_codigo && html`<small class="codigo-probable">Código probable · ${c.tipo_codigo_probable || "formato coherente"}</small>`}
          ${Number(c.consenso || 1) > 1 && html`<small class="consenso-lectura">Consenso con ${c.consenso} variantes</small>`}
          ${Math.abs(fino) >= .05 && html`<small class="ajuste-fino-etiqueta">Ajuste ${c.ajuste_fino_modo === "extendido" ? "extendido por geometría" : "fino"} ${fino > 0 ? "+" : ""}${fino.toFixed(1)}° · base ${(Number((c.confianza_base ?? c.confianza) || 0)*100).toFixed(1)}%</small>`}
          <span>${disponible ? (c.texto || "Sin lectura") : (falloVariantes ? "No disponible" : "Calculando…")}</span></button>`;
      })}
      ${!tarjetasVisibles.length && html`<p class="aviso">No hay lecturas en este filtro. Pulsa “Todas” para revisar las cuatro orientaciones.</p>`}
    </div>
    <small role="status">${aviso || "Nada se guarda por elegir una variante. El ajuste automático normal sigue en ±15° y solo puede extenderse hasta ±30° con evidencia geométrica. Solo se guarda al pulsar Aplicar supervisión."}</small>
  </section>`;
}

function VistaRecorteZona({item, bbox, grados = 0}) {
  const [zoom, setZoom] = useState(100);
  const [x,y,w,h] = bbox;
  const rad = Math.abs(Number(grados) || 0) * Math.PI / 180;
  const redondearVista = v => Math.round(v * 1000) / 1000;
  const ancho = Math.max(1, redondearVista(Math.abs(w * Math.cos(rad)) + Math.abs(h * Math.sin(rad))));
  const alto = Math.max(1, redondearVista(Math.abs(w * Math.sin(rad)) + Math.abs(h * Math.cos(rad))));
  const dimensiones = item.resultado_ocr.dimensiones;
  return html`<div>
    <div class="acciones-tabla"><button type="button" class="boton" onClick=${()=>setZoom(Math.max(100,zoom-25))}>−</button>
      <span>${zoom}%</span><button type="button" class="boton" onClick=${()=>setZoom(Math.min(400,zoom+25))}>+</button>
      <button type="button" class="boton" onClick=${()=>setZoom(100)}>Restablecer zoom del recorte</button></div>
    <div class="vista-recorte-zona"><svg viewBox=${`0 0 ${ancho} ${alto}`} role="img" aria-label="Región ajustada en la orientación elegida"
      style=${{width:`${zoom}%`,maxWidth:"none",display:"block"}}>
      <g transform=${`translate(${ancho/2} ${alto/2}) rotate(${grados}) translate(${-w/2} ${-h/2})`}>
        <svg width=${w} height=${h} viewBox=${`${x} ${y} ${w} ${h}`} overflow="hidden">
          <image href=${item.ruta_api_orientada || item.ruta_api} width=${dimensiones[0]} height=${dimensiones[1]} />
        </svg>
      </g></svg></div>
  </div>`;
}

// Compatibilidad histórica V14.13: “Usar geometría final para entrenar OCR” y proponer_entrenamiento:entrenarAjuste.
function EditorDimensionBloque({ item, pruebaId, origen, regiones, setRegiones, activa, activar, onActualizado, cerrar }) {
  const [firma, setFirma] = useState("");
  const [ocupado, setOcupado] = useState(false);
  useAvisoBorrador(true, ocupado, "Ajustar/dividir bloque: hay cambios de geometría o texto pendientes de guardar");
  const [mensaje, setMensaje] = useState("");
  const [entrenarAjuste, setEntrenarAjuste] = useState(true); // compatibilidad; V14.14 entrena siempre
  const vigente = useRef("");
  vigente.current = JSON.stringify(regiones.map(r => ({bbox:r.bbox,poligono:r.poligono||null})));
  useEffect(() => {
    let vivo = true;
    enviarJSON("/api/aprendizaje/zonas", {prueba_id:pruebaId, imagen_id:item.id, bbox:origen, accion:"estado"})
      .then(r => { if (vivo) setFirma(r.firma); }).catch(e => { if (vivo) setMensaje(e.message); });
    return () => { vivo = false; vigente.current = "cerrado"; };
  }, []);
  function modificar(i, cambios) { setRegiones(rs => rs.map((r,j) => i === j ? {...r,
    ...((cambios.bbox || Object.prototype.hasOwnProperty.call(cambios,"poligono")) ? {candidatos:[],giro:0,textoAutomatico:null} : {}), ...cambios} : r)); }
  function elegirOrientacion(i, grados, usarAjuste = null) {
    const r = regiones[i];
    const usarFino = usarAjuste === null ? r.usarAjusteFino !== false : Boolean(usarAjuste);
    const base = ((Math.round(Number(grados) / 90) * 90) % 360 + 360) % 360;
    const propuesta = propuestaTextoOrientacion({candidatos_orientacion:r.candidatos}, base, usarFino);
    if (propuesta.texto && r.texto && r.texto !== r.textoAutomatico && r.texto !== propuesta.texto &&
        !window.confirm("Hay texto escrito manualmente. ¿Sustituirlo por esta lectura?")) return false;
    modificar(i,{giroBase:base,giro:propuesta.angulo,usarAjusteFino:usarFino,confirmado:false,
      ...(propuesta.texto ? {texto:propuesta.texto,textoAutomatico:propuesta.texto} : {})});
    if (!propuesta.texto) setMensaje("No hay lectura para este giro. Pulsa Releer esta región para comparar orientaciones.");
    return true;
  }
  function usarGiroAutomaticoRegion(i) {
    const r = regiones[i];
    const automatica = candidatoOrientacionAutomatica(r?.candidatos || []);
    if (!automatica) {
      setMensaje("Todavía no hay una orientación automática para esta región. Pulsa Releer esta región primero.");
      return;
    }
    const base = ((Number(automatica.grados || 0) % 360) + 360) % 360;
    if (elegirOrientacion(i, base, true)) {
      const propuesta = propuestaTextoOrientacion({candidatos_orientacion:r.candidatos}, base, true);
      setMensaje(`Giro automático restaurado en la región ${i+1}: ${base}°${propuesta.usandoAjusteFino ? ` → ${propuesta.angulo.toFixed(1)}° con ajuste fino` : ""}.`);
    }
  }
  async function releer(i) {
    const clave = vigente.current;
    setOcupado(true); setMensaje("");
    try {
      const r = await enviarJSON("/api/aprendizaje/zonas", {prueba_id:pruebaId, imagen_id:item.id,
        bbox:regiones[i].bbox, poligono:regiones[i].poligono || null, exacta:true, releer:true});
      if (clave !== vigente.current) { setMensaje("La región cambió: vuelve a releerla."); return; }
      if (firma !== r.firma) throw new Error("El resultado cambió. Cierra este editor y selecciona de nuevo el bloque.");
      const candidatos = r.candidatos_orientacion || [];
      const base = Number(r.orientacion_grados || 0);
      const propuesta = propuestaTextoOrientacion({candidatos_orientacion:candidatos}, base, true);
      modificar(i, {texto:r.texto, textoAutomatico:r.texto, confirmado:false,
        candidatos, giroBase:base, giro:propuesta.angulo, usarAjusteFino:true});
      setMensaje(r.orientacion_dudosa ? "Orientación dudosa: revisa el texto antes de confirmarlo." : "Lectura propuesta; confirma su contenido.");
    } catch(e) { setMensaje(e.message); } finally { setOcupado(false); }
  }
  async function guardar() {
    setOcupado(true); setMensaje("");
    try {
      const resultado = await enviarJSON("/api/aprendizaje/zonas", {prueba_id:pruebaId, imagen_id:item.id, bbox:origen,
        accion:"guardar_bloque", origen, firma, proponer_entrenamiento:true,
        regiones:regiones.map(r=>({bbox:r.bbox,texto:r.texto,poligono:r.poligono||null,
          orientacion_base:Number(r.giroBase||0), ajuste:Number(r.giro||0)-Number(r.giroBase||0), variante:"auto", tipo_esperado:"auto"}))});
      const n=Number(resultado?.muestras_nuevas||0), d=Number(resultado?.muestras_duplicadas||0);
      setMensaje(n ? `Geometría guardada y añadida al aprendizaje (${n} muestra${n===1?"":"s"} nueva${n===1?"":"s"}).`
        : d ? "Geometría guardada; sus muestras ya estaban en el aprendizaje." : "Geometría guardada para aprendizaje.");
      await onActualizado?.(); cerrar();
    } catch(e) { setMensaje(e.message); } finally { setOcupado(false); }
  }
  return html`<section class="editor-union-zona">
    <div class="cabecera-editor-herramienta"><h3>Editar bloque</h3>
      <button type="button" class="boton boton-compacto" disabled=${ocupado} onClick=${cerrar}>Cerrar herramienta</button></div>
    <p>Solo se sustituye el bloque elegido. Los vecinos conservan sus recuadros y textos. Selecciona una región aquí y ajusta sus esquinas o dibújala de nuevo en la imagen.</p>
    ${regiones.length === 1 && html`<button type="button" class="boton" disabled=${ocupado} onClick=${() => {
      const [x,y,w,h] = regiones[0].bbox;
      const mitad = Math.floor(w/2);
      if (mitad < 2) { setMensaje("Amplía primero el ancho a 4 píxeles o más."); return; }
      const polis = dividirPoligonoVertical(regiones[0].poligono);
      setRegiones([{bbox:[x,y,mitad,h],poligono:polis?.[0]||null,texto:"",confirmado:false,giroBase:0,giro:0,usarAjusteFino:true},
        {bbox:[x+mitad,y,w-mitad,h],poligono:polis?.[1]||null,texto:"",confirmado:false,giroBase:0,giro:0,usarAjusteFino:true}]);
      activar(0, [x,y,mitad,h]);
    }}>Dividir en dos regiones</button>`}
    ${regiones.map((r,i) => html`<div key=${i} class="zona-dimension-fila">
      <button type="button" class="boton" aria-pressed=${activa===i} disabled=${ocupado} onClick=${()=>activar(i,r.bbox)}>Editar región ${i+1}</button>
      <small> ${r.bbox.join(", ")} · ${r.confirmado ? "Confirmada para guardar" : "Pendiente de confirmar"}</small>
      <${VistaRecorteZona} item=${item} bbox=${r.bbox} grados=${r.giro || 0} />
      <div class="acciones-tabla">
        <button type="button" class="boton" disabled=${ocupado} onClick=${()=>elegirOrientacion(i,(r.giroBase || 0)-90)}>↶ 90°</button>
        <span>${Number(r.giro || 0).toFixed(Math.abs(Number(r.giro || 0)-Math.round(Number(r.giro || 0)))>.01?1:0)}°</span>
        <button type="button" class="boton" disabled=${ocupado} onClick=${()=>elegirOrientacion(i,(r.giroBase || 0)+90)}>↷ 90°</button>
        <button type="button" class=${`boton ${r.usarAjusteFino !== false ? "boton-primario" : ""}`} disabled=${ocupado}
          onClick=${()=>elegirOrientacion(i,r.giroBase || 0,true)}>Tomar ajuste fino</button>
        <button type="button" class=${`boton ${r.usarAjusteFino === false ? "boton-primario" : ""}`} disabled=${ocupado}
          onClick=${()=>elegirOrientacion(i,r.giroBase || 0,false)}>No tomar ajuste</button>
        <button type="button" class="boton boton-primario" disabled=${ocupado || !(r.candidatos || []).length}
          onClick=${()=>usarGiroAutomaticoRegion(i)}>Usar giro automático</button>
      </div>
      <div class="lista-candidatos-orientacion">${(r.candidatos || []).map(c=>html`<button type="button" class="boton candidato-orientacion"
        disabled=${ocupado} aria-pressed=${(r.giroBase || 0)===c.grados} onClick=${()=>elegirOrientacion(i,c.grados)}>
        <strong>${c.grados}° · ${(c.confianza*100).toFixed(1)}%</strong><span>${c.texto || "Sin lectura"}</span></button>`)}</div>
      <div class="acciones-tabla">${["X","Y","Ancho","Alto"].map((label,k)=>html`<label>${label}<input type="number" class="campo"
        value=${r.bbox[k]} disabled=${ocupado} min=${k<2?0:2} onChange=${e=>{
          const b=[...r.bbox]; b[k]=Math.round(Number(e.target.value));
          const [w,h]=item.resultado_ocr.dimensiones;
          if (!Number.isFinite(b[k]) || b[0]<0 || b[1]<0 || b[2]<2 || b[3]<2 || b[0]+b[2]>w || b[1]+b[3]>h) return;
          modificar(i,{bbox:b,confirmado:false}); activar(i,b);
        }} /></label>`)}</div>
      <div class="acciones-tabla" aria-label="Mover región sin cambiar su tamaño">
        <span>Mover región · 5 px</span>${[["←",-5,0],["↑",0,-5],["↓",0,5],["→",5,0]].map(([flecha,dx,dy])=>html`
          <button type="button" class="boton" disabled=${ocupado} onClick=${()=>{
            const b=[...r.bbox], [w,h]=item.resultado_ocr.dimensiones;
            b[0]=Math.max(0,Math.min(w-b[2],b[0]+dx)); b[1]=Math.max(0,Math.min(h-b[3],b[1]+dy));
            modificar(i,{bbox:b,confirmado:false}); activar(i,b);
          }}>${flecha}</button>`)}</div>
      <button type="button" class="boton" disabled=${ocupado || !firma} onClick=${()=>releer(i)}>Releer esta región</button>
      <textarea class="campo mono" rows="3" value=${r.texto} disabled=${ocupado} maxLength="8192"
        placeholder="Relee o escribe el texto exacto de esta región" onChange=${e=>modificar(i,{texto:e.target.value,confirmado:false})} />
      <small class="subtitulo-seccion">Al pulsar Guardar, este texto y la geometría visible se consideran confirmados.</small>
    </div>`)}
    <${AyudaAprendizaje} texto="Al guardar, aprende el texto y las cuatro esquinas finales. Mover, girar o probar lecturas no entrena hasta confirmar." />
    <button type="button" class="boton boton-primario" disabled=${ocupado || !firma || regiones.some(r=>!r.texto.trim())}
      onClick=${guardar}>Guardar y reemplazar bloque original</button>
    <button type="button" class="boton" disabled=${ocupado} onClick=${cerrar}>Cancelar ajuste</button>
    <p role="status">${ocupado ? "Procesando…" : mensaje}</p>
    <small>La caja puede rotarse o convertirse en cuatro esquinas independientes. Al guardar, se aprende únicamente la geometría y el texto finales confirmados; los intentos intermedios no entrenan.</small>
  </section>`;
}

function SelectorRegion({ item, valor, onChange, onSelectText, giroVista = 0, panelTexto = null,
  textoRegion = "", onTextoRegion,
  panelCorreccion = null, correccionAbierta = false, onSeleccionarRegion,
  pruebaId = null, onZonaActualizada = null,
  anguloSeleccion = 0, onAnguloSeleccion = null, poligonoSeleccionado = null,
  onPoligonoSeleccion = null, permitirRotarSeleccion = false }) {
  const [zoom, setZoom] = useState(100);
  const [modo, setModo] = useState(panelTexto ? "mover" : "seleccionar");
  const [panelActivo, setPanelActivo] = useState("texto");
  const [origenBloque, setOrigenBloque] = useState(null);
  const [regionesBloque, setRegionesBloque] = useState([]);
  const [bloquesUnion, setBloquesUnion] = useState([]);
  const [regionActiva, setRegionActiva] = useState(0);
  function cambiarCaja(b, conservarPoligono = false) {
    onChange(b);
    if (modo === "ajustar" && origenBloque && b) {
      setRegionesBloque(rs=>rs.map((r,i)=>i===regionActiva ? {...r,bbox:b,
        ...(conservarPoligono ? {} : {poligono:null}), confirmado:false,candidatos:[],giro:0,textoAutomatico:null} : r));
    } else if (!conservarPoligono) {
      onPoligonoSeleccion?.(null);
    }
  }
  useEffect(() => { if (correccionAbierta) setModo("mover"); }, [correccionAbierta]);
  const scrollRef = useRef(null);
  const panRef = useRef(null);
  const moverCajaRef = useRef(null);
  const ajustePuntoRef = useRef(null);
  useEffect(() => {
    const marco = scrollRef.current;
    if (!marco) return;
    const rueda = (e) => { e.preventDefault(); setZoom((z) => Math.max(100, Math.min(600, z + (e.deltaY < 0 ? 25 : -25)))); };
    marco.addEventListener("wheel", rueda, { passive: false });
    return () => marco.removeEventListener("wheel", rueda);
  }, []);
  useEffect(() => { setZoom(100); setVistaPrevia(null); setVistaPoligono(null); inicioRef.current = null;
    setOrigenBloque(null); setRegionesBloque([]); setBloquesUnion([]);
    panRef.current = null; moverCajaRef.current = null; ajustePuntoRef.current = null; scrollRef.current?.scrollTo(0, 0);
  }, [item?.id, item?.ruta_api_orientada]);
  const marcoRef = useRef(null);
  const inicioRef = useRef(null);
  const ajusteRef = useRef(null);
  const [vistaPrevia, setVistaPrevia] = useState(null);
  const [vistaPoligono, setVistaPoligono] = useState(null);
  const dimensiones = item?.resultado_ocr?.dimensiones || [1, 1];
  const [anchoImagen, altoImagen] = dimensiones;
  const anguloRecorte = permitirRotarSeleccion ? Math.max(-45, Math.min(45, Number(anguloSeleccion) || 0)) : 0;
  const regionActivaObj = origenBloque ? regionesBloque[regionActiva] : null;
  const poligonoControlado = regionActivaObj?.poligono || poligonoSeleccionado || null;
  const poligonoRotado = valor && Math.abs(anguloRecorte) >= .05 ? poligonoRectanguloRotado(valor, anguloRecorte, dimensiones) : null;
  const poligonoSeleccion = vistaPoligono || poligonoControlado || poligonoRotado;
  const formaLibre = Boolean(poligonoControlado);
  function cambiarPoligono(puntos) {
    const limpio = Array.isArray(puntos) && puntos.length === 4 ? puntos.map(([x,y])=>[Math.round(Number(x)*1000)/1000,Math.round(Number(y)*1000)/1000]) : null;
    const b = limpio ? bboxDesdePoligono(limpio, dimensiones) : valor;
    if (limpio && !b) return;
    if (modo === "ajustar" && origenBloque) {
      setRegionesBloque(rs=>rs.map((r,i)=>i===regionActiva ? {...r,bbox:b||r.bbox,poligono:limpio,confirmado:false,candidatos:[],giro:0,textoAutomatico:null} : r));
      if (b) onChange(b);
    } else {
      onPoligonoSeleccion?.(limpio);
      if (b) onChange(b);
    }
  }
  function activarFormaLibre() {
    if (!valor) return;
    const base = poligonoSeleccion || poligonoRectangulo(valor);
    if (base) cambiarPoligono(base);
  }
  function volverRectangulo() {
    cambiarPoligono(null);
    onAnguloSeleccion?.(0);
  }
  function aplicarAnguloForma(nuevo) {
    const a=Math.max(-45,Math.min(45,Number(nuevo)||0));
    onAnguloSeleccion?.(a);
    if (modo === "ajustar" && origenBloque && valor) {
      const p=poligonoRectanguloRotado(valor,a,dimensiones);
      if (p) cambiarPoligono(p);
    } else if (formaLibre && valor) {
      const p=poligonoRectanguloRotado(valor,a,dimensiones);
      if (p) cambiarPoligono(p);
    }
  }
  const radianes = giroVista * Math.PI / 180;
  const coseno = Math.cos(radianes), seno = Math.sin(radianes);
  const anchoGirado = Math.abs(coseno) * anchoImagen + Math.abs(seno) * altoImagen;
  const altoGirado = Math.abs(seno) * anchoImagen + Math.abs(coseno) * altoImagen;
  const limitar = (v, minimo, maximo) => Math.max(minimo, Math.min(maximo, v));
  function punto(evento) {
    const rect = marcoRef.current.getBoundingClientRect();
    // Inversa del giro CSS: las anotaciones conservan el sistema de coordenadas OCR.
    const dx = evento.clientX - (rect.left + rect.width / 2);
    const dy = evento.clientY - (rect.top + rect.height / 2);
    const escala = marcoRef.current.offsetWidth / anchoImagen;
    return {
      x: limitar((coseno * dx + seno * dy) / escala + anchoImagen / 2, 0, anchoImagen),
      y: limitar((-seno * dx + coseno * dy) / escala + altoImagen / 2, 0, altoImagen),
    };
  }
  function caja(desde, hasta) {
    const x = Math.round(Math.min(desde.x, hasta.x));
    const y = Math.round(Math.min(desde.y, hasta.y));
    return [x, y, Math.round(Math.abs(hasta.x - desde.x)), Math.round(Math.abs(hasta.y - desde.y))];
  }
  function iniciar(evento) {
    if (!item) return;
    if (evento.button !== 0) return;
    evento.preventDefault();
    evento.currentTarget.setPointerCapture(evento.pointerId);
    if (modo === "mover") {
      panRef.current = [evento.clientX, evento.clientY, scrollRef.current.scrollLeft, scrollRef.current.scrollTop];
      return;
    }
    if (modo === "mover_recorte" && valor) {
      moverCajaRef.current = {inicio:punto(evento), bbox:[...valor],
        poligono: poligonoControlado ? poligonoControlado.map(p=>[...p]) : null};
      setVistaPrevia([...valor]);
      setVistaPoligono(poligonoControlado ? poligonoControlado.map(p=>[...p]) : null);
      return;
    }
    inicioRef.current = punto(evento);
    setVistaPoligono(null);
    setVistaPrevia([inicioRef.current.x, inicioRef.current.y, 0, 0]);
  }
  function mover(evento) {
    if (ajustePuntoRef.current) {
      const actual=punto(evento), ref=ajustePuntoRef.current;
      const p=ref.poligono.map(q=>[...q]);
      p[ref.indice]=[actual.x,actual.y];
      const b=bboxDesdePoligono(p,dimensiones);
      if (b) { setVistaPoligono(p); setVistaPrevia(b); }
      return;
    }
    if (ajusteRef.current) {
      setVistaPrevia(caja(ajusteRef.current, punto(evento)));
      return;
    }
    if (panRef.current) {
      const [x, y, left, top] = panRef.current;
      scrollRef.current.scrollLeft = left + x - evento.clientX;
      scrollRef.current.scrollTop = top + y - evento.clientY;
      return;
    }
    if (moverCajaRef.current) {
      const actual = punto(evento), origen = moverCajaRef.current;
      const dx = actual.x - origen.inicio.x, dy = actual.y - origen.inicio.y;
      if (origen.poligono) {
        const p=moverPoligono(origen.poligono,dx,dy,dimensiones);
        const b=bboxDesdePoligono(p,dimensiones);
        if (p&&b) {setVistaPoligono(p);setVistaPrevia(b);}
      } else {
        const [bx,by,bw,bh] = origen.bbox;
        const nx = limitar(Math.round(bx + dx), 0, Math.max(0, anchoImagen - bw));
        const ny = limitar(Math.round(by + dy), 0, Math.max(0, altoImagen - bh));
        setVistaPrevia([nx, ny, bw, bh]);
      }
      return;
    }
    if (!inicioRef.current) return;
    setVistaPrevia(caja(inicioRef.current, punto(evento)));
  }
  function terminar(evento) {
    panRef.current = null;
    if (ajustePuntoRef.current) {
      const p=vistaPoligono;
      ajustePuntoRef.current=null; setVistaPoligono(null); setVistaPrevia(null);
      if (evento.type !== "pointercancel" && p) cambiarPoligono(p);
      return;
    }
    if (moverCajaRef.current) {
      const ref=moverCajaRef.current, seleccion = vistaPrevia || ref.bbox, p=vistaPoligono;
      moverCajaRef.current = null; setVistaPrevia(null); setVistaPoligono(null);
      if (evento.type !== "pointercancel" && seleccion?.[2] >= 2 && seleccion?.[3] >= 2) {
        if (ref.poligono && p) cambiarPoligono(p); else cambiarCaja(seleccion);
      }
      return;
    }
    if (ajusteRef.current) {
      const seleccion = caja(ajusteRef.current, punto(evento));
      ajusteRef.current = null; setVistaPrevia(null);
      if (evento.type !== "pointercancel" && seleccion[2] >= 2 && seleccion[3] >= 2) cambiarCaja(seleccion);
      return;
    }
    if (evento.type === "pointercancel") { inicioRef.current = null; setVistaPrevia(null); setVistaPoligono(null); return; }
    if (!inicioRef.current) return;
    const seleccion = caja(inicioRef.current, punto(evento));
    inicioRef.current = null;
    setVistaPrevia(null); setVistaPoligono(null);
    if (seleccion[2] >= 2 && seleccion[3] >= 2) {
      cambiarCaja(seleccion);
      if (permitirRotarSeleccion && typeof onAnguloSeleccion === "function") onAnguloSeleccion(0);
    }
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
    <div class="controles-zoom">
      <strong>${zoom}%</strong>
      <button type="button" class="boton" onClick=${() => setZoom(Math.max(100, zoom - 25))}>−</button>
      <button type="button" class="boton" onClick=${() => setZoom(Math.min(600, zoom + 25))}>+</button>
      <button type="button" class="boton" onClick=${() => { setZoom(100); scrollRef.current?.scrollTo(0, 0); }}>Ajustar a pantalla</button>
      <button type="button" class="boton" aria-pressed=${modo === "seleccionar"} onClick=${() => { setModo("seleccionar");setPanelActivo("texto"); onSeleccionarRegion?.(); }}>Seleccionar texto</button>
      ${pruebaId && html`<button type="button" class="boton" aria-pressed=${modo === "unir"}
        onClick=${() => { setModo("unir");setPanelActivo("unir"); setBloquesUnion([]); onChange(null); onPoligonoSeleccion?.(null); onAnguloSeleccion?.(0); onSeleccionarRegion?.(); }}>Unir bloques</button>`}
      <button type="button" class="boton" aria-pressed=${modo === "mover"} onClick=${() => setModo("mover")}>Mover imagen</button>
      ${permitirRotarSeleccion && valor && html`<button type="button" class="boton" aria-pressed=${modo === "mover_recorte"}
        onClick=${() => setModo("mover_recorte")}>Mover recorte</button>`}
      ${pruebaId && html`<button type="button" class="boton" aria-pressed=${modo === "ajustar"}
        onClick=${()=>{setModo("ajustar");onAnguloSeleccion?.(0);onPoligonoSeleccion?.(null);if (!origenBloque) {setRegionesBloque([]);onChange(null);} onSeleccionarRegion?.();}}>Editar bloque</button>`}
      ${modo === "ajustar" && !origenBloque && html`<small>Pulsa el bloque OCR que deseas editar: podrás moverlo, ajustar límites, usar 4 esquinas, girarlo o dividirlo.</small>`}
      ${permitirRotarSeleccion && valor && html`<div class="control-recorte-inclinado" role="group" aria-label="Geometría flexible del recorte">
        <strong>${formaLibre ? "Forma libre · 4 esquinas" : `Inclinación: ${anguloRecorte > 0 ? "+" : ""}${anguloRecorte.toFixed(0)}°`}</strong>
        <button type="button" class=${`boton boton-compacto ${formaLibre ? "boton-primario" : ""}`}
          onClick=${formaLibre ? volverRectangulo : activarFormaLibre}>${formaLibre ? "Volver a rectángulo" : "Editar 4 esquinas"}</button>
        <button type="button" class="boton boton-compacto" onClick=${()=>aplicarAnguloForma(Math.max(-45, anguloRecorte-5))}>−5°</button>
        <input type="range" min="-45" max="45" step="1" value=${anguloRecorte}
          aria-label="Inclinación del recorte" onChange=${e=>aplicarAnguloForma(Number(e.target.value))} />
        <button type="button" class="boton boton-compacto" onClick=${()=>aplicarAnguloForma(Math.min(45, anguloRecorte+5))}>+5°</button>
        <button type="button" class="boton boton-compacto" onClick=${()=>aplicarAnguloForma(0)}>0°</button>
        ${!poligonoSeleccion && Math.abs(anguloRecorte) > .05 && html`<small class="mensaje-error">La geometría sale de la imagen. Muévela o reduce el ángulo.</small>`}
        <small>Puede ser rectángulo, recorte inclinado o cuadrilátero libre. Arrastra cualquiera de las cuatro esquinas para evitar texto vecino. Solo la forma final confirmada se aprende.</small>
      </div>`}
      ${modo === "unir" && html`<small class="ayuda-union-click">Pulsa cada bloque que pertenezca a la misma línea. Los seleccionados quedan resaltados; vuelve a pulsar uno para quitarlo.</small>`}
      <small>Amplía con la rueda. Selecciona una región o cambia a Mover imagen para desplazarte.</small>
    </div>
    <div class=${`editor-region-layout ${panelTexto && (modo === "seleccionar" || modo === "mover_recorte") ? "con-formulario" : ""}`}>
    <div class="editor-region-imagen">
    <div class="visor-region-grande" ref=${scrollRef}>
    <div style=${{position: "relative", width: `${zoom}%`, aspectRatio: `${anchoGirado} / ${altoGirado}`}}>
    <div class="selector-region" style=${{position: "absolute", left: "50%", top: "50%",
      width: `${anchoImagen / anchoGirado * 100}%`, maxWidth: "none", border: "none",
      transform: `translate(-50%, -50%) rotate(${giroVista}deg)`, transformOrigin: "center",
      transition: "none", willChange: "transform", cursor: modo === "mover" ? "grab" : modo === "mover_recorte" ? "move" : "crosshair"}} ref=${marcoRef} onPointerDown=${iniciar}
      onPointerMove=${mover} onPointerUp=${terminar} onPointerCancel=${terminar}
      role="img" aria-label="Arrastra para seleccionar la zona que contiene texto">
      <img src=${item?.ruta_api_orientada || item?.ruta_api}
        alt=${`Seleccionar texto en ${item?.nombre || "imagen"}`} draggable="false" />
      ${detectadas.filter((linea) => linea.bbox).map((linea, i) => html`
        <button type="button" key=${`ocr-${i}`} class=${`caja-region caja-ocr ${linea.orientacion_region_dudosa ? "caja-orientacion-dudosa" : ""} ${unidadConfirmada(linea, item?.correcciones) ? "caja-corregida" : ""} ${modo === "unir" && bloquesUnion.some(b=>JSON.stringify(b)===JSON.stringify(linea.bbox)) ? "caja-union-seleccionada" : ""}`}
          style=${estiloCaja(linea.bbox)} title=${`${unidadConfirmada(linea, item?.correcciones) ? "Corregido / confirmado" : "Sin corrección confirmada"}: ${textoVisible(linea)}`}
          onPointerDown=${(evento) => { if (modo !== "seleccionar" && modo !== "mover_recorte" && !(modo === "ajustar" && origenBloque)) evento.stopPropagation(); }}
          onClick=${(evento) => {
            evento?.stopPropagation?.();
            if (modo === "mover_recorte") return;
            if (modo === "ajustar") {
              if (!origenBloque) {
                const base = Number(linea.orientacion_base_grados ?? linea.orientacion_region_grados ?? 0) || 0;
                const efectivo = Number(linea.orientacion_efectiva_grados ?? base) || base;
                setOrigenBloque([...linea.bbox]); setRegionesBloque([{bbox:[...linea.bbox],poligono:Array.isArray(linea.poligono_lectura)?linea.poligono_lectura:null,texto:textoVisible(linea),
                  textoAutomatico:textoVisible(linea),confirmado:false,giroBase:base,giro:efectivo,usarAjusteFino:true}]);
                setRegionActiva(0); onChange([...linea.bbox]);
              }
              return;
            }
            if (modo === "seleccionar") return;
            if (modo !== "unir") {
              onSelectText?.(linea);
              return;
            }
            const b = [...linea.bbox];
            const existe = bloquesUnion.some(c=>JSON.stringify(c)===JSON.stringify(b));
            const seleccion = existe ? bloquesUnion.filter(c=>JSON.stringify(c)!==JSON.stringify(b)) : [...bloquesUnion, b];
            setBloquesUnion(seleccion);
            onPoligonoSeleccion?.(null); onAnguloSeleccion?.(0);
            if (!seleccion.length) { onChange(null); return; }
            const x1=Math.min(...seleccion.map(c=>c[0])), y1=Math.min(...seleccion.map(c=>c[1]));
            const x2=Math.max(...seleccion.map(c=>c[0]+c[2])), y2=Math.max(...seleccion.map(c=>c[1]+c[3]));
            onChange([x1,y1,x2-x1,y2-y1]);
          }}>${unidadConfirmada(linea, item?.correcciones) ? "✓" : ""}</button>`)}
      ${(item?.anotaciones || []).filter(a=>!a.poligono).map((anotacion) => html`
        <span key=${`manual-${anotacion.id}`} class="caja-region caja-manual"
          style=${estiloCaja(anotacion.bbox)} title=${`Manual: ${anotacion.texto_correcto}`} />`)}
      ${(item?.anotaciones || []).some(a=>Array.isArray(a.poligono)) && html`<svg class="capa-poligonos-region"
        viewBox=${`0 0 ${anchoImagen} ${altoImagen}`} preserveAspectRatio="none" aria-hidden="true">
        ${(item?.anotaciones || []).filter(a=>Array.isArray(a.poligono)).map(a=>html`<polygon key=${`poly-${a.id}`}
          class="poligono-region-manual" points=${puntosSvg(a.poligono)} />`)}
      </svg>`}
      ${poligonoSeleccion ? html`<svg class="capa-poligonos-region capa-poligono-seleccion" viewBox=${`0 0 ${anchoImagen} ${altoImagen}`} preserveAspectRatio="none" aria-hidden="true">
        <polygon class="poligono-seleccion-flexible" points=${puntosSvg(poligonoSeleccion)} /></svg>`
        : (vistaPrevia || valor) && html`<span class="caja-region caja-seleccion" style=${estiloCaja(vistaPrevia || valor)} />`}
      ${origenBloque && regionesBloque.filter((r,i)=>i!==regionActiva).map((r,i)=>Array.isArray(r.poligono)
        ? html`<svg class="capa-poligonos-region capa-poligono-borrador" viewBox=${`0 0 ${anchoImagen} ${altoImagen}`} preserveAspectRatio="none" aria-hidden="true"><polygon class="poligono-borrador-dimension" points=${puntosSvg(r.poligono)} /></svg>`
        : html`<span class="caja-region caja-borrador-dimension" style=${estiloCaja(r.bbox)}>${i+1}</span>`)}
      ${valor && modo !== "mover" && modo !== "mover_recorte" && poligonoSeleccion && poligonoSeleccion.map((p,i)=>html`
        <button type="button" class="tirador-zona tirador-poligono" aria-label=${`Mover esquina ${i+1}`}
          style=${{left:`${Number(p[0])/anchoImagen*100}%`,top:`${Number(p[1])/altoImagen*100}%`}}
          onPointerDown=${e=>{e.stopPropagation();e.preventDefault();e.currentTarget.setPointerCapture(e.pointerId);
            ajustePuntoRef.current={indice:i,poligono:poligonoSeleccion.map(q=>[...q])};}}
          onPointerMove=${mover} onPointerUp=${terminar} onPointerCancel=${terminar}>${i+1}</button>`)}
      ${valor && modo !== "mover" && modo !== "mover_recorte" && !poligonoSeleccion && [[0,0],[1,0],[0,1],[1,1]].map(([cx,cy]) => html`
        <button type="button" class="tirador-zona" aria-label="Ajustar esquina de región"
          style=${{left: `${(valor[0]+cx*valor[2])/anchoImagen*100}%`, top: `${(valor[1]+cy*valor[3])/altoImagen*100}%`}}
          onPointerDown=${e => {
            e.stopPropagation(); e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId);
            ajusteRef.current = {x: valor[0]+(1-cx)*valor[2], y: valor[1]+(1-cy)*valor[3]};
          }} onPointerMove=${mover} onPointerUp=${terminar} onPointerCancel=${terminar} />`)}
    </div>
    </div>
    </div>
    <div class="leyenda-regiones">
      <span><i class="leyenda-caja ocr"></i>Detectado por OCR</span>
      <span>✓ Corregido / confirmado y guardado</span>
      <span><i class="leyenda-caja manual"></i>Confirmado manualmente</span>
      <span><i class="leyenda-caja seleccion"></i>Selección actual</span>
    </div>
    </div>
    ${pruebaId && origenBloque && html`<${EditorDimensionBloque}
      key=${`${item.id}-${origenBloque.join(",")}`} item=${item} pruebaId=${pruebaId} origen=${origenBloque}
      regiones=${regionesBloque} setRegiones=${setRegionesBloque} activa=${regionActiva}
      activar=${(i,b)=>{setRegionActiva(i);onChange(b);}} onActualizado=${onZonaActualizada}
      cerrar=${()=>{setOrigenBloque(null);setRegionesBloque([]);onChange(null);onPoligonoSeleccion?.(null);setModo("unir");setPanelActivo("unir");}} />`}
    ${pruebaId && !origenBloque && !correccionAbierta && panelActivo === "unir" && html`<${EditorUnionZona} key=${item.id} item=${item}
      pruebaId=${pruebaId} valor=${valor} poligono=${poligonoSeleccion} onChange=${onChange} onActualizado=${onZonaActualizada}
      cerrar=${()=>{onChange(null);onPoligonoSeleccion?.(null);onAnguloSeleccion?.(0);setModo("mover");setPanelActivo("texto");}} />`}
    ${panelTexto && !origenBloque && !correccionAbierta && panelActivo === "texto" && (modo === "seleccionar" || modo === "mover_recorte" || (modo === "mover" && valor)) && html`<aside class="editor-region-form" aria-label="Texto omitido">
      <button type="button" class="boton" onClick=${() => {
        if (textoRegion && !window.confirm(t("Hay texto sin guardar. ¿Descartarlo y cerrar esta selección?"))) return;
        onTextoRegion?.(""); onChange(null); onPoligonoSeleccion?.(null); onAnguloSeleccion?.(0); setModo("mover");
      }}>Cerrar texto omitido</button>
      // Compatibilidad de contrato V14.11: poligono=${Math.abs(anguloRecorte) >= .05 ? poligonoSeleccion : null}
      ${valor && (Math.abs(anguloRecorte) < .05 || poligonoSeleccion) && html`<${HerramientasRegion} key=${`${item.id}-${valor.join(",")}-${JSON.stringify(poligonoSeleccion||null)}`} item=${item} bbox=${valor}
        poligono=${poligonoSeleccion} pruebaId=${pruebaId} onTexto=${onTextoRegion} />`}
      ${valor && Math.abs(anguloRecorte) >= .05 && !poligonoSeleccion && html`<p class="mensaje-error">El recorte inclinado sale de la imagen. Muévelo o reduce la inclinación para poder releerlo.</p>`}
      ${panelTexto}</aside>`}
    ${correccionAbierta && !origenBloque && html`<section class="editor-region-form" aria-label="Corregir texto reconocido">${panelCorreccion}</section>`}
    </div>
  </div>`;
}

function PanelImagen({ titulo, item, vacio, onSelectText, onBulkDiscard, edicionActiva, rotacionActiva, onRotate,
  onSelectImage, onMarkNoData, onVerifyImage, seleccionada = false, anclaId = null, visorRegion = null }) {
  const [zoomVista, setZoomVista] = useState(100);
  const [dimensionesNaturales, setDimensionesNaturales] = useState(null);
  const [modoBorradoMultiple, setModoBorradoMultiple] = useState(false);
  const [seleccionBorrado, setSeleccionBorrado] = useState([]);
  useEffect(() => { setModoBorradoMultiple(false); setSeleccionBorrado([]); }, [item?.id]);
  const marcoZoomRef = useRef(null);
  const arrastreRef = useRef(null);
  const ocr = item?.resultado_ocr || {};
  const estadoRevisionVisual = (item?.revision_sin_datos || item?.estado_imagen === "revisada_sin_datos")
    ? "sin-texto" : item?.estado_imagen === "verificada" ? "verificada" : "pendiente";
  const etiquetaRevisionVisual = estadoRevisionVisual === "sin-texto" ? "Sin texto · revisada"
    : estadoRevisionVisual === "verificada" ? "Imagen verificada" : "Pendiente de verificar";
  const base = Number(ocr.orientacion_texto_base_grados ?? ocr.orientacion_base_grados) || 0;
  const ajuste = Number(ocr.deskew_texto_aplicado_grados ?? ocr.deskew_aplicado_grados) || 0;
  const preferida = Number(item?.rotacion_manual_preferida_grados) || 0;
  const rotacionManualDefinida = Boolean(item?.rotacion_manual_definida);
  const anguloFirmado = (valor) => {
    const normalizado = ((Number(valor) || 0) % 360 + 360) % 360;
    return normalizado > 180 ? normalizado - 360 : normalizado;
  };
  const anguloVistaGuardada = rotacionManualDefinida ? preferida : base + ajuste;
  const anguloVistaFirmado = anguloFirmado(anguloVistaGuardada);
  const preferidaFirmada = anguloFirmado(preferida);
  const [anguloManual, setAnguloManual] = useState(anguloVistaFirmado);
  useEffect(() => setAnguloManual(anguloVistaFirmado), [item?.id, anguloVistaFirmado]);
  const giroPrevisualizado = anguloFirmado(anguloManual - anguloVistaFirmado);
  const cambioPendiente = Math.abs(giroPrevisualizado) >= 0.01;
  const enderezada = base !== 0 || Math.abs(ajuste) >= 0.05;
  const codigos = (ocr.codigos_detectados || []).filter((codigo) => codigo.valido);
  const limitarZoom = (valor) => Math.min(500, Math.max(25, Math.round(valor)));
  function cambiarZoom(valor, evento) {
    const marco = marcoZoomRef.current;
    const nuevo = limitarZoom(valor);
    if (!marco || !evento) return setZoomVista(nuevo);
    const rect = marco.getBoundingClientRect();
    const localX = evento.clientX - rect.left;
    const localY = evento.clientY - rect.top;
    const razonX = (marco.scrollLeft + localX) / Math.max(marco.scrollWidth, 1);
    const razonY = (marco.scrollTop + localY) / Math.max(marco.scrollHeight, 1);
    setZoomVista(nuevo);
    requestAnimationFrame(() => {
      marco.scrollLeft = razonX * marco.scrollWidth - localX;
      marco.scrollTop = razonY * marco.scrollHeight - localY;
    });
  }
  function alRueda(evento) {
    evento.preventDefault();
    cambiarZoom(zoomVista + (evento.deltaY < 0 ? 15 : -15), evento);
  }
  function iniciarArrastre(evento) {
    const marco = marcoZoomRef.current;
    if (!marco || evento.button !== 0 || zoomVista <= 100) return;
    marco.setPointerCapture(evento.pointerId);
    arrastreRef.current = { x: evento.clientX, y: evento.clientY,
      izquierda: marco.scrollLeft, arriba: marco.scrollTop };
    marco.classList.add("arrastrando");
  }
  function moverArrastre(evento) {
    const marco = marcoZoomRef.current;
    const inicio = arrastreRef.current;
    if (!marco || !inicio) return;
    marco.scrollLeft = inicio.izquierda - (evento.clientX - inicio.x);
    marco.scrollTop = inicio.arriba - (evento.clientY - inicio.y);
  }
  function terminarArrastre() {
    marcoZoomRef.current?.classList.remove("arrastrando");
    arrastreRef.current = null;
  }
  function ajustarPantalla() {
    const marco = marcoZoomRef.current;
    if (!marco || !dimensionesNaturales) return setZoomVista(100);
    const ancho = (marco.clientWidth - 12) / dimensionesNaturales[0];
    const alto = (marco.clientHeight - 12) / dimensionesNaturales[1];
    setZoomVista(limitarZoom(Math.min(ancho, alto, 1) * 100));
    marco.scrollTo({ left: 0, top: 0 });
  }
  function restablecerYCentrar() {
    setZoomVista(100);
    requestAnimationFrame(() => {
      const marco = marcoZoomRef.current;
      if (!marco) return;
      marco.scrollTo({ left: Math.max(0, (marco.scrollWidth - marco.clientWidth) / 2),
        top: Math.max(0, (marco.scrollHeight - marco.clientHeight) / 2), behavior: "smooth" });
    });
  }
  return html`<div id=${anclaId}
    class=${`tarjeta panel-imagen ${seleccionada ? "imagen-seleccionada" : ""}`}>
    <div class="progreso-titulo">
      <h3 class="titulo-seccion" style=${{ marginTop: 0 }}>${titulo}</h3>
      ${item && html`<span class=${`estado-miniatura estado-${estadoRevisionVisual}`}>
        ${etiquetaRevisionVisual}</span>`}
      ${onSelectImage && html`<button type="button" class="boton boton-compacto"
        onClick=${() => onSelectImage(item)}>${seleccionada && edicionActiva ? "Editando" : "Seleccionar y editar"}</button>`}
    </div>
    ${item
      ? html`${visorRegion ? React.cloneElement(visorRegion, { giroVista: giroPrevisualizado }) : html`<div class="controles-zoom">
          <span>Zoom de vista · rueda o botones</span>
          <strong>${zoomVista}%</strong>
          <button type="button" class="boton boton-compacto" aria-label="Alejar imagen"
            onClick=${() => cambiarZoom(zoomVista - 25)}>−</button>
          <button type="button" class="boton boton-compacto" aria-label="Acercar imagen"
            onClick=${() => cambiarZoom(zoomVista + 25)}>+</button>
          <button type="button" class="boton boton-compacto" onClick=${ajustarPantalla}>Ajustar a pantalla</button>
          <button type="button" class="boton boton-compacto" onClick=${restablecerYCentrar}>100%</button>
          <small>La rueda amplía; arrastra para desplazarte y haz doble clic para centrar/restablecer. No cambia el OCR.</small>
        </div>
        <div class="imagen-marco imagen-marco-zoom" ref=${marcoZoomRef} onWheel=${alRueda}
          onPointerDown=${iniciarArrastre} onPointerMove=${moverArrastre}
          onPointerUp=${terminarArrastre} onPointerCancel=${terminarArrastre}
          onDoubleClick=${restablecerYCentrar}>
          <img class=${cambioPendiente ? "imagen-giro-previsualizado" : ""}
            style=${{ width: dimensionesNaturales
              ? `${dimensionesNaturales[0] * zoomVista / 100}px` : `${zoomVista}%`, maxWidth: "none",
              transform: cambioPendiente ? `rotate(${giroPrevisualizado}deg)` : "none" }}
            src=${item.ruta_api_visual || item.ruta_api} alt=${`Imagen: ${item.ruta}`} loading="lazy"
            draggable="false" onLoad=${(e) => setDimensionesNaturales([
              e.currentTarget.naturalWidth, e.currentTarget.naturalHeight])} />
        </div>
        `}
        ${(item.revision_sin_datos || item.estado_imagen === "revisada_sin_datos") && html`<div class="aviso"><strong>Imagen revisada sin datos de texto.</strong>
          <p>${item.revision_sin_datos?.motivo || "Sin motivo adicional."}</p>
          ${onMarkNoData && html`<button type="button" class="boton" onClick=${() => onMarkNoData(item, true)}>Sí tiene texto</button>`}
        </div>`}
        <div class="estado-rotacion">
          ${rotacionManualDefinida ? html`<span class="chip rotacion-manual">Rotación manual prioritaria: ${preferidaFirmada}°</span>`
            : enderezada ? html`<span class="chip rotacion-auto">✓ Enderezada automáticamente:
            ${base}°${Math.abs(ajuste) >= 0.05 ? ` + ajuste ${ajuste.toFixed(1)}°` : ""}</span>`
            : html`<span class="chip neutro">Orientación automática: sin cambio</span>`}
          ${item.rotacion_pendiente && html`<span class="subtitulo-seccion">
            Se usará en el próximo OCR; la vista ya está girada.</span>`}
        </div>
        ${rotacionActiva && html`<div class="controles-rotacion" aria-label="Rotar imagen">
          <button type="button" class="boton boton-compacto"
            onClick=${() => setAnguloManual(Math.max(-180, anguloManual - 90))}>↶ 90°</button>
          <button type="button" class="boton boton-compacto"
            onClick=${() => setAnguloManual(Math.min(180, anguloManual + 90))}>↷ 90°</button>
          <label>Ángulo manual
            <input type="range" min="-180" max="180" step="1" value=${anguloManual}
              onInput=${(e) => setAnguloManual(Number(e.target.value))} />
          </label>
          <input class="campo campo-angulo" type="number" min="-180" max="180" step="0.1"
            value=${anguloManual} aria-label="Ángulo manual en grados"
            onInput=${(e) => setAnguloManual(Math.max(-180, Math.min(180, Number(e.target.value))))} />
          <button type="button" class="boton boton-primario boton-compacto"
            disabled=${!cambioPendiente && rotacionManualDefinida}
            onClick=${() => onRotate?.(item, anguloManual, false)}>Aplicar giro</button>
          <button type="button" class="boton boton-compacto" disabled=${!rotacionManualDefinida}
            onClick=${() => onRotate?.(item, 0, true)}>Usar giro automático</button>
          ${cambioPendiente && html`<span class="chip vista-previa-rotacion">
            Vista previa en tiempo real: ${anguloManual}° · pulsa Aplicar giro para guardarla
          </span>`}
        </div>`}
        ${edicionActiva && html`<div class="acciones-estado-imagen">
          ${onVerifyImage && !item.revision_sin_datos && item.estado_imagen !== "revisada_sin_datos" && html`
            <button type="button" class="boton boton-verificada"
              disabled=${item.estado_imagen === "verificada"}
              onClick=${() => onVerifyImage(item)}>
              ${item.estado_imagen === "verificada" ? "✓ Imagen verificada" : "Imagen verificada"}</button>`}
          ${onMarkNoData && !item.revision_sin_datos && item.estado_imagen !== "verificada" && html`
            <button type="button" class="boton boton-peligro boton-sin-datos"
              onClick=${() => onMarkNoData(item)}>Imagen sin datos de texto</button>`}
        </div>`}
        <div class="codigos-utiles">
          ${(ocr.recortes || []).some((r) => r.orientacion_dudosa) && html`
            <p class="aviso">Orientación dudosa en algún recorte: revisa el texto y aplica un giro manual si hace falta.</p>`}
          <div class="progreso-titulo"><strong>Códigos útiles</strong>
            <span class="subtitulo-seccion">${codigos.length} aceptados</span></div>
          ${codigos.length ? html`<ul class="tokens-lista">${codigos.map((codigo, i) => html`
            <li key=${`${codigo.normalizado}-${i}`} class="token-fila codigo-valido">
              <span><strong class="mono">${codigo.normalizado}</strong><small>${codigo.razon}</small></span>
              <span class="chip neutro">${codigo.tipo.replaceAll("_", " ")}</span>
            </li>`)}</ul>` : html`<p class="subtitulo-seccion">No hay códigos corroborables en esta lectura.</p>`}
        </div>
        <details class="lecturas-secundarias" open><summary>Texto completo y todas las lecturas OCR</summary>
          <div class="texto-detectado"><pre>${ocr.texto_completo || "Sin texto legible"}</pre></div>
          ${edicionActiva && onBulkDiscard && html`<div class="acciones-borrado-multiple">
            <button type="button" class="boton boton-compacto" onClick=${() => {
              setModoBorradoMultiple((v) => !v); setSeleccionBorrado([]);
            }}>${modoBorradoMultiple ? "Cancelar selección múltiple" : "Seleccionar varios textos"}</button>
            ${modoBorradoMultiple && html`<button type="button" class="boton boton-peligro boton-compacto"
              disabled=${!seleccionBorrado.length} onClick=${async () => {
                const unidades = unidadesOcr(ocr).filter((u) => seleccionBorrado.includes(u.unidad_id));
                if (!unidades.length) return;
                await onBulkDiscard(item, unidades);
                setSeleccionBorrado([]); setModoBorradoMultiple(false);
              }}>Descartar ${seleccionBorrado.length} seleccionados</button>`}
          </div>`}
          <ul class="tokens-lista">
            ${unidadesOcr(ocr).filter((u) => u.tipo_unidad !== "bloque completo").map((t) => html`
            <li key=${t.unidad_id} class=${`token-fila ${unidadConfirmada(t, item.correcciones) ? "token-confirmado" : ""}`}>
              ${modoBorradoMultiple && t.bbox && html`<input type="checkbox" class="selector-texto-multiple"
                checked=${seleccionBorrado.includes(t.unidad_id)} aria-label=${`Seleccionar ${textoVisible(t)} para descartar`}
                onChange=${(e) => setSeleccionBorrado((actual) => e.target.checked
                  ? [...actual, t.unidad_id] : actual.filter((id) => id !== t.unidad_id))} />`}
              <button type="button" class="token-texto-boton mono" disabled=${!edicionActiva || modoBorradoMultiple}
                title=${edicionActiva ? "Usar este texto en la corrección" : "Selecciona esta imagen para editar"}
                onClick=${() => onSelectText?.(item, t)}>${textoVisible(t)}</button>
              <span class=${`estado-texto ${unidadConfirmada(t, item.correcciones) ? "texto-corregido" : "texto-pendiente"}`}>
                ${unidadConfirmada(t, item.correcciones) ? "✓ Corregido / confirmado" : "Sin confirmar"}</span>
              <span class="conf">${t.confianza == null ? "—" : `${(t.confianza * 100).toFixed(1)}%`}</span>
            </li>`)}
          </ul>
          ${(ocr.reglas_codigo || []).length > 0 && html`<details><summary>Reglas de aceptación de códigos</summary>
            <ul>${ocr.reglas_codigo.map((regla) => html`<li key=${regla}>${regla}</li>`)}</ul>
          </details>`}
        </details>
        ${(item.anotaciones || []).length > 0 && html`<div class="anotaciones-manuales">
          <strong>Texto añadido manualmente</strong>
          ${(item.anotaciones || []).map((a) => html`<div key=${a.id} class="anotacion-manual">
            <span class="mono">${a.texto_correcto}</span>
            <small class="mono">región ${a.bbox.join(", ")}${Array.isArray(a.poligono) ? " · recorte inclinado" : ""}</small>
          </div>`)}
        </div>`}`
      : html`<p style=${{ color: "var(--texto-3)" }}>${vacio}</p>`}
  </div>`;
}

function fpsGrabacionOverlayVideo(video) {
  const texto = [video?.overlay_texto, video?.overlay_texto_esquina, video?.texto_overlay]
    .filter(Boolean).join(" ");
  const m = /\bRec\s*([0-9OoIl]{2,6}(?:[.,][0-9OoIl]+)?)\s*fps\b/i.exec(texto);
  if (!m) return 0;
  const normalizado = m[1].replace(/[Oo]/g, "0").replace(/[Il]/g, "1").replace(",", ".");
  const valor = Number(normalizado);
  return Number.isFinite(valor) && valor > 0 ? valor : 0;
}

function TarjetaVideoAirbag({ video, pruebaId, onSaved, bloqueado = false }) {
  const frameBase = Number(video.revision_manual?.frame_index ?? video.frame_evento ?? 0);
  const fpsOverlayBase = fpsGrabacionOverlayVideo(video);
  const fpsBase = fpsOverlayBase || Number(video.fps_grabacion || video.fps || 0);
  const resolucionBase = fpsBase > 0 ? 1000 / fpsBase : 0;
  const tiempoGuardadoRaw = Number(video.revision_manual?.tiempo_ms ?? video.tiempo_ms);
  const metadataFpsSospechosa = fpsOverlayBase > 0 && Number(video.fps || 0) > 0 &&
    Math.abs(Number(video.fps || 0) - fpsOverlayBase) > 0.01;
  const tiempoBaseRaw = metadataFpsSospechosa && resolucionBase > 0
    ? Math.max(0, frameBase) * resolucionBase
    : tiempoGuardadoRaw;
  const tiempoBase = Number.isFinite(tiempoBaseRaw) ? Math.max(0, tiempoBaseRaw) :
    (resolucionBase > 0 ? Math.max(0, frameBase) * resolucionBase : 0);
  const [frame, setFrame] = useState(Math.max(0, frameBase));
  const [tiempo, setTiempo] = useState(tiempoBase);
  const [infoTiempo, setInfoTiempo] = useState(null);
  const [cargandoTiempo, setCargandoTiempo] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const [mensaje, setMensaje] = useState(null);
  const [modoZona, setModoZona] = useState(false);
  const [zonaTemporal, setZonaTemporal] = useState(null);
  const [recalculandoVideo, setRecalculandoVideo] = useState(false);
  const [estadoRecalculoVideo, setEstadoRecalculoVideo] = useState(null);
  // V15.7.4: ROI general (dónde mirar) y microzona de nacimiento (dónde
  // aparece el primer fragmento) se mantienen separadas.
  const [zonaNacimiento, setZonaNacimiento] = useState(null);
  const [detalleNacimiento, setDetalleNacimiento] = useState(null);
  const [localizandoNacimiento, setLocalizandoNacimiento] = useState(false);
  const [modoNacimientoManual, setModoNacimientoManual] = useState(false);
  const imgZonaRef = useRef(null);
  const inicioZonaRef = useRef(null);
  const zoomZonaRef = useRef(null);
  const inicioNacimientoRef = useRef(null);

  const fpsOverlay = fpsGrabacionOverlayVideo(video);
  const fpsActual = Number(infoTiempo?.fps || fpsOverlay || video.fps_grabacion || video.fps || 0);
  const fuenteFpsActual = infoTiempo?.fps_fuente || (fpsOverlay ? "overlay_rec" : (video.fps_fuente || "archivo"));
  const resolucion = Number(infoTiempo?.resolucion_nativa_ms || video.resolucion_nativa_ms || (fpsActual ? 1000 / fpsActual : 0));
  const zonaAuto = Array.isArray(video.zona_deteccion?.bbox_norm) ? video.zona_deteccion.bbox_norm : null;
  const zonaVisible = zonaTemporal || zonaAuto;
  const fuenteZona = video.zona_deteccion?.fuente || "sin_aprendizaje";
  const tipoCamara = video.tipo_camara || video.zona_deteccion?.tipo_camara || null;
  const maxFrame = Math.max(0, Number(video.total_frames || 1) - 1);

  useEffect(() => {
    const nuevoFrame = Math.max(0, Number(video.revision_manual?.frame_index ?? video.frame_evento ?? 0));
    const nuevoTiempoRaw = Number(video.revision_manual?.tiempo_ms ?? video.tiempo_ms);
    const fpsRec = fpsGrabacionOverlayVideo(video);
    const fpsViejo = Number(video.fps || video.fps_archivo || 0);
    const metadataVieja = fpsRec > 0 && fpsViejo > 0 && Math.abs(fpsRec - fpsViejo) > .01;
    const tiempoReparado = metadataVieja ? (nuevoFrame * 1000 / fpsRec) : nuevoTiempoRaw;
    setFrame(nuevoFrame);
    setTiempo(Number.isFinite(tiempoReparado) ? Math.max(0, Math.round(tiempoReparado * 10) / 10) : 0);
    setInfoTiempo(null);
    setModoZona(false); setZonaTemporal(null); inicioZonaRef.current = null;
    setZonaNacimiento(null); setDetalleNacimiento(null); setLocalizandoNacimiento(false);
    setModoNacimientoManual(false); inicioNacimientoRef.current = null;
    setRecalculandoVideo(false); setEstadoRecalculoVideo(null);
    // V15.7: sólo se reinicia al cambiar de VIDEO. Guardar una confirmación o
    // una zona recarga los datos, pero ya no te devuelve al cuadro automático
    // ni te saca del cuadro donde estabas revisando.
  }, [video.id]);

  // V15.7: ancla visual. Mientras revisas, la tarjeta no debe desplazarse
  // aunque cambien de alto los paneles de arriba (mensajes OCR, avisos).
  const tarjetaRef = useRef(null);
  const anclaRef = useRef(null);
  function anclarTarjeta() {
    const el = tarjetaRef.current;
    if (!el) return;
    anclaRef.current = { top: el.getBoundingClientRect().top, hasta: Date.now() + 2500 };
  }
  useLayoutEffect(() => {
    const ancla = anclaRef.current; const el = tarjetaRef.current;
    if (!ancla || !el) return;
    if (Date.now() > ancla.hasta) { anclaRef.current = null; return; }
    const delta = el.getBoundingClientRect().top - ancla.top;
    if (Math.abs(delta) > 0.5) window.scrollBy(0, delta);
  });

  // V15.7: doble búfer de imagen. El cuadro anterior se queda visible hasta
  // que el nuevo terminó de cargar; el hueco nunca se encoge ni parpadea.
  const rutaFrameSolicitada = `/api/video/frame?ruta=${encodeURIComponent(video.ruta || "")}&frame=${Math.max(0, Math.round(frame || 0))}`;
  const [rutaFrameMostrada, setRutaFrameMostrada] = useState(rutaFrameSolicitada);
  const [errorFrame, setErrorFrame] = useState(false);
  useEffect(() => {
    let vigente = true;
    const img = new Image();
    img.onload = () => { if (vigente) { setRutaFrameMostrada(rutaFrameSolicitada); setErrorFrame(false); } };
    img.onerror = () => { if (vigente) setErrorFrame(true); };
    img.src = rutaFrameSolicitada;
    return () => { vigente = false; };
  }, [rutaFrameSolicitada]);
  const proporcion = Number(video.ancho) > 0 && Number(video.alto) > 0 ? `${Number(video.ancho)} / ${Number(video.alto)}` : "4 / 3";

  function tiempoProvisional(indice) {
    if (!(resolucion > 0)) return Math.max(0, Number(tiempo || 0));
    // Mientras llega la validación OCR usamos frame/FPS desde cero. No se
    // arrastra el timestamp inicial porque un OCR viejo/erróneo era la causa
    // de saltos y contradicciones visuales. El backend decide después si el
    // reloj del MISMO frame justifica un anclaje distinto.
    return Math.max(0, Math.round((Number(indice || 0) * resolucion) * 10) / 10);
  }

  useEffect(() => {
    if (!video.id || !pruebaId) return undefined;
    const controlador = new AbortController();
    const temporizador = setTimeout(async () => {
      setCargandoTiempo(true);
      try {
        const q = new URLSearchParams({
          prueba_id: String(pruebaId), video_id: String(video.id), frame: String(Math.max(0, Math.round(frame || 0))),
        });
        const info = await pedirJSON(`/api/video/tiempo-frame?${q.toString()}`, controlador.signal);
        if (!info) return;
        const valor = Number(info.tiempo_ms);
        const seguro = Number.isFinite(valor) ? Math.max(0, valor) : tiempoProvisional(frame);
        setInfoTiempo(info);
        setTiempo(Math.round(seguro * 10) / 10);
      } catch (e) {
        if (e?.name === "AbortError") return;
        setInfoTiempo({
          tiempo_ms: tiempoProvisional(frame), tiempo_overlay_ms: null,
          fuente_tiempo: "fallback_dashboard", overlay_valido: false,
          advertencia: `No se pudo validar el reloj de este cuadro: ${e.message}`,
        });
        setTiempo(tiempoProvisional(frame));
      } finally {
        if (!controlador.signal.aborted) setCargandoTiempo(false);
      }
    }, 160);
    return () => { clearTimeout(temporizador); controlador.abort(); };
  }, [frame, video.id, pruebaId, video.revision_manual?.confirmado_en]);

  function cambiarFrame(valor) {
    anclarTarjeta();
    const numero = Number(valor);
    const siguiente = Math.max(0, Math.min(maxFrame, Number.isFinite(numero) ? Math.round(numero) : 0));
    setFrame(siguiente);
    setTiempo(tiempoProvisional(siguiente));
    setInfoTiempo(null);
    if (modoZona && zonaTemporal) {
      setZonaNacimiento(null); setDetalleNacimiento(null); setModoNacimientoManual(false);
    }
  }
  function moverFrame(delta) { cambiarFrame(Number(frame || 0) + delta); }
  function tecladoVideo(e) {
    const tag = String(e.target?.tagName || "").toUpperCase();
    if (["INPUT", "BUTTON", "SELECT", "TEXTAREA"].includes(tag) || modoZona) return;
    if (e.key === "ArrowLeft") { e.preventDefault(); moverFrame(e.shiftKey ? -10 : -1); }
    if (e.key === "ArrowRight") { e.preventDefault(); moverFrame(e.shiftKey ? 10 : 1); }
    if (e.key === "Home") { e.preventDefault(); cambiarFrame(0); }
    if (e.key === "End") { e.preventDefault(); cambiarFrame(maxFrame); }
  }

  async function recalcularEsteVideo() {
    if (recalculandoVideo || bloqueado || guardando) return;
    anclarTarjeta();
    setMensaje(null);
    setEstadoRecalculoVideo({ estado: "preparando", mensaje: "Preparando este video…", procesados: 0, total_videos: 1 });
    try {
      await enviarJSON("/api/video/reanalizar", { prueba_id: pruebaId, video_id: video.id });
      setRecalculandoVideo(true);
    } catch (e) {
      setEstadoRecalculoVideo({ estado: "error", mensaje: e.message, procesados: 0, total_videos: 1 });
      setMensaje({ok:false, texto:e.message});
    }
  }

  useEffect(() => {
    if (!recalculandoVideo) return undefined;
    let cancelado = false;
    let temporizador = null;
    async function consultarRecalculoVideo() {
      try {
        const estado = await pedirJSON("/api/video/reanalisis/estado");
        if (cancelado) return;
        if (estado?.video_id && String(estado.video_id) !== String(video.id)) {
          temporizador = setTimeout(consultarRecalculoVideo, 700);
          return;
        }
        setEstadoRecalculoVideo(estado);
        if (["completado", "error"].includes(estado?.estado)) {
          setRecalculandoVideo(false);
          if (estado.estado === "completado") {
            setMensaje({ok:true, texto:"Video recalculado con el aprendizaje y la zona de interés actuales."});
            if (onSaved) await onSaved(estado);
          } else {
            setMensaje({ok:false, texto:estado.ultimo_error || estado.mensaje || "No se pudo recalcular el video."});
          }
          return;
        }
      } catch (e) {
        if (cancelado) return;
        setRecalculandoVideo(false);
        setMensaje({ok:false, texto:e.message});
        return;
      }
      temporizador = setTimeout(consultarRecalculoVideo, 700);
    }
    consultarRecalculoVideo();
    return () => { cancelado = true; if (temporizador) clearTimeout(temporizador); };
  }, [recalculandoVideo, pruebaId, video.id]);

  async function guardar(estado) {
    anclarTarjeta();
    setGuardando(true); setMensaje(null);
    try {
      const bboxNacimientoVisible = mostrarNacimiento ? zonaNacimientoVisible : null;
      const r = await enviarJSON("/api/video/revision", {
        prueba_id: pruebaId, video_id: video.id, frame_index: Math.max(0, Math.round(frame)),
        tiempo_ms: estado === "sin_evento" ? null : Math.max(0, Number(tiempo)), estado,
        usuario: "dashboard",
        bbox_evento_norm: estado === "confirmado" && Array.isArray(bboxNacimientoVisible) ? bboxNacimientoVisible : null,
      });
      if (r.tiempo_resuelto) {
        setInfoTiempo(r.tiempo_resuelto);
        const valor = Number(r.tiempo_resuelto.tiempo_ms);
        if (Number.isFinite(valor)) setTiempo(Math.max(0, Math.round(valor * 10) / 10));
      }
      if (estado === "confirmado" && Array.isArray(r.localizacion_nacimiento?.bbox_norm)) {
        setZonaNacimiento(r.localizacion_nacimiento.bbox_norm.map(Number));
        setDetalleNacimiento(r.localizacion_nacimiento);
      }
      const aprendido = estado === "confirmado" && r.ejemplo_aprendido;
      const avisoAprendizaje = r.advertencia_aprendizaje ? " La confirmación se guardó, pero el ejemplo no pudo añadirse al dataset." : "";
      const ajusteServidor = estado === "confirmado" && Math.abs(Number(r.diferencia_cliente_ms || 0)) >= 0.05
        ? " El servidor resincronizó el tiempo con el reloj/FPS del cuadro antes de guardarlo." : "";
      setMensaje({ok:true, texto: estado === "sin_evento" ? "Video marcado sin apertura."
        : aprendido ? `Punto de apertura confirmado y añadido al aprendizaje preciso (microzona + F-3…F+3).${ajusteServidor}`
        : `Punto de apertura confirmado.${ajusteServidor}${avisoAprendizaje}`});
      if (onSaved) await onSaved(r);
    } catch (e) { setMensaje({ok:false, texto:e.message}); }
    finally { setGuardando(false); }
  }

  async function guardarMaximo() {
    anclarTarjeta();
    setGuardando(true); setMensaje(null);
    try {
      const r = await enviarJSON("/api/video/maximo", {
        prueba_id: pruebaId, video_id: video.id,
        frame_index: Math.max(0, Math.round(frame)), usuario: "dashboard",
      });
      setMensaje({ok:true, texto:`Máximo despliegue visible confirmado: cuadro ${r.despliegue_maximo.frame_index}, ${r.despliegue_maximo.tiempo_ms} ms. Se exporta por separado; no cambia apertura ni inflado completo.`});
      if (onSaved) await onSaved(r);
    } catch (e) { setMensaje({ok:false, texto:e.message}); }
    finally { setGuardando(false); }
  }

  function puntoZona(evento) {
    const img = imgZonaRef.current;
    if (!img) return null;
    const rect = img.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    return {
      x: Math.max(0, Math.min(1, (evento.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (evento.clientY - rect.top) / rect.height)),
    };
  }
  function iniciarZona(evento) {
    if (!modoZona || bloqueado || guardando || evento.button !== 0) return;
    const p = puntoZona(evento); if (!p) return;
    evento.currentTarget.setPointerCapture?.(evento.pointerId);
    inicioZonaRef.current = p;
    setZonaNacimiento(null); setDetalleNacimiento(null); setModoNacimientoManual(false);
    setZonaTemporal([p.x, p.y, p.x, p.y]);
  }
  function moverZona(evento) {
    if (!modoZona || !inicioZonaRef.current) return;
    const p = puntoZona(evento); if (!p) return;
    const a = inicioZonaRef.current;
    setZonaTemporal([Math.min(a.x,p.x), Math.min(a.y,p.y), Math.max(a.x,p.x), Math.max(a.y,p.y)]);
  }
  function terminarZona(evento) {
    if (!inicioZonaRef.current) return;
    const p = puntoZona(evento);
    const a = inicioZonaRef.current;
    inicioZonaRef.current = null;
    if (!p) return;
    const zonaFinal = [Math.min(a.x,p.x), Math.min(a.y,p.y), Math.max(a.x,p.x), Math.max(a.y,p.y)];
    setZonaTemporal(zonaFinal);
    setZonaNacimiento(null); setDetalleNacimiento(null); setModoNacimientoManual(false);
    // Al terminar de dibujar la ROI general, localiza automáticamente dentro
    // de ella el primer fragmento visible del cuadro actual.
    localizarNacimiento(zonaFinal);
  }

  async function localizarNacimiento(bboxForzada = null) {
    const zonaElegida = bboxForzada || zonaTemporal || zonaAuto;
    if (!zonaElegida || localizandoNacimiento) return null;
    const [x1,y1,x2,y2] = zonaElegida.map(Number);
    if ((x2-x1) < .015 || (y2-y1) < .015) return null;
    setLocalizandoNacimiento(true);
    try {
      const r = await enviarJSON("/api/video/refinar-zona-apertura", {
        prueba_id: pruebaId, video_id: video.id,
        bbox_norm: zonaElegida.map(v => Math.round(Number(v) * 1000000) / 1000000),
        frame_index: Math.max(0, Math.round(Number(frame || 0))),
      });
      if (Array.isArray(r?.bbox_norm) && r.bbox_norm.length === 4) {
        setZonaNacimiento(r.bbox_norm.map(Number));
        setDetalleNacimiento(r);
        return r;
      }
      return null;
    } catch (e) {
      setDetalleNacimiento({error:e.message});
      return null;
    } finally { setLocalizandoNacimiento(false); }
  }

  async function guardarZona(bboxForzada = null) {
    anclarTarjeta();
    const zonaElegida = bboxForzada || zonaTemporal;
    if (!zonaElegida) return;
    const [x1,y1,x2,y2] = zonaElegida;
    if ((x2-x1) < .015 || (y2-y1) < .015) {
      setMensaje({ok:false, texto:"La zona es demasiado pequeña. Encierra el lugar donde comienza a salir la bolsa."});
      return;
    }
    setGuardando(true); setMensaje(null);
    try {
      const r = await enviarJSON("/api/video/zona-aprendizaje", {
        prueba_id: pruebaId, video_id: video.id,
        bbox_norm: zonaElegida.map(v => Math.round(Number(v) * 1000000) / 1000000),
        frame_index: Math.round(Number(frame || 0)), tipo_camara: tipoCamara,
        usuario: "dashboard",
      });
      setMensaje({ok:true, texto:`Zona guardada y bloqueada${r.perfil?.tipo_camara ? ` para ${r.perfil.tipo_camara}` : ""}. El video se volvió a analizar mirando exactamente ahí.`});
      setModoZona(false); setZonaTemporal(null);
      if (onSaved) await onSaved(r);
    } catch (e) { setMensaje({ok:false, texto:e.message}); }
    finally { setGuardando(false); }
  }
  async function guardarZonaYApertura() {
    anclarTarjeta();
    const zonaElegida = zonaTemporal;
    if (!zonaElegida) return;
    const [x1,y1,x2,y2] = zonaElegida;
    if ((x2-x1) < .015 || (y2-y1) < .015) {
      setMensaje({ok:false, texto:"La zona es demasiado pequeña. Encierra el lugar donde aparece por primera vez la bolsa."});
      return;
    }
    setGuardando(true); setMensaje(null);
    try {
      const zonaResp = await enviarJSON("/api/video/zona-aprendizaje", {
        prueba_id: pruebaId, video_id: video.id,
        bbox_norm: zonaElegida.map(v => Math.round(Number(v) * 1000000) / 1000000),
        frame_index: Math.round(Number(frame || 0)), tipo_camara: tipoCamara, usuario: "dashboard",
      });
      let nacimientoExacto = zonaNacimiento;
      if (!Array.isArray(nacimientoExacto)) {
        const afinado = await enviarJSON("/api/video/refinar-zona-apertura", {
          prueba_id: pruebaId, video_id: video.id,
          bbox_norm: zonaElegida.map(v => Math.round(Number(v) * 1000000) / 1000000),
          frame_index: Math.max(0, Math.round(Number(frame || 0))),
        });
        if (Array.isArray(afinado?.bbox_norm)) {
          nacimientoExacto = afinado.bbox_norm.map(Number);
          setZonaNacimiento(nacimientoExacto); setDetalleNacimiento(afinado);
        }
      }
      const revision = await enviarJSON("/api/video/revision", {
        prueba_id: pruebaId, video_id: video.id, frame_index: Math.max(0, Math.round(frame)),
        tiempo_ms: Math.max(0, Number(tiempo)), estado: "confirmado", usuario: "dashboard",
        comentario: "Supervisión combinada: ROI general + microzona exacta + primer cuadro de apertura",
        bbox_evento_norm: Array.isArray(nacimientoExacto) ? nacimientoExacto : null,
      });
      if (revision.tiempo_resuelto) {
        setInfoTiempo(revision.tiempo_resuelto);
        const valor = Number(revision.tiempo_resuelto.tiempo_ms);
        if (Number.isFinite(valor)) setTiempo(Math.max(0, Math.round(valor * 10) / 10));
      }
      if (Array.isArray(revision.localizacion_nacimiento?.bbox_norm)) {
        setZonaNacimiento(revision.localizacion_nacimiento.bbox_norm.map(Number));
        setDetalleNacimiento(revision.localizacion_nacimiento);
      }
      setMensaje({ok:true, texto:`Aprendizaje guardado: la ROI general indica dónde mirar y la microzona marca dónde nace exactamente la bolsa en el cuadro ${Math.round(frame)}. F-3…F+3 se guardó recortado alrededor de ese nacimiento.`});
      setModoZona(false); setZonaTemporal(null); setModoNacimientoManual(false);
      if (onSaved) await onSaved({zona: zonaResp, revision});
    } catch (e) { setMensaje({ok:false, texto:e.message}); }
    finally { setGuardando(false); }
  }

  function estiloZona(bbox) {
    if (!Array.isArray(bbox) || bbox.length !== 4) return null;
    return { left:`${bbox[0]*100}%`, top:`${bbox[1]*100}%`,
      width:`${Math.max(0,bbox[2]-bbox[0])*100}%`, height:`${Math.max(0,bbox[3]-bbox[1])*100}%` };
  }
  function zonaZoomEnfocada(nacimiento, general) {
    if (!Array.isArray(general) || general.length !== 4) return general;
    if (!Array.isArray(nacimiento) || nacimiento.length !== 4) return general;
    const [gx1,gy1,gx2,gy2]=general.map(Number);
    const [x1,y1,x2,y2]=nacimiento.map(Number);
    const gw=Math.max(.002,gx2-gx1), gh=Math.max(.002,gy2-gy1);
    const ew=Math.max(.001,x2-x1), eh=Math.max(.001,y2-y1);
    // Enseña contexto suficiente para saber qué pieza estamos viendo, pero
    // acerca 3-5× la microzona para distinguir el primer filamento.
    const zw=Math.min(gw,Math.max(ew*4.2,gw*.20));
    const zh=Math.min(gh,Math.max(eh*4.2,gh*.20));
    const cx=(x1+x2)/2, cy=(y1+y2)/2;
    let zx1=Math.max(gx1,cx-zw/2), zy1=Math.max(gy1,cy-zh/2);
    let zx2=Math.min(gx2,zx1+zw), zy2=Math.min(gy2,zy1+zh);
    zx1=Math.max(gx1,zx2-zw); zy1=Math.max(gy1,zy2-zh);
    return [zx1,zy1,zx2,zy2];
  }

  function estiloLienzoZoom(bbox) {
    if (!Array.isArray(bbox) || bbox.length !== 4) return null;
    const [x1,y1,x2,y2] = bbox.map(Number);
    const wn = Math.max(.002, x2-x1), hn = Math.max(.002, y2-y1);
    const vw = Math.max(1, Number(video.ancho || 16));
    const vh = Math.max(1, Number(video.alto || 9));
    const ratio = Math.max(.45, Math.min(4.8, (wn * vw) / (hn * vh)));
    return {aspectRatio:String(ratio)};
  }
  function estiloImagenZoom(bbox) {
    if (!Array.isArray(bbox) || bbox.length !== 4) return null;
    const [x1,y1,x2,y2] = bbox.map(Number);
    const w = Math.max(.002, x2-x1), h = Math.max(.002, y2-y1);
    return {
      width:`${100/w}%`, height:`${100/h}%`,
      left:`${-x1/w*100}%`, top:`${-y1/h*100}%`,
    };
  }
  function estiloNacimientoEnZoom(nacimiento, general) {
    if (!Array.isArray(nacimiento) || nacimiento.length !== 4 || !Array.isArray(general) || general.length !== 4) return null;
    const [gx1,gy1,gx2,gy2] = general.map(Number);
    const [x1,y1,x2,y2] = nacimiento.map(Number);
    const gw = Math.max(.0001,gx2-gx1), gh = Math.max(.0001,gy2-gy1);
    return {left:`${((x1-gx1)/gw)*100}%`,top:`${((y1-gy1)/gh)*100}%`,
      width:`${((x2-x1)/gw)*100}%`,height:`${((y2-y1)/gh)*100}%`};
  }
  function puntoNacimientoZoom(evento) {
    const lienzo = zoomZonaRef.current;
    const general = zonaZoomVisible || zonaTemporal || zonaAuto;
    if (!lienzo || !Array.isArray(general)) return null;
    const rect = lienzo.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const u = Math.max(0,Math.min(1,(evento.clientX-rect.left)/rect.width));
    const v = Math.max(0,Math.min(1,(evento.clientY-rect.top)/rect.height));
    return {x:general[0]+u*(general[2]-general[0]), y:general[1]+v*(general[3]-general[1])};
  }
  function iniciarNacimientoManual(evento) {
    if (!modoNacimientoManual || bloqueado || guardando || evento.button !== 0) return;
    const p = puntoNacimientoZoom(evento); if (!p) return;
    evento.currentTarget.setPointerCapture?.(evento.pointerId);
    inicioNacimientoRef.current = p;
    setZonaNacimiento([p.x,p.y,p.x,p.y]);
  }
  function moverNacimientoManual(evento) {
    if (!modoNacimientoManual || !inicioNacimientoRef.current) return;
    const p = puntoNacimientoZoom(evento); if (!p) return;
    const a = inicioNacimientoRef.current;
    setZonaNacimiento([Math.min(a.x,p.x),Math.min(a.y,p.y),Math.max(a.x,p.x),Math.max(a.y,p.y)]);
  }
  function terminarNacimientoManual(evento) {
    if (!inicioNacimientoRef.current) return;
    const p = puntoNacimientoZoom(evento); const a = inicioNacimientoRef.current;
    inicioNacimientoRef.current = null;
    if (!p) return;
    const exacta=[Math.min(a.x,p.x),Math.min(a.y,p.y),Math.max(a.x,p.x),Math.max(a.y,p.y)];
    const w=exacta[2]-exacta[0], h=exacta[3]-exacta[1];
    if (w < .002 || h < .002) {
      setMensaje({ok:false,texto:"La microzona exacta es demasiado pequeña. Marca un pequeño rectángulo alrededor del primer fragmento visible."});
      return;
    }
    setZonaNacimiento(exacta);
    setDetalleNacimiento({bbox_norm:exacta,frame_index:Math.round(frame),metodo:"manual_dashboard",confianza:1});
    setModoNacimientoManual(false);
  }

  const estadoManual = video.revision_manual?.estado;
  const tiempoRevisionRaw = Number(video.revision_manual?.tiempo_ms);
  const revisionManualValida = estadoManual !== "confirmado" || (Number.isFinite(tiempoRevisionRaw) && tiempoRevisionRaw >= 0);
  const revisionReparada = Boolean(video.revision_manual?.tiempo_reparado);
  const zona = video.zona_deteccion || {};
  const zonaBloqueada = Boolean(zonaAuto) && zona.bloqueada !== false;
  const zonaSugerida = Array.isArray(zona.bbox_sugerida_norm) ? zona.bbox_sugerida_norm : null;
  const zonaNacimientoPersistida = Array.isArray(video.ultima_zona_nacimiento?.bbox_norm) ? video.ultima_zona_nacimiento.bbox_norm.map(Number) : null;
  const zonaNacimientoVisible = modoZona ? zonaNacimiento : (zonaNacimiento || zonaNacimientoPersistida);
  const detalleNacimientoVisible = modoZona ? detalleNacimiento : (detalleNacimiento || video.ultima_zona_nacimiento || null);
  const mostrarNacimiento = Array.isArray(zonaNacimientoVisible) &&
    (modoZona || detalleNacimientoVisible?.frame_index == null || Number(detalleNacimientoVisible.frame_index) === Math.round(Number(frame)));
  const zonaZoomVisible = (modoZona && zonaTemporal) ? zonaZoomEnfocada(zonaNacimientoVisible,zonaTemporal) : zonaTemporal;
  const pct = zona.porcentajes || (zonaAuto ? {
    x: +(zonaAuto[0]*100).toFixed(1), y: +(zonaAuto[1]*100).toFixed(1),
    w: +((zonaAuto[2]-zonaAuto[0])*100).toFixed(1), h: +((zonaAuto[3]-zonaAuto[1])*100).toFixed(1) } : null);
  const zonaEtiqueta = fuenteZona.startsWith("manual_bloqueada") ? "Región dibujada en este video"
    : fuenteZona === "nombre_archivo" ? "Región heredada de otro video de esta cámara"
    : fuenteZona === "similitud_visual" ? `Región heredada por similitud (${(Number(zona.similitud_visual||0)*100).toFixed(0)}%)`
    : fuenteZona === "similitud_insuficiente" || fuenteZona === "nombre_no_coincide_visualmente" ? "Sin coincidencia visual suficiente"
    : "Sin zona aprendida todavía";
  const relojValidado = infoTiempo?.tiempo_overlay_ms;
  const relojLeido = infoTiempo?.tiempo_overlay_leido_ms ?? relojValidado;
  const fuenteActual = infoTiempo?.fuente_tiempo || (cargandoTiempo ? "validando…" : "pendiente");
  const advertenciaTiempo = infoTiempo?.advertencia
    || (revisionReparada ? video.revision_manual?.motivo_reparacion : null)
    || (infoTiempo?.fps_fuente === "desconocido" ? "No se leyó Rec…fps en ninguna cámara de este ensayo. El tiempo sólo se acepta desde el reloj visible." : null);
  const overlayCoincide = Boolean(infoTiempo?.overlay_valido);
  const textoEstado = estadoManual === "confirmado" && revisionManualValida ? (revisionReparada ? "Confirmado · tiempo reparado" : "Confirmado")
    : estadoManual === "confirmado" && !revisionManualValida ? "Revisión requerida (tiempo antiguo inválido)"
    : estadoManual === "sin_evento" ? "Sin apertura confirmado"
    : video.estado === "sin_evento" ? "Sin evento" : "Candidato automático";
  const etiquetaFps = {overlay_rec: "leído de Rec… fps", overlay_rec_otra_camara: "Rec… fps de otra cámara del ensayo",
    config_forzado: "fijado en config.yaml", archivo: "FPS del archivo", desconocido: "desconocido"}[fuenteFpsActual] || fuenteFpsActual;
  const guion = "—";

  return html`<div ref=${tarjetaRef} class=${`tarjeta-video-airbag ${estadoManual === "confirmado" && revisionManualValida ? "video-confirmado" : ""}`}
      tabIndex="0" onKeyDown=${tecladoVideo}>
    <div class="video-airbag-cabecera">
      <div><strong>${video.nombre || "Video"}</strong><small>${video.ruta_relativa || ""}</small></div>
      <div class="video-cabecera-acciones">
        <button type="button" class="boton boton-recalcular-video" onClick=${recalcularEsteVideo}
          disabled=${bloqueado||guardando||recalculandoVideo} title="Recalcular únicamente este video, sin repetir OCR ni los demás videos">
          ${recalculandoVideo ? "↻ Recalculando…" : "↻ Recalcular este video"}</button>
        <span class=${`chip ${estadoManual === "confirmado" && revisionManualValida ? "verde" : "neutro"}`}>${textoEstado}</span>
      </div>
    </div>
    <div class="video-airbag-grid">
      <div class=${`video-airbag-preview ${modoZona ? "seleccionando-zona" : ""}`}>
        <div class="video-frame-zona-lienzo" style=${{aspectRatio: proporcion}} onPointerDown=${iniciarZona} onPointerMove=${moverZona}
          onPointerUp=${terminarZona} onPointerCancel=${terminarZona}>
          <img ref=${imgZonaRef} src=${rutaFrameMostrada} alt=${`Cuadro ${frame} de ${video.nombre || "video"}`} draggable="false" />
          ${zonaVisible && html`<div class=${`video-zona-overlay ${zonaTemporal ? "temporal" : "aprendida"} ${zonaBloqueada && !zonaTemporal ? "bloqueada" : ""}`}
            style=${estiloZona(zonaVisible)}><span>${zonaTemporal ? "ROI general" : `${tipoCamara || "Zona"}${zonaBloqueada ? " · bloqueada" : ""}`}</span></div>`}
          ${mostrarNacimiento && html`<div class=${`video-zona-nacimiento-overlay ${detalleNacimientoVisible?.metodo === "manual_dashboard" ? "manual" : "automatica"}`}
            style=${estiloZona(zonaNacimientoVisible)}><span>◎ Nacimiento</span></div>`}
          ${!zonaTemporal && zonaSugerida && html`<div class="video-zona-overlay sugerida" style=${estiloZona(zonaSugerida)}><span>Sugerida</span></div>`}
          ${errorFrame && html`<div class="video-frame-error">No se pudo cargar el cuadro ${Math.round(frame)}</div>`}
        </div>
        ${(modoZona && zonaTemporal) && html`<div class="video-zona-zoom">
          <div class="video-zona-zoom-cabecera">
            <div><strong>Zoom exacto del nacimiento</strong><small> se acerca automáticamente al primer fragmento</small></div>
            <span>Cuadro ${Math.round(frame)}</span>
          </div>
          <div ref=${zoomZonaRef} class=${`video-zona-zoom-lienzo ${modoNacimientoManual ? "ajustando" : ""}`} style=${estiloLienzoZoom(zonaZoomVisible || zonaTemporal)}
            onPointerDown=${iniciarNacimientoManual} onPointerMove=${moverNacimientoManual}
            onPointerUp=${terminarNacimientoManual} onPointerCancel=${terminarNacimientoManual}
            aria-label="Zoom de la zona para ajustar el punto exacto de nacimiento">
            <img src=${rutaFrameMostrada} alt="Zoom de la zona de interés" draggable="false" style=${estiloImagenZoom(zonaZoomVisible || zonaTemporal)} />
            ${Array.isArray(zonaNacimientoVisible) && html`<div class=${`video-zona-nacimiento-zoom ${detalleNacimientoVisible?.metodo === "manual_dashboard" ? "manual" : "automatica"}`}
              style=${estiloNacimientoEnZoom(zonaNacimientoVisible,zonaZoomVisible || zonaTemporal)}><span>${detalleNacimientoVisible?.metodo === "manual_dashboard" ? "Tu ajuste" : "Nacimiento detectado"}</span></div>`}
            ${localizandoNacimiento && html`<div class="video-zona-localizando"><span class="spinner-inline">↻</span> Buscando el primer fragmento…</div>`}
          </div>
          <div class="video-zona-zoom-info">
            ${detalleNacimientoVisible?.error ? html`<span class="mensaje-error">${detalleNacimientoVisible.error}</span>`
              : Array.isArray(zonaNacimientoVisible) ? html`<span><strong>Microzona:</strong> ${detalleNacimientoVisible?.metodo === "manual_dashboard" ? "ajustada por ti" : "propuesta automáticamente"}
                  ${detalleNacimientoVisible?.confianza != null ? ` · confianza ${(Number(detalleNacimientoVisible.confianza)*100).toFixed(0)}%` : ""}
                  ${detalleNacimientoVisible?.persistencia != null ? ` · persistencia ${(Number(detalleNacimientoVisible.persistencia)*100).toFixed(0)}%` : ""}</span>`
              : html`<span>Selecciona la ROI general; el sistema buscará dentro de ella el primer cambio compatible con la bolsa.</span>`}
          </div>
          <div class="video-zona-zoom-acciones">
            <button type="button" class="boton" onClick=${()=>localizarNacimiento(zonaTemporal)} disabled=${bloqueado||guardando||localizandoNacimiento}>
              ${localizandoNacimiento ? "↻ Afinando…" : "◎ Afinar automáticamente"}</button>
            <button type="button" class=${`boton ${modoNacimientoManual ? "boton-primario" : ""}`}
              onClick=${()=>{setModoNacimientoManual(v=>!v); inicioNacimientoRef.current=null;}} disabled=${bloqueado||guardando||localizandoNacimiento}>
              ${modoNacimientoManual ? "Arrastra sobre el fragmento exacto" : "✎ Ajustar nacimiento a mano"}</button>
          </div>
          <small>La caja azul grande sólo dice <strong>dónde mirar</strong>. La caja pequeña marca <strong>dónde nació realmente</strong> el airbag y es la que se usa para recortar F-3…F+3 del aprendizaje visual.</small>
        </div>`}
        <div class="video-lectura-actual">
          <strong>Cuadro ${Math.round(frame)} / ${maxFrame}</strong>
          <span>${`${Number(tiempo).toFixed(1)} ms`}${cargandoTiempo ? html` <small class="validando">validando…</small>` : ""}</span>
        </div>
        <div class=${`video-roi-estado ${zonaBloqueada ? "bloqueada" : ""}`}>
          ${modoZona ? html`<div><strong>1. ROI general:</strong> encierra una zona suficientemente amplia donde aparece la bolsa. <strong>2. Nacimiento:</strong> el zoom localizará dentro de ella el primer fragmento y podrás corregirlo a mano.</div>`
          : zonaAuto ? html`<div>
              <strong>${zonaBloqueada ? "REGIÓN MANUAL BLOQUEADA" : "REGIÓN AJUSTADA AUTOMÁTICAMENTE"}</strong>
              <span class="mono">Cámara: ${tipoCamara || "sin etiqueta"} · X ${pct?.x ?? guion} % · Y ${pct?.y ?? guion} % · W ${pct?.w ?? guion} % · H ${pct?.h ?? guion} %</span>
              <small>${zonaEtiqueta}. ${zonaBloqueada ? "El sistema no puede mover esta región automáticamente." : "La autoalineación está activada en config.yaml."}</small>
            </div>`
          : html`<div><strong>Sin zona de interés</strong><small>Se analiza todo el cuadro. Usa “Marcar zona de interés” para enseñar dónde aparece primero la bolsa.</small></div>`}
          <div class="video-roi-sugerencia">${!modoZona && zonaSugerida && html`
            <small>El sistema sugiere mover la región (contorno discontinuo). Tú decides:</small>
            <button type="button" class="boton" onClick=${()=>guardarZona(zonaSugerida)} disabled=${bloqueado||guardando}>Aceptar ROI sugerida</button>`}</div>
        </div>
      </div>
      <div class="video-airbag-datos">
        <div class="video-revisor-controles-estables">
          <div class="video-timeline">
            <input type="range" min="0" max=${maxFrame} step="1" value=${frame}
              onInput=${e=>cambiarFrame(Number(e.target.value))} disabled=${bloqueado||guardando||modoZona}
              aria-label="Línea de tiempo del video" />
            <div class="video-timeline-marcas"><span>0</span><span>${Math.round(frame)}</span><span>${maxFrame}</span></div>
          </div>
          <div class="video-frame-controles">
            <button type="button" class="boton" onClick=${()=>moverFrame(-10)} disabled=${bloqueado||guardando}>← 10</button>
            <button type="button" class="boton" onClick=${()=>moverFrame(-1)} disabled=${bloqueado||guardando}>← 1 cuadro</button>
            <button type="button" class="boton" onClick=${()=>moverFrame(1)} disabled=${bloqueado||guardando}>1 cuadro →</button>
            <button type="button" class="boton" onClick=${()=>moverFrame(10)} disabled=${bloqueado||guardando}>10 →</button>
            <label>Cuadro exacto<input class="campo" type="number" min="0" max=${maxFrame}
              value=${frame} onInput=${e=>cambiarFrame(Number(e.target.value))} disabled=${bloqueado||guardando}/></label>
            <label>Tiempo del cuadro (ms)<input class="campo campo-tiempo-sincronizado" type="number" min="0" step="0.1" value=${Number(tiempo).toFixed(1)}
              readOnly aria-readonly="true" title="El tiempo se sincroniza con el cuadro, la tasa real Rec…fps y el reloj superior derecho." />
              <small>Sincronizado con el cuadro; no se guarda un tiempo contradictorio.</small></label>
          </div>
          <small class="atajos-video">Atajos: ←/→ = 1 cuadro · Shift+←/→ = 10 cuadros · Inicio/Fin = extremos.</small>
          <div class="acciones-revision-video">
            <button type="button" class="boton boton-primario" onClick=${()=>guardar("confirmado")}
              disabled=${bloqueado||guardando||cargandoTiempo||recalculandoVideo}>✓ Confirmar apertura aquí</button>
            <button type="button" class="boton" onClick=${()=>guardar("sin_evento")}
              disabled=${bloqueado||guardando||recalculandoVideo}>No hay apertura en este video</button>
          </div>
          <div class="video-maximo-visible">
            <strong>Máximo despliegue visible</strong>
            <p class="subtitulo-seccion">Después de confirmar la ruptura, avanza hasta el cuadro de mayor despliegue visible y guárdalo aquí. No es el inicio de ruptura ni una medición de volumen o de inflado completo.</p>
            <div class="acciones-revision-video">
              <button type="button" class="boton" onClick=${guardarMaximo}
                disabled=${bloqueado||guardando||cargandoTiempo||recalculandoVideo||estadoManual!=="confirmado"}
                title="Guarda el cuadro actual como máximo visible; apertura y su aprendizaje se conservan.">
                Confirmar máximo visible aquí</button>
              ${video.despliegue_maximo?.frame_index != null && html`<button type="button" class="boton"
                disabled=${guardando} onClick=${()=>cambiarFrame(Number(video.despliegue_maximo.frame_index))}>
                Ir al máximo guardado</button>`}
            </div>
            <p class="subtitulo-seccion" role="status">${video.despliegue_maximo
              ? `Cuadro ${video.despliegue_maximo.frame_index} · ${video.despliegue_maximo.tiempo_ms} ms · ${video.despliegue_maximo.estado === "confirmado" ? "confirmado" : "por revisar"}`
              : "Sin máximo confirmado. La celda del Excel permanece vacía."}</p>
          </div>
          ${recalculandoVideo && html`<div class="video-recalculo-individual"><span class="spinner-inline" aria-hidden="true">↻</span><span>${estadoRecalculoVideo?.mensaje || "Recalculando este video…"}</span></div>`}
          <div class="video-mensaje-reservado">${mensaje && html`<div class=${mensaje.ok ? "aviso" : "mensaje-error"}>${mensaje.texto}</div>`}</div>
          <div class="video-aviso-tiempo-reservado">${advertenciaTiempo && html`<div class="aviso aviso-advertencia video-aviso-tiempo"><strong>Control temporal:</strong> ${advertenciaTiempo}</div>`}</div>
        </div>
        <dl class="ficha ficha-video">
          <dt>FPS de grabación</dt><dd>${fpsActual ? Number(fpsActual).toFixed(0) : guion} <small>(${etiquetaFps})</small></dd>
          <dt>FPS del archivo</dt><dd>${video.fps_archivo ? Number(video.fps_archivo).toFixed(3) : guion} <small>(sólo reproducción)</small></dd>
          <dt>Resolución temporal</dt><dd>${resolucion ? `${resolucion.toFixed(3)} ms/cuadro` : "desconocida"}</dd>
          <dt>Tiempo del cuadro actual</dt><dd><strong>${Number(tiempo).toFixed(1)} ms</strong> · ${fuenteActual}</dd>
          <dt>Reloj esquina superior derecha</dt><dd>${relojLeido != null ? `${Number(relojLeido).toFixed(1)} ms` : (cargandoTiempo ? "leyendo…" : "no legible en este cuadro")}
            ${relojLeido != null ? (overlayCoincide ? html` <span class="chip verde chip-mini">coincide</span>` : html` <span class="chip neutro chip-mini">no coincide, descartado</span>`) : ""}</dd>
          <dt>Detección automática</dt><dd>cuadro ${video.frame_evento ?? guion} · ${video.tiempo_ms ?? guion} ms</dd>
          <dt>Tu confirmación</dt><dd>${estadoManual === "confirmado" ? `cuadro ${video.revision_manual?.frame_index ?? guion} · ${video.revision_manual?.tiempo_ms ?? guion} ms${revisionReparada ? ` (antes ${video.revision_manual?.tiempo_original_ms} ms)` : ""}` : estadoManual === "sin_evento" ? "sin apertura" : guion}</dd>
          <dt>Origen del análisis</dt><dd>${["recalculado_v15_6","recalculado_v15_7_3","recalculado_v15_7_4"].includes(video.origen_resultado_video) || video.desde_cache === false
            ? html`<span class="chip verde chip-mini">recalculado</span>`
            : video.desde_cache === true ? html`<span class="chip neutro chip-mini">caché</span>` : guion}
            ${video.algoritmo_video ? ` · ${video.algoritmo_video}` : ""}
            ${video.reanalizado_en ? ` · ${fmtFecha(video.reanalizado_en)}` : ""}</dd>
          <dt>Criterio</dt><dd>${!video.tipo_deteccion ? guion : video.metodo_confirmacion === "crecimiento_backtracking"
            ? `Nacimiento validado por crecimiento; retroceso de ${Number(video.retroceso_frames||0)} cuadro(s) al primer indicio`
            : video.tipo_deteccion === "primer_blanco_nuevo" ? `${zonaAuto ? "Primer blanco nuevo dentro de la región" : "Primer blanco nuevo visible"}` : video.tipo_deteccion}</dd>
          <dt>Validación temporal</dt><dd>${video.frame_confirmacion_automatica != null && video.frame_evento != null
            ? `Primer indicio: cuadro ${video.frame_evento} · evidencia fuerte: cuadro ${video.frame_confirmacion_automatica}` : guion}</dd>
          <dt>Crecimiento observado</dt><dd>${video.crecimiento_ratio != null ? `${Number(video.crecimiento_ratio).toFixed(2)}× en la ventana de confirmación` : guion}</dd>
          <dt>Score de apertura</dt><dd>${video.score_apertura != null ? `${(Number(video.score_apertura)*100).toFixed(1)}%` : guion}</dd>
          <dt>Ejemplos aprendidos</dt><dd>${(video.perfil_evento_aprendido?.ejemplos||0) > 0 ? `${Number(video.perfil_evento_aprendido.ejemplos)} de ${tipoCamara || "esta vista"}` : guion}</dd>
          <dt>Nacimiento preciso</dt><dd>${Array.isArray(zonaNacimientoVisible) ? `${detalleNacimientoVisible?.metodo === "manual_dashboard" ? "ajustado por ti" : "localizado automáticamente"}${detalleNacimientoVisible?.confianza != null ? ` · ${(Number(detalleNacimientoVisible.confianza)*100).toFixed(0)}%` : ""}` : guion}</dd>
          <dt>Confianza</dt><dd>${video.confianza != null ? `${(Number(video.confianza)*100).toFixed(1)}%` : guion}</dd>
          <dt>Texto de overlay</dt><dd class="mono">${video.overlay_texto || guion}</dd>
        </dl>
        <div class="video-zona-acciones">
          <button type="button" class=${`boton ${modoZona ? "boton-primario" : ""}`}
            onClick=${()=>{setModoZona(v=>!v); setZonaTemporal(null); setZonaNacimiento(null); setDetalleNacimiento(null); setModoNacimientoManual(false); inicioZonaRef.current=null; inicioNacimientoRef.current=null;}}
            disabled=${bloqueado||guardando||recalculandoVideo}>${zonaAuto ? "Redibujar zona de interés" : "◎ Marcar zona de interés"}</button>
          <button type="button" class="boton" onClick=${()=>guardarZona()}
            disabled=${bloqueado||guardando||!modoZona||!zonaTemporal} hidden=${!modoZona}>Guardar solo zona</button>
          <button type="button" class="boton boton-aprender-apertura" onClick=${guardarZonaYApertura}
            disabled=${bloqueado||guardando||cargandoTiempo||localizandoNacimiento||!modoZona||!zonaTemporal} hidden=${!modoZona}
            title="Guarda esta región como zona de interés y el cuadro actual como primer cuadro de apertura">✓ Esta zona + este cuadro = apertura</button>
          <button type="button" class="boton" onClick=${()=>{setModoZona(false);setZonaTemporal(null);setZonaNacimiento(null);setDetalleNacimiento(null);setModoNacimientoManual(false);}}
            disabled=${guardando} hidden=${!modoZona}>Cancelar</button>
        </div>
      </div>
    </div>
  </div>`;
}

function PanelVideosAirbag({ detalle, onSaved, bloqueado = false }) {
  const videos = detalle.videos || [];
  const [videosVisibles, setVideosVisibles] = useState(true);
  const [recalculando, setRecalculando] = useState(false);
  const [estadoRecalculo, setEstadoRecalculo] = useState(null);
  const [errorRecalculo, setErrorRecalculo] = useState(null);
  const c = detalle.video_apertura || {};
  const soporte = Number(c.soporte || 0);
  const valido = ["confirmado_manual", "primera_aparicion", "confirmado_3_de_4"].includes(c.estado) && c.tiempo_ms != null;
  const etiquetaEstado = c.estado === "confirmado_manual" ? `${c.tiempo_ms} ms · confirmado por ti (${c.camara_referencia || "video"})`
    : valido ? `${c.tiempo_ms} ms · primera aparición (${c.camara_referencia || "video"}, ${soporte} cámara${soporte === 1 ? "" : "s"})`
    : `Revisión · ${soporte} de ${videos.length}`;
  const excluidas = (c.camaras_excluidas || []).join(", ");

  // V15.7.4: recálculo completo del ID. Cada tarjeta también puede recalcular
  // un solo video mediante video_id, sin repetir OCR ni los demás videos.
  async function recalcularVideos() {
    if (recalculando) return;
    setErrorRecalculo(null);
    setEstadoRecalculo({ estado: "preparando", mensaje: "Preparando recálculo de videos…", procesados: 0, total_videos: videos.length });
    try {
      await enviarJSON("/api/video/reanalizar", { prueba_id: detalle.id, video_id: null });
      setRecalculando(true);
    } catch (e) {
      setEstadoRecalculo(null);
      setErrorRecalculo(e.message);
    }
  }

  useEffect(() => {
    if (!recalculando) return undefined;
    let cancelado = false;
    let temporizador = null;
    async function consultar() {
      try {
        const estado = await pedirJSON("/api/video/reanalisis/estado");
        if (cancelado) return;
        setEstadoRecalculo(estado);
        if (["completado", "error"].includes(estado?.estado)) {
          setRecalculando(false);
          if (estado.estado === "completado" && onSaved) await onSaved(estado);
          return;
        }
      } catch (e) {
        if (cancelado) return;
        setErrorRecalculo(e.message);
        setRecalculando(false);
        return;
      }
      temporizador = setTimeout(consultar, 800);
    }
    consultar();
    return () => { cancelado = true; if (temporizador) clearTimeout(temporizador); };
  }, [recalculando, detalle.id]);

  if (!videos.length) return null;

  const totalRecalculo = Number(estadoRecalculo?.total_videos || videos.length || 0);
  const procesadosRecalculo = Number(estadoRecalculo?.procesados || 0);
  const porcentajeRecalculo = totalRecalculo > 0 ? Math.min(100, (procesadosRecalculo / totalRecalculo) * 100) : 0;

  return html`<section class="tarjeta panel-videos-airbag">
    <div class="progreso-titulo video-panel-cabecera"><div><p class="sobrelinea">V15.8 · VIDEO</p><h3>Análisis de apertura del airbag</h3></div>
      <span class=${`chip ${valido ? "verde" : "neutro"}`}>${etiquetaEstado}</span></div>

    <div class="video-panel-herramientas" aria-label="Herramientas de video">
      <button type="button" class="boton boton-primario" onClick=${recalcularVideos} disabled=${recalculando}>
        ${recalculando ? "↻ Recalculando todos…" : "↻ Recalcular todos"}
      </button>
      <button type="button" class=${`boton boton-vista-videos ${videosVisibles ? "videos-abiertos" : "videos-cerrados"}`}
        onClick=${() => setVideosVisibles(v => !v)} aria-expanded=${videosVisibles}
        title=${videosVisibles ? "Ocultar las tarjetas de video" : "Mostrar las tarjetas de video"}>
        <span class="video-vista-icono" aria-hidden="true">${videosVisibles ? "▾" : "▸"}</span>
        <span>${videosVisibles ? "Ocultar videos" : "Mostrar videos"}</span>
        <span class="video-vista-contador">${videos.length}</span>
      </button>
      <span class="subtitulo-seccion video-contador-visible">${videosVisibles ? "Videos desplegados" : "Videos contraídos"}</span>
    </div>

    ${estadoRecalculo && estadoRecalculo.estado !== "inactivo" && html`<div class=${`aviso video-recalculo-estado ${estadoRecalculo.estado === "error" ? "aviso-error" : ""}`}>
      <strong>Recálculo:</strong> ${estadoRecalculo.mensaje || estadoRecalculo.estado}
      ${totalRecalculo > 0 ? ` · ${procesadosRecalculo}/${totalRecalculo} (${porcentajeRecalculo.toFixed(0)}%)` : ""}
      ${estadoRecalculo.video_actual ? html`<span class="mono"> · ${estadoRecalculo.video_actual}</span>` : ""}
      ${estadoRecalculo.ultimo_error ? html`<div class="mensaje-error">${estadoRecalculo.ultimo_error}</div>` : ""}
    </div>`}
    ${errorRecalculo && html`<div class="mensaje-error" role="alert">${errorRecalculo}</div>`}

    <p class="subtitulo-seccion">Apertura = primera ruptura visible de la costura, no el abombamiento previo. El detector propone un indicio y busca corroboración posterior; revisa el cuadro anterior y el siguiente. No se garantiza detectar cualquier píxel con compresión, reflejos u oclusión${excluidas ? `. ${excluidas} no define el tiempo por ser la vista trasera` : ""}. Tus confirmaciones manuales mandan.</p>
    <div class="video-panel-avisos-reservado">
      ${c.camara_anterior_sin_respaldo && html`<div class="aviso aviso-advertencia">
        <strong>Revisa ${c.camara_anterior_sin_respaldo.camara || c.camara_anterior_sin_respaldo.video}:</strong> detectó apertura en ${c.camara_anterior_sin_respaldo.tiempo_ms} ms, antes que las demás cámaras, sin que ninguna lo respalde. Confírmalo o corrígelo en su tarjeta.
      </div>`}
    </div>

    ${videosVisibles ? html`<div class="lista-videos-airbag">${videos.map(video => html`<${TarjetaVideoAirbag} key=${video.id||video.ruta}
      video=${video} pruebaId=${detalle.id} onSaved=${onSaved} bloqueado=${bloqueado} />`)}</div>`
      : html`<div class="videos-ocultos-resumen">
          <div><strong>Videos ocultos</strong><p class="subtitulo-seccion">La sección está contraída para dejar más espacio al resto del ID.</p></div>
          <button type="button" class="boton" onClick=${() => setVideosVisibles(true)}>Desplegar videos</button>
        </div>`}
  </section>`;
}

function VistaDetalle({ nombre }) {
  const [ocultarVerificadas, setOcultarVerificadas] = useState(false);
  const [ocultarSinTexto, setOcultarSinTexto] = useState(false);
  const [guardandoImagen, setGuardandoImagen] = useState(false);
  const [avisoNavegacion, setAvisoNavegacion] = useState("");
  const [detalle, setDetalle, errorDetalle] = useApi(`/api/pruebas/${encodeURIComponent(nombre)}`, [nombre]);
  const [config, , errorConfig] = useApi("/api/config");
  const [aprendizaje, setAprendizaje] = useApi("/api/aprendizaje", [nombre]);
  const [reglas, setReglas] = useApi("/api/reglas", [nombre]);
  const [unidadId, setUnidadId] = useState("");
  const [textoCorrecto, setTextoCorrecto] = useState("");
  const [estrategiaOcrPendiente, setEstrategiaOcrPendiente] = useState(null);
  const versionBorradorRef = useRef(0);
  const textoPersistidoRef = useRef("");
  const seleccionActualRef = useRef({ imagenId: "", unidadId: "" });
  const actualizarTextoCorrecto = useCallback((valor, marcarPersistido = false) => {
    versionBorradorRef.current += 1;
    setTextoCorrecto(valor);
    if (marcarPersistido) textoPersistidoRef.current = String(valor ?? "");
  }, []);
  const [imagenId, setImagenId] = useState("");
  const [modoEdicion, setModoEdicion] = useState(false);
  const [accionSupervision, setAccionSupervision] = useState("guardar_sin_entrenar");
  const [componenteSupervision, setComponenteSupervision] = useState("por_identificar");
  const [campoDestino, setCampoDestino] = useState("");
  const [guardandoCorreccion, setGuardandoCorreccion] = useState(false);
  const [resultadoCorreccion, setResultadoCorreccion] = useState(null);
  const [mostrarCorreccion, setMostrarCorreccion] = useState(false);
  const [region, setRegion] = useState(null);
  const [anguloRegion, setAnguloRegion] = useState(0);
  const [poligonoRegion, setPoligonoRegion] = useState(null);
  const [textoRegion, setTextoRegion] = useState("");
  const [entrenarRegion, setEntrenarRegion] = useState(true);
  const [guardandoRegion, setGuardandoRegion] = useState(false);
  const [resultadoRegion, setResultadoRegion] = useState(null);
  const [revisionEditor, setRevisionEditor] = useState(0);
  const [modoRecorte, setModoRecorte] = useState("auto");
  const [zoomOcr, setZoomOcr] = useState(1.5);
  const [roiOcr, setRoiOcr] = useState(null);
  const [alcanceRoi, setAlcanceRoi] = useState("etiqueta");
  const [campoManual, setCampoManual] = useState("");
  const [valorManual, setValorManual] = useState("");
  const [motivoSinDatos, setMotivoSinDatos] = useState("");
  useEffect(() => {
    const imagenes = detalle?.imagenes?.length ? detalle.imagenes
      : [detalle?.etiqueta, detalle?.referencia].filter(Boolean);
    const primeraImagen = imagenes[0];
    setOcultarVerificadas(false); setOcultarSinTexto(false); setAvisoNavegacion("");
    const ocr = primeraImagen?.resultado_ocr || {};
    const unidades = unidadesOcr(ocr);
    const primero = unidades[0];
    const valor = textoVisible(primero);
    setImagenId(primeraImagen?.id || "");
    setUnidadId(primero?.unidad_id || "");
    actualizarTextoCorrecto(valor, true);
    setResultadoCorreccion(null);
    setEstrategiaOcrPendiente(null);
    setMostrarCorreccion(false);
    setRegion(null); setAnguloRegion(0); setPoligonoRegion(null);
    setRoiOcr(null);
    setTextoRegion("");
    setEntrenarRegion(true);
    setResultadoRegion(null);
    setModoEdicion(false);
    const primeraClave = Object.keys(detalle?.campos || {})[0] || "";
    setCampoManual(primeraClave);
    setValorManual(detalle?.campos?.[primeraClave]?.valor || "");
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
  const imagenesVisibles = imagenesParaRevisar(imagenesDetalle, ocultarVerificadas, ocultarSinTexto);
  const imagenSeleccionada = imagenesVisibles.find((imagen) => imagen.id === imagenId)
    || imagenesVisibles[0];
  const indiceImagen = imagenesVisibles.findIndex(i => i.id === imagenSeleccionada?.id);
  const ocrSeleccionado = imagenSeleccionada?.resultado_ocr || {};
  const qrsDetalle = imagenesDetalle.flatMap((imagen) =>
    (imagen.resultado_ocr?.qrs || []).map((qr) => ({ ...qr, imagenNombre: imagen.nombre,
      faseImagen: imagen.fase, torImagen: imagen.tor })));
  const unidadesCorregibles = unidadesOcr(ocrSeleccionado);
  const unidadSeleccionada = unidadesCorregibles.find((unidad) => unidad.unidad_id === unidadId)
    || unidadesCorregibles[0];
  seleccionActualRef.current = { imagenId: imagenSeleccionada?.id || "", unidadId: unidadSeleccionada?.unidad_id || "" };
  const revisionCompletada = detalle.revision?.estado === "completada";
  const reglasRelacionadas = (reglas?.reglas || []).filter((regla) =>
    Object.entries(regla.alcance || {}).every(([clave, valor]) =>
      String(detalle[clave] || "") === String(valor)));

  function estadoBorradoresActivos() {
    const estado = {pendiente:false, ocupado:false, motivos:[], operaciones:[]};
    window.dispatchEvent(new CustomEvent("ocr-consultar-borradores", {detail:estado}));
    return estado;
  }
  function hayCambiosSinGuardar(estado = estadoBorradoresActivos()) {
    // Dibujar/seleccionar una caja sin escribir ni generar una propuesta no es un cambio persistible.
    // Antes se trataba `region` por sí sola como borrador y provocaba avisos falsos incluso después de verificar.
    return textoCorrecto !== textoPersistidoRef.current || Boolean(textoRegion.trim()) || Boolean(estado.pendiente);
  }
  function describirCambiosSinGuardar(estado = estadoBorradoresActivos()) {
    const motivos = [];
    if (textoCorrecto !== textoPersistidoRef.current) motivos.push("Corrección de texto: modificaste ‘Texto correcto’ y falta pulsar Aplicar corrección.");
    if (textoRegion.trim()) motivos.push("Texto nuevo: escribiste contenido en una región y falta guardarlo.");
    for (const motivo of (estado.motivos || [])) if (!motivos.includes(motivo)) motivos.push(motivo + ".");
    return motivos;
  }
  function mensajeCambiosSinGuardar(estado = estadoBorradoresActivos()) {
    const motivos = describirCambiosSinGuardar(estado).map(m => t(m));
    const detalle = motivos.length ? `\n• ${motivos.join("\n• ")}` : "";
    return `${t("Hay cambios sin guardar.")}${detalle}\n\n${t("Guarda el cambio correspondiente o usa Cerrar herramienta / Descartar propuesta antes de marcar la imagen como verificada.")}`;
  }
  function cerrarHerramientasTransitorias() {
    setRegion(null); setAnguloRegion(0); setTextoRegion(""); setEntrenarRegion(false); setRoiOcr(null);
    setMostrarCorreccion(false); setResultadoRegion(null); setEstrategiaOcrPendiente(null);
    setRevisionEditor(v => v + 1);
  }
  function cerrarCorreccionActiva() {
    actualizarTextoCorrecto(textoPersistidoRef.current, true);
    setEstrategiaOcrPendiente(null);
    setMostrarCorreccion(false);
  }
  function permitirCambioImagen() {
    const estado = estadoBorradoresActivos();
    if (guardandoCorreccion || guardandoRegion || guardandoImagen || estado.ocupado) {
      setAvisoNavegacion("Espera a que termine la operación antes de cambiar de imagen."); return false;
    }
    if (hayCambiosSinGuardar(estado) && !window.confirm(`${mensajeCambiosSinGuardar(estado)}\n\n${t("¿Descartar estos cambios y continuar?")}`)) return false;
    setAvisoNavegacion(""); return true;
  }
  function cambiarImagen(nuevoId, centrarVisor = false, confirmado = false, lista = imagenesDetalle) {
    if (!confirmado && nuevoId === imagenSeleccionada?.id) return true;
    if (!confirmado && !permitirCambioImagen()) return false;
    setImagenId(nuevoId);
    const imagen = lista.find((item) => item.id === nuevoId);
    const ocr = imagen?.resultado_ocr || {};
    const primera = unidadesOcr(ocr)[0];
    const valor = textoVisible(primera);
    setUnidadId(primera?.unidad_id || "");
    seleccionActualRef.current = { imagenId: nuevoId || "", unidadId: primera?.unidad_id || "" };
    actualizarTextoCorrecto(valor, true);
    setResultadoCorreccion(null);
    setMostrarCorreccion(false);
    setRegion(null); setAnguloRegion(0);
    setRoiOcr(null);
    setTextoRegion("");
    setEntrenarRegion(false);
    setResultadoRegion(null);
    if (!revisionCompletada && nuevoId) {
      setModoEdicion(true);
      window.setTimeout(() => (centrarVisor
        ? document.getElementById(`visor-imagen-${nuevoId}`)
        : document.querySelector(".aprendizaje-panel"))?.scrollIntoView({
        behavior: "smooth", block: "start",
      }), 0);
    }
    return true;
  }
  function aplicarFiltrosNavegacion(nuevoOcultarVerificadas, nuevoOcultarSinTexto) {
    const visibles = imagenesParaRevisar(imagenesDetalle, nuevoOcultarVerificadas, nuevoOcultarSinTexto);
    if (!visibles.some(i => i.id === imagenSeleccionada?.id)) {
      if (!permitirCambioImagen()) return false;
      cambiarImagen(visibles[0]?.id || "", false, true, imagenesDetalle);
    }
    setOcultarVerificadas(nuevoOcultarVerificadas);
    setOcultarSinTexto(nuevoOcultarSinTexto);
    return true;
  }
  function alternarVerificadas() {
    aplicarFiltrosNavegacion(!ocultarVerificadas, ocultarSinTexto);
  }
  function alternarSinTexto() {
    aplicarFiltrosNavegacion(ocultarVerificadas, !ocultarSinTexto);
  }
  const controlesImagen = html`<nav class="navegacion-imagenes" aria-label="Navegar imágenes">
    <button type="button" class="boton" disabled=${indiceImagen <= 0 || guardandoImagen}
      onClick=${()=>cambiarImagen(imagenesVisibles[indiceImagen-1].id)}>← Anterior</button>
    <span role="status">${imagenesVisibles.length ? `Imagen ${indiceImagen+1} de ${imagenesVisibles.length}${ocultarVerificadas ? " · sin verificadas" : ""}${ocultarSinTexto ? " · sin imágenes marcadas sin texto" : ""}` : "No hay imágenes visibles"}</span>
    <button type="button" class="boton" disabled=${indiceImagen < 0 || indiceImagen >= imagenesVisibles.length-1 || guardandoImagen}
      onClick=${()=>cambiarImagen(imagenesVisibles[indiceImagen+1].id)}>Siguiente →</button>
    <button type="button" class="boton" aria-pressed=${ocultarVerificadas} disabled=${guardandoImagen}
      onClick=${alternarVerificadas}>${ocultarVerificadas ? "Mostrar imágenes verificadas" : "Ocultar imágenes verificadas"}</button>
    <button type="button" class="boton" aria-pressed=${ocultarSinTexto} disabled=${guardandoImagen}
      onClick=${alternarSinTexto}>${ocultarSinTexto ? "Mostrar imágenes sin texto" : "Ocultar imágenes sin texto"}</button>
    ${avisoNavegacion && html`<p role="alert">${avisoNavegacion}</p>`}
    ${!imagenesVisibles.length && html`<p>${imagenesDetalle.length ? "No hay imágenes que coincidan con los filtros actuales. Puedes volver a mostrarlas desde los botones de filtro." : "Esta carpeta no contiene imágenes."}</p>`}
  </nav>`;
  function seleccionarUnidad(imagen, unidad) {
    if (imagen?.id !== imagenSeleccionada?.id && !permitirCambioImagen()) return;
    const candidatas = unidadesOcr(imagen?.resultado_ocr || {});
    const exacta = candidatas.find((item) => firmaUnidad(item) === firmaUnidad(unidad)) || candidatas[0];
    setImagenId(imagen?.id || "");
    setUnidadId(exacta?.unidad_id || "");
    seleccionActualRef.current = { imagenId: imagen?.id || "", unidadId: exacta?.unidad_id || "" };
    actualizarTextoCorrecto(textoVisible(exacta), true);
    setEstrategiaOcrPendiente(null);
    setModoEdicion(true);
    setResultadoCorreccion(null);
    setMostrarCorreccion(true);
    window.setTimeout(() => {
      const formulario = document.getElementById("formulario-correccion-activa");
      formulario?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      formulario?.querySelector("textarea")?.focus({ preventScroll: true });
      formulario?.classList.remove("destacar-formulario");
      requestAnimationFrame(() => formulario?.classList.add("destacar-formulario"));
    }, 0);
  }
  async function confirmarCorreccion(e, accionForzada = null) {
    e.preventDefault();
    const versionEnviada = versionBorradorRef.current;
    const accionEfectiva = accionForzada || (accionSupervision === "aceptar" && textoCorrecto === textoVisible(unidadSeleccionada) ? "aceptar" : "corregir");
    const textoEnviado = accionEfectiva === "aceptar" ? textoVisible(unidadSeleccionada) : textoCorrecto;
    const seleccionEnviada = { imagenId: imagenSeleccionada?.id || "", unidadId: unidadSeleccionada?.unidad_id || "" };
    setGuardandoCorreccion(true);
    setResultadoCorreccion(null);
    try {
      const resultado = await enviarJSON("/api/aprendizaje/correcciones", {
        prueba_id: detalle.id, campo: "etiqueta", imagen_id: imagenSeleccionada?.id,
        texto_ocr: textoUnidad(unidadSeleccionada),
        texto_correcto: textoEnviado,
        bbox: unidadSeleccionada?.bbox || null,
        tipo_unidad: unidadSeleccionada?.tipo_unidad || null,
        componente: componenteSupervision,
        campo_destino: campoDestino || null,
        estrategia_ocr: estrategiaOcrPendiente,
        accion: accionEfectiva,
      });
      const actualizado = await pedirJSON(`/api/pruebas/${encodeURIComponent(nombre)}`);
      setDetalle(actualizado);
      const imagenActualizada = (actualizado.imagenes || []).find(i=>i.id===imagenSeleccionada?.id);
      const guardada = unidadesOcr(imagenActualizada?.resultado_ocr || {}).find(u=>
        u.tipo_unidad === unidadSeleccionada?.tipo_unidad &&
        JSON.stringify(u.bbox || null) === JSON.stringify(unidadSeleccionada?.bbox || null));
      if (!["ilegible","no_es_campo"].includes(accionEfectiva)) {
        if (!guardada || textoVisible(guardada).trim() !== textoEnviado.trim()) {
          throw new Error("El servidor respondió, pero la lectura recargada no coincide con tu corrección. Conservamos tu borrador; no la damos por confirmada.");
        }
        const sigueEnLaMismaSeleccion = seleccionActualRef.current.imagenId === seleccionEnviada.imagenId
          && seleccionActualRef.current.unidadId === seleccionEnviada.unidadId;
        // Una respuesta tardía confirma el dato en el servidor, pero nunca devuelve
        // el editor a la caja anterior si el usuario ya está trabajando en otra.
        if (sigueEnLaMismaSeleccion) {
          setUnidadId(guardada.unidad_id);
          seleccionActualRef.current = { imagenId: seleccionEnviada.imagenId, unidadId: guardada.unidad_id };
          textoPersistidoRef.current = textoVisible(guardada);
          if (versionBorradorRef.current === versionEnviada) setTextoCorrecto(textoVisible(guardada));
        }
      }
      setResultadoCorreccion({ ok: true, resultado });
      if (seleccionActualRef.current.imagenId === seleccionEnviada.imagenId &&
          seleccionActualRef.current.unidadId === seleccionEnviada.unidadId) setEstrategiaOcrPendiente(null);
      pedirJSON("/api/aprendizaje").then(setAprendizaje).catch(() => {});
    } catch (error) {
      setResultadoCorreccion({ ok: false, mensaje: error.message });
    } finally {
      setGuardandoCorreccion(false);
    }
  }
  async function descartarTexto(unidad, restaurar = false) {
    if (!unidad?.bbox || guardandoCorreccion) return;
    setGuardandoCorreccion(true);
    try {
      const resultado = await enviarJSON("/api/aprendizaje/no-texto", {
        prueba_id: detalle.id, imagen_id: imagenSeleccionada.id,
        bbox: unidad.bbox, restaurar,
      });
      setDetalle(await pedirJSON(`/api/pruebas/${encodeURIComponent(nombre)}`));
      setResultadoCorreccion({ok: true, resultado});
      setUnidadId("");
    } catch (e) { setResultadoCorreccion({ok: false, mensaje: e.message}); }
    finally { setGuardandoCorreccion(false); }
  }
  async function descartarTextosMultiples(imagen, unidades) {
    const bboxes = (unidades || []).map((u) => u?.bbox).filter((b) => Array.isArray(b) && b.length === 4);
    if (!imagen?.id || !bboxes.length || guardandoCorreccion) return;
    setGuardandoCorreccion(true);
    setResultadoCorreccion(null);
    try {
      const resultado = await enviarJSON("/api/aprendizaje/no-texto-lote", {
        prueba_id: detalle.id, imagen_id: imagen.id, bboxes,
      });
      const actualizado = await pedirJSON(`/api/pruebas/${encodeURIComponent(nombre)}`);
      setDetalle(actualizado);
      setResultadoCorreccion({ok: true, resultado});
      if (imagen.id === imagenSeleccionada?.id) {
        const actual = (actualizado.imagenes || []).find((i) => i.id === imagen.id);
        const primera = unidadesOcr(actual?.resultado_ocr || {})[0];
        setUnidadId(primera?.unidad_id || "");
        seleccionActualRef.current = {imagenId: imagen.id, unidadId: primera?.unidad_id || ""};
        actualizarTextoCorrecto(textoVisible(primera), true);
      }
    } catch (e) {
      setResultadoCorreccion({ok:false, mensaje:e.message});
    } finally { setGuardandoCorreccion(false); }
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
      const dimensionesRegion = ocrSeleccionado.dimensiones || ocrSeleccionado.dimensiones_originales || [];
      const poligono = poligonoRegion || (Math.abs(Number(anguloRegion) || 0) >= .05
        ? poligonoRectanguloRotado(region, anguloRegion, dimensionesRegion) : null);
      if ((poligonoRegion || Math.abs(Number(anguloRegion) || 0) >= .05) && !poligono) {
        throw new Error("La geometría flexible sale de la imagen. Muévela o ajusta sus esquinas antes de guardarla.");
      }
      const resultado = await enviarJSON("/api/aprendizaje/regiones", {
        prueba_id: detalle.id, imagen_id: imagenSeleccionada?.id,
        bbox: region, poligono, texto_correcto: textoRegion,
        proponer_entrenamiento: true,
      });
      setResultadoRegion({ ok: true, resultado });
      const actualizado = await pedirJSON(`/api/pruebas/${encodeURIComponent(nombre)}`);
      setDetalle(actualizado);
      setRegion(null); setAnguloRegion(0); setPoligonoRegion(null);
      setTextoRegion("");
      setEntrenarRegion(true);
    } catch (error) {
      setResultadoRegion({ ok: false, mensaje: error.message });
    } finally {
      setGuardandoRegion(false);
    }
  }
  async function rotarImagen(imagen, grados, usarAutomatico = false) {
    setResultadoCorreccion(null);
    try {
      const resultado = await enviarJSON("/api/aprendizaje/rotaciones", {
        tipo: "carpeta", prueba_id: detalle.id, imagen_id: imagen.id, grados,
        usar_automatico: usarAutomatico,
      });
      setResultadoCorreccion({ ok: true, rotacion: true, resultado });
      setDetalle(await pedirJSON(`/api/pruebas/${encodeURIComponent(nombre)}`));
      pedirJSON("/api/aprendizaje").then(setAprendizaje).catch(() => {});
    } catch (error) {
      setResultadoCorreccion({ ok: false, mensaje: error.message });
    }
  }
  async function marcarSinDatos(imagen, restaurar = false) {
    setResultadoCorreccion(null);
    try {
      const resultado = await enviarJSON(restaurar ? "/api/imagenes/con-texto" : "/api/imagenes/sin-datos", {
        tipo: "carpeta", prueba_id: detalle.id, imagen_id: imagen.id,
        motivo: motivoSinDatos.trim() || null,
      });
      setResultadoCorreccion({ ok: true, sinDatos: true, resultado });
      const actualizado = await pedirJSON(`/api/pruebas/${encodeURIComponent(nombre)}`);
      if (!restaurar && ocultarSinTexto) {
        const lista = actualizado.imagenes?.length ? actualizado.imagenes : [actualizado.etiqueta, actualizado.referencia].filter(Boolean);
        const restantes = imagenesParaRevisar(lista, ocultarVerificadas, true);
        const indice = lista.findIndex(i => i.id === imagen.id);
        const siguiente = lista.slice(indice + 1).find(i => restantes.some(r => r.id === i.id)) || restantes[restantes.length - 1];
        cambiarImagen(siguiente?.id || "", false, true, lista);
      }
      setDetalle(actualizado);
    } catch (error) {
      setResultadoCorreccion({ ok: false, mensaje: error.message });
    }
  }
  async function verificarImagen(imagen) {
    if (guardandoImagen) return;
    const estado = estadoBorradoresActivos();
    if (guardandoCorreccion || guardandoRegion || estado.ocupado) {
      setResultadoCorreccion({ok:false, mensaje:"Espera a que termine el guardado actual antes de verificar la imagen."});
      return;
    }
    if (hayCambiosSinGuardar(estado)) {
      // Compatibilidad histórica: Hay cambios sin guardar. Guarda la corrección o cierra/descarta la herramienta activa antes de marcar la imagen como verificada.
      setResultadoCorreccion({ok:false, mensaje:mensajeCambiosSinGuardar(estado)});
      return;
    }
    setGuardandoImagen(true);
    setResultadoCorreccion(null);
    try {
      const resultado = await enviarJSON("/api/imagenes/verificar", {
        prueba_id: detalle.id, imagen_id: imagen.id,
      });
      const actualizado = await pedirJSON(`/api/pruebas/${encodeURIComponent(nombre)}`);
      const lista = actualizado.imagenes?.length ? actualizado.imagenes : [actualizado.etiqueta, actualizado.referencia].filter(Boolean);
      const imagenActualizada = lista.find(i => i.id === imagen.id);
      const unidadesActualizadas = unidadesOcr(imagenActualizada?.resultado_ocr || {});
      const unidadActualizada = unidadesActualizadas.find(u => u.unidad_id === unidadId) || unidadesActualizadas[0];
      if (imagenSeleccionada?.id === imagen.id) {
        setUnidadId(unidadActualizada?.unidad_id || "");
        seleccionActualRef.current = {imagenId: imagen.id, unidadId: unidadActualizada?.unidad_id || ""};
        actualizarTextoCorrecto(textoVisible(unidadActualizada), true);
        cerrarHerramientasTransitorias();
      }
      setResultadoCorreccion({ ok: true, imagenVerificada: true, resultado });
      if (ocultarVerificadas) {
        const restantes = imagenesParaRevisar(lista, true, ocultarSinTexto);
        const indice = lista.findIndex(i=>i.id===imagen.id);
        const siguiente = lista.slice(indice+1).find(i=>restantes.some(r=>r.id===i.id)) || restantes[restantes.length-1];
        cambiarImagen(siguiente?.id || "", false, true, lista);
      }
      setDetalle(actualizado);
    } catch (error) {
      setResultadoCorreccion({ ok: false, mensaje: error.message });
    } finally { setGuardandoImagen(false); }
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
  async function reprocesar(soloErrores = false, soloImagenVisible = false) {
    setResultadoCorreccion(null);
    try {
      let roiManual = null;
      if (modoRecorte === "manual") {
        const dimensiones = ocrSeleccionado.dimensiones || ocrSeleccionado.dimensiones_originales;
        if (!roiOcr || !dimensiones?.[0] || !dimensiones?.[1]) {
          throw new Error("Para el modo manual, selecciona primero una región sobre la imagen.");
        }
        roiManual = { x: roiOcr[0] / dimensiones[0], y: roiOcr[1] / dimensiones[1],
          ancho: roiOcr[2] / dimensiones[0], alto: roiOcr[3] / dimensiones[1] };
      }
      const resultado = await enviarJSON(`/api/casos/${encodeURIComponent(detalle.id)}/reprocesar`, {
        solo_errores: soloErrores,
        imagenes: soloImagenVisible && imagenSeleccionada?.ruta ? [imagenSeleccionada.ruta] : [],
        modo_recorte: modoRecorte,
        roi_manual: roiManual,
        zoom_forzado: zoomOcr,
        roi_alcance: alcanceRoi,
      });
      setResultadoCorreccion({ ok: true, reproceso: true, resultado });
      location.hash = "#/carga";
    } catch (error) {
      setResultadoCorreccion({ ok: false, mensaje: error.message });
    }
  }
  async function cambiarRegla(regla, estado) {
    try {
      await enviarJSON(`/api/reglas/${encodeURIComponent(regla.id)}`, {
        estado, usuario: "dashboard",
      });
      setReglas(await pedirJSON("/api/reglas"));
    } catch (error) {
      setResultadoCorreccion({ ok: false, mensaje: error.message });
    }
  }
  async function guardarCampoManual(e) {
    e.preventDefault();
    if (!campoManual || !valorManual.trim()) return;
    try {
      const resultado = await enviarJSON(
        `/api/casos/${encodeURIComponent(detalle.id)}/campos/${encodeURIComponent(campoManual)}`,
        { valor: valorManual.trim(), usuario: "dashboard" });
      setResultadoCorreccion({ ok: true, campoManual: true, resultado });
      setDetalle(await pedirJSON(`/api/pruebas/${encodeURIComponent(nombre)}`));
    } catch (error) {
      setResultadoCorreccion({ ok: false, mensaje: error.message });
    }
  }
  async function entrenarVisual() {
    try {
      const resultado = await enviarJSON("/api/aprendizaje/entrenar-visual", {});
      setResultadoCorreccion({ ok: true, entrenamientoVisual: true, resultado });
      setAprendizaje(await pedirJSON("/api/aprendizaje"));
    } catch (error) {
      setResultadoCorreccion({ ok: false, mensaje: error.message });
    }
  }
  async function activarUltimoVisual() {
    const version = aprendizaje?.ultimo_modelo_visual?.version;
    if (!version) return;
    try {
      const resultado = await enviarJSON(
        `/api/aprendizaje/modelos-visuales/${encodeURIComponent(version)}/activar`, {});
      setResultadoCorreccion({ ok: true, modeloVisual: true, resultado });
      setAprendizaje(await pedirJSON("/api/aprendizaje"));
    } catch (error) { setResultadoCorreccion({ ok: false, mensaje: error.message }); }
  }
  async function restaurarVisual() {
    try {
      const resultado = await enviarJSON("/api/aprendizaje/rollback-visual", { version: null });
      setResultadoCorreccion({ ok: true, modeloVisual: true, resultado });
      setAprendizaje(await pedirJSON("/api/aprendizaje"));
    } catch (error) { setResultadoCorreccion({ ok: false, mensaje: error.message }); }
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

    ${detalle.perfil === "empresarial" && html`<div class="tarjeta" style=${{ marginTop: 12 }}>
      <div class="progreso-titulo"><h3>Resultado consolidado del ID</h3>
        <span class=${`chip ${detalle.requiere_revision ? "" : "neutro"}`}>
          ${detalle.estado || "detectada"}</span></div>
      <dl class="ficha">
        <dt>Proyecto</dt><dd>${detalle.tipo_st || "Sin determinar"}</dd>
        <dt>Condición</dt><dd>${detalle.temperature_condition || "—"} ·
          ${detalle.module_version || "—"} · ${detalle.inflator_type || "—"}</dd>
        <dt>Fotografías</dt><dd>${detalle.total_imagenes || detalle.imagenes?.length || 0} ·
          NACH ${detalle.imagenes_nach || 0} · VOR ${detalle.imagenes_vor || 0} ·
          TOR ${(detalle.carpetas_tor || []).length}</dd>
        <dt>Videos</dt><dd>${detalle.total_videos || detalle.videos?.length || 0} ·
          ${detalle.video_apertura?.tiempo_ms != null ? `apertura ${detalle.video_apertura.tiempo_ms} ms` : "tiempo pendiente"}</dd>
        <dt>Avance</dt><dd>${Number(detalle.progreso?.porcentaje || 0).toFixed(1)}% ·
          ${detalle.progreso?.con_texto || 0} ${t("con texto")} · ${detalle.progreso?.sin_texto || 0} ${t("descartadas")}</dd>
        <dt>Campos faltantes</dt><dd>${(detalle.campos_faltantes || []).join(", ") || "Ninguno"}</dd>
        <dt>Conflictos</dt><dd>${(detalle.conflictos || []).join(", ") || "Ninguno"}</dd>
      </dl>
      <div class="acciones-revision">
        <select class="campo" value=${modoRecorte} onChange=${(e) => setModoRecorte(e.target.value)}>
          <option value="auto">Recorte automático</option>
          <option value="manual">ROI manual seleccionada</option>
          <option value="completo">Imagen completa</option>
        </select>
        <label class="control-zoom-ocr">Zoom OCR · mejora la lectura: <strong>${Number(zoomOcr).toFixed(1)}×</strong>
          <input type="range" min="1" max="3" step="0.1" value=${zoomOcr}
            onInput=${(e) => setZoomOcr(Number(e.target.value))} />
        </label>
        ${modoRecorte === "manual" && html`<select class="campo" value=${alcanceRoi}
          aria-label="Guardar ROI para" onChange=${(e) => setAlcanceRoi(e.target.value)}>
          <option value="etiqueta">Guardar para esta etiqueta</option>
          <option value="fase">Guardar para esta fase NACH/VOR</option>
          <option value="proyecto">Guardar para todo el proyecto</option>
        </select>`}
        ${modoRecorte === "manual" && roiOcr && html`<span class="subtitulo-seccion">
          Recorte enviado al OCR: ${roiOcr[2]}×${roiOcr[3]} px →
          ${Math.round(roiOcr[2] * zoomOcr)}×${Math.round(roiOcr[3] * zoomOcr)} px
        </span>`}
        ${modoRecorte === "manual"
          ? html`<button class="boton boton-primario" disabled=${!roiOcr}
              onClick=${() => reprocesar(false, true)}>Reprocesar imagen visible con esta ROI</button>`
          : html`<button class="boton" onClick=${() => reprocesar(false)}>Reprocesar este ID</button>`}
        <button class="boton" onClick=${() => reprocesar(true)}>Reintentar imágenes con error</button>
        <button class="boton" disabled=${!imagenSeleccionada}
          onClick=${() => reprocesar(false, true)}>Reprocesar imagen visible</button>
        <a class="boton" href="#/tabla">Ver carpeta en Lista</a>
        ${detalle.archivo_excel && html`<a class="boton" href="/api/resultados/excel" target="_blank">
          Abrir resultado Excel</a>`}
      </div>
      ${modoRecorte === "manual" && html`<div class="roi-ocr-panel">
        <strong>1. Encierra únicamente la zona que debe leer el OCR</strong>
        <p class="subtitulo-seccion">Este recorte sí modifica el análisis. Después pulsa “Reprocesar imagen visible”.</p>
        <${SelectorRegion} item=${imagenSeleccionada} valor=${roiOcr} onChange=${setRoiOcr} />
      </div>`}
      <form class="formulario-correccion" onSubmit=${guardarCampoManual}
        style=${{ marginTop: 14 }}>
        <label><strong>Corregir campo consolidado</strong>
          <select class="campo" value=${campoManual} disabled=${revisionCompletada}
            onChange=${(e) => {
              setCampoManual(e.target.value);
              setValorManual(detalle.campos?.[e.target.value]?.valor || "");
            }}>
            ${Object.keys(detalle.campos || {}).map((clave) => html`
              <option key=${clave} value=${clave}>${clave}</option>`)}
          </select>
        </label>
        <label><strong>Valor confirmado</strong>
          <input class="campo" value=${valorManual} disabled=${revisionCompletada}
            onInput=${(e) => setValorManual(e.target.value)} />
        </label>
        <button class="boton boton-primario" disabled=${revisionCompletada || !campoManual || !valorManual.trim()}>
          Guardar valor y actualizar Excel
        </button>
      </form>
      <label class="motivo-sin-datos"><strong>Motivo opcional para “Imagen sin datos”</strong>
        <input class="campo" value=${motivoSinDatos} maxLength=${512}
          onInput=${(e) => setMotivoSinDatos(e.target.value)}
          placeholder="Ej. fotografía de contexto, sin etiqueta ni código" />
      </label>
      ${(detalle.historial_ejecuciones || []).length > 0 && html`
        <details style=${{ marginTop: 14 }}><summary>Historial de ejecuciones
          (${detalle.historial_ejecuciones.length})</summary>
          ${(detalle.historial_ejecuciones || []).map((item, i) => html`
            <p key=${i} class="subtitulo-seccion">${item.finalizado_en} · ${item.estado} ·
              ${item.imagenes_revisadas} imágenes · ${item.modo_recorte}</p>`)}
        </details>`}
    </div>`}

    ${detalle.perfil === "empresarial" && reglasRelacionadas.length > 0 && html`
      <div class="tarjeta" style=${{ marginTop: 12 }}>
        <h3>Reglas de conocimiento relacionadas</h3>
        ${reglasRelacionadas.map((regla) => html`<div key=${regla.id} class="evidencia-aprendizaje">
          <span class="chip neutro">${regla.estado}</span>
          <strong class="mono">${regla.campo} → ${regla.valor}</strong>
          <small>${regla.cantidad_ids} IDs · ${(Number(regla.confianza || 0) * 100).toFixed(1)}% de consenso</small>
          ${regla.estado === "propuesta" && html`<div class="acciones-revision">
            <button class="boton boton-primario" onClick=${() => cambiarRegla(regla, "confirmada")}>Confirmar regla</button>
            <button class="boton boton-peligro" onClick=${() => cambiarRegla(regla, "rechazada")}>Rechazar regla</button>
          </div>`}
        </div>`)}
      </div>`}

    ${qrsDetalle.length > 0 && html`<div class="tarjeta" style=${{ marginTop: 12 }}>
      <h3>Información QR</h3>
      ${qrsDetalle.map((qr, i) => html`<div key=${`${qr.imagenNombre}-${i}`} class="evidencia-aprendizaje">
        <span class="chip neutro">${qr.formato || qr.interpretacion?.formato || "texto"}</span>
        <strong class="mono">${qr.payload_original || qr.payload || "QR sin payload legible"}</strong>
        <small>${qr.imagenNombre} · ${qr.fase || qr.faseImagen || "—"}${qr.tor || qr.torImagen
          ? ` · ${qr.tor || qr.torImagen}` : ""} ·
          ${Object.keys(qr.campos_extraidos || qr.interpretacion?.campos || {}).length} campos mapeados</small>
      </div>`)}
    </div>`}

    ${detalle.perfil !== "empresarial" && comp.faltantes && comp.faltantes.length > 0 && html`
      <div class="aviso">Tokens de la etiqueta NO encontrados en la referencia:
        ${comp.faltantes.map((t) => html`<code key=${t} class="mono">${t}</code>`)} — revisar.</div>`}

    ${(detalle.alertas || []).map((alerta, i) => html`<div key=${`${alerta.codigo}-${i}`}
      class=${`aviso alerta-${alerta.nivel || "advertencia"}`}>
      <span class="icono-alerta" title=${alerta.mensaje} aria-label=${alerta.mensaje}>⚠</span>
      <strong>${alerta.codigo?.replaceAll("_", " ") || "ADVERTENCIA"}:</strong> ${alerta.mensaje}
      <button type="button" class="boton boton-compacto" onClick=${() => atenderAlerta(alerta)}>
        Marcar atendido</button></div>`)}

    ${controlesImagen}
    ${modoEdicion && !revisionCompletada && imagenSeleccionada ? html`<div class="tarjeta aprendizaje-panel">
      <div>
        <p class="sobrelinea">APRENDIZAJE SUPERVISADO</p>
        <h3 class="titulo-seccion">Corregir una lectura</h3>
        <p class="subtitulo-seccion">La corrección se guarda como verdad confirmada y se prepara
          para el próximo lote; guardar no entrena el OCR. Una nueva versión sólo se activa
          si el lote mejora la evaluación sin introducir regresiones.</p>
      </div>
      <${PanelImagen} key=${imagenSeleccionada?.id} item=${imagenSeleccionada}
        anclaId=${`visor-imagen-${imagenSeleccionada?.id}`}
        titulo=${`Editor · ${imagenSeleccionada?.nombre || "Imagen"}`}
        vacio="Selecciona una imagen" edicionActiva=${true} rotacionActiva=${true}
        onSelectText=${seleccionarUnidad} onBulkDiscard=${descartarTextosMultiples}
        onRotate=${rotarImagen} onMarkNoData=${marcarSinDatos}
        onVerifyImage=${verificarImagen}
        visorRegion=${html`<${SelectorRegion} key=${`${imagenSeleccionada.id}-${revisionEditor}`} item=${imagenSeleccionada} valor=${region} onChange=${setRegion}
          anguloSeleccion=${anguloRegion} onAnguloSeleccion=${setAnguloRegion} poligonoSeleccionado=${poligonoRegion} onPoligonoSeleccion=${setPoligonoRegion} permitirRotarSeleccion=${true}
          textoRegion=${textoRegion} onTextoRegion=${setTextoRegion}
          pruebaId=${detalle.id} onZonaActualizada=${async () => setDetalle(await pedirJSON(`/api/pruebas/${encodeURIComponent(nombre)}`))}
          onSelectText=${(unidad) => seleccionarUnidad(imagenSeleccionada, unidad)}
          correccionAbierta=${mostrarCorreccion} onSeleccionarRegion=${cerrarCorreccionActiva}
          panelCorreccion=${html`<div>
            <button type="button" class="boton" onClick=${cerrarCorreccionActiva}>Cerrar corrección</button>
            ${resultadoCorreccion && html`<p role="status" class=${resultadoCorreccion.ok ? "aviso" : "mensaje-error"}>
              ${resultadoCorreccion.ok ? "Cambio guardado. Puedes continuar revisando." : resultadoCorreccion.mensaje}
            </p>`}
      <div class="acciones-revision">
        <button type="button" class="boton boton-peligro"
          disabled=${guardandoCorreccion || !unidadSeleccionada?.bbox}
          onClick=${() => descartarTexto(unidadSeleccionada)}>Esto no es texto</button>
        <small>Selecciona una detección. Solo se descarta esa zona; puedes deshacerlo.</small>
      </div>
      ${(imagenSeleccionada?.resultado_ocr?.regiones_no_texto || []).map((d) => html`
        <div key=${d.id} class="acciones-revision"><span>Descartado: ${d.texto_ocr}</span>
          <button type="button" class="boton" disabled=${guardandoCorreccion}
            onClick=${() => descartarTexto(d, true)}>Deshacer descarte</button></div>`)}
      ${mostrarCorreccion && unidadesCorregibles.length ? html`
        <form id="formulario-correccion-activa" class="formulario-correccion" onSubmit=${confirmarCorreccion}>
          ${unidadSeleccionada?.bbox && html`<div class="seleccion-exacta-correccion">
            <p class="sobrelinea">BLOQUE EXACTO QUE SE GUARDARÁ</p>
            <${HerramientasRegion}
              key=${`${imagenSeleccionada.id}-${unidadSeleccionada.tipo_unidad}-${unidadSeleccionada.bbox.join(",")}`} item=${imagenSeleccionada}
              bbox=${unidadSeleccionada.bbox} pruebaId=${detalle.id} onTexto=${actualizarTextoCorrecto}
              onEstrategia=${setEstrategiaOcrPendiente} />
          </div>`}
          <label>Imagen
            <select class="campo" value=${imagenSeleccionada?.id || ""}
              onChange=${(e) => cambiarImagen(e.target.value)}>
              ${imagenesVisibles.map((imagen) => html`<option key=${imagen.id} value=${imagen.id}>
                ${imagen.nombre || imagen.ruta.split(/[\\/]/).pop()} · ${(imagen.rol || "imagen").replaceAll("_", " ")}
              </option>`)}
            </select>
          </label>
          <label>Renglón o bloque OCR
            <select class="campo" value=${unidadSeleccionada?.unidad_id || ""} onChange=${(e) => {
              const unidad = unidadesCorregibles.find((u) => u.unidad_id === e.target.value);
              if (unidad) {
                seleccionarUnidad(imagenSeleccionada, unidad);
              }
            }}>
              ${unidadesCorregibles.map((t) => html`<option key=${t.unidad_id} value=${t.unidad_id}>
                ${unidadConfirmada(t, imagenSeleccionada?.correcciones) ? "✓ Corregido / confirmado · " : "○ Sin confirmar · "}${t.tipo_unidad}: ${textoVisible(t).replaceAll("\n", " ↵ ")}</option>`)}
            </select>
          </label>
          <div class="estado-bloque-seleccionado" role="status">
            <span class=${`estado-texto ${unidadConfirmada(unidadSeleccionada, imagenSeleccionada?.correcciones) ? "texto-corregido" : "texto-pendiente"}`}>
              ${unidadConfirmada(unidadSeleccionada, imagenSeleccionada?.correcciones)
                ? "✓ Este bloque ya tiene una corrección o confirmación guardada"
                : "Este bloque aún no tiene una corrección confirmada"}</span>
            ${textoCorrecto !== textoVisible(unidadSeleccionada) && html`<span class="estado-texto texto-pendiente">Borrador modificado · falta aplicar supervisión</span>`}
            ${estrategiaOcrPendiente && html`<span class="estado-texto texto-pendiente">Estrategia OCR lista para aprender al confirmar: ${estrategiaOcrPendiente.orientacion_base}° ${Number(estrategiaOcrPendiente.ajuste_manual || 0) >= 0 ? "+" : ""}${Number(estrategiaOcrPendiente.ajuste_manual || 0).toFixed(1)}° · ${estrategiaOcrPendiente.variante}</span>`}
          </div>
          <label>Texto correcto (con espacios y saltos)
            <textarea class="campo mono campo-texto" value=${textoCorrecto} required maxLength=${4096}
              rows=${Math.min(8, Math.max(2, textoCorrecto.split("\n").length + 1))}
              onChange=${(e) => actualizarTextoCorrecto(e.target.value)} placeholder="Escribe el texto correcto" />
          </label>
          <label>Componente
            <select class="campo" value=${componenteSupervision} onChange=${(e)=>setComponenteSupervision(e.target.value)}><option value="por_identificar">Por identificar</option><option value="bolsa_aire">Bolsa de aire</option><option value="tablero">Tablero</option><option value="otro">Otro componente</option></select>
          </label>
          <label>Campo propuesto
            <select class="campo" value=${campoDestino} onChange=${(e)=>setCampoDestino(e.target.value)}><option value="">Sin asignar</option>${Object.keys(detalle?.campos||{}).map(k=>html`<option value=${k}>${k}</option>`)}</select>
          </label>
          <select class="campo control-compatibilidad" aria-hidden="true" tabIndex="-1" value=${accionSupervision}
            onChange=${(e) => setAccionSupervision(e.target.value)} style=${{display:"none"}}>
            <option value="guardar_sin_entrenar">Compatibilidad</option><option value="aceptar">Aceptar lectura OCR</option>
          </select>
          <div class="acciones-correccion-simple">
            <button type="button" class="boton" disabled=${guardandoCorreccion || !unidadSeleccionada}
              onClick=${(e) => confirmarCorreccion(e, "aceptar")}>${guardandoCorreccion ? "Guardando…" : "Aceptar lectura"}</button>
            <button type="submit" class="boton boton-primario" disabled=${guardandoCorreccion || !textoCorrecto.trim()}>
              ${guardandoCorreccion ? "Guardando…" : "Aplicar corrección"}</button>
            <${AyudaAprendizaje} />
          </div>
        </form>`
        : mostrarCorreccion ? html`<p class="subtitulo-seccion">No hay texto OCR que corregir en esta imagen.</p>` : null}
          </div>`}
          panelTexto=${html`<div>
      <div>
        <p class="sobrelinea">TEXTO OMITIDO</p>
        <h3 class="titulo-seccion">Marcar una zona que el OCR no encontró</h3>
        <p class="subtitulo-seccion">Arrastra sobre la imagen, encierra el texto y escribe exactamente
          lo que dice. Si la etiqueta está inclinada, gira y mueve el recorte azul para excluir texto vecino.
          La región queda asociada a esta carpeta e imagen y se agrega al Excel.</p>
      </div>
      <form class="formulario-region formulario-region-inline" onSubmit=${confirmarRegion}>
        <p>Selecciona una zona en la imagen y escribe aquí su contenido.</p>
        <div class="campos-region">
          <label>Región seleccionada
            <input class="campo mono" value=${region ? `${region.join(", ")}${poligonoRegion ? " · 4 esquinas" : ` · ${anguloRegion > 0 ? "+" : ""}${Number(anguloRegion).toFixed(0)}°`}` : ""} readOnly
              placeholder="Arrastra sobre la imagen" />
          </label>
          <label>Texto real de esa zona
            <textarea class="campo mono campo-texto" value=${textoRegion} required maxLength=${8192}
              rows=${Math.min(10, Math.max(3, textoRegion.split("\n").length + 1))}
              onChange=${(e) => setTextoRegion(e.target.value)}
              placeholder="Escribe todo el texto, respetando espacios y saltos" />
          </label>
          <${AyudaAprendizaje} texto="El texto nuevo confirmado se incorpora automáticamente al aprendizaje visual y puede ayudar a las siguientes imágenes similares." />
          <button class="boton boton-primario"
            disabled=${guardandoRegion || !region || !textoRegion.trim()}>
            ${guardandoRegion ? "Guardando…" : "Guardar región y actualizar Excel"}
          </button>
        </div>
      </form>
      ${resultadoRegion?.ok && html`<div class="aviso">
        Región guardada y agrupada en ${detalle.nombre}.
        ${resultadoRegion.resultado.excel_pendiente
          ? " Actualización del Excel solicitada; consulta su estado arriba."
          : resultadoRegion.resultado.excel_actualizado
          ? " El Excel maestro fue actualizado."
          : ` La anotación está segura, pero el Excel no pudo actualizarse: ${resultadoRegion.resultado.advertencia_excel || "error desconocido"}.`}
      </div>`}
      ${resultadoRegion && !resultadoRegion.ok && html`
        <div class="mensaje-error">${resultadoRegion.mensaje}</div>`}
          </div>`} />`} />
      <div class="texto-detectado"><strong>Texto combinado · OCR corregido + regiones manuales</strong>
        <pre>${[imagenSeleccionada?.resultado_ocr?.texto_completo || "",
          ...(imagenSeleccionada?.anotaciones || []).map((a) => a.texto_correcto)].filter(Boolean).join("\n") || "Sin texto"}</pre>
        <small>Las regiones manuales se añaden al final. Este bloque es de consulta; no se entrena como un recorte único.</small>
      </div>
      ${aprendizaje && html`<p class="subtitulo-seccion estado-modelo">
        Correcciones auditables: <strong>${aprendizaje.memorias_imagen ?? aprendizaje.correcciones}</strong> · Reglas confirmadas activas:
        <span class="mono">${aprendizaje.modelo_activo?.version || "aún sin evidencia suficiente"}</span>
        <br />Recortes visuales entrenables: <strong>${aprendizaje.muestras_entrenables || 0}</strong> ·
        mínimo para ajuste visual: <strong>100 recortes de 15 IDs</strong> (ideal 300+) ·
        EasyOCR visual: <span class="mono">${aprendizaje.modelo_visual_activo?.version || "modelo base"}</span> ·
        Estado automático: ${aprendizaje.entrenamiento_visual?.estado || "inactivo"}
        <button type="button" class="boton boton-compacto" onClick=${entrenarVisual}
          disabled=${aprendizaje.entrenamiento_visual?.estado === "entrenando"}>
          Forzar entrenamiento ahora</button>
        ${aprendizaje.ultimo_modelo_visual?.estado === "candidato_aprobado" && html`
          <button type="button" class="boton boton-compacto" onClick=${activarUltimoVisual}>
            Activar ${aprendizaje.ultimo_modelo_visual.version}</button>`}
        ${aprendizaje.modelo_visual_activo && html`
          <button type="button" class="boton boton-compacto" onClick=${restaurarVisual}>
            Restaurar modelo anterior</button>`}
        ${aprendizaje.ultimo_modelo_visual?.metricas && html`<br />Última evaluación:
          CER ${Number(aprendizaje.ultimo_modelo_visual.metricas.candidata?.cer || 0).toFixed(3)} ·
          WER ${Number(aprendizaje.ultimo_modelo_visual.metricas.candidata?.wer || 0).toFixed(3)} ·
          Exactitud ${(Number(aprendizaje.ultimo_modelo_visual.metricas.candidata?.exactitud || 0) * 100).toFixed(1)}%`}
      </p>`}
      ${resultadoCorreccion?.ok && html`<div class="aviso">
        ${resultadoCorreccion.rotacion
          ? resultadoCorreccion.resultado.mensaje
          : resultadoCorreccion.sinDatos ? resultadoCorreccion.resultado.mensaje
          : resultadoCorreccion.imagenVerificada ? resultadoCorreccion.resultado.mensaje
          : html`<strong>Corrección guardada con su recorte y evidencia.</strong>
            Se aplicará a esta imagen y zona. La estrategia queda disponible inmediatamente para imágenes similares; el ajuste visual de EasyOCR se ejecuta automáticamente cuando es seguro y sólo se activa si mejora validación y prueba.`}
      </div>`}
      ${resultadoCorreccion && !resultadoCorreccion.ok && html`
        <div class="mensaje-error">${resultadoCorreccion.mensaje}</div>`}
      ${resultadoCorreccion?.ok && resultadoCorreccion.resultado?.advertencia_excel && html`
        <div class="mensaje-error" role="alert">${resultadoCorreccion.resultado.advertencia_excel}</div>`}

      <div class="separador-panel"></div>
      ${historialAprendizaje.length > 0 && html`<details class="historial-aprendizaje">
        <summary>Lista de aprendizaje supervisado (${historialAprendizaje.length}) · desplegar / ocultar</summary>
        <p class="subtitulo-seccion">Incluye correcciones OCR y textos omitidos guardados manualmente.</p>
        ${historialAprendizaje.map((item) => html`<div key=${item.id} class="evidencia-aprendizaje">
          <span class="chip neutro">${item.tipo}</span>
          <strong class="mono">${item.correcto}</strong>
          ${item.original && item.original !== item.correcto && html`<small class="mono">Antes: ${item.original}</small>`}
          <small>${item.imagen}${item.bbox ? ` · región ${item.bbox.join(", ")}` : ""}</small>
        </div>`)}
      </details>`}
    </div>` : html`<div class="tarjeta modo-lectura">
      <strong>${revisionCompletada ? "Revisión completada" : "Modo de consulta"}</strong>
      <p>${revisionCompletada
        ? "La edición está bloqueada. Reabre la revisión si necesitas cambiar algo."
        : "Activa “Editar y revisar” para corregir texto o marcar una zona omitida."}</p>
    </div>`}

    <${PanelVideosAirbag} detalle=${detalle} bloqueado=${revisionCompletada}
      onSaved=${async () => setDetalle(await pedirJSON(`/api/pruebas/${encodeURIComponent(nombre)}`))} />

    <div class="selector-imagenes" aria-label="Imágenes del ID">
      ${imagenesVisibles.map((imagen) => {
        const estadoVisual = (imagen.revision_sin_datos || imagen.estado_imagen === "revisada_sin_datos")
          ? "sin-texto" : imagen.estado_imagen === "verificada" ? "verificada" : "pendiente";
        const etiquetaEstado = estadoVisual === "sin-texto" ? "Sin texto · revisada"
          : estadoVisual === "verificada" ? "Imagen verificada" : "Pendiente de verificar";
        return html`<button type="button" key=${imagen.id || imagen.ruta}
        class=${`boton boton-imagen estado-${estadoVisual} ${imagen.id === imagenSeleccionada?.id ? "activa" : ""}`}
        onClick=${() => cambiarImagen(imagen.id, true)} onDoubleClick=${() => cambiarImagen(imagen.id, true)}
        title="Un clic abre esta imagen en el visor y activa su edición">
        <strong>${imagen.nombre || imagen.ruta.split(/[\\/]/).pop()}</strong>
        <small>ID: ${detalle.identificador || detalle.id}</small>
        <span class=${`estado-miniatura estado-${estadoVisual}`}>${etiquetaEstado}</span>
        <small>${imagen.fase || "SIN FASE"}${imagen.tor ? ` · ${imagen.tor}` : ""}</small>
        <small class="ruta-imagen-lista">${imagen.ruta_relativa || imagen.ruta}</small>
        <span class="miniatura-imagen-lista">
          <img src=${imagen.ruta_api_visual || imagen.ruta_api_orientada || imagen.ruta_api}
            alt=${`Vista previa de ${imagen.nombre || "imagen"}`} loading="lazy" />
        </span>
      </button>`})}
    </div>
    <div class="detalle-grid detalle-todas-imagenes">
      ${imagenesDetalle.filter((imagen) => (!modoEdicion || revisionCompletada) && imagen.id === imagenSeleccionada?.id).map((imagen) => {
        const activa = imagen.id === imagenSeleccionada?.id;
        return html`<${PanelImagen} key=${imagen.id || imagen.ruta}
          anclaId=${`visor-imagen-${imagen.id}`}
          titulo=${`${(imagen.rol || "imagen").replaceAll("_", " ")} · ${imagen.nombre || imagen.ruta?.split(/[\\/]/).pop() || "Imagen"}`}
          item=${imagen} vacio="Imagen no disponible." seleccionada=${activa}
          edicionActiva=${activa && modoEdicion && !revisionCompletada}
          onBulkDiscard=${descartarTextosMultiples}
          rotacionActiva=${activa && !revisionCompletada}
          onSelectImage=${(seleccionada) => cambiarImagen(seleccionada.id, true)}
          onSelectText=${seleccionarUnidad} onRotate=${rotarImagen}
          onMarkNoData=${marcarSinDatos} onVerifyImage=${verificarImagen} />`;
      })}
    </div>

    <a class="volver" href="#/tabla">← Volver al listado</a>
  `;
}

/* ----------------------------- App / routing ----------------------------- */

function EstadoProcesoGlobal() {
  const [estado, setEstado] = useState(null);
  const [cerrado, setCerrado] = useState("");
  const [plegado, setPlegado] = useState(false);
  useEffect(() => {
    let cancelado = false, temporizador;
    async function consultar() {
      try {
        const dato = await pedirJSON("/api/pipeline/estado");
        if (!cancelado) setEstado(dato);
      } catch (_) {}
      if (!cancelado) temporizador = setTimeout(consultar, 1800);
    }
    consultar();
    return () => { cancelado = true; clearTimeout(temporizador); };
  }, []);
  const activo = ["procesando", "pausando", "pausado", "cancelando"].includes(estado?.estado);
  const final = ["completado", "error", "cancelado", "detenido_con_avance"].includes(estado?.estado);
  const firmaFinal = `${estado?.estado || ""}|${estado?.finalizado_en || estado?.actualizado_en || ""}`;
  if (!activo && (!final || cerrado === firmaFinal)) return null;
  const porcentaje = Math.min(100, Math.max(0, Number(estado?.porcentaje) || 0));
  return html`<div class=${`notificacion-actividad proceso-${estado?.estado || "inactivo"} ${plegado ? "notificacion-plegada" : ""}`} role="status" aria-live="polite">
    <div class="notificacion-cabecera"><strong>${activo ? t("Procesamiento activo") : t("Estado del procesamiento")}</strong>
      <span class="acciones-notificacion"><button type="button" class="plegar-notificacion" aria-expanded=${!plegado}
        aria-label=${plegado ? t("Mostrar detalles") : t("Ocultar detalles")} onClick=${()=>setPlegado(v=>!v)}>${plegado ? "▴" : "▾"}</button>
      ${final && html`<button type="button" class="cerrar-notificacion" aria-label="Cerrar notificación" onClick=${()=>setCerrado(firmaFinal)}>×</button>`}</span></div>
    ${!plegado && html`<div class="contenido-notificacion"><span>${t(estado?.mensaje || estado?.fase || "Iniciando…")}</span>
      ${activo && html`<div class="notificacion-progreso"><i style=${{width:`${porcentaje}%`}}></i></div>
        <small>${porcentaje.toFixed(1)}% · ${estado?.imagenes_procesadas || 0}/${estado?.imagenes_total || "—"} ${t("imágenes")}</small>`}</div>`}
  </div>`;
}

function EstadoColaExcel() {
  const [cola, setCola] = useState(null);
  const [error, setError] = useState(false);
  const [plegado, setPlegado] = useState(false);
  useEffect(() => {
    let cancelado = false, temporizador;
    async function consultar() {
      try {
        const estado = await pedirJSON("/api/excel/cola");
        if (!cancelado) { setCola(estado); setError(false); }
      } catch (_) { if (!cancelado) setError(true); }
      if (!cancelado) temporizador = setTimeout(consultar, 2000);
    }
    consultar();
    return () => { cancelado = true; clearTimeout(temporizador); };
  }, []);
  if (error) return html`<div class=${`aviso estado-cola-excel notificacion-actividad ${plegado ? "notificacion-plegada" : ""}`} role="status">
    <div class="notificacion-cabecera"><strong>${t("Estado del Excel")}</strong><button type="button" class="plegar-notificacion"
      aria-expanded=${!plegado} onClick=${()=>setPlegado(v=>!v)}>${plegado ? "▴" : "▾"}</button></div>
    ${!plegado && html`<span>${t("No se pudo consultar la cola del Excel. Comprobando conexión…")}</span>`}</div>`;
  if (!cola || (!cola.solicitada && !cola.pendientes)) return null;
  const persistencia = cola.estado_persistencia || ({
    actualizando: "guardando", pendiente: "pendiente", actualizado: "guardado", error: "error"
  }[cola.estado] || "pendiente");
  const etiquetas = {
    guardando: "Guardando cambios en el Excel…",
    pendiente: "Cambios guardados · actualización del Excel pendiente.",
    guardado: "Excel guardado con los cambios confirmados.",
    error: "Error al actualizar el Excel."
  };
  return html`<div class=${`aviso estado-cola-excel notificacion-actividad cola-${persistencia} ${plegado ? "notificacion-plegada" : ""}`} role="status" aria-live="polite">
    <div class="notificacion-cabecera"><strong>${t(etiquetas[persistencia] || etiquetas.pendiente)}</strong>
      <button type="button" class="plegar-notificacion" aria-expanded=${!plegado}
        aria-label=${plegado ? t("Mostrar detalles") : t("Ocultar detalles")} onClick=${()=>setPlegado(v=>!v)}>${plegado ? "▴" : "▾"}</button></div>
    ${!plegado && html`<div class="contenido-notificacion">
      ${cola.pendientes > 0 && html`<span> ${cola.pendientes} ${t("actualizaciones pendientes. Puedes seguir corrigiendo.")}</span>`}
      ${persistencia === "error" && html`<span> ${cola.error || t("No se pudo completar la exportación.")}
        ${cola.error_tipo === "excel_bloqueado" ? t("El archivo Excel parece estar bloqueado por otra aplicación. Ciérralo y la cola volverá a intentarlo.")
          : cola.error_tipo === "permisos" ? t("No hay permisos suficientes para escribir el Excel. La corrección permanece pendiente.")
          : cola.error_tipo === "datos_invalidos" ? t("Se detectó un error de datos al generar el Excel. No se descartó la actualización.")
          : cola.error_tipo === "almacenamiento" ? t("El almacenamiento no está disponible temporalmente. La cola volverá a intentarlo.")
          : t("La actualización permanece en cola y se volverá a intentar.")}
        ${cola.detalle_error ? html`<span class="mono">${cola.detalle_error}</span>` : null}</span>`}
    </div>`}
  </div>`;
}

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
        <span class="logo logo-identidad" aria-label="OCR Versuchsmatrix">
          <img class="logo-grafico" src=${tema === "oscuro" ? "assets/logo_oscuro.png" : "assets/logo_claro.png"}
            alt="OCR" loading="eager" decoding="async" />
          <span class="logo-texto"><strong>Versuchsmatrix</strong><small>Validación y consolidación OCR</small></span>
        </span>
        <nav class="navegacion" aria-label="Vistas">
          <a class="tab" href="#/resumen" aria-current=${actual === "resumen" ? "page" : undefined}><${Icono} tipo="grid" />Resumen</a>
          <a class="tab" href="#/tabla" aria-current=${actual === "tabla" ? "page" : undefined}><${Icono} tipo="lista" />Listado</a>
          <a class="tab" href="#/carga" aria-current=${actual === "carga" ? "page" : undefined}><${Icono} tipo="carpeta" />Procesar carpeta</a>
        </nav>
        <span class="espacio"></span>
        <select class="selector-idioma" value=${window.OCR_I18N?.get?.()||"es"} onChange=${e=>window.OCR_I18N?.set?.(e.target.value)} aria-label="Idioma"><option value="es">ES</option><option value="en">EN</option><option value="de">DE</option></select>
        <button class="btn-tema" onClick=${alternarTema} aria-label="Cambiar tema claro/oscuro"><${Icono} tipo=${tema === "claro" ? "luna" : "sol"} />${tema === "claro" ? "Oscuro" : "Claro"}</button>
      </div>
    </header>
    <div class="centro-notificaciones" aria-label="Notificaciones de actividad">
      <${EstadoProcesoGlobal} />
      <${EstadoColaExcel} />
    </div>
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
