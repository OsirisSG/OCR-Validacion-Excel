# V14.11 — recortes inclinados y muestras visuales más limpias

V14.11 parte de V14.10 y conserva aprendizaje inmediato, autoentrenamiento,
persistencia rápida, cola Excel durable, editor, orientaciones y modelo visual.

## Problema corregido

Una selección rectangular alineada a la pantalla puede incluir caracteres de
otra línea cuando la etiqueta está inclinada. Esa contaminación perjudica tanto
la relectura de la zona como una muestra enviada al entrenamiento visual.

## Nuevo selector inclinado

En **Texto omitido** la selección manual conserva el rectángulo clásico, pero
ahora puede:

- moverse sin volver a dibujarlo (`Mover recorte`);
- inclinarse entre -45° y +45°;
- volver a 0° en un clic;
- mostrar si el polígono se sale de la imagen;
- releerse después de rectificar la perspectiva del recorte.

La inclinación modifica el recorte real que recibe el OCR; no es solamente una
rotación visual del visor.

## Entrenamiento

Si se activa **Proponer esta región como ejemplo para entrenamiento OCR**, la
muestra visual se genera mediante las cuatro esquinas del recorte inclinado y
se rectifica con `warpPerspective`. Así el dataset contiene la línea elegida y
reduce la presencia de texto vecino.

Las regiones OCR detectadas automáticamente ya conservaban `poligono_lectura`;
V14.11 extiende esa geometría precisa a las regiones que el usuario dibuja
manualmente.

La base SQLite se migra de forma aditiva con `poligono_json` en
`anotaciones_regiones`. Las anotaciones antiguas siguen siendo válidas.

## Compatibilidad

No se elimina ni reemplaza `.aprendizaje`, `.cache_ocr`, checkpoints, resultados,
cola Excel ni modelos visuales. Las selecciones antiguas sin polígono continúan
usando el comportamiento rectangular anterior.
