# Validación de campo R15.9 — runbook

Cierra los criterios **§9-6, §9-7 y §9-8** en la máquina Windows objetivo, con
el paquete R15.9 instalado. Sustituye al runbook R15.8 incorporando el
CONTRATO REAL del instalador: **R15.9 es un parche INCREMENTAL que exige un
árbol R15.7 o R15.8 completo** (ALTO-02 de la auditoría R15.8).

Antes de empezar:

```powershell
# Integridad del paquete extraído: NO hay cifra fija. El verificador recorre
# SHA256SUMS.txt y debe imprimir «SHA256SUMS OK» — tantas líneas OK como
# entradas tenga el manifiesto del paquete (cero FALTA / HASH DISTINTO).
Get-FileHash .\V-Matrix-V15.10.1-R15_9_20261018.zip -Algorithm SHA256   # opcional
.\VERIFICAR_SHA256_R15_9.ps1
```

---

## §9-6 · Instalador y rollback en Windows real

Prueba **transaccional** del instalador. Hacer SIEMPRE sobre una copia del
proyecto (`C:\VMatrix_PRUEBA`) para no arriesgar la instalación de producción.

| # | Escenario | Procedimiento | Resultado esperado |
|---|---|---|---|
| 1 | VerifyOnly post-instalación | Tras completar el escenario 6, ejecutar `.\INSTALAR_R15_9.bat -VerifyOnly` sobre el mismo destino ya actualizado | `R15_9_VERIFICADO_OK`, sin tocar archivos. **No ejecutarlo sobre una base R15.7/R15.8 previa**: este modo verifica el payload final ya instalado; la aceptación de la base se comprueba durante el preflight del escenario 6. |
| 2 | **Base híbrida (nuevo ALTO-02)** | En una copia R15.6, editar `VERSION.txt` para que diga `15.10.1-r15.7` y ejecutar el instalador | Aborta con `BASE HIBRIDA O MODIFICADA` (el hash de `app.py` no está en el contrato) ANTES de leer el manifiesto; **cero archivos modificados** |
| 3 | **Base incompleta (nuevo ALTO-02)** | Renombrar `dashboard\backend\app.py` y ejecutar | Aborta con `BASE INCOMPLETA: falta ...`; **cero archivos modificados** |
| 4 | Base desconocida | Renombrar `VERSION.txt` a `VERSION.txt.bak` y ejecutar sin `-VerifyOnly` | Aborta con `BASE NO RECONOCIDA ... R15.7/R15.8`; **cero archivos modificados** |
| 5 | V-Matrix en ejecución | Con el dashboard encendido, ejecutar el instalador | Detecta el proceso y aborta sin copiar |
| 6 | Instalación normal (y verificador ALTO-01) | Cerrar V-Matrix y ejecutar `.\INSTALAR_R15_9.bat` con un Python utilizable | `PARCHE_R15_9_COPIADO_Y_VERIFICADO_OK` — el preflight de Python NO puede fallar por versión (la esperada viaja por argumento) |
| 7 | Verificación post-instalación | `GET http://127.0.0.1:8000/api/estado` | `patch_build = 15.10.1-r15.9.1` |
| 8 | Archivo bloqueado a mitad | Bloquear `dashboard\frontend\app.js` y reinstalar | Fallo controlado + rollback: el proyecto queda como estaba |
| 9 | Rollback manual | Restaurar desde `..._BACKUP_PRE_R15_9_<fecha>` y arrancar | `patch_build` vuelve al release anterior y el dashboard abre sin errores |

Verificación adicional del contrato (mensajes): durante toda la instalación
los mensajes citan **15.10.1-r15.9.1** derivado de la variable única
(`$PatchBuild`); ningún mensaje debe citar otra versión como vigente.

Evidencia a guardar: transcripción de consola de los 9 escenarios y la ruta
del backup. Cualquier desviación se documenta como hallazgo con el hash del
archivo implicado.

---

## §9-7 · Soak de 100–200 análisis

Con el proyecto real (no la copia de prueba) instalado en R15.9 y el dashboard
encendido:

```powershell
cd C:\VMatrix
python validacion_campo\soak_r157.py `
    --lote "C:\Datos\Lote_Real" `
    --iteraciones 150 `
    --perfil alto `
    --validacion validacion_resultados.json `
    --cache-ocr .cache_ocr `
    --salida soak_r157_reporte.json
```

Qué verifica **después de cada iteración**:

