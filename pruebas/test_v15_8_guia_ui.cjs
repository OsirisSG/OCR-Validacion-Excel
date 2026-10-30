const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const raiz = path.resolve(__dirname, '..');
const app = fs.readFileSync(path.join(raiz, 'dashboard/frontend/app.js'), 'utf8');
const i18n = fs.readFileSync(path.join(raiz, 'dashboard/frontend/i18n.js'), 'utf8');
for (const texto of ['EditorCriteriosApertura','/api/config/criterios-apertura','Verde hasta (ms)',
  'Amarillo hasta (ms)','Guardar límites elegidos','Confirmar máximo visible aquí']) assert.ok(app.includes(texto), texto);
assert.ok(app.includes('v >= a'));
assert.ok(app.includes('pedirJSON("/api/resumen")'));
for (const texto of ['Set opening-time thresholds','Grenzwerte der Öffnungszeit festlegen',
  'Save selected thresholds','Gewählte Grenzwerte speichern']) assert.ok(i18n.includes(texto), texto);
console.log('V15.8: límites explícitos y máximo visible presentes, con traducciones EN/DE.');
