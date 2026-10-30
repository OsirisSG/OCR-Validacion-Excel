# Resultados de pruebas V15.10.1 R8

Fecha: 2026-10-14

## Python

Suite crítica acumulada R7/R8 (Excel, matriz, identidad, apertura, OCR, guía de etiquetas, aceptación):

- 134 passed
- 0 failed

Prueba específica R8 incluida en la suite:

- extracción de `VW316/5`, `x50`, PAB, BMG y COP BFA desde texto OCR;
- encabezado ES;
- encabezado EN;
- encabezado DE;
- grupos de tabla y fila de campos en el idioma seleccionado.

## JavaScript

- `node --check dashboard/frontend/app.js`: OK
- `node --check dashboard/frontend/visor_precision.js`: OK
- regresión frontend R8/semáforo: OK
- fallback de imágenes/cache R3-R8: OK
- aceptación provisional vs corrección humana: OK
- zoom/matriz/idiomas/consenso: 11/11 subpruebas OK

## Excel de validación

Se generaron salidas sintéticas ES/EN/DE con términos técnicos OCR observados.
La inspección de las tres confirmó:

- proyecto `Ejemplo_VW` separado de OCR;
- B3/B4 localizados según ES/EN/DE;
- grupos de `Versuchsmatrix` localizados;
- fila de campos localizados;
- sin errores `#REF!`, `#DIV/0!`, `#VALUE!`, `#NAME?` o `#N/A` detectados.

## Instalación simulada

El manifiesto R8 fue aplicado sobre una copia del árbol R7:

- hashes destino: OK;
- imports resueltos desde el árbol destino: OK;
- `utilidades.encabezados_institucionales`: OK;
- `PATCH_BUILD = 15.10.1-r8`: OK.

Estas pruebas no sustituyen la corrida final con fotografías/AVI reales del usuario.
