# ¿Y si el dato es otro? Variantes en «motivo de prueba» y «PAB · número de parte»

La duda, en tus palabras: *«si con los valores que ya tengo hay una variante, ¿seguirán
funcionando?; mi ruido entra específicamente en motivo de prueba y PAB número de parte»*.

Respuesta corta: **sí, y ahora está probado**. Los dos campos **no** son catálogos cerrados: se
validan por **forma**. Lo único que había que arreglar eran dos rigideces —el sufijo de una sola letra
en el número de parte, y el motivo en mayúsculas sin paréntesis— y ya están arregladas en V16.0.46.

---

## 1. PAB · número de parte (`module_part_number`)

### Lo que pasaba

La gramática exigía **un** carácter final:

```
antes:  ^[0-9A-Z]{3}\.\d{3}\.\d{3}\.[0-9A-Z]$      →  2GJ.880.204.J  ✓   ·   2GJ.880.204.AB  ✗
```

Las variantes reales de PAB llevan **dos** caracteres (`2GJ.880.204.AB`, `4M0.880.204.AG`), así que
la variante buena se rechazaba y la celda quedaba vacía **sin motivo aparente**. Además, la etiqueta
lo imprime con espacios (`2GJ 880 204 J`) y el libro lo escribe con puntos: sin normalizar, la
lectura correcta tampoco pasaba.

### Lo que hace ahora

```
después: ^[0-9A-Z]{3}\.\d{3}\.\d{3}\.[0-9A-Z]{1,2}$
```

y antes de comparar, `normalizar_por_campo` reconstruye el formato:

| llega así | se escribe así |
|---|---|
| `2GJ 880 204 J` | `2GJ.880.204.J` |
| `2GJ880204J` | `2GJ.880.204.J` |
| `2gj 880 204 j` | `2GJ.880.204.J` |
| `2GJ 880 204 AB` | `2GJ.880.204.AB` |
| `2GJ.880.204.AB` | `2GJ.880.204.AB` |
| `4M0.880.204.AG` | `4M0.880.204.AG` |
| `1EA.880.204.AB` | `1EA.880.204.AB` |

Lo mismo vale para el **N/P del tablero**: `2GJ.857.003.G`, `2GJ 857 003 G`, `2GJ857003G`,
`2GJ.857.003.AB`, `5QF.857.003.AB` → todas pasan.

### Lo que se sigue rechazando (a propósito)

`2GJ.880.204` (sin sufijo), `2GJ.880.20` (bloque incompleto), `880204J` (sin prefijo),
`2GJ.880.204.JJJ` (tres caracteres). Si el OCR se come el sufijo, **no se escribe nada**: sale la
duda con el recorte. Eso es lo que evita que un `.8` leído a medias acabe en el libro.

---

## 2. Motivo de prueba (`test_reason`)

### De dónde sale

No se copia del libro: se lee de la **pizarra escrita a mano** en el vídeo (la misma que dice el
proyecto), y la barra del vídeo (`EDAG Mex BMG`) es la segunda fuente. El libro sólo aporta el
**vocabulario** con el que se escribe el tipo.

### Lo que pasaba

```
antes:  ^[A-Z][A-Z0-9 .&/,-]{1,40}$
```

Rechazaba `bmg` (minúsculas), `Certificación NOM` (acentos) y `BMG (NOM)` (paréntesis) — tres formas
en las que la pizarra puede venir escrita perfectamente.

### Lo que hace ahora

Se normaliza **sin cambiar lo que dice** y luego se compara:

| llega así | se escribe así |
|---|---|
| `bmg` | `BMG` |
| `Certificación NOM` | `CERTIFICACION NOM` |
| `BMG (NOM)` | `BMG (NOM)` |
| `BMG/A`, `BMG-A`, `BMG 2`, `PRUEBA BMG RT` | tal cual |
| `BMX` (otro motivo) | `BMX` |

Un motivo **nuevo** entra igual: no hay lista cerrada. Si el proyecto cambia de `BMG` a `BMX` o a
`BMX/A`, se escribe lo que dice la pizarra.

### Lo que se sigue rechazando

`BMG_1` (guion bajo: no es texto de pizarra), `-35°C "BMG"` (eso es la línea de temperatura, no el
motivo), una cadena de 45 caracteres (no es un motivo) y `A` (una sola letra).

---

## 3. Por qué esto no rompe lo que ya funcionaba

- **Las 149 celdas que hoy coinciden con el libro no cambian**: `2GJ.880.204.J` y `BMG` siguen
  pasando exactamente igual (las pruebas lo comprueban con esos dos valores reales).
- **Se amplía la tolerancia, no el permiso**: nada que antes se rechazara por *basura* pasa ahora.
- **La puerta sigue siendo una**: todo sigue pasando por `evaluar()`, y el origen de cada valor queda
  escrito en el informe.

## 4. Cómo se comprueba (para que no haya que creerme)

```bash
cd /home/user/vmatrix/trabajo
python3 -m pytest pruebas/test_p33_variantes.py -q      # 29 pruebas
python3 -m pytest pruebas/test_p12_protocolo.py -q      # la puerta, sin regresiones
```

Y con datos de verdad, la corrida del lote:

```bash
python3 medir_contra_referencia.py --libro /home/user/versionV16_0_45.xlsx \
       --referencia /home/user/uploads/Book-10-Examples.xlsx
# llenas 154/180 · coinciden 149 · discrepan 5 · vacías 26
```

## 5. Si aparece una variante nueva de verdad

1. Añádela a `pruebas/test_p33_variantes.py` (una línea en la tabla).
2. Si sale de un proyecto distinto (otro prefijo `4M0`, `5QF`, `1EA`), el campo ya la acepta; lo que
   hay que revisar es el **léxico del proyecto**, que se aprende solo de los valores repetidos.
3. Si la variante trae un formato nuevo (tres bloques de 4 dígitos, sufijo de tres caracteres),
   entonces sí hay que tocar la gramática —y esa decisión se documenta en el informe del lote.
