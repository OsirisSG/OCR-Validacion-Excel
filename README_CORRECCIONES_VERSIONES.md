## V15 — Videos de alta velocidad y tiempo de apertura de airbag (2026-10-05)

- Integra fotografías y videos en una misma ejecución mediante `Fotos + videos`, `Solo fotos` o `Solo videos`.
- Descubre `.avi/.mp4/.mov/.mkv/.wmv/.m4v` dentro de carpetas `VIDEO` o `VIDEOS`.
- Detecta automáticamente el primer cambio visual compatible con el despliegue del airbag y conserva cuadro, FPS, tiempo, confianza y evidencia.
- Lee overlays superior/inferior para aprovechar timestamps visibles y puede calibrar temporalmente cámaras sincronizadas.
- Consolida el tiempo de apertura por consenso, con soporte nominal de 3 de 4 videos.
- Añade revisión manual de video en el dashboard: cuadro anterior/siguiente, cuadro exacto, tiempo en ms, confirmar apertura o marcar sin evento.
- Conserva resultados de fotos en `Solo videos` y resultados de video en `Solo fotos`, evitando borrar evidencia previa.
- 1000 fps se reporta correctamente como 1.0 ms/cuadro: las décimas no se presentan como exactitud física de 0.1 ms salvo que el overlay o la tasa nativa la sustenten.
- El consenso confirmado alimenta `opening_time_ms` y usa la cola Excel existente.

Ver `LEEME_V15_VIDEO_AIRBAG.md`.

## V14.15.1 — Hotfix i18n del listado (2026-09-28)

- Traduce el placeholder del buscador en ES/EN/DE.
- Traduce las métricas dinámicas de progreso (`con texto`, `descartadas`, `campos`, `faltantes`, `conflictos`).
- Traduce estados internos visibles como `estructura_valida` y `con_conflictos`.
- Aplica el mismo tratamiento al detalle del caso.
- No modifica backend ni aprendizaje.

Ver `LEEME_V14_15_1_I18N_LISTADO.md`.

## V14.15 — Editor de bloque unificado e i18n reforzado (2026-09-28)

- Unifica `Ajustar / dividir bloque` y `Mover bloque` en una sola herramienta: **Editar bloque**.
- El editor unificado conserva movimiento, redimensionado, geometría de cuatro esquinas, inclinación, relectura y división.
- No cambia el contrato de persistencia ni aprendizaje de V14.14: solo se aprende la geometría/texto final confirmados.
- Refuerza traducciones ES/EN/DE de botones y etiquetas dinámicas que podían quedarse en español, incluyendo Completar, Quitar, Verde/Amarillo/Rojo, visibles, Actualizado y estados del listado.
- El enlace dinámico `Abrir ES/EN/DE` usa traducción explícita.
- Actualiza la versión de caché del frontend a `20260928-v14-15`.
- Validación: 19/19 pruebas JavaScript; 238 pruebas Python aprobadas y los mismos 8 fallos históricos por fixtures externos ausentes.

Ver `LEEME_V14_15_EDITOR_BLOQUE_I18N.md`.

## V14.14 — Supervisión simple y aprendizaje automático (2026-09-28)

- Reduce la supervisión positiva visible a **Aceptar lectura** y **Aplicar corrección**.
- Ambas acciones crean muestra visual entrenable; también texto nuevo, uniones y geometría confirmada entrenan automáticamente.
- Desglosa el aviso de cambios sin guardar indicando qué herramienta/borrador está pendiente.
- Sustituye el tooltip frágil por ayuda visible `ⓘ` desplegable.
- Refuerza Unir bloques con selección múltiple por clic y resaltado de los bloques seleccionados.
- Mantiene compatibilidad con `.aprendizaje` y contratos históricos.


## V14.13 — Geometría flexible y aprendizaje de ediciones (2026-09-28)

