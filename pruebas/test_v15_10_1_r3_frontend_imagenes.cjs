const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const app = fs.readFileSync(path.join(root, 'dashboard/frontend/app.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'dashboard/frontend/index.html'), 'utf8');

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

assert(app.includes('function usarFallbackImagen('), 'Falta helper de fallback de imágenes');
assert((app.match(/onError=\$\{\(e\) => usarFallbackImagen/g) || []).length >= 4,
  'Los visores principales no están cableados al fallback de imagen');
assert(app.includes('raiz del lote') || app.includes('raíz del lote'),
  'El error visual no explica la posible causa de ruta');
const visor = html.search(/visor_precision\.js\?v=(?:16\.[0-9]+\.[0-9]+|15\.10\.1-r(?:[3-9]|1[0-9]))/);
const appjs = html.search(/app\.js\?v=(?:16\.[0-9]+\.[0-9]+|15\.10\.1-r(?:[3-9]|1[0-9]))/);
assert(visor >= 0 && appjs >= 0 && visor < appjs,
  'index.html no carga visor_precision.js antes de app.js con caché R3–R19');
console.log('OK: fallback de imágenes y caché R3–R19 cableados.');
