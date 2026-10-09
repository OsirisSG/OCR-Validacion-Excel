# V14 — SOP, rendimiento sostenible y recuperación segura

Fecha: 2026-09-22  
Base: V13 consolidada + correcciones de cancelación existentes

V14 conserva la lógica empresarial, 1ST/2ST, el editor OCR, el formato del Excel maestro,
las correcciones confirmadas y `.aprendizaje`. El cambio principal es separar el trabajo
que puede hacerse de forma concurrente sin crear varios propietarios CUDA.

## 1. Arquitectura implementada

Flujo efectivo:

`descubrimiento → preparación CPU acotada → cola RAM → OCR (un propietario CUDA) → validación → persistencia → Excel`

- `orquestador_ocr.py` hace lectura/decodificación anticipada en CPU mediante un pool limitado.
- La cola no es una caché ilimitada: respeta `cola_preparacion_max` y deja de admitir trabajo si
  `GestorRecursos` detecta presión de RAM.
- Las imágenes ya confirmadas por caché no se vuelven a decodificar sólo por el prefetch.
- Rotaciones, ROI y decisiones que dependen del aprendizaje permanecen dentro del flujo OCR para
  no cambiar resultados por una optimización prematura.
- `MotorEasyOCR` conserva un único `Reader` propietario de CUDA. `batch_size` se trata como el
  batch interno del reconocedor de regiones de EasyOCR, no como varias fotografías simultáneas.

## 2. Perfiles de rendimiento

El perfil predeterminado es **ALTO**.

| Perfil | GPU objetivo | VRAM límite orientativo | RAM límite | CPU objetivo | Workers preparación | Cola |
| --- | --- | --- | --- | --- | --- | --- |
| Estable | 70–85 % | 75 % | 65 % | 60–75 % | 2 | 4 |
| Alto | 85–95 % | 85 % | 80 % | 75–90 % | 3 | 8 |
| Máximo | 90–100 % | 90 % | 85 % | 85–95 % | 4 | 12 |

Son objetivos y límites de regulación, no reservas ni garantías. V14 no genera trabajo inútil para
alcanzar porcentajes. El objetivo es imágenes correctas por minuto.

Desde el dashboard se puede elegir **Estable / Alto / Máximo** antes de iniciar. En CLI:

```powershell
python pipeline.py "C:\ruta\al\lote" --perfil-rendimiento alto
```

## 3. Batch EasyOCR y CUDA OOM

Configuración inicial de V14 para una GPU de 6 GB:

```yaml
fase1:
  rendimiento:
    perfil_sop: alto
    perfil_gpu: adaptativo
    batch_gpu: 6
    batch_gpu_max: 12
    ventana_batch: 12
    reintentos_oom: 3
```

Comportamiento:

1. Reutiliza el `Reader` CUDA existente.
2. Un OOM reduce el batch de forma controlada.
3. El batch no sube después de cada foto; usa una ventana estable e histéresis.
4. Si incluso batch 1 falla, **sólo esa tarea** se ejecuta temporalmente con un `Reader` CPU lazy.
5. Las imágenes siguientes vuelven a intentar CUDA; un incidente aislado no convierte el lote entero a CPU.
6. `torch.cuda.empty_cache()` sólo se usa después de soltar referencias temporales y como ayuda de recuperación,
   nunca como sustituto de liberar tensores vivos.

## 4. Cancelación, pausa y nuevo lote

La decisión de aceptar un nuevo procesamiento ya no depende sólo del texto guardado en
`_pipeline_estado`. Antes de iniciar, el backend comprueba si `_pipeline_hilo` **sigue vivo**.

- Si el estado quedó en `cancelando` pero el hilo anterior ya terminó, se puede iniciar un nuevo lote.
- Si el hilo anterior sigue vivo, se devuelve 409 y no se crea un segundo propietario CUDA.
- El `finally` del worker limpia las banderas de cancelación/pausa y persiste el checkpoint.
- `ejecucion_id` separa ejecuciones y la reanudación conserva la identidad existente.

No es necesario borrar `.cache_ocr` para iniciar una ejecución nueva.

## 5. Cola de persistencia/Excel

`utilidades/cola_excel.py` usa SQLite como cola durable y ahora registra cada actualización con ID
único y revisión. Repetir el mismo ID es idempotente.

Estados de una actualización: `pendiente → guardando → guardado` o `error`.

Los errores se clasifican como:

- `excel_bloqueado`
- `permisos`
- `datos_invalidos`
- `almacenamiento`
- `exportacion`

Un error conserva la actualización pendiente, traceback y contador de reintentos. Los reintentos
usan backoff limitado. Una corrección nueva que llega mientras se exporta no se da por guardada con
la instantánea anterior: conserva su revisión pendiente para la siguiente exportación.

`generar_excel.py` ahora valida explícitamente el contrato de `datos_validacion` y, por ejemplo,
`resultados=None` produce un error claro antes de intentar iterarlo.

## 6. Panel de rendimiento

`/api/pipeline/estado` expone, cuando están disponibles:

