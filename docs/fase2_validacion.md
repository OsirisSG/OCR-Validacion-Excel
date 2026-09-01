# Fase 2 — Recorrido de carpetas y validación cruzada (`validacion.py`)

## Propósito

Usa `estructura_detectada.json` (Fase 0) para saber qué carpetas hoja procesar,
clasifica cada archivo, corre `extraer_texto()` (Fase 1) sobre las imágenes,
identifica la imagen de referencia y compara los tokens de la etiqueta contra
los de la referencia. Salida: `validacion_resultados.json` (la consumen la Fase
3 y el dashboard).

```
python validacion.py [--estructura ruta.json] [--salida ruta.json]
```

## Flujo por carpeta hoja

1. **Clasificación de archivos** (`clasificar_archivo`):
   - por extensión: `video` / `otro` / imagen;
   - imagen con pista de nombre (`ref`, `referencia`, `info`…) → `candidato_referencia`;
   - resto de imágenes: heurística foto vs diagrama por contenido (pocos colores
     cuantizados + poco ruido de Laplaciano → `diagrama`; si no → `fotografia`).
2. **OCR una sola vez por imagen** (caché por lote compartida entre carpetas).
3. **Referencia** (`identificar_referencia`, AISLADA y sustituible):
   pista de nombre primero; si no hay pista, heurística de densidad de texto
   (Σ áreas de bboxes / área de imagen) con tres salvaguardas:
   ≥ 2 imágenes, densidad ≥ `umbral_densidad_texto` (0.010) y ventaja ≥
   `ventaja_minima_referencia` (1.5×) sobre la segunda mejor. Sin ganador claro
   → `sin_referencia` (no se adivina).
4. **Imágenes conservadas**: todas las imágenes quedan en `imagenes`, con id,
   nombre, rol y OCR propio. `etiqueta` y `referencia` se mantienen como campos
   de compatibilidad, pero ya no descartan las fotografías adicionales.
5. **Etiqueta principal**: entre las fotografías restantes, la de mayor
   confianza OCR (`estrategia_etiqueta: mejor_confianza`; alternativa:
   `primera`).
6. **Comparación agregada** (`comparar_tokens`): reúne los tokens de todas las
   fotos de etiqueta y todas las referencias, los normaliza (mayúsculas, solo
   alfanuméricos). Con `comparar_solo_tokens_codigo: true` solo se comparan
   tokens tipo código (los que contienen dígitos), ignorando rótulos de
   lenguaje natural ('PRUEBA DE ETIQUETA') que no forman parte del contrato.
   - `ratio = |etiqueta ∩ referencia| / |etiqueta|` (los extras de la ficha no
     penalizan).
   - `ratio ≥ umbral_coincidencia_total (1.0)` → **coincidencia_total**;
     `0 < ratio < umbral` → **coincidencia_parcial**; `ratio = 0` →
     **discrepancia**; sin referencia o referencia sin texto → **sin_referencia**.
   - Etiqueta sin texto legible → discrepancia con observación explícita.

## Ejemplo real: `01_A1_variante2` de inicio a fin (salida del pipeline)

| Paso | Resultado |
| --- | --- |
| Archivos | `foto_frontal.jpg`, `foto_lateral.jpg`, `info_referencia.jpg`, `video_ensayo.mp4` |
| Clasificación | fotografia ×2 (frontal, lateral), candidato_referencia (info_referencia.jpg, pista de nombre), video ×1 |
| OCR etiqueta (mejor confianza: foto_frontal.jpg) | tokens `['PRUEBA DE ETIQUETA', 'ETQ-2024-A1-V2']`, conf 99.98%, QR detectado |
| OCR referencia (info_referencia.jpg) | tokens `['ETQ-2024-A1-V2', 'FICHA TECNICA DE REFERENCIA', 'REV 2 - AREA DE ENSAYOS', …]` |
| Tokens tipo código comparados | etiqueta `{ETQ2024A1V2}` vs referencia `{ETQ2024A1V2, REV2AREADEENSAYOS, …}` |
| Comparación | `ratio = 1.0`, coincidentes `[ETQ2024A1V2]`, faltantes `[]` → **coincidencia_total** |

## Resultados del lote sintético completo (6 carpetas hoja)

| Carpeta | Resultado | Confianza | QR | Referencia |
| --- | --- | --- | --- | --- |
| 01_A1_variante2 | coincidencia_total | 99.98 | sí | por pista de nombre |
| 02_A1_variante3 | coincidencia_total | 99.98 | sí | por pista de nombre (etiqueta leída de foto invertida 180°) |
| 03_B7_variante1 | coincidencia_total | 99.98 | no* | **por densidad de texto** (IMG_20240312.jpg, sin pista) |
| 04_B7_variante2 | discrepancia | 99.97 | sí | código V2 vs ficha V9 |
| 05_C2_variante1 | sin_referencia | 99.99 | no | dos fotos sin ganador claro → no se adivina |
| notas_sueltas | sin_procesar | — | no | carpeta anómala sin imágenes |

\* la foto elegida como etiqueta (foto_frontal, skewed 4°) sí tenía QR; la
lateral no. El campo `qr_detectado` reporta el de la etiqueta elegida.

## Formato de salida (`validacion_resultados.json`, resumido)

