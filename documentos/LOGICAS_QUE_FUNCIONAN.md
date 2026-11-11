# Lógicas que ya funcionan (para usar y para no volver a inventarlas)

Cada bloque dice **qué resuelve**, **dónde vive** y **cómo se comprueba**. Las copias de los módulos
están en `documentos/logicas/` para consulta rápida; la fuente viva es
`/home/user/vmatrix/trabajo/`.

---

## 1. Puerta única de escritura: gramática por campo

**Qué resuelve.** Que un OCR «casi bueno» no llegue nunca al libro. Todo valor pasa por
`evaluar(campo, valor)` y devuelve `valido | reparado | dudoso | invalido` con motivo.

**Dónde.** `utilidades/protocolo_campos.py` → `GRAMATICAS`, `evaluar`, `normalizar_por_campo`.

**Cómo funciona, en tres capas.**
1. **Forma**: patrón por campo (`ABC.123.456.J`, `671 ZRZ0539991D`, `03S`, `AAAA-MM-DD`…).
2. **Matriz de confusión**: si falla la forma, prueba a cambiar **un** carácter de los que el motor
   confunde de verdad (`O↔0, I↔1, S↔5, Z↔2, B↔8, G↔6, J↔4`). Si el resultado es un valor que ya
   existe en el proyecto, se acepta y **se marca como reparado**.
3. **Léxico del proyecto**: un valor que ya se vio manda sobre una lectura nueva parecida.

**Prueba.** `pruebas/test_p12_protocolo.py` + `pruebas/test_p33_variantes.py`.

---

## 2. Consenso entre fotos (no fiarse de una sola)

**Qué resuelve.** La cola de un código se lee distinta en cada foto (`…R6E`, `…R6E1`, `…R6E7`).

**Dónde.** `evidencia_tablero.py` → `consensuar` y `_consenso_alineado`.

**Cómo funciona.** Voto **posición a posición**, alineando por el prefijo y contando también a las
lecturas que se quedan cortas: la longitud la decide la posición final con apoyo. Corta cuando una
posición no llega al 50 % de los votos. Si la cola está disputada, o la serie acaba en dígito (posible
carácter de control que el libro no usa), el valor **no se escribe** y va a dudas.

**Prueba.** `pruebas/test_p30_tablero.py` (dos pruebas nuevas sobre la cola).

---

## 3. Etiqueta del tablero: serie, fecha y nivel

**Qué resuelve.** Los tres campos del tablero que no son el número de parte.

**Dónde.** `utilidades/tablero_campos.py` → `zonas_de_codigo`, `franjas_de_etiqueta`,
`leer_serie_de_etiqueta`, `leer_fecha_del_tablero`, `leer_estampa_del_nivel`.

**Claves que costaron.**
- La **serie** va pegada al DataMatrix y girada: se lee **por franjas** (encima y debajo del código),
  ampliadas y **a dos escalas** (900 y 1500 px). Leer la foto entera fallaba siempre el último
  carácter.
- La **fecha** es la de la etiqueta con **pegatina de color** (azul), en formato `17/MAY/2025`; la del
  módulo (DATA MATRIX) se descarta.
- El **nivel** es la **estampa rosa**; la amarilla es la del módulo. De ahí venían los `56K` falsos.

**Prueba.** `pruebas/test_p30_tablero.py` (16 pruebas).

---

## 4. Número de parte **moldeado** del tablero (el que no se ve)

**Qué resuelve.** Leer `2GJ.857.003.G` de un plástico negro, en relieve, sin contraste y sin etiqueta.

**Dónde.** `utilidades/grabado_punteado.py` + `leer_parte_foto.py` + `leer_parte_por_parecido.py`.

**Cómo funciona, en cuatro pasos.**
1. **Detección sin OCR**: `blackhat` sobre el gris y conteo de puntos pequeños alineados → cajas de
   renglón grabado (barato: recorre 130 fotos en segundos).
2. **Realce antes del OCR**: `plano` (dividir por el fondo desenfocado: quita el degradado de luz y
   el cepillado del plástico) y `bh` (blackhat núcleo 7, para el relieve hundido).
3. **Ventana por caja**, 900 px de ancho y **más alta por abajo que por arriba**: la caja del detector
   suele ser el renglón de arriba (`4148399X`) y el número va **debajo**.
4. **Normalización tolerante** anclada en el bloque `857`: `2G1`, `26J`, `2EJ`, `361` se leen `2GJ`;
   la `G` final se lee `6`, `C`, `Q` o `(`; si el bloque final no sale, se completa con el catálogo y
   **queda anotado**.

