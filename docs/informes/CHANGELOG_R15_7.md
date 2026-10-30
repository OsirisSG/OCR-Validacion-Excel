# CHANGELOG R15.7 — V-Matrix V15.10.1-r15.7

**Fecha:** 2026-10-16 · **Identidad:** `15.10.1-r15.7` · **Parche acumulativo**
sobre R14/R15/R15.1/R15.2/R15.3/R15.4/R15.5/R15.6.

**Origen:** auditoría independiente de R15.6
(`AUDITORIA_INDEPENDIENTE_R15_6_20261016.md`, veredicto «APROBADA como Release
Candidate / beta controlada; todavía NO Production Ready»). R15.7 cierra los
cuatro huecos ALTO/MEDIO reproducidos por el auditor **sin funciones nuevas y
sin tocar OCR, Tmax, semáforo ni plantilla Excel** (alcance mínimo P0/P1/P2 de
la §8 de esa auditoría).

---

## 1. Hallazgos cerrados

| Hallazgo | Título | Corrección | Pruebas |
|---|---|---|---|
| ALTO-01 | Una transacción exitosa en vuelo borraba la inconsistencia creada por otra operación | `TransaccionMultiAlmacen.exito()` ya no resuelve NADA: sólo la API formal de recuperación levanta bloqueos | `test_alto01_*` (3) |
| ALTO-02 | Claves de recurso no canónicas: una inconsistencia del caso no bloqueaba otras pantallas | Identidad canónica `carpeta:<id>` / `carpeta:<id>#imagen:<id>` / `carpeta:<id>#video:<id>` / `externa:<id>` + aliases heredados y bloqueo por familia padre↔hijo | `test_alto02_*` (6) |
| ALTO-03 | Registro + centinela no escribibles ⇒ fail-open tras reiniciar | Sonda obligatoria de escritura/lectura en el arranque + segunda ubicación del centinela (directorio de estado del usuario) | `test_alto03_*` (3) |
| MEDIO-04 | `verificar_imagen` respondía error con el commit ya guardado (tarea opcional post-commit) | Todo lo posterior al commit es best-effort: `advertencia_aprendizaje`, nunca error | `test_medio04_*` (3) |
| MEDIO-05 | El CAS externo aceptaba `expected_revision=None` con documento versionado | `estricto=True` en writers humanos externos (fase de rotación, sin-datos, con-texto, verificación) + la UI envía y refresca la revisión | `test_medio05_*` (4) |
| BAJO-07 | La resolución declaraba «resuelto» aunque el centinela no pudiera eliminarse | `_eliminar_centinela()` verifica el borrado y reporta `centinela_eliminado=false` + advertencia | `test_bajo07_*` (2) |
| BAJO-06 (P2) | Inventario del árbol destino ausente (staging 39 vs base 40 `.cjs`) | `utilidades/inventario_destino.py` (biblioteca + CLI) | `test_p2_inventario_del_arbol_destino` |

Detalle por hallazgo: `docs/informes/INFORME_R15_7_POR_HALLAZGO.md`.
Matriz de evidencia: `docs/informes/MATRIZ_EVIDENCIA_R15_7.md`.

## 2. Cambios principales

### ALTO-01 — el éxito no resuelve inconsistencias

* `TransaccionMultiAlmacen.exito()` queda como cierre sin efectos colaterales
  (no llama a `_resolver_inconsistencias`). Una operación B ya en vuelo no
  puede «limpiar» el bloqueo que registró una operación A que falló mientras B
  corría (doble fallo real silenciosamente desbloqueado).
* Único camino de desbloqueo: `POST /api/recuperacion/inconsistencias/{recurso}/resolver`
  o `POST /api/recuperacion/modo-recuperacion/resolver` tras verificación
  manual confirmada (flujo R15.6, ahora autoridad exclusiva).

### ALTO-02 — identidad canónica de recursos

* Nuevas claves: `carpeta:<caso>` (mutación de carpeta), `carpeta:<caso>#imagen:<img>`,
  `carpeta:<caso>#video:<video>`, `externa:<caso>`.
* `_entradas_bloqueantes()` aplica el bloqueo por FAMILIA: un bloqueo del caso
  detiene imágenes y videos, y un bloqueo de imagen/video detiene las
  operaciones de la carpeta del mismo caso (relación padre↔hijo explícita).
* Migración automática: un registro escrito por R15.6 con rutas absolutas se
  carga a su identidad canónica conservando la clave original como `alias`
  (el upgrade no pierde bloqueos activos).
* Endpoints migrados: verificación de imagen, rotación (carpeta y externa),
  sin-datos y con-texto (carpeta y externa), no-texto (simple y lote),
  anotación de región (carpeta y externa), supervisión externa, regiones
  externas, revisión de video y ROI/reversión de video (subrecurso de video).

### ALTO-03 — arranque fail-closed verificado

* `inicializar_recuperacion()`: carga el registro durable y ejecuta una SONDA
  obligatoria de escritura/lectura (crear, escribir, reemplazar, releer). Si el
  almacén no es durable, el sistema arranca en MODO RECUPERACIÓN aunque no
  exista centinela.
* El centinela se escribe en dos ubicaciones independientes:
  `.cache_ocr/recuperacion_requerida.json` y
  `~/.v_matrix_ocr/recuperacion_requerida.json` (directorio de estado del
  usuario). El arranque reconoce cualquiera de los dos.
* La sonda no puede producir falsos negativos por concurrencia (una sonda
  simultánea no bloquea ni reintenta la escritura verificada en curso).

### MEDIO-04 — semántica post-commit

* `verificar_imagen`: `incorporar_uniones_guardadas` y la programación del
  entrenamiento visual se ejecutan con `_aprendizaje_opcional`-equivalente
  (captura de `Exception` completa, no sólo `OSError/ValueError`). El fallo se
  reporta en `advertencia_aprendizaje` y la respuesta sigue siendo
  `verificada=true` con la revisión documental confirmada.

