# OCR Versuchsmatrix · V8

Esta versión continúa sobre V7/V6 sin borrar el aprendizaje ni el progreso existentes. El objetivo es separar claramente interfaz, extracción/consolidación y exportación Excel, preservando el editor OCR aprobado en V6.

## Cambios principales

### Identidad e interfaz
- Nombre visible: **OCR Versuchsmatrix**.
- Cabecera y navegación más compactas/profesionales, iconos SVG y controles unificados.
- Se conserva tema claro/oscuro y su preferencia local.
- Selector persistente ES / EN / DE. La traducción visible funciona localmente, sin servicios de Internet, y evita tocar lecturas OCR, códigos, seriales y texto libre.
- Se mantiene el editor V6: selección, zoom, desplazamiento, giros, cuatro variantes por orientación, borrador automático en Texto correcto, edición de zonas, historial y sobrescrituras.
- Se puede etiquetar una supervisión con **componente** (bolsa de aire, tablero, otro, por identificar) y **campo propuesto**.

### Identidad de casos y consolidación
- Los casos nuevos usan una identidad portable basada en proyecto + etapa + número/caso + huella de ruta relativa. Nunca depende de una ruta absoluta.
- `empresarial.proyecto_id` puede fijarse manualmente en `config.yaml`; si queda vacío se usa el nombre de la raíz.
- `utilidades/consolidacion.py` permite unir ejecuciones separadas de 1ST y 2ST de forma idempotente y conserva correcciones manuales.
- La consolidación reconoce claves históricas V7 para evitar duplicar el mismo caso al migrar.
- API local: `POST /api/resultados/consolidar` con una lista de JSON de resultados. No repite OCR.

### Extracción y procedencia
- Cada candidato nuevo conserva proyecto, etapa, caso, componente, imagen, bbox original, orientación, transformaciones, regla, fuente, confirmación manual y versión de procesamiento cuando esos datos están disponibles.
- Los seriales etiquetados conservan letras, espacios, asteriscos y ceros iniciales; no se convierten a números.
- Las fechas impresas admiten `.`, `/` y `-`. Sólo se interpreta automáticamente un formato inequívoco; `25-06-19`, por ejemplo, queda ambiguo hasta revisión y no se fuerza a un orden global.
- Corrección de caso, regla reutilizable y entrenamiento OCR siguen siendo conceptos separados.

### Tiempo de apertura
- Campo preparado: `opening_time_ms`.
- Captura manual validada en el dashboard.
- Verde: `0–6 ms` inclusive.
- Amarillo: `>6–7 ms` inclusive.
- Rojo: `>7 ms`.
- Gris: ausente, inválido o conflictivo.
- La captura automática del tiempo sigue intencionalmente pendiente: la V8 no fabrica el dato.

### Excel por proyecto
- La plantilla `plantillas/reporte_bmg_1st_2st.xlsx` es byte a byte la misma referencia proporcionada por el usuario.
- 1ST y 2ST pueden estar juntos. La lista deja de limitarse a 50 casos: 2ST se desplaza cuando 1ST necesita más filas.
- La matriz deja de truncar a 10 resultados por grupo; crece verticalmente cuando hace falta.
- Los hipervínculos de la matriz apuntan al registro exacto por identidad estable, no sólo por número de prueba.
- Se añade una hoja de trazabilidad con evidencia y procedencia.
- Exportación independiente del idioma de interfaz: ES, EN, DE o los tres. Los tres XLSX se generan desde la misma instantánea y reciben sufijos `_ES`, `_EN`, `_DE`.
- Los textos libres y valores reales no se traducen automáticamente.
- La escritura del reporte BMG es atómica y reintenta bloqueos transitorios; si Excel mantiene el archivo abierto, se informa sin borrar el archivo válido anterior.

## APIs nuevas

- `POST /api/resultados/exportar` `{ "idiomas": ["es","en","de"] }`
- `GET /api/resultados/exportado?archivo=...`
- `POST /api/resultados/consolidar` `{ "archivos": ["ejecucion_1st.json","ejecucion_2st.json"], "regenerar_excel": true }`

## Compatibilidad e instalación

