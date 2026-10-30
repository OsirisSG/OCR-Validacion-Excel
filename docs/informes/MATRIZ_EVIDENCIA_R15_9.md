# MATRIZ DE EVIDENCIA R15.9.1 — V-Matrix V15.10.1-r15.9.1

Árbol de trabajo del sandbox: `/home/user/vmatrix` = base
`codex/ocr-v15-8-1-organizacion` + overlay R15.6 (141/141) + payloads R15.7
(23/23) y R15.8 (19/19) + endurecimiento R15.9. Árbol control R15.8 pristino:
`/tmp/vm_r158_pristine` (los 19 archivos del payload R15.8 FINAL superpuestos
byte a byte sobre el R15.7 pristino).

## 1. Reproducción previa (R15.8) — los hallazgos del auditor, reproducidos

Método exigido: nada se declara corregido porque un changelog lo diga. Tres
evidencias independientes, todas sobre el árbol R15.8 pristino SIN corregir:

**(a) Script literal del auditor** (`evidencia_r159/r159_pre_fix_script_auditor_R15_8.json`
— resultados IDÉNTICOS a los publicados por el auditor, incluidos los SHA):

```json
{"sonda_crlf":       {"sonda_ok": true, "bytes_iguales": false,
                      "original_sha256": "fcaa1330…", "new_sha256": "e6ea0a7f…"},
 "sonda_interrupcion": {"registro_igual": false, "quedo_sonda": true},
 "soak_otra_ejecucion": {"acepto_terminacion_ajena": true, "devuelto": "ANTERIOR"}}
```

**(b) Snippet del verificador** (ALTO-01): ejecutado tal como está escrito en
`INSTALAR_R15_8.ps1` sobre el árbol R15.8 ⇒ **exit 33**
(`evidencia_r159/r159_pre_fix_alto01_verify_import.txt`).

**(c) Suite R15.9 nueva sobre el árbol R15.8**
(`evidencia_r159/r159_pre_fix_tests_sobre_R15_8.txt`):

```
11 failed, 6 passed, 13 skipped
```

Los 6 que pasan son anclas sin-falso-positivo que YA funcionaban en R15.8
(fail-closed sin respaldo, terminal propio antes del primer sondeo
MEDIO-07/R15.8, conflicto trivial) — anclan que la corrección R15.9 no rompe
lo que sí funcionaba. Para ALTO-01/ALTO-02 del instalador la evidencia
pre-fix es (b) más la auditoría misma (los tests de instalador R15.9 se
saltan en un árbol sin `INSTALAR_R15_9.ps1`).

## 2. Corridas del árbol R15.9 (post-corrección)

| Suite | Resultado |
|---|---|
| `test_v15_10_1_r159_endurecimiento.py` | **17 passed** |
| Instalador R15.9 (nuevo) | **13 passed** (incluye ejecución del snippet real: árbol vigente ⇒ 0; versión equivocada ⇒ 33) |
| Instaladores históricos (r15_7 + r15_8) | **20 passed** |
| Focal R15.9 (endurecimiento + instaladores) | **50 passed** |
| Par R15.7 (endurecimiento + campo + instalador, stub alineado a la API real) | **40 passed** |
| Bloque acumulado R15.x (glob `test_v15_10_1_r15*`, sin soak sintético) | **309 passed / 5 skipped** — cross-check: R15.8 medido por la auditoría 276 → R15.8 real 307 → R15.9 = 307 + 2 nuevos módulos (30) − 28 del instalador R15.8 ya contados… ver desglose abajo |
| Soak sintético heredado R15.4 (aparte) | **2 passed** |
| Frontend Node (`.cjs`) | **39/39 OK** |
| Doc tests (organizada + c1_c7) | **26 passed** |
| Suite completa del árbol de trabajo (`pruebas/`) | **1147 passed / 6 skipped / 0 fallos** (166.4 s, revisión v2) |
| Suite completa del árbol INSTALADO desde el paquete (payload sobre R15.8 pristino) | **1145 passed / 8 skipped / 0 fallos** (165.6 s, revisión v2) — los 2 skips extra son los tests de contrato que requieren los manifiestos congelados de R15.7/R15.8 (no presentes junto al árbol de prueba; se ejecutan en el árbol de trabajo) |
| Control: la MISMA suite sobre el árbol R15.8 pristino (antes de instalar) | **1115 passed / 6 skipped / 0 fallos** (172.5 s) — coincide con el cierre oficial de R15.8 |