- Añade edición mediante cuadriláteros de cuatro esquinas a Seleccionar texto, Mover recorte, Unir bloques, Ajustar/dividir bloque y Mover bloque.
- Conserva la geometría final en las ediciones de zona y la reaplica al OCR.
- Las uniones, ajustes, divisiones y movimientos confirmados pueden aportar muestras visuales rectificadas al entrenamiento.
- Solo aprende el estado final confirmado; no registra como ejemplos los movimientos provisionales.
- Mantiene compatibilidad con ediciones históricas basadas únicamente en `bbox`.

## V14.11 — Recortes inclinados para supervisión (2026-09-28)

- El recorte manual de texto omitido puede moverse y girarse entre -45° y +45°.
- La caja inclinada se rectifica antes de releerla; deja de ser una simple rotación visual.
- Las muestras visuales entrenables guardan las cuatro esquinas y usan `warpPerspective`, reduciendo contaminación de líneas vecinas.
- Las anotaciones manuales persisten su polígono mediante una migración SQLite aditiva y compatible.
- Las lecturas por orientación y la relectura manual aceptan el polígono exacto.
- Las selecciones rectangulares históricas siguen funcionando sin cambios.

Ver `LEEME_V14_11_RECORTES_INCLINADOS.md`.

## V14.10 — Identidad OCR y persistencia más rápida (2026-09-25)

- Integra el logo OCR original y variantes clara/nocturna derivadas para cabecera y favicon.
- Agrupa checkpoints de progreso durante 350 ms, manteniendo escritura inmediata en estados críticos.
- Serializa los JSON grandes en formato compacto sin cambiar su contenido.
- La cola Excel usa debounce deslizante: responde rápido a una corrección aislada y agrupa correcciones consecutivas.
- Añade caché segura de SHA-256 para no releer la misma imagen en cada corrección.
- Añade índice reutilizable de rutas para acelerar la carga de vistas previas en lotes grandes.

Ver `LEEME_V14_10_IDENTIDAD_RENDIMIENTO.md`.

# V10 · ajuste angular regional (2026-09-21)

- Mantiene las cuatro variantes 0°/90°/180°/270° del editor.
- Añade ajuste fino automático por región hasta ±45° para etiquetas sesgadas o diagonales.
- Muestra el ángulo efectivo (por ejemplo `0° → 7.2°`) y usa esa lectura como borrador.
- No confirma ni entrena automáticamente.
- Reproyecta las cajas a sus coordenadas originales.
- Búsqueda adaptativa: una pasada fina adicional cuando la orientación cardinal es sólida; refina las cuatro sólo cuando la lectura es débil o en el editor cacheado.

Ver `LEEME_V10_AJUSTE_ANGULAR.md`.

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

## Corrección V2 — reconfirmación de lecturas basadas en símbolos (2026-09-16)

Se corrigió un caso que podía impedir sobrescribir una corrección ya guardada cuando la lectura OCR original estaba formada sólo por signos o puntuación. Ejemplos reales de este patrón son `;`, `|`, `.`, `:` o combinaciones parecidas que visualmente corresponden a dígitos/letras.

Antes, la memoria textual pasaba primero esas lecturas por `normalizar_codigo()`. Como esa función conserva únicamente el alfabeto operativo de códigos, una lectura como `;` se convertía en texto vacío y la segunda confirmación podía ser rechazada aunque la caja seleccionada fuera correcta.

La V2 separa ambos conceptos:

- `correcciones_texto` conserva cualquier texto visible confirmado por la persona y permite sobrescribirlo cronológicamente.
- El modelo ligero de códigos sólo recibe pares que sí contienen caracteres válidos para ese modelo.
- La búsqueda de la unidad OCR prioriza texto y `bbox` exactos antes de normalizar.
- Si `tokens` y `lineas_texto` contienen dos representaciones de la misma caja, una `bbox` exacta se considera una sola selección humana.
- Se añadió `pruebas/test_reconfirmacion_simbolos_unittest.py` para cubrir `; → 4 → 41`, volver a una corrección anterior y reconfirmación a través del handler del dashboard.

