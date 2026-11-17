# V-Matrix V15.10.1 R8

Corrección acumulada basada en R7 y en el ZIP diagnóstico de la instalación real.

## Mejora R8

- B3/B4 del resumen ya no quedan fijos en alemán: se localizan ES/EN/DE.
- `xNN`, programa VW, PAB, BMG y COP BFA se recuperan de los textos OCR cuando están observados.
- El nombre del proyecto sigue viniendo sólo de la selección explícita del usuario.
- Los grupos de `Versuchsmatrix`/`Rangos` se localizan según el idioma seleccionado.
- Se conserva la limpieza de matrices, semáforo de apertura, rutas de imágenes y correcciones R7.

## Instalación

1. Cerrar completamente V-Matrix, servidor y navegador.
2. Extraer TODO este ZIP a una carpeta temporal.
3. Ejecutar `INSTALAR_R8.bat`.
4. Debe terminar con `PARCHE_R8_COPIADO_Y_VERIFICADO_OK`.
5. Reiniciar V-Matrix y abrir `http://127.0.0.1:8000/api/estado`.
6. Confirmar `patch_build = 15.10.1-r8`.
7. Hacer Ctrl+F5 una vez.

El instalador crea respaldo y no toca `.aprendizaje`, `.agents`, `AGENTS.md`, AVI, imágenes ni Excel del usuario.
