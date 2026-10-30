# Revisión trazable por skill · V15.9.1 (r1)

**Fecha:** 2026-10-12. Cumple la condición 2 de la puerta de skills de la
auditoría estricta: una revisión trazable por cada skill, con archivos/diff
analizados, pruebas ejecutadas, hallazgos y decisiones. Las skills viven en
`.agents/skills/` y fueron aplicadas DURANTE la preparación de este parche.

## 1. v-matrix-safe-change

- **Archivos analizados:** `video_airbag.py` (`consenso_valido`,
  `consenso_videos`), `dashboard/backend/app.py` (`_aplicar_consenso_video_a_fila`,
  `_estado_apertura_detalle`, `_resolver_instantanea_para_ejecucion`),
  `pipeline.py` (persistencia de Fase 3), `utilidades/persistencia.py`.
- **Pruebas:** `pruebas/test_v15_9_1_consenso_publicacion.py` (incluye
  compatibilidad con consensos históricos sin `estado_consenso` e ítems de caché
  antiguos), `pruebas/test_v15_9_1_compatibilidad_y_preferencias.py` (A5/A6/A7),
  suite completa 504 OK + 1 falla de entorno conocida.
- **Hallazgos:** el diff V15.9.0 publicaba propuestas como confirmadas (B1) y
  borraba señales graves al consolidar (B2); el perfil legacy perdía la
  instantánea de criterios (A6); el respaldo legacy de `opening_time_ms` se
  había eliminado (A5).
- **Decisiones:** nada se publica sin `confirmado`; la escritura de validación
  es atómica y en todos los perfiles (`_persistir_validacion`); rollback
  documentado (`git apply -R cambios_V15_9_1.patch`); `.aprendizaje` solo crece
  (historiales reversibles, nunca borrado).

## 2. v-matrix-airbag-onset

- **Archivos analizados:** `video_airbag.py` (detector dos momentos,
  `normalizar_item_temporal_video`, `resolver_tiempo_metadata`, bloque
  `cv2.phaseCorrelate`), `pruebas/test_v15_9_detector_dos_momentos.py`.
- **Pruebas:** `pruebas/test_v15_9_1_consenso_publicacion.py` (FPS no
  corroborados, overlay dudoso con reloj contradictorio y con error de lectura,
  ausencia de reloj no bloqueante, precedencia manual); benchmark sintético con
  `utilidades/benchmark_detector.py` (~31 fps; phaseCorrelate media 4.14 ms,
  p95 5.45 ms por cuadro; evento detectado en el frame esperado).
- **Hallazgos:** la advertencia genérica del detector heurístico no debe
  bloquear un consenso limpio, pero las causas graves sí (distinción B2);
  «overlay dudoso» exige señal POSITIVA (error o contradicción), no la simple
  ausencia de reloj legible — sin ese ajuste, el 3-de-4 nunca confirmaría con
  videos sin Rec…fps visible.
- **Decisiones:** `_causas_revision_graves` implementa la distinción; la
  exactitud con videos reales sigue marcada como pendiente
  (`validado_con_videos_reales=False`).

## 3. v-matrix-roi-supervision

- **Archivos analizados:** `aprendizaje_video_airbag.py`
  (`guardar_zona_aprendida`, `seleccionar_zona_aprendida`,
  `_zona_manual_bloqueada`), `dashboard/backend/app.py`
  (`aprender_zona_video`, nuevo `revertir_zona_video`),
  `dashboard/frontend/app.js` (`TarjetaVideoAirbag`).
- **Pruebas:** `pruebas/test_v15_9_1_roi_reversion.py` (historial persistente
  y acotado, reversión reversible, selección por índice, errores sin historial,
  exposición de `historial_roi` al frontend, existencia del endpoint).
- **Hallazgos:** la UI anunciaba «Revertir» sin flujo real (A1): no existía
  operación para restaurar una ROI aceptada/guardada.