Desglose del delta: control R15.8 = 1115; R15.9 (v2) añade EXACTAMENTE 32
pruebas (17 endurecimiento + 13 instalador + 2 de la revisión) y no retira
ninguna (focal R15.8 51/51; par R15.7 40/40) ⇒ 1115 + 32 = 1147 = árbol de
trabajo. **Cero regresiones.** El árbol instalado muestra 1145/8: mismas
pruebas, con los 2 tests de contrato saltados por ausencia de los manifiestos
congelados junto al árbol de prueba (limitación del entorno, no del paquete).

## 3. Correcciones R15.9 — correspondencia hallazgo → prueba

| Hallazgo (auditoría R15.8) | Corrección | Prueba que fallaba en R15.8 y pasa en R15.9 |
|---|---|---|
| ALTO-01 (verificador con literal) | versión por argumento `sys.argv[2]` desde `$PatchBuild` | `test_alto01_snippet_real_del_instalador_acepta_el_arbol_vigente` (exit 0) / `…rechaza_un_build_equivocado` (exit 33) |
| ALTO-02 (delta sobre bases viejas ⇒ híbrido) | bases R15.7/R15.8/R15.9 + `Assert-BaseIntegra` (32 claves por hash) | `test_alto02_tabla_cubre…`, `…el_arbol_vigente_satisface_el_contrato…`, `…un_hash_r15_6_rechazado…`, `…antes_de_copiar` |
| ALTO-03 (sonda sin backup) | respaldo durable + `_leer_registro_o_respaldo` | `test_alto03_interrupcion_deja_respaldo_y_el_arranque_recupera` (+5) |
| MEDIO-04 (CRLF→LF) | sonda en BYTES | `test_medio04_sonda_preserva_los_bytes_exactos` (CRLF/BOM/UTF-8) + contraste |
| MEDIO-05 (terminal ajeno aceptado) | identidad estricta por `ejecucion_id` | `test_medio05_soak_rechaza_activo_y_terminal_de_otra_ejecucion` (guion exacto del auditor) (+4) |
| BAJO-06 (marker duplicado) | listas únicas + mensaje real | `test_bajo06_markers_y_bases_sin_duplicados` |

## 4. Artefactos de reconstrucción (no defectos del parche)

Sin novedades respecto de R15.7/R15.8: bit ejecutable de `iniciar.command` /
`instalar.command` (git 100755; se restaura con `chmod +x` en árboles
re-creados) y el enlace histórico a `RESULTADOS_PRUEBAS_V15_9_2.md` (sólo en
copias recuperadas de paquetes antiguos).

**Nota de transparencia sobre el paquete R15.8:** su
`V-MATRIX_R15_8.patch` llevaba la MATRIZ de evidencia en versión intermedia
(309/5) mientras el payload llevaba la final (307 + cross-check). El parche
aplicaba limpio y el código era idéntico; el desfase era sólo de ese
documento. En R15.9 el parche se genera AL FINAL (tras toda edición de
documentos) y la verificación final compara patch contra payload byte a byte.

## 5. Inventario del paquete

* Payload (revisión v2): **29 archivos** = MANIFEST R15.8 (19) ∪ delta
  R15.9 (17; 7 solapados) — DOCTRINA DE CONVERGENCIA: cualquier base
  aceptada (R15.7/R15.8/R15.9) acaba en el MISMO árbol. Los 12 ficheros de
  la unión son byte-idénticos al MANIFEST R15.8 (verificado por SHA-256);
  el contrato `Assert-BaseIntegra` garantiza además la integridad de la base.
