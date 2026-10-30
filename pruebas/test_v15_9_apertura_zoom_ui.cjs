/** V15.9 · contratos de interfaz: rangos previos a procesar, zoom/lupa y matriz completa. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const raiz = path.resolve(__dirname, "..");
const app = fs.readFileSync(path.join(raiz, "dashboard", "frontend", "app.js"), "utf8");
const css = fs.readFileSync(path.join(raiz, "dashboard", "frontend", "estilos.css"), "utf8");
const i18n = fs.readFileSync(path.join(raiz, "dashboard", "frontend", "i18n.js"), "utf8");

test("diálogo de rangos se abre ANTES de procesar y valida límites", () => {
  for (const cadena of [
    "Configurar rangos de apertura", "Verde hasta (ms)", "Amarillo hasta (ms)",
    "Procesar con estos rangos", "Usar predeterminados (6 / 7 ms)",
    "Guardar para próximas carpetas", "Cancelar",
    "0 ≤ verde < amarillo", "Escribe dos números finitos",
    "Los límites no pueden ser negativos.", "Combinación definitiva",
    "dialogo-rangos-vista-previa", "Vista previa del semáforo",
    "dialogoRangos", "confirmarProcesamiento", "rango_apertura",
    "verde_max: rango.verde_max, amarillo_max: rango.amarillo_max",
    "origen: rango.origen, guardar_preferencia: !!rango.guardar_preferencia",
  ]) {
    assert.ok(app.includes(cadena), `Falta en app.js: ${cadena}`);
  }
  // «Procesar carpeta» abre el diálogo primero; el trabajo empieza sólo al confirmar.
  const iProcesar = app.indexOf("const procesar = async (ev) => {");
  assert.ok(iProcesar >= 0, "Falta VistaCarga.procesar");
  const cuerpo = app.slice(iProcesar, app.indexOf("const confirmarProcesamiento", iProcesar));
  assert.ok(cuerpo.includes("setDialogoRangos(true)"), "procesar() debe abrir el diálogo");
  assert.ok(!cuerpo.includes("/api/pipeline"), "procesar() no debe iniciar el pipeline por sí solo");
  const iConfirmar = app.indexOf("const confirmarProcesamiento", iProcesar);
  const confirmar = app.slice(iConfirmar, iConfirmar + 2600);
  assert.ok(confirmar.includes("/api/pipeline"), "confirmarProcesamiento envía el pipeline");
  assert.ok(confirmar.includes("rango_apertura"), "confirmarProcesamiento envía rango_apertura");
  // El diálogo valida la combinación antes de habilitar «Procesar con estos rangos».
  const iDialogo = app.indexOf("function DialogoRangosApertura");
  assert.ok(iDialogo > 0, "Falta DialogoRangosApertura");
  const dialogo = app.slice(iDialogo, iDialogo + 12000);
  assert.ok(dialogo.includes("validar(vRaw, aRaw)"), "El diálogo valida los límites");
  assert.ok(dialogo.includes("procesarConCampos(\"elegido\")"), "Acción con rangos elegidos");
  assert.ok(dialogo.includes("procesarConCampos(\"predeterminado\")"), "Acción con predeterminados");
  assert.ok(dialogo.includes("guardar_preferencia"), "El diálogo envía guardar_preferencia");
  assert.ok(dialogo.includes("checked=${guardarPreferencia}"), "El checkbox parte sin marcar");
  for (const clase of ["dialogo-rangos", "dialogo-rangos-campos",
                       "dialogo-rangos-guardar", "dialogo-rangos-acciones"]) {
    assert.ok(css.includes(clase), `Falta estilo: ${clase}`);
  }
});

test("zoom del video: suave con rueda, presets, doble clic, fullscreen y lupa F±2", () => {
  for (const cadena of [
    "video-inspector-barra", "video-inspector-marco", "video-inspector-overlays",
    "video-lupa-temporal", "video-lupa-panel", "Ajustar a pantalla", "Lupa F±2",
    "PASOS_ZOOM", "zoomInspector", "zoomPaso", "ruedaZoomInspector",
    "dobleClicZoom", "pantallaCompleta", "setLupaActiva",
    "Lupa temporal F-2…F+2 (tecla L)",
  ]) {
    assert.ok(app.includes(cadena), `Falta en app.js: ${cadena}`);
  }
  // El marco usa la rueda y la imagen el doble clic; el teclado tiene +/−/0/F/L.
  assert.ok(app.includes("onWheel=${ruedaZoomInspector}"), "Falta zoom con rueda");
  assert.ok(app.includes("onDblClick=${dobleClicZoom}"), "Falta zoom con doble clic");
  const iTeclas = app.indexOf("function tecladoVideo(e) {");
  assert.ok(iTeclas >= 0, "Falta tecladoVideo");
  const teclas = app.slice(iTeclas, iTeclas + 1400);
  for (const t of ["zoomPaso(1)", "zoomPaso(-1)", "resetZoomInspector()",
                   "pantallaCompleta()", "setLupaActiva((v) => !v)"]) {
    assert.ok(teclas.includes(t), `Atajo faltante en tecladoVideo: ${t}`);
  }
  // Overlays independientes (ROI / sugerida / nacimiento) y lupa V15.10 de F-2...F+2.
  for (const t of ["overlayRoi", "overlaySugerida", "overlayNacimiento",
                   "F (actual)", "[-2, -1, 0, 1, 2]",
                   "Misma microzona en cinco cuadros nativos"]) {
    assert.ok(app.includes(t), `Falta en app.js: ${t}`);
  }
  for (const clase of ["video-inspector-barra", "video-inspector-marco",
                       "video-lupa-temporal", "video-lupa-panel", "boton-compacto"]) {
    assert.ok(css.includes(clase), `Falta estilo: ${clase}`);
  }
});

test("matriz dinámica: sólo casos reales, sin vacantes artificiales", () => {
  for (const cadena of [
    "Se muestran únicamente casos existentes",
    "matriz-sin-clasificar", "matriz-columna-cupos",
    "Sin clasificar (", "sin_clasificar",
    "motivo_estado", "abrir en Listado",
  ]) {
    assert.ok(app.includes(cadena), `Falta en app.js: ${cadena}`);
  }
  const iMatriz = app.indexOf("function MatrizApertura(");
  const matriz = app.slice(iMatriz, iMatriz + 7000);
  assert.ok(!matriz.includes('item.tipo === "vacante"'),
    "V15.10 no debe renderizar vacantes artificiales");
  assert.ok(!matriz.includes("matriz-celda-vacante"),
    "V15.10 no debe crear celdas vacantes");
});

test("i18n del diálogo de rangos en inglés y alemán", () => {
  for (const cadena of [
    "Configure opening ranges", "Process with these ranges", "Use defaults (6 / 7 ms)",
    "Save for next folders (permanent preference)",
    "Öffnungsbereiche konfigurieren", "Mit diesen Bereichen verarbeiten",
    "Standardwerte verwenden (6 / 7 ms)", "Für nächste Ordner speichern",
  ]) {
    assert.ok(i18n.includes(cadena), `Falta traducción: ${cadena}`);
  }
  // Las claves V15.8 siguen publicadas.
  assert.ok(i18n.includes("Save selected thresholds"));
  assert.ok(i18n.includes("Gewählte Grenzwerte speichern"));
});

/* ---------------- V15.9.1 · contratos de corrección (auditoría r1) ---------------- */
const html = fs.readFileSync(path.join(raiz, "dashboard", "frontend", "index.html"), "utf8");
const backend = fs.readFileSync(path.join(raiz, "dashboard", "backend", "app.py"), "utf8");

