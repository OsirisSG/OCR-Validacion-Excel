# Patch V2 — reconfirmación de bloques ya corregidos

Este parche corrige el caso donde una lectura OCR original formada sólo por signos (por ejemplo `;`, `|`, `.`, `:`) no podía sobrescribirse correctamente después de una primera confirmación.

## Si ya instalaste `OCR_CORREGIDO_CONSOLIDADO_2026-09-16`

Puedes sustituir únicamente estos archivos manteniendo sus rutas:

- `aprendizaje.py`
- `dashboard/backend/app.py`

Después reinicia completamente el servidor/dashboard. No borres ni sustituyas `.aprendizaje/aprendizaje.sqlite3`.

El archivo `pruebas/test_reconfirmacion_simbolos_unittest.py` es opcional en producción; se incluye para poder verificar la regresión.

## Qué prueba este parche

Se validaron correcciones sucesivas como `; → 4 → 41`, volver a una corrección anterior y la persistencia tras recargar el OCR desde SQLite. También se corrigió la identificación cuando la misma caja aparece duplicada en `tokens` y `lineas_texto`.
