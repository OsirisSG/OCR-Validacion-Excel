# Revisión trazable por skill · V15.9.5 (correctiva N7-N9)

**Fecha:** 2026-10-12. Una revisión por cada skill con archivos/diff
analizados, pruebas ejecutadas, hallazgos y decisiones. Base auditada:
`AUDITORIA_ESTRICTA_V_MATRIX_V15_9_4.md` (N7 crítica, N8 media-alta, N9 alta)
e instrucciones `CORRECCIONES_OBLIGATORIAS_V_MATRIX_V15_9_5.md`, incluidos sus
3 casos de regresión incorporados verbatim al repo. Alcance deliberadamente
acotado por la auditoría: contrato de identidad Excel; NO se reescriben el
motor de apertura ni las seis skills.

## 1. v-matrix-matrix-excel

- **Archivos analizados:** `utilidades/identidad_excel.py` (nuevo contrato
  `hojas_del_entregable`, `_analizar_referencia` con segmentos de
  nombre/metadata, `_segmento_es_metadato`, `_token_es_metadato`, escaneo de
  cabeceras/pies `_textos_cabecera_pie`, `escribir_bloque_identidad` con
  `decision_usuario_confirmada`/`estado_identidad`, política de publicación
  en `aplicar_identidad_a_salida`), `reporte_bmg.py` (exención documentada de
  la hoja de diccionario), `plantilla_empresarial.py` (puerta de borrador sin
  cambios), plantilla BMG real inspeccionada hoja por hoja y cabecera por
  cabecera.
- **Pruebas:** N7 (hoja visible no declarada, hoja oculta, exención
  documentada con y sin contrato, cabecera Y pie, BMG real hoja `Rangos` +
  control limpio, celda etiquetada en hoja no mapeada), N8 (año ES/EN/DE,
  semana/Week/Woche, versión, fecha, revisión, nombre compuesto, ID distinto
  del nombre visible, A vs AB y AB vs A, referencia ambigua fail-closed con
  explicación), N9 (los cuatro `estado_identidad`, bloque visible con
  verificación y decisión, plantilla sin celda identificable); 3 casos
  literales del auditor en rojo→verde; 23 ampliaciones V15.9.4 y 7 regresiones
  V15.9.4 verdes sin tocar.
- **Hallazgos:** N7: el escaneo se limitaba a `hojas_busqueda` declaradas por
  el generador — una hoja visible adicional con identidad de otro proyecto se
  publicaba; las cabeceras/pies no se examinaban. N8: el análisis por tokens
  trataba cualquier resto del título («Año 2026») como nombre de otro
  proyecto — falsos positivos que bloqueaban reportes correctos. N9:
  `identidad_verificada = bool(mapeadas) or bool(sin_asignar)` convertía la
  decisión «Sin asignar» en identidad confirmada, contradiciendo el requisito
  N2 de la auditoría anterior.
- **Decisiones:** el entregable son TODAS las hojas visibles (más las
  declaradas aunque estuvieran ocultas), con excepción explícita, documentada
  en el bloque y decidida por el generador (nunca por la plantilla); el texto
  tras una mención de proyecto se analiza por segmentos separando nombre de
  metadatos de prueba (contrato general ES/EN/DE, no excepción ad-hoc); lo no
  resoluble con certeza bloquea con explicación; `identidad_verificada` exige
  celda mapeada + no «Sin asignar» + sin contradicciones; la publicación
  pendiente (P02) es una rama explícita de política con estado diferenciado;
  ningún texto existente se reemplaza nunca.

## 2. v-matrix-safe-change

- **Archivos analizados:** diff completo V15.9.4→V15.9.5 (7 archivos de
  código + 3 de pruebas), política de publicación y estados en
  `dashboard/backend/app.py` y `pipeline.py`.
- **Pruebas:** suite completa 631/0/0 (3 corridas) + node 43/43; regresiones
  V15.9.2 (C1-C7), V15.9.3 (CRIT-01..04/ALTA-05) y V15.9.4 (N1-N6) verdes sin
  modificar sus archivos de pruebas; fresh clone base+parche acumulado con
  suite verde y reversión `git apply -R` ensayada.
- **Hallazgos:** ningún cambio en rutas de persistencia, consenso, cola o
  reemplazo atómico; el riesgo de regresión estaba en el control BMG limpio
  (falso positivo del diccionario generado), resuelto por contrato de
  exención y no debilitando el escáner.
- **Decisiones:** preservar N1-N6 intactos (condición 5 de aprobación);
  cambios aditivos en API (`identidad_verificada`,
  `pendiente_sin_asignar`, `estado_identidad`, `estado_publicacion =
  "pendiente_publicada"`) sin romper consumidores existentes; exención de
  hojas sólo por código del generador, nunca por contenido de la plantilla.

## 3. v-matrix-video-zoom-ux

- **Archivos analizados:** `dashboard/frontend/app.js` (tarjeta exportadora),
  `dashboard/frontend/i18n.js` (textos ES/EN/DE).
- **Pruebas:** `pruebas/test_v15_9_5_estados_ui.cjs` (2 contratos: aviso
  PENDIENTE diferenciado con claves `pendiente_publicada`/
  `pendiente_sin_asignar` y traducciones EN/DE); 41 contratos UI anteriores
  verdes (43/43 en total).
- **Hallazgos:** la UI sólo distinguía éxito/bloqueado; un Excel pendiente
  «Sin asignar» se mostraba como éxito normal sin matiz.
- **Decisiones:** tercer estado visible (aviso PENDIENTE informativo,
  separado del éxito y del bloqueo N6), con textos ES/EN/DE; el aviso de
  bloqueado y la descarga de borrador de V15.9.4 se conservan sin cambios.

## 4. v-matrix-airbag-onset

- **Archivos analizados:** `video_airbag.py` y migración de consensos (sin
  cambios en V15.9.5; revisión de no-regresión).
- **Pruebas:** matriz de consenso N4 (3/4, 4/4, 3/3, 2/4, 2/2, 1/1, manual,
  revisión obligatoria) y migración N5 verdes dentro de la suite completa.
- **Hallazgos/decisiones:** política única de 3 cámaras y comprobación de
  `guardado` intactas; la auditoría pidió explícitamente NO reescribir el
  motor de apertura — no se tocó.

## 5. v-matrix-roi-supervision

- **Archivos analizados:** rutas de ROI/zoom/recálculo (sin cambios; revisión
  de no-regresión).
- **Pruebas:** tests de ROI, zoom, recálculo individual y matriz verdes en la
  suite completa; navegación por contrato (`dashboard/frontend/navegacion.py`)
  sin cambios.
- **Hallazgos/decisiones:** ninguno; la verificación visual en navegador real
  sigue siendo pendiente de campo declarado.

## 6. v-matrix-evaluation-lab

- **Archivos analizados:** benchmark sintético y laboratorio de evaluación
  (sin cambios).
- **Pruebas:** suite completa; ningún dato corporativo real en pruebas (todo
  sintético con `tmp_path` y fixtures).
- **Hallazgos/decisiones:** los pendientes de campo (AVI anotados, FPS
  reales, GPU, error temporal por fotograma) se mantienen documentados sin
  declararlos aprobados.
