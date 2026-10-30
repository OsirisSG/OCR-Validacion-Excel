/** V15.9.2 · C7: contratos de interfaz del paso previo «proyecto + rangos». */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const raiz = path.resolve(__dirname, "..");
const app = fs.readFileSync(path.join(raiz, "dashboard", "frontend", "app.js"), "utf8");
const css = fs.readFileSync(path.join(raiz, "dashboard", "frontend", "estilos.css"), "utf8");
const i18n = fs.readFileSync(path.join(raiz, "dashboard", "frontend", "i18n.js"), "utf8");

test("C7: diálogo previo con bloque de proyecto obligatorio", () => {
  for (const cadena of [
    "Proyecto al que pertenecen las pruebas",
    "Obligatorio: elige conscientemente el proyecto",
    "— Elige proyecto conscientemente —",
    "Nuevo proyecto…",
    "Sin asignar (el lote quedará pendiente)",
    "Sugerencias pendientes de aceptación",
    "Usar sugerencia",
    "slugProyecto",
    "function proyectoElegido()",
    "dialogo-proyecto-bloque",
    "Configuración previa al procesamiento",
  ]) {
    assert.ok(app.includes(cadena), `Falta en app.js: ${cadena}`);
  }
  // El bloque de rangos V15.9.1 sigue presente (dos bloques independientes).
  assert.ok(app.includes("Configurar rangos de apertura"), "Falta el bloque de rangos");
  assert.ok(app.includes("dialogo-rangos-bloque"), "Falta la sección de rangos");
});

test("C7: no se procesa sin decisión explícita de proyecto", () => {
  const iDialogo = app.indexOf("function DialogoRangosApertura");
  assert.ok(iDialogo > 0);
  const fin = app.indexOf("\nfunction ", iDialogo + 10);
  const dialogo = app.slice(iDialogo, fin > iDialogo ? fin : iDialogo + 16000);
  // Los botones de procesar exigen proyecto elegido.
  assert.ok(dialogo.includes("disabled=${!proyectoActual}"), "Botón no se bloquea sin proyecto");
  assert.ok(dialogo.includes("const proyecto = proyectoElegido();"), "procesarConCampos exige proyecto");
  assert.ok(dialogo.includes("if (!proyecto)"), "Guardia de proyecto faltante");
  // confirmarProcesamiento envía el proyecto en la misma solicitud que el rango.
  const iConfirmar = app.indexOf("const confirmarProcesamiento");
  const confirmar = app.slice(iConfirmar, iConfirmar + 3000);
  assert.ok(confirmar.includes("if (!proyecto)"), "confirmarProcesamiento rechaza sin proyecto");
  assert.ok(confirmar.includes("sin_asignar: !!proyecto.sin_asignar"), "Envía sin_asignar");
  assert.ok(confirmar.includes("nombre_proyecto: proyecto.nombre_proyecto || null"), "Envía nombre");
  assert.ok(confirmar.includes("rango_apertura"), "Sigue enviando rango_apertura");
});

test("C7: proyectos cargados desde la API, nunca del localStorage", () => {
  assert.ok(app.includes('pedirJSON("/api/proyectos")'), "Falta la carga de /api/proyectos");
  // La identidad de la ejecución se muestra en el panel de progreso.
  assert.ok(app.includes("estado?.proyecto_ejecucion"), "Falta proyecto_ejecucion en el panel");
  assert.ok(app.includes("identidad pendiente (carga legacy)"), "Falta el estado pendiente legacy");
  // El slug del diálogo coincide con la regla del backend (sin normalizar acentos).
  const iSlug = app.indexOf("function slugProyecto");
  const slug = app.slice(iSlug, iSlug + 400);
  assert.ok(slug.includes('.replace(/[^a-z0-9._-]+/g, "-")'), "Regla de slug distinta al backend");
  assert.ok(!slug.includes("normalize("), "El slug no debe normalizar acentos (paridad backend)");
});

test("C7: estilos e i18n ES/EN/DE del bloque de proyecto", () => {
  for (const clase of ["dialogo-proyecto-bloque", "dialogo-proyecto-sugerencias",
                       "chip-sugerencia", "dialogo-previo", "identidad-pendiente"]) {
    assert.ok(css.includes(clase), `Falta estilo: ${clase}`);
  }
  for (const clave of [
    "Project the tests belong to", "Unassigned (the batch will stay pending)",
    "Consciously choose a project", "Stable ID", "Suggestions pending acceptance",
    "Projekt, zu dem die Versuche gehören", "Nicht zugeordnet (Charge bleibt ausstehend)",
    "Projekt bewusst wählen", "Stabile ID", "Vorschläge zur Bestätigung ausstehend",
  ]) {
    assert.ok(i18n.includes(clave), `Falta traducción: ${clave}`);
  }
});
