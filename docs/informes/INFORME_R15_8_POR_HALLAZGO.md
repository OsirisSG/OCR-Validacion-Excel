# INFORME R15.8 POR HALLAZGO — V-Matrix V15.10.1-r15.8

Correspondencia uno a uno entre los hallazgos de la revalidación independiente
de R15.7 (`AUDITORIA_REVALIDADA_R15_7_20261016.md`, §5 «8/8 reproducciones» y
§6) y su corrección + prueba. Método: cada hallazgo se REPRODUJO antes de
corregir (la prueba nueva falla sobre el árbol R15.7) y se volvió a ejecutar
después (verde). Ver matriz de corridas en `MATRIZ_EVIDENCIA_R15_8.md`.

---

## ALTO-01 — La sonda de recuperación no prueba el target real

* **Repro (revalidación):** target `estado_inconsistente.json` no reemplazable
  con directorio padre escribible ⇒ `_sonda_recuperacion()` devolvía
  `escribible=True`, `inicializar_recuperacion()` no activaba el modo y una
  escritura real a `RUTA_INCONSISTENCIAS` fallaba después.
* **Causa:** la sonda R15.7 escribía un archivo HERMANO
  (`sonda_recuperacion.json`), no la semántica real de reemplazo del target.
* **Corrección:** la sonda actúa sobre el target exacto: exige archivo regular,
  conserva el contenido previo, escribe la sonda con
  temporal+fsync+replace+relectura y RESTAURA el contenido previo byte a byte
  (`_restaurar_contenido_verificado`). Fallo en cualquier paso ⇒ modo
  recuperación. La sonda deliberadamente NO escribe un registro válido.
* **Pruebas:** `test_alto01_sonda_falla_si_el_target_no_es_un_archivo_regular`
  (target=directorio), `test_alto01_sonda_prueba_el_reemplazo_del_target_real`
  (`Path.replace` bloqueado ⇒ falla y el registro previo queda intacto),
  `test_alto01_sonda_preserva_el_registro_existente` (sin falsos positivos, sin
  temporales residuales).

## ALTO-02 — Migración legacy incorrecta con rutas relativas

* **Repro (revalidación):** documento con `raiz=<lote>` y ruta de imagen
  RELATIVA (`CASO1/img_0001.png`); registro heredado R15.6 con la ruta
  ABSOLUTA. R15.7 no traducía la ruta heredada al recurso canónico
  (`_clave_ruta` resolvía la relativa del documento contra el CWD) y el guard
  de `carpeta:<case_id>` permitía continuar.
* **Corrección:** `_raiz_documento()` + `_variantes_clave_ruta()`: el índice
  registra cada ruta almacenada en TODAS sus variantes (resuelta, relativa
  contra `datos["raiz"]` con CONFINAMIENTO, literal) y `_recurso_canonico()`
  consulta todas; `_cargar_inconsistencias()` PERSISTE la migración canónica
  conservando el alias. La dirección inversa (registro relativo, documento
  absoluto) también resuelve.
* **Pruebas:** `test_alto02_migracion_relativa_en_documento_bloquea` (bloquea
  y el registro durable queda canónico + alias),
  `test_alto02_registro_relativo_heredado_bloquea`,
  `test_alto02_ruta_relativa_fuera_de_la_raiz_no_mapea_al_caso` (confinamiento).

## ALTO-03 — Endpoints mutantes durante MODO RECUPERACIÓN

* **Repro (revalidación):** con `_modo_recuperacion` forzado,
  `pruebas_externas.evaluar()` EJECUTÓ: el endpoint no invocaba ningún guard.
* **Corrección:** política transversal declarada —
  `_guard_recuperacion_transversal` como dependencia de la aplicación: todo
  POST/PUT/PATCH/DELETE ⇒ 503 en MODO RECUPERACIÓN. Exenciones DECLARADAS y
  cerradas (`_ENDPOINTS_SEGUROS_EN_RECUPERACION`): el propio flujo de
  recuperación (`/api/recuperacion/*`) y las acciones de seguridad
  `pausar`/`cancelar` del pipeline. `externas/evaluar` lleva además su guard
  explícito. Test contractual P0-5: el catálogo de rutas mutantes debe tener
  guard o ser exención exacta — una ruta nueva sin política no pasa la suite.
* **Pruebas:** `test_alto03_evaluar_banco_externo_bloqueado_en_modo_recuperacion`,
  `test_alto03_toda_ruta_mutante_declara_politica_de_recuperacion`,
  `test_alto03_guard_transversal_bloquea_mutantes_y_permite_la_salida`.

## ALTO-04 — `/api/revisiones` puede modificar un caso bloqueado

* **Repro (revalidación):** con inconsistencia activa para `carpeta:<case_id>`,
  `actualizar_revision()` siguió ejecutándose.
* **Corrección:** `_assert_recurso_consistente()` sobre el recurso canónico
  (`carpeta:<item_id>` / `externa:<item_id>`) al inicio del endpoint, antes de
  cualquier transición durable.
