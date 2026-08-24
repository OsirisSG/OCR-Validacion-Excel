# Error 003 — El recorte de ROI alrededor del QR truncaba el código a leer

- **Fecha:** 2026-08-23
- **Fase:** 1 (preprocesamiento / ancla QR)
- **Qué se intentó:** usar el QR como ancla espacial con un ROI expandido `2.0 × tamaño_del_QR` por lado, y una política que solo rechazaba el ROI si dejaba < 30% del ancho/alto de la imagen.
- **Síntoma:** en los casos (a) y (b) con QR, el código salía cortado: `ETQ-202` / `ETQ-2024-A1` en lugar de `ETQ-2024-A1-V2`. La parte del texto fuera del ROI jamás llegaba al OCR, así que ningún umbral de confianza la recuperaba. En la foto con skew de 4° además el QR se detectaba ANTES de rotar la imagen pero el recorte se hacía DESPUÉS: coordenadas del ancla y del recorte en marcos distintos.
- **Por qué falló:** dos causas. (1) El texto no tiene posición fija respecto al QR (lo advierte el Documento Maestro §3): cualquier recorte agresivo puede cortar texto que cae fuera, y el detector no puede avisar de lo que no ve. (2) Bug de coordenadas: detección del QR sobre la imagen original y recorte sobre la imagen deskewed.
- **Nuevo enfoque adoptado (verificado):**
  1. El QR se detecta SOBRE la imagen ya preprocesada (mismo marco de coordenadas que el recorte).
  2. ROI deliberadamente conservador: margen `3.0×`, y se rechaza si dejaría < 90% del ancho o alto (`fase1.qr.roi_frac_minima`). En la práctica solo recorta márgenes vacíos evidentes.
  3. Reintento anti-truncamiento: si una caja detectada toca el borde del ROI (±8 px) o el ROI no produce texto, se re-lee la imagen completa y gana la mejor pasada.
  - Resultado: los 6 casos de `pruebas/prueba_fase1_casos.py` pasan (código completo en los cuatro casos QR/posición + 180° + skew).
- **Lección para el ajuste fino:** si en lotes reales las fotos tienen mucho fondo y se quiere un ROI más agresivo, bajar `roi_frac_minima` con cautela y vigilar tokens cortados; el reintento por borde tocado es la red de seguridad, pero no ve texto que quedó totalmente fuera.
