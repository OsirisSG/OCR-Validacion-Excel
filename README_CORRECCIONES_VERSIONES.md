# Integración de versiones y correcciones — 2026-09-16

Este paquete es la versión consolidada que conviene conservar. Se construyó comparando los tres ZIP recibidos y conservando la base completa más las correcciones posteriores de interfaz, persistencia y edición de zonas.

## Qué ZIP era cada uno

- `3283afce-d73f-4e04-ace8-c2f8b5091f7a.zip`: proyecto completo anterior. Sirve como referencia histórica, pero no contiene las correcciones nuevas de sobrescritura ni las mejoras posteriores del editor.
- `4f78a411-e020-4ccc-b3ca-0ab54dd33464.zip`: **paquete de parche**, no proyecto completo. Contiene versiones posteriores de `aprendizaje.py`, backend, frontend, estilos y pruebas JavaScript. No debe usarse solo como instalación.
- `24d5f233-42e6-4d9e-9f89-abe7aa9134fd.zip`: proyecto completo más la primera parte de las correcciones de sobrescritura (`utilidades/correcciones_ocr.py` y pruebas Python). Es la mejor base de los tres.

La versión de este ZIP usa `24d5f233-42e6-4d9e-9f89-abe7aa9134fd.zip` como base y superpone los archivos más recientes de `4f78a411-e020-4ccc-b3ca-0ab54dd33464.zip`. El ZIP `3283...` queda superado.

## Problema principal corregido: una corrección ya guardada no se podía rectificar

Antes, varias rutas del sistema partían del OCR bruto o de la primera corrección y podían volver a mostrar una versión antigua. Eso afectaba especialmente una secuencia como:

1. OCR reconoce `ABC`.
2. Se confirma `A.1`.
3. Después se descubre que era incorrecto y se cambia a `A.2`.
4. Al recargar, alguna vista o exportación podía seguir usando `A.1` o incluso `ABC`.

Ahora las confirmaciones se tratan como historial ordenado. La última confirmación válida para la misma imagen y caja es la vigente. También se admite volver a un valor anterior: si se guardó `A.1`, luego `A.2` y finalmente se confirma otra vez `A.1`, esa reconfirmación recibe una fecha nueva y vuelve a ser la versión activa.

Además, después de guardar desde el dashboard el frontend vuelve a consultar el detalle y comprueba que el texto devuelto por el servidor coincide con el borrador. Si no coincide, no muestra un éxito falso y conserva el texto que estabas editando.

## Funciones de interfaz que se conservan

- Clic en un texto OCR para abrir la corrección y desplazarse automáticamente al formulario correspondiente.
- Texto completo y listado de lecturas OCR desplegable.
- Estado visual por bloque: confirmado/corregido o pendiente.
- Vista del recorte asociado al texto seleccionado.
- Alternativas OCR por orientación con texto y confianza para 0°, 90°, 180° y 270° cuando están disponibles.
- Clic en una alternativa para copiar su lectura a **Texto correcto** sin guardarla automáticamente.
- Giro visual del recorte y restablecimiento de giro.
- Botón **Comparar lecturas de esta zona** para pedir alternativas cuando la zona seleccionada no las tenía persistidas.
- Guardado de orientación regional y retorno a orientación automática.
- Herramientas de selección, unión, movimiento, ajuste y división de zonas.
- Navegación **Anterior / Siguiente** entre imágenes.
- Opción **Ocultar imágenes verificadas / Mostrar todas las imágenes**.
- Protección de borradores: si cambias de imagen con texto o región sin guardar, se pide confirmación; también se bloquea el cambio mientras hay una operación de guardado en curso.
- Historial/lista de aprendizaje plegable.
- Contadores de progreso del caso (`con texto`, `descartadas`) y posición actual de navegación.
- Correcciones de bloque completo, de renglón y de zonas editadas.
- Regeneración del Excel mediante la cola existente; las correcciones guardadas se proyectan también en la ruta de exportación.

## Cómo se resuelve la persistencia

La lógica común está en `utilidades/correcciones_ocr.py`. Esa función aplica correcciones sin destruir el OCR bruto y entiende tanto el formato nuevo —varias correcciones cuyo origen sigue siendo el OCR original— como historiales antiguos encadenados (`original → corrección 1 → corrección 2`).

