const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const path = require('path');
const source = fs.readFileSync(path.join(__dirname, '../dashboard/frontend/app.js'), 'utf8');
const helper = source.slice(source.indexOf('function propuestaTextoOrientacion('), source.indexOf('const firmaUnidad'));
const handler = source.slice(source.indexOf('  function elegirGiroRecorte('), source.indexOf('  async function guardarGiroRecorte('));
const state = {
  recorteSeleccionado: {marco:'a', candidatos_orientacion:[{grados:90,texto:'10.04.25'}, {grados:180,texto:'A-2\nB.3'}, {grados:270,texto:''}]},
  imagenSeleccionada:{id:'foto'}, unidadSeleccionada:{unidad_id:'u',texto:'original'},
  textoOrientacionRef:{current:null}, textoCorrecto:'original',
  textoVisible:u=>u.texto,
  window:{confirm:()=>false},
};
state.setTextoCorrecto = t => { state.textoCorrecto=t; };
state.setGiroRecorte = g => { state.giro=g; };
state.setMensajeOrientacion = m => { state.mensaje=m; };
vm.createContext(state);
vm.runInContext(helper + handler, state);
state.elegirGiroRecorte(90);
assert.equal(state.textoCorrecto,'10.04.25');
state.elegirGiroRecorte(180);
assert.equal(state.textoCorrecto,'A-2\nB.3');
state.textoCorrecto='manual';
state.elegirGiroRecorte(90);
assert.equal(state.textoCorrecto,'manual');
assert.equal(state.giro,180);
state.window.confirm=()=>true;
state.elegirGiroRecorte(90);
assert.equal(state.textoCorrecto,'10.04.25');
state.elegirGiroRecorte(270);
assert.equal(state.textoCorrecto,'10.04.25');
assert.equal(state.giro,270);
state.elegirGiroRecorte(0);
assert.equal(state.textoCorrecto,'10.04.25');
state.elegirGiroRecorte(450);
assert.equal(state.giro,90);
assert.equal((source.match(/onClick=\$\{\(\) => elegirGiroRecorte\(/g)||[]).length,3);
console.log('OK: copia, saltos y puntos, cambios sucesivos, cancelación, confirmación, lectura vacía/ausente y tres controles conectados.');
