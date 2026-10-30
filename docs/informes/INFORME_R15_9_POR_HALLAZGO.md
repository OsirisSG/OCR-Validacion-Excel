# INFORME R15.9/R15.9.1 POR HALLAZGO — V-Matrix V15.10.1-r15.9.1

Correspondencia uno a uno entre los hallazgos de la auditoría independiente de
R15.8 (`AUDITORIA_INDEPENDIENTE_R15_8_20261018.md`, §3 y §5) y su corrección +
prueba. Método: cada hallazgo se REPRODUJO antes de corregir —incluido el
script Python del auditor, ejecutado literal sobre un árbol R15.8 pristino con
resultados idénticos a los publicados— y se volvió a ejecutar después.
Evidencia: `MATRIZ_EVIDENCIA_R15_9.md` y `EVIDENCIA_R159_pre_fix_R15_8.txt`
(en el paquete).

---

## ALTO-01 — El instalador obligaba a tener R15.7 tras instalar R15.9

* **Repro (auditor):** extrajo la instrucción Python de
  `Verify-ImportResolution` tal como estaba escrita
  (`!= '15.10.1-r15.7'`) y la ejecutó sobre el árbol R15.8: **exit 33**.
  Nuestra reproducción: `evidencia_r159/r159_pre_fix_alto01_verify_import.txt`
  (exit 33, mismo árbol pristino).
* **Causa:** el transform R15.8→R15.9 heredó el literal del verificador (las
  correcciones de mensajes de R15.8 no llegaron a esta función).
* **Corrección:** `Verify-ImportResolution($Python, $BuildEsperado)`; el
  snippet compara con `sys.argv[2]`; la llamada transmite `$PatchBuild`. Un
  único punto de verdad para la versión.
* **Pruebas:** `test_alto01_verificador_sin_literales_de_version` (sin
  literales + argumento en firma y llamada),
  `test_alto01_snippet_real_del_instalador_acepta_el_arbol_vigente` (ejecuta
  el snippet REAL extraído ⇒ 0),
  `test_alto01_snippet_real_rechaza_un_build_equivocado` (⇒ 33; el verificador
  sigue siendo estricto).

## ALTO-02 — La instalación «acumulativa» omitía artefactos de R15.7

* **Repro (auditor):** aceptaba bases R14…R15.8 pero el ZIP sólo lleva el
  delta: faltaban 13 artefactos de R15.7 (`app.js`, `inventario_destino.py`,
  pruebas y validación de campo) sobre una base R15.6 ⇒ árbol híbrido.
* **Decisión de diseño (opción «b» del auditor):** parche INCREMENTAL con
  base restringida y comprobada por hash.
* **Corrección:** `Assert-BaseConocida` sólo acepta R15.7/R15.8/R15.9;
  nueva `Assert-BaseIntegra` con tabla-contrato de 32 claves (unión de los
  payloads R15.7 y R15.8 + valores R15.9 en los modificados): las 23 claves
  del release base son REQUERIDAS y todas deben tener hash conocido. Se
  ejecuta antes de leer el manifiesto/copiar: híbrido ⇒ aborto sin cambios.
* **Pruebas:** `test_alto02_tabla_cubre_todos_los_artefactos_de_los_releases_base`
  (32 claves = unión exacta; requeridas = manifiesto R15.7),
  `test_alto02_el_arbol_vigente_satisface_el_contrato_completo` (funcional:
  el árbol vigente pasa SU propio contrato),
  `test_alto02_un_hash_r15_6_rechazado_por_el_contrato` (cruce con el
  manifiesto R15.6 auditado: sus hashes se rechazan),
  `test_alto02_la_tabla_se_evalua_antes_de_copiar`,
  `test_alto02_bases_restringidas_a_r15_7_en_adelante`.

## ALTO-03 — La sonda podía destruir el registro por interrupción

* **Repro (auditor):** `SystemExit` tras la sustitución ⇒ `registro_igual=false`,
  `quedo_sonda=true`; el siguiente arranque entraba en modo recuperación pero
  NO recuperaba las entradas. Nuestra reproducción literal sobre el árbol
  R15.8 pristino: idéntica (mismo JSON de resultados).
* **Corrección:** (1) respaldo durable del registro ANTES de la sonda
  (`_ruta_respaldo_sonda()` + `_escribir_bytes_verificados`: temporal+fsync+
  replace+relectura a nivel de bytes); (2) protocolo al reinicio
  (`_leer_registro_o_respaldo`): registro sano ⇒ datos + limpieza del
  respaldo residual; dañado/ausente ⇒ restauración byte a byte desde el
  respaldo + recarga de entradas SIN modo; nada utilizable ⇒ fail-closed
  R15.6 intacto (y la instalación fresca sin registro sigue siendo normal).
