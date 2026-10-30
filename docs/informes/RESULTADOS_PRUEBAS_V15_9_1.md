# Resultados de pruebas · V15.9.1 (r1 correctivo de auditoría)

**Fecha:** 2026-10-12 · **Base:** V15.8.1 + parche V15.9.0 + correcciones r1.
**Entorno:** Linux (sandbox CI), Python 3.13, Node 20; sin videos reales ni
GPU/RTX (las validaciones con datos reales siguen pendientes, ver final).

## Batería Python

`python -m pytest pruebas/`

| Métrica | Resultado |
|---|---|
| Aprobadas | 505 |
| Fallas | 1 (`test_dashboard.py::test_estado_config_y_frontend`) |

La única falla es la conocida de entorno: exige una carpeta ya procesada y
falla igual en V15.8.1 y V15.9.0 sin datos. No hay fallas nuevas.

## Batería Node

`node --test pruebas/*.cjs` → **34/34 en verde**, incluidos los 7 contratos
nuevos de V15.9.1 (A1, A2, A3, A4, A7, B3, B1/B2).

## Pruebas nuevas (una por hallazgo de la auditoría)

| Archivo | Cubre |
|---|---|
| `pruebas/test_v15_9_1_consenso_publicacion.py` | B1 (propuesta no publicada), B2 (causas graves: FPS, overlay dudoso, ROI incierta), precedencia manual, compatibilidad con consensos históricos V15.8.1, y end-to-end hasta la fila del dashboard (`pendiente_revision` con valor solo en tooltip). |
| `pruebas/test_v15_9_1_paridad_matriz.py` | B3: bloque único «Sin clasificar» en el Excel con causa/ID/vínculo/recuento; igualdad de IDs dashboard↔Excel↔Listado con `None`, `LEGACY`, `3RD` y combinaciones fuera de columnas. B1/B2 end-to-end hasta la EXPORTACIÓN: consenso propuesto y causa grave pintan gris con motivo «Pendiente de revisión» (medida visible solo en comentario) y el confirmado limpio se colorea. |
| `pruebas/test_v15_9_1_roi_reversion.py` | A1: historial persistente (hasta 8), reversión real y reversible, selección por índice, errores sin historial, exposición del historial al frontend y endpoint `POST /api/video/zona-revertir`. |
| `pruebas/test_v15_9_1_compatibilidad_y_preferencias.py` | A5 (legacy no se vuelve gris: raíz y `metadata_ruta`, con confiabilidad), A6 (persistencia atómica en perfil legacy y empresarial, reanudación, sin `archivo_salida`), A7 (predeterminados nunca guardan preferencia; elegido con/sin guardar). |
| `pruebas/test_v15_9_apertura_zoom_ui.cjs` (ampliado) | Contratos A1/A2/A3/A4/A7/B3/B1-B2 en frontend, backend, CSS e `index.html`. |

## Reproducción de los bloqueantes antes de corregir

- **B1:** 3 cámaras comparables, 2 coincidentes y 1 sin evento → V15.9.0
  devolvía `consenso_valido == True` con `estado_consenso == 'propuesto'`.
  V15.9.1: `False`; el dashboard deja el campo `pendiente_revision`.
- **B2:** 3 cámaras coincidentes con una marcada por causa grave → V15.9.0
  consolidaba `requiere_revision == False`. V15.9.1: la señal sobrevive, el
  motivo identifica la cámara y `consenso_valido == False`.
- **B3:** un caso `3RD/HT/UGL` aparecía en `sin_clasificar` del dashboard pero
  no en la hoja Resumen del Excel. V15.9.1: bloque único global con los mismos
  IDs en ambas vistas (prueba de paridad).

## Benchmark (A8)

`python utilidades/benchmark_detector.py --sintetico` (clip 640×480, 30 frames,
2 repeticiones, este entorno):

- fps de procesamiento: ~31 fps (mínimo de 0.65 s por video).
- `cv2.phaseCorrelate`: media 4.14 ms/cuadro, p95 5.45 ms/cuadro,
  ~12.8 % del tiempo total del análisis.
- RAM máxima del proceso: ~116 MB.

El harness (`utilidades/benchmark_detector.py`) acepta videos reales
(`video.avi --repeticiones N --salida informe.json`) para repetir la medición en
el hardware final y comparar V15.8.1 vs V15.9 con la misma orden. El detector
queda instrumentado (`resultado["rendimiento_detector"]`).

## Pendiente con datos reales (sin cambios frente a V15.9.0)

- Exactitud ±1 cuadro en 30 casos y acuerdo ≥ 0.95 con revisión humana (30 casos).
- Lote real de 4 cámaras para el umbral 3-de-4, reflejos reales, dos tasas de
  adquisición y reproducción a 8 fps; caso sin apertura y confirmación manual.
- Benchmark V15.8.1 vs V15.9 en hardware con RTX con clips nativos (CPU/RAM/VRAM,
  latencia media/percentil y exactitud).
- Interacción real en navegador para A1/A2 (pan a 800 %, fullscreen, reversión y
  persistencia tras recarga) con capturas; los tests de este parche verifican
  contratos y lógica, no un navegador real.

## Skills (S0)

Las seis skills están integradas en `.agents/skills/` (+ `AGENTS.md`), con front
matter YAML validado (`name` = carpeta, `description` no vacía). La revisión
trazable por skill ejecutada durante la preparación de este parche (condición 2
de la puerta de skills) está documentada en
[REVISION_SKILLS_V15_9_1.md](REVISION_SKILLS_V15_9_1.md).
