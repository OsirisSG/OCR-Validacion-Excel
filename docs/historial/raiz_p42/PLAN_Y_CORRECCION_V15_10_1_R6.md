# Plan y corrección V15.10.1 R6

## Hallazgo reproducido
El mensaje de Windows "no se encontró Python" ocurría antes de ejecutar `aplicar_parche_seguro.py`; por tanto R5 no había copiado el payload y el backend seguía ejecutando la versión previa que lanzaba `ModuleNotFoundError: utilidades.verificador_apertura`.

## Corrección
1. Instalador primario reescrito en PowerShell, sin dependencia de Python en PATH.
2. Verificación SHA-256 post-copia de todo el payload.
3. Comprobación explícita de módulos críticos de apertura.
4. Detección opcional del Python real del proyecto/proceso y prueba de resolución de imports.
5. Marca observable `patch_build = 15.10.1-r6` en `/api/estado`.
6. Cache-busting del frontend a r6.
7. Conservación de matriz dinámica: 5.8/6.4/7.2 ms -> verde/amarillo/rojo cuando el dato es publicable; conflicto/pendiente permanece gris.

## Criterio de éxito inmediato
- `INSTALAR_R6.bat` termina con `PARCHE_R6_COPIADO_Y_VERIFICADO_OK`.
- Existe y tiene contenido `C:\Programas Base\OCR-Validacion-Excel-ocr-gpu-produccion\utilidades\verificador_apertura.py`.
- Tras reiniciar, `/api/estado` muestra `15.10.1-r6`.
- El procesamiento ya no falla por `ModuleNotFoundError` del verificador.

La validación final de precisión de OCR/apertura requiere los AVI, imágenes y plantillas reales del entorno del usuario.
