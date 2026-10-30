# V7 — Reporte BMG 1ST + 2ST y matriz de tiempo de apertura

Esta versión parte de V6. No cambia el flujo de corrección OCR por orientación que ya estaba validado.

## Qué cambia

### Dashboard / Resumen

Se añade una matriz de resultados inspirada en la hoja `Übersicht Standversuche` del Excel de referencia.

- Se muestran dos bloques en la misma vista: `1ST` y `2ST`.
- Las columnas son:
  - +85 °C / UGL
  - +85 °C / OGL
  - +85 °C / nominal
  - RT / nominal
  - -35 °C / nominal
  - -35 °C / OGL
  - -35 °C / UGL
- Cada celda contiene el número de prueba.
- Al hacer clic en una prueba, el dashboard abre `Listado`, aplica la búsqueda por número de prueba y resalta la carpeta exacta.

### Semáforo de tiempo de apertura

Este semáforo es independiente del semáforo de calidad OCR.

| Estado | Regla |
|---|---|
| Verde | tiempo <= 6 ms |
| Amarillo | tiempo > 6 ms y <= 7 ms |
| Rojo | tiempo > 7 ms |
| Gris | dato no disponible, no numérico o todavía en conflicto/revisión |

La fuente preferida es `opening_time_ms`, campo que ya forma parte del contrato empresarial y del extractor OCR. Si el dato todavía no puede obtenerse con fiabilidad, el sistema no inventa un valor: la prueba queda gris.

## Excel BMG

La V7 incorpora `plantillas/reporte_bmg_1st_2st.xlsx`, derivada del libro de referencia suministrado.

Cuando el perfil procesado es empresarial y no se selecciona explícitamente otra plantilla:

1. se genera un único libro con 1ST y 2ST;
2. `Versuchsmatrix` contiene la lista detallada;
3. `Übersicht Standversuche` contiene las matrices de 1ST y 2ST;
4. el color de cada número de prueba usa `opening_time_ms` con las mismas reglas del dashboard;
5. las celdas del resumen enlazan internamente a la fila correspondiente de `Versuchsmatrix`;
6. las pruebas conocidas sin tiempo de apertura aparecen en gris;
7. las posiciones sin prueba permanecen vacías.

La plantilla admite 50 casos 1ST y 50 casos 2ST, de acuerdo con el programa x50 de referencia. Si se excede esa capacidad, la generación se detiene con un error explícito antes de deformar el libro.

## Orden de la lista detallada

Dentro de cada etapa se usa el orden del documento de referencia:

1. NT / nominal (10)
2. NT / OGL (5)
3. NT / UGL (5)
4. HT / nominal (10)
5. HT / OGL (5)
6. HT / UGL (5)
7. RT / nominal (10)

En el resumen se conserva el orden visual del ejemplo: +85 UGL, +85 OGL, +85 nominal, RT nominal, -35 nominal, -35 OGL, -35 UGL.

## Compatibilidad

- V6 sigue siendo la base funcional del OCR y de la corrección por giro.
- El nuevo reporte BMG es modular. Si la plantilla BMG no existe, el generador anterior sigue disponible.
- Una plantilla empresarial seleccionada explícitamente por el usuario conserva prioridad.
- No se modifica `.aprendizaje/aprendizaje.sqlite3`.

## Archivos principales modificados

- `reporte_bmg.py` — nuevo adaptador de Excel BMG.
- `generar_excel.py` — activa el reporte BMG cuando corresponde.
- `reglas_cumplimiento.yaml` — añade `tiempo_apertura_ms`.
- `config.yaml` — añade color gris y configuración del reporte.
- `dashboard/backend/app.py` — expone estado de apertura y matriz 1ST/2ST.
- `dashboard/frontend/app.js` — dibuja la matriz y enlaza con Listado.
- `dashboard/frontend/estilos.css` — apariencia de la matriz y resaltado de la fila seleccionada.
- `dashboard/frontend/index.html` — versión de assets para evitar caché vieja.
- `plantillas/reporte_bmg_1st_2st.xlsx` — libro base del formato solicitado.

## Pruebas añadidas

- `pruebas/test_reporte_bmg_v7.py`
- `pruebas/test_matriz_apertura_dashboard_v7.py`

Cubren 1ST + 2ST, los cuatro estados del tiempo de apertura, el tratamiento gris de conflictos, la posición de las pruebas en el resumen y el enlace interno a la lista del Excel.
