# OCR Versuchsmatrix — V11

## Objetivo de esta versión

V11 prioriza estabilidad del editor, filtros de revisión y confiabilidad del reporte BMG sobre nuevas pasadas OCR.
Se construyó sobre V10.

## Cambios del editor

- **Ajustar / dividir bloque** conserva el texto vigente del bloque al abrir el editor. Ya no comienza vacío.
- Se separa el **giro base** (0/90/180/270) del **ángulo efectivo** producido por el ajuste fino. Así, un bloque 0°→7° que se gira +90° pasa a la base 90° y puede verse como 90°→97°, en vez de intentar buscar una orientación base inexistente de 97°.
- Se mantienen mover región, cuatro tiradores de esquina, edición numérica X/Y/ancho/alto y división en dos.
- Las anotaciones manuales de texto omitido permanecen en una capa independiente; no deben bloquear el ajuste o división de una caja OCR.

## Ajuste fino opcional

El editor mantiene las cuatro orientaciones cardinales y ahora ofrece dos decisiones explícitas:

- **Tomar ajuste fino**: usa el ángulo efectivo y la lectura obtenida después del deskew.
- **No tomar ajuste**: usa el giro cardinal base y la lectura cardinal previa al deskew.

El backend conserva `texto_base` / `confianza_base` además de la lectura ajustada para que esta decisión sea real, no solamente visual. Cambiar entre ambas opciones modifica únicamente el borrador de **Texto correcto** hasta pulsar **Aplicar supervisión**.

## Texto no necesario

La acción de supervisión antes llamada **No corresponde a un campo** aparece como **Texto no necesario**. Es una supervisión negativa, no una muestra entrenable. No debe confundirse con **Esto no es texto**, que sirve para descartar una detección OCR falsa.

## Navegación de imágenes

Se añaden dos filtros independientes:

- **Ocultar imágenes verificadas** / **Mostrar imágenes verificadas**.
- **Ocultar imágenes sin texto** / **Mostrar imágenes sin texto**.

Pueden combinarse. Cuando el filtro de imágenes sin texto está activo y se marca la imagen actual como **Imagen sin datos de texto**, el editor avanza a la siguiente imagen visible. Restaurarla con **Sí tiene texto** vuelve a hacerla elegible.

## Notificaciones

Las tarjetas flotantes de procesamiento y de actualización de Excel siguen persistentes, pero ahora pueden **plegarse/desplegarse**. Plegar una tarjeta no cancela ni oculta internamente la tarea.

## Consolidación: correcciones manuales

Se corrigió una condición crítica: al consolidar ejecuciones, la corrección manual vigente de cada campo se elige por `corregido_en`, no por la fecha general de ejecución de la carpeta.

Si dos correcciones del mismo campo tienen exactamente la misma marca temporal pero valores diferentes:

- se conserva una elección determinista;
- se registra `conflictos_correcciones_manual`;
- el campo queda con `requiere_revision=true` y `estado=conflicto`.

## Excel BMG

V11 refuerza el generador existente:

- 1ST y 2ST permanecen en un mismo libro cuando se consolidan.
- La matriz de apertura conserva verde <=6 ms, amarillo >6 y <=7 ms, rojo >7 ms y gris sin valor válido/con conflicto.
- Los vínculos del resumen siguen apuntando al registro detallado.
- La lista no se limita a 50 casos.
- Los **36 campos** de `CLAVES_PLANTILLA` tienen encabezados explícitos ES/EN/DE.
- Las reglas de procedencia definidas del diccionario de datos están traducidas ES/EN/DE; los campos sin fuente definida muestran un pendiente explícito en cada idioma.
- La matriz distingue **cantidad esperada**, **encontrada** y **procesada**.
- Una combinación de temperatura/generador fuera de las siete combinaciones estándar no desaparece: se agrega a **Casos sin clasificación de matriz**, en gris y con vínculo al detalle.
- Al generar un libro nuevo se limpian los IDs de ejemplo de las zonas de datos de la plantilla antes de escribir resultados reales.

### Limitación que sigue siendo importante

Para consolidar ejecuciones de 1ST y 2ST procesadas desde raíces completamente independientes, conviene fijar `empresarial.proyecto_id` con el mismo valor en ambas ejecuciones. Si queda vacío, el fallback sigue usando el nombre de la carpeta raíz. V11 evita mezclar proyecto/etapa/caso en las claves, pero todavía no puede adivinar con certeza que dos raíces arbitrarias pertenecen al mismo proyecto.

## Pruebas

- Todos los archivos JavaScript de pruebas incluidos pasan.
- 25/25 pruebas focalizadas de zonas, regiones mixtas, ajuste fino, estabilidad y V11 pasaron.
- Suite Python general: **172 pruebas pasan**.
- **8 pruebas** no se pueden completar con el paquete limpio porque dependen de `validacion_resultados.json` y del banco externo de imágenes/fixtures, que no se incluyen para no mezclar datos de prueba con el proyecto del usuario.

## Instalación

1. Cierra el dashboard y el proceso Python.
2. Respalda `.aprendizaje/`, `validacion_resultados.json` y tus resultados reales.
3. Si vienes exactamente de V10, descomprime el PATCH V11 sobre la raíz del proyecto.
4. No sustituyas `.aprendizaje/aprendizaje.sqlite3` con una base vacía.
5. Reinicia el servidor.
6. Recarga el navegador; V11 cambia el identificador de caché de `app.js`, `i18n.js` y `estilos.css`.

