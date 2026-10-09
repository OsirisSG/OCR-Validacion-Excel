const fs=require('fs'), path=require('path'), assert=require('assert');
const root=path.resolve(__dirname,'..');
const app=fs.readFileSync(path.join(root,'dashboard/frontend/app.js'),'utf8');
const i18n=fs.readFileSync(path.join(root,'dashboard/frontend/i18n.js'),'utf8');
const index=fs.readFileSync(path.join(root,'dashboard/frontend/index.html'),'utf8');

assert(app.includes('}}>Editar bloque</button>'), 'Falta botón unificado Editar bloque');
assert(app.includes('<h3>Editar bloque</h3>'), 'El panel de edición no usa el nombre unificado');
assert(!app.includes('}}>Ajustar / dividir bloque</button>'), 'Sigue visible el botón Ajustar/dividir bloque');
assert(!app.includes('}}>Mover bloque</button>'), 'Sigue visible el botón Mover bloque separado');
assert(app.includes('podrás moverlo, ajustar límites, usar 4 esquinas, girarlo o dividirlo'), 'Falta ayuda del editor unificado');
assert(i18n.includes('"Editar bloque":"Edit block"'), 'Falta traducción EN de Editar bloque');
assert(i18n.includes('"Editar bloque":"Block bearbeiten"'), 'Falta traducción DE de Editar bloque');
for (const k of ['"Completar":"Complete"','"Quitar":"Remove"','"Completar":"Abschließen"','"Quitar":"Entfernen"',
                 '"Verde":"Green"','"Verde":"Grün"','"discrepancia":"discrepancy"','"discrepancia":"Abweichung"']) {
  assert(i18n.includes(k), `Falta cobertura i18n: ${k}`);
}
assert(app.includes('${t("Abrir")} ${idioma.toUpperCase()}'), 'El botón dinámico Abrir idioma no usa i18n explícito');
const recursos=Array.from(index.matchAll(/(?:src|href)="([^"]+)"/g), m=>m[1]);
const versiones=['app.js','i18n.js','estilos.css'].map(nombre=>{
  const recurso=recursos.find(url=>url.split('?')[0]===nombre);
  assert(recurso, `Falta recurso ${nombre}`);
  const version=new URL(recurso,'http://localhost/').searchParams.get('v');
  assert(version, `Falta versión de caché en ${nombre}`);
  return version;
});
assert.strictEqual(new Set(versiones).size,1,'JS, i18n y CSS deben compartir versión');
console.log('V14.15: editor de bloque unificado e i18n dinámico OK');
