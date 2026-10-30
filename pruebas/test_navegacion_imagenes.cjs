const fs=require('fs'), vm=require('vm'), path=require('path'), assert=require('assert');
const base=path.join(__dirname,'../dashboard/frontend');
let slots=[], cursor=0, efectos=[];
const api={id:'caso',nombre:'Caso',perfil:'empresarial',comparacion:{resultado:'parcial'},revision:{estado:'parcial'},
  imagenes:[
    {id:'a',ruta:'a.jpg',nombre:'A',estado_imagen:'pendiente',resultado_ocr:{dimensiones:[100,100],lineas_texto:[{texto:'A',bbox:[0,0,10,10]}]},correcciones:[{id:1,texto_ocr:'a',texto_correcto:'A'}]},
    {id:'b',ruta:'b.jpg',nombre:'B',estado_imagen:'verificada',resultado_ocr:{}},
    {id:'c',ruta:'c.jpg',nombre:'C',estado_imagen:'pendiente',resultado_ocr:{lineas_texto:[{texto:'C',bbox:[0,0,10,10]}]}},
  ]};
let detail=api, confirmar=true, consultaOcupada=false;
let ultimaCorreccion=null;
const ctx=vm.createContext({
 React:{
  createElement:(type,props,...children)=>({type,props:props||{},children}),
  useState:init=>{const i=cursor++;if(!(i in slots))slots[i]=typeof init==='function'?init():init;return[slots[i],v=>{slots[i]=typeof v==='function'?v(slots[i]):v;}];},
  useRef:init=>{const i=cursor++;return slots[i]||(slots[i]={current:init});},
  useEffect:(f,deps)=>{const i=cursor++,old=slots[i];if(!old||deps.some((v,j)=>v!==old[j])){slots[i]=deps;efectos.push(f);}},
  useMemo:f=>f(),useCallback:f=>f},
 ReactDOM:{createRoot:()=>({render:()=>{}})}, document:{getElementById:()=>null,querySelector:()=>null},
 window:{confirm:()=>confirmar,setTimeout:()=>{},dispatchEvent:e=>{e.detail.ocupado=consultaOcupada;}},
 CustomEvent:function(type,options){this.type=type;this.detail=options.detail;},
 requestAnimationFrame:()=>{}, location:{hash:''},
});
vm.runInContext(fs.readFileSync(path.join(base,'vendor/htm.umd.js'),'utf8'),ctx);
vm.runInContext(fs.readFileSync(path.join(base,'app.js'),'utf8'),ctx);
ctx.useApi=url=>url.startsWith('/api/pruebas/')?[detail,d=>{detail=d;},null]:[{},()=>{},null];
ctx.enviarJSON=async(url,data)=>{
 if(url==='/api/imagenes/verificar') detail={...detail,imagenes:detail.imagenes.map(i=>i.id===data.imagen_id?{...i,estado_imagen:'verificada'}:i)};
 if(url==='/api/aprendizaje/zonas') return {candidatos_orientacion:[{grados:90,texto:'A.90',confianza:0.95}]};
 if(url==='/api/aprendizaje/correcciones') {
  ultimaCorreccion=data;
  detail={...detail,imagenes:detail.imagenes.map(i=>i.id!==data.imagen_id?i:{...i,resultado_ocr:{...i.resultado_ocr,
   lineas_texto:i.resultado_ocr.lineas_texto.map(u=>JSON.stringify(u.bbox)!==JSON.stringify(data.bbox)?u:
    {...u,texto_original:u.texto_original||u.texto,texto:data.texto_correcto,confirmado_manualmente:true})}})};
 }
 return {mensaje:'ok'};
};
ctx.pedirJSON=async()=>detail;
function all(n){return !n||typeof n!=='object'?[]:Array.isArray(n)?n.flatMap(all):[n,...n.children.flatMap(all),...Object.values(n.props).filter(v=>v&&v.type&&Array.isArray(v.children)).flatMap(all)];}
function render(){cursor=0;const tree=ctx.VistaDetalle({nombre:'Caso'});const pending=efectos;efectos=[];pending.forEach(f=>f());return tree;}
const btn=(tree,label)=>all(tree).find(n=>n.type==='button'&&n.children.includes(label));
const editor=tree=>all(tree).find(n=>typeof n.type==='function'&&n.type.name==='PanelImagen');
(async()=>{
 render();let t=render();
 btn(t,'Ocultar imágenes verificadas').props.onClick();t=render();
 assert.equal(all(t).filter(n=>String(n.props.class).includes('boton-imagen')).length,2);
 assert(btn(t,'← Anterior').props.disabled);
 btn(t,'Siguiente →').props.onClick();t=render();assert.equal(editor(t).props.item.id,'c');
 assert(btn(t,'Siguiente →').props.disabled);
 btn(t,'← Anterior').props.onClick();t=render();assert.equal(editor(t).props.item.id,'a');
 const hist=all(t).find(n=>n.type==='details'&&n.props.class==='historial-aprendizaje');
 assert(hist && !hist.props.open);
 // Entra a la corrección real y cambia su borrador.
 editor(t).props.onSelectText(detail.imagenes[0],detail.imagenes[0].resultado_ocr.lineas_texto[0]);t=render();
 const textarea=all(t).find(n=>n.type==='textarea'&&n.props.placeholder==='Escribe el texto correcto');
 textarea.props.onChange({target:{value:'BORRADOR'}});t=render();
 confirmar=false;btn(t,'Siguiente →').props.onClick();t=render();assert.equal(editor(t).props.item.id,'a');
 confirmar=true;consultaOcupada=true;btn(t,'Siguiente →').props.onClick();t=render();assert.equal(editor(t).props.item.id,'a');
 consultaOcupada=false;
 // V14.5: verificar nunca descarta un borrador silenciosamente.
 await editor(t).props.onVerifyImage(detail.imagenes[0]);t=render();assert.equal(editor(t).props.item.id,'a');
 assert(all(t).some(n=>n.type==='div'&&String(n.props.class).includes('mensaje-error')&&String(n.children).includes('Hay cambios sin guardar')));
 // Cerrar corrección descarta el borrador visible y limpia el estado de navegación.
 btn(t,'Cerrar corrección').props.onClick();t=render();
 await editor(t).props.onVerifyImage(detail.imagenes[0]);t=render();assert.equal(editor(t).props.item.id,'c');
 await editor(t).props.onVerifyImage(detail.imagenes[2]);t=render();assert(!editor(t));
 assert(all(t).some(n=>n.children.includes('No hay imágenes que coincidan con los filtros actuales. Puedes volver a mostrarlas desde los botones de filtro.')));
 btn(t,'Mostrar imágenes verificadas').props.onClick();t=render();assert.equal(editor(t).props.item.id,'a');
 console.log('OK: filtro, límites, navegación, borradores, bloqueo durante guardado, avance tras verificar, última imagen e historial plegado.');
  // V5: una región de origen dudosa no bloquea la caja exacta.
  detail.imagenes[0].resultado_ocr.lineas_texto[0].marco_region='region-a';
  detail.imagenes[0].resultado_ocr.recortes=[{marco:'region-a',orientacion_grados:0,
    orientacion_dudosa:true,orientacion_confirmada:false,
    candidatos_orientacion:[{grados:90,texto:'REGION GRANDE',confianza:0.9}]}];
  t=render();editor(t).props.onSelectText(detail.imagenes[0],detail.imagenes[0].resultado_ocr.lineas_texto[0]);t=render();
  let campo=all(t).find(n=>n.type==='textarea'&&n.props.placeholder==='Escribe el texto correcto');
  assert(campo && !campo.props.disabled,'V5 no debe bloquear la corrección textual por orientación regional dudosa');
  campo.props.onChange({target:{value:'A.90'}});t=render();
  let form=all(t).find(n=>n.props.id==='formulario-correccion-activa');
  await form.props.onSubmit({preventDefault(){}});t=render();
  assert.equal(ultimaCorreccion.texto_correcto,'A.90');
  assert.equal(ultimaCorreccion.tipo_unidad,'renglón');
  assert.equal(editor(t).props.item.resultado_ocr.lineas_texto[0].texto,'A.90');
  campo=all(t).find(n=>n.type==='textarea'&&n.props.placeholder==='Escribe el texto correcto');
  campo.props.onChange({target:{value:'A.91'}});t=render();
  const accion=all(t).find(n=>n.type==='select'&&all(n).some(o=>o.type==='option'&&o.props.value==='aceptar'));
  accion.props.onChange({target:{value:'aceptar'}});t=render();
  form=all(t).find(n=>n.props.id==='formulario-correccion-activa');
  await form.props.onSubmit({preventDefault(){}});t=render();
  assert.equal(ultimaCorreccion.accion,'corregir','Aceptar no debe descartar una edición manual de la casilla');
  assert.equal(editor(t).props.item.resultado_ocr.lineas_texto[0].texto,'A.91');
  console.log('OK: V6 corrige y sobrescribe una caja exacta aunque su región de origen esté marcada como dudosa.');
})().catch(e=>{console.error(e);process.exitCode=1;});
