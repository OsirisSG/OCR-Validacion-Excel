# Resultados de pruebas · V15.9.3 (correctiva de auditoría estricta)

**Fecha:** 2026-10-12 · **Base:** V15.8.1 exacta + parche V15.9.2 + correcciones
CRIT-01..04 y ALTA-05 de `AUDITORIA_ESTRICTA_V_MATRIX_V15_9_2.md` /
`CORRECCIONES_OBLIGATORIAS_V_MATRIX_V15_9_3.md`.
**Rama:** `codex/ocr-v15-9-3-correctiva` (commit de código `f10ecbf`).
**Entorno:** Linux (sandbox CI), Python 3.13, Node 20; sin videos reales ni
GPU/RTX y sin navegador real (las validaciones de campo siguen pendientes, ver
final). Ninguna prueba toca `.aprendaje`, resultados reales, videos ni Excel
reales: todo con fixtures sintéticos en `tmp_path`.

## Puerta test-first: reproducción en ROJO antes de corregir

`pruebas/test_v15_9_3_criticos.py` se escribió ANTES de cualquier cambio de
código y se ejecutó sobre el árbol V15.9.2 (`226e028`):

```
python -m pytest pruebas/test_v15_9_3_criticos.py -q
11 failed, 7 passed, 1 skipped in 1.45s
```

Las 11 fallas reproducen exactamente los defectos auditados:

| Falla roja | Defecto reproducido |
|---|---|
| `test_crit01_legado_sin_total_principales_falla_cerrado` | CRIT-01: `consenso_valido({…, "soporte": 1})` sin `total_principales` devolvía `True`. |
| `test_crit01_migracion_sin_videos_deja_evidencia_pendiente` | CRIT-01: sin videos, el legado inválido se dejaba intacto y publicado. |
| `test_crit02_revision_sin_motivo_no_se_publica` | CRIT-02: 3/4 con una cámara `requiere_revision=True` sin motivo publicaba `confirmado` + `consenso_valido=True`, con `motivo_revision` contradictorio. |
| `test_crit03_empresarial_no_publica_reporte_identificado_incorrecto` | CRIT-03: `generar_desde_plantilla` guardaba la salida oficial pese a `identidad_verificada=False` y contaminaba el Excel vigente anterior. |
| `test_crit03_bmg_tampoco_publica_sin_mapeo` | CRIT-03: `generar_reporte_bmg` publicaba igual. |
| `test_crit04_registro_ilegible_bloquea_escrituras_y_preserva_bytes` | CRIT-04: `proyectos.json` truncado con «Proyecto A» + `registrar_proyecto("Proyecto B")` ⇒ éxito y registro sobrescrito. |
| `test_crit04_recuperacion_explicita_respalda_bytes_originales` | CRIT-04: no existía recuperación con respaldo. |
| `test_crit04_permisos_de_lectura_fallan_cerrado` | CRIT-04: archivo ilegible por permisos se reiniciaba en memoria. |
| `test_crit04_endpoint_proyectos_reporta_registro_ilegible` | CRIT-04: `/api/proyectos` respondía 200 con lista vacía fingida (`DID NOT RAISE`). |
| `test_crit04_pipeline_con_registro_ilegible_no_procesa` | CRIT-04: `iniciar_pipeline` SOBREESCRIBÍA el registro corrupto (bytes cambiados, «Proyecto A» perdido). |
| `test_alta05_fallo_a_mitad_de_escritura_no_toca_la_salida_anterior` | ALTA-05: `libro.save(destino)` directo dejaba la salida anterior corrupta con bytes parciales. |

El `skipped` era un puntero a la regresión P01 ya cubierta en
`test_v15_9_2_proyecto_c7.py`; se eliminó en verde (la suite no deja skips).

## Batería Python (tras la corrección)

`python -m pytest pruebas/ -q`

| Métrica | Resultado |
|---|---|
| Aprobadas | **574** |
| Fallas | **0** |
| Skips | **0** |

Sin asteriscos: la «falla de entorno» que V15.9.2 declaraba
(`test_estado_config_y_frontend`, que exigía el artefacto no versionado
`validacion_resultados.json`) quedó RESUELTA de forma hermética con el fixture
`estado_con_datos` (apunta `RUTA_VALIDACION` a un resultado mínimo temporal y
limpia la caché del backend antes y después). Delta frente a V15.9.2:
**+20 pruebas** (18 críticas nuevas, 1 de casilla legado-incompleto, 1
hermética reescrita).

Estabilidad verificada con **5 ejecuciones completas consecutivas en verde**
(574/574 cada una). Dos pruebas resultaron lábiles bajo carga por razones
ajenas a esta correctiva y se hicieron deterministas sin debilitar contratos:

- `test_prefetch_cpu_es_acotado_y_recupera_resultado`: el acotado de cola se
  ejercita ahora con las sondas de presión real de CPU/RAM aisladas
  (monkeypatch); la aserción de backpressure sigue intacta.
- `test_sha_completo_reutiliza_video_movido_y_detecta_cambio_intermedio_grande`:
  la memoización de `_firma_completa` usa `ctime_ns`, cuya granularidad real es
  el tick del reloj tosco del kernel (1–4 ms); una pausa de 10 ms garantiza que
  el ctime avance entre la copia y la modificación intermedia.

## Batería Node

