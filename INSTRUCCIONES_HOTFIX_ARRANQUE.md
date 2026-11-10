# HOTFIX de arranque V-Matrix V15.10.1 — 2026-10-14

## Qué corrige

Restaura tres dependencias que existen en el árbol V15.10.0 pero que no vienen dentro de los parches incrementales V15.10.1/H5:

- `utilidades/evidencia_apertura.py` (resuelve el `ModuleNotFoundError` de Python).
- `dashboard/frontend/visor_precision.js` (define `window.VMatrixVisorPrecision`, incluida `xyxyToPercent`).
- `dashboard/frontend/index.html` actualizado para cargar `visor_precision.js` ANTES de `app.js`, con parámetros de caché nuevos.

Este paquete es una reparación focalizada de los dos bloqueos de inicio mostrados en la captura. No sustituye el árbol completo V15.10.0 ni demuestra que todos los archivos de versiones previas estén presentes.

## Aplicación segura en Windows

1. Cierra V-Matrix.
2. Haz una copia de respaldo de `dashboard/frontend/index.html` si ya existe.
3. Extrae el ZIP en la **raíz** de `OCR-Validacion-Excel-ocr-gpu-produccion` (la carpeta que contiene `dashboard`, `utilidades`, `video_airbag.py`, etc.), conservando las rutas y permitiendo reemplazar `dashboard/frontend/index.html`.
4. Comprueba que existan los tres archivos con las rutas indicadas arriba.
5. Inicia de nuevo la aplicación. En el navegador haz `Ctrl + F5` para descartar caché antigua.
6. Si el error de importación continúa, confirma que el lanzador esté usando esa misma carpeta y el intérprete/entorno virtual del proyecto.

No modifica ni incluye `.aprendizaje`, datos reales, `AGENTS.md` ni skills.

## Validación local

Desde la raíz del proyecto, con el entorno de Python del proyecto activo:

```powershell
python -c "from utilidades.evidencia_apertura import generar_candidatos; print('IMPORT_OK')"
node --check dashboard/frontend/visor_precision.js
```

Además, abre `dashboard/frontend/index.html` y confirma que el script `visor_precision.js` aparezca antes de `app.js`.

## Alcance y límites

Esta reparación no corrige la lógica de censura temporal H5 detectada en la auditoría ni equivale a aprobación para producción. Primero confirma que la interfaz arranque; después deben ejecutarse las pruebas temporales de regresión correspondientes.