```json
{
  "raiz": "...", "carpetas_procesadas": 6,
  "resultados": [{
    "ruta": "...\\01_A1_variante2", "nombre": "01_A1_variante2",
    "prefijo_numerico": "01", "nomenclatura": "A1", "variante": "2",
    "identificador": "01_A1_variante2",
    "es_conforme": true, "anomalia_fase0": null,
    "tipos_archivo": {"fotografia": ["foto_frontal.jpg", "foto_lateral.jpg"],
                       "candidato_referencia": ["info_referencia.jpg"], "video": [...]},
    "imagenes": [{"id": "...", "nombre": "foto_frontal.jpg",
                    "rol": "etiqueta_adicional", "resultado_ocr": {"texto_completo": "..."}},
                  {"id": "...", "nombre": "foto_lateral.jpg",
                    "rol": "etiqueta_principal", "resultado_ocr": {"texto_completo": "..."}},
                  {"id": "...", "nombre": "info_referencia.jpg",
                    "rol": "referencia", "resultado_ocr": {"texto_completo": "..."}}],
    "etiqueta": {"ruta": "...\\foto_frontal.jpg",
                  "resultado_ocr": {"tokens": [...], "qr_bbox": [...], ...}},
    "referencia": {"ruta": "...\\info_referencia.jpg", "resultado_ocr": {...}},
    "comparacion": {"resultado": "coincidencia_total", "ratio": 1.0,
                     "coincidentes": ["ETQ2024A1V2"], "faltantes": []},
    "confianza_ocr_pct": 99.98, "qr_detectado": true, "observaciones": []
  }]
}
```

## Decisiones de diseño y alternativas descartadas

- **Comparar solo tokens tipo código** (default activo): en la primera corrida,
  comparar todos los tokens marcó 'PRUEBA DE ETIQUETA' como faltante y degradó
  carpetas correctas a `coincidencia_parcial`. El dominio del Documento Maestro
  (§1) son nomenclaturas alfanuméricas; los rótulos naturales no son contrato.
- **Sin adivino en la referencia**: densidad + ventaja mínima + mínimo 2
  imágenes. Antes, la función devolvía "la más textosa" aunque todas fueran
  fotos de etiquetas (05_C2_variante1 daba referencia falsa). Ambigüedad →
  `sin_referencia`, que el semáforo pinta de rojo y un revisor humano resuelve.
- **Heurística aislada** (`identificar_referencia` no depende del pipeline):
  sustituible por regla de nombre de archivo (PARÁMETRO ABIERTO §10.2) sin
  tocar nada más.
- **Caché de OCR por lote**: cada imagen se lee una vez aunque la lógica de
  referencia/etiqueta la evalúe varias veces. El callback de progreso se emite
  por imagen, no solamente al terminar una carpeta.
- Alternativa descartada: identificar la referencia por resolución/aspecto —
  fotos de pantallas vs papel rompen el supuesto; la densidad de texto es la
  señal que el propio Documento Maestro propone.

## Parámetros configurables (defaults en `config.yaml → fase2`)

| Parámetro | Default | Efecto |
| --- | --- | --- |
| `umbral_densidad_texto` | 0.010 | piso de densidad para ser referencia |
| `ventaja_minima_referencia` | 1.5 | ventaja sobre la segunda candidata |
| `usar_pista_nombre` / `palabras_pista_referencia` | true / [ref, referencia, info…] | atajo por nombre de archivo |
| `estrategia_etiqueta` | mejor_confianza | elección de foto de etiqueta |
| `comparar_solo_tokens_codigo` | true | ignora lenguaje natural en la comparación |
| `umbral_coincidencia_total` | 1.0 | ratio requerido para "total" |
| `diagrama_max_colores` / `diagrama_max_ruido` | 4 / 50.0 | heurística foto vs diagrama |
| `procesar_videos` | false | reservado para futuro; hoy los videos siempre se ignoran con alerta |

## Advertencias recuperables

Cada carpeta devuelve `alertas[]` con `codigo`, `nivel`, `mensaje` e imagen
cuando aplica. `SIN_IMAGENES`, `IMAGEN_CORRUPTA`, `SIN_TEXTO_DETECTADO`,
`VIDEOS_IGNORADOS`, `ERROR_LECTURA_IMAGEN` y `FALLBACK_ACELERADOR` no abortan
todo el lote: quedan visibles en el detalle y permiten continuar revisando las
demás fotografías.

El progreso se publica por imagen. La ETA usa la mediana de una ventana de ocho
duraciones y excluye la primera muestra, que incluye la carga inicial del modelo.

## Limitaciones conocidas

- La distinción fotografia/diagrama es una heurística de v1 (colores + ruido);
  con lotes reales puede requerir calibración. No afecta la validación (ambas
  se OCR-ean igual; solo cambia la etiqueta de clasificación en el Excel).
- Si una carpeta contiene varias imágenes con nombre de referencia, todas se
  conservan y participan en la comparación; una se expone además en el campo
  heredado `referencia`.
- La estrategia `mejor_confianza` asume que la foto "buena" es la más legible;
  si todas las fotos son ilegibles, la comparación saldrá discrepancia/sin
  referencia y queda para revisión humana (comportamiento deseado).
