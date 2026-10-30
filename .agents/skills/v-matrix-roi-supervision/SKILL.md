---
name: v-matrix-roi-supervision
description: Reglas de supervisión de ROI en videos de airbag. ROI bloqueada, herencia visual, microzona de nacimiento separada, y flujo real de revertir con historial.
---

# V-Matrix · ROI Supervision

Cómo revisar cambios sobre la región de interés en `aprendizaje_video_airbag.py`,
`video_airbag.py` y el visor de video del dashboard.

## Principios
1. **ROI general ≠ microzona.** La ROI general dice *dónde mirar*; la microzona
   de nacimiento dice *dónde aparece el primer fragmento*. Son objetos distintos
   y se dibujan/almacenan por separado.
2. **ROI manual bloqueada.** Una ROI dibujada o aceptada por el usuario queda
   `bloqueada=True`. El sistema no la mueve automáticamente. La autoalineación
   (ORB) solo produce `bbox_sugerida_norm`; el usuario decide
   (aceptar / ajustar / bloquear / revertir).
3. **Herencia visual auditada.** Un video hereda ROI de otro ejemplo solo con
   similitud visual mínima (`similitud_minima_zona`); el ranking compuesto
   (similitud + tipo de cámara + matches + inliers + ejemplos) debe ser
   consultable en `zona_deteccion.ranking_candidatos`.
4. **Revertir es un flujo real (A1).** Cada ROI guardada conserva la anterior en
   `historial_roi` (hasta 8, persistente). El endpoint
   `POST /api/video/zona-revertir` restaura una versión previa y reanaliza; la
   ROI desplazada entra al historial (reversible). La UI muestra ROI actual vs
   anterior con overlay punteado antes de decidir.
5. **Reanálisis sin mover ROI confirmada.** Recalcular un video o el lote usa la
   ROI vigente; nunca la sustituye por una sugerencia sin confirmación.

## Verificación de interfaz (obligatoria)
- Comparar visualmente ROI anterior y nueva antes de aceptar una sugerencia.
- Tras guardar una ROI: recalcular y confirmar que la ROI no cambió sola.
- Tras revertir: la caja visible coincide con la versión restaurada y el historial
  creció. Reiniciar el dashboard: el historial persiste.

## Integridad
El aprendizaje escribe únicamente en `.aprendizaje/zonas_video_airbag.json` y
referencias JPEG asociadas. Ninguna skill o script puede borrar ese directorio.
