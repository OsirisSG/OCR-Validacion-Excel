/** Regresión V15.10.1: «Aceptar lectura» sigue provisional en interfaz y reanudación. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const raiz = path.resolve(__dirname, "..");
const app = fs.readFileSync(path.join(raiz, "dashboard", "frontend", "app.js"), "utf8");
const css = fs.readFileSync(path.join(raiz, "dashboard", "frontend", "estilos.css"), "utf8");
const i18n = fs.readFileSync(path.join(raiz, "dashboard", "frontend", "i18n.js"), "utf8");

const inicio = app.indexOf("function unidadAceptadaProvisional");
const fin = app.indexOf("\n/* ----------------------------- Componentes", inicio);
assert.ok(inicio >= 0 && fin > inicio, "No se encontraron las funciones de estado de supervisión");
const bloque = app.slice(inicio, fin);
const crearHelpers = new Function("textoUnidad", "textoVisible", `${bloque}\nreturn {
  unidadAceptadaProvisional, unidadConfirmada, estadoSupervisionUnidad,
  etiquetaSupervisionUnidad,
};`);
const h = crearHelpers(u => u?.texto_original || u?.texto || "", u => u?.texto || u?.texto_original || "");

test("La aceptación provisional no se presenta como corrección humana", () => {
  const bbox = [2, 3, 20, 10];
  const unidad = { texto: "A", texto_original: "A", bbox, aceptado_provisional: true,
    estado_supervision: "aceptado_provisional" };
  assert.equal(h.unidadAceptadaProvisional(unidad), true);
  assert.equal(h.unidadConfirmada(unidad), false);
  assert.equal(h.estadoSupervisionUnidad(unidad), "aceptado_provisional");
  assert.equal(h.etiquetaSupervisionUnidad(unidad), "Aceptado provisional · pendiente de verificar");
});

test("Una corrección guardada prevalece y conserva el estado humano", () => {
  const unidad = { texto: "B", texto_original: "A", bbox: [2, 3, 20, 10],
    confirmado_manualmente: true, estado_supervision: "corregido_humano" };
  assert.equal(h.estadoSupervisionUnidad(unidad), "corregido_humano");
  assert.equal(h.unidadConfirmada(unidad), true);
});

test("La reanudación vuelve a mostrar el estado provisional y no usa un check verde", () => {
  const unidad = { texto: "A", texto_original: "A", bbox: null };
  const aceptacion = [{ texto_ocr: "A", texto_correcto: "A", bbox: null,
    fuente: "aceptar_ocr", estado_supervision: "aceptado_provisional" }];
  assert.equal(h.estadoSupervisionUnidad(unidad, aceptacion), "aceptado_provisional");
  assert.equal(h.unidadConfirmada(unidad, aceptacion), false);
  assert.ok(app.includes('◷ ${t("Aceptado provisional · pendiente de verificar")}'));
  assert.ok(app.includes("Lectura aceptada provisionalmente; no es una corrección humana verificada"));
  assert.ok(app.includes("texto_ocr: textoVisible(unidadSeleccionada)"));
});

test("Los estados provisionales tienen apariencia y textos ES/EN/DE diferenciados", () => {
  assert.ok(css.includes("caja-provisional"));
  assert.ok(css.includes("token-provisional"));
  assert.ok(css.includes("texto-provisional"));
  for (const traduccion of [
    "Provisionally accepted · pending verification",
    "Vorläufig angenommen · Prüfung ausstehend",
    "Reading accepted provisionally; it is not a verified human correction",
    "Lesung vorläufig angenommen; keine verifizierte menschliche Korrektur",
  ]) assert.ok(i18n.includes(traduccion), `Falta traducción: ${traduccion}`);
});

test("La matriz expone decisión, razón, fuente y tiempo crudo en su tooltip accesible", () => {
  assert.ok(app.includes("function MatrizApertura"));
  assert.ok(app.includes("const trazaCelda = (item)"));
  assert.ok(app.includes("item?.motivo_rechazo"));
  assert.ok(app.includes("item?.raw_time_ms"));
  assert.ok(app.includes("item?.fuente_evidencia"));
  assert.ok(app.includes("aria-label=${tituloCelda(item)}"));
  assert.ok(app.includes("no_positivo: \"tiempo final debe ser > 0\""));
});

test("El panel conserva raw/rechazo y bloquea eventos censurados como tiempos finales", () => {
  assert.ok(app.includes("eventoCensuradoVideo"));
  assert.ok(app.includes("Evento censurado al inicio"));
  assert.ok(app.toLowerCase().includes("evento censurado al inicio del clip"));
  assert.ok(app.includes("Auditoría temporal (no es propuesta)"));
  assert.ok(app.includes("videoCensurado"));
  assert.ok(app.includes("CENSURADO"));
  assert.ok(app.includes("async function guardarZonaYApertura()"));
  assert.ok(app.includes("||!zonaTemporal||eventoCensuradoVideo"));
});
