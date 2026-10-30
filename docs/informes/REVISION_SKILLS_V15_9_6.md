# Revisión trazable por skill · V15.9.6 (correctiva N10-N12)

**Fecha:** 2026-10-13. Una revisión por cada skill con archivos/diff
analizados, pruebas ejecutadas, hallazgos y decisiones. Base auditada:
`AUDITORIA_ESTRICTA_V_MATRIX_V15_9_5.md` (N10 crítica, N11 alta, N12
media-alta) e instrucciones `CORRECCIONES_OBLIGATORIAS_V_MATRIX_V15_9_6.md`,
incluidos sus 5 casos de regresión incorporados verbatim al repo. Alcance
deliberadamente acotado: contrato de identificación Excel.

## 1. v-matrix-matrix-excel

- **Archivos analizados:** `utilidades/identidad_excel.py` (nuevas
  `_ETIQUETA_EXPLICITA`, `_celda_valor_editable`,
  `mapear_pares_etiqueta_valor`, `_plegar`, `_palabras`, `_nucleo_nombre`,
  `_representaciones_identidad`, `_CLAVES_ETAPA_FASE`,
  `_VALORES_ETAPA_FASE`; `_analizar_referencia` y `_segmento_es_metadato`
  reescritos; eliminación del conjunto fusionado `permitidos`),
  `reporte_bmg.py` y `plantilla_empresarial.py` (sin cambios en esta
  versión; revisados para confirmar que el contrato de hojas y exenciones de
  V15.9.5 alimenta correctamente el nuevo mapeo estructural), plantilla BMG
  real inspeccionada hoja por hoja.
- **Pruebas:** N10 (par en hoja adicional corregido y registrado, valor
  vacío rellenado, valor numérico bloqueado sin reemplazo, fila tabular
  ambigua bloqueada y su variante coherente, hoja exenta intacta, «Sin
  asignar» en par complementario, empresarial con hash de plantilla intacto,
  BMG real con `Projekt:` en `Rangos` y título `Stufe 1ST` en DE), N11
  (Beta/Beta Sur/Beta Norte/Sur, mayúsculas-espaciado-tildes, alias
  registrado vs no registrado, ID técnico distinto y ID parecido), N12
  (10 títulos con etapa/fase contextual ES/EN/DE y delimitadores `— | ( ) -`,
  valores sueltos 1ST/NACH/VOR como nombre ajeno bloqueados, identidad con
  etapa legítima en su nombre); 5 casos literales del auditor en rojo→verde;
  7+23 de V15.9.4 y 3+24 de V15.9.5 verdes.
- **Hallazgos:** N10: la revisión de textos libres es CIEGA a pares
  etiqueta/valor separados (el valor «A» no contiene la palabra clave), de
  modo que cubrir todas las hojas con el escáner textual (V15.9.5) no
  sustituía el mapeo estructural. N11: `permitidos` fusionaba tokens de
  nombre e ID y aceptaba cualquier token compartido como verificación, así
  que «Proyecto Beta» validaba «Proyecto Beta Sur». N12: los metadatos no
  incluían los valores reales de etapa/fase del flujo V-Matrix (1ST, 2ST,
  3RD, NACH, VOR), de modo que títulos legítimos quedaban bloqueados.
- **Decisiones:** verificación estructural y textual COMPLEMENTARIAS;
  etiqueta explícita con separador como único disparador del mapeo
  estructural (las cabeceras de tabla sin separador —columna «Proyecto» de
  trazabilidad/evidencia— no son campos de identidad: mapearlas corrompía
  cabeceras generadas y anulaba P08 en BMG, detectado por las pruebas de
  regresión durante la implementación); sustitución limitada a la celda de
  valor y registrada con su valor anterior; ambigüedad (fórmula, celda
  combinada, valor no textual, fila tabular) ⇒ bloqueo señalando hoja/celda
  sin reemplazar nada; comparación de nombre completo normalizado con
  variantes triviales (mayúsculas, diacríticos, espaciado, guiones) y alias
  sólo si están registrados explícitamente en la identidad; valores de
  etapa/fase aceptados únicamente en contexto de su clave, nunca como permiso
  global.

## 2. v-matrix-safe-change

- **Archivos analizados:** diff V15.9.5→V15.9.6 (2 archivos: módulo de
  identidad y un test volteado documentadamente), más revisión de no
  regresión en `dashboard/backend/app.py`, `pipeline.py` y generadores.
- **Pruebas:** suite completa 671/0/0 (3 corridas) + node 43/43; fresh clone
  de la base V15.8.1 con parche acumulado (671/0/0, 43/43, `archivos/`
  byte-idéntico, reversión ensayada) y clon de V15.9.5 con parche
  incremental; hashes de plantilla BMG real y empresarial verificados dentro
  de las pruebas nuevas.
- **Hallazgos:** el cambio de contrato N10 colisionaba con una prueba propia
  de V15.9.5 (`test_n7_celda_mapeada_no_garantiza_las_demas_referencias`),
  que exigía bloqueo donde la auditoría nueva exige corrección específica.
- **Decisiones:** la prueba se volteó DE FORMA DOCUMENTADA (comentario
  «V15.9.6 (CRIT-N10) SUPERSEDE…»), conservando y ampliando su garantía
  original en el mismo test: un título libre de otro proyecto sigue
  bloqueando sin reemplazo y un par con fórmula bloquea señalando la celda.
  Ningún otro test antiguo se editó ni eliminó. API y pipeline sin cambios:
  `celdas_complementarias` se añade a los metadatos y al bloque visible sin
  romper consumidores.

## 3. v-matrix-video-zoom-ux

- **Archivos analizados:** `dashboard/frontend/app.js` e `i18n.js` (sin
  cambios en V15.9.6; revisión de no regresión de los estados
  confirmado/pendiente/bloqueado de V15.9.5).
- **Pruebas:** 43 contratos UI verdes, incluidos los 5 de estados de
  exportación (bloqueada y pendiente) y sus traducciones ES/EN/DE.
- **Hallazgos/decisiones:** ninguno; los tres estados siguen propagándose
  igual y la navegación real en navegador permanece como pendiente de campo.

## 4. v-matrix-airbag-onset

- **Archivos analizados:** `video_airbag.py` y migración de consensos (sin
  cambios; revisión de no regresión).
- **Pruebas:** matriz de consenso N4 (3/4, 4/4, 3/3, 2/4, 2/2, 1/1, manual,
  revisión obligatoria) y migración N5 verdes dentro de la suite completa.
- **Hallazgos/decisiones:** política única de 3 cámaras y comprobación de
  `guardado` intactas; la auditoría pidió no reescribir el motor de apertura.

## 5. v-matrix-roi-supervision

- **Archivos analizados:** rutas de ROI/zoom/recálculo (sin cambios).
- **Pruebas:** tests de ROI, zoom, recálculo individual y matriz verdes en la
  suite completa; navegación por contrato sin cambios.
- **Hallazgos/decisiones:** ninguno; la verificación visual con navegador
  real sigue declarada como pendiente de campo.

## 6. v-matrix-evaluation-lab

- **Archivos analizados:** benchmark sintético y laboratorio de evaluación
  (sin cambios).
- **Pruebas:** suite completa; todo sintético (`tmp_path`, fixtures y copias
  temporales de la plantilla BMG real), sin datos corporativos.
- **Hallazgos/decisiones:** los pendientes de campo (AVI anotados con FPS
  reales, GPU/RTX, Windows/macOS, navegador real) se mantienen documentados
  sin declararlos aprobados.
