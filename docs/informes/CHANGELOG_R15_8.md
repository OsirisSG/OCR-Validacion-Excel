# CHANGELOG R15.8 — V-Matrix V15.10.1-r15.8

**Fecha:** 2026-10-16 · **Identidad:** `15.10.1-r15.8` · **Parche acumulativo**
sobre R14/R15/R15.1/R15.2/R15.3/R15.4/R15.5/R15.6/R15.7.

**Origen:** revalidación independiente de R15.7
(`AUDITORIA_REVALIDADA_R15_7_20261016.md`, veredicto «R15.7 no debe
descartarse… mantener como Release Candidate; NO Production Ready
definitivo»). R15.8 cierra los ocho huecos adversariales que la revalidación
reprodujo (4 ALTO + 4 MEDIO) y los tres hallazgos de documentación/operación,
**sin funciones nuevas y sin tocar OCR, Tmax, semáforo ni plantilla Excel**
(alcance P0/P1/P2 de la §8 de esa revalidación: «sólo cierre de confiabilidad»).

---

## 1. Hallazgos cerrados

| Hallazgo | Título | Corrección | Pruebas |
|---|---|---|---|
| ALTO-01 | La sonda de recuperación no probaba el target real (escribía un archivo hermano) | `_sonda_recuperacion()` escribe sobre `estado_inconsistente.json` EXACTO: reemplazo + restauración verificada del contenido previo; target no regular/no reemplazable ⇒ MODO RECUPERACIÓN | `test_alto01_sonda_*` (3) |
| ALTO-02 | Migración legacy incorrecta con rutas relativas (`_clave_ruta` resolvía contra el CWD y no contra `datos["raiz"]`) | `_variantes_clave_ruta()` + `_raiz_documento()`: el índice y el canónico registran/consultan TODAS las variantes (absoluta, relativa→raíz CON confinamiento, literal); la migración canónica se PERSISTE en el registro durable | `test_alto02_*` (3) |
| ALTO-03 | `/api/externas/evaluar` (y cualquier mutante) podía ejecutar durante MODO RECUPERACIÓN | Guard TRANSVERSAL de recuperación (dependencia FastAPI en las 40 rutas POST/PUT/PATCH/DELETE) + política DECLARADA: exenciones sólo para el propio flujo de recuperación y pausar/cancelar; `evaluar` lleva además guard explícito | `test_alto03_*` (3) |
| ALTO-04 | `/api/revisiones` podía modificar un caso bloqueado | `_assert_recurso_consistente()` canónico (`carpeta:<id>` / `externa:<id>`) antes de cualquier transición de revisión | `test_alto04_*` (2) |
| MEDIO-05 | `/api/alertas/atender` ignoraba el bloqueo de recuperación | Guard canónico antes de atender/ocultar la alerta | `test_medio05_alertas_*` (1) |
| MEDIO-06 | El listado de recuperación duplicaba alias (un incidente ⇒ `total=2`) | `listar_inconsistencias()` deduplica por identidad de incidente y expone `claves` | `test_medio06_*` (2) |
| MEDIO-07 | Falso fallo del soak si el pipeline terminaba antes del primer sondeo | `_esperar_pipeline()` sigue el `ejecucion_id` del POST y acepta un terminal de ESA MISMA ejecución; un terminal ajeno no se acepta | `test_medio07_*` (2) |
| MEDIO-08 | El soak heredaba el `ejecucion_id` de la iteración anterior (`locals().get` sin reiniciar) | `lanzado=None` + `ejecucion_objetivo` por ciclo; reporte con la identidad exacta de la iteración | `test_medio08_*` (1) |
| BAJO-09 | El README raíz aún se identificaba como R15.6 | Cabecera y sección R15.8; enlace al changelog R15.8 e `INSTALAR_R15_8` | `test_bajo09_*` (1) |
| BAJO-10 | Mensajes del instalador decían R15.6 | `INSTALAR_R15_8.*`: TODOS los mensajes (banner, throw, postflight, resultado) derivan de `$PatchBuild` con `[regex]::Escape` | `test_bajo10_*` (1) |
| BAJO-11 | El runbook decía «17/17 OK» con un payload mayor | Runbook R15.8 sin conteo fijo («tantas líneas OK como entradas tenga SHA256SUMS.txt»); también corregido en el runbook R15.7 del árbol | `test_bajo11_*` (1) |
| Observación | «Tmax» ambiguo (¿apertura publicada o máximo inflado?) | Definición formal en `validar_tmax_semaforo.py` y en el runbook: Tmax = tiempo de apertura PUBLICADO | `test_observacion_tmax_*` (1) |

Detalle por hallazgo: `docs/informes/INFORME_R15_8_POR_HALLAZGO.md`.
Matriz de evidencia: `docs/informes/MATRIZ_EVIDENCIA_R15_8.md`.

