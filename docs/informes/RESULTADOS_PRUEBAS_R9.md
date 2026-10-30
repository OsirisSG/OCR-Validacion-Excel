# Resultados de pruebas R9

Validaciones ejecutadas sobre una copia completa del proyecto diagnóstico del usuario con R9 superpuesta:

- 83 pruebas Python críticas: PASS.
  - R9 estándar de apertura
  - H5 tiempos inválidos/censura
  - contratos V15.10
  - matriz y semáforo
  - Excel y proyecto
  - rutas/imágenes
  - encabezados por idioma
- 17 pruebas Python adicionales de OCR/identidad/consolidación: PASS.
- 17 subpruebas Node de aceptación/zoom/matriz/i18n/consenso: PASS.
- Pruebas estáticas frontend R9/R7/R3: PASS.
- `node --check` app.js y visor_precision.js: PASS.
- `py_compile` de módulos modificados: PASS.

Pruebas R9 específicas:
- material claro cerca de deformación: detectado.
- material claro lejano: filtrado y no promovido como apertura fuerte.
- 5.8 ms alta evidencia -> verde estimado.
- 6.4 ms alta evidencia -> amarillo estimado.
- 7.2 ms alta evidencia -> rojo estimado.
- estimaciones fuertes contradictorias -> gris/abstención.
- referencia temporal inválida -> gris/abstención.
- score de evidencia no se presenta como probabilidad calibrada.

No se declara certificación de precisión física final sin un conjunto de AVI reales etiquetados de varias piezas/cámaras.
