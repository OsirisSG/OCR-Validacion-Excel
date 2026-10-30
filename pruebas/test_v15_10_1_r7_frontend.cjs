const fs = require('fs');
const path = require('path');
const root = path.resolve(__dirname, '..');
const app = fs.readFileSync(path.join(root, 'dashboard/frontend/app.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'dashboard/frontend/index.html'), 'utf8');
function assert(cond, msg) { if (!cond) throw new Error(msg); }

assert(!app.includes('.map((t) => html`\n            <li key=${t.unidad_id}'),
  'Regresión: el token OCR vuelve a sombrear la función global t()');
assert(app.includes('.map((unidad) => html`\n            <li key=${unidad.unidad_id}'),
  'No se encontró el callback OCR corregido');
assert(app.includes('${t(etiquetaSupervisionUnidad(unidad, item.correcciones))}'),
  'La traducción de etiqueta OCR no usa la función t() global');
assert(app.includes('resumen.semaforo_apertura || resumen.semaforo'),
  'El resumen no está usando el semáforo de apertura junto a la matriz');
assert(app.includes('resumen.distribucion_apertura_por_lote || resumen.distribucion_por_lote'),
  'Las barras por lote no usan el semáforo de apertura');
assert(/app\.js\?v=(?:16\.[0-9]+\.[0-9]+|15\.10\.1-r(?:[7-9]|1[0-9]))/.test(html), 'index.html no fuerza caché compatible R7+');
console.log('OK: frontend R7+ sin shadow de t() y con semáforo de apertura coherente.');
