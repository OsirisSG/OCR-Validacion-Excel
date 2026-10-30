# Revisión trazable por skill · V15.9.3 (correctiva de auditoría estricta)

**Fecha:** 2026-10-12. Una revisión por cada skill con archivos/diff
analizados, pruebas ejecutadas, hallazgos y decisiones. Base auditada:
`AUDITORIA_ESTRICTA_V_MATRIX_V15_9_2.md` (CRIT-01..04, ALTA-05, MEDIA-06) e
instrucciones `CORRECCIONES_OBLIGATORIAS_V_MATRIX_V15_9_3.md`.

## 1. v-matrix-safe-change

- **Archivos analizados:** `utilidades/proyectos.py` (`_leer`, nuevo
  `RegistroProyectosCorruptoError`, nueva `recuperar_registro`),
  `dashboard/backend/app.py` (`/api/proyectos`, `iniciar_pipeline`),
  `plantilla_empresarial.py` (nuevo `_guardar_atomico`), `reporte_bmg.py`
  (`_guardar_atomico` existente reutilizado para el borrador).
- **Pruebas:** CRIT-04 completo y ALTA-05 de `test_v15_9_3_criticos.py`
  (bytes intactos tras intento de escritura, respaldo SHA-256, permisos 000,
  endpoints 503, fallo inyectado a mitad de guardado con salida previa
  intacta y sin temporales huérfanos); regresiones C3/C4/P10 en verde.
- **Hallazgos:** CRIT-04 violaba «fallar cerrado ante datos corruptos»: el
  registro ilegible se reiniciaba en memoria y la siguiente escritura borraba
  los proyectos previos; ALTA-05 violaba «nunca reemplazar una salida válida
  con una escritura parcial».
- **Decisiones:** `_leer` propaga error en vez de fingir registro vacío (cero
  bytes tocados: el fallo ocurre ANTES de cualquier escritura); recuperación
  sólo explícita y con respaldo verificado byte a byte; guardado atómico
  temporal+validación+`os.replace` (la validación reabre el temporal: hojas
  presentes y archivo no vacío); el generador NO lanza excepción por identidad
  no verificada (abortaría la fase 3 y perdería `_persistir_validacion`):
  devuelve la ruta del borrador.

## 2. v-matrix-airbag-onset

- **Archivos analizados:** `video_airbag.py` (`consenso_valido` rama legada,
  `consenso_videos`: `alerta_sin_clasificar`, motivos, sello del detector),
  `dashboard/backend/app.py` (`_migrar_consensos_video` rama sin videos, nuevo
  `_degradar_campos_consenso_legacy`).
- **Pruebas:** CRIT-01/CRIT-02 de `test_v15_9_3_criticos.py` (repro literal de
  la auditoría en ambos casos), `test_compatibilidad_consenso_historico_v1581`
  y `test_consenso_*` actualizados, regresiones B1/B2/C1/C2 de V15.9.1-2 en
  verde (consenso 3/4 limpio confirmado, 2/2 confirmado, manual manda, causa
  grave bloquea, informativa explícita no bloquea).
- **Hallazgos:** CRIT-01: la rama legacy degradaba el umbral a 1 cuando
  `total_principales` faltaba (`int(None or 0)=0` ⇒ `requerido=1`). CRIT-02:
  exigir motivo textual para bloquear convertía la ausencia de motivo en
  revisión informativa de facto y producía el consolidado contradictorio
  (motivo «quedó marcada para revisión» + `requiere_revision=False` +
  publicación).
- **Decisiones:** metadata incompleta falla cerrado; sin videos originales la
  migración degrada a `pendiente_revision` conservando medida y evidencia
  (`video_apertura_anterior`, sello de algoritmo para no re-juzgar en cada
  carga); legados con respaldo completo y sin videos sólo se sellan (sin
  elevar estado); `alerta_sin_clasificar` ya no requiere motivo: sólo
  `revision_informativa=True` explícita y auditable excepciona (el detector
  actual la sella por diseño; los items legados sin sello se recuperan
  reanalizando).

## 3. v-matrix-matrix-excel

- **Archivos analizados:** `utilidades/identidad_excel.py`
  (`aplicar_identidad_a_salida` con nuevo `publicable`,
  `marcar_borrador_no_publicable`, textos ES/EN/DE), `plantilla_empresarial.py`
  y `reporte_bmg.py` (puerta de publicación), destinos de borrador.
- **Pruebas:** CRIT-03 de `test_v15_9_3_criticos.py` (empresarial con salida
  vigente previa que debe quedar intacta, BMG con la plantilla real
  `plantillas/reporte_bmg_1st_2st.xlsx`, legacy sin bloqueo, hashes de
  plantilla byte-idénticos), `test_c7_p08_..._bloquea_publicacion` reescrita,
  P01/P02/P07 y paridad Excel↔dashboard en verde.
