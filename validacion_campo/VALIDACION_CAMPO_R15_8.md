# Validación de campo R15.8 — runbook

Cierra los criterios **§9-6, §9-7 y §9-8** en la máquina Windows objetivo, con
el paquete R15.8 instalado. Sustituye al runbook R15.7 incorporando las
correcciones de la revalidación independiente (BAJO-10/11, MEDIO-07/08 y la
definición formal de «Tmax»).

Antes de empezar:

```powershell
# Integridad del paquete extraído: NO hay cifra fija (BAJO-11). El verificador
# recorre SHA256SUMS.txt y debe imprimir «SHA256SUMS OK» — tantas líneas OK
# como entradas tenga el manifiesto del paquete (cero FALTA / HASH DISTINTO).
Get-FileHash .\V-Matrix-V15.10.1-R15_8_20261016.zip -Algorithm SHA256   # opcional
.\VERIFICAR_SHA256_R15_8.ps1
```

---

## §9-6 · Instalador y rollback en Windows real

Prueba **transaccional** del instalador. Hacer SIEMPRE sobre una copia del
proyecto (`C:\VMatrix_PRUEBA`) para no arriesgar la instalación de producción.

| # | Escenario | Procedimiento | Resultado esperado |
|---|---|---|---|
| 1 | VerifyOnly sobre base válida | `.\INSTALAR_R15_8.bat -VerifyOnly` en la carpeta del proyecto R15.7 | `R15_8_VERIFICADO_OK`, sin tocar archivos |
| 2 | Base desconocida | Renombrar `VERSION.txt` a `VERSION.txt.bak` y ejecutar sin `-VerifyOnly` | Aborta con `throw` ANTES de leer el manifiesto; **cero archivos modificados** |
| 3 | V-Matrix en ejecución | Con el dashboard encendido, ejecutar el instalador | Detecta el proceso y aborta sin copiar |
| 4 | Instalación normal | Cerrar V-Matrix y ejecutar `.\INSTALAR_R15_8.bat` | `PARCHE_R15_8_COPIADO_Y_VERIFICADO_OK`, backup en `..._BACKUP_PRE_R15_8_<fecha>` |
| 5 | Verificación post-instalación | `GET http://127.0.0.1:8000/api/estado` | `patch_build = 15.10.1-r15.8` |
| 6 | Archivo bloqueado a mitad | Bloquear `dashboard\frontend\app.js` (abrir con un editor que mantenga lock) y reinstalar | Fallo controlado + rollback: el proyecto queda como estaba (comparar hashes con el backup) |
| 7 | Rollback manual | Restaurar la carpeta desde `..._BACKUP_PRE_R15_8_<fecha>` y arrancar | `patch_build` vuelve a `15.10.1-r15.7` y el dashboard abre sin errores |

Verificación adicional R15.8 (mensajes, BAJO-10): durante toda la instalación
los mensajes citan **15.10.1-r15.8** derivado de una única variable de versión
(`$PatchBuild`); ningún mensaje debe decir «R15.6».

Evidencia a guardar: transcripción de consola de los 7 escenarios y la ruta del
backup. Cualquier desviación (por ejemplo «el rollback dejó un archivo nuevo»)
se documenta como hallazgo con el hash del archivo.

---

## §9-7 · Soak de 100–200 análisis

Con el proyecto real (no la copia de prueba) instalado en R15.8 y el dashboard
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

Qué verifica **después de cada iteración** (y por qué importa):

| Invariante | Fallo que detecta |
|---|---|
| `patch_build` = `15.10.1-r15.8` | instalación híbrida o rollback a medias |
| `modo_recuperación` nulo **y** 0 inconsistencias | cualquier doble fallo real silencioso (objetivo fail-closed de R15.6/R15.7/R15.8) |
| pipeline terminó sin `error` | fallos de análisis/OOM que la UI podría no mostrar |
| `revision_documento` no retrocede | escrituras perdidas o restauraciones indebidas |
| sin `*.tmp` huérfanos en `.cache_ocr` | escrituras verificadas interrumpidas |

Semántica de ejecución corregida en R15.8 (MEDIO-07/08 de la revalidación):

