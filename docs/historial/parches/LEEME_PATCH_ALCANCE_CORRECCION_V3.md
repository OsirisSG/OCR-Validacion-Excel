# PATCH V3 — Corrección consistente por bloque exacto

Fecha: 2026-09-16

## Qué problema corrige

En el dashboard existían dos rutas visuales distintas al abrir una detección:

1. Algunas detecciones pertenecían a un **recorte regional** (`marco_region`). En ese caso se mostraban las alternativas 0/90/180/270 del recorte grande completo.
2. Otras detecciones no tenían región asociada. En ese caso se mostraba la **bbox exacta del renglón**.

Esto explicaba por qué dos bloques aparentemente similares se comportaban distinto. Una lectura regional podía contener varias líneas mientras el selector inferior apuntaba a un único renglón. Si esa lectura se copiaba al formulario, el alcance visual y el alcance guardado no coincidían.

## Qué cambia en V3

- El formulario de corrección muestra **siempre la caja exacta que se va a guardar** con la leyenda `BLOQUE EXACTO QUE SE GUARDARÁ`.
- `Comparar lecturas de esta zona` relee exclusivamente esa bbox y permite comparar 0/90/180/270 para ese bloque.
- Si la detección pertenece a una región mayor, el panel regional se conserva como `Orientación del recorte regional (avanzado)`.
- Girar o elegir una alternativa del panel regional ya no reemplaza automáticamente el texto del renglón exacto. Su función es decidir la orientación del recorte regional.
- El frontend envía además `tipo_unidad` (`renglón`, `token` o `bloque completo`) al backend.
- El backend usa `tipo_unidad + bbox + texto original` para resolver la unidad correcta antes de guardar. Esto evita cruces cuando `tokens` y `lineas_texto` comparten caja o existen representaciones paralelas.
- Se conserva el arreglo V2 para reconfirmaciones de OCR originales basados en símbolos (`;`, `|`, `.`, etc.).
- Se actualizó la versión de caché del frontend a `20260916-correcciones-3`.

## Instalación recomendada

Si ya tienes instalada la V2, cierra completamente el dashboard y copia el contenido del ZIP PATCH V3 sobre la raíz del proyecto, permitiendo reemplazar archivos.

**No borres ni sustituyas tu carpeta `.aprendizaje`.** Haz primero una copia de seguridad de `.aprendizaje/aprendizaje.sqlite3` si existe.

Después:

1. Reinicia el servidor Python/dashboard.
2. En el navegador usa `Ctrl + F5`.
3. Abre una detección que antes fallaba.
4. Comprueba que arriba aparece `BLOQUE EXACTO QUE SE GUARDARÁ`.
5. Si deseas propuestas OCR, pulsa `Comparar lecturas de esta zona` y elige 0/90/180/270.
6. Cambia el texto, pulsa `Aplicar supervisión`, recarga la página y confirma que persiste.
7. Vuelve a cambiar ese mismo bloque una segunda vez y repite la comprobación.

## Archivos principales modificados

- `dashboard/frontend/app.js`
- `dashboard/frontend/index.html`
- `dashboard/backend/app.py`
- `aprendizaje.py` (incluido en el parche acumulativo para conservar la corrección V2)
- `utilidades/correcciones_ocr.py` (incluido en el parche acumulativo)

## Validación

- 120 pruebas Python relevantes: OK.
- Todas las pruebas JavaScript `.cjs` del dashboard: OK.
- `python -m py_compile`: OK.
- `node --check dashboard/frontend/app.js`: OK.

Las pruebas generales que dependen de archivos empresariales externos no incluidos en los ZIP originales siguen fuera de esta validación, igual que en la entrega anterior.
