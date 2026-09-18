# PATCH V5 — flujo simple de corrección y variantes OCR

Fecha: 2026-09-16

## Qué cambia

Esta versión revierte la parte confusa introducida en V4 sin perder la capacidad de sobrescribir correcciones.

- Se elimina el botón **“Comparar lecturas de esta zona”**.
- Al abrir un renglón/bloque, sus variantes OCR 0°/90°/180°/270° se preparan automáticamente y aparecen debajo del recorte cuando están disponibles.
- Los botones de giro y las tarjetas de variante sólo cambian la vista y **copian la lectura de ese ángulo a “Texto correcto” como borrador**.
- Nada se confirma ni se incorpora al aprendizaje hasta pulsar **“Aplicar supervisión”**.
- Se elimina el mensaje/barrera **“Corrección textual bloqueada temporalmente”**. Una orientación regional dudosa ya no impide escribir o reconfirmar un texto.
- Se elimina del formulario de corrección el panel regional duplicado que podía hacer parecer que se estaba corrigiendo una caja distinta. La corrección se centra en una sola caja exacta.
- Se conserva la identidad de la unidad (`bbox` + tipo de unidad) y la sobrescritura cronológica de correcciones ya confirmadas.

## Flujo esperado

1. Selecciona un renglón o bloque OCR.
2. Se muestra el recorte exacto que recibirá la supervisión.
3. Debajo aparecen las variantes OCR cuando terminan de calcularse.
4. Puedes pulsar ←90°, →90°, Restablecer giro o una tarjeta 0°/90°/180°/270°.
5. Si esa orientación tiene texto OCR, se copia a **Texto correcto** como propuesta editable.
6. Puedes modificar la propuesta manualmente.
7. Sólo al pulsar **Aplicar supervisión** se guarda la decisión.
8. Puedes volver a ese mismo bloque más tarde y sobrescribir la corrección; la última confirmación queda vigente.

## Instalación sobre V4

1. Cierra por completo el dashboard/servidor Python.
2. Haz copia de seguridad de `.aprendizaje`, en especial `.aprendizaje/aprendizaje.sqlite3`.
3. Descomprime el PATCH V5 en la raíz del proyecto y acepta reemplazar archivos.
4. **No borres ni reemplaces tu carpeta `.aprendizaje`.**
5. Reinicia el servidor.
6. En el navegador usa `Ctrl+F5` para forzar la carga de `app.js` V5.

## Archivos funcionales modificados

- `dashboard/frontend/app.js`
- `dashboard/frontend/index.html`
- `dashboard/backend/app.py`

El backend conserva las correcciones de reconfirmación de V2/V3, pero deja de rechazar una supervisión únicamente por tener una orientación regional marcada como dudosa.
