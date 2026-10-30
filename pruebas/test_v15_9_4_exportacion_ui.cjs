/** V15.9.4 · N6: contratos de interfaz de la exportación BLOQUEADA.
 *  El operador debe ver «exportación bloqueada» separado del éxito del OCR,
 *  con descarga diferenciada del borrador y textos ES/EN/DE. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const raiz = path.resolve(__dirname, "..");
const app = fs.readFileSync(path.join(raiz, "dashboard", "frontend", "app.js"), "utf8");
const i18n = fs.readFileSync(path.join(raiz, "dashboard", "frontend", "i18n.js"), "utf8");

test("N6: tarjeta exportadora distingue bloqueados de generados", () => {
  for (const cadena of [
    "estado?.bloqueados",
    "exportacion-bloqueada",
    "url_borrador",
    "Exportación BLOQUEADA: identidad del proyecto no verificable.",
    "El OCR terminó y está guardado; el Excel oficial NO se publicó.",
    "Descargar borrador (no publicable)",
  ]) {
    assert.ok(app.includes(cadena), `Falta en app.js: ${cadena}`);
  }
  // Las descargas oficiales siguen su propio bloque (no se mezclan).
  assert.ok(app.includes("estado.generados.map"), "Falta el bloque de descargas oficiales");
});

test("N6: Excel parcial del pipeline expone borradores por separado", () => {
  for (const cadena of [
    "archivos_excel_parcial_borrador",
    "/api/pipeline/borrador-parcial",
    "Descargar borrador (no publicable)",
  ]) {
    assert.ok(app.includes(cadena), `Falta en app.js: ${cadena}`);
  }
});

test("N6: mensajes de exportación bloqueada traducidos ES/EN/DE", () => {
  for (const cadena of [
    "Export BLOCKED: project identity not verifiable.",
    "OCR finished and is saved; the official Excel was NOT published.",
    "Download draft (non-publishable)",
    "Export GESPERRT: Projektidentität nicht verifizierbar.",
    "OCR ist fertig und gespeichert; die offizielle Excel-Datei wurde NICHT veröffentlicht.",
    "Entwurf herunterladen (nicht veröffentlichungsfähig)",
  ]) {
    assert.ok(i18n.includes(cadena), `Falta en i18n.js: ${cadena}`);
  }
});
