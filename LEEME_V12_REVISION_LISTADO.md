# V12 — sincronización del estado de revisión en Listado

## Problema corregido
Al marcar una carpeta como **Completar revisión**, el detalle mostraba correctamente `completada`, pero la tabla de **Listado** podía seguir mostrando `Revisión parcial`.

La revisión sí estaba guardada. El problema era de presentación: durante una ejecución/reanudación, el Listado mezcla los resultados persistidos con `resultados_parciales` conservados en memoria. Esa instantánea parcial podía contener un estado de revisión antiguo y reemplazaba la fila que acababa de construirse con la revisión vigente de la base de aprendizaje.

## Corrección
V12 aplica dos protecciones:

1. **La revisión persistida siempre tiene prioridad** al combinar una fila parcial con la tabla del Listado.
2. Al cambiar manualmente el estado de una revisión, la copia parcial en memoria se actualiza inmediatamente. De esta manera no existe un intervalo en el que el detalle diga `Completada` y el Listado diga `Revisión parcial`.

No se modifica el historial de aprendizaje ni el contenido OCR.

## Prueba de regresión
Se añadieron pruebas que reproducen el caso:

- instantánea parcial = `parcial`;
- revisión persistida posterior = `completada`;
- el Listado debe devolver `completada`;
- al completar una revisión, la caché parcial también debe pasar a `completada`.

## Instalación
Si ya usas V11, cierra el servidor y copia el contenido del parche V12 sobre la raíz del proyecto, permitiendo reemplazar `dashboard/backend/app.py`. Después vuelve a iniciar el servidor.

No borres ni sustituyas `.aprendizaje/aprendizaje.sqlite3`.

Al ser un cambio de backend, no es necesario limpiar el caché OCR. Una recarga normal del Listado es suficiente después de reiniciar el servidor.
