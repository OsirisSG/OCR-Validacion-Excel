# Sistema local de OCR y validación de pruebas

Aplicación local para recorrer lotes de fotografías, extraer nomenclaturas con
OCR, comparar etiquetas contra imágenes de referencia, generar un Excel maestro
y consultar los resultados desde un dashboard responsivo.

El procesamiento no utiliza APIs de OCR ni servicios en la nube. EasyOCR es el
motor portable instalado y seleccionado por defecto; PaddleOCR puede instalarse
por separado y seleccionarse en `config.yaml` cuando la plataforma lo soporte.

## Funciones principales

- Descubrimiento recursivo de carpetas sin asumir profundidad fija.
- Detección de nombres conformes y carpetas anómalas.
- OCR sobre imágenes completas con deskew, binarización y QR opcional.
- Detección de regiones, cuatro orientaciones y realce de texto grabado.
- Aprendizaje incremental supervisado con versiones, evaluación y rollback.
- Comparación etiqueta ↔ referencia por tokens alfanuméricos.
- Semáforo configurable desde YAML.
- Excel maestro con estructura completa y matriz de cumplimiento.
- Dashboard local con resumen, listado, detalle y procesamiento de carpetas.
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

### PaddleOCR opcional

EasyOCR permite una instalación base por CPU sin exigir PaddlePaddle, CUDA o una
GPU concreta. Si deseas evaluar PaddleOCR, instala PaddlePaddle y PaddleOCR
siguiendo las instrucciones oficiales correspondientes a tu sistema, CPU o GPU.
Después configura:

```yaml
fase1:
  motor: paddle
  motor_fallback: easyocr
```

Si PaddleOCR falla al inicializar, el sistema vuelve a EasyOCR. En Windows, el
adaptador ya desactiva MKLDNN para evitar el fallo de oneDNN registrado en
`errores/2026-08-23_paddle_onednn_windows.md`.

### Dependencias opcionales

La instalación base contiene únicamente lo necesario para ejecutar el pipeline,
generar el Excel y abrir el dashboard. Las mejoras futuras están separadas para
no convertir cada instalación en un entorno pesado:

| Archivo | Capacidades preparadas |
| --- | --- |
| `requirements-formats.txt` | HEIC/HEIF, RAW, secuencias, video y PDF |
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
no debe presentarse como universal; las ruedas de PyTorch, PaddlePaddle y varios
paquetes de imagen dependen de la plataforma.

## Inicio rápido con los datos sintéticos

El repositorio incluye `datos_prueba/`, generado artificialmente y sin datos
empresariales. Desde la raíz del proyecto ejecuta:

```bash
python pipeline.py "datos_prueba/Lote_Pruebas"
```

El comando ejecuta:

1. Fase 0: descubrimiento de estructura.
2. Fases 1–2: OCR y validación cruzada.
3. Fase 3: generación del Excel.

Produce localmente:

- `estructura_detectada.json`
- `validacion_resultados.json`
- `resultado_maestro.xlsx`

Estos artefactos se regeneran y no se versionan porque contienen rutas absolutas
del equipo que ejecutó el pipeline.

## Ejecutar el dashboard

Con el entorno virtual activado:

```bash
python dashboard/backend/app.py
```

Abre en el navegador:

```text
http://127.0.0.1:8000/
```

El dashboard ofrece cinco vistas:

- **Resumen:** KPIs y distribución del semáforo.
- **Listado:** bandeja única con carpetas y pruebas complejas, búsqueda, estado
  de revisión, acciones para completar/reabrir y eliminación reversible.
- **Detalle:** todas las imágenes de la carpeta, texto completo con su layout y
  corrección de tokens, líneas o bloques multilinea. También permite dibujar una
  región y transcribir texto que el OCR omitió por completo.
- **Procesar carpeta:** ejecuta las Fases 0–3 desde una ruta local.
- **Pruebas complejas:** muestra fotografías externas difíciles, sus métricas y
  permite confirmar correcciones para el aprendizaje supervisado.

Para un lote grande, usa una ruta local en **Procesar carpeta**. Los archivos no
se suben ni se duplican en el navegador. Durante la ejecución aparecen un reloj
fluido, porcentaje por imagen, carpetas e imágenes pendientes, tiempo estimado
recalculado y cada resultado ya terminado.

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

Cada ejecución registra ejemplos localmente. Desde el detalle del dashboard se
puede corregir una lectura; el sistema entrena un candidato y solo lo activa si
mejora los casos confirmados sin regresiones. Las predicciones no confirmadas no
se usan como verdad de entrenamiento.

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
├── requirements.txt              # Ejecución portable
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
├── docs/                         # Documentación por fase
└── errores/                      # Bitácoras técnicas curadas
```

## Limitaciones actuales

- La validación compara OCR de etiqueta contra OCR de referencia; todavía no
  compara formalmente los componentes del nombre de carpeta contra el OCR.
- La comparación final selecciona una imagen de etiqueta y una referencia; no
  une todavía tokens repartidos entre varias fotografías.
- HEIC/HEIF, RAW, PDF y GIF animado requieren conversión previa.
- Texto manuscrito complejo, superficies curvas, reflejos y desenfoque pueden
  requerir datos propios y fine-tuning.
- Solo se permite una ejecución simultánea del pipeline desde el dashboard.
- Instalar un grupo opcional no implica que su integración funcional ya esté
  implementada.

## Documentación para mantenimiento

Antes de modificar una fase, consulta:

- `docs/fase0_autodescubrimiento.md`
- `docs/fase1_ocr.md`
- `docs/fase2_validacion.md`
- `docs/fase3_excel.md`
- `docs/fase4_dashboard.md`
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
PowerShell. Si administras tu propio equipo y prefieres habilitar de forma
persistente los scripts locales y los scripts remotos firmados, puedes usar:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Este último comando modifica la política del usuario actual. No lo ejecutes en
un equipo administrado por una organización sin consultar antes sus políticas
de seguridad.

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
openpyxl y EasyOCR/PaddleOCR. Detén el servidor, activa `.venv` y vuelve a
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
