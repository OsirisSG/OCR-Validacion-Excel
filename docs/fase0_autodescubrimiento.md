# Fase 0 — Auto-descubrimiento de estructura (`estructura.py`)

## Propósito

Recorrer una raíz de lotes fotográficos de profundidad variable y no uniforme,
descubrir el patrón dominante de nombres de carpeta y clasificar cada carpeta
como **conforme** o **anómala**, sin asumir profundidad fija ni nombres
preconocidos. El resultado se serializa en `estructura_detectada.json`, que
consumen las Fases 2 y 3 (evita recorrer disco dos veces).

## Uso

```
python estructura.py <ruta_raiz> [--salida ruta.json]
```

Como librería: `mapear_estructura(ruta_raiz) -> dict` (retorna estructura de
datos, no imprime), `guardar_estructura(estructura, ruta)`, y
`carpetas_hoja(estructura)` para saber qué procesar en Fase 2.

## Heurística implementada

1. **Recorrido recursivo determinista** (`os.walk` con hijos ordenados). Por
   cada carpeta se registra: ruta completa y relativa, profundidad, nombre,
   archivos agrupados por categoría (imagen / video / otro, según extensiones de
   `config.yaml → fase0`) y si el nombre empieza con prefijo numérico.
2. **Regex generadas dinámicamente**: cada nombre se parte en tokens por `_`, `-`
   o espacio (los separadores se conservan literales) y cada token se generaliza:
   | Token | Fragmento regex | Ejemplo |
   | --- | --- | --- |
   | solo dígitos | `\d{k}` (conserva ancho) | `01` → `\d{2}` |
   | MAYÚSCULAS+dígitos con letra | `[A-Z0-9]+` | `A1` → `[A-Z0-9]+` |
   | palabra+dígitos | `palabra\d+` | `variante2` → `variante\d+` |
   | palabra pura | literal | `sueltas` → `sueltas` |
   | otro | `re.escape` | — |
3. **Patrón dominante** = el regex generalizado compartido por más carpetas, si
   alcanza el mínimo `fase0.min_carpetas_para_patron` (default **2**). Si ninguna
   familia lo alcanza, se declara `patron_dominante: null` y todas las subcarpetas
   quedan anómalas con motivo `sin_patron_dominante` (no se inventa patrón).
4. **Conforme** = `re.fullmatch(patron_dominante, nombre)`. El resto es anómala
   con motivo `no_cumple_patron_dominante`.
5. **Hoja** = carpeta con archivos y sin ningún descendiente con archivos (una
   carpeta intermedia que solo agrupa no se procesa en Fase 2).

## Formato de salida (`estructura_detectada.json`)

```json
{
  "raiz": "C:\\...\\datos_prueba\\Lote_Pruebas",
  "generado_en": "2026-08-23T01:10:52",
  "total_carpetas": 7,
  "patron_dominante": "\\d{2}_[A-Z0-9]+_variante\\d+",
  "estadisticas_patrones": {"\\d{2}_[A-Z0-9]+_variante\\d+": 5, "notas_sueltas": 1},
  "carpetas": [
    {
      "ruta": "C:\\...\\01_A1_variante2",
      "ruta_relativa": "01_A1_variante2",
      "nombre": "01_A1_variante2",
      "profundidad": 1,
      "es_raiz": false,
      "sigue_patron_prefijo_numerico": true,
      "patron_generalizado": "\\d{2}_[A-Z0-9]+_variante\\d+",
      "conforme": true,
      "motivo_anomalia": null,
      "es_hoja": true,
      "archivos": {"imagenes": ["foto_frontal.jpg", "foto_lateral.jpg", "info_referencia.jpg"],
                    "videos": ["video_ensayo.mp4"], "otros": []},
      "conteos": {"imagenes": 3, "videos": 1, "otros": 0}
    }
  ],
  "anomalias": [{"ruta": "C:\\...\\notas_sueltas", "motivo": "no_cumple_patron_dominante"}]
}
```

## Evidencia de ejecución (datos sintéticos de `datos_prueba/`)

```
Raíz: ...\datos_prueba\Lote_Pruebas
Patrón dominante: '\d{2}_[A-Z0-9]+_variante\d+'
Carpetas: 7 | conformes: 5 | anómalas: 1 | hoja: 6
  ANÓMALA [no_cumple_patron_dominante]: ...\notas_sueltas
```

**Ejemplo 1 (conforme).** `01_A1_variante2` → tokens `01` (dígitos), `A1`
(nomenclatura), `variante2` (palabra+dígitos) → `\d{2}_[A-Z0-9]+_variante\d+`.
Coincide con el dominante (5 carpetas lo comparten) → conforme. Es hoja porque
contiene 3 imágenes + 1 video.

**Ejemplo 2 (anómala).** `notas_sueltas` → tokens literal `notas` + `sueltas` →
patrón propio `notas_sueltas` con 1 sola ocurrencia (< mínimo 2) → anómala por
`no_cumple_patron_dominante`. Además su único archivo cae en "otros" (.txt).

**Ejemplo 3 (no-hoja).** La raíz `Lote_Pruebas` tiene profundidad 0, sin archivos
propios: no es hoja y no se procesa en Fase 2; sus hijas sí.

## Decisiones de diseño y alternativas descartadas

- **Generalizar dígitos con ancho fijo (`\d{2}`) en vez de `\d+`**: reproduce el
  patrón de referencia del Documento Maestro y detecta como anomalía un lote con
  numeración inconsistente (`2_A1_variante3` no cumple `\d{2}_...`). Alternativa
  descartada (`\d+`) por ser demasiado laxa: uniría familias distintas.
- **Palabras literales en el patrón** (p.ej. `variante`): el dominante queda
  anclado a la semántica real del lote en vez de aceptar cualquier palabra.
- **Umbral mínimo de carpetas** (configurable, default 2): evita declarar
  "dominante" un patrón que solo describe a una sola carpeta.
- **`es_hoja` por contenido, no por profundidad**: la jerarquía real no es
  uniforme; una carpeta intermedia vacía no debe generar filas en el Excel.

## Parámetros configurables (defaults en `config.yaml → fase0`)

| Parámetro | Default | Efecto |
| --- | --- | --- |
| `extensiones_imagen` | jpg, jpeg, png, bmp, tif, tiff, webp | clasificación de archivos |
| `extensiones_video` | mp4, avi, mov, mkv, wmv | clasificación de archivos |
| `min_carpetas_para_patron` | 2 | mínimo de carpetas para declarar dominante |
| `archivo_salida` | `estructura_detectada.json` | artefacto serializado |

## Limitaciones conocidas

- La clasificación conforme/anómala es **solo por nombre de carpeta** (como pide
  el Documento Maestro); una carpeta conforme pero sin fotos se reporta vía
  conteos, no como anomalía de Fase 0.
- Si dos familias de patrón empatan en cantidad, se elige la alfabéticamente
  menor (determinista, documentado aquí); con datos reales conviene revisar
  `estadisticas_patrones` en el JSON.
- Nombres con mezcla rara de mayúsculas/minúsculas caen en `re.escape` (patrón
  único) y quedarán anómalos; ajustable si aparecen en lotes reales.
