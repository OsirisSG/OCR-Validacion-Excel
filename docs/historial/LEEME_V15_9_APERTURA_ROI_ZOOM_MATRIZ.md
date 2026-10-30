# LEEME V15.9 — Apertura, ROI, zoom y matriz (2026-10-12)

Versión **15.9.0** sobre V15.8.1. Guía de uso completo:
[LEEME_V15_9_APERTURA_ROI_ZOOM_MATRIZ.md](../guias/LEEME_V15_9_APERTURA_ROI_ZOOM_MATRIZ.md).

## Cambios

- **Rangos de apertura antes de procesar**: al pulsar «Procesar carpeta»
  aparece el diálogo «Configurar rangos de apertura» (verde/amarillo, con
  vista previa de la combinación) antes de cualquier trabajo. Predeterminados
  6/7 ms; validación estricta; casilla opcional para guardar la preferencia;
  instantánea por ejecución con origen trazable.
- **Detector de dos momentos**: aparición corroborada + retroceso al primer
  cambio conectado; puntuaciones separadas por fuente (fisura, tela clara,
  abombamiento, reflejo, movimiento de cámara, ruido); estado
  `evento_al_inicio` cuando la apertura está desde el primer cuadro (sin
  inventar nacimiento) con `razones_evento` guardadas por video.
- **ROI general y microzona distintas**: ROI manual bloqueada y persistente;
  sugerencia automática sólo con confirmación explícita; aceptar/ajustar/
  bloquear/revertir; una imagen pertenece a un solo visor.
- **Zoom e inspección**: 100/200/400/800 % + ajuste a pantalla, rueda,
  doble clic, pantalla completa, atajos `+`/`−`/`0`/`F`/`L` y lupa temporal
  F−1/F/F+1 con el mismo punto espacial; overlays independientes.
- **Matriz completa**: todas las posiciones esperadas (HT/RT/NT ×
  UGL/OGL/NOM, cupos 5/10 con expansión), vacantes en gris tenue sin ID ni
  tiempo, motivos de gris trazables, «Sin clasificar» con causa y enlace al
  Listado; mismos rangos en dashboard y Excel.
- **Consenso 3 de 4**: con 4 cámaras comparables, 3 coincidentes confirman;
  menos respaldo queda «pendiente de revisión» con `tiempo_propuesto_ms` sin
  aplicar; salidas separadas (primer instante por cámara + consolidado);
  estados confirmado/propuesto/discordancia/sin_evento/sin_datos; la
  confirmación humana tiene prioridad.

## Documentación relacionada

- [RESULTADOS_PRUEBAS_V15_9.md](../informes/RESULTADOS_PRUEBAS_V15_9.md).
- [ACTUALIZACION_CARPETA_V15_9.md](../informes/ACTUALIZACION_CARPETA_V15_9.md).
