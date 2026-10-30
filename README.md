# OCR Versuchsmatrix

# Sistema local de OCR y validación de pruebas

Aplicación local para recorrer lotes de fotografías, extraer nomenclaturas con
OCR, comparar etiquetas contra imágenes de referencia, generar un Excel maestro
y consultar los resultados desde un dashboard responsivo.

> **Versión V16.0.2 · 2026-10-19.** Cambio formal de numeración a partir de R15.9.1, conservando el mismo motor OCR, lógica de apertura, Tmax, semáforo y generación Excel.
> El **paquete ACUMULATIVO V16** permite actualizar directamente instalaciones verificadas desde R15.6 hasta R15.9.1. No es el instalador incremental antiguo.
> Las mejoras históricas de R15.9.1 (integridad, recuperación y durabilidad) se mantienen. Consulta su historial en `docs/informes/CHANGELOG_R15_9.md`.
> Sigue pendiente la validación de campo con Windows, GPU y videos reales; el cambio de nombre no certifica producción.

El procesamiento no utiliza APIs de OCR ni servicios en la nube. EasyOCR es el
motor de producción: se mantiene una sola instancia por ejecución y usa
CUDA/MPS cuando están disponibles, con CPU como respaldo seguro.

## Corrección específica V16.0.2 (semáforo)

Sobre V16.0.1 verificada, aplica `INSTALAR_V16_0_2_SEMAFORO.bat` del paquete
correspondiente, con V-Matrix detenido, respaldo y comprobación de hashes.
No se usa para instalar sobre R15.x o instalaciones híbridas. Corrige la
proyección de estimaciones automáticas y la coherencia matriz-resumen, sin
transformar estimaciones en mediciones finales ni tocar los algoritmos OCR/video.
Los resultados anteriores de R15 son historia y la precisión de estimaciones
no está certificada con ground truth de video.

## Actualización acumulativa a V-Matrix V16.0.1

El instalador anterior `INSTALAR_V16_0_1.bat` requería R15.9.1 y NO debe usarse para una base R15.8. Utiliza solamente `INSTALAR_V16_ACUMULADO.bat` del paquete acumulativo.

V16.0.1 sucede a V15.10.1 R15.9.1 y conserva el mismo motor de análisis. Esta entrega de reparación V16.0.1 está basada en el diagnóstico real del 2026-10-19; no es un instalador universal. Consulte INSTRUCCIONES_V16_0_1.md antes de instalar. No es necesario aplicar cada parche intermedio. **No extraigas ni copies manualmente el parche encima de archivos activos**: ejecuta `INSTALAR_V16_ACUMULADO.bat` con la aplicación cerrada y con respaldo de tus datos.

- Identidad V16.0.2: `VERSION.txt` = `16.0.2`, `PATCH_BUILD` = `16.0.2`, caché estática `?v=16.0.2`. El texto V16.0.1 restante explica la instalación anterior.
- Comprobación de instalación: `INSTALAR_V16_ACUMULADO.bat --verify-only` solamente **después de instalar V16**.
- El instalador verifica integridad, estado exacto del origen, cierre de procesos, crea respaldo y revierte archivos si falla.
- La evidencia de R15 queda como historial. No se declara listo para producción sin Windows real, rollback, GPU y videos reales con tiempos de referencia.

## Documentación organizada

La raíz conserva este README, los lanzadores, la configuración y los archivos
necesarios para instalar/ejecutar. Las notas y los informes están agrupados en
[el índice de documentación](docs/README.md):

- [Guías actuales](docs/guias/): instalación y funciones (histórico V15.8; la
  instalación vigente de V16.0.1 es `INSTALAR_V16_0_1.bat`, ver [informes](docs/informes/)).
- [Informes y pruebas](docs/informes/): validación y aplicación de actualizaciones.
- [Historial](docs/historial/): notas de versiones anteriores.
- [Parches históricos](docs/historial/parches/): instrucciones antiguas conservadas
  como referencia, no como pasos para aplicar a la versión actual.

## Funciones principales