### MEDIO-05 — CAS externo estricto

* Documento externo con `revision_documento > 0` + `expected_revision=None` ⇒
  **409** (fase de rotación): sin-datos, con-texto y rotación externas.
* Frontend: `TarjetaExterna` recibe `revision_documento` del documento externo,
  lo envía en cada mutación y, ante 409, recarga antes de reintentar
  (`esConflictoDeRevision`), de modo que una pestaña vieja no pierde el cambio:
  sólo se le pide recargar.

### BAJO-07 / BAJO-06 (P2)

* `_eliminar_centinela()` verifica el borrado en ambas ubicaciones y devuelve
  `centinela_eliminado` / `advertencia_centinela` en la respuesta de resolución.
* `utilidades/inventario_destino.py`: inventario del árbol DESTINO posterior al
  upgrade (identidad VERSION.txt/PATCH_BUILD, conteos `.py`/`.cjs`, extras
  heredados respecto del staging y coherencia de identidad).

### P2 (segunda parte) — herramental de validación de campo

Criterios §9-6…§9-8 de la auditoría, que no pueden emitirse desde el sandbox:

* `validacion_campo/soak_r157.py` — soak de 100–200 análisis contra el
  dashboard en marcha, con verificación de invariantes R15 después de CADA
  iteración (identidad del build, registro de recuperación vacío, pipeline sin
  error, `revision_documento` monótona, sin temporales huérfanos) y reporte
  JSON de evidencia. Sólo lectura sobre el proyecto.
* `validacion_campo/validar_tmax_semaforo.py` — Tmax publicado vs ground truth
  humano: Δ por caso, semáforo detectado vs humano con el MISMO motor de reglas
  del dashboard, MAE/mediana/máximo, % dentro de tolerancia y % de acuerdo;
  plantilla CSV incluida.
* `validacion_campo/VALIDACION_CAMPO_R15_7.md` — runbook con los 7 escenarios
  del instalador/rollback en Windows, el procedimiento de soak y el de
  calibración de Tmax, con criterios de aceptación y empaquetado de evidencia.
* Pruebas: `pruebas/test_v15_10_1_r157_validacion_campo.py` (8 pruebas,
  incluido un servidor HTTP de prueba que demuestra que el soak **detecta** un
  bloqueo sobreviviente y un build equivocado).

## 3. Qué NO cambia

* Motor OCR, Tmax, semáforo, plantilla Excel y pipeline: sin cambios.
* Semántica de compensación, registro durable, modo recuperación y flujo de
  recuperación UI/API de R15.6: conservados; sólo se endurecen sus bordes.
* Las bases aceptadas por el instalador son acumulativas (r14 … r15.6, r15.7).

## 4. Evidencia de la ronda

* `pruebas/test_v15_10_1_r157_endurecimiento.py`: **22 pruebas nuevas**, todas
  fallando contra R15.6 y pasando contra R15.7 (ver
  `docs/informes/MATRIZ_EVIDENCIA_R15_7.md`, sección «reproducción previa»).
* Bloque crítico acumulado R15.2→R15.7 + endurecimiento: **179 passed**.
* Suite Python completa del árbol (excluido el soak de video de 100–200
  análisis, que excede la ventana del sandbox): **1082 passed / 6 skipped /
  0 fallos** sobre el árbol de INSTALACIÓN SIMULADA (R15.6 + payload completo
  de 23 archivos) y **1042 passed / 6 skipped / 0 fallos** sobre el mismo árbol
  ANTES de instalar (control R15.6). La diferencia de 40 pruebas es la
  cobertura nueva del payload (22 + 8 + 10): cero regresiones.
* Artefactos de la reconstrucción, documentados en la matriz (§3-bis) para que
  no se confundan con regresiones — ambos afectan por igual a R15.6 y R15.7 y
  ninguno toca archivos del payload: el enlace local a
  `RESULTADOS_PRUEBAS_V15_9_2.md` presente en algunas copias recuperadas del
  README histórico, y el bit ejecutable de `iniciar.command`/`instalar.command`
  al re-crear el árbol con herramientas que no preservan modos (git-mode
  100755 en el repositorio).
* Frontend Node: **39/39** `.cjs` OK en el árbol reconstruido (incluye 3
  `.cjs` legados de la base histórica recuperados como cobertura extra).
* Tres pruebas heredadas actualizadas al contrato R15.7 (identidad canónica,
  CAS externo estricto, cache-busting), documentadas en la matriz de evidencia.

## 5. Pendiente de campo (no se declara producción)

1. Instalador/rollback en Windows real (CIM/WMI, proceso activo, `-Force`,
   archivo bloqueado, fallo a mitad) — el sandbox no dispone de PowerShell.
2. Calibración de Tmax/semáforo con AVI reales y ground truth humano.
3. Soak de 100–200 análisis en la máquina Windows objetivo (CPU/GPU real).

## 6. Instalación

* Paquete completo: ejecutar `INSTALAR_R15_7.bat` (o `.ps1`) desde la raíz
  extraída del ZIP. Bases aceptadas: V15.9.10+R14 instalado, o
  R15/R15.1/R15.2/R15.3/R15.4/R15.5/R15.6/R15.7.
* Sólo código: `V-MATRIX_R15_7.patch` aplica sobre el árbol R15.6
  (`git apply` / `patch -p1`).
* Verificación: `VERIFICAR_SHA256_R15_7.ps1` y `MANIFEST_SHA256_R15_7.txt`
  (payload instalable).
* Tras instalar: `GET /api/estado` debe responder
  `patch_build = 15.10.1-r15.7`.
