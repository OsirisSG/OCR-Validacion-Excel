/** V15.9.5 · N9: tres estados distintos en la interfaz de exportación.
 *  Confirmado/publicable, sin asignar/pendiente y bloqueado por
 *  contradicción deben verse diferenciados, con textos ES/EN/DE. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const raiz = path.resolve(__dirname, "..");
const app = fs.readFileSync(path.join(raiz, "dashboard", "frontend", "app.js"), "utf8");
const i18n = fs.readFileSync(path.join(raiz, "dashboard", "frontend", "i18n.js"), "utf8");

test("N9: la tarjeta exportadora muestra el estado PENDIENTE diferenciado", () => {
  for (const cadena of [
    "pendiente_publicada",
    "pendiente_sin_asignar",
    "exportacion-pendiente",
    "Excel publicado como PENDIENTE: proyecto «Sin asignar» por decisión del usuario.",
    "El OCR terminó; este reporte NO tiene identidad de proyecto verificada.",
  ]) {
    assert.ok(app.includes(cadena), `Falta en app.js: ${cadena}`);
  }
  // El aviso de bloqueado (N6) sigue existiendo y es independiente.
  assert.ok(app.includes("exportacion-bloqueada"), "Falta el aviso de exportación bloqueada");
});

test("N9: textos del estado pendiente traducidos ES/EN/DE", () => {
  for (const cadena of [
    "Excel published as PENDING: project «Unassigned» by user decision.",
    "OCR finished; this report has NO verified project identity.",
    "Excel als AUSSTEHEND veröffentlicht: Projekt «Nicht zugeordnet» per Benutzerentscheidung.",
    "OCR abgeschlossen; dieser Bericht hat KEINE verifizierte Projektidentität.",
  ]) {
    assert.ok(i18n.includes(cadena), `Falta en i18n.js: ${cadena}`);
  }
});