* `MANIFEST_SHA256_R15_9.txt` (29 entradas) generado desde el árbol real;
  `SHA256SUMS.txt` con TODOS los artefactos del ZIP; patch
  `V-MATRIX_R15_9.patch` (**17 archivos**: el delta real contra R15.8 — los
  12 de la unión no cambian nada en una base R15.8, por eso no figuran en el
  diff) construido desde lista explícita al final de toda edición;
  `git apply` verificado contra el árbol R15.8 pristino → árbol final
  byte-idéntico al del payload (17 deltas + 12 iguales).

## 6. Pendiente de campo (inalcanzable desde este entorno)

Instalador y rollback en Windows real (ahora con los escenarios 2 y 3 del
contrato de base: híbrido e incompleto), archivo bloqueado por Excel/editor,
CIM/WMI, Defender/AV vs `replace`, ACL del archivo de recuperación, disco casi
lleno, rutas con espacios/acentos/largas, soak real de 100–200 análisis sobre
CPU/GPU objetivo, ground truth humano frame a frame y la prueba opcional de
interrupción de la sonda — runbook: `validacion_campo/VALIDACION_CAMPO_R15_9.md`.

## 7. REVISIÓN v2 — auditoría independiente del paquete entregado (2026-10-18)

El usuario replicó la entrega v1 (ZIP `5903c3a6…`) en su propio entorno
(`uploads/comandos.txt`, `integrity.json`, `*.log`). Resultados y cierre:

| Réplica del usuario | Resultado | Estado |
|---|---|---|
| Integridad de los 4 ZIP (CRC, duplicados, SUMS/MANIFEST) | R15.9 23/23 + 17/17, sha del ZIP coincide | ✓ |
| Focal 5 ficheros sobre instalado | 67 passed / 2 skipped | ✓ |
| `pytest test_v15_10_1_r15*.py -k 'not soak'` | **319 passed / 7 skipped / 0 fallos** | ✓ |
| `node --test pruebas/*.cjs` | **61/61** | ✓ |
| `git apply --check` del patch sobre R15.8 | OK | ✓ |
| `git apply --check` del patch sobre R15.7 | FAIL (esperado: el patch es el DELTA vs R15.8; para bases R15.7 está el instalador, que acepta R15.7 por contrato) | ✓ documentado |
| **Instalación DIRECTA R15.7→R15.9 + suite (4 ficheros)** | **3 failed** (tests históricos R15.7/R14 con literales de versión) | ✗ ⇒ corregido en v2 |

Causa raíz de los 3 fallos: el payload v1 llevaba sólo el delta R15.9; una
instalación DIRECTA desde R15.7 (camino permitido por el contrato ALTO-02)
se quedaba con las copias R15.7 de `test_v15_10_1_r15_7_instalador_base.py`
y `test_v15_10_1_r14_auditoria_preventiva.py` (fijaban `15.10.1-r15.7`
literal), que las rondas R15.8 ya habían re-anclado y distribuido.
**Corrección v2:** payload = MANIFEST R15.8 ∪ delta R15.9 (29 archivos) ⇒
verificado en esta misma máquina: instalación directa R15.7 + payload v2 ≡
instalación R15.8 + payload v2 (árboles IDÉNTICOS, `diff -r` vacío) y suite
completa **1145/8/0 en AMBOS**.

Además, el guion BOM del usuario (`bom_r158.log` vs `bom_r159.log`) destapó
que el lector del registro (texto estricto) y la sonda (bytes, utf-8-sig)
usaban criterios DISTINTOS para un mismo fichero con BOM, y que el motivo
fail-closed había perdido el detalle de diagnóstico de R15.8. **Corrección
v2:** lector en BYTES (mismo criterio que la sonda; BOM aceptado, corrupto
sigue fail-closed) + motivo con el detalle del daño; +2 pruebas persistentes
(guion BOM del auditor y detalle del motivo) → focal **103 passed**.

Árboles de la revisión (reconstruidos: repo_principal `5fbef43` ∪
repo_parches `V15.10.1-R15_6` ∪ ficheros no-payload del workspace ∪ payloads
congelados por manifiesto): control R15.8 **1115/6/0** (sin cambios),
instalado **1145/8/0**, directo 7→9 **1145/8/0**, workspace **1147/6/0**.
El único incidente fue el artefacto conocido del bit ejecutable de
`*.command` (restaurado con `chmod +x`; cubierto por el test c5).


