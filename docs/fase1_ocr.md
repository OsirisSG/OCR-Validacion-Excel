# Fase 1 — Motor de OCR local (`ocr_engine.py`)

## Propósito

`extraer_texto(imagen_path) -> dict` ejecuta el pipeline de lectura sobre una
foto de etiqueta y retorna tanto los tokens alfanuméricos para comparar códigos
como el texto completo con espacios, signos y saltos de línea. También conserva
bounding boxes, posición del QR (si existe) y orientación corregida.
Procesamiento 100% local (PaddleOCR/EasyOCR), sin APIs ni nube.

## Contrato de entrada/salida

```python
extraer_texto("foto_frontal.jpg")
# {
#   "tokens": [{"texto": "ETQ-2024-A1-V2", "bbox": (326, 132, 622, 71), "confianza": 1.0}, ...],
#   "lineas_texto": [{"texto": "PRUEBA DE ETIQUETA", "bbox": [...], "confianza": 0.99}, ...],
#   "texto_completo": "PRUEBA DE ETIQUETA\nETQ-2024-A1-V2",
#   "qr_bbox": (75, 515, 180, 180) | None,   # SOLO geometría, nunca se decodifica
#   "orientacion_corregida_grados": 4.0,
#   # campos aditivos documentados:
#   "imagen": "...", "motor": "paddle", "confianza_media": 0.998,
#   "dispositivo": "cuda" | "mps" | "cpu", "advertencias_motor": [],
#   "num_lineas_ocr": 2, "dimensiones": (1040, 760), "roi_usado": None,
#   "variante_preprocesamiento": "adaptativa",
#   "intentos_ocr": [{"orientacion_grados": 0, "variante": "adaptativa", ...}]
# }
```

CLI: `python ocr_engine.py imagen1.jpg [imagen2.png ...] [--compacto]`

## Pipeline (orden real de ejecución)

1. **Carga unicode-safe** (`np.fromfile` + `cv2.imdecode`): rutas con acentos no
   rompen en Windows es-ES (fallo clásico de `cv2.imread`).
2. **Selección de recursos**: `recursos.py` prueba el acelerador solicitado con
   una asignación real de PyTorch. En `auto` el orden es CUDA → MPS → CPU.
   EasyOCR usa la GPU; OpenCV, QR, deskew y variantes usan los hilos CPU. Si la
   inicialización o inferencia acelerada falla, se recrea el lector en CPU y se
   devuelve una advertencia trazable.
3. **Búsqueda multiorientación**: empieza en 0° y, si no aparece un código
   alfanumérico sólido, prueba 90°, 180° y 270° sin interpolar la imagen.
4. **Deskew** (±15°): umbral adaptativo → dilatación horizontal → `minAreaRect`
   → mediana de ángulos. Solo rota si supera `angulo_minimo_correccion` (2°).
5. **Variantes visuales adaptativas**: la imagen original es la ruta principal.
   Si la lectura sigue siendo débil se prueban binarización, CLAHE y realce
   morfológico de relieve para texto grabado o moldeado en plástico.
6. **Regiones de texto**: si la imagen completa no produce un código sólido,
   MSER agrupa caracteres, amplía hasta seis recortes con contexto y los escala
   antes del OCR. Las cajas se transforman de vuelta al marco orientado.
7. **Detección del QR** sobre la imagen YA corregida (así el ancla y el recorte
   comparten marco de coordenadas — ver errores/003). `cv2.QRCodeDetector` por
   defecto; `pyzbar` opcional por config. Valida cuadratura (0.7–1.3) y tamaño.
8. **ROI conservador**: expansión `3.0×` el tamaño del QR, rechazado si dejara
   < 90% del ancho/alto. Sin QR → imagen completa, sin error ni degradación.
9. **OCR dual** (EasyOCR portable por defecto / PaddleOCR alternativo, caché
   por proceso): una pasada restringida encuentra códigos y otra sin `allowlist`
   recupera lenguaje natural, espacios, acentos y puntuación.
10. **Selección por evidencia**: se priorizan tokens con letras y números; entre
   candidatos se comparan confianza, longitud y cobertura. Una lectura de texto
   natural no impide buscar un código colocado verticalmente.
11. **Reintento anti-truncamiento**: si un token toca el borde del ROI o el ROI
   no dio texto → relectura de la imagen completa.
12. **Reconstrucción y trazabilidad**: se agrupan cajas por renglón y sus huecos
    relativos reconstruyen espacios y saltos de línea. Se conservan orientación,
    variante y resumen de cada intento para explicar por qué ganó una lectura.

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
| `motor` / `motor_fallback` | easyocr / paddle | motor principal y alternativo |
| `lang` | en | alfabeto del reconocedor (nomenclaturas alfanuméricas) |
| `caracteres_permitidos` | letras, dígitos y separadores de código | limita el alfabeto de EasyOCR |
| `umbral_confianza` | 0.50 | descarta líneas por debajo |
| `umbral_confianza_texto_completo` | 0.25 | conserva texto natural tenue sin debilitar el filtro de códigos |
| `extraer_texto_completo` | true | habilita la pasada sin restricción de alfabeto y la reconstrucción de layout |
| `umbral_espacio_px` | 40 | **PARÁMETRO ABIERTO §10.3**: separa tokens en una fila |
| `preprocesamiento.deskew` / `angulo_minimo_correccion` | true / 2.0° | corrección fina |
| `preprocesamiento.binarizacion_*` | true / 51 / 15 | binarización adaptativa |
| `preprocesamiento.variante_principal` | original | primera lectura, elegida por pruebas con fotografías reales |
| `preprocesamiento.regiones_texto.activar` | true | habilita propuestas MSER y lectura ampliada por región |
| `preprocesamiento.regiones_texto.max_regiones` | 6 | limita el costo máximo de recortes |
| `preprocesamiento.regiones_texto.altura_objetivo_px` | 220 | escala regiones pequeñas antes del OCR |
| `preprocesamiento.busqueda_adaptativa.modo` | adaptativo | amplía solo si falta un código sólido; `exhaustivo` prueba todo |
| `preprocesamiento.busqueda_adaptativa.orientaciones` | 0, 90, 180, 270 | rotaciones rectas evaluables |
| `preprocesamiento.busqueda_adaptativa.variantes_respaldo` | adaptativa, CLAHE, relieve | rutas para bajo contraste y plástico grabado |
| `preprocesamiento.busqueda_adaptativa.confianza_codigo_suficiente` | 0.70 | evita pasadas extra si ya existe evidencia sólida |
| `qr.detector` | cv2 | cv2 o pyzbar (si está instalado) |
| `qr.margen_roi_factor` / `roi_frac_minima` | 3.0 / 0.90 | conservadurismo del ROI |
| `qr.reintentar_imagen_completa` | true | red de seguridad anti-truncamiento |

## Decisiones de diseño y alternativas descartadas

- **Búsqueda adaptativa en vez de costo fijo**: una etiqueta legible a 0° usa
  una sola inferencia. Las rotaciones y variantes se activan cuando falta un
  código confiable; el modo exhaustivo queda disponible para lotes difíciles.
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
- Las regiones mejoran el aislamiento, pero todavía no despliegan superficies
  cilíndricas ni rectifican perspectiva severa de forma geométrica.
- Texto manuscrito con plumón y texto curvo: los modelos preentrenados los lee
  peor; es el caso de uso del Anexo A (datos sintéticos + afinado).
- `umbral_espacio_px` es fijo en píxeles: en fotos de resoluciones muy
  dispares puede requerir calibración por lote (pendiente con datos reales).
