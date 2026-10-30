# Plan de corrección R12

## Objetivo
Corregir la diferencia entre **pendiente de procesamiento** y **abstención/gris**, y hacer la decisión automática de apertura más explicable y defendible.

## Cambios
1. Durante una ejecución activa, un caso sólo deja de ser pendiente cuando su estado es realmente final (`procesada`, `procesada_con_advertencias`, `con_conflictos`, `completado` o un resultado legacy definitivo sin estado transitorio).
2. Los casos `detectada`, `inventariada`, `procesando`, `pendiente`, etc. se muestran en azul y no contaminan el gris.
3. La leyenda de la matriz ya no pinta `origen_criterio` como si fuera un color.
4. El resumen en vivo expone confirmadas, estimadas automáticas, abstenciones y pendientes.
5. La decisión automática usa puertas explícitas: onset local nuevo, previo limpio, continuidad, crecimiento/inicio fuerte, geometría coherente y ausencia de riesgo grave.
6. Si no existe mapa de deformación, un solo indicio aislado no basta; se exige doble señal coherente o crecimiento físico claro.
7. Los tooltips muestran puertas, bloqueos y riesgos para explicar por qué un caso obtuvo color o quedó en abstención.

## Semántica
- Azul: procesamiento pendiente.
- Gris: caso ya evaluado, pero con evidencia insuficiente/conflicto/referencia temporal no válida.
- Verde/amarillo/rojo: tiempo defendible según límites elegidos.
- Un color automático estimado no equivale a publicación automática.
