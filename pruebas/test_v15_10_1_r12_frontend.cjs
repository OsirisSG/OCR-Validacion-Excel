const fs = require('fs');
const src = fs.readFileSync('dashboard/frontend/app.js','utf8');
if (!src.includes('pendiente de procesamiento')) throw new Error('Falta leyenda azul pendiente');
if (!src.includes('matriz.tiene_pendientes')) throw new Error('La matriz no expone/usa pendientes');
if (!src.includes('Puertas:')) throw new Error('Falta trazabilidad de puertas de decisión');
if (!src.includes('Bloqueos:')) throw new Error('Falta explicación de bloqueos');
if (src.includes('Object.entries(matriz.regla || {})')) throw new Error('La leyenda vuelve a pintar origen_criterio como color');
console.log('OK R12 frontend: pendiente azul + decisión explicable');