## 2. Cambios principales

### ALTO-01 — la sonda prueba el target real

* La sonda R15.7 creaba `sonda_recuperacion.json` HERMANO: con el target no
  reemplazable (p. ej. ACL de Windows o un directorio en su lugar) y el padre
  escribible, el arranque daba el almacén por durable y luego la escritura
  real del registro fallaba (exactamente el repro de la revalidación).
* Ahora: leer el contenido previo (si existe y es archivo regular) → escribir
  la sonda EN el target (`_escribir_json_verificado`: temporal+fsync+replace+
  relectura) → restaurar el contenido previo byte a byte (o retirar el archivo
  si no existía) con verificación. Cualquier fallo ⇒ fail-closed.
* La sonda nunca escribe un registro válido a propósito: si el proceso muere a
  mitad de la prueba, el archivo remanente no puede leerse como «todo en
  orden» (activa el modo recuperación en el siguiente arranque).

### ALTO-02 — rutas heredadas relativas contra datos["raiz"]

* Nuevo `_raiz_documento()` (raíz del lote declarada por el documento) y
  `_variantes_clave_ruta()`: absoluta resuelta, relativa resuelta CONTRA LA
  RAÍZ del lote (sólo si queda confinada a ella) y forma literal.
* `_indice_rutas_documento()` registra todas las variantes; `_recurso_canonico()`
  consulta todas. La migración en `_cargar_inconsistencias()` se PERSISTE: el
  registro durable queda canónico con el alias heredado.
* Confinamiento: una ruta relativa que escapa de la raíz del lote NO se mapea
  al recurso del caso.

### ALTO-03 — guard transversal + política declarada por ruta

* `_guard_recuperacion_transversal` (dependencia de la app FastAPI): todo
  POST/PUT/PATCH/DELETE falla con 503 en MODO RECUPERACIÓN, salvo las
  exenciones declaradas en `_ENDPOINTS_SEGUROS_EN_RECUPERACION`:
  `/api/recuperacion/*` (la salida) y `pausar`/`cancelar` del pipeline
  (seguridad: detener análisis no crea estado nuevo).
* `externas/evaluar` lleva además el guard explícito pedido por la
  revalidación.
* Test contractual: cada ruta mutante del catálogo debe llevar el guard o ser
  una de las cuatro exenciones exactas — una ruta nueva sin política no pasa
  la suite.

### ALTO-04 / MEDIO-05 — revisiones y alertas respetan el bloqueo

* `actualizar_revision()` aplica `_assert_recurso_consistente(carpeta:<id> /
  externa:<id>)` antes de tocar almacenes: ninguna transición de revisión
  sobre un caso inconsistente.
* `atender_alerta()` exige el caso desbloqueado: una anomalía no puede
  marcarse como atendida mientras el caso esté formalmente bloqueado.

### MEDIO-06 — listado deduplicado

* El registro interno sigue indexando aliases (R15.7), pero el listado público
  deduplica por identidad de incidente y añade `claves` con todas las
  identidades que responden al mismo incidente. `total` vuelve a significar
  «incidentes», no claves.

### MEDIO-07 / MEDIO-08 — soak fiable

* `_esperar_pipeline(..., ejecucion_objetivo)`: acepta un estado terminal
  antes del primer sondeo si pertenece a la ejecución lanzada (o si el
  servidor no expone `ejecucion_id`); un terminal de otra ejecución no se
  acepta y se agota la ventana de admisión con diagnóstico.
* `ejecutar_soak()`: `lanzado`/`ejecucion_objetivo` se reinician por
  iteración; el reporte atribuye cada fallo a la ejecución exacta. Además se
  verifica que el terminal final pertenezca a la ejecución lanzada.

### P2 — identidad y documentación

* `INSTALAR_R15_8.ps1/.bat` con una única variable `$PatchBuild`; los mensajes
  ya no pueden quedarse en una versión anterior (BAJO-10).
* README raíz identifica R15.8 (BAJO-09); runbook R15.8 con conteo de
  integridad dinámico (BAJO-11) y definición formal de «Tmax».
* `PATCH_BUILD` pasa a ser la fuente única también de `FastAPI(version=…)`.

## 3. Compatibilidad

* Base aceptada por el instalador: r14, r15, r15.1 … r15.7 (acumulativo) +
  markers por contenido.
* El guard transversal NO altera respuestas fuera del MODO RECUPERACIÓN; las
  suites completas R15.6 (control) y R15.7 pasan sin cambios de contrato, con
  el aislamiento por prueba del estado de recuperación añadido en `conftest.py`.
* `soak_r157.py` conserva su nombre y el alias `PATCH_BUILD_R157` (ahora
  apunta a `15.10.1-r15.8`); el runbook R15.7 del árbol queda corregido.