`aprendizaje.py` actualiza la marca temporal cuando se reconfirma una combinación ya existente. Para las muestras visuales, la muestra vigente de una misma imagen/caja queda confirmada y las versiones anteriores dejan de ser la muestra entrenable vigente. Así se evita que una rectificación conviva como si ambas respuestas fueran simultáneamente correctas.

El backend aplica la memoria humana antes de buscar el bloque que se va a corregir. Por ello puede editarse de nuevo una lectura que ya aparece corregida. La acción **Aceptar lectura OCR** tampoco pisa silenciosamente un texto que hayas modificado en el formulario: si el borrador difiere del texto visible, el frontend envía una corrección real.

## Instalación sobre tu proyecto actual

1. Cierra el backend.
2. Haz una copia de seguridad de tu instalación actual.
3. **Conserva especialmente** `.aprendizaje/` si contiene `aprendizaje.sqlite3`; ahí viven correcciones, revisiones y muestras supervisadas. Conserva también los datos generados que necesites, como `validacion_resultados.json`, `.cache_ocr/` y los Excel ya generados.
4. Extrae este ZIP sobre una copia del proyecto o sustituye solamente el código. No borres tu `.aprendizaje` existente.
5. Vuelve a iniciar con `Iniciar_OCR.bat`, `iniciar.py` o `iniciar.command` según el sistema.
6. En el navegador usa `Ctrl+F5` (o recarga sin caché). `index.html` ya incluye una nueva versión de `app.js` y `estilos.css` para evitar cargar archivos antiguos desde caché.

No es necesario volver a entrenar para que una corrección de texto ya guardada se vea. Entrenamiento visual y corrección visible son procesos distintos.

## Prueba manual recomendada

Abre una imagen con OCR y selecciona un bloque. Comprueba que la página baja hasta el editor, revisa las tarjetas 0/90/180/270 y sus porcentajes, elige una lectura, corrígela y guarda. Después modifica nuevamente una letra o número, guarda otra vez y recarga la página. Debe mostrarse la segunda versión. Repite el mismo flujo con **bloque completo** y, si utilizas uniones de zona, con una zona unida.

También conviene verificar la navegación: activa **Ocultar imágenes verificadas**, usa Anterior/Siguiente y confirma que no se pierde un borrador sin pedir permiso.

## Validación automatizada realizada

- `python -m compileall`: sin errores de sintaxis.
- `node --check dashboard/frontend/app.js`: sin errores de sintaxis JavaScript.
- 5 pruebas JavaScript específicas del editor: pasaron, incluyendo navegación, rotaciones, clic con desplazamiento al formulario, copia de alternativas y sobrescritura tras recarga.
- 115 pruebas Python independientes de los fixtures empresariales pasaron en conjunto.
- En `pruebas/test_dashboard.py`, 17 pruebas pasaron y 6 dependen de resultados/fixtures que no estaban incluidos en los ZIP recibidos (`validacion_resultados.json` y banco externo de ejemplo).
- Las 2 pruebas de `pruebas/test_excel_textos.py` también dependen de `validacion_resultados.json`, ausente del paquete.
- Una prueba heredada esperaba una sola lectura regional; se actualizó para el comportamiento vigente de cuatro orientaciones, que es necesario para mostrar las alternativas 0/90/180/270.

Los fallos dependientes de fixtures no se “arreglaron” inventando datos, porque eso ocultaría la ausencia real de los archivos de prueba y podría mezclar rutas falsas con tu proyecto.

## Archivos principales modificados o añadidos

- `aprendizaje.py`
- `dashboard/backend/app.py`
- `dashboard/frontend/app.js`
- `dashboard/frontend/estilos.css`
- `dashboard/frontend/index.html`
- `utilidades/correcciones_ocr.py`
- `pruebas/test_reconfirmacion_unittest.py`
- `pruebas/test_sobrescritura_publica_unittest.py`
- `pruebas/test_editor_zonas.cjs`
- `pruebas/test_estado_texto.cjs`
- `pruebas/test_navegacion_imagenes.cjs`
- `pruebas/test_texto_rotacion.cjs`
- `pruebas/test_redireccion_correccion.cjs`
- `pytest.ini`
- `instalar.command`
- `iniciar.command`

Consulta `docs/correcciones_versiones_20260916.md` para una explicación más técnica del flujo de datos y de las decisiones de integración.
