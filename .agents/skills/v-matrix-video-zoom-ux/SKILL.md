---
name: v-matrix-video-zoom-ux
description: Requisitos de zoom, pan, pantalla completa y navegación de cuadros en el visor de video. Overlays alineados, controles visibles en fullscreen y ES/EN/DE.
---

# V-Matrix · Video Zoom UX

Guía para revisar el visor de video del dashboard (`TarjetaVideoAirbag`).

## Contratos de zoom/pan
1. **Zoom por pasos** 100/200/400/800 % + ajuste a pantalla (tecla `0`), rueda,
   doble clic y teclas `+`/`−`. La transformación imagen↔visor es única: los
   overlays se posicionan en % de la imagen, así el zoom nunca los recoloca.
2. **Pan por arrastre (A2).** Con zoom > 100 % y SIN estar dibujando ROI, el
   puntero capturado desplaza el marco (`scrollLeft`/`scrollTop`). El pan está
   separado del modo de selección de zona (`modoZona`) — nunca compiten.
3. **Pantalla completa con controles (A2).** El fullscreen se pide sobre el
   contenedor del visor CON su barra de controles (zoom, overlays, lupa), no solo
   sobre la imagen.
4. **Lupa temporal F−1/F/F+1** (tecla `L`): mismo punto espacial en tres cuadros
   para comparar el primer indicio.
5. **Overlays independientes** ROI / Sugerida / Nacimiento / Anterior, cada uno
   con su checkbox y estilo propio.

## Reglas de alineación
- Al hacer zoom (cualquier nivel) y luego guardar/reabrir, la ROI debe quedar
  sobre los mismos píxeles. Verificar con distintos aspect ratios y tras scroll.
- La ROI dibujada en modo zona usa coordenadas normalizadas [0..1] relativas a la
  imagen, no al contenedor con scroll.

## Accesibilidad e idiomas
- Atajos documentados en pantalla (`Atajos: …`).
- Todos los textos del visor pasan por `t()` (ES/EN/DE); ninguna cadena literal
  nueva sin traducir.
- Zoom accesible por teclado y botones, no solo por rueda.

## Prueba mínima manual
1. Abrir un video, zoom 800 %, pan hasta la costura, dibujar/aceptar ROI.
2. Guardar, reabrir, confirmar que la ROI sigue alineada.
3. Pantalla completa: la barra de controles es visible y funcional.
4. Cambiar idioma a EN y DE: el visor traduce sus etiquetas.