**Prueba.** `pruebas/test_p31_parte.py` (7 pruebas, una sobre la foto real del 222504).

---

## 5. Ahorro de barrido por parecido de tomas (ORB)

**Qué resuelve.** No leer 130 fotos por caso para encontrar una.

**Dónde.** `fotos_parecidas.py` + `leer_parte_por_parecido.py`.

**Cómo funciona.** Las tomas son una **secuencia fija**; se ordenan las fotos del caso por parecido
ORB con la toma buena del 222504 (`VOR/IMG_1598.JPG`) y se leen las primeras, cortando al juntar dos
lecturas iguales. En el 222504 el barrido completo da **una** lectura (precisión perfecta, coste
alto); con parecido se hace en 8 fotos.

**Prueba.** Uso directo documentado en `leer_parte_por_parecido.py --referencia`.

---

## 6. Generador: dos fuentes que no dependen del mismo error

**Qué resuelve.** El tipo de generador (`NOM/OGL/UGL`) sin copiarlo del libro.

**Dónde.** `rellenar_desde_referencia.py` → `arreglar_generador`, `generador_en_barra`.

**Cómo funciona.** Nombre de la carpeta (`222521 RDW OGL NT`) + barra inferior del vídeo
(`232561 RdW HT OGL 0ms`). Se reparan sólo las dos posiciones que fallan de verdad (última letra → L,
primera → U) y **se escribe cuando las dos fuentes coinciden**; si discrepan, no se toca la celda y
sale la duda con las dos lecturas.

---

## 7. Proveedor leído, no escrito a mano

**Qué resuelve.** `Autoliv` / `FORVIA` desde la etiqueta girada 90° y en cuerpo diminuto.

**Dónde.** `utilidades/lector_etiquetas.py` + `leer_etiqueta_*` en `evidencia_modulo.py`.

**Cómo funciona.** Se busca en la mitad derecha de la foto, en los tres giros y ampliada; se contrasta
con la celda. Si se sostiene, se escribe como `corroborado_por_etiqueta`.

**Prueba.** `pruebas/test_p29_proveedor.py`.

---

## 8. Variantes: la forma, no el catálogo

**Qué resuelve.** Que un dato distinto (otra variante de PAB, otro motivo de prueba) no rompa la
lectura.

**Dónde.** `utilidades/protocolo_campos.py` → `normalizar_por_campo` + gramáticas.

**Cómo funciona.**
- **Número de parte**: `ABC.123.456.` + **1 o 2** caracteres; se normaliza venga con espacios, todo
  seguido o en minúsculas.
- **Motivo de prueba**: mayúsculas y sin acentos, admite paréntesis; **no** es un catálogo cerrado.
- Lo que no tiene forma se rechaza (`2GJ.880.204` sin sufijo, `BMG_1`, cadenas de 45 caracteres).

**Prueba.** `pruebas/test_p33_variantes.py` (29 pruebas).

---

## 9. Medición: la única cifra que vale

**Qué resuelve.** Saber si el lote mejoró o empeoró, contra el libro completo.

**Dónde.** `medir_contra_referencia.py`.

```bash
python3 medir_contra_referencia.py --libro versionV16_0_45.xlsx --referencia uploads/Book-10-Examples.xlsx
# → llenas 154/180 · coinciden 149 · discrepan 5 · vacías 26
```

Se corre **después de cada lote** y se pega el resultado en el informe. Sin esto, no hay lote.

---

## 10. Paquete y ensayo: cómo se publica un parche

**Qué resuelve.** Que el instalador no se reinvente y que se pueda deshacer.

**Dónde.** `vmatrix/construir_paquete_p33.py`, `vmatrix/ensayo_paquete_p30.py`,
`evidencia/ensayo_instalador.py`.

**Cómo funciona.** El paquete se copia de la **versión que el usuario tiene instalada** (hoy
V16.0.28), se le cambia la versión, se sustituye el payload por los archivos del árbol de trabajo y
se recalculan **todos** los hashes; los hashes de V16.0.28 van declarados como «versión previa».
El ensayo prueba 10 bloques: prístino, instalar, verificar, reinstalar, proyecto ajeno, archivo tocado
a mano, restauración sin permiso, restauración limpia, respaldo manipulado y payload corrupto.

**Estado.** 10/10 en V16.0.46, y además probado sobre un proyecto **realmente en V16.0.28**:
`INSTALABLE` → `102/102` → `VERIFICADO 102/102`.