- Descubrimiento recursivo de carpetas sin asumir profundidad fija.
- Flujo empresarial por ID para proyectos 1ST/2ST, con fallback legacy por caso.
- Recorrido exclusivo de `PHOTOS/NACH`, `PHOTOS/VOR` y `TOR X` cuando la estructura es válida.
- Pre-detección CRAFT en miniatura, descarte rápido sin texto y OCR sólo de recortes ampliados.
- Consolidación de todas las fotos del mismo ID y trazabilidad de cada evidencia.
- Detección de nombres conformes y carpetas anómalas.
- OCR sobre imágenes completas con deskew, binarización y QR opcional.
- Detección de regiones, cuatro orientaciones y realce de texto grabado.
- Giro manual de ángulo libre, con prioridad explícita sobre la orientación automática.
- Zoom visual separado del recorte/zoom OCR que vuelve a analizar una región real.
- Detección automática y extensible de plantilla según la estructura del lote.
- Clasificación visible de códigos útiles y descarte explicable de frases o valores espurios.
- Selección automática CUDA/MPS/CPU con fallback seguro y CPU para preprocesamiento.
- SOP V14: preparación CPU/lectura anticipada con cola RAM acotada y backpressure.
- Perfiles Estable/Alto/Máximo (ALTO por defecto) con límites orientativos de CPU/RAM/VRAM.
- Batch EasyOCR adaptativo con histéresis, reducción ante OOM y fallback temporal por tarea sin abandonar CUDA.
- Reanudación idempotente con `ejecucion_id`: un doble clic no lanza dos ejecuciones.
- Aprendizaje incremental por imagen: observaciones confirmadas antes de pausar/detener.
- Aprendizaje incremental supervisado con versiones, evaluación y rollback.
- Dataset visual auditable y entrenamiento EasyOCR por lotes, separado del OCR normal.
- Comparación etiqueta ↔ referencia por tokens alfanuméricos.
- Semáforo configurable desde YAML.
- Excel maestro con estructura completa y matriz de cumplimiento.
- Dashboard local con resumen, listado, detalle y procesamiento de carpetas.
- Progreso por imagen, ETA calibrada, pausa/continuación y advertencias legibles.
- Analizador general de libros Excel, hojas, columnas y categorías.
- Tema claro/oscuro y diseño para escritorio, tablet y móvil.

## Requisitos

- Windows 10/11, macOS o Linux de 64 bits.
- Python **3.12** recomendado y verificado.
- 8 GB de RAM como mínimo; 16–32 GB recomendados para lotes grandes.
- Espacio libre para dependencias y modelos OCR (aproximadamente 1–2 GB).
- Internet durante la primera instalación y la primera descarga de modelos.
  Después, el OCR puede ejecutarse localmente sin internet.

No copies entornos virtuales entre sistemas operativos. Cada máquina debe crear
su propio `.venv` e instalar las dependencias desde `requirements.txt`.

## Instalación

La opción recomendada detecta el sistema y prepara un entorno completo:

- macOS/Linux: doble clic en `instalar.command` o ejecuta
  `./instalar.command`.
- Windows: doble clic en `instalar.bat`.
- Cualquier sistema: `python instalar.py --perfil completo`.

El instalador elige una sola distribución compatible de PyTorch: CUDA para una
NVIDIA soportada, Metal/MPS en Apple Silicon o CPU como respaldo. La rueda
acelerada también ejecuta operaciones en CPU; instalar dos paquetes `torch`
distintos en el mismo entorno no es posible ni necesario. Consulta
`docs/instalacion_multiplataforma.md` para diagnóstico y recuperación.

Para revisar lo que hará sin instalar:

```bash
python instalar.py --solo-diagnostico
python instalar.py --simular
```

### Instalación manual

### 1. Clonar el repositorio

```bash
git clone https://github.com/OsirisSG/OCR-Validacion-Excel.git
cd OCR-Validacion-Excel
```

Si ya tienes configuradas llaves SSH en GitHub, también puedes clonar con
`git@github.com:OsirisSG/OCR-Validacion-Excel.git`.

### 2. Crear un entorno virtual

