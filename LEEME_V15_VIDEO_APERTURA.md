# OCR V15 — Tiempo de apertura de airbag por video

Fecha: 2026-10-05  
Base: V14.15.1

## Objetivo

Añadir análisis local de videos de alta velocidad encontrados dentro de carpetas `VIDEO` o `VIDEOS` de cada caso empresarial. El sistema busca el primer cambio visual compatible con el despliegue de una bolsa de aire, calcula un tiempo de apertura por video y consolida el resultado cuando al menos 3 de hasta 4 videos coinciden.

## Flujo automático

1. Descubre hasta 4 videos `.avi`, `.mp4`, `.mov`, `.mkv`, `.wmv` o `.m4v` por caso.
2. Construye una referencia con los primeros cuadros.
3. Analiza cambio visual y aparición de área clara, excluyendo por defecto las bandas superior/inferior para que los overlays no disparen falsos positivos.
4. Hace una pasada gruesa y después refina cuadro por cuadro alrededor del primer cambio.
5. Si el video contiene texto superior/inferior con un tiempo explícito (`ms`, `us`, `s` o timecode etiquetado), intenta leerlo con el OCR ya cargado.
6. Si no hay timestamp utilizable, calcula el tiempo desde la cadencia del video y una interpolación sub-frame.
7. Busca un consenso de al menos 3 videos dentro de la tolerancia configurada.
8. Cuando la fuente soporta físicamente 0.1 ms (>=10 000 fps o timestamp explícito con esa resolución), el consenso puede confirmarse automáticamente. En fuentes más lentas el valor a 0.1 ms queda como propuesta y exige revisión humana.

## Precisión de 0.1 ms

V15 diferencia entre **resolución física** y **estimación mostrada**:

- 10 000 fps -> 0.1 ms/cuadro: soporte nativo de 0.1 ms.
- 1 000 fps -> 1 ms/cuadro: el sistema puede interpolar y mostrar décimas, pero no las presenta como precisión física nativa.
- Si el propio video imprime `6.3 ms`, `6300 us` o un timecode equivalente y el OCR lo lee, esa fuente temporal puede respaldar décimas aunque el FPS sea menor.

La interfaz siempre muestra la resolución nativa para que el usuario sepa qué está midiendo realmente.

## Revisión manual en el dashboard

Dentro del detalle de un ID aparece **Tiempo de apertura por video**:

- miniaturas del cuadro anterior, candidato y siguiente;
- navegación cuadro a cuadro;
- tiempo automático y fuente temporal;
- texto del timestamp OCR, cuando existe;
- campo editable a pasos de 0.1 ms;
- botón **Aquí comienza la apertura**;
- botón **No se observa apertura**;
- consenso 3/4 y botón **Aceptar resultado**.

Al aceptar el consenso, `opening_time_ms` se actualiza y la cola Excel se regenera. La matriz existente mantiene los criterios <=6 ms verde, 6–7 ms amarillo y >7 ms rojo.

## Compatibilidad y rendimiento

- Los videos se procesan localmente con OpenCV; no se suben a ningún servicio.
- El análisis de videos tiene caché en `.cache_ocr/videos_apertura.json`; repetir una ejecución no vuelve a recorrer videos sin cambios salvo que se solicite reanalizar.
- El OCR de timestamp reutiliza el motor OCR del proceso y sólo se aplica a bandas del cuadro candidato.
- Los casos procesados antes de V15 pueden descubrir sus carpetas VIDEO/VIDEOS al abrirse y analizarse desde el dashboard sin rehacer todo el OCR fotográfico.
- No se modifica `.aprendizaje`, ni las correcciones de fotos, ni los checkpoints históricos.

## Configuración

La sección `video_apertura` de `config.yaml` controla duración máxima, resolución del análisis, umbrales de cambio, consenso y OCR del timestamp.

## Validación

Se incluyen pruebas sintéticas para:

- detección de una región blanca que aparece en un video de alta velocidad;
- consenso 3 de 4;
- parseo de `ms` y `us`;
- persistencia del campo `opening_time_ms` como pendiente cuando la fuente no soporta físicamente 0.1 ms;
- confirmación manual sin falsificar la resolución nativa;
- presencia del panel de revisión y sus controles ES/EN/DE.

La validación real de codecs, timestamps y exactitud temporal debe hacerse con los videos de producción del equipo Windows/RTX A3000.
