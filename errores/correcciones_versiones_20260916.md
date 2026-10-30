# Nota técnica: sobrescritura, orientación y conservación de interfaz

## Objetivo

Unificar las tres versiones recibidas sin perder funciones del dashboard y corregir el caso en el que una confirmación humana anterior seguía reapareciendo después de rectificarla.

## Arquitectura de la corrección

### 1. OCR bruto inmutable

El resultado OCR guardado continúa siendo la fuente bruta. Las confirmaciones humanas se proyectan sobre una copia para mostrar, validar y exportar. Esto permite auditar qué leyó originalmente el OCR y qué terminó confirmando una persona.

### 2. Historial humano ordenado

`utilidades/correcciones_ocr.aplicar_correcciones()` resuelve las correcciones por imagen, caja y texto de origen. Mantiene un conjunto de textos conocidos para soportar dos formas de historial:

- forma actual: `ABC → A.1`, luego `ABC → A.2`;
- forma heredada: `ABC → A.1`, luego `A.1 → A.2`.

El registro cronológicamente posterior gana. Para una confirmación repetida ya existente, `aprendizaje.py` actualiza `creado_en`, lo que permite reconfirmar una versión anterior sin insertar duplicados innecesarios.

### 3. Texto completo y cajas

Las correcciones localizadas se aplican a `tokens` y `lineas_texto`. Si hay una corrección espacial posterior, `texto_completo` se reconstruye desde las líneas visibles. Una corrección explícita del bloque completo puede prevalecer cuando es posterior; si después se corrige una línea, la transcripción global anterior se considera obsoleta.

### 4. Zonas editadas

Las uniones/divisiones de `utilidades/edicion_zonas.py` se aplican antes de la proyección final de correcciones. Esto hace posible corregir nuevamente un bloque creado por una edición de zona. El handler del dashboard detecta `edicion_zona` y vuelve a guardar el bloque cuando cambia su texto.

### 5. Confirmación visual vigente

Al registrar o reconfirmar una muestra visual en la misma imagen y `bbox`, las muestras anteriores de esa zona se marcan como no vigentes para entrenamiento. La muestra seleccionada vuelve a quedar confirmada, con su fecha actualizada. Esto evita entrenar simultáneamente con dos respuestas incompatibles para la misma región.

## Flujo del dashboard

1. El detalle del caso carga las correcciones persistidas y proyecta el texto vigente.
2. Al pulsar una lectura, `seleccionarUnidad()` selecciona imagen/bloque, abre el formulario y ejecuta `scrollIntoView()` sobre `formulario-correccion-activa`.
3. Si la lectura está asociada a un recorte OCR regional, se muestran las alternativas guardadas de orientación. Cada tarjeta contiene grados, confianza y texto.
4. Si el bloque no tiene esas alternativas, `HerramientasRegion` permite solicitar **Comparar lecturas de esta zona**, que relee el recorte en 0/90/180/270.
5. Elegir giro o tarjeta copia la propuesta a la casilla, pero no confirma nada automáticamente.
6. Al guardar, el backend busca el bloque sobre la versión ya corregida, conserva su `texto_original` y registra la nueva versión.
7. El frontend vuelve a pedir el caso completo. Si el texto recargado no coincide con el borrador enviado, presenta error y no declara el cambio como guardado.

## Navegación y protección de trabajo

La vista mantiene Anterior/Siguiente, filtro de imágenes verificadas y posición actual. `permitirCambioImagen()` consulta también a subeditores mediante el evento `ocr-consultar-borradores`; si hay texto, selección de región o una operación en curso, el cambio se bloquea o solicita confirmación. Al verificar una imagen con el filtro activo, se avanza a la siguiente pendiente disponible.

## Orientaciones

El reconocimiento regional evalúa 0°, 90°, 180° y 270° por diseño. El resultado guarda `candidatos_orientacion` con `grados`, `confianza` y `texto`, además de la orientación seleccionada y si se considera dudosa. Una orientación regional confirmada puede forzar una sola dirección en el reprocesamiento posterior.

Una prueba heredada esperaba una única llamada al reconocedor; esa expectativa era incompatible con esta función y se actualizó para exigir cuatro lecturas y las cuatro tarjetas de candidato.

## Exportación

`generar_excel.py` utiliza `GestorAprendizaje.filtrar_no_texto()`. Esa ruta ahora termina aplicando el mismo resolvedor de correcciones que usa el dashboard. Por ello la vista y una regeneración posterior del Excel comparten la misma versión humana vigente. Un archivo XLSX que ya estaba creado no cambia mágicamente: debe ejecutarse la cola/regeneración de Excel.

## Caché del navegador

`dashboard/frontend/index.html` cambia los parámetros de versión de `app.js` y `estilos.css`. Aun así, después de sustituir archivos se recomienda una recarga sin caché (`Ctrl+F5`) para no conservar JavaScript anterior en una pestaña abierta.

## Datos que no deben perderse al reemplazar código

- `.aprendizaje/aprendizaje.sqlite3` y su dataset visual, si existen.
- `validacion_resultados.json` si deseas conservar el último procesamiento mostrado en el dashboard.
- `.cache_ocr/` si quieres reanudar/reutilizar resultados sin reprocesar imágenes.
- `.plantillas/` y `base_conocimiento.json` si tu instalación ya los utiliza.
- Excel generados que quieras conservar.

El ZIP consolidado es código; no debe utilizarse como motivo para borrar esos artefactos locales.

## Limitaciones de la validación realizada

No se ejecutó EasyOCR real con la GPU del equipo del usuario ni una inspección visual en un navegador Windows real. Sí se validó sintaxis, lógica de persistencia con SQLite temporal, handlers aislados, edición de zonas y los flujos JavaScript del dashboard. Las pruebas generales que dependen de `validacion_resultados.json`/fixtures empresariales no pueden ser reproducidas a partir de los ZIP porque esos datos no fueron incluidos.
