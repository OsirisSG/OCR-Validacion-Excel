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
assert(source.includes('copiada automáticamente a Texto correcto como borrador'));
assert(source.includes('nada se guarda hasta pulsar Aplicar supervisión'));
assert(source.includes('variantes-siempre-visibles'));
assert(!source.includes('Guardar orientación regional'));
assert(!source.includes('Comparar lecturas de esta zona'));
console.log('OK: V6 gira, mantiene las cuatro variantes desplegadas y propone Texto correcto sin guardar automáticamente.');
