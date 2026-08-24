# Error 001 — PaddleOCR falla en inferencia con oneDNN en Windows (Python 3.13)

- **Fecha:** 2026-08-23
- **Fase:** 1 (motor de OCR)
- **Qué se intentó:** instalación directa de `paddlepaddle` + `paddleocr` (ruedas 3.3.1 / 3.x para Python 3.13) y primera inferencia con la API `PaddleOCR(...).predict()` con valores por defecto.
- **Síntoma:** los modelos PP-OCRv6_medium_det/rec se descargan correctamente, pero al ejecutar la inferencia se lanza:
  `NotImplementedError: (Unimplemented) ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<pir::DoubleAttribute>] (at ..\paddle\fluid\framework\new_executor\instruction\onednn\onednn_instruction.cc:118)`
- **Por qué falló:** bug de compatibilidad entre el ejecutor PIR de Paddle y el backend oneDNN (MKLDNN) en esta combinación de versión/Windows. No es un problema del código del proyecto ni de los modelos.
- **Nuevo enfoque adoptado:** instanciar el motor con `enable_mkldnn=False`. Verificado: la inferencia CPU funciona y la confianza de reconocimiento sobre imagen de prueba es ~0.98. El parámetro queda aplicado en `ocr_engine.py` (clase `_MotorPaddle`) y documentado en `docs/fase1_ocr.md`.
- **Pendiente / nota:** si en el futuro se instala `paddlepaddle-gpu` para usar los 6 GB de VRAM disponibles, re-probar con MKLDNN activado, porque el bug puede no aparecer en la ruta GPU. La v1 corre en CPU (rueda instalada); el rendimiento es suficiente para validación y se documenta como limitación.
