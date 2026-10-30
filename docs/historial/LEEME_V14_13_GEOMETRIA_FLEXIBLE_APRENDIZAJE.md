# OCR V14.13 — Geometría flexible y aprendizaje de ediciones

Fecha: 2026-09-28  
Base: V14.12.1

## Objetivo

Extender el editor para que las regiones de texto no dependan solamente de cajas rectangulares alineadas a la imagen. Las herramientas de edición que realmente modifican una región textual pueden trabajar con un cuadrilátero de cuatro esquinas y conservar esa geometría al guardar y entrenar.

## Herramientas con geometría flexible

- Seleccionar texto.
- Mover recorte.
- Unir bloques.
- Ajustar / dividir bloque.
- Mover bloque.

`Ajustar a pantalla` y `Mover imagen` siguen siendo controles de visualización y no generan aprendizaje porque no cambian la geometría de un dato OCR.

## Cómo se usa

1. Selecciona o abre una región.
2. Pulsa **Editar 4 esquinas**.
3. Arrastra cualquiera de los cuatro tiradores hasta seguir la perspectiva o inclinación real del texto.
4. Si lo prefieres, usa el control angular para una rotación uniforme.
5. Confirma la operación correspondiente.

**Volver a rectángulo** restaura la caja rectangular si no necesitas una forma libre.

## Aprendizaje

El sistema registra únicamente la **geometría final confirmada**. Los movimientos intermedios del ratón no se convierten en ejemplos de entrenamiento.

Al confirmar una unión, ajuste, división o movimiento de bloque, V14.13 puede conservar:

- texto final confirmado;
- cuadrilátero final;
- orientación/ajuste final cuando existan;
- recorte visual rectificado para el dataset de entrenamiento.

El recorte visual se obtiene rectificando la perspectiva del cuadrilátero final antes de almacenarlo como muestra. Esto reduce la contaminación por texto vecino en etiquetas inclinadas.

## Compatibilidad

La migración de `ediciones_zona` es aditiva: se incorpora el campo `poligono` cuando no existe. Las ediciones antiguas que solo tienen `bbox` continúan funcionando como antes.

No borrar ni sustituir `.aprendizaje`, `.cache_ocr`, checkpoints ni archivos de resultados del usuario al aplicar el parche.

## Validación

Se añadieron pruebas para:

- intersección por polígono sin arrastrar texto vecino incluido solo en la envolvente rectangular;
- persistencia de polígonos en uniones;
- persistencia de polígonos en ajuste/división;
- generación de una muestra visual rectificada desde el cuadrilátero confirmado;
- controles frontend de cuatro esquinas y envío de la geometría al backend.

Las pruebas CUDA reales siguen requiriendo el equipo Windows con RTX A3000.
