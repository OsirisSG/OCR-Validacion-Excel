const fs = require('fs');
const assert = require('assert');

const app = fs.readFileSync('dashboard/frontend/app.js', 'utf8');
assert(app.includes('Estimación automática de apertura'), 'La UI no distingue el tiempo estimado automático');
assert(app.includes('item?.color_fuente') && app.includes('Color:'), 'La UI no expone la fuente del color');
assert(app.includes('tiempo_es_estimado'), 'La UI no conserva la bandera de estimación automática');
assert(app.includes('publicación pendiente'), 'La UI debe aclarar que el color estimado no auto-publica');
console.log('OK: R9 distingue color estimado de publicación confirmada.');
