# OCR V14.15 — Editor de bloque unificado e i18n reforzado

Fecha: 2026-09-28  
Base: V14.14

## Editor unificado

La barra ya no muestra dos acciones separadas para `Ajustar / dividir bloque` y `Mover bloque`. Se sustituyen por **Editar bloque**.

Al seleccionar un bloque desde esta herramienta se conserva en el mismo flujo:

- mover la región;
- modificar X/Y/ancho/alto;
- arrastrar límites;
- editar cuatro esquinas;
- corregir inclinación;
- releer la región;
- dividir en dos regiones;
- editar el texto final;
- confirmar y alimentar el aprendizaje con el estado final.

No se modifica el backend de aprendizaje de V14.14. Los movimientos provisionales siguen sin entrenar; solo el resultado confirmado se persiste y puede incorporarse al dataset visual.

## Idiomas

Se amplió ES/EN/DE para etiquetas dinámicas que podían quedar parcialmente en español después de renderizados de React. Entre ellas: `Editar bloque`, `Completar`, `Reabrir`, `Quitar`, `Restaurar`, `Marcar completada`, colores del resumen, `carpetas`, `visibles`, `Actualizado`, `discrepancia`, estados estructurales y ayudas del editor.

El enlace de Excel parcial usa `t("Abrir")` de forma explícita antes del código de idioma.

## Compatibilidad

- No cambia `.aprendizaje`.
- No cambia SQLite ni migraciones.
- No cambia Excel ni cola de persistencia.
- No cambia checkpoints.
- No cambia la lógica OCR/GPU.
- Compatible con las correcciones y geometrías de V14.14/V14.13.

Después de instalar, reinicia el dashboard. El `index.html` lleva una nueva versión de caché; `Ctrl+F5` sigue siendo una comprobación útil si el navegador mantiene recursos antiguos.
