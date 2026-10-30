# Resultados de verificación del parche V15.10.1 — 2026-10-13

## Código de origen comprobado (lectura GitHub)

- Rama original `codex/ocr-v15-8-1-organizacion`: commit `5fbef43bb4c2c9142327afd3f88e89b460aed6c5`.
- Referencia actual `Parche_Temp/main`: commit `2aa4fc3a5c1f987572952cca17c14a17e7cc6cd4`.
- Los cuatro archivos modificados por el codemod (`utilidades/matriz_apertura.py`,
  `dashboard/frontend/app.js`, `dashboard/backend/app.py`,
  `utilidades/benchmark_detector.py`) se consultaron en dicha referencia.
  Cada ancla de transformación tuvo exactamente **una** coincidencia con el
  texto remoto consultado. Estas comprobaciones son de compatibilidad de
  parches, no ejecución real del pipeline completo.

## Pruebas ejecutadas en este ambiente

Comando:

```text
python -m pytest -q pruebas/test_v1510_piloto.py
19 passed, 1 skipped
```

La prueba omitida verifica la matriz **después de aplicar** el parche a la
referencia real V15.9.10; este entorno no tiene un checkout íntegro de esa
referencia. La prueba se habilita al aplicar el ZIP en el repositorio del
usuario. No se ejecutó aquí la suite completa 752+ ni Node/browser.

Cobertura nueva: prioridad temporal de correcciones humanas por campo,
protección de proyectos, abstención OCR, 1000/5000 FPS, sincronización
común, rechazo 2/4, detección de duplicados, top candidatos sin publicación,
ROI fuera de límites, no escritura SQLite, detección de fuga entre splits,
validación del backend contra tiempos grises, y aplicación/reversión
transaccional en árbol simulado.

## No verificado (bloquea producción)

- Integración completa sobre checkout V15.9.10 en Windows corporativo.
- Fotografías reales EDAG/VW con etiquetas validadas por experto.
- Datos de `.aprendizaje` (no recibidos) y pesos actualmente activos.
- Videos AVI reales a 1000/5000 FPS con anotaciones de primer frame.
- Performance CPU/RAM/GPU en equipo de uso, tolerancias y sincronización.
- Integridad de salida contra plantilla Excel corporativa real y suite global.

**Conclusión:** El ZIP es un parche piloto entregable, no la finalización del
plan maestro V15.10 ni certificación de una exactitud de 0.1 ms.
