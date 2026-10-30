# MATRIZ DE EVIDENCIA R15.7 — V-Matrix V15.10.1-r15.7

Árbol reconstruido y verificado en este sandbox:
* Base: repositorio principal `OCR-Validacion-Excel`, rama
  `codex/ocr-v15-8-1-organizacion` (base diagnóstica histórica del proyecto).
* Overlay: los 141 archivos de `MANIFEST_SHA256_R15_6.txt`
  (**141/141 hashes OK**) → identidad `15.10.1-r15.6`.
* Soporte de base recuperado del árbol histórico instalado
  (`codigo_final_referencia` del repositorio de parches): `utilidades/proyectos.py`,
  `utilidades/identidad.py`, `criterios_usuario.py`, `estructura.py`,
  `generar_excel.py`, `inventario.py`, `plantilla_empresarial.py`,
  `AGENTS.md`, 27 módulos de `pruebas/`, los 6 `skills/*/SKILL.md` y
  `.agents/` (incluye 3 `.cjs` legados).

## 1. Reproducción previa (R15.6) — las 22 pruebas nuevas FALLAN

```
$ pytest pruebas/test_v15_10_1_r157_endurecimiento.py   # árbol R15.6
21 failed, 1 passed
FAILED test_alto01_exito_no_resuelve_inconsistencia_ajena
FAILED test_alto01_peticion_en_vuelo_no_desbloquea_el_caso
FAILED test_alto01_solo_la_api_de_recuperacion_levanta_el_bloqueo
FAILED test_alto02_inconsistencia_de_carpeta_bloquea_verificar_imagen
FAILED test_alto02_inconsistencia_de_imagen_bloquea_operacion_de_carpeta
FAILED test_alto02_inconsistencia_de_carpeta_bloquea_revision_de_video
FAILED test_alto02_inconsistencia_de_carpeta_bloquea_rotacion
FAILED test_alto02_identidad_canonica_de_recursos
FAILED test_alto02_entradas_heredadas_se_migran_al_cargar
FAILED test_alto03_arranque_fail_closed_sin_registro_ni_centinela
FAILED test_alto03_sonda_ok_no_bloquea            (no existe la sonda)
FAILED test_alto03_doble_ubicacion_del_centinela   (no existe el espejo)
FAILED test_medio04_fallo_incorporar_uniones_no_convierte_en_error
FAILED test_medio04_fallo_entrenamiento_visual_no_convierte_en_error
FAILED test_medio04_error_inesperado_del_aprendizaje_tampoco_es_fatal
FAILED test_medio05_marca_externa_sin_expected_revision_409
FAILED test_medio05_restaurar_externa_sin_expected_revision_409
FAILED test_medio05_rotacion_externa_sin_expected_revision_409
FAILED test_bajo07_resolucion_reporta_centinela_no_eliminado
FAILED test_bajo07_resolucion_normal_elimina_el_centinela (sin advertencia/flag)
FAILED test_p2_inventario_del_arbol_destino        (no existe el módulo)
```

Repro crítico del auditor reproducido literalmente:
* ALTO-01 → `E AssertionError: ALTO-01: una transacción exitosa ajena resolvió
  la inconsistencia`.
* ALTO-02 → la verificación avanzó y el documento pasó de revisión con el caso
  bloqueado (`DID NOT RAISE`).
* ALTO-03 → arranque sin registro ni centinela = guard permitido (`DID NOT
  RAISE`).
* MEDIO-04 → excepción escapando del endpoint con commit ya guardado.
* MEDIO-05 → rama externa aceptando `expected_revision=None` con revisión > 0.

## 2. Reproducción posterior (R15.7) — todo verde

