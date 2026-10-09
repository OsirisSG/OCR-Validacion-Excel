# OCR V14.15.1 — Hotfix de traducción del listado

Fecha: 2026-09-28  
Base: V14.15

## Correcciones

Se corrigen los últimos textos dinámicos del listado que podían permanecer en español con EN/DE activos:

- placeholder de búsqueda por identificador/nomenclatura;
- métricas de progreso: `con texto`, `descartadas`, `campos`, `faltantes`, `conflictos`;
- estados internos visibles: `estructura_valida`, `estructura_incompleta`, `con_conflictos`, `detectada`, `procesada`, `procesada_con_advertencias`, `completado`;
- el mismo desglose de progreso en el detalle del caso.

Los valores numéricos y los identificadores empresariales no se traducen.

## Compatibilidad

No cambia backend, aprendizaje, Excel, caché OCR, checkpoints ni lógica de revisión. Es un hotfix de frontend/i18n sobre V14.15.

## Validación

- `node --check dashboard/frontend/app.js`: OK.
- `node --check dashboard/frontend/i18n.js`: OK.
- 20/20 pruebas JavaScript: OK.
- `python -m py_compile` de módulos principales: OK.
- Suite Python: 238 aprobadas / 8 fallos históricos por fixtures externos ausentes, sin regresiones nuevas.
