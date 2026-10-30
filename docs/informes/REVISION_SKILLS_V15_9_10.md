# Revisión trazable por skill · V15.9.10 (correctiva N17)

**Fecha:** 2026-10-13. Una revisión por cada skill con archivos/diff
analizados, pruebas ejecutadas, hallazgos y decisiones. Base auditada:
`AUDITORIA_ESTRICTA_V_MATRIX_V15_9_9.md` (N16 corregida en los casos
comprobados; N17 crítica) e instrucciones
`CORRECCIONES_OBLIGATORIAS_V_MATRIX_V15_9_10.md`, incluidas sus 7 pruebas
incorporadas verbatim al repo
(`pruebas/test_v15_9_10_auditoria_regresiones.py`). Alcance deliberadamente
acotado: mapeo de identidad de Excel en `utilidades/identidad_excel.py`.

## 1. v-matrix-matrix-excel

- **Archivos analizados:** `utilidades/identidad_excel.py` (nuevos
  `_MENCION_INICIAL`, `_celda_en_cabecera_estructural` y
  `_evidencia_valor_proyecto`; `_clasificar_par` con guarda estructural al
  inicio y evidencia positiva en la rama `unico` de etiqueta desnuda;
  docstrings actualizados), `plantilla_empresarial.py` y `reporte_bmg.py`
  (sin cambios; revisados para confirmar que P08 y el contrato N6 propagan
  el «sin campo verificable» y las nuevas contradicciones fail-closed),
  plantilla BMG real inspeccionada (`Rangos`, `Übersicht Standversuche`),
  fixture empresarial (`Captura_pruebas` contiene la tabla formal
  `TablaCaptura` `A4:AJ205`: su fila 4 queda ahora protegida
  estructuralmente, no sólo por vocabulario).
- **Pruebas:** 7 casos literales del auditor en rojo (5 failed / 2 passed
  sobre `8c916ba`, mismos valores que su evidencia) → 7/7 verdes; 18 casos
  de ampliación (tabla poblada, dos tablas por hoja en posiciones
  arbitrarias, autofiltro, etiqueta explícita en cabecera de tabla, par
  explícito en cuerpo de tabla, visual desconocida + explícito fail-closed,
  evidencia positiva ×4, contiguo vacío, colisión «Temperatura», explícito
  ES/EN/DE, empresarial borrador/publicado con hashes y releídos, BMG real
  con tabla formal); 727 pruebas de V15.9.2-V15.9.9 verdes.
- **Hallazgos:** N17 tiene dos causas raíz: (a) ninguna ruta consultaba
  `ws.tables`/`Table.ref`/`auto_filter` antes de clasificar un par, de modo
  que la VERDAD ESTRUCTURAL del libro (una cabecera de tabla registrada) se
  ignoraba y el diccionario `_CABECERAS_COLUMNA` de V15.9.9 quedaba como
  única defensa —insuficiente por diseño: «Temperatura», «Color» o
  cualquier palabra fuera de catálogo reabría la corrupción; (b) en la rama
  `unico`, la ausencia de filas de datos se seguía tratando como garantía
  de campo único incluso sin tabla registrada, escribiendo por suposición
  sobre contiguos desconocidos («A», «PRJ-001», «Old»). Efecto colateral de
  (a): una cabecera legítima con datos debajo generaba contradicción y
  bloqueaba una salida que tenía campo explícito correcto (falso negativo).
- **Decisiones:** una única función estructural compartida por ambas rutas
  dentro del clasificador común `_clasificar_par` (exigencia 6 del auditor:
  sin bifurcaciones declarada/complementaria); la guarda estructural se
  evalúa ANTES de distinguir explícita/desnuda («sin importar qué texto
  contenga») y produce omisión silenciosa (nunca contradicción: una
  cabecera de tabla no es un título contradictorio); sin estructura formal,
  el par desnudo exige evidencia POSITIVA del contiguo (coherencia con la
  identidad o mención inicial) y en su defecto fail-closed con hoja/celda
  señaladas; el vocabulario N16 se conserva como segunda capa para tablas
  visuales con contiguo reconocible (omisión silenciosa, no bloqueo); el
  contiguo vacío sigue rellenándose (N10) y la política de editabilidad
  (fórmulas/números/combinadas/estilos) no cambia. Se voltearon 2 pruebas
  de ampliación de autor (V15.9.7) cuyo contrato fue reemplazado
  explícitamente por la exigencia 3 del auditor, con docstring `SUPERSEDE`;
  ninguna prueba del auditor fue editada.

## 2. v-matrix-safe-change

- **Archivos analizados:** diff V15.9.9→V15.9.10 (4 archivos: módulo de
  identidad + 2 archivos de pruebas nuevos + volteo documentado de
  `pruebas/test_v15_9_7_ampliacion.py`), más revisión de no regresión en
  `dashboard/backend/app.py`, `pipeline.py`, generadores y frontend
  (byte-idénticos).
- **Pruebas:** suite completa 752/0/0 (3 corridas) + node 43/43; fresh
  clone de la base V15.8.1 con parche acumulado y clon de V15.9.9 con
  parche incremental (verificados en el paquete de entrega con reversión a
  0 diferencias); hashes de plantilla BMG real y empresarial verificados
  dentro de las pruebas nuevas con Excel guardados y releídos
  (`Table.ref`, nombres de columna y cabeceras intactas tras
  guardar/cargar).
- **Hallazgos:** incidencia de entorno repetida (no del parche): los
  `.command` perdieron el bit ejecutable al restaurarse el sandbox (git
  seguía en 100755); el test C5 lo detectó, se restauró con `chmod 755` y
  quedó verde. Documentado sin atribuirlo al parche.
- **Decisiones:** cambio mínimo localizado; metadatos y contratos de API
  sin cambios (las cabeceras formales dejan de aparecer en
  `celdas`/`celdas_complementarias` y dejan de generar contradicciones; el
  nuevo bloqueo fail-closed viaja por la contradicción estructural ya
  existente y la respuesta N6 ya la comunica); sin dependencias nuevas ni
  reemplazos globales; las pruebas del auditor se conservan verbatim.

## 3. v-matrix-video-zoom-ux

- **Archivos analizados:** `dashboard/frontend/app.js` e `i18n.js` (sin
  cambios en V15.9.10; revisión de no regresión de los estados
  confirmado/pendiente/bloqueado y de la tarjeta exportadora).
- **Pruebas:** 43 contratos UI verdes (C7, N6 bloqueados/generados, N9
  pendiente, zoom, matriz, i18n ES/EN/DE).
- **Hallazgos/decisiones:** ninguno; los borradores y bloqueos por N17
  viajan por los mismos contratos de V15.9.4/V15.9.6 (aviso visible en
  UI/API sin cambios de frontend). Navegador real sigue pendiente de campo.

## 4. v-matrix-airbag-onset

- **Archivos analizados:** `video_airbag.py` y migración de consensos (sin
  cambios; revisión de no regresión).
- **Pruebas:** matriz de consenso N4 y migración N5 verdes dentro de la
  suite completa; umbrales y tiempos sin cambios.
- **Hallazgos/decisiones:** el detector de airbag no se tocó (la auditoría
  acota expresamente la corrección al mapeo de identidad de Excel).

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
  representativos —incluidos libros con tablas formales reales del entorno
  del usuario—, AVI anotados reales, GPU/RTX, Windows/macOS, navegador
  real) se mantienen documentados sin declararlos aprobados; no se declara
  aptitud para producción en esta versión.