macOS o Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Windows CMD:

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate.bat
```

### 3. Instalar dependencias

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

La primera ejecución de EasyOCR descargará sus modelos de detección y
reconocimiento al caché del usuario. Esa descarga ocurre una sola vez.

### Motor OCR

EasyOCR permite una instalación base por CPU sin exigir una GPU concreta. Con
`fase1.dispositivo: auto`, el sistema usa CUDA, después MPS (Apple Silicon) y
finalmente CPU. La inferencia neuronal corre en el acelerador y OpenCV, QR y la
preparación geométrica usan la CPU. No es necesario instalar PaddleOCR.

### Dependencias opcionales

La instalación base contiene únicamente lo necesario para ejecutar el pipeline,
generar el Excel y abrir el dashboard. Las mejoras futuras están separadas para
no convertir cada instalación en un entorno pesado:

| Archivo | Capacidades preparadas |
| --- | --- |
| `requirements-formats.txt` | HEIC/HEIF, RAW, secuencias y PDF (los videos siguen excluidos del OCR) |
| `requirements-quality.txt` | calidad de imagen, similitud difusa y análisis |
| `requirements-training.txt` | aumentación, métricas y seguimiento de entrenamiento |
| `requirements-production.txt` | telemetría, CLI, rendimiento y ejecutables |

Instala solamente los grupos que necesites:

```bash
python -m pip install -r requirements-formats.txt
python -m pip install -r requirements-quality.txt
python -m pip install -r requirements-training.txt
python -m pip install -r requirements-production.txt
python -m pip check
```

`requirements-complete.txt` referencia todos los grupos funcionales. El
instalador automático lo hace por etapas para colocar primero la rueda correcta
de PyTorch y verificar el acelerador al final.

Estas dependencias preparan el entorno, pero no habilitan automáticamente una
función: cada mejora debe integrarse en el código, probarse y documentarse.

### Bloqueo de versiones por plataforma

Los archivos `requirements*.txt` usan rangos para conservar compatibilidad entre
Windows, macOS y Linux. Cuando necesites congelar un entorno ya verificado,
genera el lock desde esa misma máquina:

```bash
python -m pip check
python -m pip freeze > requirements-lock.txt
```

Registra junto al lock el sistema operativo, la arquitectura, la versión de
Python y, si aplica, CUDA. Un lock generado en macOS ARM64 o en Windows con GPU
no debe presentarse como universal; las ruedas de PyTorch y varios
paquetes de imagen dependen de la plataforma.

## Inicio rápido con los datos sintéticos

Si tu copia incluye `datos_prueba/`, ese conjunto es artificial y no contiene datos
empresariales. El ZIP de corrección no necesita esos fixtures para funcionar. Desde la
raíz del proyecto puedes ejecutar:

```bash
python pipeline.py "datos_prueba/Lote_Pruebas"
```

El comando ejecuta:

1. Fase A: inventario persistente, sin cargar EasyOCR.
2. Fase B: QR, detección, zoom/ROI, OCR y consolidación.
3. Generación del Excel y cola de revisión.

Produce localmente:

- `estructura_detectada.json`
- `inventario_proyecto.json`
- `validacion_resultados.json`
- `resultado_maestro.xlsx`

Para una estructura empresarial, el sistema busca automáticamente una plantilla
compatible en la biblioteca local `.plantillas/`, en la raíz, en `plantillas/`,
en la carpeta superior y en las rutas configuradas. Desde **Procesar carpeta**
se pueden registrar contratos XLSX independientes y asociarles tipo 1ST/2ST y
marcadores de ruta. Cada archivo conserva sus propias columnas, diccionario,
catálogos, validaciones y formato; nunca se combinan contratos. Si no hay una
coincidencia inequívoca se usa el formato integrado o una selección explícita.
`--plantilla` sigue disponible para scripts:

```bash
python pipeline.py "/ruta/Proyecto_1ST" \
  --plantilla "/ruta/728c57b2-46cc-42f9-99fd-d23a6fcaab82.xlsx" \
  --excel resultado_1st.xlsx
