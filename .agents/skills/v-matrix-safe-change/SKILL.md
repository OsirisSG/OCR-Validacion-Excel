---
name: v-matrix-safe-change
description: Reglas de cambio seguro para V-Matrix OCR. Obligatorias antes de modificar motor, dashboard, Excel o persistencia; priorizan integridad, compatibilidad y rollback.
---

# V-Matrix · Safe Change

Skill de guardia para CUALQUIER cambio en el repositorio OCR-Validacion-Excel.

## Cuándo aplicarla
Siempre que un agente proponga un diff sobre: `video_airbag.py`, `validacion.py`,
`pipeline.py`, `reporte_bmg.py`, `generar_excel.py`, `utilidades/*`,
`dashboard/backend/*`, `dashboard/frontend/*` o archivos de aprendizaje.

## Reglas duras (no negociables)
1. **Integridad primero.** Nunca borrar ni sobrescribir `.aprendizaje/`, bases
   SQLite, checkpoints de reanudación, `validacion.json` ni videos originales.
   Toda escritura de estado usa `utilidades.persistencia.escribir_json_seguro`
   (atómica; si falla, conserva la versión previa).
2. **Correcciones humanas son sagradas.** Una `revision_manual`, ROI bloqueada o
   corrección OCR confirmada jamás se sobreescribe por un proceso automático.
3. **Compatibilidad legacy.** Antes de fusionar: leer JSON de versiones anteriores
   (V15.6–V15.8) y comprobar que siguen cargando. `consenso_valido` debe tolerar
   consensos sin `estado_consenso`; el semáforo debe tolerar tiempos fuera de
   `campos` (fallback A5).
4. **Nunca inventar datos.** Prohibido publicar un tiempo no confirmado como
   confirmado (B1), sustituir ausencia de medida por 0 ms, o inventar IDs en la
   matriz. Lo propuesto se queda `pendiente_revision` con su valor solo en tooltip.
5. **Rollback por diseño.** Cada parche debe poder revertirse con
   `git apply -R cambios_V*.patch` sin pérdidas; documentar el procedimiento.
6. **Sin dependencias de red en runtime.** Nada de CDNs ni descargas durante la
   ejecución normal; herramientas de QA (pytest, ruff…) son solo de desarrollo.

## Checklist antes de declarar «listo»
- [ ] `python -m pytest pruebas/` en verde (falla de entorno conocida: `test_dashboard.py::test_estado_config_y_frontend` sin carpeta procesada).
- [ ] `node --test pruebas/*.cjs` en verde.
- [ ] Prueba de regresión específica para cada bug corregido (reproduce → corrige → verifica).
- [ ] Los JSON legacy de prueba siguen abriendo en el dashboard.
- [ ] VERSION.txt, `index.html` (parámetros `?v=`) y changelog actualizados en el mismo parche.

## Señales de alarma detectadas por esta skill
- Un test nuevo sin escenario de fallo previo.
- Un endpoint que muta `.aprendizaje` sin historial/reversión.
- Cambios de caché de estáticos sin actualizar `index.html`.
- Publicación de `opening_time_ms` desde un consenso `propuesto`/`discordancia`.
