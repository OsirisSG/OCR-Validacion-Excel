---
name: v-matrix-evaluation-lab
description: Banco de pruebas y puerta de publicación de V-Matrix. Suite completa, benchmark V15.8.1 vs V15.9, precisión por cámara, negativos y rendimiento. Impide aprobar con fallos críticos.
---

# V-Matrix · Evaluation Lab

Puerta de calidad antes de publicar cualquier versión de V-Matrix.

## Batería obligatoria antes de publicar
1. `python -m pytest pruebas/` → todo en verde. Falla de entorno conocida:
   `test_dashboard.py::test_estado_config_y_frontend` (exige datos procesados;
   falla igual sin carpeta procesada). Cualquier OTRA falla bloquea la publicación.
2. `node --test pruebas/*.cjs` → todo en verde.
3. Cada bug corregido aporta un test que lo reproduce (falla antes, pasa después).

## Puerta de publicación (no se aprueba si…)
- Existe un fallo crítico reproducible (B1/B2/B3 o equivalente).
- El consenso publica un tiempo `propuesto`/`discordancia` como confirmado.
- La matriz Excel y el dashboard divergen en IDs, tiempos, estado o colores.
- Una ROI confirmada por el usuario se mueve sola o no puede revertirse.
- Un JSON legacy deja de cargar o se vuelve gris sin motivo.

## Benchmark y rendimiento (A8)
- `python utilidades/benchmark_detector.py <video>` y su variante `--sintetico`.
- Comparar V15.8.1 vs V15.9 en el mismo hardware con clips nativos: fps reales de
  procesamiento, CPU/RAM/VRAM, latencia media/percentil y exactitud.
- La fase de correlación (`cv2.phaseCorrelate`) queda medida por cuadro en
  `resultado["rendimiento_detector"]`.

## Validación con datos reales (pendiente hasta tener videos)
- Exactitud ±1 cuadro en 30 casos y acuerdo ≥ 0.95 con revisión humana en 30 casos.
- Lote real de 4 cámaras para el umbral 3-de-4; casos con reflejos, sin apertura,
  dos tasas de adquisición y reproducción a 8 fps.
- Confirmación manual y máximo visible sin contaminación.
- Mientras no haya videos reales, mantener `validado_con_videos_reales=False`.

## Registro
Cada ejecución de la puerta deja evidencia: comando, resultado, hash de versión y
decisión (aprobado / retenido). Sin evidencia ejecutada no hay aprobación.