```

El tipo 1ST/2ST se detecta en la ruta, carpetas superiores e hijas inmediatas.
Si no aparece, usa `--tipo-st 1ST`, `--tipo-st 2ST` o `--tipo-st LEGACY`.
El Excel empresarial conserva las hojas de la plantilla, escribe una fila por ID
en `Captura_pruebas` y añade `Trazabilidad_OCR`, una fila por fotografía.

También puedes separar el trabajo:

```bash
python pipeline.py "/ruta/Proyecto_1ST" --modo inventario
python pipeline.py "/ruta/Proyecto_1ST" --modo reanudar --inventario inventario_proyecto.json
```

El caché reanudable queda en `.cache_ocr/imagenes.sqlite3` (transacciones y WAL;
la primera apertura importa el JSON histórico). Las reglas empresariales
se guardan en `base_conocimiento.json`: nacen como propuestas después de tres IDs
y 90 % de consenso, y sólo rellenan campos después de confirmarse. Las memorias
OCR supervisadas existentes continúan en `.aprendizaje/aprendizaje.sqlite3`.

Estos artefactos se regeneran y no se versionan porque contienen rutas absolutas
del equipo que ejecutó el pipeline.

El contrato funcional consolidado vive en `docs/documento_maestro.md`.

## Ejecutar el dashboard

La forma más sencilla detecta el sistema, el entorno virtual y el acelerador
disponible, muestra un diagnóstico y abre el navegador:

- macOS/Linux: doble clic en `iniciar.command` o ejecuta `./iniciar.command`.
- Windows: doble clic en `Iniciar_OCR.bat`. Crea `.venv_ocr` sólo si hace falta,
  comprueba el puerto y espera a que `/api/estado` responda.
- Cualquier sistema: `python iniciar.py`.

También se puede usar el arranque directo con el entorno virtual activado:

```bash
python dashboard/backend/app.py
```

Opciones de Windows:

```powershell
.\iniciar_ocr.ps1 -SinAbrir
.\iniciar_ocr.ps1 -Diagnostico
```

Las correcciones marcadas “Confirmar para el próximo lote” se guardan como
recortes en `.aprendizaje/dataset_visual/recortes`. Una edición individual sólo
se guarda en la cola; nunca dispara entrenamiento. El botón “Entrenar lote
visual” habilita el ajuste a partir de 100 recortes confirmados de al menos 15
IDs (idealmente 300+ variados), separando entrenamiento, validación y prueba por
ID. Registra CER, WER y exactitud por campo; un candidato sólo puede activarse si
mejora sin degradar el conjunto de prueba y siempre admite rollback.

Abre en el navegador:

```text
http://127.0.0.1:8000/
```

El dashboard ofrece tres vistas principales:

- **Resumen:** KPIs y distribución del semáforo.
- **Listado:** bandeja única con carpetas y pruebas complejas, búsqueda, estado
  de revisión (`Por revisar`, `Revisión parcial`, `Casi listo`, `Completada`),
  acciones para completar/reabrir y eliminación reversible.
- **Detalle:** todas las imágenes de la carpeta, texto completo con su layout y
  corrección de tokens, líneas o bloques multilinea. También permite dibujar una
  región y transcribir texto que el OCR omitió por completo. Al elegir una imagen
  de la lista inferior, un solo clic abre el visor y activa su edición. El giro
  manual de cualquier ángulo se previsualiza mientras se mueve el control y sólo
  se guarda al pulsar **Aplicar giro**. Esa decisión —incluso 0°— tiene prioridad
  sobre el enderezado automático; **Usar automático** elimina esa prioridad. También muestra la lista
  conjunta de correcciones y textos omitidos usados como aprendizaje supervisado.
- **Procesar carpeta:** ejecuta las Fases 0–3 desde una ruta local, acepta la ruta
  con o sin comillas, permite nombrar el Excel, elegir si se sobrescribe el
  archivo existente y pausar/continuar entre imágenes. Al detener ofrece
  continuar, conservar el avance de inmediato o terminar el ID actual. El
  checkpoint, los resultados parciales y el caché permiten reanudar sin repetir
  OCR de imágenes que no cambiaron. Al pausar después de una imagen o detener al
  terminar un ID también genera `*_parcial.xlsx`, visible desde el panel, con los
  IDs terminados y el avance consolidable del ID activo. Si no se autoriza
  sobrescribir, crea automáticamente `nombre_1.xlsx`, `nombre_2.xlsx`, etc.
  Las últimas diez direcciones y su nombre de Excel se conservan localmente en
  el navegador para poder seleccionarlas en ejecuciones posteriores.

Las pruebas complejas ya no viven en una pestaña aislada: aparecen en el mismo
Listado y abren su propio detalle con el mismo estuche de revisión de las
carpetas normales. Se puede seleccionar un renglón, pulsar su caja directamente
sobre la imagen, dibujar una región omitida, transcribirla, girar la fotografía,
consultar el historial supervisado y enviar tanto OCR como texto manual al Excel.

El **zoom de vista** sólo amplía la fotografía en pantalla y no altera el OCR. El
**zoom OCR** permite recortar una región de interés y volver a procesar únicamente
esa zona; ese recorte sí cambia la lectura. El detalle prioriza una lista deduplicada
de códigos útiles. Las frases, unidades sueltas y fragmentos sin estructura quedan
en las lecturas completas plegables y cada descarte muestra una regla comprensible.
La rueda, los botones, el arrastre y el doble clic controlan el visor. La acción
**Imagen sin datos de texto** registra una revisión humana válida —con motivo
opcional— sin convertirla en un fallo del OCR.

El editor de correcciones incluye una previsualización compacta de la imagen
asociada. Sus controles `+`/`−`, rueda, restablecimiento y paneo amplían al mismo
tiempo la fotografía y las cajas OCR; por ello seleccionar una caja conserva las
coordenadas originales. El panel mantiene juntos imagen, OCR original y texto
confirmado.

Los JSON operativos se escriben mediante un único escritor seguro. Usa un
temporal único por hilo/proceso, `flush` + `fsync`, reemplazo atómico, bloqueo
`RLock` por destino y ocho reintentos progresivos ante archivos ocupados en
Windows. Si un caché sigue bloqueado, conserva la última versión válida, muestra
una advertencia separada y continúa el OCR con el avance en memoria.

Para un lote grande, usa una ruta local en **Procesar carpeta**. Los archivos no
se suben ni se duplican en el navegador. Durante la ejecución aparecen un reloj
fluido, porcentaje por imagen, carpetas e imágenes pendientes, tiempo estimado
recalculado y cada resultado ya terminado.

La ETA ignora la inicialización costosa del primer modelo y usa la mediana de las
últimas imágenes. Por eso no extrapola el calentamiento inicial como si se
repitiera en todo el lote. En la prueba local de referencia del 31-08-2026,
13 imágenes finalizaron en 35 segundos usando MPS y 8 hilos CPU.

El puerto se cambia en `config.yaml`:

```yaml
dashboard:
  puerto: 8000
