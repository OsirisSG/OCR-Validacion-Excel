# CHANGELOG R15.9.1 — V-Matrix V15.10.1-r15.9.1 (revisión de auditoría)

**Fecha:** 2026-10-18 · **Identidad:** `15.10.1-r15.9` · **Parche INCREMENTAL**
sobre un árbol R15.7/R15.8 completo (contrato nuevo, ver §ALTO-02).

**Origen:** auditoría técnica independiente de R15.8
(`AUDITORIA_INDEPENDIENTE_R15_8_20261018.md`, dictamen «NO APTO AÚN PARA
LIBERACIÓN GENERAL»). R15.9 cierra sus tres bloqueadores (ALTO-01/02/03), sus
dos medios (MEDIO-04/05) y su hallazgo bajo (BAJO-06) **sin funciones nuevas y
sin tocar OCR, Tmax, semáforo ni plantilla Excel** (orden de cierre §5 de esa
auditoría, puntos 1–4; el punto 5 —suites completas y pruebas Windows/reales—
se documenta en la matriz de evidencia y queda lo no-emisible como campo).

---

## 1. Hallazgos cerrados

| Hallazgo | Título | Corrección | Pruebas |
|---|---|---|---|
| ALTO-01 | El verificador del instalador comparaba contra el literal `'15.10.1-r15.7'` ⇒ toda instalación correcta salía 33 | `Verify-ImportResolution($Python, $BuildEsperado)`: la versión viaja por ARGUMENTO desde `$PatchBuild` (`sys.argv[2]`); la suite EJECUTA el snippet real extraído del instalador (acepta el árbol vigente = 0, rechaza versión equivocada = 33) | `test_alto01_*` (3) |
| ALTO-02 | El instalador declaraba bases R14…R15.8 pero el paquete sólo lleva el delta ⇒ árbol HÍBRIDO sobre R15.6 | Contrato real declarado y APLICADO: bases restringidas a R15.7/R15.8/R15.9 + `Assert-BaseIntegra` verifica el HASH de las 32 claves de los releases base (unión R15.7∪R15.8 ∪ modificados R15.9) ANTES de copiar; árbol híbrido/incompleto aborta sin modificar nada | `test_alto02_*` (4) |
| ALTO-03 | La sonda sustituía el registro real sin respaldo: un corte abrupto entre sustitución y restauración perdía las entradas (repro: `SystemExit` ⇒ `quedo_sonda=true` sin vía de recuperación) | Respaldo DURABLE del registro (bytes, fsync+replace+relectura) ANTES de la sonda + protocolo de recuperación al reinicio (`_leer_registro_o_respaldo`): el arranque restaura el registro byte a byte, recarga las entradas y NO activa modo recuperación; sin respaldo utilizable el fail-closed R15.6 se conserva | `test_alto03_*` (6) |
| MEDIO-04 | La restauración en modo TEXTO normalizaba CRLF→LF: registro CRLF salía con otro SHA-256 | La sonda opera a nivel de BYTES (`_escribir_bytes_verificados`): CRLF/BOM/UTF-8 preservados exactos; pruebas con CRLF, BOM y acentos | `test_medio04_*` (4) |
| MEDIO-05 | El soak aceptaba como final un terminal AJENO tras observar cualquier activo (repro: activo ANTERIOR + terminal ANTERIOR ⇒ devolvía ANTERIOR) | Identidad ESTRICTA con `ejecucion_id` esperado: el inicio sólo se marca con un activo de ESA ejecución y el terminal sólo se acepta con el MISMO id; id ausente o distinto = evidencia inconclusa (se sigue esperando). Sin id en el POST se conserva el criterio heredado activo→terminal | `test_medio05_*` (5) |
| BAJO-06 | `$markersBase` duplicaba el marker R15.8; mensaje de error citaba bases inexistentes | Listas únicas (test de duplicados) y mensaje alineado con el contrato real («parche incremental, requiere R15.7/R15.8 completo») | `test_bajo06_*` (1) |

Detalle por hallazgo: `docs/informes/INFORME_R15_9_POR_HALLAZGO.md`.
Matriz de evidencia: `docs/informes/MATRIZ_EVIDENCIA_R15_9.md`.

## 2. Cambios principales

### ALTO-01 — versión por argumento en el verificador

