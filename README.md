# Sistema local de OCR y validación de pruebas

Aplicación local para recorrer lotes de fotografías, extraer nomenclaturas con
OCR, comparar etiquetas contra imágenes de referencia, generar un Excel maestro
y consultar los resultados desde un dashboard responsivo.

El procesamiento no utiliza APIs de OCR ni servicios en la nube. EasyOCR es el
motor portable incluido por defecto como respaldo; PaddleOCR puede instalarse
por separado y seleccionarse en `config.yaml`.

## Funciones principales

- Descubrimiento recursivo de carpetas sin asumir profundidad fija.
- Detección de nombres conformes y carpetas anómalas.
- OCR sobre imágenes completas con deskew, binarización y QR opcional.
- Comparación etiqueta ↔ referencia por tokens alfanuméricos.
- Semáforo configurable desde YAML.
- Excel maestro con estructura completa y matriz de cumplimiento.
- Dashboard local con resumen, listado, detalle y procesamiento de carpetas.
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

El Documento Maestro recomienda PaddleOCR como motor principal cuando la
plataforma lo soporte. Instala PaddlePaddle/PaddleOCR siguiendo las instrucciones
oficiales correspondientes a tu sistema, CPU o GPU. Después configura:

```yaml
fase1:
  motor: paddle
  motor_fallback: easyocr
```

Si PaddleOCR no está instalado, el sistema continúa con EasyOCR.

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

El dashboard ofrece cuatro vistas:

- **Resumen:** KPIs y distribución del semáforo.
- **Listado:** búsqueda, filtros y navegación a detalle.
- **Detalle:** imágenes y tokens OCR de etiqueta/referencia.
- **Procesar carpeta:** ejecuta las Fases 0–3 desde una ruta local.

Para un lote grande, usa una ruta local en **Procesar carpeta**. Los archivos no
se suben ni se duplican en el navegador.

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
├── pipeline.py                   # Orquestador Fases 0–3
├── configuracion.py              # Configuración y reglas compartidas
├── config.yaml
├── reglas_cumplimiento.yaml
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

## Documentación para mantenimiento

Antes de modificar una fase, consulta:

- `docs/fase0_autodescubrimiento.md`
- `docs/fase1_ocr.md`
- `docs/fase2_validacion.md`
- `docs/fase3_excel.md`
- `docs/fase4_dashboard.md`

Cada cambio debe conservar los contratos de entrada/salida, actualizar el
Markdown de su fase y registrar en `errores/` cualquier enfoque fallido antes de
cambiar de estrategia.

## Solución de problemas

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