```

## Procesar datos reales

Se recomienda mantener los datos reales fuera del repositorio:

```bash
python pipeline.py "/ruta/al/lote"
```

En Windows:

```powershell
python pipeline.py "D:\Lotes\Lote_2026_08"
```

También puedes iniciar el dashboard, abrir **Procesar carpeta** y pegar esa ruta.

No publiques fotografías, Excel generados o JSON de resultados sin revisar si
contienen rutas locales o información confidencial.

## Analizar la estructura de cualquier Excel

Para inventariar todas las hojas y columnas de un libro desconocido:

```bash
python analizar_excel.py "/ruta/al/archivo.xlsx"
```

El comando no modifica el Excel. Genera `<archivo>_analisis_excel.json` con la
fila probable de encabezados, tipos de datos, vacíos, fórmulas, categorías
observadas, muestras y posibles nombres canónicos de cada columna.

Si el archivo contiene información sensible, omite las muestras:

```bash
python analizar_excel.py archivo.xlsx --sin-muestras
```

Consulta el contrato completo en `docs/analizador_excel.md`.

## Reglas del semáforo

Se configuran en `reglas_cumplimiento.yaml`:

```yaml
criterios:
  confianza_ocr:
    verde: ">= 90"
    amarillo: "70-89"
    rojo: "< 70"
  coincidencia_texto:
    verde: "coincidencia_total"
    amarillo: "coincidencia_parcial"
    rojo: "discrepancia,sin_referencia"
