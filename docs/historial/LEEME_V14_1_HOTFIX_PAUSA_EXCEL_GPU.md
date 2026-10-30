# OCR Versuchsmatrix V14.1 — Hotfix pausa, Excel, miniaturas y telemetría GPU

Fecha: 2026-09-23
Base: V14 consolidada del 2026-09-22.

## Cambios incluidos

### 1. El tiempo transcurrido ya no cuenta las pausas

El reloj del dashboard ahora representa **tiempo activo de procesamiento**.

- Al pulsar **Pausar después de esta imagen**, el estado pasa primero a `pausando`.
- La imagen/inferencia en curso termina de forma segura.
- Cuando el worker llega al siguiente punto cooperativo, el estado pasa a `pausado` y el reloj se congela.
- Mientras el proceso permanezca pausado, el tiempo transcurrido no aumenta.
- Al pulsar **Continuar procesamiento**, se inicia un nuevo segmento de tiempo activo y el contador continúa desde el valor congelado.
- Si se recupera un checkpoint después de cerrar/reabrir el programa, el tiempo que el programa estuvo cerrado tampoco se suma.

Esto evita que una pausa de varios minutos u horas infle el tiempo real del OCR.

### 2. Corrección del `TypeError: 'NoneType' object is not iterable` al actualizar Excel

El generador Excel ahora normaliza solamente las colecciones opcionales conocidas que pueden estar temporalmente en `None`, por ejemplo:

- `imagenes`
- `tokens`
- `observaciones`
- resultados opcionales del banco externo

Los campos estructuralmente obligatorios siguen validándose de forma estricta. No se añadió un `try/except` genérico que esconda el problema.

La cola SQLite conserva las actualizaciones pendientes; al arrancar esta versión volverá a intentar automáticamente la exportación y, si ya no existe otro error real, las revisiones pendientes quedarán guardadas.

### 3. Miniaturas con rutas relativas

El backend ahora resuelve correctamente rutas registradas como, por ejemplo:

`PHOTOS/NACH/IMG_4144.JPG`

bajo la raíz real del lote. Esto corrige miniaturas que podían aparecer rotas aunque el archivo existiera dentro del lote procesado.

### 4. Utilización GPU visible sin instalar `pynvml`

PyTorch permite medir VRAM pero no el porcentaje de utilización de los SM. V14 mostraba `— % GPU` cuando `pynvml` no estaba instalado.

V14.1 mantiene NVML como primera opción y añade fallback a `nvidia-smi`, que normalmente ya viene con el controlador NVIDIA de Windows. No se añadió una dependencia Python obligatoria.

Nota: en el Administrador de tareas de Windows, el gráfico seleccionado como **3D** puede permanecer en 0 % aunque CUDA esté trabajando. Para comparar visualmente conviene seleccionar un gráfico **CUDA / Compute**. El dato del dashboard intenta consultar directamente la GPU NVIDIA.

### 5. Los perfiles vuelven a controlar realmente los workers CPU

En V14, `workers_preparacion: 3` y `cola_preparacion_max: 8` estaban fijados en `config.yaml`, por lo que seleccionar **Máximo** seguía mostrando 3 workers.

Ahora ambos están en `auto`:

- Estable: 2 workers / cola 4
- Alto: 3 workers / cola 8
- Máximo: 4 workers / cola 12

El backpressure de RAM/CPU continúa teniendo prioridad sobre llenar la cola.

## Qué no cambia

- `.aprendizaje` no se elimina ni migra destructivamente.
- No se crean lectores CUDA adicionales.
- No se fuerza el 100 % de GPU con trabajo artificial.
- La pausa sigue siendo cooperativa: no interrumpe una inferencia CUDA a la mitad.
- Se conservan 1ST/2ST, revisiones, correcciones manuales y formato Excel.
