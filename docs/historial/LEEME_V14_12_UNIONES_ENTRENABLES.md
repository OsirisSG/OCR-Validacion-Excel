# V14.12 — Uniones de bloques como aprendizaje visual

Fecha: 2026-09-28
Base: V14.11

## Objetivo

Las correcciones realizadas con **Completar o unir texto de una zona → Confirmar reemplazo de bloques** ahora pueden formar parte del dataset visual de EasyOCR. Antes se conservaban como edición estructural y actualizaban el Excel, pero se marcaban con `entrenamiento: false`.

## Comportamiento nuevo

- La opción **Usar esta unión como ejemplo para entrenamiento OCR** aparece activada por defecto.
- Al confirmar una unión, primero se conserva la edición estructural exactamente como antes y después se genera evidencia visual entrenable.
- Si el texto confirmado contiene una línea por cada bloque original, V14.12 crea un recorte entrenable por línea. Esto evita entrenar al reconocedor con un párrafo grande cuando ya existe geometría suficiente para separar las líneas.
- Si la unión reconstruye una sola cadena a partir de varios fragmentos, se conserva un único recorte con la zona unida completa.
- El entrenamiento automático de V14.9 se programa inmediatamente cuando aparece una muestra nueva y respeta el bloqueo del pipeline CUDA.
- Desactivar la casilla conserva la unión y el Excel, pero no añade esa unión al entrenamiento visual.

## Uniones creadas antes de V14.12

No se borran ni se modifican. Cuando una imagen se marca nuevamente como **Imagen verificada**, el backend revisa las uniones activas de esa imagen y las incorpora de forma oportunista al dataset visual. La firma del dataset evita duplicarlas si la misma imagen se verifica otra vez.

Esta migración se hace por imagen para no recorrer miles de fotografías al arrancar el dashboard.

## Seguridad

- Un fallo al crear el recorte de entrenamiento no revierte ni pierde la unión humana ya confirmada.
- El modelo visual sigue activándose únicamente si supera las comprobaciones de validación y prueba existentes.
- `.aprendizaje`, `.cache_ocr`, checkpoints y cola Excel no deben borrarse al instalar el parche.
