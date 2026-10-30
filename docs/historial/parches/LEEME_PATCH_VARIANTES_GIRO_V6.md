# V6 — Restauración de variantes OCR al girar

Esta versión corrige la regresión de V5 en la que algunos bloques dejaban de mostrar las propuestas OCR de **0°, 90°, 180° y 270°**.

## Flujo restaurado

Al seleccionar un renglón o bloque:

1. Se muestra el **bloque exacto que se guardará**.
2. Las cuatro variantes OCR se calculan automáticamente y quedan visibles debajo del recorte, con **ángulo, confianza y texto**.
3. Los botones **↶ 90°**, **↷ 90°** y **Restablecer giro** giran la vista.
4. Al girar, la lectura correspondiente se copia automáticamente a **Texto correcto** como **borrador**.
5. También se puede pulsar directamente una de las cuatro tarjetas para elegir su lectura.
6. Nada se guarda hasta pulsar **Aplicar supervisión**.

Se mantiene eliminado el botón **“Comparar lecturas de esta zona”**. También se mantiene eliminado el bloqueo de **“Corrección textual bloqueada temporalmente”**.

## Qué se corrigió técnicamente

V5 reutilizaba `/api/aprendizaje/zonas` para preparar las variantes. Esa ruta contiene reglas de edición (anotaciones, expansión de zonas, estado de revisión, etc.) que pueden rechazar algunas cajas aunque solo se quiera comparar OCR. Por eso las tarjetas aparecían en unos bloques y en otros no.

V6 incorpora una ruta de solo lectura:

`/api/aprendizaje/lecturas-orientacion`

Esta ruta:

- usa exactamente la `bbox` seleccionada;
- no expande la caja;
- no crea ni modifica zonas;
- no guarda aprendizaje;
- no exige confirmar una orientación regional;
- devuelve siempre las cuatro posiciones 0/90/180/270 (una posición puede decir `Sin lectura` si OCR no encontró texto).

El panel del bloque exacto también vuelve a ocupar todo el ancho para que las cuatro tarjetas se vean desplegadas de forma similar al panel clásico. El ángulo actual se muestra entre los botones de giro, como en el diseño anterior que resultaba más claro.

## Instalación sobre V5

1. Cierra completamente el dashboard/servidor Python.
2. Haz respaldo de `.aprendizaje`, especialmente `.aprendizaje/aprendizaje.sqlite3`.
3. Descomprime el PATCH V6 sobre la raíz de tu proyecto V5 y acepta reemplazar archivos.
4. **No borres ni reemplaces `.aprendizaje`.**
5. Inicia nuevamente el servidor.
6. En el navegador usa `Ctrl+F5`.

El `index.html` usa una nueva versión de caché (`correcciones-6`) tanto para JavaScript como para CSS, para evitar que el navegador conserve la interfaz de V4/V5. Si después de instalar todavía aparece el botón “Comparar lecturas de esta zona”, el navegador está mostrando archivos antiguos: reinicia el servidor y usa `Ctrl+F5`.

## Prueba rápida

Selecciona un bloque con OCR. Debes ver cuatro tarjetas debajo del recorte. Pulsa ↷90°: la imagen gira, la tarjeta 90° queda seleccionada y su lectura pasa a `Texto correcto`. Cambia manualmente ese texto si hace falta y pulsa `Aplicar supervisión` solo cuando quieras guardar.


## Validación

- 7 pruebas JavaScript del dashboard: todas correctas.
- 42 pruebas Python dirigidas a orientación, persistencia, sobrescritura, zonas y reconfirmación: correctas.
- Suite Python completa disponible: 142 pruebas correctas; 8 pruebas dependen de `validacion_resultados.json` y del banco empresarial externo, archivos que no vienen en los ZIP de trabajo.
- `node --check` y `python -m py_compile`: correctos.
