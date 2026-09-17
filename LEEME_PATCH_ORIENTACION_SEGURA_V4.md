# PATCH V4 — orientación regional segura antes de corregir texto

Fecha: 2026-09-16

## Qué corrige

La V3 cometía un error de orden lógico en los renglones que nacen de un recorte regional con **orientación dudosa**.

Un renglón podía mostrar, por ejemplo, texto OCR `3`, aunque su caja visual cubriera una línea como `VW 316/S`. Esto ocurre porque esa caja/texto fueron generados desde la orientación regional elegida automáticamente (por ejemplo 270°). Mientras esa orientación no esté confirmada, tanto el texto como la geometría del renglón son provisionales.

La V3 presentaba esa caja provisional como **“BLOQUE EXACTO QUE SE GUARDARÁ”** y permitía aplicar supervisión. Eso podía asociar una corrección humana correcta a la caja equivocada.

## Regla nueva

Cuando una unidad tiene `marco_region` y el recorte asociado cumple:

- `orientacion_dudosa = true`
- `orientacion_confirmada = false`

el flujo ahora es:

1. Elegir visualmente la orientación correcta del recorte regional (0/90/180/270).
2. Pulsar **“Usar X° y reprocesar esta imagen”**.
3. El sistema guarda la preferencia regional y reprocesa la imagen.
4. El OCR reconstruye renglones y cajas con esa orientación ya fijada.
5. Sólo entonces se habilita **Texto correcto** y **Aplicar supervisión**.

En ese estado provisional se oculta el panel **“BLOQUE EXACTO QUE SE GUARDARÁ”**, porque todavía no podemos afirmar que esa caja sea la definitiva.

## Protección adicional en backend

No es sólo un cambio visual. El backend también rechaza una corrección textual sobre una unidad cuya orientación regional siga dudosa y no confirmada. Así, una pestaña vieja del navegador o un cliente desactualizado tampoco puede guardar una corrección sobre geometría provisional.

Las acciones `ilegible` y `no_es_campo` siguen permitidas porque no afirman un contenido textual correcto.

## Qué NO cambia

- Las unidades sin `marco_region` siguen corrigiéndose directamente.
- Las regiones cuya orientación ya fue confirmada vuelven a mostrar el bloque exacto y permiten sobrescrituras normales.
- Se conservan 0/90/180/270, porcentajes, navegación, ocultar verificadas, historial, correcciones repetidas y sobrescritura de una confirmación anterior.
- La V2 de reconfirmación de símbolos (`;`, `.`, `|`, etc.) sigue incluida.
- La identidad `renglón` / `token` / `bloque completo` de V3 sigue incluida.

## Caso de las capturas

En `IMG_5330`, el selector indicaba `renglón: 3` y el recorte regional estaba marcado como orientación dudosa. El ganador automático 270° producía lecturas `3` / `2`, mientras que la vista a 0° mostraba el contenido horizontal. Ese renglón no debía corregirse todavía: primero había que fijar la orientación regional y reprocesar.

En `IMG_5329`, el renglón `232541` no presenta ese conflicto regional; por eso sigue entrando directamente al editor de texto.

## Instalación sobre V3

1. Cierra completamente el dashboard y el proceso Python.
2. Haz copia de seguridad de `.aprendizaje/aprendizaje.sqlite3`.
3. Descomprime el PATCH V4 en la raíz del proyecto y permite reemplazar archivos.
4. **No borres ni reemplaces tu carpeta `.aprendizaje`.**
5. Reinicia el servidor.
6. Haz `Ctrl + F5` en el navegador.

Archivos operativos modificados:

- `dashboard/backend/app.py`
- `dashboard/frontend/app.js`
- `dashboard/frontend/index.html`

El parche también incluye las pruebas nuevas/actualizadas.

## Prueba manual recomendada

Abre una imagen con “Orientación dudosa del recorte regional”. Debes ver primero el flujo de orientación y la corrección textual bloqueada. Elige el giro que visualmente deja el texto derecho y pulsa **“Usar X° y reprocesar esta imagen”**. Después del reproceso, vuelve al caso: el renglón debe aparecer reconstruido y entonces sí podrás corregirlo y volver a sobrescribirlo cuantas veces sea necesario.

## Validación realizada

- Sintaxis de `app.js`: correcta.
- Compilación de `dashboard/backend/app.py`: correcta.
- 5 pruebas JavaScript del dashboard ejecutadas correctamente.
- Suite Python sin las pruebas que dependen de archivos empresariales externos ausentes: **122 passed**.
- Se añadió una prueba específica que comprueba que una orientación regional dudosa bloquea la supervisión textual hasta reprocesar.
