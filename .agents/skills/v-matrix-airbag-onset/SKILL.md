---
name: v-matrix-airbag-onset
description: Criterios de medición del primer instante de apertura de airbag. Distingue primer indicio de corroboración, exige FPS reales y nunca proclama validación sin videos reales.
---

# V-Matrix · Airbag Onset

Guía para revisar o modificar el detector de apertura (`video_airbag.py`).

## Definición operativa
La apertura es el **primer cuadro en que la bolsa es físicamente visible**,
aunque sean pocos píxeles. NO es el abombamiento del tablero, ni el reflejo, ni
el movimiento de cámara. Flujo de dos momentos: aparición corroborada → retroceso
al primer cambio conectado (backtracking al primer indicio).

## Reglas de medición
1. **FPS reales, nunca los del contenedor.** Los AVI declaran 8 fps de
   reproducción; la tasa de grabación sale del overlay `Rec…fps` (validado) o de
   config. Si la fuente es `desconocido`, el tiempo solo se acepta desde el reloj
   visible. Registrar `advertencia_fps` si se usaron fps declarados.
2. **Resolución temporal.** `resolucion_nativa_ms = 1000/fps_grabacion`. Nunca
   reportar más precisión que un cuadro; `exactitud_0_1ms_sustentada` solo con
   resolución ≤ 0.2 ms.
3. **Causas graves por cámara (B2).** `advertencia_fps`, `overlay_validado=False`,
   `overlay_error`, `advertencia_tiempo`, `advertencia_deteccion`,
   `evento_al_inicio` o ROI autoalineada sin confirmar son bloqueantes y deben
   sobrevivir a la consolidación del consenso.
4. **Consenso 3-de-4.** Con ≥4 cámaras comparables se exigen 3 coincidentes
   (±1 cuadro) para `confirmado`. Con menos, se admite la cámara ausente y rige
   `min_camaras_primera_aparicion`. Por debajo → `propuesto`/`discordancia` con
   `tiempo_propuesto_ms` SIN aplicar. La confirmación humana manda siempre.
5. **`evento_al_inicio`.** Si el evento está en el primer cuadro, no inventar el
   nacimiento: estado `evento_al_inicio` con `tiempo_ms_sospechoso`.

## Evidencia exigida antes de afirmar exactitud
- Video real anotado, 3–4 cámaras, dos tasas de adquisición, reproducción 8 fps.
- Casos: fisura/tela temprana, sin apertura, reflejos, reloj de cámara visible.
- Métrica de detección por cámara y agreement ≥ 0.95 con revisión humana (30 casos).
- Sin videos reales: mantener `validado_con_videos_reales=False` y
  `limitacion_detector` visibles. No proclamar validación.

## Benchmark de rendimiento (A8)
`python utilidades/benchmark_detector.py <video.avi>` registra fps de
procesamiento, latencia media/p95 de `cv2.phaseCorrelate`, CPU/RAM. Comparar
V15.8.1 vs V15.9 en el mismo hardware antes de publicar cambios del detector.
