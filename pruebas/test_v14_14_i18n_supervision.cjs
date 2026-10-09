const fs=require('fs'), path=require('path'), assert=require('assert');
const root=path.resolve(__dirname,'..');
const src=fs.readFileSync(path.join(root,'dashboard/frontend/app.js'),'utf8');
const i18n=fs.readFileSync(path.join(root,'dashboard/frontend/i18n.js'),'utf8');
for (const s of ['Mover recorte','Editar 4 esquinas','Volver a rectángulo','Aprendizaje automático','Aceptar lectura','Aplicar corrección','Pulsa cada bloque que pertenezca a la misma línea. Los seleccionados quedan resaltados; vuelve a pulsar uno para quitarlo.']) {
  assert(i18n.includes(`"${s}"`), `Falta traducción de ${s}`);
}
assert(src.includes('describirCambiosSinGuardar(estado).map(m => t(m))'), 'El desglose de cambios no se traduce en origen');
assert(src.includes('t("¿Descartar estos cambios y continuar?")'), 'El confirm de descarte no respeta idioma');
assert(src.includes('caja-union-seleccionada'), 'La selección múltiple de unir bloques perdió resaltado');
assert(src.includes('setBloquesUnion(seleccion)'), 'Unir bloques no conserva selección múltiple por clic');
console.log('OK: V14.14 traduce controles dinámicos y conserva desglose/unión por clic.');