Para una instalación que ya usa la versión consolidada anterior basta con sustituir `aprendizaje.py` y `dashboard/backend/app.py`, y reiniciar el servidor. No se debe reemplazar ni borrar `.aprendizaje/aprendizaje.sqlite3`.

## V4 — orientación regional antes que corrección textual

La V3 hacía una suposición demasiado fuerte: trataba la `bbox` de un renglón nacido de una región con orientación dudosa como si ya fuera definitiva. En V4, si el recorte regional sigue `orientacion_dudosa` y no `orientacion_confirmada`, primero se obliga a fijar el giro y reprocesar. La corrección textual queda temporalmente bloqueada tanto en frontend como en backend. Después del reproceso vuelve a estar disponible la sobrescritura normal.

Consulta `LEEME_PATCH_ORIENTACION_SEGURA_V4.md` para el flujo exacto y el caso de las capturas de `IMG_5330` / `IMG_5329`.


## V5 — flujo simple, variantes automáticas y giro como borrador

La V5 elimina la barrera obligatoria de orientación de V4. El editor vuelve a un flujo directo: una sola caja exacta, su imagen y las variantes OCR debajo. El botón “Comparar lecturas de esta zona” desaparece; las variantes se calculan automáticamente al abrir la corrección. Al girar o elegir una variante, su lectura se copia a **Texto correcto** sólo como borrador y no se guarda hasta pulsar **Aplicar supervisión**. También se elimina el panel regional duplicado dentro del formulario para evitar que parezca que una lectura grande va a sobrescribir un renglón individual.

La protección contra sobrescrituras equivocadas queda en la identidad exacta de la unidad (`bbox` y `tipo_unidad`) y en el historial cronológico de correcciones, no en bloquear la edición del usuario. Consulta `LEEME_PATCH_FLUJO_SIMPLE_V5.md`.

Validación V5: 6 pruebas JavaScript del editor pasaron y 123 pruebas Python independientes de los fixtures empresariales externos pasaron. También se verificó sintaxis con `node --check` y `python -m compileall`.

## V6 — 18 de septiembre de 2026

- Restauradas las cuatro propuestas OCR 0°/90°/180°/270° siempre visibles en el bloque exacto.
- El giro o la selección de una tarjeta copia su lectura a `Texto correcto` únicamente como borrador.
- Eliminada la dependencia de la API de edición de zonas para comparar orientaciones.
- Nueva ruta de solo lectura `/api/aprendizaje/lecturas-orientacion`.
- Se conservan eliminados “Comparar lecturas de esta zona” y el bloqueo textual de V4.
- El bloque exacto ocupa todo el ancho para mostrar las variantes desplegadas.
- Caché de `app.js` y `estilos.css` incrementada a `20260918-correcciones-6`.
- El ángulo actual vuelve a mostrarse junto a los botones de giro, y el panel exacto ocupa todo el ancho.
- Validación: 7 pruebas JavaScript correctas; 42 pruebas Python dirigidas correctas; suite completa con 142 correctas y 8 no reproducibles por faltar fixtures empresariales externos (`validacion_resultados.json` y banco externo).

## V7 — Matriz de apertura y reporte BMG 1ST + 2ST

Se mantiene V6 como base de corrección OCR y se añade el reporte BMG solicitado. El dashboard incorpora una matriz clicable 1ST/2ST basada en `opening_time_ms`: verde <=6 ms, amarillo >6 y <=7 ms, rojo >7 ms, gris sin valor fiable. El Excel utiliza el formato `Übersicht Standversuche` + `Versuchsmatrix`, combina ambas etapas en un único archivo y enlaza cada número del resumen con su fila detallada. Ver `LEEME_MATRIZ_APERTURA_V7.md`.

