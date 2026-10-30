# AGENTS.md — Instrucciones globales para agentes (V-Matrix OCR)

Reglas SIEMPRE activas para cualquier agente que trabaje en este repositorio.

## Reglas globales obligatorias

Dos skills se aplican en TODO cambio, sin excepción:

1. **Safe Change** — `.agents/skills/v-matrix-safe-change/SKILL.md`
   Integridad primero: nunca borrar/sobrescribir `.aprendizaje/`, bases de
   datos, checkpoints, `validacion.json`, correcciones humanas ni videos
   originales; compatibilidad con JSON antiguos; rollback documentado; sin
   dependencias de red en producción.
2. **Evaluation Lab** — `.agents/skills/v-matrix-evaluation-lab/SKILL.md`
   Puerta de publicación: `python -m pytest pruebas/` y
   `node --test pruebas/*.cjs` ejecutados y en verde (única falla tolerada:
   `test_dashboard.py::test_estado_config_y_frontend`, conocida de entorno);
   cada bug corregido aporta su test de reproducción; no aprobar con fallos
   críticos reproducibles.

## Skills por área (leer antes de tocar el área)

| Área | Skill |
|---|---|
| Detección/consenso de apertura | `.agents/skills/v-matrix-airbag-onset/SKILL.md` |
| ROI y aprendizaje | `.agents/skills/v-matrix-roi-supervision/SKILL.md` |
| Visor, zoom, idioma, caché UI | `.agents/skills/v-matrix-video-zoom-ux/SKILL.md` |
| Matriz dashboard/Excel | `.agents/skills/v-matrix-matrix-excel/SKILL.md` |

Detalles de uso, límites e integración incremental: `.agents/AGENTS.md`.
Evidencia de aplicación: `docs/informes/REVISION_SKILLS_V15_9_9.md` y
`docs/informes/REVISION_SKILLS_V15_9_10.md` (resultados de suite en
`docs/informes/RESULTADOS_PRUEBAS_V15_9_10.md`).

## Estructura formal de las tablas Excel (V15.9.10, N17)

Antes de tratar una etiqueta de proyecto como campo editable se inspecciona
la ESTRUCTURA formal del libro: `ws.tables` (`Table.ref`,
`headerRowCount != 0`) y `ws.auto_filter.ref`. Una celda en la fila de
cabecera de una tabla registrada o de un autofiltro NUNCA es campo de
proyecto, sin importar su texto, idioma, posición o número de filas de
datos: se omite y la tabla conserva `ref`, nombres de columna y formato.
Un diccionario de palabras no sustituye a esa comprobación.

Sin objeto `Table` ni contrato explícito, un par desnudo `Proyecto | valor`
es AMBIGUO: sólo se escribe cuando el contiguo tiene evidencia positiva de
ser nombre de proyecto (coincide con la identidad declarada o empieza por
una mención de proyecto). En caso contrario no se escribe por suposición:
se registra contradicción estructural, `publicable=False` y borrador no
publicable. Un campo explícito con separador sí es contrato y se mapea.


## Identidad de proyecto (V15.9.2, C7)

El proyecto de un lote lo declara el usuario al pulsar «Procesar carpeta».
La plantilla Excel, la carpeta o la corrida anterior NUNCA fijan el proyecto
por sí solas; pueden sugerirlo marcado como pendiente de aceptación.
