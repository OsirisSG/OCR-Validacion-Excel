# Revisión trazable por skill · V15.9.4 (correctiva N1-N6)

**Fecha:** 2026-10-12. Una revisión por cada skill con archivos/diff
analizados, pruebas ejecutadas, hallazgos y decisiones. Base auditada:
`AUDITORIA_ESTRICTA_V_MATRIX_V15_9_3.md` (N1-N6) e instrucciones
`CORRECCIONES_OBLIGATORIAS_V_MATRIX_V15_9_4.md`, incluidos sus 7 casos de
regresión incorporados verbatim al repo.

## 1. v-matrix-safe-change

- **Archivos analizados:** `utilidades/proyectos.py` (`_leer` validación
  entrada por entrada), `dashboard/backend/app.py`
  (`_migrar_consensos_video` con verificación de `ResultadoPersistencia`,
  invalidación de caché y advertencia visible; `_generar_excel_asociado` con
  `PublicacionExcelBloqueadaError`), `utilidades/cola_excel.py` (semántica de
  error/pendiente reutilizada, sin cambios), `plantilla_empresarial.py`
  (`_guardar_atomico` bajo `PermissionError`).
- **Pruebas:** N3 parametrizado (7 estructuras corruptas, bytes intactos,
  respaldo íntegro), N5 (fallo inyectado: advertencia, caché, disco intacto,
  reintento persistido), N6 (cola conserva pendiente; PermissionError en
  `os.replace` con salida anterior intacta y sin temporales); los 7 casos de
  la auditoría en rojo→verde.
- **Hallazgos:** N3 violaba «fallar cerrado ante datos no íntegros» (el
  filtro silencioso de entradas inválidas las borraba al guardar); N5 violaba
  «no declarar éxito sin escritura verificada» (migración contada como hecha
  con `guardado=False` y caché que no reintentaba).
- **Decisiones:** validación estricta por entrada sin descartes; error de
  migración comunicado, cache invalidada (`mtime=None`) con reintento en la
  próxima carga y vista en memoria fail-closed; la cola durable conserva el
  estado pendiente con error visible hasta corregir el mapeo (nada de éxito
  fantasma); reemplazo atómico sigue limpiando temporales ante cualquier
  fallo.

## 2. v-matrix-airbag-onset

- **Archivos analizados:** `video_airbag.py` (`consenso_valido` rama legada),
  `dashboard/backend/app.py` (migración sin videos heredada de V15.9.3).
- **Pruebas:** N4 matriz completa (3/4, 4/4, 3/3 publicados; 2/4, 2/2, 1/1
  pendientes; manual auditado manda), 3/4 con revisión obligatoria pendiente,
  migración de 2/2 a pendiente conservando medida y evidencia; los dos casos
  literales de la auditoría (1/1, 2/2).
- **Hallazgos:** N4: la rama histórica aplicaba un estándar distinto del
  vigente (`min(2, max(1, total))` publicaba 1/1 y 2/2 con metadata
  completa), cuando la ruta automática actual exige 3+ cámaras comparables.
- **Decisiones:** POLÍTICA ÚNICA de publicación automática: mínimo 3 cámaras
  comparables en todas las rutas; no existe ningún modo autorizado con menos
  cámaras (si se habilitara, exigirá aceptación humana y configuración
  versionada con trazabilidad); la confirmación humana real con evidencia
  sigue siendo la única excepción; pruebas antiguas que exigían 2/2 válido se
  invirtieron documentadamente.

## 3. v-matrix-matrix-excel

- **Archivos analizados:** `utilidades/identidad_excel.py` (nuevo
  `detectar_referencias_contradictorias`, `es_borrador_no_publicable`,
  `PublicacionExcelBloqueadaError`, `publicable` con contradicciones, textos
  ES/EN/DE de contradicción), ambos generadores (puerta heredada de V15.9.3
  sin cambios), plantilla BMG real inspeccionada celda a celda.
- **Pruebas:** N1/N2 completos (título A1 + etiqueta A2 en los 3 idiomas,
  título coherente que publica, BMG real con título ajeno y control sin
  falsos positivos, «Sin asignar» bloqueado/permitido según título, A/B
  consecutivos sin mezclas de `project_id`, reanudación B con plantilla A);
  muestras reales generadas en el paquete.