* El soak sigue el **`ejecucion_id`** devuelto por el POST de cada iteración y
  lo reporta en el JSON; un fallo del lanzamiento reporta `ejecucion_id: null`
  (nunca hereda el de la iteración anterior).
* Si el análisis termina antes del primer sondeo, el terminal de ESA MISMA
  ejecución se acepta como fin válido (ya no se informa «el pipeline no
  arrancó»); un terminal de OTRA ejecución (más antigua) no se acepta.
* El soak se detiene en el primer fallo para no contaminar la evidencia; el
  reporte JSON conserva la iteración exacta, su duración, el resumen del
  pipeline y las métricas de recursos.

Criterio de aceptación: **150 iteraciones sin fallos**.

Antes del soak largo, un ensayo corto (5 iteraciones) para validar conectividad:

```powershell
python validacion_campo\soak_r157.py --lote "C:\Datos\Lote_Real" --iteraciones 5
```

---

## §9-8 · Tmax/semáforo con AVI reales y ground truth humano

**Definición formal (R15.8, observación de la revalidación):** en esta
validación «Tmax» es el **tiempo de apertura PUBLICADO** por el sistema —
`resultado_caso_canonico.apertura.tiempo_ms` (o `opening_time_ms` heredado), el
mismo valor que colorea el semáforo del dashboard y del Excel. NO es el
«máximo inflado» del análisis de video ni otro campo: lo que se valida es que
la cifra publicada coincide con la observación humana. La calibración del
máximo inflado es un proceso aparte (zona de apertura / aprendizaje de video).

1. Copiar `validacion_campo\plantilla_ground_truth_tmax.csv` y rellenarla con
   las mediciones **humanas** (una fila por caso):

   ```csv
   caso,tiempo_ms_humano,nota
   1001,5.9,"lectura cuadro a cuadro"
   A1_variante3,6.4,"duda de 1 cuadro"
   ```

   `caso` puede ser el nombre de la carpeta, el `case_key`, el id corto del
   caso o el nombre del directorio de la fila.

2. Ejecutar:

   ```powershell
   python validacion_campo\validar_tmax_semaforo.py `
       --validacion validacion_resultados.json `
       --ground-truth validacion_campo\ground_truth_tmax.csv `
       --tolerancia-ms 1.0 `
       --minimo-acuerdo 90 `
       --salida validacion_tmax_reporte.json
   ```

3. El reporte indica, por caso: valor humano, valor publicado, Δ ms, semáforo
   detectado vs humano y acuerdo; y agrega MAE, mediana, máximo, % dentro de
   tolerancia y % de acuerdo de semáforo.

Lectura correcta del resultado:

* **`gris` en el detectado** = el sistema no publica color (sin dato, propuesta
  o conflicto pendiente de revisión humana). No es un error de Tmax: es la
  política fail-closed de la serie R15. Se cuenta aparte (`sin_valor`).
* Para calibrar (criterio §9-8 `PARÁMETRO ABIERTO` del proyecto), usa las
  discrepancias de semáforo como lista de trabajo: cada caso donde el humano
  dice `verde` y el sistema `gris`, o donde difieren `amarillo`/`rojo`, se
  revisa con el vídeo delante.
* Los límites vigentes se muestran en el encabezado (por defecto verde ≤ 6 ms,
  amarillo ≤ 7 ms, `origen: predeterminado`). Si el proyecto tiene límites
  confirmados por el usuario, aparecerán como `origen: vigente`.

---

## Empaquetado de la evidencia

Adjuntar a la auditoría final:

1. `soak_r157_reporte.json` (150 iteraciones, `"ok": true`).
2. `validacion_tmax_reporte.json` + el CSV de ground truth usado.
3. Transcripción de los 7 escenarios del instalador (§9-6) con la ruta del backup.
4. `GET /api/estado` con el `patch_build = 15.10.1-r15.8`.

Con esos cuatro elementos, los criterios §9-1…§9-8 quedan cubiertos y la línea
R15 puede pasar a la declaración de Production Ready (o documentar en cada
hallazgo la decisión de aceptarlo con su mitigación).
