# Reconfirmación de bloques previamente corregidos — V2

Fecha: 2026-09-16

## Síntoma

Algunas regiones podían corregirse una segunda vez y otras no. El patrón problemático aparecía especialmente cuando el OCR bruto había leído únicamente puntuación o símbolos, aunque el recorte mostrara claramente un número o texto. Por ejemplo, una caja podía tener OCR original `;` y ser corregida posteriormente a `4` o `41`.

## Causa

`GestorAprendizaje.registrar_correccion()` validaba la corrección usando `normalizar_codigo()` antes de guardar la memoria textual. Esa normalización elimina todo lo que no pertenezca al alfabeto operativo de códigos. Por ello `normalizar_codigo(';')` produce una cadena vacía y la operación se rechazaba.

Además, el endpoint podía recibir la misma región dos veces, una en `tokens` y otra en `lineas_texto`. En una reconfirmación esto podía convertir una caja espacialmente inequívoca en una coincidencia aparentemente ambigua.

## Solución

1. La validación textual ahora exige texto visible no vacío, no texto alfanumérico normalizado.
2. Toda corrección humana se guarda en `correcciones_texto`, incluso si el OCR original es sólo puntuación.
3. Sólo se alimenta la tabla del modelo ligero `correcciones` cuando tanto origen como destino poseen contenido válido después de la normalización alfanumérica.
4. `_buscar_unidad_ocr()` prioriza coincidencia exacta y `bbox` exacta antes de la normalización.
5. Duplicados equivalentes entre `tokens` y `lineas_texto` no invalidan una caja exacta.

## Pruebas añadidas

`pruebas/test_reconfirmacion_simbolos_unittest.py` verifica:

- corrección de `;` a `4`;
- sobrescritura posterior de `4` por `41` conservando como origen la lectura OCR real;
- volver a una corrección anterior;
- reconfirmación pasando por `/api/aprendizaje/correcciones`;
- persistencia tras volver a publicar el OCR desde la base SQLite.

## Datos existentes

No se requiere migración de la base SQLite. La corrección es compatible con el historial existente. Conservar siempre `.aprendizaje/aprendizaje.sqlite3` al actualizar código.
