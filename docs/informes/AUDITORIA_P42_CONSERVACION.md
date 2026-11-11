# V16.0.52 P42 r3 — conservación y estado de validación

Estado: **borrador; no aprobado para main**. Base de revisión: `0d283730476404ad7812d87103ef197c1e98509b`.

## Correcciones implementadas

- Recuperadas funciones de proveedor y normalización desde las copias `documentos/logicas`, contrastadas con las pruebas P29/P30/P33. La sintaxis del nivel exige dos dígitos y K/S; se recupera la gramática específica de serie de tablero.
- El nombre accesible de la matriz conserva número de prueba y tiempo. La descripción accesible vuelve a exponer la auditoría. El tooltip visual conserva su diseño de tiempo breve.
- `_poblar_lista` usa actualización aditiva cuando hay datos existentes: no mueve filas; conserva valores, fórmulas, comentarios, hipervínculos y cabeceras; sólo rellena celdas vacías con valores publicables. Las discrepancias quedan en `ULTIMAS_DISCREPANCIAS` y, al generar el libro, en el informe `.relleno.json`.
- Números repetidos en origen o destino se rechazan antes de escribir. Esto evita mezclar 1ST y 2ST, pero exige resolver la identidad: no se adivina la etapa a partir de la fila. Un número corregido se añade como otra fila; no usurpa la anterior.
- Sólo la plantilla institucional distribuida, comprobada por SHA-256, permite regeneración con limpieza. Una copia modificada se considera libro del usuario.
- `limpiar_ejemplos` ya no toma todos los números del libro de entrada como ejemplos. Requiere `fase3.numeros_ejemplo_confirmados` explícito.
- Identidad de build, backend, caché y soak sincronizada a 16.0.52; esto no cambia el algoritmo de vídeo ni acredita exactitud.

## Auditoría de escrituras destructivas

Referencias por función para no depender de desplazamientos de líneas. El inventario adjunto `AUDITORIA_P42_ESCRITURAS.tsv` contiene archivo y línea actuales de los patrones encontrados por análisis AST. Es detección sintáctica, no prueba de seguridad de todas las escrituras dinámicas.

| Archivo / función | Comportamiento y riesgo | Estado |
|---|---|---|
| reporte_bmg.py / _poblar_lista, _escribir_fila | Limpiaba A:BC y escribía None: pérdida de datos y comentarios. Crítico. | Ruta aditiva para libros existentes; limpieza reservada al ejemplo institucional conocido. |
| reporte_bmg.py / _previos_por_caso, _conservar_previos | Tope 400 y elección del primer número repetido. No preservaba filas ausentes, comentarios ni conflicto contra nueva lectura. Alto. | La ruta aditiva no depende de estos helpers legados. |
| reporte_bmg.py / _rellenar_lista | Infería ejemplos desde el mismo libro del usuario. Alto si limpiar_ejemplos=True. | Corregido mediante lista explícita. El emparejamiento antiguo y la propagación de constantes requieren revisión adicional. |
| reporte_bmg.py / _limpiar_bloques_historicos_matriz, _poblar_matriz | Borra y reconstruye IDs/colores en Übersicht. Alto si esa hoja tiene anotaciones manuales. | No corregido en esta revisión; no afirmar conservación integral del libro. |
| reporte_bmg.py / _crear_trazabilidad, _crear_diccionario, _crear_evidencia_video, _crear_matriz_apertura_dinamica | Elimina/recrea hojas derivadas existentes. Alto para anotaciones humanas añadidas allí. | Pendiente de estrategia explícita de archivo/historial. |
| ordenar_libro.py / contador_en_banda | Borra o mueve SUBTOTAL de A6 según modo. | Herramienta de formato separada; no ejecutar sobre originales durante esta revisión. |
| utilidades/relleno_libro.py / aplicar | Sólo llena vacíos; no sobrescribe. | Guardas presentes. Su emparejamiento por número no distingue duplicados de etapa. |
| utilidades/rescate_columnas.py / aplicar | Sólo llena vacíos. | Guardas presentes; revisar legitimidad de las derivaciones, no sólo la escritura. |
| utilidades/corregir_libro.py / corregir | Sustituciones XML explícitas de celdas. | Uso bajo revisión de correcciones; no es parte de la exportación normal. |

La corrección r3 original era insuficiente: hacía prevalecer cualquier nueva lectura sobre el valor anterior y recuperaba únicamente vacíos. No detectaba números ambiguos ni preservaba filas históricas ausentes. Las pruebas sintéticas añadidas reprodujeron cinco fallos antes del cambio y pasan después.

## Tablero y campos de contexto

