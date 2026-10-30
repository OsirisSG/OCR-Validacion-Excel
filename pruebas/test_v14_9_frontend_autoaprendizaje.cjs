const fs = require('fs');
const path = require('path');
const s = fs.readFileSync(path.join(__dirname,'..','dashboard','frontend','app.js'),'utf8');
if (!s.includes('aprendizaje inmediato desde la última imagen')) throw new Error('Falta estado inmediato');
if (!s.includes('Forzar entrenamiento ahora')) throw new Error('El botón debe quedar opcional, no obligatorio');
if (!s.includes('se ejecuta automáticamente cuando es seguro')) throw new Error('Falta explicación auto');
console.log('V14.9 frontend autoaprendizaje OK');