* **Pruebas:** `test_alto03_interrupcion_deja_respaldo_y_el_arranque_recupera`
  (repro completo: respaldo = bytes originales, arranque recupera
  `carpeta:CASO1`, sin modo, target restaurado, respaldo retirado),
  `test_alto03_registro_danado_con_respaldo_se_recupera`,
  `test_alto03_registro_danado_sin_respaldo_sigue_fail_closed`,
  `test_alto03_registro_danado_con_respaldo_invalido_fail_closed`,
  `test_alto03_registro_sano_limpia_respaldo_residual`,
  `test_alto03_sonda_falla_con_registro_ilegible_y_no_lo_toca` (la evidencia
  ilegible no se toca ni se respalda),
  `test_alto03_sonda_sana_retira_el_respaldo`.

## MEDIO-04 — La sonda no preservaba CRLF byte a byte

* **Repro (auditor):** registro CRLF ⇒ sonda OK pero SHA antes/después
  distinto (`fcaa1330…` → `e6ea0a7f…`): el camino texto leía con newlines
  universales y restauraba en modo texto.
* **Corrección:** toda la sonda en BYTES: lectura `read_bytes`, respaldo y
  restauración con `_escribir_bytes_verificados` (binario + relectura de
  igualdad de bytes). El script del auditor post-corrección devuelve
  `bytes_iguales=true` con el SHA original en ambos lados.
* **Pruebas:** `test_medio04_sonda_preserva_los_bytes_exactos` (paramétrica:
  CRLF, BOM-UTF-8, UTF-8-acentos),
  `test_medio04_restauracion_usa_bytes_no_texto` (incluye el CONTRASTE: el
  camino texto de R15.8 sí alteraba CRLF — documentado como razón del cambio).

## MEDIO-05 — El soak terminaba esperando un ID incorrecto

* **Repro (auditor):** activo ANTERIOR + terminal ANTERIOR con ejecución
  pedida NUEVA ⇒ devolvía ANTERIOR (`acepto_terminacion_ajena=true`).
* **Corrección:** identidad estricta cuando el POST devolvió `ejecucion_id`:
  `arrancado` sólo con activo de ESA ejecución; terminal sólo con el MISMO id;
  id ausente o distinto = inconcluso (se sigue esperando hasta la ventana de
  admisión, con diagnóstico que cita la ejecución esperada). Sin id en el
  POST, criterio heredado activo→terminal (servidores sin identidad).
* **Pruebas:** `test_medio05_soak_rechaza_activo_y_terminal_de_otra_ejecucion`
  (guion EXACTO del auditor), `test_medio05_soak_id_ausente_es_inconcluso…`,
  `test_medio05_soak_acepta_terminal_propio_antes_del_primer_sondeo`
  (MEDIO-07/R15.8 conservado), `test_medio05_soak_sin_ids_conserva_criterio…`,
  `test_medio05_soak_terminal_propio_tras_activo_propio`.

## BAJO-06 — Metadatos duplicados/obsoletos en el instalador

* **Corrección:** `$markersBase` = R15_7/R15_8/R15_9 sin duplicados;
  `$basesVersion` sin duplicados; mensaje de base desconocida = contrato real.
* **Prueba:** `test_bajo06_markers_y_bases_sin_duplicados`.

---

## Qué NO se tocó (alcance §5 de la auditoría)

Motor OCR, detección de ruptura, Tmax, semáforo, contratos Excel: sin cambios.
Cambios no-perimetrales limitados a la identidad del release
(`PATCH_BUILD`/`VERSION.txt`/cache-busters → `15.10.1-r15.9`) y a los
artefactos de instalador.

---

# Revisión v2 — dos brechas encontradas por la auditoría del paquete (2026-10-18)

## BRECHA-A (medio) — instalación directa R15.7→R15.9 dejaba tests históricos con literales

* **Reproducción (usuario):** `direct7to9.log` — árbol R15.7 + payload v1 +
  suite ⇒ `3 failed` (`test_identidad_r15_7_coherente_en_todo_el_paquete`,
  `test_backend_publica_salud_y_persistencia_segura`,
  `test_frontend_cache_r14`): las copias R15.7 de
  `test_v15_10_1_r15_7_instalador_base.py` y
  `test_v15_10_1_r14_auditoria_preventiva.py` fijan literales
  `15.10.1-r15.7`; R15.8 ya los había re-anclado y DISTRIBUIDO (están en su
  MANIFEST), pero una base R15.7 que salta a R15.9 directo nunca los recibe.
* **Corrección:** payload de convergencia = MANIFEST R15.8 (19) ∪ delta
  R15.9 (17) = **29 archivos**. Verificación: instalación directa R15.7 +
  payload v2 produce un árbol IDÉNTICO (`diff -r` vacío) al de R15.8 +
  payload v2, y la suite completa da **1145/8/0 en ambos**.
