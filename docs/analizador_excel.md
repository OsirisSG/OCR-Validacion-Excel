# Analizador general de libros Excel (`analizar_excel.py`)

## Propósito

Inspeccionar un libro `.xlsx` o `.xlsm` completo sin modificarlo. El módulo
recorre todas las hojas —incluidas las ocultas— y genera un JSON que ayuda a
entender estructuras desconocidas antes de definir reglas de importación.

## Información producida

Por libro:

- nombre, tamaño, propiedades y nombres definidos;
- total de hojas, hojas ocultas y cantidad de fórmulas;
- parámetros utilizados durante el análisis.

Por hoja:

- estado visible/oculto y detección de hoja vacía;
- fila probable de encabezados y confianza de la heurística;
- filas y columnas con datos;
- inventario de columnas y advertencias.

Por columna:

- encabezado original y nombre normalizado en `snake_case`;
- letra e índice de Excel;
- tipo dominante y distribución de tipos;
- vacíos, fórmulas, muestras y resumen numérico;
- cardinalidad observada;
- posibles categorías cuando existen pocos valores repetidos;
- posibles significados y nombres canónicos basados en el encabezado y los
  valores observados.

Las propuestas semánticas son heurísticas. Deben confirmarse antes de convertirlas
en un esquema definitivo.

## Uso

```bash
python analizar_excel.py "/ruta/al/archivo.xlsx"
```

La salida predeterminada es `<archivo>_analisis_excel.json` junto al libro.
También puede elegirse otra ubicación:

```bash
python analizar_excel.py archivo.xlsx --salida analisis/resultado.json
```

Opciones principales:

```text
--max-filas-encabezado 25  Filas iniciales consideradas para hallar encabezados
--max-muestras 5           Valores de ejemplo por columna
--max-categorias 20        Cardinalidad máxima mostrada como categoría
--sin-muestras             Omite ejemplos potencialmente sensibles
```

## Seguridad y límites

- El libro se abre en modo de solo lectura.
- El JSON puede incluir muestras y categorías del archivo; no debe publicarse
  sin revisión. Por ello `*_analisis_excel.json` está excluido en `.gitignore`.
- Las fórmulas se cuentan pero no se ejecutan. Se usa el último valor guardado
  en el libro cuando está disponible.
- Los archivos binarios heredados `.xls` deben convertirse antes a `.xlsx`.
- La detección de encabezados es heurística y reporta su nivel de confianza.

## Uso como librería

```python
from analizar_excel import analizar_libro

resultado = analizar_libro("archivo.xlsx")
for hoja in resultado["hojas"]:
    print(hoja["nombre"], hoja["fila_encabezado"])
```
