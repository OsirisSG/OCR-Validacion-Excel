# V-Matrix V15.10.1 R3 — plan y corrección acumulada

Fecha: 14 de octubre de 2026.

## Objetivo inmediato

Corregir sin regresión los dos fallos reportados en la ejecución real:

1. `PublicacionExcelBloqueadaError` cuando la plantilla no contiene una celda de proyecto identificable, aunque el usuario ya eligió explícitamente el proyecto.
2. Imágenes que no cargan en el dashboard después de mover el lote/proyecto o cuando `dashboard.raiz_datos_permitida` conserva una ruta antigua.

Se conservan todas las correcciones acumuladas R2/H5: censura de tiempos no positivos/no finitos, aceptación provisional, protección de correcciones OCR obsoletas, `visor_precision.js`, matriz dinámica, trazabilidad y arranque.

## Diagnóstico

### Excel

La política previa exigía una celda de proyecto mapeable en la plantilla para considerar verificada la identidad. Esto podía bloquear una ejecución donde el proyecto había sido seleccionado expresamente por el usuario. La plantilla no debe convertirse en la fuente de identidad de la ejecución.

### Imágenes

`_resolver_raiz_datos()` usaba `raiz_datos_permitida OR datos['raiz']`. Si la primera existía en configuración pero ya no existía en disco, no probaba la segunda. Por ello una configuración obsoleta podía ocultar una raíz válida. Además, la reubicación de rutas persistidas era sensible a cambios de carpeta y, para rutas Windows, a diferencias de representación.

## Cambios R3

### R3-01 — publicación Excel con selección explícita

Nuevo `utilidades/identidad_excel_publicacion.py`.

- Primero ejecuta la política segura existente.
- Si existe una contradicción real/estructural, mantiene el bloqueo.
- Si el único problema es que la plantilla no trae una celda mapeable y el proyecto proviene de una selección explícita del usuario (`declarado_usuario` o equivalente explícito), permite publicar.
- Elimina únicamente los marcadores internos de borrador/advertencia generados por esa causa.
- Registra en el libro que la identidad provino de la selección explícita de la ejecución.
- No hace reemplazo global, no altera fórmulas y no toma el proyecto de la plantilla.

`reporte_bmg.py` usa esta política de publicación.

### R3-02 — resolución robusta de imágenes/videos

Nuevo `utilidades/rutas_recursos.py` y adaptación de `dashboard/backend/app.py`.

Orden de resolución de raíz:

1. `raiz_datos_permitida`, sólo si realmente existe;
2. `validacion_resultados.json -> raiz`, si existe;
3. reubicación local conservando estructura conocida;
4. ancestro común de archivos existentes que ya estén registrados en los resultados.

La seguridad no se relaja: `/api/imagen` y `/api/video` siguen exigiendo que la ruta solicitada pertenezca al inventario procesado.

La reubicación admite rutas relativas y lotes movidos, y normaliza de forma portable rutas Windows.

### R3-03 — fallback visual

`dashboard/frontend/app.js` intenta la vista original `/api/imagen` si falla una vista orientada/transformada. Si también falla, deja un mensaje de diagnóstico en el elemento en lugar de entrar en un bucle de carga.

`index.html` usa versión de caché `15.10.1-r3` para forzar la carga del JavaScript actualizado.

### R3-04 — pruebas

Nuevas regresiones:

- raíz configurada obsoleta + raíz real válida;
- rutas relativas;
- lote movido conservando sufijo;
- proyecto explícito + plantilla sin celda => publicable;
- contradicción real => sigue bloqueada;
- identidad legacy => no habilita el fallback;
- frontend con fallback de imagen y orden de scripts R3.

## Política de seguridad que NO cambia

- Una contradicción real de proyecto sigue bloqueando la publicación.
- La selección explícita del usuario no autoriza reemplazos masivos en la plantilla.
- `.aprendizaje`, `AGENTS.md`, `.agents/skills/*`, ROI manuales, modelos y datos originales no se borran ni se sustituyen por el instalador.
- Tiempos finales de apertura <=0, NaN/Infinity o censurados siguen sin ser publicables como confirmados o propuestas normales.
- El detector autónomo/IA permanece sujeto a validación con AVI reales y datos reservados antes de declarar precisión de producción.

## Aplicación

Con V-Matrix cerrado:

```powershell
python aplicar_parche_seguro.py "C:\Programas Base\OCR-Validacion-Excel-ocr-gpu-produccion"
python validar_parche_acumulado.py "C:\Programas Base\OCR-Validacion-Excel-ocr-gpu-produccion" --full
```

Después iniciar V-Matrix y usar `Ctrl+F5` una vez en el navegador.

## Qué validar en tu corrida real

1. Las dos actualizaciones pendientes de Excel deben salir de cola si la única causa era la ausencia de celda de proyecto.
2. Si persiste un bloqueo, el borrador contiene una contradicción real/estructural que debe revisarse; R3 no la oculta.
3. Abrir un caso con fotos: miniatura, visor principal, rotación y editor de regiones deben mostrar la imagen.
4. Mover/copiar un lote y volver a abrirlo: si la estructura relativa se conserva, las imágenes deben resolverse con la nueva raíz.
5. Confirmar que ES/EN se generan como archivos oficiales y no `.borrador_no_publicable.xlsx` cuando no existen contradicciones reales.
