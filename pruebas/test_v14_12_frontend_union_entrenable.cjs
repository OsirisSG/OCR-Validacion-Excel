const fs = require('fs');
const path = require('path');
const app = fs.readFileSync(path.join(__dirname, '..', 'dashboard', 'frontend', 'app.js'), 'utf8');
if (!app.includes('Usar unión para entrenar OCR')) throw new Error('Falta control compacto de entrenamiento en unión');
if (!app.includes('proponer_entrenamiento: deshacer ? false : entrenarUnion')) throw new Error('La unión no envía la decisión entrenable');
if (!app.includes('useState(true)')) throw new Error('La unión no queda entrenable por defecto');
if (!app.includes('Una línea: entrena la zona unida. Varias líneas: intenta separarlas por línea.')) throw new Error('Falta ayuda compacta de una/múltiples líneas');
if (app.includes('<small>Activado por defecto. Si dejas una línea por cada bloque original')) throw new Error('Sigue visible la explicación redundante de V14.12');
console.log('OK: uniones visuales entrenables por defecto con control explícito.');
