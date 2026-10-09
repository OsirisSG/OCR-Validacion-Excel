# V14.9 — Aprendizaje inmediato por imagen

## Objetivo
Reducir trabajo repetido durante la revisión humana. Una corrección confirmada puede ayudar a la siguiente imagen similar sin esperar a acumular cuatro evidencias ni pulsar manualmente «Entrenar lote visual».

## Dos capas de aprendizaje

1. **Aprendizaje inmediato de estrategia**
   - Se activa desde la primera imagen confirmada.
   - Reutiliza orientación base, ajuste fino, tratamiento y tipo esperado en otra imagen del mismo grupo de ruta y con una caja equivalente.
   - La estrategia aprendida se **ensaya**, nunca se impone ciegamente: si la nueva lectura es ruido o peor que el OCR normal, se descarta.
   - Reconfirmar varias veces la misma imagen no multiplica el soporte.

2. **Ajuste visual automático de EasyOCR**
   - Ya no requiere pulsar «Entrenar lote visual».
   - Al verificar una imagen, si existe una muestra entrenable nueva y se cumplen los mínimos configurados, se programa automáticamente un ajuste visual.
   - Si el pipeline OCR principal usa la GPU, el entrenamiento queda pendiente y se reanuda al terminar el OCR.
   - El modo automático usa `epocas_auto: 1` para reducir el coste de cada actualización.
   - Si el candidato mejora validación y prueba, puede activarse automáticamente (`auto_activar_si_mejora: true`).
   - El botón queda como **Forzar entrenamiento ahora**, únicamente como control manual opcional.

## Protección
La capa inmediata exige por defecto mismo grupo estable de ruta + caja normalizada equivalente. Por eso una sola imagen no se convierte en una regla global. Las reglas consolidadas siguen requiriendo varias imágenes y dominancia configurada.

## Flujo recomendado
Corregir/releer -> Aplicar supervisión -> Imagen verificada -> continuar con la siguiente imagen. No es necesario pulsar Entrenar lote visual.