El análisis de llamadas del árbol activo no encontró una llamada desde `pipeline.py`/`flujo_empresarial.py` al pipeline especializado `utilidades.tablero_pipeline.analizar_fotos`. Lo invoca `tablero_caso.py`. El lote especializado usa `leer_tablero_lote.py` → `evidencia_tablero.py`. Esto explica una posible separación entre la corrida normal y la evidencia especializada; no demuestra qué comando se ejecutó en el equipo del cliente.

`analizar_fotos` descarta extensiones no admitidas e imágenes no legibles. Sin motor OCR conserva propuestas/dudas sin lectura. Para cerrar el diagnóstico se necesita registrar: comando ejecutado, rutas relativas de fotos, clasificación de anclas, disponibilidad del OCR, recortes y conteos de evidencia por campo antes de generar Trazabilidad. No convertir propuestas en valores confirmados sólo para llenar columnas.

`flujo_empresarial.py` sí contempla motivo explícito mediante encabezados como MOTIVO/TEST REASON. No debe inferirse motivo ni laboratorio desde fabricante o nombre de carpeta. La derivación de semana debe exigir perfil EDAG explícito, número WWYYNN válido y fecha que corrobore semana/año; fuera de ese contrato, abrir duda. `rescate_columnas.planificar` actualmente deriva semana ISO desde fecha sin esa guarda de perfil: queda señalado para revisión. No se han inventado valores para Semana/Motivo/Fecha/Lugar.

## Evidencia y límites

- 112 pruebas focalizadas aprobadas; 12 pruebas adicionales de integridad/documentación aprobadas (hay solapamiento entre ambos conjuntos).
- Node: 54 aprobadas, 0 fallidas.
- La primera suite completa pudo ejecutar 1739 casos: 1593 aprobados, 67 fallidos y 79 omitidos; antes no podía recogerse por imports ausentes. Incluye 2 fallos P30 ya corregidos después de esa ejecución. Los resultados definitivos y comparación con main se adjuntan por separado.
- No se han desactivado las pruebas fallidas del detector ni relajado la puerta de publicación.
- El guardado de un libro sintético con 11 imágenes conserva las 11, los comentarios en Versuchsmatrix/Rangos y el hash del archivo de entrada. No equivale a una validación del libro real.
- No se dispone aquí del conjunto completo `libros/` descrito en los nuevos documentos. No se certifica ≥198/200 ni conservación de las 11 imágenes de esos libros reales. Las pruebas nuevas usan libros sintéticos.
- No se modifican SQLite, aprendizaje, validacion.json ni fotos/vídeos originales.

## Reversión

Cada cambio de esta revisión es un commit de la rama. Revertir esos commits conserva el historial y devuelve el código previo; no aplicar una reversión sobre libros de producción. El diff unificado adjunto permite `git apply --check` y `git apply -R` sobre la base indicada, en una copia limpia. Los libros de entrada deben mantenerse como originales y generar resultados en otra ruta.

La prueba de CSS ahora admite espacios alrededor de `:` sin cambiar la exigencia de `position: sticky`. La prueba organizativa conserva una lista cerrada de documentos y manifiestos originales del paquete en la raíz, por el requisito de transferirlos sin pérdida; los documentos nuevos permanecen en docs/.

## Comparación ejecutada con main

En el mismo entorno, main `16f6b18` produjo 68 fallos, 1109 aprobaciones y 54 omisiones. La revisión intermedia produjo 66 fallos, 1600 aprobaciones y 79 omisiones. 63 fallos son comunes, incluyendo detector/consenso, módulo histórico APLICAR_PARCHE_V15_10 ausente y permisos ejecutables de lanzadores Mac. Los tres fallos adicionales eran organización de documentos, enlace al informe aún no creado y comprobación CSS sensible a espacios; quedaron corregidos y verificados por separado. Resultado definitivo en RESULTADOS_P42_REVISION.txt. No se ha cambiado video_airbag.py respecto de main.

## Verificación con el libro disponible

Se recibieron y leyeron 04_REPRODUCIR.md y 05_INVENTARIO.md. Se ejecutó simular_borrado.py con la muestra V16.0.52 del super parche y la evidencia real del diagnóstico (10 casos, seis campos). Resultado: cero celdas antes ocupadas modificadas o perdidas en Versuchsmatrix/Rangos; 11 imágenes conservadas con bytes idénticos. No se sustituye el A/B solicitado sobre V16.0.51 ni la referencia corregida, todavía no disponibles.

Suite definitiva: **1604 aprobadas, 63 fallidas, 79 omitidas**. Los 63 fallos son un subconjunto exacto de los fallos reproducidos en main. Node: **54/54**. Publicación retenida.