```

El estado global es el color más restrictivo de los criterios evaluados. Los
mismos hex se utilizan en Excel y dashboard.

## Aprendizaje incremental

Cada ejecución registra observaciones localmente. Desde el detalle del dashboard
se puede confirmar una corrección y su recorte exacto; el entrenamiento se inicia
únicamente por lote y un candidato sólo se puede activar si mejora los conjuntos
de validación y prueba. Las predicciones no confirmadas no se usan como verdad.

La base y las versiones se guardan en
`.aprendizaje/aprendizaje.sqlite3`; las fotografías no se copian. La supervisión
puede bajar cuando se repiten confusiones ya confirmadas, pero una mera ejecución
sin corrección humana no entrena al sistema ni garantiza menos revisión.

La misma corrección supervisada está disponible en **Pruebas complejas**. Las
imágenes externas se guardan localmente en `.pruebas_externas/`, fuera de Git.

```bash
python aprendizaje.py estado
```

Consulta el diseño, los umbrales y el rollback en
`docs/aprendizaje_incremental.md`.

## Configuración

Los parámetros viven en:

- `config.yaml`: motores, preprocesamiento, extensiones, referencia y dashboard.
- `reglas_cumplimiento.yaml`: umbrales del semáforo.

No fijes nuevos umbrales directamente en Python o JavaScript. Añádelos al YAML y
documenta el valor por defecto.

## Pruebas

Instala las dependencias de desarrollo:

```bash
python -m pip install -r requirements-dev.txt
```

Este grupo incluye `pytest`, cobertura, `ruff`, `mypy` y `pre-commit`.

Contratos del dashboard:

```bash
python -m pytest -q pruebas/test_dashboard.py
```

Casos obligatorios del OCR (la primera ejecución puede descargar modelos):

```bash
python pruebas/prueba_fase1_casos.py
```

Verificación del Excel:

```bash
python pruebas/verificar_excel.py
```

## Estructura del proyecto

```text
OCR-Validacion-Excel/
├── estructura.py                 # Fase 0
├── ocr_engine.py                 # Fase 1
├── validacion.py                 # Fase 2
├── generar_excel.py              # Fase 3
├── analizar_excel.py             # Inventario de libros Excel
├── aprendizaje.py                # Modelo incremental, versiones y rollback
├── pipeline.py                   # Orquestador Fases 0–3
├── configuracion.py              # Configuración y reglas compartidas
├── config.yaml
├── reglas_cumplimiento.yaml
├── instalar.py                  # Instalación CPU/CUDA/MPS autodetectada
├── instalar.command / .bat      # Lanzadores de instalación
├── requirements.txt              # Ejecución portable
├── requirements-complete.txt     # Todos los grupos funcionales
├── requirements-dev.txt          # Pruebas y calidad de código
├── requirements-formats.txt      # Formatos extendidos opcionales
├── requirements-quality.txt      # Calidad y similitud opcionales
├── requirements-training.txt     # Entrenamiento opcional
├── requirements-production.txt   # Operación y empaquetado opcionales
├── dashboard/
│   ├── backend/app.py
│   └── frontend/
├── datos_prueba/                 # Fixtures sintéticos publicables
├── pruebas/
├── docs/
│   ├── README.md                 # Índice de documentación
│   ├── guias/                    # Instalación y versión actual
│   ├── informes/                 # Resultados de pruebas y actualizaciones
│   ├── historial/                # Notas anteriores y parches archivados
│   └── fase*.md                  # Documentación técnica por fase
└── errores/                      # Bitácoras técnicas curadas
```

## Reporte BMG 1ST + 2ST (V7)

La V7 conserva el flujo OCR/corrección por giro de V6 y añade un reporte BMG
basado en `plantillas/reporte_bmg_1st_2st.xlsx`. El mismo libro reúne 1ST y
2ST, mantiene `Versuchsmatrix` como listado detallado y presenta en
`Übersicht Standversuche` una matriz por temperatura/tipo de inflador.

El color de cada número de prueba representa exclusivamente el tiempo de
apertura (`opening_time_ms`): verde hasta 6 ms inclusive, amarillo por encima
de 6 y hasta 7 ms inclusive, rojo por encima de 7 ms y gris cuando el dato no
existe o requiere revisión. En el dashboard, las celdas de la matriz del
Resumen llevan a la fila correspondiente de Listado; en el Excel generado,
las celdas del resumen enlazan a la fila de `Versuchsmatrix`.

Consulta [LEEME_MATRIZ_APERTURA_V7.md](docs/historial/LEEME_MATRIZ_APERTURA_V7.md) para el detalle de reglas, capacidad y
archivos modificados.

## Limitaciones actuales

- El flujo legacy conserva su comparación etiqueta/referencia. El empresarial
  consolida todas las fotografías del ID y contrasta ruta, QR y OCR.
- HEIC/HEIF, RAW, PDF y GIF animado requieren conversión previa.
- Texto manuscrito complejo, superficies curvas, reflejos y desenfoque pueden
  requerir datos propios y fine-tuning.
- Solo se permite una ejecución simultánea del pipeline desde el dashboard.
- Por ahora los videos se inventarían y se advierten, pero nunca se envían al OCR.
- El entrenamiento visual necesita suficientes recortes confirmados de IDs
  distintos; antes de ese umbral permanece correctamente en espera.

## Documentación para mantenimiento

Antes de modificar una fase, consulta:

- [Índice de documentación](docs/README.md)
- `docs/fase0_autodescubrimiento.md`
- `docs/fase1_ocr.md`
- `docs/fase2_validacion.md`
- `docs/fase3_excel.md`
- `docs/fase4_dashboard.md`
- `docs/instalacion_multiplataforma.md`
- `docs/aprendizaje_incremental.md`

Cada cambio debe conservar los contratos de entrada/salida, actualizar el
Markdown de su fase y registrar en `errores/` cualquier enfoque fallido antes de
cambiar de estrategia.

## Solución de problemas

### PowerShell bloquea la activación del entorno virtual

Primero intenta activar el entorno normalmente:

```powershell
.\.venv\Scripts\Activate.ps1
```

Si PowerShell indica que la ejecución de scripts está deshabilitada, puedes
permitirla únicamente durante la sesión actual:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

El alcance `Process` es temporal: el cambio desaparece al cerrar esa ventana de
PowerShell. `Iniciar_OCR.bat` ya aplica únicamente este alcance y no modifica la
política permanente del equipo.

### “Ningún motor de OCR disponible”

Activa el entorno correcto y reinstala:

```bash
python -m pip install -r requirements.txt
```

Comprueba EasyOCR:

```bash
python -c "import easyocr; print(easyocr.__version__)"
```

### El dashboard indica “Entorno OCR incompleto”

El dashboard debe arrancarse desde el mismo entorno donde instalaste OpenCV,
openpyxl y EasyOCR. Detén el servidor, activa `.venv` y vuelve a
ejecutar `python dashboard/backend/app.py`.

### El puerto 8000 está ocupado

Cambia `dashboard.puerto` en `config.yaml` o detén el proceso anterior.

### El dashboard no muestra resultados

Ejecuta primero `python pipeline.py <ruta>` o utiliza **Procesar carpeta**. Al
terminar, vuelve a Resumen.

### Rutas de Windows mostradas en otro equipo

Vuelve a ejecutar el pipeline en la máquina actual. Los JSON y el Excel son
artefactos locales y no deben copiarse como fuente de datos entre equipos.

## Seguridad y publicación

- El servidor escucha únicamente en `127.0.0.1` y no incluye autenticación.
- No lo expongas directamente a internet.
- Mantén datos empresariales, credenciales, modelos y artefactos generados fuera
  de Git; `.gitignore` ya excluye sus ubicaciones habituales.
- Revisa `git status` antes de cada commit.

### V9 · estabilidad del editor y experiencia de revisión

V9 corrige traducciones dinámicas y contraste oscuro, agrega notificaciones flotantes de actividad, evita que una respuesta tardía devuelva el editor a una corrección anterior, corrige el falso aviso de borrador tras un guardado confirmado, permite ajustar/dividir bloques que se superponen con anotaciones manuales sin borrar esas anotaciones y añade descarte múltiple. Guardar una corrección no entrena el OCR por sí solo; el entrenamiento visual se propone explícitamente y se ejecuta por lote. También se añadieron caché de variantes de orientación y agrupación de actualizaciones de Excel. Consulta [LEEME_V9_ESTABILIDAD_UI.md](docs/historial/LEEME_V9_ESTABILIDAD_UI.md).

### R15.9.1 · revisión de auditoría y endurecimiento del registro

R15.9 cierra los tres bloqueadores y los dos medios que la auditoría
independiente de R15.8 reprodujo (`AUDITORIA_INDEPENDIENTE_R15_8_20261018.md`)
sin funciones nuevas y sin tocar OCR, Tmax, semáforo ni Excel:

* **ALTO-01** — el verificador de importaciones del instalador compara el
  `PATCH_BUILD` del árbol con la versión pasada por ARGUMENTO (el literal
  R15.7 que hacía fallar toda instalación correcta con exit 33 ya no existe);
  la suite ejecuta el snippet real extraído del instalador.
* **ALTO-02** — contrato de BASE ÍNTEGRA: el instalador declara su contrato
  real (parche incremental sobre R15.7/R15.8) y verifica el HASH de cada
  archivo clave de los releases base antes de copiar; un árbol híbrido
  aborta sin modificar nada.
* **ALTO-03** — la sonda guarda un RESPALDO DURABLE del registro (fsync +
  replace + relectura) ANTES de sustituirlo y el arranque lo recupera
  (`_leer_registro_o_respaldo`): un corte abrupto durante la sonda ya no
  puede perder las entradas del historial de anomalías.
* **MEDIO-04** — la sonda opera a nivel de BYTES: un registro con CRLF o BOM
  sale con el mismo SHA-256 (antes la restauración en modo texto lo
  normalizaba).
* **MEDIO-05** — el soak sólo acepta el terminal de la ejecución pedida: un
  activo/terminal de otra ejecución (o sin id) es evidencia inconclusa y se
  sigue esperando.
* **BAJO-06** — marker del instalador sin duplicados y mensaje de base
  alineado con el contrato real.

Detalle: [CHANGELOG_R15_9.md](docs/informes/CHANGELOG_R15_9.md),
[INFORME_R15_9_POR_HALLAZGO.md](docs/informes/INFORME_R15_9_POR_HALLAZGO.md) y
[MATRIZ_EVIDENCIA_R15_9.md](docs/informes/MATRIZ_EVIDENCIA_R15_9.md).

### R15.8 · cierre del perímetro de recuperación

R15.8 cierra los ocho huecos reproducidos por la revalidación independiente de
R15.7 (`AUDITORIA_REVALIDADA_R15_7_20261016.md`) sin funciones nuevas y sin
tocar OCR, Tmax, semáforo ni Excel:

* **ALTO-01** — la sonda de arranque escribe sobre el TARGET REAL del registro
  (`estado_inconsistente.json`), prueba el reemplazo y restaura el contenido
  previo verificado; un target no regular/no reemplazable ⇒ MODO RECUPERACIÓN.
* **ALTO-02** — las rutas heredadas RELATIVAS se resuelven contra
  `datos["raiz"]` (con confinamiento) y la migración canónica se persiste: un
  bloqueo pre-upgrade sigue bloqueando al caso en todas las pantallas.
* **ALTO-03** — guard TRANSVERSAL de recuperación: ningún endpoint
  POST/PUT/PATCH/DELETE ejecuta en MODO RECUPERACIÓN; el test contractual
  obliga a declarar la política de cada ruta (exenciones declaradas: el propio
  flujo de recuperación y pausar/cancelar el pipeline).
* **ALTO-04 / MEDIO-05** — `revisiones` y `alertas/atender` respetan el
  bloqueo canónico del caso.
* **MEDIO-06** — el listado de recuperación deduplica aliases (un incidente =
  una entrada, con sus `claves`).
* **MEDIO-07/08** — soak ligado al `ejecucion_id` del POST, acepta la
  finalización antes del primer sondeo y reinicia su estado por iteración.
* **BAJO-09/10/11** — README raíz identifica R15.8, mensajes del instalador
  derivados de una única variable de versión y runbook sin conteo fijo de
  integridad. Definición formal: «Tmax» = tiempo de apertura publicado.

Detalle: [CHANGELOG_R15_8.md](docs/informes/CHANGELOG_R15_8.md),
[INFORME_R15_8_POR_HALLAZGO.md](docs/informes/INFORME_R15_8_POR_HALLAZGO.md) y
[MATRIZ_EVIDENCIA_R15_8.md](docs/informes/MATRIZ_EVIDENCIA_R15_8.md).

### R15.7 · endurecimiento de recuperación y concurrencia

R15.7 cierra los cuatro huecos reproducidos por la auditoría independiente de
R15.6 (`AUDITORIA_INDEPENDIENTE_R15_6_20261016.md`) sin funciones nuevas y sin
tocar OCR, Tmax, semáforo ni Excel:

* **ALTO-01** — el éxito de una transacción ya no resuelve inconsistencias: sólo
  el flujo formal de recuperación levanta un bloqueo.
* **ALTO-02** — identidad canónica de recursos (`carpeta:<id>`,
  `carpeta:<id>#imagen:<id>`, `carpeta:<id>#video:<id>`, `externa:<id>`): el
  bloqueo del caso alcanza todas sus pantallas y los registros R15.6 con rutas
  se migran conservando el alias.
