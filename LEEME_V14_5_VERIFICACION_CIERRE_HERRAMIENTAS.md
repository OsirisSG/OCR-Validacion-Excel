# OCR V14.5 — Verificación segura y cierre consistente de herramientas

Fecha: 2026-09-24
Base: V14.3 + V14.4

## Qué incluye

V14.5 es acumulativa. Conserva todas las correcciones de V14.1, V14.2 y V14.3, e incorpora también V14.4:

- giro automático funcional en las herramientas de recorte;
- selección de orientación por congruencia de código antes del ajuste fino;
- prioridad a códigos numéricos compactos y alfanuméricos coherentes;
- penalización de fragmentos cortos de alta confianza cuando existe un código completo más congruente;
- el ajuste fino ya no puede convertir por sí solo un fragmento en ganador sobre la orientación base coherente.

Además agrega las correcciones de interfaz de V14.5 descritas abajo.

## Problema corregido: aviso de cambios sin guardar después de verificar

Había varios estados transitorios que podían quedar activos aunque el usuario ya hubiera terminado la revisión visible:

1. Una región dibujada, aunque no tuviera texto ni propuesta, se consideraba por sí sola un borrador.
2. Al cerrar la herramienta de texto omitido, el texto escrito podía permanecer oculto en el estado del navegador.
3. Al cerrar una corrección reconocida, una propuesta automática de orientación podía dejar `Texto correcto` distinto al último valor persistido.
4. Al marcar una imagen como verificada, las herramientas internas podían continuar montadas con selecciones o propuestas anteriores.

Eso podía producir después el mensaje:

`Hay cambios sin guardar en esta imagen. ¿Descartarlos y continuar?`

incluso cuando el usuario acababa de marcar la imagen como verificada.

## Nuevo comportamiento de “Imagen verificada”

- Una selección vacía ya no se considera un cambio sin guardar.
- Si existe un cambio real sin guardar, **Imagen verificada no lo descarta**.
- En ese caso se muestra un mensaje indicando que primero debe guardarse o cerrarse/descartarse la herramienta activa.
- Cuando la imagen se verifica correctamente, se limpian las selecciones y herramientas transitorias del editor.
- El editor de corrección se cierra y `Texto correcto` queda sincronizado con el valor persistido.
- Si están ocultándose las imágenes verificadas, el salto a la siguiente imagen ocurre después de esa limpieza, sin dejar un borrador fantasma.

## Botones de cierre

Se añadió **Cerrar herramienta** de forma visible a:

- `Completar o unir texto de una zona`;
- `Ajustar o dividir bloque`.

Se conserva:

- `Cerrar corrección` para una lectura OCR reconocida;
- `Cerrar texto omitido` para una región manual.

`Cerrar texto omitido` ahora es explícito: si hay texto no guardado pregunta si se desea descartarlo; al confirmar, limpia también ese texto oculto.

`Cerrar corrección` descarta únicamente el borrador no aplicado y vuelve al último texto persistido, evitando que el navegador lo siga detectando como cambio pendiente.

## Compatibilidad

No se modifica el formato de:

- `.aprendizaje`;
- `.cache_ocr`;
- checkpoints;
- Excel maestro.

No es necesario borrar aprendizaje ni avances existentes.

## Aplicación recomendada

1. Cerrar completamente el dashboard.
2. Aplicar el parche V14.5 sobre la carpeta actual del proyecto y aceptar reemplazos.
3. No borrar `.aprendizaje`, `.cache_ocr` ni el checkpoint.
4. Iniciar nuevamente el dashboard.
5. Para una corrección: aplicar supervisión primero y después marcar `Imagen verificada`.

Si existe un borrador real sin guardar, V14.5 impedirá verificar la imagen hasta resolverlo; ya no quedará una imagen marcada como verificada con un borrador oculto pendiente.
