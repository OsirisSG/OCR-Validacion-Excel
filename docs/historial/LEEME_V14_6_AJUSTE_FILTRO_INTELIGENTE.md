# OCR V14.6 — Ajuste fino adaptativo y filtro inteligente de lecturas

Fecha: 2026-09-24

## Objetivo

V14.6 corrige dos comportamientos observados durante la supervisión manual:

1. El ajuste fino podía perseguir inclinaciones demasiado grandes y terminar leyendo ruido del fondo.
2. La confianza OCR podía favorecer fragmentos o cadenas incoherentes frente a información con estructura empresarial más razonable.

## Ajuste fino V14.6

- Las orientaciones cardinales 0°, 90°, 180° y 270° siguen siendo la primera decisión.
- La orientación se decide **antes** del ajuste fino.
- Ajuste normal: máximo **±15°**.
- Ajuste extendido: máximo **±30°**, únicamente cuando existe evidencia geométrica fuerte de texto inclinado.
- Se elimina el uso de **±45° como ajuste fino**.
- En la orientación cardinal ganadora se hace una micro-búsqueda de **±2°** alrededor del ángulo geométrico estimado.
- Un ajuste fino nunca puede sustituir una lectura congruente por ruido sólo porque aumente la confianza OCR.

## Clasificación de lecturas

Cada candidata se clasifica como:

- Código
- Fecha
- Valor / medición
- Texto
- Ruido probable

La clasificación considera:

- presencia de letras y números;
- longitud;
- símbolos;
- coherencia entre mayúsculas y minúsculas;
- formato de fecha;
- formato numérico / unidades;
- pureza alfanumérica;
- confianza OCR;
- consenso entre variantes.

Los códigos alfanuméricos compactos y coherentes (por ejemplo `S4054664` o `abc12345`) reciben prioridad sobre fragmentos cortos o cadenas con mezcla irregular de mayúsculas/minúsculas. Una cadena como `21% : 50` no se etiqueta como código.

## Filtro visual

El editor mantiene las cuatro orientaciones disponibles, pero añade filtros opcionales:

- Todas
- Solo útiles
- Códigos
- Fechas / valores
- Texto

También muestra una tarjeta de “Mejor opción automática” con el tipo de información y un puntaje de congruencia 0–100.

Si ninguna lectura alcanza congruencia suficiente, el sistema **no sustituye automáticamente Texto correcto**. Las variantes siguen visibles para revisión manual.

## Compatibilidad

V14.6 es acumulativa sobre V14.5. No modifica destructivamente `.aprendizaje`, `.cache_ocr`, checkpoints ni la cola SQLite del Excel.
