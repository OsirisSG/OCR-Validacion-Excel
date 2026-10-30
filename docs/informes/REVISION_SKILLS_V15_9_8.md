# Revisión trazable por skill · V15.9.8 (correctiva N15)

**Fecha:** 2026-10-13. Una revisión por cada skill con archivos/diff
analizados, pruebas ejecutadas, hallazgos y decisiones. Base auditada:
`AUDITORIA_ESTRICTA_V_MATRIX_V15_9_7.md` (N15 crítica) e instrucciones
`CORRECCIONES_OBLIGATORIAS_V_MATRIX_V15_9_8.md`, incluidos sus 4 casos de
regresión incorporados verbatim al repo
(`pruebas/test_v15_9_8_auditoria_regresiones.py`). Alcance deliberadamente
acotado: contrato de identificación Excel en
`utilidades/identidad_excel.py`.

## 1. v-matrix-matrix-excel

- **Archivos analizados:** `utilidades/identidad_excel.py` (nuevo
  `_clasificar_par`, política estructural única compartida por las rutas
  declarada y complementaria; `buscar_celdas_proyecto` reclasificado como
  generador de CANDIDATOS; `_valores_ajenos_columna` excluye etiquetas de
  proyecto anidadas; bucle declarado de `aplicar_identidad_a_salida`
  reescrito; `mapear_pares_etiqueta_valor` refactorizado al clasificador
  común; comentario de `excluidas` actualizado), `plantilla_empresarial.py`
  y `reporte_bmg.py` (sin cambios; revisados para confirmar que
  `hojas_busqueda=[HOJA_CAPTURA,"Resumen"]` y
  `[HOJA_RESUMEN,HOJA_LISTA]` alimentan correctamente la nueva política y
  que la ruta P08 de borrador propaga el «sin campo verificable»).
- **Pruebas:** 4 casos literales del auditor en rojo (2 failed / 2 passed
  sobre `a079976`, mismos fallos que su log) → 4/4 verdes; 12 de ampliación
  (cabecera declarada 2 y 3 columnas con número/formato intactos releyendo
  el Excel temporal, ambigua con históricos, cabecera + par explícito
  válido, explícita en fila tabular, ES/EN/DE, ocultas/exentas, empresarial
  y BMG reales con hash de plantilla y propagación a borrador); 690 pruebas
  de V15.9.2-V15.9.7 verdes sin editar ninguna.
- **Hallazgos:** N15: dos rutas de mapeo con políticas distintas para la
  misma etiqueta. `ETIQUETAS_PROYECTO` acepta separador opcional, así que
  la ruta declarada trataba «Proyecto» desnudo como campo; la protección
  estructural N14 (`_evidencia_campo_unico`) sólo regía la complementaria y
  `excluidas` la apartaba precisamente de las etiquetas declaradas. El
  resultado era la destrucción de cabeceras (`Etapa`/`Caso` ⇒ nombre de
  proyecto) con `identidad_verificada=True`: éxito falso sobre columnas
  semánticamente corruptas.
- **Decisiones:** CENTRALIZAR la clasificación en `_clasificar_par` y
  ejecutarla ANTES de cualquier escritura en ambas rutas, de modo que
  «encontrar la etiqueta» nunca autorice a modificarla; cabecera tabular
  desnuda ⇒ omisión silenciosa con columnas intactas (no contradicción
  falsa: es una disposición legítima); ambigüedad ⇒ verificación de
  coherencia y bloqueo fail-closed; sin campo inequívoco ⇒ P08 emite
  borrador no publicable. `excluidas` se conserva pero sólo como registro
  de pares ya clasificados. Endurecimiento deliberado: la etiqueta
  explícita en fila tabular ahora también bloquea en la ruta declarada
  (antes sólo en la complementaria), por exigencia de política única.

## 2. v-matrix-safe-change

- **Archivos analizados:** diff V15.9.7→V15.9.8 (3 archivos: módulo de
  identidad + 2 archivos de pruebas nuevos; ningún test antiguo editado ni
  volteado), más revisión de no regresión en `dashboard/backend/app.py`,
  `pipeline.py`, generadores y frontend.
- **Pruebas:** suite completa 706/0/0 (3 corridas) + node 43/43; fresh
  clone de la base V15.8.1 con parche acumulado y clon de V15.9.7 con
  parche incremental (verificados en el paquete de entrega con reversión a
  0 diferencias); hashes de plantilla BMG real y empresarial verificados
  dentro de las pruebas nuevas.
- **Hallazgos:** incidencia de entorno (no del parche): la restauración del
  sandbox dejó los `.command` sin bit ejecutable en el árbol de trabajo
  mientras git seguía registrando 100755; el test C5 lo detectó, se
  restauró con `chmod 755` y quedó verde. Se documenta sin atribuirlo al
  parche, como exige la auditoría.
- **Decisiones:** cambio mínimo localizado en un solo módulo; metadatos
  compatibles (las cabeceras tabulares declaradas simplemente dejan de
  aparecer en `celdas`; los consumidores de `publicable`/`estado_identidad`
  no cambian); ninguna dependencia nueva.

## 3. v-matrix-video-zoom-ux

- **Archivos analizados:** `dashboard/frontend/app.js` e `i18n.js` (sin
  cambios en V15.9.8; revisión de no regresión de los estados
  confirmado/pendiente/bloqueado y de la respuesta de exportación).
- **Pruebas:** 43 contratos UI verdes, incluidos los de estados de
  exportación y sus traducciones ES/EN/DE.
- **Hallazgos/decisiones:** ninguno; los borradores nuevos por N15 viajan
  por el mismo contrato de V15.9.4/V15.9.6. Navegación real en navegador
  sigue pendiente de campo.

## 4. v-matrix-airbag-onset

- **Archivos analizados:** `video_airbag.py` y migración de consensos (sin
  cambios; revisión de no regresión).
- **Pruebas:** matriz de consenso N4 y migración N5 verdes dentro de la
  suite completa.
- **Hallazgos/decisiones:** política única de 3 cámaras y comprobación de
  `guardado` intactas; no se tocó el motor de apertura.

## 5. v-matrix-roi-supervision

- **Archivos analizados:** rutas de ROI/zoom/recálculo (sin cambios).
- **Pruebas:** tests de ROI, zoom, recálculo individual y matriz verdes en
  la suite completa.
- **Hallazgos/decisiones:** ninguno; aprendizaje ROI, detector y
  checkpoints conservados (el diff no los toca). Verificación visual con
  navegador real sigue pendiente de campo.

## 6. v-matrix-evaluation-lab

- **Archivos analizados:** benchmark sintético y laboratorio de evaluación
  (sin cambios).
- **Pruebas:** suite completa; todo sintético (`tmp_path`, fixtures y
  copias temporales de la plantilla BMG real), sin datos corporativos ni
  mezclar proyectos.
- **Hallazgos/decisiones:** los pendientes de campo (Excel representativos
  del entorno del usuario, AVI anotados con FPS reales, GPU/RTX,
  Windows/macOS, navegador real) se mantienen documentados sin declararlos
  aprobados; no se declara aptitud para producción en esta versión.