| Invariante | Fallo que detecta |
|---|---|
| `patch_build` = `15.10.1-r15.9.1` | instalación híbrida o rollback a medias |
| `modo_recuperacion` nulo **y** 0 inconsistencias | cualquier doble fallo real silencioso |
| pipeline terminó sin `error`, de LA EJECUCIÓN LANZADA | fallos de análisis/OOM; terminadores ajenos (R15.9: un terminal de otra ejecución ya no se acepta como fin) |
| `revision_documento` no retrocede | escrituras perdidas o restauraciones indebidas |
| sin `*.tmp` huérfanos en `.cache_ocr` | escrituras verificadas interrumpidas |

Semántica de ejecución (R15.8 + endurecimiento R15.9): el soak sigue el
**`ejecucion_id`** del POST; el inicio sólo cuenta con un activo de ESA
ejecución y el fin sólo se acepta con el MISMO id (un activo/terminal de otra
ejecución o sin id es inconcluso y se sigue esperando). El reporte atribuye
cada fallo a la ejecución exacta y se detiene en el primer fallo.

Criterio de aceptación: **150 iteraciones sin fallos**. Ensayo corto previo
(5 iteraciones) para validar conectividad.

---

## §9-8 · Tmax/semáforo con AVI reales y ground truth humano

**Definición formal (vigente desde R15.8):** «Tmax» es el **tiempo de apertura
PUBLICADO** por el sistema (`resultado_caso_canonico.apertura.tiempo_ms` /
`opening_time_ms` heredado), el valor que colorea el semáforo del dashboard y
del Excel; NO es el «máximo inflado» del análisis de video.

1. Copiar `validacion_campo\plantilla_ground_truth_tmax.csv` y rellenarla con
   mediciones **humanas** (una fila por caso).
2. Ejecutar:

   ```powershell
   python validacion_campo\validar_tmax_semaforo.py `
       --validacion validacion_resultados.json `
       --ground-truth validacion_campo\ground_truth_tmax.csv `
       --tolerancia-ms 1.0 `
       --minimo-acuerdo 90 `
       --salida validacion_tmax_reporte.json
   ```

3. Leer el reporte (por caso: humano vs publicado, Δ ms, semáforos y acuerdo;
   agregados MAE/mediana/% tolerancia/% acuerdo). `gris` = sin dato publicado
   (política fail-closed), se cuenta aparte. Las discrepancias de semáforo son
   la lista de trabajo de calibración.

---

## Prueba adicional R15.9 — interrupción de la sonda (ALTO-03, opcional pero recomendada)

Con el dashboard instalado en R15.9 y un bloqueo real activo:

1. Anotar el contenido de `.cache_ocr\estado_inconsistente.json` (hash).
2. Provocar un arranque con el almacén protegido (p. ej. ACL de solo-lectura
   sobre el ARCHIVO, directorio escribible) y matar el proceso durante el
   arranque (o simular corte de alimentación).
3. Comprobar que existe `.cache_ocr\estado_inconsistente.json.respaldo_sonda`
   con el hash del paso 1, restaurar permisos y arrancar de nuevo.
4. Resultado esperado: `GET /api/recuperacion/inconsistencias` muestra la
   entrada original (recuperada del respaldo), `modo_recuperacion: null` y el
   registro restaurado con el MISMO hash; el respaldo desaparece.

---

## Empaquetado de la evidencia

Adjuntar a la auditoría final:

1. `soak_r157_reporte.json` (150 iteraciones, `"ok": true`).
2. `validacion_tmax_reporte.json` + el CSV de ground truth usado.
3. Transcripción de los 9 escenarios del instalador (§9-6) con la ruta del backup.
4. `GET /api/estado` con el `patch_build = 15.10.1-r15.9.1`.

Con esos cuatro elementos (más la prueba opcional de la sonda), los criterios
§9-1…§9-8 quedan cubiertos y la línea R15 puede pasar a la declaración de
Production Ready (o documentar cada aceptación con su mitigación).


### Nota de revisión independiente 2026-10-19

`-VerifyOnly` verifica que **todos los archivos del payload de destino ya
estén instalados**; no es un `-CheckBase`. El escenario de base se valida por
el preflight del instalador normal (sin copiar hasta aceptar la base). Para
comprobar sólo el destino, ejecutar `-VerifyOnly` después de una instalación
completa. Identidad del paquete de revisión: `15.10.1-r15.9.1`.