* **Prueba:** la propia réplica del usuario (su `installed9` ya daba
  319/7/0 porque recibía los re-anclados vía MANIFEST R15.8; ahora también
  el camino directo).

## BRECHA-B (bajo) — lector del registro con criterio distinto al de la sonda (BOM) y motivo sin detalle

* **Reproducción (usuario):** `bom_r158.log` vs `bom_r159.log` — un registro
  válido con BOM UTF-8: la sonda R15.9 lo acepta (bytes ⇒ `utf-8-sig`
  autodetectado) pero el loader R15.9 (texto estricto `utf-8`) lo marca
  «ilegible»; además el motivo perdió el detalle de R15.8
  («(Unexpected UTF-8 BOM (decode using utf-8-sig): …)» ⇒ v1 genérico).
* **Corrección:** `_leer_registro_o_respaldo` lee BYTES (mismo criterio que
  la sonda); `_cargar_inconsistencias` restaura el DETALLE del daño en el
  motivo («ilegible (JSONDecodeError: …)» / «(estructura no reconocida)»).
  Un registro corrupto sigue fail-closed y byte-intacto.
* **Pruebas (+2, persistentes):**
  `test_revision_registro_con_bom_carga_y_sobrevive_a_la_sonda` (guion del
  auditor: carga → sonda → bytes intactos → re-arranque) y
  `test_revision_registro_danado_reporta_el_detalle_en_el_motivo`.
  Pre-fix v1: ambas fallan (motivo genérico / BOM fail-closed en falso).


---

# Revisión v3 — auditoría independiente 2026-10-19

## MEDIO-A — `-VerifyOnly` confundido con comprobación de base

* **Repro del auditor:** el runbook sugería correr `INSTALAR_R15_9.bat
  -VerifyOnly` sobre una base R15.7/R15.8 sin instalar. El código omite la
  copia, luego contrasta todos los hashes del MANIFEST del destino: por ello
  debe fallar sobre una base anterior (y sí pasa si el payload ya está
  instalado). No se ejecutó PowerShell en Windows; hallazgo derivado de la
  secuencia del script y hashes.
* **Corrección:** runbook y README especifican que `-VerifyOnly` es sólo
  post-instalación; la compatibilidad de base se comprueba con el preflight
  del instalador normal antes de copiar. No se añade un modo `-CheckBase`
  porque no es necesario para este procedimiento de campo.

## MEDIO-B — esquema interno JSON no validado

* **Reproducción exacta:** `null` / `42` en `inconsistencias` lanzaban
  `AttributeError`; `aliases: 42` lanzaba `TypeError`; aliases mixtos se
  convertían a texto, migraban el registro y alteraban bytes.
* **Corrección:** `_validar_esquema_registro_inconsistencias` valida todo el
  payload (raí­z objeto, lista, entradas objeto, recurso texto no vacío,
  aliases lista de strings) ANTES de tocar estado y también antes de
  restaurar un respaldo. Un registro sintáctico pero mal formado activa
  recuperación, preserva el original y no lanza excepción.
* **Pruebas adversariales:** seis cuerpos del auditor (null, número, aliases
  escalar, aliases mixtos, recurso no-string y recurso vacío), más respaldo
  residual malformado sin target ⇒ todos con excepción no controlada nula,
  recuperación activa, cero entradas y bytes intactos. BOM/CRLF/truncado siguen
  cubiertos.

## BAJO-C — identidad, conteos y alcance de la suite

* Build v2 y v1 compartían la identidad `15.10.1-r15.9`. Este corte adopta
  `15.10.1-r15.9.1` en VERSION/backend/frontend/soak/instalador y en el
  nombre del ZIP; el instalador admite también la reinstalación de R15.9.
* Se corrige en README el conteo obsoleto de 17 pruebas/17 hashes; payload
  sigue 29 y endurecimiento ahora contiene 26 pruebas.
* El auditor externo reportó una suite amplia **844/29/5** en su
  reconstrucción incompleta y cuatro fallos base que también aparecen en
  R15.8; un quinto N17 pasó aislado (1/1), pero la ejecución conjunta quedó
  sin resolver. Se conserva ese dictamen: no se presenta ese banco como
  suite completa verde ni como certificación. Las pruebas de Windows y de
  campo AVI/GPU siguen pendientes.

## Decisión de calidad

R15.9.1 queda para **validación controlada**, no Production Ready. El cierre
  de los fallos de código aquí no reemplaza el banco de regresión completo ni
  §9-6/7/8 del runbook Windows (instalación/rollback, soak y ground truth).