- **Hallazgos:** CRIT-03: ambos generadores ignoraban `identidad_verificada`
  y guardaban de todos modos; la prueba P08 de V15.9.2 exigía precisamente que
  el generador creara la salida bloqueada, así que la suite no certificaba el
  bloqueo.
- **Decisiones:** `publicable = identidad_verificada OR origen legacy`
  (`nombre_carpeta_legacy`/`sin_datos` conservan el flujo P11 con advertencia);
  con `publicable=False` se guarda `*.borrador_no_publicable.xlsx` en la misma
  carpeta (ubicación diferenciada por nombre), el destino oficial no se crea ni
  se reemplaza, el marcador visible se escribe en la hoja resumen en los tres
  idiomas y la plantilla original jamás se toca (sólo celdas de metadata
  identificadas en la copia de salida, nunca buscar-y-reemplazar global).

## 4. v-matrix-roi-supervision

- **Archivos analizados:** sin cambios de ROI en esta correctiva; se revisó
  que el fail-closed de consensos no alterara zonas aprendidas ni reversiones
  (`aprendizaje_video_airbag.py`, `revertir_zona_video`).
- **Pruebas:** regresiones C3/C4 de `test_v15_9_2_correcciones_c1_c7.py`
  (rollback con comparación de bytes, 422/500/503) y de
  `test_editor_zonas`/`test_v15_9_apertura_zoom_ui.cjs` en verde.
- **Hallazgos:** ninguno nuevo; los contratos V15.9.2 siguen vigentes.
- **Decisiones:** no tocar el flujo ROI en esta versión (fuera del alcance
  auditado); la degradación CRIT-01 afecta sólo a `opening_time_ms` y nunca a
  zonas/ROI.

## 5. v-matrix-evaluation-lab

- **Archivos analizados:** `pruebas/test_v15_9_3_criticos.py` (nuevo, 18
  casos), `pruebas/test_dashboard.py` (fixture hermético `estado_con_datos`),
  `pruebas/test_v14_sop_recuperacion.py` y `pruebas/test_maximos_video.py`
  (determinismo), pruebas V15.9.2 invertidas/actualizadas.
- **Pruebas:** puerta rojo→verde ejecutada de verdad: RED `11 failed / 7
  passed / 1 skipped` sobre `226e028` ANTES de cualquier cambio de código;
  GREEN suite completa `574 passed / 0 failed / 0 skipped` repetida 5 veces +
  node 38/38 (ver `RESULTADOS_PRUEBAS_V15_9_3.md`).
- **Hallazgos:** la «falla de entorno» declarada en V15.9.2 era evitable
  (dependencia de un artefacto no versionado); dos pruebas eran lábiles bajo
  carga por sondas de presión reales y granularidad de `ctime_ns`.
- **Decisiones:** cero fallas declaradas y cero skips; nada de datos reales en
  pruebas (sólo fixtures sintéticos en `tmp_path`); las correcciones de
  determinismo no debilitan contratos (el backpressure y la detección de
  cambio intermedio se siguen ejercitando); los cambios de pruebas existentes
  son sólo los exigidos por la auditoría y están documentados uno por uno.

## 6. v-matrix-video-zoom-ux

- **Archivos analizados:** `dashboard/frontend/app.js` (sin cambios en esta
  correctiva); se verificó que la ruta devuelta por los generadores (incluido
  el borrador) es la que el backend expone en `archivo_excel_parcial` /
  `archivos_excel`, visible para el operador.
- **Pruebas:** node `38/38` (zoom, rueda, doble clic, ajustar a pantalla,
  diálogo previo de dos bloques, guardia sin proyecto, i18n ES/EN/DE);
  `/api/estado` y `/api/proyectos` con registro corrupto devuelven 503 con
  mensaje visible (no lista vacía fingida).
- **Hallazgos:** ninguno nuevo en UI; el nombre `borrador_no_publicable` en la
  ruta expuesta hace visible el bloqueo sin diálogo adicional.
- **Decisiones:** no modificar el frontend en una correctiva de contrato; el
  marcador de borrador vive en la hoja Resumen (auditable en el propio Excel).

## Evidencia de ejecución

- RED: `11 failed, 7 passed, 1 skipped` (log capturado antes de corregir).
- GREEN: `574 passed, 1 warning` ×5 corridas consecutivas; críticos `18
  passed`; node `# tests 38 / # pass 38 / # fail 0`.
- MEDIA-06 (empaquetado): `SHA256SUMS.txt` con rutas relativas a la raíz del
  ZIP verificables con `sha256sum -c` desde la carpeta extraída; los
  `.command` son byte-idénticos a la base (no aparecen en el diff) y se
  documenta en el manifiesto.
