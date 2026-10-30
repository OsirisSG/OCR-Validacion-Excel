# Revisión trazable por skill · V15.9.2 (r2 + C7)

**Fecha:** 2026-10-12. Cumple la condición de la puerta de skills: una revisión
trazable por cada skill, con archivos/diff analizados, pruebas ejecutadas,
hallazgos y decisiones. Las skills viven en `.agents/skills/`; desde V15.9.2
(C6) `AGENTS.md` en la raíz las activa para cualquier agente (Codex incluido).

## 1. v-matrix-safe-change

- **Archivos analizados:** `utilidades/persistencia.py`
  (`ResultadoPersistencia.__bool__`), `aprendizaje_video_airbag.py`
  (`_guardar_json`, `guardar/revertir_zona_aprendida`, nuevos
  `perfil_zona_aprendida`/`restaurar_perfil_zona`), `dashboard/backend/app.py`
  (`revertir_zona_video`, `aprender_zona_video`, `_cargar_datos`,
  `_migrar_consensos_video`, `iniciar_pipeline`), `pipeline.py` (config por
  copia local), `utilidades/proyectos.py` (escritura verificada).
- **Pruebas:** C3/C4 de `test_v15_9_2_correcciones_c1_c7.py` (fallos
  inyectados por etapa, rollback comparando bytes de disco), P10 y escritura
  fallida del registro en `test_v15_9_2_proyecto_c7.py`; suite 554 + 1 entorno.
- **Hallazgos:** C3 (éxito fantasma con escritura fallida) y C4 (ROI
  persistida antes del reanálisis) violaban «no declarar éxito sin escritura
  verificada» y «toda operación multi-paso necesita rollback».
- **Decisiones:** verificación `guardado` en TODA escritura de aprendizaje y
  registro de proyectos; orden transaccional pre-chequeo→snapshot→mutar→
  rollback; migración C1 persiste una sola vez y no aborta la carga si falla;
  rollback documentado (`git apply -R V15_9_2_completo.patch`, reversible
  verificado en fresh clone); la identidad C7 nunca escribe preferencias
  globales (copia local de config por ejecución).

## 2. v-matrix-airbag-onset

- **Archivos analizados:** `video_airbag.py` (`consenso_valido` rama legada,
  `consenso_videos`, `_causas_revision_graves`, bandera genérica del detector
  en `analizar_video`), `dashboard/backend/app.py`
  (`_normalizar_tiempos_video_fila`, `_aplicar_consenso_video_a_fila`).
- **Pruebas:** C1/C2 de `test_v15_9_2_correcciones_c1_c7.py` (repro literal
  2/4, 3/4 y 2/2 legados, manual preservada, alerta sin clasificar vs
  informativa vs grave, detector sintético marcado informativo).
- **Hallazgos:** la rama de compatibilidad publicaba 2/4 antiguos como
  confirmados (C1) y el consolidado borraba alertas con motivo no catalogado
  (C2); la bandera genérica del detector, en cambio, es informativa por diseño
  y NO debe bloquear confirmaciones limpias.
- **Decisiones:** regla vigente reevalúa legados (3 de 4 comparables); sello
  `algoritmo_consenso` + migración con evidencia `video_apertura_anterior`;
  clasificación explícita informativa/bloqueante con motivo por cámara; sin
  cambio a `ALGORITMO_VERSION` del detector (no fuerza reanálisis masivo de
  cachés); sigue vigente «nunca proclamar validación sin videos reales».

## 3. v-matrix-matrix-excel

- **Archivos analizados:** `plantilla_empresarial.py`
  (`generar_desde_plantilla` + verificación post-save), `reporte_bmg.py`
  (salida con `aplicar_identidad_a_salida`), `generar_excel.py` (propagación
  de `proyecto_ejecucion`), `utilidades/identidad_excel.py` (nuevo).
- **Pruebas:** P01/P02/P07/P08/P10 de `test_v15_9_2_proyecto_c7.py` con
  lectura real de celdas (`Captura_pruebas!B1`, bloque Resumen) y hash de
  plantilla; muestra Excel real en la entrega; suite de paridad B3 V15.9.1 sin
  cambios.
- **Hallazgos:** la salida heredaba el título histórico de la plantilla como
  identidad visible; no había canal identificado para el proyecto declarado.