- **Decisiones:** `historial_roi` (máx. 8) dentro del perfil del video,
  endpoint `POST /api/video/zona-revertir` que reanaliza y actualiza consenso/
  JSON/Excel, overlay punteado «ROI anterior» + comparación numérica antes de
  decidir; la reversión guarda la ROI desplazada en el historial.

## 4. v-matrix-video-zoom-ux

- **Archivos analizados:** `dashboard/frontend/app.js` (inspector, teclado,
  diálogo de rangos), `dashboard/frontend/estilos.css`,
  `dashboard/frontend/i18n.js`, `dashboard/frontend/index.html`.
- **Pruebas:** `pruebas/test_v15_9_apertura_zoom_ui.cjs` (contratos A1–A4, A7:
  pan con puntero capturado separado del modo ROI, fullscreen con barra de
  controles, diálogo 100 % por `t()`, versiones de caché sincronizadas,
  cabeceras no-cache).
- **Hallazgos:** sin pan por arrastre; el fullscreen dejaba los controles
  fuera; las etiquetas del diálogo no pasaban por el sistema de idiomas; los
  estáticos seguían pidiéndose con `?v=20261009-v15-8`.
- **Decisiones:** pan solo con zoom > 100 % y sin `modoZona`; `requestFullscreen`
  sobre `.video-airbag-preview`; claves nuevas ES/EN/DE; `index.html` entra al
  parche con `?v=20261012-v15-9-1`. La validación visual en navegador real
  (capturas de pan/800 %/fullscreen/reversión) queda pendiente en hardware del
  usuario.

## 5. v-matrix-matrix-excel

- **Archivos analizados:** `utilidades/matriz_apertura.py` (`agrupar_casos`,
  `causa_sin_clasificar`, `construir_sin_clasificar`), `reporte_bmg.py`
  (`_poblar_matriz`, nuevo `_poblar_sin_clasificar`, `generar_reporte_bmg`).
- **Pruebas:** `pruebas/test_v15_9_1_paridad_matriz.py` (bloque único global
  con causa/ID/vínculo/recuento; igualdad de IDs dashboard↔Excel↔Listado con
  `None`, `LEGACY`, `3RD` y combinaciones fuera de columnas; ausencia de bloque
  cuando no hay casos fuera; y B1/B2 end-to-end: propuesto y causa grave quedan
  GRIS con motivo «Pendiente de revisión» y la medida solo en comentario,
  mientras el confirmado limpio se colorea).
- **Hallazgos:** los casos fuera de 1ST/2ST existían en `sin_clasificar` del
  dashboard pero desaparecían del Resumen Excel (B3); además los fuera-de-combo
  intra-etapa se dibujaban en el bloque de etapa, sin paridad con el dashboard.
- **Decisiones:** una sola definición de clasificación (motor compartido),
  bloque único detrás del 2ST, causa expuesta también en el tooltip del
  dashboard.

## 6. v-matrix-evaluation-lab

- **Archivos analizados:** suite completa `pruebas/` (pytest + node),
  `utilidades/benchmark_detector.py` (nuevo), `pytest.ini`.
- **Pruebas ejecutadas en este parche:** `python -m pytest pruebas/` →
  504 aprobadas, 1 falla de entorno conocida
  (`test_dashboard.py::test_estado_config_y_frontend`); `node --test
  pruebas/*.cjs` → 34/34. Clon limpio de V15.8.1 + `git apply` del parche +
  repetición de ambas baterías: mismos resultados; `git apply --reverse --check`
  OK (rollback posible).
- **Hallazgos:** la puerta no debe aprobar con bloqueantes reproducibles; el
  benchmark antes/después de `phaseCorrelate` no existía (A8).
- **Decisiones:** se retiene la publicación hasta correr la batería en el
  hardware final con videos reales anotados (exactitud ±1 cuadro, acuerdo ≥0.95,
  umbral 3-de-4 real, reflejos, dos tasas de adquisición) y el benchmark
  V15.8.1 vs V15.9.1 en la misma máquina. Todo lo verificable aquí está en
  `RESULTADOS_PRUEBAS_V15_9_1.md`.
