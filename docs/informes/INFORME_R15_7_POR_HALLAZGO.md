# INFORME R15.7 POR HALLAZGO — V-Matrix V15.10.1-r15.7

**Referencia:** `AUDITORIA_INDEPENDIENTE_R15_6_20261016.md` §5 (hallazgos), §8
(plan mínimo R15.7), §9 (criterios de Production Ready).
**Alcance declarado:** endurecimiento de recuperación y concurrencia. Sin
funciones nuevas. Sin tocar OCR, Tmax, semáforo ni Excel.

Para cada hallazgo: repro del auditor → corrección aplicada → pruebas que la
fijan → evidencia de la reproducción previa (R15.6) y posterior (R15.7).

---

## ALTO-01 — Una transacción exitosa puede borrar la inconsistencia creada por otra transacción concurrente

**Repro (auditor):** operación B ya superó su precheck sobre `carpeta:RACE`
cuando A falla y registra la inconsistencia; B termina bien y `tx.exito()`
borra el registro durable de A ⇒ bloqueo perdido sin verificación humana.

**Causa raíz:** `TransaccionMultiAlmacen.exito()` llamaba incondicionalmente a
`_resolver_inconsistencias(self.recurso)`.

**Corrección R15.7:**
* `exito()` deja de tener efectos: es un cierre sin resolución de bloqueos.
* La única vía de desbloqueo es el flujo formal de recuperación
  (`resolver_inconsistencia` / `resolver_modo_recuperacion`) con confirmación
  manual y auditoría de quién/cuándo.
* `_resolver_inconsistencias()` se conserva como utilidad interna del flujo
  formal y de herramientas, pero ya no se invoca desde el éxito de operaciones.

**Pruebas:**
* `test_alto01_exito_no_resuelve_inconsistencia_ajena` — registro durable
  vacío antes del `exito()` y no vacío después; el guard sigue en 503.
* `test_alto01_peticion_en_vuelo_no_desbloquea_el_caso` — carrera real:
  `verificar_imagen` termina con éxito mientras otra operación registra la
  inconsistencia a mitad de camino; el caso queda bloqueado.
* `test_alto01_solo_la_api_de_recuperacion_levanta_el_bloqueo` — la resolución
  explícita desbloquea y la operación vuelve a funcionar.

**Evidencia de repro previa (R15.6):** las tres pruebas FALLARON contra el
árbol R15.6 (`assert "ALTO-01: una transacción exitosa ajena resolvió la
inconsistencia"`), y pasan contra R15.7.

---

## ALTO-02 — Claves de recurso no canónicas: el bloqueo se saltaba entre pantallas del mismo caso

**Repro (auditor):** inconsistencia durable registrada para `carpeta:<ID>` y
`verificar_imagen` construía su recurso como ruta absoluta de la imagen ⇒
`_assert_recurso_consistente(ruta, ...)` no encontraba el bloqueo y la
verificación avanzaba con el caso bloqueado.

**Corrección R15.7 — identidad canónica:**

| Pantalla / operación | Identidad previa | Identidad R15.7 |
|---|---|---|
| `corregir_lectura`, `editar_zona`, corrección de campo | `carpeta:<id>` | `carpeta:<id>` (sin cambio) |
| `verificar_imagen`, `marcar_region_no_texto`(+lote), `anotar_region_no_detectada`, rotación de imagen, sin-datos/con-texto de imagen | ruta absoluta | `carpeta:<id>#imagen:<imagen_id>` |
| `revisar_video`, `aprender_zona_video`, `revertir_zona_video` | ruta absoluta | `carpeta:<id>#video:<video_id>` |
| Pruebas externas (evaluar/correcciones/regiones/rotación/sin-datos/con-texto) | ruta absoluta | `externa:<id>` |

* Regla de bloqueo por FAMILIA (`_entradas_bloqueantes`): dos recursos están
  relacionados si comparten raíz canónica. Un bloqueo del caso detiene sus
  imágenes y videos; un bloqueo de una imagen/video detiene las operaciones de
  la carpeta del mismo caso.
* Relación padre↔hijo explícita (`_padre_recurso`, `_recursos_relacionados`).
* Migración al cargar: un registro R15.6 con clave por ruta se reescribe a la
  identidad canónica y conserva la clave original como `alias`; la resolución
  acepta tanto la clave canónica como el alias heredado.

