# V13 — GPU agresiva, reanudación idempotente y aprendizaje incremental

Fecha: 2026-09-22

V13 se construye sobre la V12 completa. Mantiene el arreglo de V12 que sincroniza
**Revisión completada** entre Detalle y Listado, y añade tres cambios solicitados.

## 1. GPU agresiva para RTX A3000 de 6 GB

En `config.yaml` el perfil queda:

```yaml
fase1:
  rendimiento:
    perfil_gpu: agresivo
    batch_gpu: 8
    batch_gpu_max: 12
    workers_easyocr: 0
```

`recursos.py` ya no limita automáticamente una GPU menor de 8 GB a batch 2. Para
una GPU de ~6 GB propone batch 8 y permite un techo de 12. `ocr_engine.py` empieza
con el lote alto y, si CUDA devuelve **out of memory**, reduce el lote por mitades
(8 → 4 → 2 → 1) y reintenta **sin abandonar la GPU**. Sólo cae a CPU si el error
no es un OOM recuperable o si incluso batch 1 falla.

También se activan `cudnn.benchmark` y TF32 cuando PyTorch/CUDA los soportan.

> La utilización no puede permanecer en 100% durante lectura de disco, OpenCV,
> QR, guardado SQLite o Excel. El objetivo de V13 es mantener la GPU mucho más
> ocupada durante reconocimiento OCR, sin provocar una caída completa por VRAM.

Los resultados OCR incluyen `batch_ocr` para diagnóstico.

## 2. Continuar/Reanudar ya no puede lanzar dos ejecuciones

Cada ejecución tiene un `ejecucion_id` estable, guardado en el checkpoint. Al
reanudar se reutiliza exactamente el mismo identificador.

Antes de iniciar el nuevo hilo, el backend reserva atómicamente el estado
`reanudando`. Un segundo clic o una segunda petición mientras esa reserva existe
recibe conflicto 409 y no crea otro hilo. Los resultados continúan deduplicándose
por `case_key`/ruta estable.

Esto evita el caso observado donde **Continuar** podía iniciar dos reanudaciones
de la misma ejecución y terminar mostrando/creando trabajo duplicado.

## 3. Observaciones de aprendizaje persistidas por imagen

V12 podía conservar OCR en caché/progreso y registrar las observaciones de una
ejecución al final. Si el proceso se detenía antes del cierre completo, parte de
esas observaciones podía no llegar a SQLite.

V13 añade `registrar_observacion_incremental()`:

1. termina OCR de una imagen;
2. aplica descartes/correcciones vigentes;
3. guarda inmediatamente las observaciones en `.aprendizaje/aprendizaje.sqlite3`;
4. recién después continúa a la siguiente imagen.

Cada observación lleva una firma de `ejecucion_id + imagen + texto + bbox + motor`.
Por ello reanudar el mismo trabajo no duplica registros, pero una ejecución nueva
sí conserva su propio historial.

La migración SQLite es aditiva: añade la columna `firma` e índice único parcial a
`observaciones`. No borra correcciones, anotaciones, revisiones ni modelos.

## Instalación recomendada

Si vienes de V12, puedes usar el consolidado V13 como referencia, pero **conserva
tus datos**:

- `.aprendizaje/`
- `validacion_resultados.json`
- `.cache_ocr/` si quieres conservar progreso reanudable
- `base_conocimiento.json`
- plantillas y Excel propios

Nunca sustituyas tu `aprendizaje.sqlite3` por una base vacía.

No hace falta ejecutar `preparar_prueba_ocr.py --preparar` para instalar V13.

## Validación realizada

- 178 pruebas Python pasaron en la suite disponible.
- 8 pruebas adicionales siguen dependiendo de fixtures externos ausentes
  (`validacion_resultados.json` y banco controlado del dashboard), igual que en
  versiones anteriores.
- Todas las pruebas JavaScript `.cjs` del editor pasaron.
- Prueba V13 específica: batch 8 provoca OOM simulado y se recupera 8→4→2 sin
  cambiar a CPU.
- Prueba V13 específica: reanudar conserva el mismo `ejecucion_id` y reserva el
  estado antes de lanzar el hilo.
- Prueba V13 específica: la misma imagen se registra una sola vez al reanudar la
  misma ejecución y se registra de nuevo en una ejecución realmente nueva.

## Nota sobre seguridad de VRAM

`batch_gpu_max: 12` es un techo, no una reserva fija. Si tus imágenes contienen
muchas regiones muy grandes, EasyOCR puede reducir el lote automáticamente. Si
prefieres todavía más agresividad, puedes subir el techo, pero 12 es el máximo
que se entrega por defecto para una RTX A3000 de 6 GB.
