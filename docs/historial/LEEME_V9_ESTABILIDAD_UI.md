# OCR Versuchsmatrix — V9 Estabilidad de interfaz y edición

Fecha: 2026-09-21  
Base utilizada: **V8 consolidada del 20-09-2026**.

> Si existe una versión posterior a V8 fuera de este paquete, no mezclar archivos a ciegas. Portar este parche sobre esa versión comparando los archivos modificados.

## Qué corrige V9

### Idiomas ES / EN / DE

- Se amplió la cobertura del traductor para menús, botones, ayudas, estados y mensajes dinámicos.
- El observador de idioma ahora también reacciona a cambios de texto realizados por React, no solo a nodos nuevos.
- Se protegen del traductor las lecturas OCR, texto libre, código, rutas y elementos marcados como `data-no-translate`.
- El idioma de interfaz sigue siendo independiente de los idiomas elegidos para exportación.

### Tema oscuro y contraste

Se normalizaron variables semánticas (`--superficie`, `--texto-1`, `--texto-secundario`, `--azul`) y se añadieron reglas específicas para estados que antes conservaban colores pensados para tema claro. Se revisaron estados verificados, pendientes, errores, pausa, avisos, controles, opciones de `select` y paneles del editor.

### Notificaciones persistentes

La actividad del pipeline y la cola de Excel se muestran ahora como tarjetas flotantes en la esquina inferior derecha. La notificación de procesamiento permanece mientras el proceso está activo/pausado/cancelándose y conserva un estado final visible al completar, detener con avance o fallar.

### Respuesta tardía de una corrección

Cada guardado conserva la identidad `{imagen, unidad}` que fue enviada. Si el usuario ya seleccionó otro bloque cuando llega la respuesta del servidor, la respuesta confirma la primera corrección pero **no cambia la selección ni el borrador actual**.

### “Imagen verificada” y falso aviso de descarte

El editor mantiene una línea base del texto realmente persistido. Después de verificar que el servidor devolvió la corrección guardada, esa línea base se actualiza. Por ello una corrección ya guardada no se considera un borrador pendiente al verificar/cambiar de imagen. Si el usuario modifica de nuevo el texto después del guardado, el aviso sí aparece.

### Ajustar / dividir con texto omitido manual

Las anotaciones manuales se conservan en una capa independiente. Una superposición ya no bloquea el ajuste o división de un bloque OCR exacto. Una unión genérica que abarque una anotación manual sigue avisando para evitar mezclar/doblar contenido.

### Guardado vs entrenamiento

- La acción predeterminada es `guardar_sin_entrenar`.
- Una corrección manual sí se guarda y prevalece en su ámbito.
- Guardar **no ejecuta entrenamiento**.
- Para proponer una corrección al dataset visual se elige explícitamente `Guardar y proponer como ejemplo de entrenamiento`.
- Un texto omitido manual se guarda siempre; solo se propone como muestra entrenable si se marca la casilla correspondiente.
- El entrenamiento visual continúa siendo una acción por lote y evaluada, no una consecuencia automática de cada edición.

### Descarte múltiple de textos

En `Texto completo y todas las lecturas OCR` aparece un modo `Seleccionar varios textos`. Permite seleccionar varias detecciones de la misma imagen y descartarlas con una sola operación. El backend actualiza la revisión y solicita una sola actualización de Excel para el lote completo.

### Rendimiento

Se aplicaron optimizaciones conservadoras:

1. Las correcciones ya no esperan a refrescar la lista completa de aprendizaje para devolver el control al editor.
2. La rotación tampoco bloquea esperando ese refresco secundario.
3. La cola de Excel agrupa cambios cercanos durante 3 s para evitar regenerar el libro por cada clic consecutivo.
4. Las cuatro lecturas 0°/90°/180°/270° de una caja exacta usan una caché en memoria acotada (256 entradas). Se invalida al cambiar el archivo/orientación o el modelo visual.
5. El descarte múltiple evita varias recargas/exportaciones cuando se eliminan varias detecciones de una misma imagen.

## Sobre filtrar “solo etiquetas y plásticos”

**No se activó un filtro destructivo en V9.** Es intencional.

El sistema conoce regiones OCR y tiene preprocesamiento útil para etiquetas impresas y texto grabado/moldeado, pero todavía no posee un clasificador suficientemente fiable que determine que una fotografía o región es “plástico relevante” frente a otra evidencia. Descartar todo lo demás antes del OCR puede ocultar números de prueba, pizarras, fechas o relaciones necesarias para corroboración.

La estrategia recomendada es:

- conservar todas las imágenes válidas como evidencia;
- limitar OCR mediante regiones/caché y reprocesamiento selectivo;
- clasificar relevancia después de la detección;
- cuando haya suficientes ejemplos confirmados, añadir un modo opcional `Etiquetas y plásticos` sin convertirlo en el comportamiento obligatorio.

## Mejoras V8 comprobadas antes de modificar

La batería V8 sigue pasando para:

- identidad `OCR Versuchsmatrix`;
- interfaz ES/EN/DE y exportación independiente del idioma de interfaz;
- exportación ES/EN/DE desde la misma instantánea;
- identidad estable proyecto/etapa/caso;
- consolidación 1ST + 2ST;
- matriz de tiempo de apertura y límites 6/7 ms;
- correcciones sucesivas y persistencia;
- editor V6 con cuatro variantes por orientación;
- cola de Excel y reanudación contempladas por las pruebas disponibles.

El tiempo de apertura automático continúa siendo un dato a validar antes de convertir una lectura OCR en valor confirmado.

## Validación V9

Resultados en el paquete limpio:

- Todas las pruebas JavaScript del editor pasan, incluida una nueva prueba de carrera para respuesta tardía.
- Pruebas V8 + aprendizaje + zonas + reconfirmación + orientación + cola + no-texto + V9: pasan.
- Suite completa: **165 pruebas pasan**.
- Quedan **8 pruebas no ejecutables con éxito por datos de prueba ausentes en el ZIP base**: seis dependen del banco/dashboard controlado y dos de `validacion_resultados.json`. Son las mismas dependencias externas ya identificadas; V9 no fabrica esos datos.
- `node --check` para `app.js` e `i18n.js`: correcto.
- `python -m compileall` para backend/aprendizaje: correcto.

## Archivos principales modificados

- `dashboard/frontend/app.js`
- `dashboard/frontend/i18n.js`
- `dashboard/frontend/estilos.css`
- `dashboard/frontend/index.html`
- `dashboard/backend/app.py`
- `aprendizaje.py`
- `pruebas/test_v9_frontend.cjs`
- `pruebas/test_v9_estabilidad_unittest.py`

## Instalación segura sobre V8

1. Cerrar completamente el dashboard/servidor.
2. Respaldar `.aprendizaje/`, `.cache_ocr/`, `validacion_resultados.json` y los Excel reales.
3. Aplicar el PATCH V9 sobre la raíz del proyecto y permitir reemplazar código.
4. **No sustituir la base real `.aprendizaje/aprendizaje.sqlite3` por la del paquete.** El patch no contiene una base de aprendizaje.
5. Reiniciar el servidor. El backend envía `no-cache` para frontend; no hace falta borrar el caché OCR ni reprocesar el lote para instalar V9.
