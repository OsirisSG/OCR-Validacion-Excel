# Resultados de pruebas R10

Validaciones ejecutadas sobre una copia completa del proyecto del usuario.

## Python

- 11/11 pruebas específicas R10:
  - primer indicio mínimo + crecimiento posterior;
  - evidencia lejos de deformación;
  - FPS de reproducción falso;
  - FPS de alta velocidad válido;
  - color estimado con canal temporal separado;
  - un solo video defendible;
  - conflicto entre videos;
  - duración de llenado hasta meseta;
  - abstención sin meseta;
  - agregación de duración de llenado.
- 93/93 regresiones críticas acumuladas de H5/R7/R8/R9/R10.

## Frontend

- zoom suave/geometría: OK;
- sintaxis `app.js`: OK;
- sintaxis `visor_precision.js`: OK;
- fallback de imágenes: OK;
- caché R10: OK;
- zoom/pan/lupa/matriz/consenso: 11/11;
- aceptación provisional/trazabilidad: 6/6.

## Limitación pendiente

Las pruebas sintéticas y de regresión validan contratos y comportamiento de software. La calibración final de precisión física debe hacerse con AVI reales etiquetados cuadro por cuadro.
