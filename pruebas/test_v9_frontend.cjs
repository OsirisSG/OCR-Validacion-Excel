const fs=require('fs'), vm=require('vm'), path=require('path'), assert=require('assert');
const base=path.join(__dirname,'../dashboard/frontend');
let slots=[], cursor=0, efectos=[];
let confirmaciones=0;
let detail={id:'caso',nombre:'Caso',perfil:'empresarial',comparacion:{resultado:'parcial'},revision:{estado:'parcial'},
  imagenes:[{id:'a',ruta:'a.jpg',nombre:'A',estado_imagen:'pendiente',resultado_ocr:{dimensiones:[200,100],lineas_texto:[
    {texto:'UNO',bbox:[0,0,50,20],tipo_unidad:'renglón'},
    {texto:'DOS',bbox:[60,0,50,20],tipo_unidad:'renglón'}]},correcciones:[]}]};
let modo='demorado', resolverCorreccion=null;
function aplicarCorreccion(data){
  detail={...detail,imagenes:detail.imagenes.map(i=>i.id!==data.imagen_id?i:{...i,resultado_ocr:{...i.resultado_ocr,
    lineas_texto:i.resultado_ocr.lineas_texto.map(u=>JSON.stringify(u.bbox)!==JSON.stringify(data.bbox)?u:
      {...u,texto_original:u.texto_original||u.texto,texto:data.texto_correcto,confirmado_manualmente:true})}})};
}
const ctx=vm.createContext({
 React:{
  createElement:(type,props,...children)=>({type,props:props||{},children}),
  useState:init=>{const i=cursor++;if(!(i in slots))slots[i]=typeof init==='function'?init():init;return[slots[i],v=>{slots[i]=typeof v==='function'?v(slots[i]):v;}];},
  useRef:init=>{const i=cursor++;return slots[i]||(slots[i]={current:init});},
  useEffect:(f,deps)=>{const i=cursor++,old=slots[i];if(!old||deps.some((v,j)=>v!==old[j])){slots[i]=deps;efectos.push(f);}},
  useMemo:f=>f(),useCallback:f=>f},
 ReactDOM:{createRoot:()=>({render:()=>{}})},
 document:{getElementById:()=>null,querySelector:()=>null},
 window:{confirm:()=>{confirmaciones++;return true;},setTimeout:()=>{},dispatchEvent:()=>{}},
 CustomEvent:function(type,options){this.type=type;this.detail=options.detail;},
 requestAnimationFrame:()=>{}, location:{hash:''},
});
vm.runInContext(fs.readFileSync(path.join(base,'vendor/htm.umd.js'),'utf8'),ctx);
vm.runInContext(fs.readFileSync(path.join(base,'app.js'),'utf8'),ctx);
ctx.useApi=url=>url.startsWith('/api/pruebas/')?[detail,d=>{detail=d;},null]:[{},()=>{},null];
ctx.pedirJSON=async()=>detail;
ctx.enviarJSON=(url,data)=>{
  if(url==='/api/aprendizaje/correcciones'){
    if(modo==='demorado') return new Promise(resolve=>{resolverCorreccion=()=>{aplicarCorreccion(data);resolve({mensaje:'ok'});};});
    aplicarCorreccion(data); return Promise.resolve({mensaje:'ok'});
  }
  if(url==='/api/imagenes/verificar'){
    detail={...detail,imagenes:detail.imagenes.map(i=>({...i,estado_imagen:'verificada'}))};
    return Promise.resolve({mensaje:'ok'});
  }
  return Promise.resolve({mensaje:'ok'});
};
function all(n){return !n||typeof n!=='object'?[]:Array.isArray(n)?n.flatMap(all):[n,...n.children.flatMap(all),...Object.values(n.props).filter(v=>v&&v.type&&Array.isArray(v.children)).flatMap(all)];}
function render(){cursor=0;const tree=ctx.VistaDetalle({nombre:'Caso'});const pending=efectos;efectos=[];pending.forEach(f=>f());return tree;}
const editor=tree=>all(tree).find(n=>typeof n.type==='function'&&n.type.name==='PanelImagen');
const form=tree=>all(tree).find(n=>n.props.id==='formulario-correccion-activa');
const textarea=tree=>all(tree).find(n=>n.type==='textarea'&&n.props.placeholder==='Escribe el texto correcto');
const btn=(tree,label)=>all(tree).find(n=>n.type==='button'&&n.children.includes(label));
(async()=>{
  render(); let t=render();
  const u1=detail.imagenes[0].resultado_ocr.lineas_texto[0], u2=detail.imagenes[0].resultado_ocr.lineas_texto[1];
  editor(t).props.onSelectText(detail.imagenes[0],u1); t=render();
  textarea(t).props.onChange({target:{value:'UNO-CORREGIDO'}}); t=render();
  const primera=form(t).props.onSubmit({preventDefault(){}});
  // Mientras la primera respuesta está en vuelo, el usuario avanza al segundo texto.
  editor(t).props.onSelectText(detail.imagenes[0],u2); t=render();
  assert.equal(textarea(t).props.value,'DOS');
  resolverCorreccion(); await primera; t=render();
  assert.equal(textarea(t).props.value,'DOS','una respuesta tardía no debe devolver el editor al texto anterior');
  const selector=all(t).find(n=>n.type==='select'&&String(n.props.value||'').includes('renglón'));
  assert(selector,'debe conservar una selección OCR activa');

  // Guardar el segundo texto fija la nueva línea base: verificar ya no pide descartar cambios.
  modo='inmediato';
  textarea(t).props.onChange({target:{value:'DOS-CORREGIDO'}}); t=render();
  await form(t).props.onSubmit({preventDefault(){}}); t=render();
  btn(t,'Ocultar imágenes verificadas').props.onClick(); t=render();
  const antes=confirmaciones;
  await editor(t).props.onVerifyImage(detail.imagenes[0]);
  assert.equal(confirmaciones,antes,'una corrección ya persistida no debe provocar aviso de cambios sin guardar');
  console.log('OK: V9 evita saltos por respuestas tardías y no marca como sucio un texto ya persistido.');
})().catch(e=>{console.error(e);process.exitCode=1;});
