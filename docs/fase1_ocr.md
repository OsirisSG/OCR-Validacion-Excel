# Fase 1 — Motor de OCR local (`ocr_engine.py`)

## Propósito

`extraer_texto(imagen_path) -> dict` ejecuta el pipeline de lectura sobre una
foto de etiqueta y retorna tokens con bounding boxes, posición del QR (si
existe) y orientación corregida. Procesamiento 100% local (PaddleOCR/EasyOCR),
sin APIs ni nube.

## Contrato de entrada/salida

```python
extraer_texto("foto_frontal.jpg")
# {
#   "tokens": [{"texto": "ETQ-2024-A1-V2", "bbox": (326, 132, 622, 71), "confianza": 1.0}, ...],
#   "qr_bbox": (75, 515, 180, 180) | None,   # SOLO geometría, nunca se decodifica
#   "orientacion_corregida_grados": 4.0,
#   # campos aditivos documentados:
#   "imagen": "...", "motor": "paddle", "confianza_media": 0.998,
#   "num_lineas_ocr": 2, "dimensiones": (1040, 760), "roi_usado": None
# }
```

CLI: `python ocr_engine.py imagen1.jpg [imagen2.png ...] [--compacto]`

## Pipeline (orden real de ejecución)

1. **Carga unicode-safe** (`np.fromfile` + `cv2.imdecode`): rutas con acentos no
   rompen en Windows es-ES (fallo clásico de `cv2.imread`).
2. **Orientación de documento (0/90/180/270)**: clasificador interno de
   PaddleOCR (`use_doc_orientation_classify=True`). Corrige fotos boca abajo o
   giradas antes de detectar texto.
3. **Deskew** (±15°): umbral adaptativo → dilatación horizontal → `minAreaRect`
   → mediana de ángulos. Solo rota si supera `angulo_minimo_correccion` (2°).
4. **Binarización adaptativa** (Gauss, blockSize 51, C 15) tras el deskew.
5. **Detección del QR** sobre la imagen YA corregida (así el ancla y el recorte
   comparten marco de coordenadas — ver errores/003). `cv2.QRCodeDetector` por
   defecto; `pyzbar` opcional por config. Valida cuadratura (0.7–1.3) y tamaño.
6. **ROI conservador**: expansión `3.0×` el tamaño del QR, rechazado si dejara
   < 90% del ancho/alto. Sin QR → imagen completa, sin error ni degradación.
7. **OCR** (Paddle principal / EasyOCR fallback, caché por proceso) con filtro
   de confianza por línea.
8. **Respaldo 180° adaptativo**: solo si la lectura salió vacía o con confianza
   < 0.60, se prueba rotada 180° y gana la mejor pasada (el clasificador del
   paso 2 cubre el caso normal; esto es red de seguridad).
9. **Reintento anti-truncamiento**: si un token toca el borde del ROI o el ROI
   no dio texto → relectura de la imagen completa.
10. **Segmentación de tokens** (ver abajo).

## Ejemplo: texto crudo del motor vs tokens finales (caso a: QR + texto arriba)

```
=== TEXTO CRUDO DEL MOTOR (líneas con caja y confianza) ===
  'PRUEBA DE ETIQUETA'    bbox=(328, 71, 339, 34)  conf=0.9995
  'ETQ-2024-A1-V2'        bbox=(326, 132, 622, 71) conf=1.0000

=== TOKENS FINALES SEGMENTADOS ===
  'PRUEBA DE ETIQUETA'    bbox=(328, 71, 339, 34)  conf=0.9995
  'ETQ-2024-A1-V2'        bbox=(326, 132, 622, 71) conf=1.0000

qr_bbox: (75, 515, 180, 180) | roi: None (política conservadora: sin recorte)
```

Cuando el motor entrega líneas completas la segmentación es paso transparente;
su valor aparece cuando el detector parte el código en fragmentos:
- **Filas**: dos cajas están en la misma fila si su solape vertical supera el
  50% de la menor altura (salto de línea = fila nueva).
- **Dentro de la fila**: hueco horizontal ≤ `umbral_espacio_px` (40 px) → mismo
  token; hueco mayor → tokens separados.
- **Unión de fragmentos**: sin espacio si el hueco es < 25% de la altura
  (palabra partida por el detector, típico en códigos), con espacio si es mayor
  (palabras distintas). La caja del token es la unión; la confianza, la mínima.

## Casos de prueba obligatorios (§3) — resultado verificado

`pruebas/prueba_fase1_casos.py` (salida real del 2026-08-23):

