const fs = require('fs');
const assert = require('assert');
const path = require('path');
const source = fs.readFileSync(path.join(__dirname, '../dashboard/frontend/app.js'), 'utf8');

assert(source.includes('function propuestaTextoOrientacion(recorte, grados)'));
assert(source.includes('function HerramientasRegion({item, bbox, pruebaId = null, onTexto = null, candidatos = []})'));
assert(source.includes('onClick=${()=>girar(giro-90)}'));
assert(source.includes('onClick=${()=>girar(giro+90)}'));
assert(source.includes('onClick=${()=>girar(0)}'));
assert(source.includes('onClick=${()=>girar(c.grados)}'));
assert(source.includes('onTexto(propuesta.texto)'));
assert(source.includes('copiada a Texto correcto como borrador'));
assert(source.includes('nada se guarda hasta pulsar Aplicar supervisión'));
assert(!source.includes('Guardar orientación regional'));
console.log('OK: girar o elegir una variante propone Texto correcto como borrador y no guarda automáticamente.');
