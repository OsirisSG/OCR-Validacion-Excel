# RESULTADOS DE PRUEBAS V15.9 — Apertura, ROI, zoom y matriz

Versión: **15.9.0** · Base: **V15.8.1** · Rama local:
`codex/ocr-v15-9-apertura-roi-zoom-matriz` (el repositorio de GitHub es de
sólo lectura; la entrega es un parche local + zip).

## Resumen de ejecución (entorno local de desarrollo)

| Batería | Resultado |
| --- | --- |
| `python -m pytest pruebas/` | **462 aprobadas · 1 falla conocida** |
| `node --test pruebas/*.cjs` (24 archivos) | **24/24 en verde** |

La única falla es `test_dashboard.py::test_estado_config_y_frontend`, que
exige datos procesados en la base del dashboard (`hay_datos`) y falla desde
la línea base V15.8.1 en un entorno sin carpeta procesada. No está
relacionada con V15.9 y no se modificó su contrato.

Las pruebas nuevas de V15.9 son:

- `pruebas/test_v15_9_criterios_ejecucion.py` (13): rangos confirmados antes
  de procesar, predeterminados 6/7 ms, validación (finitos, no negativos,
  `0 ≤ verde < amarillo`), instantánea por ejecución con origen, preferencia
  guardada sólo con casilla marcada y rechazo del trabajo con rangos
  inválidos.
- `pruebas/test_v15_9_matriz_completa.py` (7): las 7 columnas con sus cupos
  (5/10), vacantes sin ID ni tiempo, gris nunca es 0 ms, expansión de cupos,
  «Sin clasificar» con causa y semáforo compartido con el Excel.
- `pruebas/test_v15_9_detector_dos_momentos.py` (5): razones del evento
  (dos momentos, fuentes separadas, reloj), `evento_al_inicio` sin inventar
  tiempo, rechazo de flash global y de abombamiento.
- `pruebas/test_v15_9_consenso_3_de_4.py` (9): 3-de-4 confirma, menos
  respaldo queda propuesto/discordancia con tiempo propuesto (nunca
  autoaplicado), cámaras raras/excluidas no destruyen el consenso,
  confirmación humana manda y estados sin_evento/sin_datos/evento_al_inicio.
- `pruebas/test_v15_9_apertura_zoom_ui.cjs` (4): el diálogo se abre ANTES de
  procesar, envía `rango_apertura`, valida límites; zoom 100/200/400/800 con
  rueda/doble clic/teclado, lupa F±1, overlays independientes; matriz con
  vacantes y sin clasificar; i18n EN/DE del diálogo.

## Cobertura de las fases

- **Fase 0**: base de pruebas con `git worktree` de la versión previa; la
  batería completa se corrió antes y después. Validación ±1 cuadro con datos
  reales: **pendiente** (no hay videos de ensayo en el repositorio).
- **Fase 0.5**: cubierta por `test_v15_9_criterios_ejecucion.py` +
  contratos de `test_v15_9_apertura_zoom_ui.cjs`.
- **Fase 1**: cubierta por `test_v15_9_detector_dos_momentos.py` y las
  regresiones de `test_ruptura_real.py` (30 casos sintéticos de ruptura).
- **Fase 2**: cubierta por las regresiones de aprendizaje
  (`test_v15_7_bugs_prioritarios.py`, `test_v14_9_*`) que fijan los
  umbrales de selección de zona y el bloqueo de ROI manual.
- **Fase 3**: cubierta por `test_v15_9_apertura_zoom_ui.cjs`.
- **Fase 4**: cubierta por `test_v15_9_matriz_completa.py` +
  `test_matriz_apertura_dashboard_v7.py`.
- **Fase 5**: cubierta por `test_v15_9_consenso_3_de_4.py` y las
  regresiones de consenso de `test_v15_7_bugs_prioritarios.py` /
  `test_v15_6_tiempo_video_estable.py` / `test_ruptura_real.py`.
- **Fase 6**: verificación de `analisis_video.py` (legado): no duplica la
  lógica del semáforo (sólo `utilidades/matriz_apertura.py` +
  `criterios_usuario.py`). Cachés acotadas y con identidad de archivo:
  `_CACHE_RELOJ_MAX = 4096` con desalojo, caché de video invalidada por
  `ALGORITMO_VERSION` y `firma_video.firma_contenido` (identidad por bytes).

## Contratos que no se rompieron

- Identificadores del Excel (1ST/2ST) intactos.
- Estados legados de consenso (`confirmado_manual`, `primera_aparicion`,
  `sin_consenso`, `sin_datos`) intactos; `estado_consenso` es un campo nuevo.
- La confirmación humana nunca se reemplaza por un consenso automático.
- Nunca se inventan tiempos: el gris queda sin `opening_time_ms` y el estado
  `evento_al_inicio` queda sin `tiempo_ms` (sólo `tiempo_ms_sospechoso`).
- Interfaz local, sin internet; ES/EN/DE conservados y ampliados.

## Pendientes con datos reales (aceptación futura)

1. Exactitud de ±1 cuadro contra cronómetro de referencia (30 videos).
2. Acuerdo ≥ 0.95 con la revisión humana de 30 casos reales.
3. Umbral de consenso 3-de-4 con un lote real de 4 cámaras.
4. Criterio de definición de `reflejo` con reflejos reales (los límites de
   medición no se tocaron).
