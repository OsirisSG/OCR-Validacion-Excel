# Documentación del proyecto

Versión **V15.8.1**: organización de guías, informes, historial y parches, sobre
las funciones de V15.8. Sin cambios en el motor OCR ni en los datos del usuario.

Para instalar o iniciar el programa, comienza por el [README principal](../README.md).
La reorganización sólo cambia la ubicación de notas e informes: no mueve código,
dependencias, datos, aprendizaje ni archivos de salida.

## Guías actuales

- [Funciones y uso de V15.8: etiquetas, ruptura, máximo visible y rangos](guias/LEEME_V15_8_GUIA_RUPTURA_MAXIMO.md).
- [Instalación multiplataforma y diagnóstico CPU/GPU](instalacion_multiplataforma.md).
- [Notas de instalación V15 del paquete original](guias/LEEME_INSTALACION_V15.txt).

## Informes y validación

- [Cambios y pruebas de V15.8](informes/RESULTADOS_PRUEBAS_V15_8.md).
- [Aplicación de V15.8 a la carpeta del proyecto y respaldo](informes/ACTUALIZACION_CARPETA_V15_8.md).
- [Informes de versiones anteriores](informes/).

## Documentación técnica

- [Contrato funcional y documento maestro](documento_maestro.md).
- [Descubrimiento de carpetas](fase0_autodescubrimiento.md).
- [Motor OCR](fase1_ocr.md).
- [Validación y consolidación](fase2_validacion.md).
- [Generación de Excel](fase3_excel.md).
- [Dashboard](fase4_dashboard.md).
- [Flujo empresarial](flujo_empresarial.md).
- [Aprendizaje incremental](aprendizaje_incremental.md).
- [Evaluación OCR compleja](evaluacion_ocr_complejo.md).
- [Analizador Excel](analizador_excel.md).

## Historial conservado

- [Resumen de correcciones y versiones](historial/README_CORRECCIONES_VERSIONES.md).
- [Notas de versiones anteriores](historial/).
- [Instrucciones de parches anteriores](historial/parches/).
- [Bitácoras de errores](../errores/).

Las instrucciones antiguas se conservan para consulta. No vuelvas a aplicar sus
parches sobre una versión nueva sin revisar su compatibilidad.

`VERSION.txt` y `requirements*.txt` permanecen en la raíz porque los utiliza la
instalación. No son archivos históricos ni deben eliminarse para limpiar la carpeta.
