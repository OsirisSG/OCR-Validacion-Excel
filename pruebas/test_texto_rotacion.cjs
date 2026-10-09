const fs = require('fs');
const assert = require('assert');
const path = require('path');
const source = fs.readFileSync(path.join(__dirname, '../dashboard/frontend/app.js'), 'utf8');

assert(source.includes('function propuestaTextoOrientacion(recorte, grados, usarAjusteFino = true)'));
assert(source.includes('function HerramientasRegion({item, bbox, pruebaId = null, onTexto = null, onEstrategia = null, candidatos = []})'));
assert(source.includes('onClick=${()=>girarBase(giroBase-90)}'));
assert(source.includes('onClick=${()=>girarBase(giroBase+90)}'));
assert(source.includes('onClick=${()=>girarBase(0)}'));
assert(source.includes('onClick=${()=>girarBase(base)}'));
assert(source.includes('onTexto(propuesta.texto)'));
assert(source.includes('copiada automáticamente a Texto correcto como borrador'));
assert(source.includes('variantes-siempre-visibles'));
assert(source.includes('grados_efectivos'));
assert(source.includes('ajuste_fino_grados'));
assert(source.includes('etiquetaAngulo')); // la etiqueta 0° → 7.2° se arma dinámicamente
assert(!source.includes('Guardar orientación regional'));
assert(!source.includes('Comparar lecturas de esta zona'));
console.log('OK: V10 mantiene las cuatro bases, aplica ajuste fino y propone Texto correcto sin guardar automáticamente.');
