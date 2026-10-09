const fs=require('fs'), path=require('path'), assert=require('assert');
const root=path.resolve(__dirname,'..');
const app=fs.readFileSync(path.join(root,'dashboard/frontend/app.js'),'utf8');
const i18n=fs.readFileSync(path.join(root,'dashboard/frontend/i18n.js'),'utf8');
const index=fs.readFileSync(path.join(root,'dashboard/frontend/index.html'),'utf8');

assert(app.includes('placeholder=${t("Buscar por identificador o nomenclatura…")}'), 'El buscador no usa i18n explícito');
assert(app.includes('${t("con texto")}'), 'con texto no usa i18n explícito');
assert(app.includes('${t("descartadas")}'), 'descartadas no usa i18n explícito');
assert(app.includes('${t("campos")}'), 'campos no usa i18n explícito');
assert(app.includes('${t("faltantes")}'), 'faltantes no usa i18n explícito');
assert(app.includes('${t("conflictos")}'), 'conflictos no usa i18n explícito');
assert(app.includes('${t(f.estado_deteccion || "—")}'), 'estado_deteccion no usa i18n explícito');
assert(app.includes('${t(f.estado || "detectada")}'), 'estado no usa i18n explícito');
for (const k of [
  '"Buscar por identificador o nomenclatura…":"Search by identifier or nomenclature…"',
  '"Buscar por identificador o nomenclatura…":"Nach Kennung oder Nomenklatur suchen…"',
  '"con texto":"with text"','"con texto":"mit Text"',
  '"descartadas":"discarded"','"descartadas":"verworfen"',
  '"campos":"fields"','"campos":"Felder"',
  '"estructura_valida":"valid structure"','"estructura_valida":"gültige Struktur"',
  '"con_conflictos":"with conflicts"','"con_conflictos":"mit Konflikten"'
]) assert(i18n.includes(k), `Falta traducción: ${k}`);
const recursos=Array.from(index.matchAll(/(?:src|href)="([^"]+)"/g), m=>m[1]);
const versiones=['app.js','i18n.js','estilos.css'].map(nombre=>{
  const recurso=recursos.find(url=>url.split('?')[0]===nombre);
  assert(recurso, `Falta recurso ${nombre}`);
  const version=new URL(recurso,'http://localhost/').searchParams.get('v');
  assert(version, `Falta versión de caché en ${nombre}`);
  return version;
});
assert.strictEqual(new Set(versiones).size,1,'JS, i18n y CSS deben compartir versión');
console.log('V14.15.1: i18n restante del listado OK');