| Caso | Imagen | QR | Tokens obtenidos | Veredicto |
| --- | --- | --- | --- | --- |
| (a) QR + texto arriba | caso_a_qr_texto_arriba.png | sí | `['PRUEBA DE ETIQUETA', 'ETQ-2024-A1-V2']` conf 0.9998 | OK |
| (b) QR + texto abajo | caso_b_qr_texto_abajo.png | sí | `['ETQ-2024-A1-V2', 'PRUEBA DE ETIQUETA']` conf 0.9996 | OK |
| (c) sin QR + texto arriba | caso_c_sin_qr_texto_arriba.png | no | `['PRUEBA DE ETIQUETA', 'ETQ-2024-A1-V2']` conf 0.9998 | OK |
| (d) sin QR + texto abajo | caso_d_sin_qr_texto_abajo.png | no | `['ETQ-2024-A1-V2', 'PRUEBA DE ETIQUETA']` conf 0.9998 | OK |
| extra: invertida 180° | 02_A1_variante3/foto_lateral.jpg | no | `['PRUEBA DE ETIQUETA', 'ETQ-2024-A1-V3']` conf 0.9997 | OK |
| extra: skew 4° | 03_B7_variante1/foto_frontal.jpg | sí | `['PRUEBA DE ETIQUETA', 'ETQ-2024-B7-V1']` conf 0.9969, rot 4.0° | OK |

La ausencia/presencia del QR y la posición del texto no cambian el
comportamiento: el código se extrae completo en los cuatro casos.

## Parámetros configurables (defaults en `config.yaml → fase1`)

| Parámetro | Default | Efecto |
| --- | --- | --- |
| `motor` / `motor_fallback` | paddle / easyocr | motor principal y de respaldo |
| `lang` | en | alfabeto del reconocedor (nomenclaturas alfanuméricas) |
| `umbral_confianza` | 0.50 | descarta líneas por debajo |
| `umbral_confianza_segunda_pasada` | 0.60 | dispara el respaldo 180° |
| `umbral_espacio_px` | 40 | **PARÁMETRO ABIERTO §10.3**: separa tokens en una fila |
| `preprocesamiento.deskew` / `angulo_minimo_correccion` | true / 2.0° | corrección fina |
| `preprocesamiento.detectar_invertida_180` | true | respaldo 180° |
| `preprocesamiento.binarizacion_*` | true / 51 / 15 | binarización adaptativa |
| `qr.detector` | cv2 | cv2 o pyzbar (si está instalado) |
| `qr.margen_roi_factor` / `roi_frac_minima` | 3.0 / 0.90 | conservadurismo del ROI |
| `qr.reintentar_imagen_completa` | true | red de seguridad anti-truncamiento |

## Decisiones de diseño y alternativas descartadas

- **Clasificador de orientación de documento** en vez de doble pasada 180°
  siempre: corrige 0/90/180/270 con una inferencia barata; la doble pasada
  quedaría como costo fijo ×2 en todo el lote. La doble pasada adaptativa queda
  como respaldo (ver errores/003 y la iteración previa).
- **ROI conservador por política** (nunca < 90% de dimensión): el Documento
  Maestro advierte que el texto no tiene posición fija; un recorte agresivo
  truncó códigos en la primera iteración (errores/003). El ROI queda para
  fotos con márgenes vacíos evidentes.
- **QR detectado tras el deskew**: evita mezclar coordenadas de marcos
  distintos (bug real de la primera iteración).
- **`cv2.QRCodeDetector.detect()`** (geometría) en vez de `detectAndDecodeMulti`:
  el decodificador es más frágil y el contrato pide solo ubicar. pyzbar queda
  como alternativa configurable.
- **Filtro de confianza antes de segmentar**: evita que líneas basura (conf
  < 0.5) contaminen tokens de código.

## Limitaciones conocidas

- **CPU**: la rueda instalada es `paddlepaddle` CPU. Con 6 GB de VRAM
  disponibles, instalar `paddlepaddle-gpu` reduciría el tiempo por lote
  (documentado como pendiente, no afecta exactitud).
- `enable_mkldnn=False` obligatorio en este entorno (bug oneDNN, errores/001);
  desactivar MKLDNN cuesta algo de velocidad en CPU.
- El deskew no corrige rotaciones grandes (> 15°) ni perspectiva; para eso
  está el clasificador de documento (múltiplos de 90°) y, en el futuro, el
  fine-tuning del Anexo A.
- Texto manuscrito con plumón y texto curvo: los modelos preentrenados los lee
  peor; es el caso de uso del Anexo A (datos sintéticos + afinado).
- `umbral_espacio_px` es fijo en píxeles: en fotos de resoluciones muy
  dispares puede requerir calibración por lote (pendiente con datos reales).
