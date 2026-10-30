# Revisión trazable por skill · V15.9.9 (correctiva N16)

**Fecha:** 2026-10-13. Una revisión por cada skill con archivos/diff
analizados, pruebas ejecutadas, hallazgos y decisiones. Base auditada:
`AUDITORIA_ESTRICTA_V_MATRIX_V15_9_8.md` (N15 confirmada como mejora real;
N16 crítica) e instrucciones `CORRECCIONES_OBLIGATORIAS_V_MATRIX_V15_9_9.md`,
incluidas sus 7 pruebas incorporadas verbatim al repo
(`pruebas/test_v15_9_9_auditoria_regresiones.py`). Alcance deliberadamente
acotado: mapeo de identidad de Excel en `utilidades/identidad_excel.py`.

## 1. v-matrix-matrix-excel

- **Archivos analizados:** `utilidades/identidad_excel.py` (nuevo
  `_CABECERAS_COLUMNA`; `_es_cabecera_reconocible` ampliada a clasificador
  centralizado de cabeceras; `_clasificar_par` con guarda de cabecera en la
  rama `unico` de etiqueta desnuda; docstrings actualizados),
  `plantilla_empresarial.py` y `reporte_bmg.py` (sin cambios; revisados
  para confirmar que la ruta P08 de borrador y el contrato N6 de respuesta
  propagan correctamente el «sin campo verificable» de las tablas vacías),
  plantilla BMG real inspeccionada (`Übersicht Standversuche`, `Rangos`).
- **Pruebas:** 7 casos literales del auditor en rojo (4 failed / 3 passed
  sobre `7171da1`, mismos valores que su evidencia) → 7/7 verdes; 14 de
  ampliación (cabecera vacía complementaria, combinada debajo, vocabulario
  ES/EN/DE ×6, colisión semántica «Etapa», paridad con campo declarado,
  guardado/releído con hash, empresarial borrador y publicado, BMG real);
  706 pruebas de V15.9.2-V15.9.8 verdes sin editar ninguna.
- **Hallazgos:** N16: la evidencia «sin datos debajo» se trataba como
  garantía de campo único, pero una tabla vacía también la cumple; la
  comprobación de cabeceras reconocibles sólo se ejecutaba en la rama
  `ambigua`. Con «Etapa»/«Stage»/«Stufe»/«Caso» contiguos a «Proyecto», la
  cabecera desaparecía y el reporte salía verificado/publicado. Además el
  vocabulario de cabeceras era incompleto (faltaban Caso/Case/Fall y otras
  claves de columna).
- **Decisiones:** consultar el clasificador de cabeceras ANTES de cualquier
  sustitución junto a etiqueta desnuda, en las dos rutas (centralizado en
  `_clasificar_par`); cabecera reconocible ⇒ omisión silenciosa (es una
  disposición legítima, no un conflicto: sin contradicción falsa) y P08
  emite borrador si no hay otro campo; colisión semántica genuina resuelta
  sólo por asignación explícita (etiqueta con separador = contrato de
  plantilla), jamás por sobrescritura automática; vocabulario ampliado
  ES/EN/DE sin tocar etapas/fases contextuales de N12 (los VALORES de etapa
  —1ST/NACH/VOR— no entran en el vocabulario: siguen siendo posibles
  nombres de proyecto).

## 2. v-matrix-safe-change

- **Archivos analizados:** diff V15.9.8→V15.9.9 (3 archivos: módulo de
  identidad + 2 archivos de pruebas nuevos; ningún test antiguo editado ni
  volteado), más revisión de no regresión en `dashboard/backend/app.py`,
  `pipeline.py`, generadores y frontend (byte-idénticos, como verificó
  también el auditor).
- **Pruebas:** suite completa 727/0/0 (3 corridas) + node 43/43; fresh
  clone de la base V15.8.1 con parche acumulado y clon de V15.9.8 con
  parche incremental (verificados en el paquete de entrega con reversión a
  0 diferencias); hashes de plantilla BMG real y empresarial verificados
  dentro de las pruebas nuevas con Excel guardados y releídos.
- **Hallazgos:** incidencia de entorno repetida (no del parche): los
  `.command` perdieron el bit ejecutable al restaurarse el sandbox (git
  seguía en 100755); el test C5 lo detectó, se restauró con `chmod 755` y
  quedó verde. Documentado sin atribuirlo al parche.
- **Decisiones:** cambio mínimo localizado; metadatos y contratos de API
  sin cambios (las cabeceras vacías simplemente dejan de aparecer en
  `celdas`/`celdas_complementarias`; el borrador y la respuesta N6 ya
  existían); sin dependencias nuevas ni reemplazos globales.

## 3. v-matrix-video-zoom-ux

- **Archivos analizados:** `dashboard/frontend/app.js` e `i18n.js` (sin
  cambios en V15.9.9; revisión de no regresión de los estados
  confirmado/pendiente/bloqueado y de la tarjeta exportadora).
- **Pruebas:** 43 contratos UI verdes, incluidos los 20 que el auditor
  ejecutó por separado (C7, N6 bloqueados/generados, N9 pendiente, zoom,
  matriz, i18n ES/EN/DE).
- **Hallazgos/decisiones:** ninguno; los borradores por N16 viajan por el
  mismo contrato de V15.9.4/V15.9.6. Navegador real sigue pendiente de
  campo.

## 4. v-matrix-airbag-onset

- **Archivos analizados:** `video_airbag.py` y migración de consensos (sin
  cambios; revisión de no regresión; el auditor confirmó la igualdad byte a
  byte con V15.9.7).
- **Pruebas:** matriz de consenso N4 y migración N5 verdes dentro de la
  suite completa; umbrales y tiempos sin cambios.
- **Hallazgos/decisiones:** el detector de airbag no se tocó (la auditoría
  lo señala expresamente como no afectado por N16).

## 5. v-matrix-roi-supervision

- **Archivos analizados:** rutas de ROI/zoom/recálculo (sin cambios).
- **Pruebas:** tests de ROI, zoom, recálculo individual y matriz verdes en
  la suite completa; aprendizaje y checkpoints conservados (el diff no los
  toca).
- **Hallazgos/decisiones:** ninguno; verificación visual con navegador real
  sigue pendiente de campo.

## 6. v-matrix-evaluation-lab

- **Archivos analizados:** benchmark sintético y laboratorio de evaluación
  (sin cambios).
- **Pruebas:** suite completa; todo sintético (`tmp_path`, fixtures y
  copias temporales de la plantilla BMG real), sin datos corporativos ni
  mezclar proyectos.
- **Hallazgos/decisiones:** los pendientes de campo (Excel corporativos
  representativos, AVI anotados reales, GPU/RTX, Windows/macOS, navegador
  real) se mantienen documentados sin declararlos aprobados; no se declara
  aptitud para producción en esta versión.
