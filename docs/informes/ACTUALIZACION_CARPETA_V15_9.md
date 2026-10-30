# ACTUALIZACIÓN DE CARPETA V15.9 — qué cambia y cómo aplicarlo

Versión objetivo: **15.9.0** sobre **V15.8.1**. Este informe es el documento
de cambios de la entrega **V-Matrix OCR V15.9 (apertura · ROI · zoom ·
matriz)**. El repositorio de GitHub es de sólo lectura: los cambios se
entregan como archivos modificados completos + `cambios_V15_9.patch` dentro
de un zip; no se hace push ni PR.

## Archivos modificados/nuevos del motor

| Archivo | Cambio |
| --- | --- |
| `utilidades/matriz_apertura.py` | Motor único del semáforo y de la matriz (columnas HT/RT/NT × UGL/OGL/NOM con cupos 5/10, vacantes, sin clasificar, `evaluar_apertura` con motivo). |
| `criterios_usuario.py` | Preferencia de límites con historial; instantánea por ejecución (`guardar_instantanea_ejecucion`, `cargar_instantanea_ejecucion`) con origen `predeterminado`/`vigente`/`elegido`. |
| `reporte_bmg.py` | Excel usa el mismo motor (`evaluar_apertura` compartido) y respeta la instantánea de la ejecución. |
| `generar_excel.py` | Reexportación con criterios vigentes; sin cambios de identificadores 1ST/2ST. |
| `pipeline.py` | Reanudación conserva la instantánea de criterios de la ejecución; `SolicitudPipeline` acepta `rango_apertura`. |
| `dashboard/backend/app.py` | `/api/pipeline` acepta `rango_apertura` (valida ANTES de lanzar el hilo; 422 sin trabajo si es inválido), registra la instantánea, guarda preferencia sólo con casilla marcada; `/api/config` publica `criterios_predeterminados`, `criterios_vigentes` y `criterio_efectivo`; matriz completa en `/api/resumen`. |
| `video_airbag.py` | Detector de dos momentos (aparición corroborada + retroceso al primer cambio conectado), `scores_fuentes` separados, baseline robusto, marca `evento_al_inicio` sin inventar tiempos, `razones_evento` guardadas, `consenso_videos` con `estado_consenso` 3-de-4 y salidas separadas (primer instante por cámara + consolidado). |
| `aprendizaje_video_airbag.py` | Ranking de candidatos de ROI con score compuesto (intersección sobre unión + inliers + magnitud de cambio); **umbrales de aceptación intactos**; una imagen pertenece a un solo visor. |
| `dashboard/frontend/app.js` | Diálogo «Configurar rangos de apertura» al procesar; MatrizApertura completa (vacantes, motivos, sin clasificar, cupos); zoom 100/200/400/800 + rueda/doble clic/fullscreen/teclado; lupa F−1/F/F+1; overlays ROI/Sugerida/Nacimiento independientes. |
| `dashboard/frontend/estilos.css` | Estilos del diálogo, vacantes, inspector de zoom y lupa. |
| `dashboard/frontend/i18n.js` | Traducciones EN/DE de los textos nuevos. |
| `VERSION.txt` | 15.8.1 → 15.9.0. |

## Cómo aplicar la actualización

1. Respaldar la carpeta del proyecto (o trabajar en una rama local).
2. Copiar los archivos del zip sobre el proyecto (vienen completos).
3. Opcional: aplicar `cambios_V15_9.patch` con `git apply cambios_V15_9.patch`
   si prefieres el diff sobre una copia limpia de V15.8.1.
4. Ejecutar la batería: `python -m pytest pruebas/` y `node --test pruebas/*.cjs`.
5. Reiniciar el dashboard para que el frontend recargue.

## Garantías de la publicación (reglas del plan)

- No se rompen revisiones ni reglas anteriores (la base V15.8.1 pasa igual).
- **Nunca se inventan tiempos**: el gris queda sin `opening_time_ms`, el
  estado `evento_al_inicio` queda sin `tiempo_ms` (sólo sospechoso) y el
  consenso sin respaldo deja `tiempo_propuesto_ms` **sin aplicar**.
- **No se alteran ROIs confirmadas por el usuario** (ROI manual bloqueada y
  persistente; sugerencias sólo con confirmación explícita).
- **No se sustituye una medición ausente por 0 ms**; 0 ms sólo se colorea si
  el dato es real y confiable.
- Identificadores **1ST/2ST** del Excel intactos.
- Interfaz y etiquetas en **ES/EN/DE**; ejecución **local sin internet**.

## Validaciones pendientes con datos reales

Las aceptaciones que requieren videos/casos reales quedan pendientes (no hay
datos de ensayo en el repositorio): exactitud ±1 cuadro sobre 30 casos,
acuerdo ≥ 0.95 con revisión humana, umbral 3-de-4 con lote real de 4 cámaras
y criterio de `reflejo` con reflejos reales. Detalle en
[RESULTADOS_PRUEBAS_V15_9](RESULTADOS_PRUEBAS_V15_9.md).
