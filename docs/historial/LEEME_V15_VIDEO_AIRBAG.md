# V15 — Análisis de video de apertura de airbag

Fecha: 2026-10-05  
Base: V14.15.1

## Objetivo

V15 integra los videos de alta velocidad al mismo lote que las fotografías. El pipeline descubre archivos dentro de carpetas `VIDEO` o `VIDEOS`, analiza automáticamente el primer cambio visual compatible con el despliegue del airbag y permite que el usuario confirme manualmente el cuadro exacto desde el dashboard.

## Carga conjunta

En **Procesar carpeta** aparece el selector **Contenido a procesar**:

- **Fotos + videos (recomendado)**: inventaría y procesa NACH/VOR junto con VIDEO/VIDEOS.
- **Solo fotos**: procesa únicamente fotografías y conserva los resultados de video ya existentes.
- **Solo videos**: analiza únicamente VIDEO/VIDEOS y conserva los resultados OCR de fotografías ya existentes.

Esto permite agregar videos a un lote ya procesado sin borrar `.aprendizaje`, `.cache_ocr` ni las correcciones anteriores.

## Detección de apertura

El analizador no extrae físicamente una imagen por cada milisegundo. Lee el video secuencialmente y compara cada cuadro con una línea base inicial. Para detectar la primera aparición de la bolsa usa cambio visual y aumento de píxeles claros dentro del área útil, ignorando márgenes donde suelen existir overlays.

Cuando encuentra un candidato conserva el número de cuadro, confianza, tiempo derivado del FPS y una vista previa. También intenta leer texto de las bandas superior e inferior del cuadro candidato usando el mismo OCR del proyecto.

## Precisión temporal

La resolución nativa depende del video:

- 1000 fps = 1.0 ms entre cuadros.
- 2000 fps = 0.5 ms entre cuadros.
- 10000 fps = 0.1 ms entre cuadros.

V15 puede mostrar décimas y calcular una estimación sub-frame, pero **no declara exactitud física de 0.1 ms** si la fuente no la sustenta. La exactitud de 0.1 ms se marca como sustentada únicamente cuando el timestamp visible o la tasa nativa proporcionan esa resolución.

Si un video contiene un timestamp visible, se intenta leer. Cuando un video aporta simultáneamente tiempo por FPS y timestamp de ensayo, esa diferencia puede utilizarse para calibrar los demás videos sincronizados antes del consenso.

## Consenso de cuatro videos

El resultado consolidado busca el grupo temporal dominante. Con la configuración predeterminada se requieren al menos **3 videos** compatibles. Por ejemplo, si tres cámaras convergen en 6.0 ms y una cuarta discrepa, el caso puede quedar como `confirmado_3_de_4`.

La tolerancia se adapta a la resolución nativa para no exigir una concordancia imposible entre cuadros de un video de 1000 fps.

## Revisión manual

El detalle del ID incluye un panel **Análisis de apertura de airbag**. Cada video permite:

- ver el cuadro candidato;
- avanzar o retroceder un cuadro;
- escribir el número exacto de cuadro;
- escribir/corregir el tiempo de apertura;
- pulsar **Confirmar apertura aquí**;
- marcar **No hay apertura en este video**.

Después de cada confirmación se recalcula el consenso y el campo `opening_time_ms`; la actualización se persiste y entra a la misma cola de Excel.

## Compatibilidad

V15 conserva OCR de fotografías, aprendizaje, correcciones, geometrías, checkpoints y cola Excel. Para un lote ya terminado se puede volver a seleccionar la misma raíz y elegir **Solo videos** para añadir la información de video sin rehacer el OCR de las fotografías.

## Limitación importante

La validación en este entorno prueba la lógica con videos sintéticos y OpenCV, pero la precisión real del punto de despliegue debe comprobarse con los videos de la cámara de alta velocidad y sus overlays reales. La detección automática es una propuesta revisable; la confirmación humana prevalece.