- perfil activo;
- CPU y RAM;
- GPU y VRAM;
- imágenes completadas e imágenes/minuto;
- batch EasyOCR actual;
- workers de preparación y cola pendiente/MB;
- media, p50 y p95 de inferencia;
- reintentos CUDA OOM y derivaciones temporales a CPU;
- estado y errores de la persistencia Excel.

La utilización de núcleos GPU no se inventa: si NVML no está disponible aparece como dato no disponible.
VRAM se obtiene de PyTorch cuando CUDA está activo.

## 7. Archivos principales modificados/nuevos

- `gestor_recursos.py` — perfiles, límites, telemetría y métricas de etapas.
- `orquestador_ocr.py` — preparación CPU acotada y backpressure.
- `ocr_engine.py` — batch adaptativo, OOM, fallback temporal CPU y reutilización de imagen preparada.
- `validacion.py` — integración del prefetch sin reprocesar caché confirmada.
- `utilidades/cola_excel.py` — cola durable, idempotente, reintentos y clasificación de errores.
- `generar_excel.py` — contratos explícitos de entrada.
- `pipeline.py` — perfil SOP, métricas de etapas y selector CLI.
- `dashboard/backend/app.py` — reconciliación estado/hilo, perfiles, métricas y persistencia.
- `dashboard/frontend/app.js` — selector de perfil y panel de rendimiento/persistencia.
- `config.yaml` — configuración V14.
- `pruebas/test_v14_sop_recuperacion.py` — contratos específicos V14.

## 8. Validación ejecutada en este paquete

Comandos ejecutados desde la raíz:

```powershell
python -m py_compile ocr_engine.py pipeline.py recursos.py gestor_recursos.py orquestador_ocr.py utilidades/cola_excel.py generar_excel.py dashboard/backend/app.py
node --check dashboard/frontend/app.js
python -m pytest -q pruebas/test_v14_sop_recuperacion.py
python -m pytest -q
```

Resultados en el entorno de construcción:

- Pruebas V14 nuevas: **9/9 aprobadas**.
- Suite completa: **187 aprobadas, 8 fallidas**.
- Línea base V13 antes de modificar: **178 aprobadas, 8 fallidas**.
- Los mismos 8 fallos de ambas ejecuciones dependen de fixtures externos ausentes en el ZIP:
  `validacion_resultados.json` y el banco controlado usado por varias pruebas del dashboard/Excel.
- No quedó una regresión nueva respecto de la línea base.

El entorno de construcción tenía `torch 2.10.0+cpu`, sin CUDA. Por tanto, los casos de OOM y fallback
se probaron de forma simulada/unitaria. **No se afirma una mejora de velocidad real de GPU sin medirla
en la RTX A3000.**

## 9. Verificación real en la RTX A3000 de 6 GB

Usa el mismo lote fijo para V13 y V14, con el Excel cerrado y sin cambiar resolución/configuración.
Haz primero una ejecución en frío y después una con modelos/cachés ya cargados.

En V14 ejecuta por ejemplo:

```powershell
python pipeline.py "D:\LOTE_CONTROL" --perfil-rendimiento alto --excel v14_alto.xlsx
```

Repite con `estable` y `maximo`. Guarda el JSON impreso por `pipeline.py`; incluye
`metricas_rendimiento` y `recursos`. Compara al menos:

- duración total;
- imágenes/minuto;
- porcentaje de reconocimiento correcto sobre el mismo conjunto corregido;
- media/p50/p95 de inferencia;
- OOM y derivaciones CPU;
- batch alcanzado;
- RAM/VRAM máximas observadas;
- cancelación y capacidad de iniciar un lote nuevo.

No elijas el perfil por el porcentaje de GPU. El perfil correcto es el que aumente imágenes correctas
por minuto de forma estable sin OOM repetitivo ni pérdida de precisión.

## 10. Recuperación ante problemas

### Cancelé y no puedo iniciar

Consulta `/api/pipeline/estado`. Si el hilo anterior sigue cerrando recursos, espera a que deje de estar
vivo; V14 evita intencionadamente superponer dos propietarios CUDA. Si ya terminó, un estado persistido
`cancelando` no debería impedir una ejecución nueva.

### Excel bloqueado

Cierra el libro que esté abierto. El OCR puede seguir; la actualización permanece en la cola SQLite y se
reintenta. Revisa `error_tipo` para distinguir bloqueo de archivo de datos inválidos.

### CUDA OOM

Deja que el regulador reduzca batch. Si ocurre repetidamente incluso con batch 1, prueba primero el perfil
`estable`. No borres `.aprendizaje` ni cambies todo el proyecto a CPU por un caso aislado.

### Reinicio inesperado

Conserva:

- `.aprendizaje/`
- `.cache_ocr/`
- `validacion_resultados.json`
- `base_conocimiento.json`
- tus plantillas y Excel

Reanuda desde el dashboard o usa el modo `reanudar` con el inventario correspondiente. No reemplaces una
base de aprendizaje existente por una vacía.
