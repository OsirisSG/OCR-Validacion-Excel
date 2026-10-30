// Verificación de estructura y eventos React/htm; no sustituye una prueba visual.
// V15.10.1: el harness carga visor_precision.js antes de app.js, igual que index.html.
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const assert = require('assert');
const base = path.join(__dirname, '../dashboard/frontend');
let states = [], cursor = 0;
const ctx = vm.createContext({
  window: {confirm:()=>true},
  React: {
    createElement: (type, props, ...children) => ({type, props: props || {}, children}),
    useState: initial => {
      const i = cursor++;
      if (!(i in states)) states[i] = typeof initial === 'function' ? initial() : initial;
      return [states[i], v => { states[i] = typeof v === 'function' ? v(states[i]) : v; }];
    },
    useEffect: () => {}, useLayoutEffect: () => {}, useRef: value => ({current: value}),
    useMemo: f => f(), useCallback: f => f,
  },
  ReactDOM: {createRoot: () => ({render: () => {}})},
  document: {getElementById: () => ({})},
  console,
});
vm.runInContext(fs.readFileSync(path.join(base, 'vendor/htm.umd.js'), 'utf8'), ctx);
vm.runInContext(fs.readFileSync(path.join(base, 'visor_precision.js'), 'utf8'), ctx);
// En navegador globalThis === window; en vm.Context no necesariamente. Igualamos el harness.
if (!ctx.window.VMatrixVisorPrecision && ctx.VMatrixVisorPrecision) {
  ctx.window.VMatrixVisorPrecision = ctx.VMatrixVisorPrecision;
}
assert(ctx.window.VMatrixVisorPrecision, 'visor_precision.js no expuso VMatrixVisorPrecision');
vm.runInContext(fs.readFileSync(path.join(base, 'app.js'), 'utf8'), ctx);
function all(node) {
  if (!node || typeof node !== 'object') return [];
  if (Array.isArray(node)) return node.flatMap(all);
  return [node, ...(node.children || []).flatMap(all)];
}
const props = {item: {id:'foto', resultado_ocr:{dimensiones:[500,300], lineas_texto:[
  {texto:'10.04', bbox:[10,10,40,20]}, {texto:'.25', bbox:[55,10,20,20]}]}},
  valor:null, panelTexto:'formulario', pruebaId:'caso', onChange: b => { props.valor = b; }};
function render() { cursor = 0; return ctx.SelectorRegion(props); }
let tree = render();
const boton = (tree, text) => all(tree).find(n => n.type === 'button' && n.children.includes(text));
boton(tree, 'Unir bloques').props.onClick();
tree = render();
let cajas = all(tree).filter(n => String(n.props.class || '').includes('caja-ocr'));
cajas[0].props.onClick();
tree = render();
cajas = all(tree).filter(n => String(n.props.class || '').includes('caja-ocr'));
cajas[1].props.onClick();
assert.strictEqual(JSON.stringify(props.valor), '[10,10,65,20]');
tree = render();
assert.strictEqual(all(tree).filter(n => n.props.class === 'tirador-zona').length, 4);
assert.strictEqual(all(tree).filter(n => typeof n.type === 'function' && n.type.name === 'EditorUnionZona').length, 1);
boton(tree, 'Mover imagen').props.onClick();
tree = render();
assert.strictEqual(all(tree).filter(n => typeof n.type === 'function' && n.type.name === 'EditorUnionZona').length, 1);
console.log('OK: selección múltiple, cuatro esquinas y panel condicional debajo del visor.');
boton(tree, 'Editar bloque').props.onClick();
tree = render();
all(tree).filter(n => String(n.props.class || '').includes('caja-ocr'))[0].props.onClick();
tree = render();
const editor = all(tree).find(n => typeof n.type === 'function' && n.type.name === 'EditorDimensionBloque');
assert(editor);
assert.equal(JSON.stringify(editor.props.origen), '[10,10,40,20]');
assert.equal(editor.props.regiones[0].confirmado, false);
assert.equal(editor.props.regiones[0].texto, '10.04');
assert.equal(all(tree).filter(n => typeof n.type === 'function' && n.type.name === 'EditorUnionZona').length, 0);
states = []; cursor = 0;
let nuevas;
const panel = ctx.EditorDimensionBloque({...editor.props, setRegiones: r=>{nuevas=r;}, activar:()=>{}});
boton(panel, 'Dividir en dos regiones').props.onClick();
assert.equal(nuevas.length, 2);
assert.equal(JSON.stringify(nuevas[0].bbox), '[10,10,20,20]');
assert.equal(JSON.stringify(nuevas[1].bbox), '[30,10,20,20]');
assert(nuevas.every(r=>!r.confirmado && r.texto===''));
assert.equal(boton(panel, 'Guardar y reemplazar bloque original').props.disabled, true);
console.log('OK: ajuste conserva el texto original, división en dos borradores y bloqueo de guardado sin confirmación.');
states=[];cursor=0;
let copiado='';
const herramientasProps={item:props.item,bbox:[10,10,40,20],texto:'',
  candidatos:[{grados:90,grados_efectivos:97,ajuste_fino_grados:7,texto:'10.04.25',confianza:0.9,texto_base:'10.04.2S',confianza_base:0.7}],onTexto:t=>{copiado=t;}};
let herramientas=ctx.HerramientasRegion(herramientasProps);
boton(herramientas,'↷ 90°').props.onClick();
assert.equal(copiado,'10.04.25');
cursor=0;herramientas=ctx.HerramientasRegion(herramientasProps);
assert.equal(all(herramientas).find(n=>typeof n.type==='function' && n.type.name==='VistaRecorteZona').props.grados,97);
boton(herramientas,'No tomar ajuste').props.onClick();
assert.equal(copiado,'10.04.2S');
boton(herramientas,'Restablecer giro').props.onClick();
assert.equal(copiado,'10.04.2S','Un giro sin candidato no borra el texto');
states=[];cursor=0;
const recorte=ctx.VistaRecorteZona({...herramientasProps,grados:90});
assert.equal(all(recorte).find(n=>n.type==='svg').props.viewBox,'0 0 20 40');
console.log('OK: recorte visible, giro, dimensiones rotadas y copia de lectura conservando puntos.');