`node --test pruebas/*.cjs` → **38/38 en verde**. Esta correctiva no modifica
el frontend; los contratos de UI (diálogo previo de dos bloques, zoom, ROI,
matriz, i18n) siguen certificados sin cambios.

## Pruebas nuevas

| Archivo | Cubre |
|---|---|
| `pruebas/test_v15_9_3_criticos.py` | CRIT-01 (repro literal de la auditoría, metadata completa conserva reglas 3/4 y 2/2, migración sin videos degrada a `pendiente_revision` conservando medida y evidencia, respaldo completo sin videos NO degrada), CRIT-02 (3/4 con revisión sin motivo ⇒ pendiente y `consenso_valido=False`; 3/4 limpio ⇒ confirmado; marca informativa explícita no bloquea; confirmación humana manda; coherencia motivo/`requiere_revision`), CRIT-03 (empresarial y BMG: destino oficial intacto, borrador `*.borrador_no_publicable.xlsx` con ADVERTENCIA + marcador visible, título antiguo no suplantado, plantilla byte-idéntica; identidad legacy no bloquea), CRIT-04 (bytes intactos, lecturas y escrituras bloqueadas, recuperación con respaldo SHA-256, permisos, endpoints 503), ALTA-05 (fallo inyectado a mitad de escritura: salida previa intacta, sin temporales huérfanos). |

## Pruebas existentes actualizadas (cambio de contrato exigido por la auditoría)

| Prueba | Cambio |
|---|---|
| `test_c2_items_legados_sin_motivo_son_informativos` → `test_c2_items_legados_sin_motivo_bloquean_v15_9_3` | INVERTIDA: la ausencia de motivo ya NO es informativa; sólo `revision_informativa=True` explícita excepciona (CRIT-02). |
| `test_c7_p08_plantilla_sin_campo_identificable_advierte_y_no_suplanta` → `..._bloquea_publicacion` | REESCRITA: ahora certifica que la publicación fue EVITADA (destino oficial no creado, borrador diferenciado), no sólo el texto de advertencia (CRIT-03). |
| `test_compatibilidad_consenso_historico_v1581` | El legado «ok» incluye `total_principales` (como el JSON real de V15.8.1); se añade el caso incompleto ⇒ `False` (CRIT-01). |
| `test_consenso_valido_rellena_la_casilla` | Metadata completa; se añade `test_consenso_legado_incompleto_no_rellena_v15_9_3` (CRIT-01). |
| `test_estado_config_y_frontend` | Hermética con fixture `estado_con_datos` (instrucción 7 de la auditoría). |

Contratos V15.9.2 que NO se debilitaron (regresiones en verde): sello
`algoritmo_consenso` y migración con evidencia, C3 escritura verificada, C4
rollback de ROI, C5 bits 100755, P01/P02/P07/P10/P12, precedencia de orígenes
C7, paridad Excel↔dashboard, rangos en «Procesar carpeta», 3/4, ES/EN/DE.

## Impacto operativo del fail-closed (documentado para el usuario)

- Lotes históricos con consensos automáticos legados de metadata incompleta
  (sin `total_principales`) bajan a **pendiente de revisión** al cargarse; la
  medida se conserva como evidencia (`video_apertura_anterior`, campo en
  `pendiente_revision` visible sólo en tooltip). Se recuperan reanalizando los
  videos (el detector actual sella `revision_informativa` y metadata completa)
  o con confirmación humana explícita, que siempre tiene prioridad.
- Una salida Excel identificada cuya plantilla no declara celda de proyecto
  mapeable se guarda como `*.borrador_no_publicable.xlsx` junto al destino
  oficial (que NO se crea ni se reemplaza). La ruta del borrador es la que
  devuelve el generador y la que muestra el dashboard; la corrida NO aborta
  (una excepción en fase 3 habría perdido la persistencia de los resultados
  OCR ya calculados).
- `proyectos.json` ilegible: lecturas y escrituras bloqueadas con
  `RegistroProyectosCorruptoError` (503 visible en `/api/proyectos` y al
  iniciar pipeline), cero bytes modificados. Recuperación explícita con
  `recuperar_registro()` que respalda los bytes originales verificados por
  SHA-256 en `proyectos.json.corrupto-<marca>.bak`.

## Verificación de paquete (fresh clone)

Clon limpio en la base V15.8.1 exacta (`5fbef43`) + `git apply` del parche
V15.9.3 acumulado: `git apply --check` OK; todos los archivos de `archivos/`
byte-idénticos al árbol parcheado; `git diff 5fbef43..HEAD --summary` sin
cambios de modo (C5, `.command` quedan `-rwxr-xr-x`); suite Python 574/0/0 y
node 38/38 repetidas en el clon; `git apply -R` revierte sin rechazos.
`SHA256SUMS.txt` con rutas relativas a la raíz del ZIP, verificables con
`sha256sum -c SHA256SUMS.txt` desde la carpeta extraída (MEDIA-06).

## Pendientes de campo (sin cambios + los añadidos por la auditoría)

Ejecución real de `.command` en macOS, verificación visual en navegador,
validación ±1 cuadro/0.95 con datos reales, benchmark RTX (sintético en este
entorno), videos reales anotados, dos proyectos consecutivos, reanudación,
selectores 1ST/2ST y registros de FPS. Este entorno no tiene GPU, videos
reales ni acceso a internet: la puerta de producción final requiere esas
pruebas de campo.