**Pruebas:**
* `test_alto02_inconsistencia_de_carpeta_bloquea_verificar_imagen` (repro
  literal del auditor: antes verificaba y avanzaba la revisión).
* `test_alto02_inconsistencia_de_imagen_bloquea_operacion_de_carpeta`
  (polaridad inversa) y `..._bloquea_revision_de_video`, `..._bloquea_rotacion`.
* `test_alto02_identidad_canonica_de_recursos` (contrato de claves y familia).
* `test_alto02_entradas_heredadas_se_migran_al_cargar` (upgrade sin perder
  bloqueos activos).

**Evidencia:** 6/6 fallando en R15.6; 6/6 pasando en R15.7. Las pruebas
históricas que asumían la clave por ruta (p. ej.
`test_aprender_doble_fallo_no_afirma_revertido`) se actualizaron al contrato
canónico, igual que el mensaje de `fallar()` (ahora informa
`carpeta:<id>#video:<id>`).

---

## ALTO-03 — Registro + centinela no escribibles ⇒ fail-open tras reiniciar

**Repro (auditor):** ni `estado_inconsistente.json` ni
`recuperacion_requerida.json` podían escribirse; en la sesión el bloqueo vivía
en memoria, pero tras el reinicio `_cargar_inconsistencias()` no detectaba
nada y el guard permitía continuar (`after restart guard: ALLOWED`).

**Corrección R15.7:**
* `inicializar_recuperacion()`: carga el registro y ejecuta una **sonda
  obligatoria** de escritura/lectura (temporal + fsync + replace + relectura)
  sobre el almacén de recuperación. Si no puede garantizarse la durabilidad,
  arranca en MODO RECUPERACIÓN (fail-closed) sin necesidad de centinela.
* El arranque real del backend (import del módulo) ejecuta la sonda.
* **Segunda ubicación del centinela**: `~/.v_matrix_ocr/recuperacion_requerida.json`
  (directorio de estado del usuario), reconocida por el arranque aunque todo el
  árbol del proyecto sea no escribible.
* La sonda no produce falsos negativos por concurrencia (una segunda sonda
  simultánea no reintenta sobre una escritura verificada en curso).

**Pruebas:**
* `test_alto03_arranque_fail_closed_sin_registro_ni_centinela` (repro del
  auditor: el guard responde 503 tras el reinicio).
* `test_alto03_sonda_ok_no_bloquea` (sin falsos positivos con almacén sano).
* `test_alto03_doble_ubicacion_del_centinela` (replica + detección en arranque).

**Nota de riesgo aceptado:** si el usuario borra manualmente
`~/.v_matrix_ocr/recuperacion_requerida.json` y el árbol del proyecto está
sano, el bloqueo de recuperación se pierde — mismo comportamiento que el
registro durable oficial (requiere acción manual explícita, no ocurre solo).

---

## MEDIO-04 — `verificar_imagen` respondía error después de confirmar la imagen

**Repro (auditor):** `RuntimeError` forzado en
`gestor.incorporar_uniones_guardadas()` (tarea auxiliar POST-commit) escapaba
del endpoint; el cliente recibía error con la revisión ya incrementada, la
imagen verificada y el documento confirmado.

**Corrección R15.7:** ambas tareas posteriores al commit
(`incorporar_uniones_guardadas` y la programación del entrenamiento visual
automático) se ejecutan en bloques `try/except Exception` con resultado no
fatal; los fallos se acumulan en `advertencia_aprendizaje` y la respuesta
mantiene `verificada=true`, `revision_documento` y `estado_imagen=verificada`.

**Pruebas:**
* `test_medio04_fallo_incorporar_uniones_no_convierte_en_error` (repro literal).
* `test_medio04_fallo_entrenamiento_visual_no_convierte_en_error`.
* `test_medio04_error_inesperado_del_aprendizaje_tampoco_es_fatal`
  (`KeyError`, no sólo `OSError/ValueError`).

---

## MEDIO-05 — CAS externo aceptaba `expected_revision=None` con revision>0

**Repro (auditor):** documento externo `revision_documento=5` +
`expected_revision=None` ⇒ aceptado en modo no estricto; en estricto ⇒ 409.