## 8. Revisión v3 — auditoría independiente 2026-10-19

| Hallazgo nuevo | Evidencia/reproducción | Corrección | Pruebas post-fix |
|---|---|---|---|
| MEDIO-A: `-VerifyOnly` sobre base anterior no es un check de base | Auditor calculó faltantes/hash-distintos en R15.7 (18/11) y R15.8 (9/8); código verifica todos los hashes finales al saltar copia | Runbook/README lo limitan a destino ya instalado; base se valida en preflight normal | Documentación revisada; Windows PowerShell no disponible en sandbox |
| MEDIO-B: entradas internas JSON mal tipadas | Script independiente: null/42 ⇒ AttributeError; aliases int ⇒ TypeError; aliases mixtos mutan bytes | validador integral previo a migración/restauración; recovery fail-closed, bytes preservados | 7 escenarios de esquema adversariales verdes; R15.9 endurecimiento 26/26 |
| BAJO-C: build id duplicado y conteo README obsoleto | auditor comparó ZIP v1/v2 con PATCH_BUILD idéntico; encontró 17/17 y 17 tests obsoletos | identidad `15.10.1-r15.9.1`; README actualizado (29 payload, 26 pruebas) | identidad validada por tests de paquete |

**Alcance externo conservado:** auditor reconstruyó árboles con 656 archivos y
confirmó igualdad directo/secuencial, integridad 36/36 ZIP, MANIFEST 29/29,
SUMS 35/35, Git apply 29/29 y node 61/61. Sin embargo su suite amplia
terminó en **844 passed / 29 skipped / 5 failed** (cuatro aparentan ser
limitaciones del banco y el quinto N17 sólo pasó aislado). Por tanto el
resultado no se contabiliza como suite completa aprobada.

**Pendiente:** suite completa sin fallos en banco canónico, PowerShell Windows
real, rollback, soak 150 AVI reales y Tmax/semáforo contra ground truth.


## 9. Verificación local de R15.9.1 (2026-10-19)

| Verificación | Resultado | Dictamen |
|---|---:|---|
| Suite completa Python del árbol de trabajo | **1155 passed / 6 skipped / 0 failed** (140.7 s) | ✓ |
| Focal endurecimiento + instalador R15.9.1 + compatibilidad R15.8 | **53 passed** | ✓ |
| Frontend Node del árbol de trabajo | **55 passed / 0 failed** | ✓ |
| Guion independiente exacto del auditor (BOM, CRLF, truncado, null, 42, aliases int/mixtos) | 7/7 sin excepción no controlada; BOM/CRLF cargan; truncado/tipos inválidos recovery=true; bytes intactos | ✓ |
| Respaldo residual malformado sin target | recovery=true; cero entradas; target ausente; respaldo byte-intacto | ✓ |
| Suite completa en reconstrucción externa del usuario | 844/29/5 en el banco incompleto reportado | No se oculta ni se cuenta como aprobación; hallazgo de entorno queda abierto |
| Suite final del ZIP instalado desde R15.8 (árbol reconstruido) | **1153 passed / 7 skipped / 1 failed** | El fallo único es `test_raiz_conserva_solo_readme_y_txt_funcionales`; se reproduce idéntico en el control R15.8 (legacy docs de la reconstrucción); no se declara 100% verde |
| Instalación directa R15.7→R15.9.1 (payload 29) | **1153 passed / 7 skipped / 1 failed**; contenido idéntico al secuencial en 783 archivos | Igual fallo de organización documental base; no atribuido como regresión del payload |
| Suite completa workspace R15.9.1 | **1155 passed / 6 skipped / 0 failed** | ✓ |
| Frontend Node workspace | **55/55 passed** | ✓ |
| PowerShell Windows y campo AVI/Tmax | no ejecutado | pendiente §9-6/7/8 |

Identidad v3: `15.10.1-r15.9.1`; README raíz y `VERSION.txt` coinciden;
cinco cache-busters frontend coinciden; hashes actuales incluidos en
`Assert-BaseIntegra` para permitir reinstalar R15.9.1.