* **ALTO-03** — sonda obligatoria de escritura/lectura al arrancar y centinela
  de recuperación en dos ubicaciones: sin almacén durable el sistema arranca en
  MODO RECUPERACIÓN aunque no exista centinela.
* **MEDIO-04** — las tareas posteriores al commit (uniones guardadas,
  entrenamiento visual) son best-effort y se reportan como
  `advertencia_aprendizaje`, nunca como error.
* **MEDIO-05** — CAS estricto en writers humanos de pruebas externas; la UI
  envía `expected_revision` y recarga ante 409.
* **BAJO-06/07** — `utilidades/inventario_destino.py` inventaría el árbol
  destino tras el upgrade y la resolución de recuperación verifica la
  eliminación del centinela.

Detalle: [CHANGELOG_R15_7.md](docs/informes/CHANGELOG_R15_7.md),
[INFORME_R15_7_POR_HALLAZGO.md](docs/informes/INFORME_R15_7_POR_HALLAZGO.md) y
[MATRIZ_EVIDENCIA_R15_7.md](docs/informes/MATRIZ_EVIDENCIA_R15_7.md).


### Identidad de revisión del parche de recuperación

La revisión de auditoría de 2026-10-19 se identifica de forma inequívoca como
`15.10.1-r15.9.1` en `VERSION.txt`, `PATCH_BUILD`, caché frontend y marker
de instalación. No debe confundirse con los ZIP previos `15.10.1-r15.9`.
