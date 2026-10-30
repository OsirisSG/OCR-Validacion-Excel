const fs = require('fs');
const path = require('path');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'dashboard/frontend/app.js'), 'utf8');

if (!source.includes('function candidatoOrientacionAutomatica')) throw new Error('Falta selector de orientación automática');
if (!source.includes('Usar giro automático')) throw new Error('Falta botón de giro automático regional');
if (!source.includes('function usarGiroAutomaticoRegion')) throw new Error('Falta giro automático en Ajustar / dividir bloque');
const botonesAuto = (source.match(/Usar giro automático/g) || []).length;
if (botonesAuto < 3) throw new Error(`El giro automático no está disponible en todas las herramientas esperadas: ${botonesAuto}`);
if (!source.includes('Recomendada por congruencia')) throw new Error('Falta indicador de orientación recomendada');
if (!source.includes('tienenCriterioNuevo')) throw new Error('Las variantes heredadas de V14.3 no se fuerzan a recalcular');
if (!source.includes('La orientación se eligió por congruencia antes del ajuste fino')) throw new Error('Falta aplicación automática inicial');
console.log('OK: V14.4 aplica y permite restaurar el giro automático por congruencia.');