test("V15.9.1 (A1): flujo real de reversión de ROI con historial", () => {
  for (const cadena of [
    "revertirRoi", "/api/video/zona-revertir", "historial_roi", "roiAnterior",
    "Revertir ROI anterior", "overlayAnterior", "video-roi-revertir",
  ]) {
    assert.ok(app.includes(cadena), `Falta en app.js: ${cadena}`);
  }
  assert.ok(backend.includes("/api/video/zona-revertir"), "Falta endpoint de reversión");
  assert.ok(backend.includes("revertir_zona_aprendida"), "El backend usa la reversión del aprendizaje");
  // El overlay de la ROI anterior se renderiza para comparar antes de revertir.
  assert.ok(app.includes("video-zona-overlay anterior"), "Overlay de ROI anterior");
  assert.ok(css.includes(".video-zona-overlay.anterior"), "Estilo de ROI anterior");
});

test("V15.9.1 (A2): pan por arrastre y pantalla completa con controles", () => {
  for (const cadena of [
    "iniciarPan", "moverPan", "terminarPan", "puedePan", "panRef",
    "setPointerCapture", "pan-activo",
  ]) {
    assert.ok(app.includes(cadena), `Falta en app.js: ${cadena}`);
  }
  // El pan sólo existe en inspección (zoom>100) y jamás dentro del modo ROI.
  assert.ok(app.includes("zoomInspector > 100 && !modoZona"), "Pan separado del dibujo de ROI");
  // La pantalla completa cubre el visor con su barra de controles.
  assert.ok(app.includes("previewRef.current || visorInspectorRef.current"),
    "Fullscreen sobre el contenedor con controles");
  assert.ok(app.includes("<div ref=${previewRef}"), "El preview tiene ref propia");
  assert.ok(css.includes(".video-inspector-marco.pan-activo"), "Cursor de pan");
  assert.ok(css.includes(".video-airbag-preview:fullscreen"), "Fullscreen con barra visible");
});

