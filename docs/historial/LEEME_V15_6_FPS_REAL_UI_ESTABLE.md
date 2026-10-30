# V15.6 — FPS real del video + revisor estable

Este parche incremental parte de V15.5.

## Corrección crítica de tiempo

Algunos AVI EDAG declaran **8 fps** en el contenedor para reproducción, aunque el overlay del propio video indica la tasa real de captura, por ejemplo `Rec5000 fps`.

V15.6 separa ambas cosas:

- `FPS del archivo`: velocidad de reproducción reportada por OpenCV/AVI.
- `FPS de grabación`: tasa real tomada de `RecXXXX fps` en el overlay.
- La resolución temporal y el tiempo de apertura usan siempre los FPS de grabación cuando están disponibles.

Caso comprobado:

- archivo: 8 fps;
- overlay: `Rec5000 fps`;
- cuadro 11;
- reloj superior derecho: `2.2`.

Resultado V15.6: **5000 fps, 0.200 ms/cuadro y 2.2 ms**. Nunca 1375 ms.

También se reparan en memoria resultados antiguos que quedaron guardados con 8 fps, y el consenso de cámaras vuelve a normalizarlos antes de calcular `opening_time_ms`.

El parser tolera errores OCR comunes como `Rec5O00 fps` (letra O por cero).

## Revisor de video estable

- la imagen y los controles de transporte permanecen fijos al revisar en escritorio;
- timeline, ±1, ±10, frame exacto y confirmar ya no cambian de posición por mensajes o datos que aparecen/desaparecen;
- se reserva espacio para mensajes para evitar saltos de layout;
- el cálculo provisional del tiempo usa `frame / FPS_real` desde cero mientras el backend lee el reloj del mismo frame;
- el backend sigue siendo la fuente autoritativa y nunca guarda tiempos negativos.

## Caché y Excel

V15.6 cambia la versión del algoritmo, por lo que **Reanalizar sólo videos** fuerza resultados nuevos de video sin repetir OCR de imágenes. El consenso corregido sigue alimentando `opening_time_ms`, la matriz del dashboard y el Excel con los umbrales configurados.

## Verificación

Se añadieron pruebas específicas para:

- 8 fps de reproducción + `Rec5000 fps`;
- cuadro 11 = 2.2 ms;
- reparación de consenso antiguo;
- OCR `Rec5O00 fps`;
- rechazo de negativos;
- presencia del panel estable en frontend.