- **Decisiones:** identidad sólo en celdas identificadas (etiqueta de
  cabecera en zona acotada + bloque propio en Resumen), jamás
  buscar-y-reemplazar global; plantilla inmutable (hash verificado); sin campo
  identificable ⇒ ADVERTENCIA visible y reporte identificado bloqueado;
  escritura verificada post-save; ES/EN/DE coherentes (nombre visible
  idéntico, bloque traducido); IDs/paridad de la matriz intactos (el proyecto
  no altera `case_key` ya expuestos).

## 4. v-matrix-roi-supervision

- **Archivos analizados:** `aprendizaje_video_airbag.py` (snapshot/restore,
  historial), endpoints `zona-aprender`/`zona-revertir` del backend.
- **Pruebas:** C3/C4 (rollback restaura la ROI activa exacta, historial
  intacto tras pre-chequeo fallido, 503/500 según etapa) + suite A1 V15.9.1
  (historial, reversibilidad, índice) sin regresión.
- **Hallazgos:** revertir podía dejar ROI cambiada con análisis/JSON viejos y
  declarar éxito sin guardar.
- **Decisiones:** la reversión sigue siendo reversible (la ROI desplazada va
  al historial) y además transaccional; el rollback restaura el perfil
  snapshot completo con escritura verificada; si el rollback falla se declara
  «estado inconsistente» con el historial disponible para recuperación manual;
  microzona de nacimiento y ROI bloqueada sin cambios.

## 5. v-matrix-evaluation-lab

- **Archivos analizados:** suite completa `pruebas/` (pytest + node),
  `pytest.ini`, aislamiento `.aprendizaje`/`.cache_ocr`/Excel en las pruebas
  nuevas (tmp_path + monkeypatch de rutas de persistencia), `utilidades/benchmark_detector.py`
  (sin cambios, disponible para campo).
- **Pruebas:** puerta test-first documentada (18/22 fallan pre-corrección);
  554 pytest + 38 node en árbol de trabajo Y en fresh clone parcheado;
  comparación byte a byte `archivos/` vs parche; reverse-check.
- **Hallazgos:** dos pruebas existentes necesitaban actualización legítima
  (whitelist de raíz por `AGENTS.md` C6; ventanas de slice del cjs de UI por
  crecimiento del diálogo) — se actualizaron las pruebas, no se relajó ningún
  contrato.
- **Decisiones:** no se declara aprobación con la falla de entorno conocida
  (documentada como tal, preexistente); las validaciones con datos reales
  (±1 cuadro, 3-de-4 real, RTX, navegador) siguen listadas como pendientes de
  campo en RESULTADOS y en la matriz P01-P12; benchmark sigue siendo sintético
  en sandbox.

## 6. v-matrix-video-zoom-ux

- **Archivos analizados:** `dashboard/frontend/app.js` (diálogo previo de dos
  bloques, badge de proyecto en panel de progreso), `i18n.js` (19 claves
  nuevas ES→EN/DE), `estilos.css` (`.dialogo-proyecto-bloque`,
  `.chip-sugerencia`, `.identidad-pendiente`, breakpoint 520 px), visor de
  video (sin cambios en V15.9.2).
- **Pruebas:** `test_v15_9_2_proyecto_ui.cjs` (4 contratos: bloque obligatorio,
  guardias `disabled`/`if (!proyecto)`, `/api/proyectos` + slug paritario,
  estilos/i18n) + 34 contratos V15.9/15.9.1 sin regresión (38/38 node).
- **Hallazgos:** el paso previo V15.9.1 sólo cubría rangos; sin bloque de
  proyecto la identidad se heredaba en silencio (C7).
- **Decisiones:** dos bloques independientes en el mismo diálogo (proyecto +
  rangos), botones de procesar desactivados hasta elección consciente,
  sugerencias con aceptación expresa (clic + nombre editable), estado
  pendiente visible (ámbar) en progreso, ES/EN/DE completos, usable en panel
  pequeño; zoom/pan/fullscreen del visor intactos.

## Evidencia de ejecución

- Puerta test-first: `git stash` → 18/22 fallan; `git stash pop` → 22/22.
- Suites completas ejecutadas en árbol de trabajo y fresh clone:
  **554 pytest (1 entorno) + 38/38 node** en ambos.
- Paquete: apply/check/byte-compare/reverse verificados; hashes en
  `SHA256SUMS.txt` de la entrega; muestra Excel real P01 generada y leída.
- Ver resultados por prueba en [RESULTADOS_PRUEBAS_V15_9_2.md](RESULTADOS_PRUEBAS_V15_9_2.md).
