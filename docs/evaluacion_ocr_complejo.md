# Evaluación OCR con placas grabadas reales

## Fuente y alcance

Se descargó temporalmente el repositorio público
[`Embossed-Text-Reader`](https://github.com/DevashishPrasad/Embossed-Text-Reader),
cuya colección contiene placas y piezas metálicas con texto en relieve,
reflejos, curvatura y contraste irregular. La fuente no declara una licencia de
redistribución; por esa razón las fotografías se conservan únicamente en
`.pruebas_externas/`, que Git ignora. El detalle externo dentro de **Listado** permite
verlas, repetir la medición y confirmar correcciones sin incorporarlas al
repositorio. Se agregaron cuatro imágenes del directorio oficial de ejemplos de
[`EasyOCR`](https://github.com/JaidedAI/EasyOCR/tree/master/examples), publicado
bajo Apache-2.0, para medir texto natural en escenas, francés y señalización.
`pruebas/evaluar_ocr_externo.py` conserva además el evaluador CLI.

Fecha de la medición actual: 2026-08-31. Motor: EasyOCR local con Apple MPS;
preprocesamiento OpenCV por CPU.

## Casos

| Imagen | Dificultad | Texto esperado normalizado |
| --- | --- | --- |
| `test4.jpg` | pieza curva, relieve y reflejo | `IBC20` |
| `test5.jpg` | pieza curva, bajo contraste | `GCC10` |
| `test18.jpg` | placa plana, relieve fino | `123456789` |
| `test2.jpg` | código solo numérico sobre metal | `96819216` |
| `easyocr_english.png` | cartel con múltiples renglones | 7 fragmentos en inglés |
| `easyocr_example3.png` | texto de escena en distintas zonas | 3 fragmentos |
| `easyocr_french.jpg` | texto natural con acentos | 5 fragmentos en francés |
| `easyocr_chinese.jpg` | señalización bilingüe | 3 fragmentos |

## Resultado después de los ajustes

| Imagen | Mejor lectura | Exacta | Intentos | Tiempo |
| --- | --- | --- | ---: | ---: |
| `test4.jpg` | `IBCZI` | no; dos sustituciones | 2 | 13.94 s |
| `test5.jpg` | `GCCIO` | no; dos sustituciones | 2 | 6.71 s |
| `test18.jpg` | `1234456789` | no; una inserción | 1 | 0.73 s |
| `test2.jpg` | `96819216` | sí | 1 | 4.87 s |

Exactitud estricta de OCR bruto: **1/4 (25%)**. El benchmark es deliberadamente pequeño y
difícil; no debe interpretarse como precisión general del sistema.
La similitud media por caracteres es **77.5%**; esta métrica muestra el avance
de los casos aproximados, pero no sustituye la coincidencia exacta del código.
En los cuatro casos de texto natural se encontraron **16 de 18 fragmentos
esperados (88.9%)**, preservando el texto detectado como líneas y bloque
multilinea. La métrica de texto no se mezcla con la exactitud estricta de código.

Tres de estas placas ya cuentan con una corrección humana guardada. En una
reejecución del mismo archivo y `bbox`, la memoria supervisada eleva el resultado
efectivo a **4/4 (100%)**. Este valor mide que el sistema no olvida trabajo ya
revisado; no se reporta como exactitud sobre fotografías nuevas. El JSON y el
dashboard exponen por separado `exactitud_ocr_bruta` y `exactitud_efectiva`.

## Hallazgos

- La imagen original funciona mejor que la binarización como primera pasada en
  fotografías reales.
- Los códigos formados únicamente por dígitos deben considerarse evidencia
  válida. Este ajuste convirtió `test2.jpg` de una lectura errónea tras 16
  intentos y 72.55 s a una lectura exacta en un intento y 3.89 s.
- Restringir EasyOCR al alfabeto usado por códigos reduce símbolos espurios,
  aunque no resuelve por sí solo el relieve curvo.
- La detección MSER, el recorte con contexto y la ampliación redujeron `IBC20`
  de 16–20 intentos a 2 y `GCC10` de 4–5 intentos a 2. Las lecturas restantes
  (`IBCZI`, `GCCIO`) exponen confusiones que el aprendizaje confirmado puede
  corregir cuando acumule soporte.