test("V15.9.1 (A3): el diálogo de rangos usa el sistema de idiomas", () => {
  const iDialogo = app.indexOf("function DialogoRangosApertura");
  const dialogo = app.slice(iDialogo, app.indexOf("function VistaResumen", iDialogo));
  for (const clave of [
    't("Configurar rangos de apertura")', 't("Verde hasta (ms)")',
    't("Amarillo hasta (ms)")', 't("Procesar con estos rangos")',
    't("Usar predeterminados (6 / 7 ms)")', 't("Cancelar")',
    't("Guardar para próximas carpetas (preferencia permanente)")',
  ]) {
    assert.ok(dialogo.includes(clave), `El diálogo no traduce: ${clave}`);
  }
  // Traducciones nuevas en los tres idiomas.
  for (const cadena of [
    "Traffic-light preview", "Rules", "Cancel", "saved preference",
    "Ampel-Vorschau", "Regeln", "Abbrechen", "gespeicherte Präferenz",
  ]) {
    assert.ok(i18n.includes(cadena), `Falta traducción V15.9.1: ${cadena}`);
  }
});

test("V15.10.1 R12+: caché de estáticos sincronizada a la versión vigente", () => {
  const recursos = ["estilos.css", "i18n.js", "visor_precision.js", "app.js"];
  let version = null;
  for (const recurso of recursos) {
    const patron = recurso.replace(".", "\\.");
    const m = html.match(new RegExp(`${patron}\\?v=([0-9a-z.\\-]+)`));
    assert.ok(m, `index.html no versiona ${recurso}`);
    version = version || m[1];
    assert.equal(m[1], version, `${recurso} no comparte la misma versión de caché`);
  }
  // R15.1 (SUPERSEDE documentado): el pin acepta sub-releases (r15.1) — la
  // caché sigue al release vigente; R12+ sigue siendo el mínimo.
  assert.match(version || "", /^(?:16\.[0-9]+\.[0-9]+|15\.10\.1-r(?:1[2-9]|[2-9][0-9])(?:\.[0-9]+)*)$/, "La caché debe tener identidad V16 o una versión R12+ histórica");
  assert.ok(backend.includes("no-store, no-cache, must-revalidate"), "Falta cabecera no-cache");
});

test("V15.9.1 (A7): predeterminados nunca guardan preferencia global", () => {
  assert.ok(app.includes('origen === "predeterminado" ? false : guardarPreferencia'),
    "El frontend fuerza no guardar con predeterminados");
  assert.ok(backend.includes('rango.origen != "predeterminado"'),
    "El backend ignora guardar_preferencia con predeterminados");
});

test("V15.9.1 (B3): el backend expone causa en sin_clasificar", () => {
  const util = fs.readFileSync(path.join(raiz, "utilidades", "matriz_apertura.py"), "utf8");
  const reporte = fs.readFileSync(path.join(raiz, "reporte_bmg.py"), "utf8");
  assert.ok(util.includes("def causa_sin_clasificar"), "Causa compartida en el motor");
  assert.ok(util.includes('"causa": causa_sin_clasificar(fila)'), "El dashboard expone causa");
  assert.ok(reporte.includes("_poblar_sin_clasificar"), "Bloque único global en el Excel");
  assert.ok(reporte.includes("agrupar_casos"), "El Excel usa la agrupación del dashboard");
});

test("V15.9.1 (B1/B2): consenso sólo publica confirmado", () => {
  const va = fs.readFileSync(path.join(raiz, "video_airbag.py"), "utf8");
  assert.ok(va.includes('estado_consenso == "confirmado" and not c.get("requiere_revision")'),
    "consenso_valido exige confirmado sin revisión");
  assert.ok(va.includes("_causas_revision_graves"), "Causas graves por cámara");
  assert.ok(va.includes("graves_en_consenso"), "La consolidación conserva causas graves");
  assert.ok(backend.includes('"estado": "pendiente_revision"'),
    "El dashboard conserva el tiempo propuesto como pendiente");
});
