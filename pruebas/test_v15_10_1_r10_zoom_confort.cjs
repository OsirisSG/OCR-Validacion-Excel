const assert = require('node:assert/strict');
const visor = require('../dashboard/frontend/visor_precision.js');

assert.equal(typeof visor.zoomSuavePorRueda, 'function');
assert.equal(typeof visor.zoomSuavePorPaso, 'function');

// La rueda debe cambiar el zoom de forma progresiva, no saltar 100->200.
const z1 = visor.zoomSuavePorRueda(100, -100, 100, 1000, 1.12);
assert.ok(z1 > 100 && z1 < 150, `zoom rueda inesperado: ${z1}`);
const z2 = visor.zoomSuavePorRueda(z1, -100, 100, 1000, 1.12);
assert.ok(z2 > z1 && z2 < 170);

// Límites duros.
assert.equal(visor.zoomSuavePorRueda(995, -1000, 100, 1000, 1.12), 1000);
assert.equal(visor.zoomSuavePorRueda(100, 1000, 100, 1000, 1.12), 100);
assert.equal(visor.zoomSuavePorPaso(100, 1, 100, 1000, 1.25), 125);
assert.equal(visor.zoomSuavePorPaso(125, -1, 100, 1000, 1.25), 100);

// Coordenadas fuente/viewport siguen siendo inversas con zoom y rotación:
// el confort visual no puede desplazar ROI/microzona.
const tr = {sourceWidth: 1920, sourceHeight: 1080, scale: 0.5, rotationDeg: 17, centerX: 600, centerY: 400};
const origen = {x: 731.25, y: 412.5};
const vp = visor.sourceToViewportPoint(origen, tr);
const vuelta = visor.viewportToSourcePoint(vp, tr, false);
assert.ok(Math.abs(vuelta.x - origen.x) < 1e-6);
assert.ok(Math.abs(vuelta.y - origen.y) < 1e-6);

console.log('OK: zoom suave, limites y geometria estable.');