* `python -c $code $Target $BuildEsperado` y en el snippet
  `sys.argv[2]` — el literal que quedaba obsoleto en cada release desaparece
  del contrato (un solo `$PatchBuild`).
* Prueba contractual: se extrae el snippet REAL del `.ps1` y se ejecuta sobre
  el árbol vigente (exit 0) y contra un build equivocado (exit 33).

### ALTO-02 — contrato de base íntegra (decisión de diseño documentada)

* Opción (b) del auditor: restringir la base y comprobar su integridad por
  hash, no sólo marker/VERSION.
* `Assert-BaseIntegra` (se ejecuta tras `Assert-BaseConocida`, ANTES de leer
  el manifiesto ni copiar): cada clave del contrato (32: unión de los 23 del
  payload R15.7 y los 19 del R15.8) debe existir (si era del release R15.7) y
  tener un hash ∈ {contenido R15.7, contenido R15.8, contenido R15.9}.
* Un árbol R15.6 (con o sin VERSION editada) no tiene los hashes del contrato
  ⇒ aborta con `BASE HIBRIDA O MODIFICADA` / `BASE INCOMPLETA`, cero archivos
  modificados. La suite cruza el contrato con el manifiesto R15.6 auditado y
  verifica que SUS hashes se rechazan.
* Consecuencia operativa: para actualizar desde R15.6 o anteriores hay que
  instalar primero el paquete R15.7 completo (el instalador lo indica).

### ALTO-03 — sonda con respaldo durable + recuperación al arranque

* Antes de tocar el target, `_sonda_recuperacion` escribe
  `estado_inconsistente.json.respaldo_sonda` con
  `_escribir_bytes_verificados` (temporal + fsync + replace + relectura).
* `_leer_registro_o_respaldo()` (arranque): registro sano ⇒ datos + limpieza
  de respaldo residual; registro dañado/ausente ⇒ restauración byte a byte
  desde el respaldo + sus datos; nada utilizable ⇒ `None` y el llamador
  activa modo recuperación SOLO si el target existía (instalación fresca sin
  registro sigue siendo estado normal).
* Repro del auditor verificado: `SystemExit` tras la sustitución deja
  `quedo_sonda=true` (inevitable) PERO el respaldo contiene los bytes
  originales y el siguiente arranque recupera `carpeta:CASO1` sin modo.

### MEDIO-04 — sonda byte a byte

* Lectura (`read_bytes`) + escritura binaria verificada + restauración binaria:
  CRLF, BOM-UTF-8 y UTF-8 con acentos salen con el MISMO SHA-256 tras la
  sonda (tests con los tres casos; el SHA del repro del auditor cambia de
  `e6ea0a7f…` a `fcaa1330…` = el original).

### MEDIO-05 — soak con identidad estricta

* `_esperar_pipeline(..., ejecucion_objetivo)`: con id esperado, un activo o
  terminal de otra ejecución —o sin id— NO marca inicio ni acepta fin
  (inconcluso); se agota la ventana de admisión con diagnóstico que incluye
  la ejecución esperada. MEDIO-07 (R15.8) se conserva: terminal propio antes
  del primer sondeo se acepta. La prueba reproduce el guion EXACTO del
  auditor (activo ANTERIOR + terminal ANTERIOR ⇒ no se acepta).

### BAJO-06 — metadatos limpios

* `$markersBase` sin duplicados (R15_7, R15_8, R15_9 — una vez cada uno),
  `$basesVersion` sin duplicados, mensaje de error = contrato real.

## 3. Nota sobre el paquete R15.8 (detectado en esta ronda)

Al reconstruir la evidencia se detectó que el `V-MATRIX_R15_8.patch` enviado
llevaba la MATRIZ de evidencia en su versión intermedia (309/5) mientras el
payload llevaba la final (307 + cross-check): el parche aplicaba limpio pero
ese documento difería del payload. Sin impacto en código. En R15.9 el parche
se genera AL FINAL (tras toda edición de documentos) y la verificación final
compara patch contra payload byte a byte. R15.9 sustituye íntegramente al
paquete R15.8.

## 4. Compatibilidad

* `soak_r157.py` conserva nombre y aliases (`PATCH_BUILD_R157/R158` → apuntan
  a `15.10.1-r15.9`); el test de identidad del soak es version-aware.