- **Hallazgos:** N1: mapear UNA celda etiquetada no probaba la ausencia de
  títulos precargados contradictorios (el libro podía exhibir dos proyectos a
  la vez). N2: «Sin asignar» se trataba como verificación de la identidad
  antigua.
- **Decisiones:** contrato de mapeo ampliado: escaneo de referencias visibles
  a proyecto en las hojas oficiales (resumen + hojas de búsqueda), comparación
  por tokens contra la identidad autoritativa, y `publicable=False` ante
  cualquier referencia no resoluble con certeza; NUNCA reemplazo global ciego
  (el título contradictorio permanece intacto y se lista con hoja/celda/texto
  en el bloque); la decisión «Sin asignar» se separa de la verificación de
  limpieza de metadatos y queda en la trazabilidad.

## 4. v-matrix-roi-supervision

- **Archivos analizados:** sin cambios de ROI en esta correctiva; se verificó
  que el escáner de identidad y la política N4 no tocan zonas aprendidas,
  reversiones ni historial ROI.
- **Pruebas:** regresiones C3/C4 (escritura verificada, rollback) y suite ROI
  completa en verde.
- **Hallazgos:** ninguno nuevo.
- **Decisiones:** mantener el flujo ROI fuera del alcance auditado.

## 5. v-matrix-evaluation-lab

- **Archivos analizados:** `pruebas/test_v15_9_4_auditoria_regresiones.py`
  (7 casos VERBATIM de la auditoría), `pruebas/test_v15_9_4_ampliacion.py`
  (23 casos), `pruebas/test_v15_9_4_exportacion_ui.cjs` (3 contratos),
  pruebas invertidas (N4) y de determinismo (tick de reloj en
  `hash_archivo`).
- **Pruebas:** puerta rojo→verde real: RED `7 failed` sobre `b19e8a0` ANTES
  del código; GREEN suite completa `604 passed / 0 failed / 0 skipped` (3+
  corridas) + node `41/41`; verificación posterior en clon limpio base+parche.
- **Hallazgos:** tercera prueba con flake de granularidad de reloj
  (`hash_archivo` cachea por mtime_ns y el test reescribe con igual tamaño);
  se corrigió con la misma pausa anti-tick sin debilitar el contrato.
- **Decisiones:** los casos de la auditoría se incorporan SIN modificaciones
  (criterio de aceptación literal); cero fallas declaradas, cero skips; todo
  sintético y hermético; los cambios de pruebas existentes son sólo los
  exigidos por N4 y están documentados uno por uno.

## 6. v-matrix-video-zoom-ux

- **Archivos analizados:** `dashboard/frontend/app.js` (tarjeta exportadora,
  bloque de Excel parcial), `dashboard/frontend/i18n.js` (ES/EN/DE),
  `pipeline.py` (mensaje final de fase 3), endpoints de descarga
  (`/api/resultados/exportado`, nuevos `/api/resultados/borrador` y
  `/api/pipeline/borrador-parcial`), `/api/estado`
  (`advertencia_migracion_consensos`).
- **Pruebas:** N6 API (borrador fuera de `generados`, `publicable=False`,
  descargas cruzadas rechazadas), contratos cjs nuevos (41/41), mensajes del
  pipeline distinguiendo «OCR terminado» de «exportación BLOQUEADA».
- **Hallazgos:** N6: el borrador se ofrecía como exportación generada con URL
  de descarga oficial y el pipeline anunciaba «Resultados y Excel
  actualizados» sin distinguir el bloqueo.
- **Decisiones:** estado estructurado (`publicable`, `estado_publicacion`,
  `bloqueados[{idioma, motivo, ruta_borrador, url_borrador}]`,
  `archivos_excel_borrador`, `archivos_excel_parcial_borrador`) preservando
  compatibilidad con consumidores actuales; descargas diferenciadas por ruta
  explícita; OCR sigue siendo exitoso cuando corresponde; notificaciones
  traducidas ES/EN/DE.

## Evidencia de ejecución

- RED: `7 failed in 0.65s` (log capturado sobre el árbol V15.9.3 antes de
  corregir; los 7 reproducen N1-N6).
- GREEN: `604 passed, 1 warning` ×3+ corridas; auditoría `7 passed`;
  ampliación `23 passed`; node `# tests 41 / # pass 41 / # fail 0`.
- Fresh clone `5fbef43` + parche acumulado: apply OK, byte-idénticos, 0
  cambios de modo, 604/0/0 + 41/41, reversión exacta.
