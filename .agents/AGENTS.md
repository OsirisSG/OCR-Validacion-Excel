# Agentes · V-Matrix OCR

Este directorio contiene las **skills** de V15.9.1: manuales de QA para agentes
de desarrollo (Codex y similares). No son código ejecutable ni modifican el
motor; son reglas y criterios que un agente debe leer y aplicar al trabajar sobre
este repositorio.

## Skills disponibles

| Skill | Propósito | Fallos que ayuda a prevenir |
|---|---|---|
| `v-matrix-safe-change` | Cambio seguro, integridad, compatibilidad y rollback | B1, B2, A4–A7 |
| `v-matrix-airbag-onset` | Medición del primer instante de apertura, FPS reales, consenso | B1, B2, A8 |
| `v-matrix-roi-supervision` | ROI bloqueada, herencia visual, reversión con historial | A1 |
| `v-matrix-video-zoom-ux` | Zoom, pan, fullscreen, lupa, alineación de overlays, ES/EN/DE | A2–A4 |
| `v-matrix-matrix-excel` | Paridad dashboard↔Excel, vacantes, «Sin clasificar» | B3, A5–A7 |
| `v-matrix-evaluation-lab` | Batería de pruebas y puerta de publicación | Todos |

## Cómo las usa un agente

1. Antes de tocar código, leer la skill del área afectada (`SKILL.md`).
2. Aplicar sus reglas duras mientras se escribe el cambio.
3. Ejecutar el checklist de verificación correspondiente antes de declarar listo.
4. `v-matrix-safe-change` y `v-matrix-evaluation-lab` aplican **siempre**, en
   cualquier cambio, además de la skill específica del área.

## Límites de las skills

- Son documentos de criterio, no pruebas ya ejecutadas. La evidencia real sale de
  correr `pytest`/`node --test` y el benchmark (`utilidades/benchmark_detector.py`).
- Ninguna skill puede modificar `.aprendizaje`, bases de datos, correcciones
  humanas, videos empresariales ni resultados reales; trabajan con fixtures aisladas.
- No envían videos AVI a servicios externos ni a CI alojado sin autorización.
- No imponen CDNs ni nuevas dependencias de producción; `pytest`, `ruff`, etc.
  son solo herramientas de desarrollo. Hypothesis y Playwright quedan como
  propuestas de validación, no dependencias instaladas.

## Integración incremental recomendada

1. **Pre-r1:** integrar *Safe Change* y *Evaluation Lab* en una rama de pruebas
   para reproducir los bloqueantes.
2. **Después:** *Matrix Excel* y *Airbag Onset* para revisar B1–B3.
3. **Por último:** *ROI Supervision* y *Video Zoom UX* con verificaciones visuales
   de A1–A4.

## Evidencia de uso

La revisión trazable por skill ejecutada durante la preparación de V15.9.1
(condición 2 de la puerta de skills) está en
`docs/informes/REVISION_SKILLS_V15_9_1.md`. La de V15.9.2 (correcciones C1-C6
más el requisito nuevo C7 de proyecto explícito) está en
`docs/informes/REVISION_SKILLS_V15_9_2.md`, con resultados de suite en
`docs/informes/RESULTADOS_PRUEBAS_V15_9_2.md`. La de V15.9.3 (correctiva de la
auditoría estricta: CRIT-01 a CRIT-04 y ALTA-05) está en
`docs/informes/REVISION_SKILLS_V15_9_3.md`, con la puerta rojo a verde y los
resultados de suite en `docs/informes/RESULTADOS_PRUEBAS_V15_9_3.md`. La de
V15.9.4 (correctiva de la auditoría N1-N6) está en
`docs/informes/REVISION_SKILLS_V15_9_4.md`, con resultados en
`docs/informes/RESULTADOS_PRUEBAS_V15_9_4.md`. La de V15.9.5 (correctiva de
la auditoría N7-N9) está en `docs/informes/REVISION_SKILLS_V15_9_5.md`, con
resultados en `docs/informes/RESULTADOS_PRUEBAS_V15_9_5.md`. La de V15.9.6
(correctiva de la auditoría N10-N12) está en
`docs/informes/REVISION_SKILLS_V15_9_6.md`, con resultados en
`docs/informes/RESULTADOS_PRUEBAS_V15_9_6.md`. La de V15.9.7 (correctiva
de la auditoría N13-N14) está en
`docs/informes/REVISION_SKILLS_V15_9_7.md`, con resultados en
`docs/informes/RESULTADOS_PRUEBAS_V15_9_7.md`. La de V15.9.8 (correctiva
de la auditoría N15) está en
`docs/informes/REVISION_SKILLS_V15_9_8.md`, con resultados en
`docs/informes/RESULTADOS_PRUEBAS_V15_9_8.md`. La de V15.9.9 (correctiva
de la auditoría N16) está en
`docs/informes/REVISION_SKILLS_V15_9_9.md`, con resultados en
`docs/informes/RESULTADOS_PRUEBAS_V15_9_9.md`. La de V15.9.10 (correctiva
de la auditoría N17: protección estructural de cabeceras de tablas Excel
formales y evidencia positiva en pares desnudos) está en
`docs/informes/REVISION_SKILLS_V15_9_10.md`, con resultados en
`docs/informes/RESULTADOS_PRUEBAS_V15_9_10.md`.
