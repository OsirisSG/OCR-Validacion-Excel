# Aprendizaje incremental y visual seguro

## Qué aprende

Cada pipeline registra localmente las lecturas OCR, confianza, caja, motor,
imagen y ejecución en `.aprendizaje/aprendizaje.sqlite3`. Una observación sin
confirmar **no modifica el modelo**. El entrenamiento comienza cuando una
persona corrige un código desde el detalle del dashboard o mediante CLI.

Las correcciones alimentan dos capas distintas:

1. Correcciones exactas recurrentes, por ejemplo `K001 → GCC10`.
2. Confusiones de caracteres respaldadas por un patrón confirmado, como
   `O/0`, `I/1` o `Z/2`.

Una corrección exacta necesita aparecer en al menos dos imágenes distintas. Una
confusión general necesita tres evidencias y un patrón correcto repetido. Estos
umbrales viven en `config.yaml → aprendizaje`.

Hay una excepción segura que no generaliza: si se vuelve a procesar exactamente
el mismo archivo (mismo hash), texto y `bbox`, su corrección confirmada se
reutiliza desde la primera evidencia. Así una reejecución no vuelve a pedir la
misma supervisión, pero una fotografía nueva conserva los umbrales anteriores.

Por eso el aviso distingue dos hechos: **“corrección guardada”** significa que
ya se memorizará para el mismo archivo y región; **“regla global todavía no
activada”** significa que aún no hay evidencia suficiente para cambiar textos en
fotografías nuevas. No se perdió la corrección.

## Ciclo de una versión

```text
ejecución OCR
  → observaciones sin etiqueta
  → corrección humana y recorte en cola
  → lote mínimo de 100 recortes / 15 IDs
  → modelo candidato EasyOCR
  → comparación con modelo activo
  → promoción solo si mejora y no hay regresiones
  → historial + rollback
```

Una corrección individual nunca entrena. Para el reconocedor visual se requieren
por defecto 100 recortes confirmados procedentes de 15 IDs distintos; 300 o más
ejemplos variados es el objetivo recomendado. La separación determinista por ID
crea conjuntos de entrenamiento, validación y prueba sin fuga. Se calculan CER,
WER y exactitud global/por campo. El entrenamiento puede iniciarse después de
una revisión temprana de unos 15 IDs y continuar después en lotes de 20 y 50.

## Dashboard

En `Listado → Detalle` aparece **Corregir una lectura**. Se puede seleccionar
cualquiera de las imágenes de la carpeta y corregir un token, una línea o el
bloque completo, incluidos espacios y saltos. El backend verifica que la imagen
y el texto pertenezcan al lote procesado antes de registrar la corrección.

Toda corrección se conserva literalmente en `correcciones_texto`. Si solo cambia
el layout (espacios o renglones), queda como evidencia de tipo `layout` y no se
usa para entrenar sustituciones de códigos. Solo una diferencia alfanumérica
normalizada alimenta el modelo incremental de códigos.

Si el OCR no detectó ninguna unidad, el usuario puede dibujar una caja sobre la
imagen y transcribir su contenido. `anotaciones_regiones` conserva carpeta,
imagen, hash, coordenadas y texto real. La región se copia como PNG a
`.aprendizaje/dataset_visual/recortes`; alimenta el reconocedor EasyOCR, no el
detector CRAFT, y se reutiliza en el Excel sin fingir que ya generaliza.

La lista de aprendizaje supervisado del detalle muestra ambas clases de verdad
humana: correcciones de una lectura OCR y regiones de texto omitido. Las
orientaciones manuales se guardan en `rotaciones_imagen`; la próxima ejecución
rota primero el archivo y después conserva la búsqueda automática 0°/90°/180°/270°
y el ajuste fino de inclinación.

La tabla `revisiones` mantiene el flujo
`por_revisar → parcial → casi_listo → completada` para carpetas y pruebas
externas. `casi_listo` es una sugerencia automática de alta seguridad; solo una
persona marca `completada`. Quitar un elemento es una baja lógica reversible: no elimina
la fotografía, el JSON ni la evidencia aprendida.

## CLI

```bash
python aprendizaje.py estado
python aprendizaje.py corregir imagen.jpg K001 GCC10
python aprendizaje.py entrenar
python aprendizaje.py rollback
python aprendizaje.py rollback --version 20260830-120000-abcd1234-ef01
python aprendizaje.py exportar dataset_confirmado.jsonl
python entrenamiento_easyocr.py
```

## Privacidad y recuperación

- La base vive solo en el equipo y está excluida de Git.
- La ruta concreta es `.aprendizaje/aprendizaje.sqlite3`; las tablas `modelos`,
  `correcciones`, `correcciones_texto`, `anotaciones_regiones` y
  `rotaciones_imagen`, `muestras_visuales`, `modelos_visuales` e
  `imagenes_sin_datos` contienen el
  historial, las versiones y la evidencia confirmada.
- No se modifican ni duplican fotografías completas. Sólo se guardan los
  recortes confirmados que forman el dataset visual auditable.
- Todo token corregido mantiene `texto_original`, evidencia y versión del
  modelo en el resultado OCR.
- Una versión anterior puede reactivarse con rollback.
- Para respaldar el aprendizaje, copia la carpeta `.aprendizaje/` mientras el
  dashboard y el pipeline estén detenidos.

## Límite importante

El modelo no puede deducir por sí solo que una lectura es correcta. Entrenar con
su propia predicción convertiría errores en etiquetas falsas. Cada ejecución
aporta ejemplos para revisar; cada corrección confirmada aporta conocimiento.
Las regiones y correcciones confirmadas forman además un dataset visual
auditable. El entrenamiento EasyOCR se ejecuta por lotes y crea candidatos
versionados; nunca se ejecuta automáticamente después de cada corrección. Las
reglas de sustitución y conocimiento continúan como capas independientes.
