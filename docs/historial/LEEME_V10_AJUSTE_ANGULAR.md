# V10 · OCR con ajuste angular para etiquetas sesgadas y diagonales

Esta versión parte de V9 y **no cambia el flujo aprobado del editor**: siguen visibles las cuatro orientaciones base 0°, 90°, 180° y 270°; seleccionar una tarjeta o girar copia la lectura a **Texto correcto** como borrador y nada se guarda hasta pulsar **Aplicar supervisión**.

## Qué cambia

El OCR regional ahora puede corregir inclinaciones que no son múltiplos de 90°. Cada orientación base puede incorporar un **ajuste fino** de hasta ±45° sobre la región seleccionada. Por ejemplo, una tarjeta puede mostrar `0° → 7.2°`, `90° → 96.4°` o `0° → 32.0°`.

La búsqueda no recorre cada grado. Primero ejecuta las orientaciones cardinales. Después estima geométricamente la inclinación del texto en la región y sólo prueba el ángulo estimado. Si la lectura cardinal ya es sólida, el pipeline añade como máximo una pasada fina; si las lecturas cardinales son débiles, permite refinar las cuatro bases para rescatar una etiqueta muy diagonal. El panel del editor sí puede optimizar las cuatro tarjetas, pero su resultado queda cacheado por imagen/caja/orientación.

## Seguridad de la lectura

El ajuste fino sólo reemplaza una lectura cardinal si la nueva lectura no empeora su puntuación. Las cajas detectadas se reproyectan al marco original usando la matriz inversa de la rotación, por lo que el texto diagonal no debe desplazar la región guardada.

El ángulo automático es una ayuda de reconocimiento y visualización. No confirma texto ni entrena el OCR por sí solo.

## Configuración

En `config.yaml`:

```yaml
fase1:
  preprocesamiento:
    ajuste_fino_regiones:
      activar: true
      angulo_minimo: 1.25
      angulo_maximo: 45.0
      todas_variantes_editor: true
```

`angulo_maximo` puede reducirse si se quiere priorizar rendimiento sobre cobertura. No se añadieron dependencias ni servicios en línea.

## Archivos modificados

- `ocr_engine.py`
- `config.yaml`
- `dashboard/backend/app.py`
- `dashboard/frontend/app.js`
- `dashboard/frontend/i18n.js`
- `dashboard/frontend/estilos.css`
- `dashboard/frontend/index.html`
- pruebas de regresión de orientación

## Validación

- Prueba sintética de texto a 30°: el estimador regional recupera aproximadamente el ángulo esperado.
- Se verifica que una lectura fina peor nunca sustituya una cardinal mejor.
- Se conservan las cuatro tarjetas 0°/90°/180°/270°.
- Se conserva el bugfix V9 de respuestas tardías y correcciones guardadas.
- Suite Python disponible: 168 pruebas pasan. Las 8 restantes requieren `validacion_resultados.json` y el banco externo de pruebas que no forman parte del ZIP.
- Todas las pruebas JavaScript `.cjs` pasan.

## Instalación sobre V9

1. Cierra el dashboard y el proceso Python.
2. Respalda `.aprendizaje/`, resultados, configuración propia y cualquier archivo de datos real.
3. Descomprime el PATCH V10 sobre la raíz de V9 y permite reemplazar código.
4. **No reemplaces tu `.aprendizaje/aprendizaje.sqlite3`.**
5. Inicia de nuevo el dashboard. Los recursos web llevan una nueva versión de caché.

Si la instalación local contiene cambios posteriores a V9, no conviene aplicar el parche por encima sin comparar; integra estos cambios sobre esa versión más nueva.
