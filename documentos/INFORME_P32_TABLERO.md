# P32 · Número de parte moldeado del tablero (V16.0.45)

**Entrega:** `versionV16_0_45.xlsx` · `vmatrix/VMATRIX_PARCHE_V16_0_45.zip` (9 565 676 B, sha256
`8630de9d…d5d83d14`) · `documentos/dudas_p32.html` (31 dudas) · paquete ensayado **10/10**.

## Lo que faltaba y por qué

La columna `Tablero · N/P` salía vacía. La conclusión anterior —«el número no está en las fotos»—
era **falsa**: estaba mal buscado. El número **no va impreso en ninguna etiqueta**; va grabado en el
plástico negro del tablero, con letra de puntos, en relieve y sin contraste, junto al número del
proveedor (`4148399X`). El OCR de la foto entera no lo ve, y por eso el barrido anterior sólo
encontraba el `2GJ.880.204.J` de la etiqueta del **módulo**.

Ampliando a mano la zona del 222504 se lee, sin ambigüedad:

```
4148399X
2GJ.857.003.G
```

## Cómo se lee ahora

1. **Detección sin OCR** (`localizar_grabado_punteado`): `blackhat` sobre el gris, se cuentan puntos
   pequeños alineados en fila y se devuelven las cajas con más puntos. Barato: recorre las 130 fotos
   de una carpeta en segundos.
2. **Realce antes del OCR** (`relieves_de_grabado`):
   - `plano`: se divide la imagen por su propio fondo desenfocado; quita el degradado de la luz y el
     cepillado del plástico. Es la que hace legible el 222509.
   - `bh`: `blackhat` con núcleo 7, que saca la sombra del relieve hundido.
3. **Ventana por caja**, 900 px de ancho y **más alta por abajo que por arriba**: la caja del
   detector suele ser el renglón de arriba (`4148399X`) y el número va debajo. Con la ventana
   centrada se cortaba justo el número de parte.
4. **Normalización** (`interpretar_parte_tablero`), apoyada en el bloque `857` que no cambia:
   `2G1`, `26J`, `2EJ`, `361` se leen `2GJ`; la `G` final se lee `6`, `C`, `Q` o `(`; y si el bloque
   final no sale en la foto, se completa con el del catálogo y queda anotado en el origen.
5. **Una foto por subproceso**: el OCR deja ~200 MB por llamada y la máquina tiene 2 GB; en un solo
   proceso el barrido muere por memoria (pasó).

## Resultado

`versionV16_0_45.xlsx` frente al libro de referencia: **154 de 180 llenas · 149 coinciden · 5
discrepan · 26 vacías** (v44: 149 · 144 · 5).

| campo | v44 | v45 | coinciden |
|---|---|---|---|
| `dashboard_part_number` | 0/9 | **5/9** | 5 de 5 |
| `dashboard_engineering_level` | 7/9 | 7/9 | 7 |
| `dashboard_date` | 5/9 | 5/9 | 5 |
| `dashboard_serial_number` | 1/9 | 1/9 | 1 |

Lo leído, foto a foto:

| caso | foto | OCR | escrito |
|---|---|---|---|
| 222504 | `VOR/IMG_1598.JPG` | `25J.857.003G2` | `2GJ.857.003.G` |
| 222509 | `VOR/IMG_1779.JPG` | `26J.857.003` | `2GJ.857.003.G` |
| 222530 | `VOR/IMG_2654.JPG` | `2GJ.857.003` | `2GJ.857.003.G` |
| 232561 | `VOR/IMG_5195.JPG` | `2Gt.857.003` | `2GJ.857.003.G` |
| 232566 | `NACH/IMG_5442.JPG` | `2GJ.857.003` | `2GJ.857.003.G` |

En el 222504 el bloque final **se lee** en la foto (`.G`); en las otras cuatro el OCR se corta en
`…003` y el bloque final se completa con el del catálogo — queda registrado con el origen
`grabado_moldeado_catalogo` en `evidencia_tablero.json`.

## Las cinco carpetas sin lectura

`222521`, `232550`, `232564`, `252581`, `252590`. Se barrieron entre 8 y 22 fotos por caso (las más
parecidas por ORB a la toma buena del 222504) y no apareció el renglón legible: en esas carpetas la
toma del grabado no está, o está fuera de foco. La celda queda vacía y en el panel de dudas va la
opción **`2GJ.857.003.G`** a un clic, sacada de las carpetas donde sí se leyó.

Para cerrarlas del todo hace falta **una foto más por carpeta**: la toma de la cara inferior junto al
módulo, como el `VOR/IMG_1598.JPG` del 222504.

## Verificación

- `pytest pruebas/test_p31_parte.py` → **7 pruebas** (normalización de `2G1`/`26J`/`2EJ`, la `G` como
  `C`/`(`/`6`, el bloque final en dígito, que el `2GJ.880.204.J` del módulo **no** se acepte, y la
  detección de renglones punteados sobre la foto real del 222504).
- Barrido completo del 222504 (118 fotos): **una** lectura, y es la foto buena. Precisión perfecta,
  a costa de leer muchas fotos; por eso se añadió el orden por parecido.

## Siguiente

1. Confirmar en el panel las series y fechas pendientes (un clic cada una).
2. Fotos del grabado en las cinco carpetas que faltan para cerrar `N/P` a 9/9.
