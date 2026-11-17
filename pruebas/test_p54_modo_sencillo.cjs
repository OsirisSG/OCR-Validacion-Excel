// P54 · «Modo sencillo»: la pantalla de inicio pide sólo lo imprescindible y reutiliza el
// mismo diálogo de rangos/proyecto y el mismo POST /api/pipeline que «Procesar carpeta».
const fs = require('fs'), path = require('path'), assert = require('assert'), vm = require('vm');
const root = path.resolve(__dirname, '..');
const leer = (r) => fs.readFileSync(path.join(root, 'dashboard/frontend', r), 'utf8');
const sencillo = leer('sencillo.js'), css = leer('sencillo.css'), app = leer('app.js');
const i18n = leer('i18n.js'), index = leer('index.html');

// 1. Se carga antes de app.js y con su hoja de estilos; sin recursos de red.
const scripts = Array.from(index.matchAll(/<script src="([^"]+)"/g), (m) => m[1].split('?')[0]);
assert(scripts.indexOf('sencillo.js') >= 0 && scripts.indexOf('sencillo.js') < scripts.indexOf('app.js'),
  'sencillo.js debe cargarse antes de app.js');
assert(/href="sencillo\.css\?v=/.test(index), 'falta sencillo.css en index.html');
for (const [nombre, texto] of [['sencillo.js', sencillo], ['sencillo.css', css]])
  assert(!/https?:\/\/|@import|url\(/.test(texto), `${nombre} no debe usar recursos externos`);

// 2. La aplicación abre el modo sencillo por defecto y deja volver desde el avanzado.
assert(app.includes('modoSencillo.rutaInicial()'), 'App no usa la ruta inicial del modo sencillo');
assert(app.includes('vista === "inicio"'), 'App no pinta la vista #/inicio');
assert(app.includes('href="#/inicio"') && app.includes('modoSencillo.fijarModo("sencillo")'),
  'falta el regreso «Modo sencillo» en el dashboard avanzado');
assert(app.includes(': "#/resumen");'), 'sin sencillo.js la app debe seguir abriendo el resumen');

// 3. Mismo contrato que «Procesar carpeta»: diálogo de rangos + proyecto, y el mismo POST.
for (const pieza of ['DialogoRangosApertura', 'enviarJSON("/api/pipeline"', 'rango_apertura', 'proyecto:',
  'sin_asignar', 'RedSegura.crearSondeoSerial', '/api/pipeline/cancelar', 'ExportadorExcel',
  'contenido: conVideo ? "todo" : "fotos"', 'idiomas_exportacion: [idioma]'])
  assert(sencillo.includes(pieza), `sencillo.js no reutiliza: ${pieza}`);
assert(sencillo.includes('if (!proyecto)'), 'sin proyecto elegido no se inicia nada (C7)');

// 4. Sólo cuatro decisiones a la vista y el paso al análisis avanzado.
for (const texto of ['"Carpeta"', '"Laboratorio"', '"Idioma"', '"Vídeos"', '"Análisis avanzado"', '"Procesar"'])
  assert(sencillo.includes(`t(${texto})`), `falta en la pantalla sencilla: ${texto}`);
assert(/id: "EDAG"[^}]*disponible: true/.test(sencillo), 'EDAG debe ser el laboratorio disponible');

// 5. Todo texto t("…") de sencillo.js tiene traducción al inglés y al alemán.
const D = { en: {}, de: {} };
const bloque = i18n.slice(i18n.indexOf('const P54 = {'), i18n.indexOf('for (const idioma of ["en", "de"])'));
const P54 = vm.runInNewContext(`${bloque}; P54`);
const claves = new Set(Array.from(sencillo.matchAll(/\bt\("((?:[^"\\]|\\.)*)"\)/g), (m) => m[1]));
assert(claves.size > 40, 'se esperaban las cadenas del modo sencillo');
for (const idioma of ['en', 'de'])
  for (const clave of claves)
    assert(P54[idioma][clave] || i18n.includes(`"${clave}":`), `falta traducción (${idioma}): ${clave}`);
void D;

// 6. Accesible y sin mareo: foco visible, zonas táctiles de 44 px y «reducir movimiento».
assert(css.includes('prefers-reduced-motion'), 'sencillo.css debe respetar «reducir movimiento»');
assert(css.includes('focus-visible'), 'sencillo.css debe marcar el foco del teclado');
assert(!/transition:[^;]*\b(width|height|top|left)\b/.test(css), 'sólo se anima transform y opacity');
assert(/\.sen-segmentos button \{[^}]*min-height: 44px/.test(css), 'zona táctil mínima de 44 px');

console.log('P54: modo sencillo OK');
