# Revisión trazable por skill · V15.9.7 (correctiva N13-N14)

**Fecha:** 2026-10-13. Una revisión por cada skill con archivos/diff
analizados, pruebas ejecutadas, hallazgos y decisiones. Base auditada:
`AUDITORIA_ESTRICTA_V_MATRIX_V15_9_6.md` (N13 crítica, N14 alta) e
instrucciones `CORRECCIONES_OBLIGATORIAS_V_MATRIX_V15_9_7.md`, incluidos
sus 4 casos de regresión incorporados verbatim al repo
(`pruebas/test_v15_9_7_auditoria_regresiones.py`). Alcance deliberadamente
acotado: contrato de identificación Excel en
`utilidades/identidad_excel.py`.

## 1. v-matrix-matrix-excel

- **Archivos analizados:** `utilidades/identidad_excel.py` (nuevas
  `_ETIQUETA_DESNUDA`, `_evidencia_campo_unico`, `_es_cabecera_reconocible`,
  `_coherente_con_identidad`, `_valores_ajenos_columna`,
  `_motivo_no_editable`, `_registro_campo_no_editable`; `_celda_valor_editable`
  ampliada a la celda inicial de rangos combinados;
  `mapear_pares_etiqueta_valor` extendida a etiquetas desnudas con evidencia
  estructural; bucle declarado de `aplicar_identidad_a_salida` reescrito con
  validación previa a la escritura), `plantilla_empresarial.py` y
  `reporte_bmg.py` (sin cambios; revisados para confirmar que la propagación
  a borrador y las exenciones alimentan correctamente la nueva política),
  plantilla BMG real inspeccionada (`Rangos`, `Übersicht Standversuche`).
- **Pruebas:** 4 casos literales del auditor en rojo (4 failed sobre
  `9bd190b`) → verde; 15 de ampliación N13/N14 (fórmula con referencias
  externas, segundo par editable, combinada inicial, empresarial y BMG
  reales en copias temporales con hash de plantilla y propagación a
  borrador, pares desnudos abreviados multihoja, cabecera tabular intacta,
  ambigüedad con datos ajenos bloqueada, tabla de dos columnas con
  cabecera reconocible, ocultas/exentas, fórmula/combinada en campo
  desnudo, ES/EN/DE, migración A→B); 671 pruebas de V15.9.2-V15.9.6 verdes
  sin editar ninguna.
- **Hallazgos:** N13: la protección de editabilidad de V15.9.6
  (`_celda_valor_editable`) existía y funcionaba, pero sólo se aplicaba al
  mapeo complementario; el bucle declarado escribía a ciegas
  (`libro[hoja][celda] = visible`), destruyendo fórmulas/números y lanzando
  `AttributeError` con `MergedCell`. N14: la regla «sólo etiquetas
  explícitas con separador» dejaba un punto ciego doble: el par desnudo
  «Proyecto»/«A» no lo veía el mapeo estructural ni el escáner textual (el
  valor corto no contiene la palabra clave), así que se publicaba en
  silencio con un valor ajeno visible.
- **Decisiones:** política ÚNICA de escritura segura para declaradas y
  complementarias (validar antes de escribir; bloqueo estructural con
  hoja/celda/motivo; celda no validada fuera de `identidad_verificada`);
  la etiqueta desnuda sólo se mapea con evidencia estructural segura de
  campo único (fila ≤2 celdas sin datos debajo), moderando documentadamente
  la prohibición de V15.9.6 sin perder su protección: ≥3 celdas siguen
  siendo cabecera tabular intocable y la estructura ambigua se verifica
  contra la identidad con bloqueo fail-closed ante cualquier valor ajeno;
  las cabeceras de metadatos reconocibles (Etapa/Case/Datum…) permiten
  distinguir tabla de dos columnas de campo único. Ningún reemplazo masivo
  de columnas de casos ni de históricos.

## 2. v-matrix-safe-change

- **Archivos analizados:** diff V15.9.6→V15.9.7 (3 archivos: módulo de
  identidad + 2 archivos de pruebas nuevos; ningún test antiguo editado ni
  volteado en esta versión), más revisión de no regresión en
  `dashboard/backend/app.py`, `pipeline.py`, generadores y frontend.
- **Pruebas:** suite completa 690/0/0 (3 corridas) + node 43/43; fresh
  clone de la base V15.8.1 con parche acumulado y clon de V15.9.6 con
  parche incremental (verificados en el paquete de entrega con reversión a
  0 diferencias); hashes de plantilla BMG real y empresarial verificados
  dentro de las pruebas nuevas; muestra Excel antes/después con plantillas
  intactas.
- **Hallazgos:** el endurecimiento de `_celda_valor_editable` (celda
  inicial de rango combinado ya no es editable) es más estricto que el
  contrato de V15.9.6, pero ninguna prueba ni fixture existente dependía
  de escribir en una celda inicial combinada: suite completa verde sin
  cambios en pruebas antiguas.
- **Decisiones:** cambio mínimo y localizado en un solo módulo; API y
  metadatos compatibles (se añaden `nota` en complementarias y bloqueos
  estructurales declarados; consumidores sin cambios); la ruta de borrador
  oficial y la respuesta de exportación de V15.9.4/V15.9.6 se conservan.

## 3. v-matrix-video-zoom-ux

- **Archivos analizados:** `dashboard/frontend/app.js` e `i18n.js` (sin
  cambios en V15.9.7; revisión de no regresión de los estados
  confirmado/pendiente/bloqueado y de la respuesta de exportación).
- **Pruebas:** 43 contratos UI verdes, incluidos los de estados de
  exportación (bloqueada y pendiente) y sus traducciones ES/EN/DE.
- **Hallazgos/decisiones:** ninguno; los bloqueos estructurales nuevos
  viajan por el mismo contrato `publicable`/`estado_publicacion` ya
  propagado al frontend. Navegación real en navegador sigue pendiente de
  campo.

## 4. v-matrix-airbag-onset

- **Archivos analizados:** `video_airbag.py` y migración de consensos (sin
  cambios; revisión de no regresión).
- **Pruebas:** matriz de consenso N4 y migración N5 verdes dentro de la
  suite completa.
- **Hallazgos/decisiones:** política única de 3 cámaras y comprobación de
  `guardado` intactas; la auditoría pidió no reescribir el motor de
  apertura y no se tocó.

## 5. v-matrix-roi-supervision

- **Archivos analizados:** rutas de ROI/zoom/recálculo (sin cambios).
- **Pruebas:** tests de ROI, zoom, recálculo individual y matriz verdes en
  la suite completa.
- **Hallazgos/decisiones:** ninguno; verificación visual con navegador
  real sigue declarada como pendiente de campo.

## 6. v-matrix-evaluation-lab

- **Archivos analizados:** benchmark sintético y laboratorio de evaluación
  (sin cambios).
- **Pruebas:** suite completa; todo sintético (`tmp_path`, fixtures y
  copias temporales de la plantilla BMG real), sin datos corporativos.
- **Hallazgos/decisiones:** los pendientes de campo (AVI anotados con FPS
  reales, GPU/RTX, Windows/macOS, navegador real) se mantienen documentados
  sin declararlos aprobados; no se declara aptitud para producción en esta
  versión.