## V8 · OCR Versuchsmatrix (2026-09-20)

V8 conserva el editor V6 y agrega identidad portable de proyecto/etapa/caso, procedencia ampliada, consolidación idempotente 1ST/2ST, interfaz ES/EN/DE, exportación Excel ES/EN/DE desde una misma instantánea, matriz dinámica sin límite fijo de 50 casos, trazabilidad y escritura Excel atómica. `opening_time_ms` queda listo para captura manual y semáforo, sin inventar captura automática.

## V9 · Estabilidad de interfaz, cola y edición (2026-09-21)

- Traducción ES/EN/DE ampliada y actualización de textos dinámicos.
- Correcciones de contraste en tema oscuro.
- Notificaciones persistentes de procesamiento/Excel en esquina.
- Protección contra respuestas tardías que devuelvan el editor a una selección anterior.
- Línea base persistida para evitar falsos avisos al verificar una imagen ya guardada.
- Ajustar/dividir bloques OCR puede convivir con anotaciones manuales superpuestas sin borrarlas.
- Guardar y entrenar quedan separados; texto omitido solo se propone a entrenamiento mediante opt-in.
- Descarte múltiple de detecciones OCR.
- Caché acotada de variantes por orientación, refrescos secundarios no bloqueantes y agrupación de exportaciones Excel.
- No se aplica todavía un filtro destructivo de “solo etiquetas/plásticos”; ver `LEEME_V9_ESTABILIDAD_UI.md`.

## V11 · estabilidad de editor, filtros y consolidación

- Ajustar/Dividir conserva el texto y separa giro base de ángulo efectivo.
- Selector explícito Tomar ajuste fino / No tomar ajuste.
- Acción Texto no necesario.
- Filtros independientes para verificadas e imágenes sin texto.
- Notificaciones flotantes plegables.
- Consolidación por fecha de corrección de cada campo y detección de empates conflictivos.
- Excel: 36 encabezados ES/EN/DE, cantidades esperadas/encontradas/procesadas y casos fuera de la matriz visibles en gris.

Ver `LEEME_V11_ESTABILIDAD_EDITOR_EXCEL.md`.

## V13 — 2026-09-22

- Conserva la sincronización de revisión de V12.
- Perfil CUDA agresivo/adaptativo para RTX A3000 6 GB (`batch_gpu: 8`, techo 12).
- OOM CUDA reduce lote y reintenta en GPU antes de considerar fallback CPU.
- `ejecucion_id` persistente en checkpoint para reanudación idempotente.
- Estado `reanudando` evita doble clic/doble hilo sobre el mismo avance.
- Observaciones OCR se guardan incrementalmente por imagen en SQLite.
- Firma idempotente evita duplicar aprendizaje al reanudar la misma ejecución.

## V14.6 — ajuste fino adaptativo y filtrado semántico (2026-09-24)

- Ajuste fino normal limitado a ±15°.
- Extensión hasta ±30° sólo con evidencia geométrica fuerte; se elimina ±45° como ajuste fino.
- Micro-búsqueda ±2° alrededor del ángulo geométrico en la orientación recomendada.
- Clasificación de candidatas: código, fecha, valor/medición, texto y ruido probable.
- Penalización explícita a alfanuméricos con mezcla irregular de mayúsculas/minúsculas y a símbolos impropios de códigos.
- Consenso entre variantes como evidencia secundaria.
- Filtros visuales sin eliminar las cuatro orientaciones originales.
- Si ninguna candidata es suficientemente congruente, no se sobrescribe automáticamente Texto correcto.
- Ver `LEEME_V14_6_AJUSTE_FILTRO_INTELIGENTE.md`.

## V14.7 — control manual del OCR regional (2026-09-25)

