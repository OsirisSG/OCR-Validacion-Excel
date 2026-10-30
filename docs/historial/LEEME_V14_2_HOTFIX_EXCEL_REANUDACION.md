# OCR V14.2 — Hotfix de Excel y reanudación completa

Fecha: 2026-09-23

Esta versión corrige dos fallos observados en V14.1 durante una ejecución real:

1. La cola de Excel podía quedar con actualizaciones pendientes por `TypeError: 'NoneType' object is not iterable`.
2. Al reanudar un checkpoint, podían omitirse carpetas futuras que solamente habían sido descubiertas/inventariadas y todavía no habían sido procesadas.

## 1. Causa del error de Excel

V14.1 ya validaba varios datos en `generar_excel.py`, pero la exportación también vuelve a proyectar el OCR mediante las capas de aprendizaje/correcciones. Algunas estructuras OCR pueden incluir claves válidas cuyo valor sea `None`, por ejemplo:

- `tokens = None`
- `lineas_texto = None`
- `codigos_detectados = None`
- `recortes = None`
- `qrs = None`

Una expresión del tipo `for x in objeto.get("tokens", [])` no protege ese caso: si la clave existe y contiene `None`, `.get()` devuelve `None` y Python intenta iterarlo.

V14.2 normaliza esas colecciones solamente en los puntos donde contractualmente se espera una colección, sin convertir indiscriminadamente cualquier `None` del sistema. Se corrigieron las rutas de:

- `aprendizaje.py`
- `utilidades/correcciones_ocr.py`
- `utilidades/edicion_zonas.py`
- `plantilla_empresarial.py`

La cola de Excel conserva el traceback completo en SQLite y ahora publica además un `detalle_error` resumido en el dashboard. Las actualizaciones pendientes no se descartan por este error.

## 2. Causa del fallo de reanudación

Durante la fase de descubrimiento, el dashboard publica filas de todos los casos antes de que se ejecute OCR. Esas filas pueden tener estados como `detectada` o `inventariada`.

V14.1 reconstruía `casos_omitidos` con una regla demasiado amplia y podía interpretar esas filas como trabajo ya finalizado. Al reanudar, esto podía hacer que se procesara la carpeta interrumpida o inmediata y se saltaran carpetas posteriores.

V14.2 considera completados únicamente los casos con evidencia explícita de finalización. Los estados de descubrimiento, inventario, pausa, cancelación, error o pendiente siguen siendo trabajo pendiente.

Además, V14.2 NO confía en el `casos_omitidos` interno heredado del checkpoint V14.1. Lo reconstruye a partir de `resultados_parciales`. Esto permite recuperar un checkpoint que ya haya sido contaminado por el bug de V14.1 sin borrar manualmente la caché.

## 3. Aplicar el parche sobre una instalación V14.1 existente

1. Cierra por completo el dashboard y espera a que termine cualquier proceso Python del OCR.
2. Haz una copia de seguridad de la carpeta del proyecto si lo deseas.
3. Extrae el ZIP del parche directamente sobre la raíz del proyecto y acepta reemplazar los archivos incluidos.
4. **No borres ni reemplaces `.cache_ocr`**. Ahí puede estar la cola con actualizaciones de Excel todavía pendientes.
5. **No borres ni reemplaces `.aprendizaje`**.
6. No borres el Excel maestro, `validacion_resultados.json`, `inventario_proyecto.json` ni los checkpoints existentes.
7. Arranca el dashboard normalmente.

Al iniciar, la cola persistente de Excel vuelve a despertar y reintenta sus actualizaciones pendientes. Si la actualización guardada es válida, el contador de pendientes debe disminuir hasta cero.

Si el lote quedó en estado pausado/detenido con avance, usa **Reanudar avance guardado**. La lista de casos a omitir se reconstruirá con la regla V14.2 y las carpetas únicamente detectadas/inventariadas volverán a quedar disponibles para procesamiento.

## 4. Si el Excel todavía falla

V14.2 muestra en el dashboard la última línea útil del traceback, además de conservar el traceback completo en la cola persistente.

Si el mismo error continúa después de instalar este parche, comparte el archivo `.md` real de la bitácora generado en `errores/` (no solamente la ruta de Windows). Con el traceback completo se podrá identificar la función y línea exactas que quedan fuera de estas rutas corregidas.

## 5. Pruebas realizadas

Pruebas nuevas V14.2:

- proyección de correcciones con colecciones OCR `None`;
- aprendizaje/no-texto con OCR parcial y colecciones `None`;
- generación completa de `.xlsx` con esas colecciones `None`;
- reporte BMG configurado con OCR parcial;
- reconstrucción de reanudación con casos procesado/cancelado/detectado/inventariado;
- compatibilidad con resultados legacy completos sin campo `estado`.

Resultado: **6/6 aprobadas**.

Suite crítica combinada V14/V14.1/V14.2 (Excel, cola, edición de zonas, SOP y reanudación): **38/38 aprobadas**.

La suite global conserva los ocho fallos históricos vinculados a fixtures externos ausentes (`validacion_resultados.json` y banco externo de pruebas). En este entorno compartido, una prueba de prefetch también puede depender de la presión real de CPU porque el propio SOP aplica backpressure al superar el límite del perfil; ejecutada dentro de la suite crítica pasó correctamente.

## 6. Datos que este parche no debe tocar

- `.aprendizaje`
- `.cache_ocr` de la instalación del usuario
- correcciones confirmadas
- resultados persistidos
- checkpoint real del lote
- Excel maestro existente
- estructura 1ST/2ST

El parche contiene solamente código, pruebas y documentación. No incluye las bases SQLite generadas durante las pruebas de desarrollo.
