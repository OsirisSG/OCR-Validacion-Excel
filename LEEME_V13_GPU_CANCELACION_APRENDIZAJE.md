# OCR Versuchsmatrix V13 — cancelación, GPU y aprendizaje

Fecha: 2026-09-22
Base: V12.

## Corrección urgente: Cancelar ya no bloquea la aplicación

En V12 la comprobación cooperativa de cancelación intentaba generar el Excel parcial antes de lanzar la cancelación. Si el XLSX tardaba, estaba abierto o el disco estaba ocupado, el estado podía permanecer en `cancelando` y la interfaz impedía iniciar/cargar otro trabajo.

V13 cambia el orden:

1. se solicita la cancelación;
2. el OCR sale en cuanto llega al siguiente punto seguro;
3. el pipeline cambia a `detenido_con_avance` y libera sus eventos/hilo;
4. el Excel parcial se genera en segundo plano.

También se añadieron comprobaciones de cancelación dentro de la búsqueda OCR, entre orientaciones y entre regiones. Una inferencia CUDA ya iniciada no puede ser abortada a mitad por Python, pero V13 reduce considerablemente el tiempo hasta el siguiente punto seguro.

Si una ejecución previa quedó en `cancelando` pero su hilo ya terminó, iniciar una carpeta nueva recupera automáticamente el estado y no queda bloqueado por esa marca obsoleta.

## Reanudar sin duplicar la ejecución

Al reanudar un checkpoint empresarial V13 reutiliza directamente:

- la misma raíz;
- el inventario existente;
- los resultados parciales;
- los casos ya finalizados como omitidos.

No vuelve a entrar por la ruta de "ejecución nueva". Esto evita repetir la inicialización/inventario y el comportamiento observado de duplicación al pulsar Continuar.

Para proyectos legacy sin inventario se conserva un fallback compatible, manteniendo los casos ya procesados como omitidos.

## Aprendizaje incremental

Las observaciones OCR se registran después de cada imagen terminada. Ya no dependen de que todo el lote llegue al final.

El registro es idempotente por imagen + texto + bbox + motor: reanudar la misma imagen no crea una segunda observación idéntica.

Las correcciones manuales siguen separadas del entrenamiento visual: una corrección persistida es la verdad del caso; sólo las acciones explícitamente marcadas como entrenables pasan al conjunto de entrenamiento.

## GPU agresiva

En `config.yaml` V13 activa:

```yaml
fase1:
  rendimiento:
    gpu_agresivo: true
    batch_gpu: 6
```

En CUDA se habilita `cudnn.benchmark` y, cuando está disponible, TF32/matmul de alto rendimiento. V13 ya no limita automáticamente una GPU de 6 GB a batch 2 cuando el modo agresivo está activo.

Si CUDA reporta falta de memoria, EasyOCR reduce el batch progresivamente (por ejemplo 6 -> 3 -> 1) y reintenta en GPU antes de usar CPU. Esto permite aprovechar más la RTX A3000 de 6 GB sin convertir un OOM puntual en un fallback permanente a CPU.

La GPU no estará al 100% durante lectura de archivos, OpenCV, QR, persistencia o Excel; el objetivo es maximizar su uso durante reconocimiento neuronal.

## V12 preservado

Se conserva la corrección de V12: una revisión marcada como completada tiene prioridad sobre copias parciales en memoria y debe mostrarse como completada tanto en el detalle como en el Listado.

## Instalación

1. Cierra el servidor anterior por completo.
2. Conserva/respalda `.aprendizaje/`, especialmente `aprendizaje.sqlite3`.
3. Descomprime V13 en una carpeta nueva.
4. Copia tus datos persistentes desde la instalación actual; no sustituyas tu base de aprendizaje por una vacía.
5. Inicia el dashboard.

Si V12 está actualmente atrapada en `cancelando`, cerrar el servidor es seguro para este cambio: el checkpoint queda en disco y V13 recupera estados interrumpidos como reanudables.

## Validación

- 176 pruebas Python pasaron.
- 8 pruebas requieren fixtures externos ausentes en el paquete (`validacion_resultados.json` y banco externo controlado).
- Todas las pruebas JavaScript del editor pasaron.
- Se probó que cancelar no llama a la exportación Excel de forma síncrona.
- Se probó que la observación incremental no se duplica al registrarla dos veces.
- Se probó que reanudar con inventario reutiliza el checkpoint y omite casos ya terminados.
