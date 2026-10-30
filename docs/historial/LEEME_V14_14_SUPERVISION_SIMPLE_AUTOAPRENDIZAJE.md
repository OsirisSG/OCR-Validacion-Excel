# OCR V14.14 — Supervisión simple + aprendizaje automático

Fecha: 2026-09-28
Base: V14.13

## Flujo simplificado

La corrección OCR visible queda reducida a dos decisiones positivas:

- **Aceptar lectura**: confirma que la lectura OCR visible es correcta.
- **Aplicar corrección**: guarda el texto editado por el revisor.

Ambas decisiones positivas generan evidencia visual entrenable automáticamente. Ya no es necesario elegir entre «guardar sin entrenar» y «proponer para entrenamiento». Las acciones negativas (por ejemplo, «Esto no es texto») siguen fuera del entrenamiento positivo.

Texto nuevo, uniones y geometría final confirmada también se proponen siempre al aprendizaje visual. El entrenamiento pesado conserva su orquestación segura: si el pipeline OCR usa CUDA, queda diferido en vez de competir por GPU.

## Aviso de cambios sin guardar

El mensaje ahora enumera el origen exacto del borrador: corrección textual, texto nuevo, unión de bloques o ajuste/división. Así el revisor sabe qué debe guardar, cerrar o descartar antes de verificar la imagen.

## Ayuda ⓘ

La ayuda de aprendizaje se renderiza como un control visible `ⓘ`. Al abrirlo explica qué se aprende. No depende solo del tooltip del navegador.

## Unión por clic

En **Unir bloques**, cada bloque pulsado queda resaltado. Pueden seleccionarse dos o más bloques y volver a pulsar uno para quitarlo. La caja de unión se recalcula con todos los bloques seleccionados.

## Compatibilidad

- No borra `.aprendizaje`, `.cache_ocr`, checkpoints ni resultados.
- Conserva contratos antiguos del backend para clientes previos.
- Los controles antiguos de acción se mantienen únicamente ocultos como compatibilidad de frontend; no aparecen en la interfaz normal.

## Idiomas ES / EN / DE

Se añadieron traducciones para los controles dinámicos de geometría flexible, aprendizaje automático, unión múltiple y el desglose de cambios pendientes. Los cuadros `confirm()` usan ahora el traductor directamente, por lo que ya no dependen del observador del DOM.

## Garantía de aprendizaje positivo

El backend fuerza el aprendizaje visual para toda confirmación positiva, incluso si un navegador antiguo envía todavía el campo histórico `guardar_sin_entrenar` o un flag de entrenamiento desactivado. Se conservan esos campos únicamente por compatibilidad de contrato. `ilegible` y `no_es_campo` continúan fuera del entrenamiento positivo.
