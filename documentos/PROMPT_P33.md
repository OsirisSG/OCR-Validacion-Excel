# Prompt de continuación · VMATRIX (P34)

> Copia y pega este mensaje al empezar la siguiente sesión. Está escrito para que quien lo reciba
> —persona o modelo— sepa qué se está haciendo, qué ya funciona, cómo hay que devolver las cosas y
> qué falta, sin tener que reconstruir nada.

---

## 1. Qué es este trabajo

Leer automáticamente los datos de las **placas y etiquetas de airbag** (módulo PAB y tablero de
instrumentos) a partir de fotos y **rellenar el libro Excel** del proyecto sin inventar nada: lo que
no se sostiene con las fotos **no se escribe**, y sale como **duda con el recorte al lado** para que
una persona lo confirme de un clic.

- Fotos de entrada: `/var/tmp/fotos/<caso>/{NACH,VOR}/*.JPG` (unos 130 archivos por caso, 10 casos).
- Libro de referencia (verdad de campo): `uploads/Book-10-Examples.xlsx`.
- Cada caso es una carpeta con nombre `222504 RDW NOM NT` → **número · proyecto · lugar · temperatura**.
- El motor de OCR es RapidOCR sin torch (`utilidades/codigos_modulo.motor_compartido()`).

## 2. Estado actual (cerrado y verificado)

| lote | qué dejó | archivo de entrega |
|---|---|---|
| P27 | etiqueta del **módulo PAB**: parte, nivel, fecha, serie, variante (protocolo de dos códigos) | — |
| P28 | **tipo de generador** por carpeta + barra del vídeo | — |
| P29 | **proveedor** leído de la etiqueta (`Autoliv`) + sintaxis del nivel `##K`/`##S` | — |
| P30 | **tablero**: nivel (estampa rosa), fecha (pegatina), serie (etiqueta QR) | `versionV16_0_43.xlsx` |
| P31/P32 | **número de parte moldeado** del tablero `2GJ.857.003.G` | `versionV16_0_45.xlsx` |
| P33 | **variantes**: número de parte con sufijo de 2 y motivo de prueba normalizado | `VMATRIX_PARCHE_V16_0_46.zip` |

Medición vigente: **154/180 celdas llenas · 149 coinciden · 5 discrepan** contra el libro de
referencia. Por campo del tablero: **N/P 5/9 · nivel 7/9 · fecha 5/9 · serie 1/9**.

Las 5 discrepancias son conocidas y **a propósito**: 3 son el generador (se decidió leer carpeta +
barra aunque el libro diga otra cosa), 1 es la fecha del módulo del 222530 y 1 es un espacio en la
serie del módulo.

## 3. Reglas de campo que hay que respetar (vienen de la lámina y del usuario)

- **N/P del tablero**: `2GJ.857.003.G`. Va **grabado en relieve** en el plástico negro —no impreso—,
  en la parte **inferior del grabado**; el último bloque puede ser **letra o número**.
- **N/P del módulo (PAB)**: `2GJ.880.204.J`. Va **impreso** en la etiqueta VW AG, junto a `ZRZ 02S`.
  Admite variantes con sufijo de **1 o 2** caracteres.
- **Serie del tablero**: etiqueta QR **parecida pero no igual** a la del PAB; si hay varias, **la más
  larga**. No confundir con la del módulo (`671 ZRZ…`).
- **Fecha del tablero**: etiqueta QR con **sticker de color** (azul); en la pieza dice `17/MAY/2025`
  y en el libro va `DD/MM/AAAA`.
- **Nivel del tablero**: **estampa rosa** (`##S`, se admite `##K`). La amarilla es la del módulo.
- **Motivo de prueba** (`test_reason`): lo lee la **pizarra escrita a mano** del vídeo; nunca se
  copia del libro.
- **Proveedor del generador**: se **lee** de la etiqueta (`Autoliv`), no se pone a mano.
- **Generador**: carpeta del caso + barra del vídeo (decisión del usuario, aunque el libro discrepe).

## 4. Cómo hay que devolver las cosas (formato de entrega)

En cada lote, siempre **estos cinco** entregables y en este orden:

1. **`versionV16_0_NN.xlsx`** — el libro rellenado. Se construye **siempre desde el libro anterior**,
   nunca desde el de referencia: las celdas que ya estaban se respetan y sólo se escriben vacías.
2. **`informe_pNN.json`** — qué se escribió (caso, campo, valor, origen) y la lista de **dudas** con
   `motivo`, `valor`, `detalle`, `imagen` (recorte) y `opciones` (valor propuesto / dejar vacío).
3. **`documentos/dudas_pNN.html`** — panel de dudas con la imagen incrustada (JPEG recomprimido a
   640 px, calidad 72: el panel entero tiene que pesar < 1 MB).
4. **`documentos/INFORME_pNN_*.md`** — método, tablas de lo leído, lo que quedó en duda y **por qué**.
5. **`vmatrix/VMATRIX_PARCHE_V16_0_NN.zip`** + `.sha256` — el parche, con el ensayo de 10 bloques
   en verde y el `LEEME_V16_0_NN.md` dentro. Y una **versión ligera** (`_LIGERO.zip`, <1 MB) para
   cuando el zip completo no se puede descargar.

Además, en cada respuesta al usuario: el número de celdas escritas, la medición contra la referencia
(`llenas / coinciden / discrepan`) y **nombres exactos de archivo**. Nada de «he mejorado la
lectura» sin cifras.

### Reglas de honestidad

