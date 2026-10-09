# OCR V14.3 — persistencia, NoneType y reanudación completa

Fecha: 2026-09-23

## Objetivo

Este hotfix acumula las correcciones V14.2 y añade un blindaje adicional para
resultados OCR históricos/parciales donde colecciones opcionales pueden existir
con valor `None`.

## Correcciones incluidas

1. **Excel / `NoneType`**
   - La exportación normaliza colecciones opcionales conocidas antes de aplicar
     aprendizaje, descartes y correcciones.
   - Se mantiene validación explícita para datos estructuralmente inválidos: no
     se ocultan errores reales con `try/except` genérico.
   - La cola conserva las revisiones pendientes, traceback y tipo de error.

2. **Recuperación automática de la cola Excel**
   - Una cola que queda con 3 (o más) actualizaciones pendientes por un fallo
     temporal o por un error corregido en código se reabre al iniciar el
     dashboard y vuelve a intentar la instantánea pendiente.
   - Las revisiones pendientes se consolidan en una sola regeneración cuando
     pertenecen al mismo estado actual.
   - No se incluye ni reemplaza `.cache_ocr/cola_excel.sqlite3` en este paquete.

3. **Reanudación exhaustiva**
   - Al recuperar un checkpoint, `casos_omitidos` se reconstruye a partir de
     resultados realmente terminados.
   - Los casos `detectada`, `inventariada`, `cancelada`, `pendiente`, etc. no se
     consideran completados.
   - Se ignora la lista `casos_omitidos` potencialmente contaminada creada por
     V14.1, por lo que un checkpoint ya afectado puede recuperarse sin borrarlo.

4. **Blindaje adicional de aprendizaje y validación**
   - `tokens=None` y `lineas_texto=None` ya no rompen el registro incremental
     del aprendizaje ni el cierre de una ejecución.
   - Los historiales y resultados persistidos opcionales se leen de forma segura
     cuando una versión anterior dejó un campo opcional en `None`.
   - Se endurecieron rutas de edición del dashboard que combinan tokens y líneas.

5. **Pausa / tiempo transcurrido**
   - Se conserva el comportamiento V14.1: el tiempo se congela cuando el worker
     entra realmente en `pausado` y continúa desde el mismo valor al reanudar.

## Aplicación recomendada

1. Cierra completamente el dashboard.
2. Haz una copia de seguridad del proyecto si deseas conservar una instantánea.
3. Copia los archivos del parche encima del proyecto y acepta reemplazar código.
4. **No borres** `.aprendizaje`.
5. **No borres** `.cache_ocr`.
6. **No borres** el checkpoint del pipeline.
7. Inicia el dashboard. La cola Excel debe reintentar automáticamente lo pendiente.
8. Usa `Reanudar avance guardado`; V14.3 recalculará qué casos faltan.

## Si el Excel vuelve a fallar

Conserva la cola y comparte la bitácora generada en `errores/`. El dashboard y la
cola ya guardan el traceback para poder identificar el archivo y la línea exactos.
No borres las actualizaciones pendientes como primera medida.
