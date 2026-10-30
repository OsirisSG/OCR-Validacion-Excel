# V15.9 — Apertura, ROI, zoom y matriz completa (guía de uso)

Esta guía describe las funciones nuevas de **V15.9.0** para el flujo de
airbag (1ST/2ST). No cambia los límites de medición ni la regla de tiempos:
FPS, frames y el cálculo de la apertura siguen intactos. Sólo cambia *qué
haces* con los rangos, la región de interés, la inspección de cuadros y la
matriz resumen.

## 1. Rangos de apertura antes de procesar (Fase 0.5)

Al pulsar **«Procesar carpeta»** aparece primero el diálogo
**«Configurar rangos de apertura»**. No empieza ningún trabajo (ni OCR, ni
lectura de videos, ni escrituras) hasta que elijas una acción:

- **«Procesar con estos rangos»**: usa los valores escritos (p. ej. verde
  hasta 5.5 ms y amarillo hasta 6.5 ms).
- **«Usar predeterminados (6 / 7 ms)»**: usa los valores iniciales del
  proyecto sin tocar tu preferencia guardada.
- **«Cancelar»**: no procesa nada.

Casilla opcional (apagada por defecto):
**«Guardar para próximas carpetas (preferencia permanente)»**. Si no la
marcas, los rangos elegidos sólo aplican a este lote (instantánea de la
ejecución) y tu preferencia global queda como estaba.

Reglas de validación: dos números finitos en milisegundos (se admiten
decimales), no negativos y siempre `0 ≤ verde < amarillo`. La combinación
definitiva se muestra antes de iniciar. El **gris nunca se sustituye por
0 ms**: significa «sin tiempo fiable, pendiente/conflicto o sin caso».

Los mismos rangos se aplican al **semáforo del dashboard** y al **Excel**;
si después cambias los rangos en «Definir rangos del tiempo de apertura»,
la matriz y la leyenda se actualizan (vuelve a exportar el Excel).

## 2. ROI general y microzona de nacimiento (Fase 2)

- La **ROI general** («dónde mirar») y la **microzona de nacimiento**
  («dónde nació realmente») son regiones distintas.
- Una ROI manual **bloqueada** se conserva: el sistema no la mueve ni la
  entrena mientras esté bloqueada. Puedes revertir a la última ROI guardada.
- La **ROI sugerida** (aprendizaje automático) sólo se aplica si la aceptas
  explícitamente; nunca se coloca sola sobre una ROI manual confirmada.
- El punto exacto de nacimiento se ajusta a mano en el zoom de la zona
  («✎ Ajustar nacimiento a mano») o se afina automáticamente («◎ Afinar
  automáticamente»). La microzona se usa para recortar el aprendizaje visual
  (F-3…F+3), no para cambiar el tiempo de apertura.

## 3. Zoom y lupa del visor de video (Fase 3)

Sobre el cuadro actual dispones de una barra de inspección:

- **Zoom 100 / 200 / 400 / 800 %** con botones, la rueda del ratón sobre el
  marco, doble clic (alterna 100 ↔ 400) y teclado: `+`/`−` cambia de paso,
  `0` ajusta a pantalla y `F` activa pantalla completa.
- **«Lupa F±1»** (tecla `L`): muestra F−1, F y F+1 con el mismo punto
  espacial en los tres cuadros para comparar el primer indicio.
- **Overlays independientes**: puedes encender y apagar por separado
  *ROI*, *Sugerida* y *Nacimiento*.
- Los atajos de cuadro siguen igual: `←`/`→` (1 cuadro),
  `Shift+←/→` (10 cuadros), `Inicio`/`Fin` (extremos).
- El zoom nunca recoloca los overlays ni altera las coordenadas guardadas:
  la transformación imagen↔visor es única.

## 4. Matriz de apertura completa (Fase 4)

- La matriz muestra **todas las posiciones esperadas** de HT/RT/NT ×
  UGL/OGL/NOM para 1ST y 2ST, con sus cupos (5 o 10 según la combinación).
- **Posición sin caso** = celda «vacante» en gris tenue con borde, sin ID ni
  tiempo, distinta del gris de caso no confiable. Se explica en la leyenda.
- Los cupos se expanden solos si hay más casos de los esperados.
- **«Sin clasificar»** agrupa los casos sin etapa, temperatura o generador
  verificable (con la causa a la vista). Se cuentan para que ningún caso
  desaparezca del resumen. Al hacer clic en una celda se localiza su carpeta
  en el Listado.
- Los identificadores del Excel (1ST/2ST) no se alteran y nunca se inventan
  identificadores ni tiempos.

## 5. Consenso de videos (Fase 5)

- La salida es doble: **primer instante fiable por cámara** y **resultado
  consolidado del caso**.
- Con **4 cámaras comparables** (o todas las disponibles si hay menos), la
  coincidencia de **3** confirma automáticamente. Menos respaldo queda
  **«pendiente de revisión»** (estado `propuesto` o `discordancia`) y el
  sistema conserva el tiempo propuesto **sin aplicarlo**.
- Estados visibles: `confirmado`, `propuesto`, `discordancia`, `sin_evento`,
  `sin_datos` (y `evento_al_inicio` por cámara cuando la apertura ya está
  desde el primer cuadro).
- Las **confirmaciones humanas tienen prioridad** sobre cualquier consenso
  automático. Las vistas de respaldo (p. ej. SCHEIBE) no definen el tiempo.

## 6. Marca `evento_al_inicio` (Fase 1)

Si la apertura ya es visible desde el primer cuadro, el detector lo marca
`evento_al_inicio`: **no inventa un nacimiento en el frame 0**, conserva el
primer indicio visible y deja el tiempo confirmado vacío (sólo queda el
tiempo sospechoso para orientar la revisión manual).

## Puntos pendientes con datos reales

- La exactitud de ±1 cuadro y el acuerdo ≥ 0.95 sobre 30 casos reales
  siguen **pendientes de validación con videos reales** (en el repositorio
  no hay videos de ensayo).
- Ver [RESULTADOS_PRUEBAS_V15_9](../informes/RESULTADOS_PRUEBAS_V15_9.md).