1. Cierra el dashboard.
2. Respaldar `.aprendizaje/`, `validacion_resultados.json`, `.cache_ocr/` y los Excel vigentes.
3. Copia el parche sobre V7 y permite reemplazar código.
4. **No reemplaces tu `.aprendizaje/aprendizaje.sqlite3` con una base de desarrollo.**
5. Reinicia el servidor y recarga el navegador. No es necesario ejecutar `preparar_prueba_ocr.py --preparar` ni borrar la caché OCR.

## Pendientes explícitos

- La captura automática fiable de `opening_time_ms` todavía depende de localizar una fuente visual/medición inequívoca. Hasta entonces se captura manualmente o queda gris.
- La capa ES/EN/DE traduce el vocabulario controlado de la aplicación; cualquier nuevo texto visible que se agregue en el futuro debe añadirse al diccionario local. Códigos, seriales y texto libre permanecen intactos.
- La decodificación 2D se mantiene en modo oportunista según las dependencias locales ya disponibles; no se añadió ninguna dependencia obligatoria de Internet.

## Validación V8

Pruebas específicas añadidas para identidad, consolidación idempotente, migración de claves V7, seriales con asteriscos/ceros, fechas ambiguas y matrices con más de 50 casos. Se conserva además toda la suite V6 de selección, orientación y sobrescritura.

## Reanudación, pausa y cola de guardado

- La ejecución recuerda los idiomas de exportación elegidos y el nombre base de salida.
- Al pausar o cancelar conservando avance, el sistema genera un Excel parcial claramente identificado. Si se eligieron varios idiomas, ofrece un parcial por idioma desde la misma instantánea disponible.
- Regenerar el Excel tras una corrección usa `validacion_resultados.json`/el estado consolidado vigente y no vuelve a ejecutar OCR.
- La cola expone los estados de persistencia **pendiente / guardando / guardado / error**. Una exportación que termina tarde sólo confirma la revisión que empezó a guardar; una corrección posterior permanece pendiente y no puede quedar marcada como guardada por esa respuesta tardía.
- Las escrituras de JSON y del reporte BMG usan archivo temporal único, reemplazo atómico y reintentos acotados. Un archivo Excel abierto puede producir un error de exportación, pero no elimina el último archivo válido ni el progreso OCR.

## Corrección, clasificación y aprendizaje

- **Guardar sin entrenar** es la acción predeterminada. Una corrección confirmada de un caso no equivale a entrenar el modelo OCR.
- **Corregir y entrenar** sigue disponible sólo como acción explícita.
- Componente y campo se pueden confirmar desde el editor. La confirmación queda ligada al caso/evidencia y se proyecta en la consolidación y Excel; no se propaga automáticamente a otras piezas.
- Una respuesta tardía del servidor no reemplaza un borrador más reciente que el usuario haya escrito o seleccionado mientras se estaba guardando.

## Diccionario y trazabilidad del Excel

El reporte BMG añade una hoja de diccionario de datos que documenta la fuente/regla de cada campo conocido. Los campos cuya fuente automática aún no está definida quedan marcados como pendientes/manuales en vez de rellenarse con valores del ejemplo. La hoja de trazabilidad conserva, cuando existe, proyecto, etapa, caso, componente, imagen, región, OCR original, corrección/normalización, regla, orientación y confirmación; las rutas locales de evidencia se enlazan cuando están disponibles.

## Validación final de esta entrega

- `python -m compileall`: correcto.
- `node --check dashboard/frontend/app.js`: correcto.
- `node --check dashboard/frontend/i18n.js`: correcto.
- 7 pruebas JavaScript/CJS heredadas del editor V6: correctas; se mantienen las cuatro variantes 0°/90°/180°/270°, giro→borrador y sobrescritura.
- 15 pruebas V8 específicas de identidad, consolidación, idiomas, exportación, frontend, seriales/fechas y reporte dinámico: correctas.
- Suite Python completa: **160 pruebas correctas y 8 dependientes de fixtures externos no incluidos**. Seis requieren el conjunto de dashboard/banco externo y dos requieren `validacion_resultados.json`. No se generaron datos ficticios para forzarlas a pasar.