| Bloque | Comando | Resultado |
|---|---|---|
| Endurecimiento R15.7 | `pytest pruebas/test_v15_10_1_r157_endurecimiento.py` | **22 passed** (fallan 21/22 en R15.6) |
| Bloque crítico acumulado R15.2→R15.7 | `pytest` (19 módulos R15.x) | **179 passed** |
| Instalador R15.7 (fuente, sin pwsh) | `pytest pruebas/test_v15_10_1_r15_7_instalador_base.py` | **10 passed** |
| Suite Python completa del árbol de INSTALACIÓN SIMULADA (reconstrucción R15.6 + payload R15.7 completo, 23 archivos) | `pytest pruebas/ --ignore=pruebas/test_v15_10_1_r154_soak_analisis_video.py` | **1082 passed / 6 skipped / 0 fallos** (§3-bis) |
| Herramental de campo (soak `--simular` con servidor HTTP de prueba + Tmax/semáforo sintético) | `pytest pruebas/test_v15_10_1_r157_validacion_campo.py` | **8 passed** |
| Frontend Node | `node pruebas/*.cjs` (39 archivos del árbol reconstruido) | **39/39 OK** |

Cobertura por hallazgo (17 pruebas específicas + 5 de contrato/arranque):

| Hallazgo | Pruebas | Resultado R15.6 | Resultado R15.7 |
|---|---|---|---|
| ALTO-01 | 3 | fallan | pasan |
| ALTO-02 | 6 | fallan | pasan |
| ALTO-03 | 3 | fallan | pasan |
| MEDIO-04 | 3 | fallan | pasan |
| MEDIO-05 | 4 | fallan | pasan |
| BAJO-07 | 2 | fallan | pasan |
| P2/BAJO-06 | 1 | falla | pasa |

## 3. Pruebas heredadas actualizadas al contrato R15.7 (trazabilidad)

Ninguna se relajó: se ajustaron al contrato nuevo con comentario explícito.

| Archivo | Cambio | Motivo |
|---|---|---|
| `pruebas/test_v15_10_1_r155_transaccion_coordinada.py` | el recurso afectado se verifica como identidad canónica (`carpeta:<id>#video:V1`) y la resolución usa el alias heredado | ALTO-02 |
| `pruebas/test_v15_10_1_r156_documento_externo.py` | carreras externas: la pestaña desactualizada recibe 409, recarga la revisión y reintenta; se siguen verificando AMBOS cambios persistidos | MEDIO-05 |
| `pruebas/test_v15_10_1_r14_auditoria_preventiva.py` | build publicado y cache-busting pasan a `15.10.1-r15.7` | bump de identidad |
| `pruebas/test_restaurar_texto_unittest.py` | el arnés AST inyecta los constructores de identidad canónica del backend (no una copia) | ALTO-02 |
| `pruebas/test_v15_10_1_r15_6_instalador_base.py` | conserva la verificación del instalador R15.6 (histórico) y delega la identidad del árbol vigente al módulo R15.7 | bump de identidad |
| `pruebas/conftest.py` | aísla el centinela espejo en `tmp` (ninguna prueba escribe en el HOME real) | ALTO-03 |

## 3-bis. Comparación R15.6 ↔ R15.7 y artefactos de la RECONSTRUCCIÓN

La suite completa se ejecutó sobre dos árboles idénticos salvo el parche,
derivados de la misma reconstrucción del entorno:

| Árbol | Comando | Resultado |
|---|---|---|
| R15.6 (control, ANTES de instalar) | `pytest pruebas/ --ignore=...soak...` | **1042 passed / 6 skipped / 0 failed** |
| R15.7 (DESPUÉS de instalar el payload del ZIP, 23 archivos) | `pytest pruebas/ --ignore=...soak...` | **1082 passed / 6 skipped / 0 failed** |

La diferencia (40 pruebas) es exactamente la cobertura nueva que trae el
payload: 22 (endurecimiento) + 8 (herramental de campo) + 10 (instalador
R15.7). **Cero regresiones atribuibles al parche**: ningún módulo que pasa en
R15.6 falla en R15.7, y el bloque R15.x completo pasa (284 passed / 6 skipped).

