# V14.12.1 — Etiqueta compacta de unión entrenable

Fecha: 2026-09-28

## Cambio

Se simplifica el control mostrado al unir bloques.

Antes se mostraba una explicación larga junto al checkbox. Ahora se muestra:

- `Usar unión para entrenar OCR`
- un icono `ⓘ` con ayuda contextual.

La ayuda indica: `Una línea: entrena la zona unida. Varias líneas: intenta separarlas por línea.`

## Comportamiento funcional

No cambia la lógica de V14.12:

- Si varios bloques reconstruyen una sola línea y el texto confirmado no contiene saltos de línea, se usa la zona unida como una muestra.
- Si el texto confirmado contiene varias líneas y pueden asociarse a los bloques originales, se intentan crear muestras separadas por línea.
- El checkbox continúa activado por defecto.
- La corrección se guarda aunque falle la creación de la muestra entrenable.

## Instalación

Aplicar sobre V14.12 con el dashboard cerrado. No borrar `.aprendizaje`, `.cache_ocr`, checkpoints ni la cola del Excel. Después reiniciar y usar `Ctrl+F5` si el navegador conserva el frontend anterior.
