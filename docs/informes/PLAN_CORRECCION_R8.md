# Plan de corrección V15.10.1 R8 — encabezados OCR e idioma

R8 es acumulativa sobre R7 y mantiene sus correcciones de frontend, matriz, Excel, identidad de proyecto, imágenes y apertura.

## Objetivo R8

1. Recuperar términos técnicos institucionales observados en OCR (`VWxxx/x`, `xNN`, `PAB`, `BMG`, `COP BFA`) sin convertirlos en identidad de proyecto.
2. Mantener `nombre_proyecto/project_id` exclusivamente desde la selección explícita del usuario.
3. Localizar en ES/EN/DE los textos de presentación del encabezado del resumen y los grupos de la tabla detallada.
4. Evitar mezclas de alemán/inglés/español en una exportación de un solo idioma.
5. Mantener sin cambios la lógica de semáforo, consenso, tiempos inválidos, imágenes y aceptación provisional de R7.

## Contrato

- OCR aporta términos técnicos observados; no sustituye el proyecto elegido.
- Si OCR no aporta un término institucional, se usa fallback de plantilla trazable.
- Las hojas institucionales conservan sus nombres para no romper referencias.
- El encabezado y la tabla cambian de presentación según el idioma de exportación.
- B3/B4 de `Übersicht Standversuche` incluyen comentarios de trazabilidad del origen OCR/fallback.

## Validación

- Pruebas específicas R8: extracción OCR + ES/EN/DE.
- Regresión crítica R7/H5/matriz/Excel/identidad/OCR.
- Verificación JS del visor, fallback de imágenes, semáforo y lupa.
