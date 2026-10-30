# MATRIZ DE EVIDENCIA R15.8 — V-Matrix V15.10.1-r15.8

Árbol de trabajo del sandbox: `/home/user/vmatrix` = base
`codex/ocr-v15-8-1-organizacion` + overlay R15.6 (141/141) + payload R15.7
(23/23) + endurecimiento R15.8. Árbol control R15.7 pristino:
`/tmp/vm_r157_pristine` (los 23 archivos del payload R15.7 congelado
restaurados byte a byte sobre el árbol, con los ficheros R15.8 retirados).

## 1. Reproducción previa (R15.7) — las pruebas nuevas FALLAN

Método exigido por la dirección de trabajo: nada se declara corregido porque
un changelog lo diga. Las 18 pruebas de
`pruebas/test_v15_10_1_r158_endurecimiento.py` se ejecutaron PRIMERO sobre el
árbol control R15.7 SIN las correcciones (evidencia en
`evidencia_r158/r158_pre_fix_repro_previa_R15_7.txt` de la entrega):

```
13 failed, 5 passed in 3.61s

FAILED test_alto01_sonda_falla_si_el_target_no_es_un_archivo_regular
FAILED test_alto02_migracion_relativa_en_documento_bloquea
FAILED test_alto02_registro_relativo_heredado_bloquea
FAILED test_alto03_evaluar_banco_externo_bloqueado_en_modo_recuperacion
FAILED test_alto03_toda_ruta_mutante_declara_politica_de_recuperacion
FAILED test_alto03_guard_transversal_bloquea_mutantes_y_permite_la_salida
FAILED test_alto04_revision_carpeta_bloqueada_con_inconsistencia_activa
FAILED test_alto04_revision_externa_bloqueada_con_inconsistencia_activa
FAILED test_medio05_alertas_respetan_el_bloqueo_de_recuperacion
FAILED test_medio06_listado_deduplica_el_mismo_incidente
FAILED test_medio07_soak_acepta_terminal_antes_del_primer_sondeo
FAILED test_medio08_soak_no_hereda_ejecucion_id_entre_iteraciones
FAILED test_soak_identidad_por_defecto_r15_8
```

Correspondencia con los 8 hallazgos de la revalidación (§5): los 8 quedan
reproducidos como fallos AL MENOS por una prueba (ALTO-01×1, ALTO-02×2,
ALTO-03×3, ALTO-04×2, MEDIO-05×1, MEDIO-06×1, MEDIO-07×1, MEDIO-08×1). Las 5
que pasan sobre R15.7 son guardas sin-falso-positivo (la sonda no daña un
registro sano, la resolución por alias ya funcionaba, un terminal ajeno no se
confundía porque el soak R15.7 rechazaba la llamada nueva, el confinamiento
trivial ya no mapeaba) — anclan que la corrección no rompe lo que sí funcionaba.
Para BAJO-09/10/11 la evidencia pre-fix es la propia revalidación
(`static_notes.txt`: README «R15.6», mensajes «R15.6» del instalador, runbook
«17/17»).

## 2. Corridas del árbol R15.8 (post-corrección)

| Suite | Resultado |
|---|---|
| `test_v15_10_1_r158_endurecimiento.py` | **18 passed** |
| Instaladores (r15_8 nuevo 13 + r15_7 histórico 10 + r15_6 histórico 10) | **33 passed** |
| Focal R15.8 (endurecimiento + instaladores) | **51 passed** |
| Par R15.7 (endurecimiento 22 + campo 8 + instaladores 10) | **40 passed** |
| Bloque acumulado R15.x (`pruebas/test_v15_10_1_r15*.py` por glob, sin soak sintético) | **307 passed / 5 skipped** — cross-check: la revalidación midió 276 sobre R15.7; 276 + 31 = 307 |
| Suite completa del árbol (`pruebas/`) | **1115 passed / 6 skipped / 0 fallos** (152.0 s) |
| La MISMA suite sobre el árbol INSTALADO desde el ZIP final | **1115 passed / 6 skipped / 0 fallos** (155.5 s) |
| Control: la MISMA suite sobre el árbol R15.7 pristino (antes de instalar) | **1084 passed / 6 skipped / 0 fallos** (152.8 s) |
| Δ | **+31 = 18 endurecimiento + 13 instalador R15.8** ⇒ cero regresiones |
| Soak sintético heredado R15.4 (aparte) | **2 passed** |
| Frontend Node (`.cjs`), árbol de trabajo y árbol instalado | **39/39 OK** en ambos |
| Doc tests (organizada + c1_c7) | **26 passed** |

Notas de la ronda de identidad: `test_v15_10_1_r14_auditoria_preventiva.py`
(cache/frontend y PATCH_BUILD) pasó a leer la versión de `VERSION.txt` (fuente
única) para no acoplarse a un literal por release;
`test_v15_10_1_r15_7_instalador_base.py` pasó a modo HISTÓRICO (verifica el
instalador R15.7 congelado, ya no la identidad del árbol) — el patrón
SUPERSEDE ya usado con el R15.6.

## 3. Artefactos de reconstrucción (no defectos del parche)

Misma característica que R15.7 (§3-bis de su matriz), sin novedades:

* **Bit ejecutable** de `iniciar.command`/`instalar.command`: los árboles
  re-creados con herramientas que no preservan modos pierden el `100755` que
  el repositorio declara en git. Ninguno viaja en payload ni parche; en los
  árboles de verificación se restaura con `chmod +x`.
* **Enlace histórico** a `RESULTADOS_PRUEBAS_V15_9_2.md`: sólo las copias del
  README histórico recuperadas de paquetes antiguos lo contienen; la copia del
  árbol vigente no enlaza nada roto.

## 4. Inventario del paquete (por confirmar en el empaquetado)

* Payload: **19 archivos** — sólo los nuevos/modificados de esta ronda (la
  instalación es acumulativa sobre el árbol R15.7 ya publicado).
* `MANIFEST_SHA256_R15_8.txt` generado desde el árbol real; `SHA256SUMS.txt`
  con TODOS los artefactos del ZIP; patch `V-MATRIX_R15_8.patch` construido
  desde lista explícita sobre el árbol R15.7 (`git apply` verificado).

## 5. Pendiente de campo (inalcanzable desde este entorno)

Instalador y rollback en Windows real, archivo bloqueado por Excel/editor,
CIM/WMI, Defender/AV vs `replace`, ACL del archivo de recuperación, disco
casi lleno, rutas con espacios/acentos/largas, soak real de 100–200 análisis
sobre CPU/GPU objetivo y ground truth humano frame a frame — runbook:
`validacion_campo/VALIDACION_CAMPO_R15_8.md` (§9-6/7/8).