### Artefactos de la reconstrucción (no son defectos del parche)

Dos comportamientos aparecieron al re-crear el árbol en el sandbox y quedan
caracterizados para que nadie los confunda con regresiones de R15.7:

1. **Enlace local a `RESULTADOS_PRUEBAS_V15_9_2.md`.** Algunas copias de
   `docs/historial/README_CORRECCIONES_VERSIONES.md` recuperadas de paquetes
   históricos enlazan a un documento de V15.9.2 que no está publicado en
   ninguno de los repositorios disponibles; con esa copia,
   `test_enlaces_markdown_locales_resuelven_despues_de_mover` falla **igual en
   R15.6 pristino que en R15.7**. La copia usada en la verificación final no
   arrastra ese enlace y el test pasa. Ni el documento ni el README histórico
   viajan en el payload o el parche: es un hueco de la reconstrucción, no una
   regresión.
2. **Bit ejecutable de `iniciar.command`/`instalar.command`.** Re-crear el
   árbol con herramientas que no preservan modos los deja en 644 y
   `test_c5_comandos_mac_conservan_modo_ejecutable` falla. El repositorio los
   tiene en git-mode `100755`, el árbol limpio re-extraído pasa la prueba, y
   ninguno de los dos archivos está en el payload ni en el parche (0
   coincidencias en el diff): al restaurar el modo la pareja de módulos queda
   verde.

## 4. Integridad del paquete

* `MANIFEST_SHA256_R15_7.txt`: payload instalable (23 rutas).
* `SHA256SUMS.txt`: todos los artefactos del paquete (32 entradas).
* `V-MATRIX_R15_7.patch`: diff unificado (22 archivos) contra el árbol R15.6
  instalado; verificado con `git apply --check` + aplicación real sobre una
  reconstrucción byte a byte del árbol R15.6 (reproduce el árbol R15.7 sin
  diferencias de hash y pasa la suite en el árbol parcheado (1082 passed / 6 skipped / 0 fallos)). La plantilla de
  ground truth (`validacion_campo/plantilla_ground_truth_tmax.csv`) viaja sólo
  en el payload; el resto de `validacion_campo/` va en ambos.
* Identidad coherente: `VERSION.txt` = `PATCH_BUILD` =
  cache-busting del frontend (`v=15.10.1-r15.7` ≥ 5 apariciones) = instalador.
* Instalación simulada end-to-end (desde el ZIP extraído): árbol R15.6
  reconstruido → copia del payload (23 archivos, 23/23 byte a byte contra el
  ZIP) → bloque R15.x completo 284 passed / 6 skipped + 39/39 `.cjs` OK, y
  suite completa 1082 passed / 6 skipped / 0 fallos.
* Patch verificado: `git apply` sobre la reconstrucción R15.6 produce el árbol
  R15.7 **sin diferencias de hash** en los 22 archivos; el árbol parcheado pasa
  1082 passed / 6 skipped / 0 fallos y el mismo árbol antes del parche
  1042 passed / 6 skipped / 0 fallos.

## 5. No cubierto aquí (campo) — con herramental entregado

1. Ejecución real del instalador/rollback en Windows (`pwsh` no disponible):
   runbook de 7 escenarios en `validacion_campo/VALIDACION_CAMPO_R15_7.md`.
2. Soak de 100–200 análisis en la máquina objetivo:
   `validacion_campo/soak_r157.py` (probado aquí contra un servidor HTTP de
   prueba: completa el soak, detecta un bloqueo sobreviviente y un build
   equivocado, y se detiene en el primer fallo conservando la evidencia).
3. Tmax/semáforo con AVI reales y ground truth humano:
   `validacion_campo/validar_tmax_semaforo.py` + plantilla CSV (validado aquí
   con documento sintético: clasificación con el motor real de reglas,
   MAE/mediana/acuerdo de semáforo y lista de discrepancias).
