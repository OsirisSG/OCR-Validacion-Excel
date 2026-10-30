# OCR V14.4 — Giro automático y congruencia de códigos

## Correcciones principales

- El panel regional ya no parte siempre de 0°. La orientación recomendada por OCR se aplica al abrir las variantes.
- Se añade el botón **Usar giro automático** para volver a la recomendación después de una rotación manual.
- El mismo control queda disponible de forma consistente en las herramientas de corrección/selección de región, **Ajustar / dividir bloque**, mover/ajustar bloque y rotación general de imagen. Las vistas que comparten `HerramientasRegion` heredan el botón automáticamente; el editor de dimensiones también lo incorpora de forma explícita.
- La orientación se decide primero con las cuatro bases 0°/90°/180°/270° usando congruencia de código, antes del ajuste fino.
- Un fragmento corto de alta confianza (por ejemplo `1`) ya no desplaza automáticamente a un código completo y coherente (por ejemplo `S4054664`).
- Los códigos numéricos compactos y los alfanuméricos con uso coherente de mayúsculas/minúsculas reciben prioridad sobre fragmentos.
- Los alfanuméricos con mezcla irregular de mayúsculas/minúsculas reciben penalización, sin bloquear la revisión manual.
- El ajuste fino sólo se acepta si mantiene o mejora la congruencia; no puede sustituir un código completo por un fragmento sólo por subir la confianza.
- Las variantes guardadas por V14.3 que no contienen la nueva marca de recomendación se vuelven a calcular al abrir la región, por lo que no es necesario reprocesar todo el lote.

## Compatibilidad

- No cambia `.aprendizaje`.
- No cambia `.cache_ocr` ni los checkpoints existentes.
- No cambia el formato del Excel.
- El parche está pensado para aplicarse sobre V14.3.

## Verificación

- Suite específica de orientación/código: OK.
- JavaScript y Python: sintaxis válida.
- Suite global: 204 pruebas aprobadas y los mismos 8 fallos históricos por fixtures externos ausentes (`validacion_resultados.json` y banco externo del dashboard).
