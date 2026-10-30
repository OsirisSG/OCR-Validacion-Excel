---
name: v-matrix-matrix-excel
description: Reglas de paridad de la matriz de apertura entre dashboard y Excel. Posiciones vacantes, IDs reales, rangos, trazabilidad y grupo «Sin clasificar» único.
---

# V-Matrix · Matrix Excel

Cómo mantener la paridad entre la matriz del dashboard y el reporte Excel.

## Fuente única de verdad
- Columnas, cupos y semáforo viven en `utilidades/matriz_apertura.py`.
  Dashboard y Excel las comparten; `analisis_video.py` legado no duplica reglas.
- La agrupación de casos (`agrupar_casos`) y la `causa_sin_clasificar` son las
  mismas para ambas vistas (paridad por construcción).

## Reglas de la matriz
1. **Una sola definición de columnas** HT/RT/NT × UGL/OGL/NOM, cupos 5/10 con
   expansión si hay más casos.
2. **Posiciones vacantes** en gris tenue, sin ID ni tiempo, con leyenda propia
   (distintas del gris de valor desconocido). Nunca 0 ms inventado ni IDs falsos.
3. **Celdas de caso** con semáforo compartido (verde/amarillo/rojo/gris) y motivo
   trazable (`sin_tiempo`, `pendiente_revision`, `conflicto`, `sin_caso`…).
4. **Grupo «Sin clasificar» ÚNICO (B3).** Todos los casos fuera de
   etapa/categorización (3RD, LEGACY, sin etapa, combinaciones fuera de columnas)
   aparecen en UN bloque global detrás del bloque 2ST en el Excel, con causa, ID
   real, vínculo al Listado y recuento. Ya no hay bloques intra-etapa.
5. **Instantánea de criterios.** El Excel usa `criterios_apertura_ejecucion`
   (V15.9) para que pantalla y libro no divergen; sin instantánea, reglas vigentes.
6. **1ST/2ST intactos.** Los identificadores y hojas 1ST/2ST no se alteran.

## Prueba de paridad obligatoria
- Generar Excel y dashboard sobre los MISMOS resultados y comparar IDs por
  columna y en «Sin clasificar» (incluidos `None`, `LEGACY`, `3RD`).
- Verificar concordancia de IDs, tiempos, estado y colores entre JSON, dashboard
  y Excel, antes y después de un reanálisis.
- `pruebas/test_v15_9_1_paridad_matriz.py` cubre esta paridad.

## Integridad
Exportar nunca muta los resultados compartidos: trabaja sobre una copia y no
toca `.aprendizaje`, checkpoints ni originales.