- Si no hay nada que escribir, **se dice** («este lote no escribe nada, y por esto») y se documenta.
- Cada valor escrito lleva **origen** (`pizarra`, `etiqueta_del_tablero`, `grabado_moldeado`,
  `grabado_moldeado_catalogo`, `barra_video`, `correo`). Si el bloque final de un número de parte se
  completó con el catálogo, se dice en el origen.
- Los recortes de las dudas se generan del **mismo recorte que se leyó**, no de la foto entera.

## 4.5. La documentación viaja en el parche y se instala en el repo

Los documentos de este lote (`documentos/PROMPT_P33.md`, `LOGICAS_QUE_FUNCIONAN.md`,
`VARIANTES_motivo_y_PAB.md`, `INFORME_P32_TABLERO.md`, `ENTREGA_P33.md` y las copias de
`documentos/logicas/`) van **dentro del payload**: al instalar aparecen en la carpeta `documentos/`
del proyecto, junto a los informes de lote que ya estaban.

Y se pueden editar sin miedo. El instalador los trata distinto del código: si un documento no está
como se entregó, lo marca **EDITADO** y **no lo pisa** —lo respeta, lo cuenta aparte en `verificar` y
te avisa—. El código, en cambio, sigue protegido igual que siempre: un `.py` tocado a mano deja el
diagnóstico en **INCOMPATIBLE** y no se instala nada.

```
verificar  →  VERIFICADO 122/122.
              Documentos editados por ti y respetados: 1 (no se tocan).
```

## 5. Cómo se construye el parche (importante)

El parche se arma **desde lo que el usuario tiene instalado: V16.0.28**.

```bash
cd /home/user/vmatrix
python3 construir_paquete_p33.py            # ORIGEN = instalador_v16_0_28 → instalador_v16_0_46
python3 ensayo_paquete_p30.py instalador_v16_0_46 /tmp/ensayo.txt   # 10/10
zip -r -X -q VMATRIX_PARCHE_V16_0_46.zip instalador_v16_0_46 && sha256sum VMATRIX_PARCHE_V16_0_46.zip
```

Antes de publicar hay que **probar el parche sobre un proyecto realmente en V16.0.28**:

```bash
rm -rf /tmp/p28 && mkdir -p /tmp/p28
git -C trabajo archive 0f0d84c | tar -x -C /tmp/p28            # proyecto base
python3 instalador_v16_0_28/evidencia/ensayo_instalador.py instalador_v16_0_28 instalar /tmp/p28
python3 instalador_v16_0_46/evidencia/ensayo_instalador.py instalador_v16_0_46 diagnosticar /tmp/p28
python3 instalador_v16_0_46/evidencia/ensayo_instalador.py instalador_v16_0_46 instalar /tmp/p28
python3 instalador_v16_0_46/evidencia/ensayo_instalador.py instalador_v16_0_46 verificar /tmp/p28
```

Tiene que dar: `INSTALABLE` → `INSTALACION CORRECTA … VERIFICADO 102/102` → `VERIFICADO 102/102` y,
repetido, `Ya instalada`. Si sale `DESCONOCIDO` o `BLOQUEADO` **no se publica**.

## 6. Límites de la máquina (esto ha costado horas)

- **Memoria: 2 GB.** Cada llamada al OCR deja ~200 MB. **Un solo proceso de OCR a la vez** y, si hay
  que leer muchas fotos, **un subproceso por foto** (`leer_parte_foto.py`). En un mismo proceso, más
  de ~8 lecturas acaban en `Killed`.
- `/tmp` es pequeño: limpiar antes de comprimir (`rm -rf /tmp/pytest-of-user /tmp/evidencia_*`).
- El OCR es RapidOCR sin torch; **no hay tesseract**. `cv2.QRCodeDetector` no sirve para DataMatrix.
- Una foto con OCR ≈ 1 s a 2 000 px; el barrido completo de un caso ≈ 22 min.

## 7. Lo que falta (P34 en adelante)

1. **N/P del tablero 9/9**: faltan 5 carpetas (222521, 232550, 232564, 252581, 252590). No es un
   fallo del lector: en esas carpetas no hay toma del grabado legible. Hace falta **una foto más por
   carpeta**: la cara inferior junto al módulo, como `222504/VOR/IMG_1598.JPG`.
2. **Serie del tablero 8/9 en duda**: las lecturas no coinciden entre fotos o la serie acaba en
   dígito; hay que confirmarlas en el panel (un clic) o afinar la cola.
3. **Fecha 4/9 en duda** y **nivel 2/9 sin estampa**: igual, panel o fotos nuevas.
4. **Variantes**: si aparece un proyecto con otro prefijo de número de parte (`4M0`, `5QF`, `1EA`) o
   un motivo de prueba nuevo, las reglas ya lo aceptan; lo que hay que hacer es **añadir el caso a
   `pruebas/test_p33_variantes.py`** para que quede cubierto.

## 8. Archivos que no hay que tocar sin querer

- `utilidades/protocolo_campos.py` — gramáticas por campo; **es la puerta** de todo lo que se escribe.
- `utilidades/grabado_punteado.py` — número de parte moldeado; depende del realce (`plano`, `bh`).
- `utilidades/tablero_campos.py` — serie, fecha y nivel del tablero (estampa **rosa**).
- `rellenar_desde_referencia.py` — único punto que escribe en el libro; las celdas ocupadas se
  respetan (`--libro` es el libro anterior).
- `evidencia/ensayo_instalador.py` — espejo en Python del instalador PowerShell; es lo que se usa
  para ensayar el paquete.