- Añade selector del tipo de dato esperado: automático, código, fecha, número/medición o texto.
- Añade umbral de congruencia configurable y control de copia automática al borrador.
- Añade relectura OCR real a un ángulo exacto elegido por el revisor.
- El ajuste manual cubre ±45°; el automático conserva límites seguros de V14.6.
- Permite forzar Original, CLAHE, binarización adaptativa o relieve, o comparar los cuatro tratamientos.
- Muestra confianza OCR y congruencia por separado y explica las razones de la candidata seleccionada.
- Evita presentar como código lecturas con símbolos fuertes o mezcla sospechosa de mayúsculas/minúsculas aunque llegue una candidata cacheada de una versión previa.
- Mantiene aprendizaje, caché, checkpoints, cola de Excel y flujo de supervisión existentes.

## V14.8 — aprendizaje reforzado de estrategias OCR (2026-09-25)

- Aprende orientación base, ajuste angular, tratamiento visual y tipo de dato únicamente de decisiones humanas finalmente confirmadas.
- Una misma imagen/caja no puede inflar el soporte mediante clics repetidos.
- 2 imágenes coherentes generan sugerencia; 4 imágenes distintas con >=75 % de dominancia habilitan preferencia automática.
- El dashboard muestra soporte/dominancia y permite probar la estrategia aprendida antes de confirmarla.
- El procesamiento normal puede ensayar patrones consolidados en regiones similares, pero los descarta si degradan la congruencia o producen ruido.
- Generalización contextual por proyecto/fase/campo cuando existe contexto; en OCR inicial se limita a grupo estable de ruta y zona relativa.
- Caché de estrategias por instancia para evitar consultas SQLite repetidas por región.
- Las estrategias se incluyen en la exportación del dataset de aprendizaje.
- Ver `LEEME_V14_8_APRENDIZAJE_ESTRATEGIAS.md`.

## V14.9 — Aprendizaje inmediato por imagen
- Una estrategia OCR confirmada puede ensayarse desde la siguiente imagen similar si coincide el grupo de ruta y la geometría normalizada de la zona.
- La estrategia inmediata nunca sustituye una lectura mejor: se compara contra el OCR normal y se rechaza si produce ruido o degrada congruencia.
- El entrenamiento visual deja de depender del botón: al verificar una imagen con nueva muestra entrenable se programa automáticamente cuando se cumplen los mínimos.
- Si el pipeline OCR está usando la GPU, el entrenamiento visual queda diferido y se retoma al finalizar.
- Los ajustes automáticos usan una época por actualización y un candidato sólo se activa automáticamente si mejora validación y prueba.
- «Entrenar lote visual» queda disponible como «Forzar entrenamiento ahora», únicamente como control opcional.

## V14.12 — Uniones de bloques entrenables (2026-09-28)

- `Confirmar reemplazo de bloques` puede crear evidencia visual de EasyOCR y queda activado por defecto.
- Las uniones multilínea se separan por línea cuando el número de líneas coincide con los bloques originales; las reconstrucciones de una sola cadena conservan un recorte unido.
- Las muestras nuevas disparan el aprendizaje visual automático sin esperar al botón manual.
- Al verificar una imagen se recuperan de forma oportunista las uniones antiguas de esa imagen para incorporarlas al dataset visual sin duplicados.
- Si falla la creación del recorte entrenable, la edición humana y la actualización Excel se conservan.
- Ver `LEEME_V14_12_UNIONES_ENTRENABLES.md`.

## V14.12.1 — Etiqueta compacta para uniones entrenables (2026-09-28)

- Simplifica el checkbox a `Usar unión para entrenar OCR`.
- Sustituye la explicación larga visible por un icono `ⓘ` con ayuda contextual.
- La ayuda aclara: una sola línea entrena la zona unida; varias líneas intentan separarse por línea.
- No modifica la lógica de aprendizaje, persistencia, Excel ni entrenamiento de V14.12.
- Actualiza la versión de caché del frontend para que el cambio aparezca al reiniciar.