* **Pruebas:** `test_alto04_revision_carpeta_bloqueada_con_inconsistencia_activa`,
  `test_alto04_revision_externa_bloqueada_con_inconsistencia_activa`.

## MEDIO-05 — `/api/alertas/atender` ignora el bloqueo

* **Repro (revalidación):** con el caso marcado inconsistente,
  `atender_alerta()` persistió la atención de la alerta.
* **Corrección:** guard canónico antes de atender (una anomalía no puede
  ocultarse con el caso bloqueado).
* **Prueba:** `test_medio05_alertas_respetan_el_bloqueo_de_recuperacion`.

## MEDIO-06 — El listado de recuperación duplica alias

* **Repro (revalidación):** el mismo incidente bajo `carpeta:abc` y su ruta
  heredada ⇒ `GET /api/recuperacion/inconsistencias` con `total=2`.
* **Corrección:** el listado deduplica por identidad de incidente (el registro
  interno conserva los aliases) y expone `claves` con todas las identidades
  del incidente. La resolución por alias sigue funcionando (regresión cubierta).
* **Pruebas:** `test_medio06_listado_deduplica_el_mismo_incidente`,
  `test_medio06_resolucion_por_alias_sigue_funcionando`.

## MEDIO-07 — Falso fallo del soak si el pipeline termina muy rápido

* **Repro (revalidación):** `_esperar_pipeline()` sólo aceptaba un terminal si
  ANTES vio un estado activo; POST muy rápido + primer GET ya `completado` ⇒
  «el pipeline no arrancó».
* **Corrección:** el soak sigue el `ejecucion_id` del POST; un terminal de ESA
  misma ejecución se acepta aunque no se viera el estado intermedio. Un
  terminal de OTRA ejecución no se acepta (se agota la ventana de admisión con
  diagnóstico).
* **Pruebas:** `test_medio07_soak_acepta_terminal_antes_del_primer_sondeo`,
  `test_medio07_soak_no_confunde_terminal_de_otra_ejecucion`.

## MEDIO-08 — El soak hereda el `ejecucion_id` de la iteración anterior

* **Repro (revalidación):** `lanzado` no se reiniciaba y se consultaba con
  `locals().get("lanzado")`: iteración 2 con lanzamiento fallido reportaba el
  `EXEC1` de la iteración 1.
* **Corrección:** `lanzado=None` + `ejecucion_objetivo` por ciclo; el reporte
  usa la variable local (sin `locals()`); se verifica además que el terminal
  final pertenezca a la ejecución lanzada.
* **Prueba:** `test_medio08_soak_no_hereda_ejecucion_id_entre_iteraciones`.

---

## BAJO-09 — README raíz aún se identificaba como R15.6

* Cabecera del README reescrita: declara **R15.8**, resume el cierre R15.8,
  enlaza `CHANGELOG_R15_8.md` y `INSTALAR_R15_8.bat`. Sección nueva
  «R15.8 · cierre del perímetro de recuperación».
* **Prueba:** `test_bajo09_readme_raiz_declara_r15_8`.

## BAJO-10 — Mensajes del instalador todavía decían R15.6

* `INSTALAR_R15_8.ps1/.bat`: banner, mensaje de base desconocida, avisos de
  postflight (index/app.py/VERSION.txt) y resultado derivan de la variable
  única `$PatchBuild` con `[regex]::Escape`; cero literales «R15.6».
* **Prueba:** `test_bajo10_mensajes_del_instalador_derivados_de_variable_de_version`.

## BAJO-11 — Runbook decía «17/17» con payload 23

* Runbook R15.8 (nuevo): «tantas líneas OK como entradas tenga SHA256SUMS.txt,
  cero FALTA / HASH DISTINTO». El runbook R15.7 del árbol también queda
  corregido (sin cifra fija).
* **Prueba:** `test_bajo11_runbook_sin_conteo_fijo_de_integridad`.

## Observación — definición formal de «Tmax»

* `validar_tmax_semaforo.py` (docstring) y runbook R15.8 definen: «Tmax» = el
  TIEMPO DE APERTURA PUBLICADO (`resultado_caso_canonico.apertura.tiempo_ms` /
  `opening_time_ms` heredado), el valor que colorea semáforo y Excel; NO es el
  «máximo inflado» del análisis de video. La herramienta sigue midiendo el
  evento correcto para el criterio §9-8.
* **Prueba:** `test_observacion_tmax_definicion_formal` +
  `test_soak_herramienta_documenta_ejecucion_id`.

---

## Qué NO se tocó (alcance §8 de la revalidación)

Motor OCR, algoritmo de apertura/ruptura, máximo inflado, semáforo, plantilla
Excel: sin cambios. Las únicas líneas de `app.py` ajenas al perímetro de
recuperación son la identidad (`PATCH_BUILD`/`FastAPI(version=…)` →
`15.10.1-r15.8`) y los cache-busters del frontend.