* `test_v15_10_1_r15_8_instalador_base.py` pasa a HISTÓRICO (verifica el
  instalador R15.8 congelado); la identidad vigente la verifica el R15.9
  (patrón SUPERSEDE de la serie).
* `test_v15_10_1_r14_auditoria_preventiva.py` ya era version-aware (lee
  VERSION.txt): no cambia en esta ronda.

## Revisión v2 (2026-10-18, tras la auditoría del paquete entregado)

* **Payload de convergencia (29 archivos)** = MANIFEST R15.8 (19) ∪ delta
  R15.9 (17): una instalación DIRECTA R15.7→R15.9 ahora entrega también los
  tests históricos re-anclados por R15.8 (`test_v15_10_1_r15_7_instalador_base.py`,
  `test_v15_10_1_r14_auditoria_preventiva.py`, `conftest.py`,
  `validar_tmax_semaforo.py`, VALIDACIONES_R15_7/R15_8 y los artefactos
  R15.8), dejando el MISMO árbol que partir de R15.8 (verificado con
  `diff -r` vacío y suite 1145/8/0 en ambos caminos). El patch sigue siendo
  el delta de 17 archivos contra R15.8 (los 12 adicionales no cambian nada
  sobre R15.8).
* **Lector del registro en BYTES** (mismo criterio que la sonda):
  `json.loads` sobre bytes detecta `utf-8-sig`, así que un registro válido
  con BOM (re-guardado con un editor de Windows) ya NO se reporta
  «ilegible» en falso; un fichero corrupto sigue en fail-closed.
* **Motivo con detalle de diagnóstico restaurado** (comportamiento R15.8):
  «registro de inconsistencias ilegible (JSONDecodeError: …)» en vez del
  mensaje genérico.
* +2 pruebas persistentes en `test_v15_10_1_r159_endurecimiento.py` (19 en
  total): guion BOM del auditor (carga + sonda + re-arranque) y detalle del
  motivo en fail-closed. Tabla-contrato regenerada (hashes finales).
* Números v2: workspace **1147/6/0** · instalado **1145/8/0** · directo
  R15.7→R15.9 **1145/8/0** · control R15.8 **1115/6/0** · focal R15.9+R15.8+R15.7
  **103 passed** · node 61/61 (réplica del usuario).

## Revisión v3 — R15.9.1 (2026-10-19)

* Identidad de build nueva `15.10.1-r15.9.1` en `VERSION.txt`, backend,
  cinco cache-busters frontend, soak e instalador; R15.9 v1/v2 quedan
  distinguibles y no se sobrescriben. El instalador sigue aceptando como
  bases íntegras R15.7, R15.8, R15.9 y R15.9.1.
* MEDIO-A auditor: el runbook ahora limita `-VerifyOnly` a verificar el
  payload de destino ya instalado; la aceptación de base se prueba durante
  preflight del instalador normal. No se afirma que `-VerifyOnly` verifique
  una base aún en R15.7/R15.8.
* MEDIO-B auditor: validación de esquema completo del registro antes de
  migrar: cada entrada debe ser objeto, `recurso` texto no vacío y `aliases`
  lista de textos. Esquema inválido activa recuperación, sin excepción
  descontrolada, mutación parcial ni modificación de bytes. +7 casos de esquema y +1 prueba de runbook
  (26 de endurecimiento; +14 del instalador en total).
* BAJO-C auditor: README del paquete ya no contiene recuentos obsoletos de
  17/17 ni afirma sólo 17 tests; los conteos corresponden a 29 payload y 26
  pruebas de endurecimiento.
* No se modifican OCR, detección de ruptura/apertura, Tmax, semáforo ni Excel.

### Resultados de verificación del corte R15.9.1

* Suite workspace: **1155 passed / 6 skipped / 0 failed**; Node workspace:
  **55/55**; focal R15.9.1/instalador/compatibilidad R15.8: **53/53**.
* Árboles R15.8+payload y R15.7 directo+payload (783 archivos, ignorando
  cachés de ejecución): idénticos. Sus suites amplias: **1153/7/1**; el único
  fallo de organización documental se reproduce en el control R15.8
  reconstruido y no se presenta como verde.
* Informe externo entregado por el usuario: **844/29/5** en un banco
  incompleto; se conserva el resultado y la reserva, sin certificar producción.