**Corrección R15.7:**
* Fase de rotación de las ramas externas: `_verificar_expected_revision(...,
  estricto=True)` en sin-datos, con-texto y rotación (los tres writers humanos
  externos versionados).
* Frontend: `TarjetaExterna` recibe `revision_documento` del documento
  externo (que ya expone `_externas_publicas`), lo envía en cada mutación y,
  ante 409, recarga el documento antes de reintentar.

**Pruebas:**
* `test_medio05_marca_externa_sin_expected_revision_409`,
  `..._restaurar_externa_..._409`, `..._rotacion_externa_..._409`.
* `test_medio05_escritor_externo_con_revision_correcta_funciona` (control: con
  la revisión vigente la operación sigue funcionando).
* Las pruebas históricas de carreras externas
  (`test_dos_pestanas_preservan_ambos_cambios`,
  `test_commit_externo_versiona_revision`) se ajustaron al contrato estricto:
  la pestaña desactualizada recibe 409, recarga y reintenta; ningún cambio se
  pierde (se verifican ambos estados persistidos).

**Nota de interoperabilidad:** esto es exactamente el criterio §9-5 del
auditor («CAS externo estricto frente a pestañas antiguas»). Una pestaña de
R15.6 sin `expected_revision` recibirá 409 y un mensaje de recarga; no se
pierde ningún cambio.

---

## BAJO-07 — La resolución podía quedar «resuelta ahora, recuperándose de nuevo al reiniciar»

**Corrección:** `_eliminar_centinela()` borra el centinela en sus dos
ubicaciones y **verifica** que ya no existe. Las respuestas de resolución
incluyen `centinela_eliminado` (bool) y `advertencia_centinela` (texto explícito
si no pudo garantizarse), en lugar de ignorar el `OSError`.

**Pruebas:** `test_bajo07_resolucion_reporta_centinela_no_eliminado` (con un
directorio en lugar del archivo, `unlink()` falla) y
`test_bajo07_resolucion_normal_elimina_el_centinela`.

---

## P2 — Evidencia del árbol destino

**BAJO-06 (auditor):** el inventario se tomaba del staging canónico (39 `.cjs`)
mientras la base instalada conservaba 40. Se añade
`utilidades/inventario_destino.py` (biblioteca + CLI `python -m
utilidades.inventario_destino --destino <ruta> --staging <ruta>`), que
reporta identidad (VERSION.txt / PATCH_BUILD), conteos `.py`/`.cjs`, los tests
EXTRA heredados, los faltantes respecto del staging y la coherencia de
identidad. Prueba: `test_p2_inventario_del_arbol_destino`.

---

## Criterios §9 de la auditoría — estado tras R15.7

| # | Criterio | Estado |
|---|---|---|
| 1 | Una inconsistencia nunca puede ser eliminada por una transacción ajena | **Cubierto** (ALTO-01) |
| 2 | Todas las pantallas del mismo caso reconocen el mismo bloqueo | **Cubierto** (ALTO-02) |
| 3 | Fallo de registry + fallo de sentinel + reinicio sigue fail-closed | **Cubierto** (ALTO-03, sonda + espejo) |
| 4 | Una tarea opcional post-commit nunca convierte un commit exitoso en error | **Cubierto** (MEDIO-04) |
| 5 | CAS externo estricto frente a pestañas antiguas | **Cubierto** (MEDIO-05) |
| 6 | Instalador/rollback validado en Windows real | **Herramentalizado**: runbook con 7 escenarios (`validacion_campo/VALIDACION_CAMPO_R15_7.md`); ejecución en Windows real pendiente |
| 7 | Soak 100–200 análisis en la máquina objetivo | **Herramentalizado**: `validacion_campo/soak_r157.py` (invariantes R15 por iteración + reporte de evidencia); ejecución pendiente en la máquina objetivo |
| 8 | Tmax/semáforo con AVI reales y ground truth humano | **Herramentalizado**: `validacion_campo/validar_tmax_semaforo.py` + plantilla de ground truth; ejecución pendiente en la máquina objetivo |

R15.7 cierra los criterios de código 1–5 y entrega el herramental para los
criterios 6–8 (runbook + dos herramientas de campo con pruebas propias). Los
resultados 6–8 sólo pueden emitirse ejecutándose en la máquina Windows objetivo;
el paquete incluye todo lo necesario para producirlos.
