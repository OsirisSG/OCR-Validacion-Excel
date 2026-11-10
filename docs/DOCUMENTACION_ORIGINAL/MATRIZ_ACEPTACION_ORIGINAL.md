# Matriz de aceptación V15.9.10 — condiciones obligatorias de la auditoría N17

Veredicto V15.9.9: NO APTA PARA PRODUCCIÓN (N16 corregida en los casos
comprobados; N17 crítica). Esta matriz verifica condición por condición el
estado en V15.9.10 según las «Condiciones obligatorias» 1-8 y la «Entrega
requerida» de `CORRECCIONES_OBLIGATORIAS_V_MATRIX_V15_9_10.md`.
**No se declara apto para producción** sin las pruebas de campo reales.

| # | Condición exigida | Estado | Evidencia |
|---|---|---|---|
| 1 | Proteger la estructura formal: comprobar `ws.tables`/`Table.ref` ANTES de cualquier mapeo/escritura en ruta declarada o complementaria; una celda de la fila de cabeceras de tabla registrada no es campo editable, sin depender de texto, idioma o número de filas | **CUMPLE** | `_celda_en_cabecera_estructural` consultada AL INICIO de `_clasificar_par`, antes de distinguir explícita/desnuda y antes de cualquier escritura; recorre `hoja.tables` (`headerRowCount != 0`, `range_boundaries(Table.ref)`) y `hoja.auto_filter.ref`. Pruebas: 7 verbatim (tabla formal ES/EN/DE con `ref="A2:B2"`, tabla+explícito, tabla visual) + ampliación (poblada, explícita en cabecera de tabla, autofiltro). El texto «Temperatura»/«Temperature»/«Temperatur» no interviene en la decisión |
| 2 | Cubrir tablas vacías y pobladas, cualquier ubicación y varias tablas por hoja; preservar cabeceras, metadatos de tablas, fórmulas, combinaciones, números, estilos y plantilla original | **CUMPLE** | Vacías: verbatim ×3 + empresarial + BMG; poblada: `test_n17_tabla_formal_poblada…` (guardada/releída); ubicación arbitraria y dos tablas por hoja: `test_n17_varias_tablas_en_posiciones_arbitrarias…` (D5:E5 y B9:C9, releídas con `Table.ref` intacto); autofiltro: `test_n17_autofiltro…`. Preservación: suite N13 (fórmulas/números/combinadas/estilos) verde sin cambios + hashes SHA-256 de plantillas antes==después en empresarial y BMG real + verbatim guarda/relee |
| 3 | Sin objeto `Table` ni contrato explícito, tratar `Proyecto \| valor` como AMBIGUA cuando no hay evidencia positiva de que el valor sea el proyecto, en lugar de sobrescribir por defecto; mantener compatibilidad de `Proyecto \| Proyecto A` y `Proyecto: \| Proyecto A`; permitir mapeo explícito, no adivinar | **CUMPLE** | `_evidencia_valor_proyecto` + `_MENCION_INICIAL`: contiguo sin evidencia («Temperatura» en tabla visual, «A», «PRJ-001», «Old») ⇒ contradicción estructural fail-closed, `publicable=False`, nada se escribe. Controles del auditor 2/2 verdes desde V15.9.9 sin tocarlos (`Proyecto \| Proyecto A`, `Proyecto: \| Proyecto A`); evidencia positiva ×4 en ampliación; mapeo explícito con separador permitido (contrato de plantilla). Los 2 volteos necesarios (pruebas de AUTOR V15.9.7 que afirmaban la sobrescritura por defecto) están documentados con docstring `SUPERSEDE` — la propia condición 3 reemplaza ese contrato |
| 4 | Cabecera legítima + campo explícito `Proyecto: \| Proyecto A` ⇒ actualizar sólo ese campo, permitir publicación y no registrar contradicciones falsas | **CUMPLE** | `test_n17_tabla_registrada_con_campo_explicito_debajo_publica_sin_bloquear` (verbatim, estaba ROJO en V15.9.9) + `test_n17_autofiltro…` + `test_n17_empresarial_tabla_formal_con_campo_explicito_publica` (oficial publicado, cabecera y `TablaVacia` intactas tras releer) + muestra 2 |
| 5 | Si solo hay cabecera de tabla: sin celdas mapeadas, sin identidad verificada, sin publicación; borrador bloqueado con aviso correcto en interfaz y API | **CUMPLE** | Verbatim ×3 idiomas: `celdas==[]`, `identidad_verificada=False`, `estado_identidad=no_verificada`, `publicable=False`; generador empresarial ⇒ `.borrador_no_publicable` oficial nunca en `generados/` (P08, muestra 1); aviso en UI/API por el contrato N6 existente (respuestas `bloqueados`/`estado_publicacion`), contratos node 43/43 sin cambios de frontend |
| 6 | Reutilizar UNA única función estructural para ambos recorridos (`buscar_celdas_proyecto` y `mapear_pares_etiqueta_valor`), sin bifurcaciones que reproduzcan N13-N16 | **CUMPLE** | Desde V15.9.8 ambos recorridos convergen en `_clasificar_par`; la nueva guarda estructural vive DENTRO de esa función única (un solo punto de decisión). Prueba de paridad: `test_n17_par_explicito_en_cuerpo_de_tabla_se_mapea` y los casos declarada/complementaria de la ampliación ejercitan las dos entradas con el mismo resultado; no se añadió ninguna copia de la lógica |
| 7 | Pruebas de exportación real con `openpyxl`: persistencia, `Table.ref`, nombres de columnas, varias hojas, campos declarados, exportadores BMG/empresarial/genérico, SHA de plantilla, oficial vs borrador | **CUMPLE** | Guardado/releído con `Table.ref` y cabeceras: verbatim + `test_n17_tabla_formal_poblada…` + `test_n17_varias_tablas…`; varias hojas: Ficha/Detalle/Resumen en ampliación y verbatim; genérico: `aplicar_identidad_a_salida` directo; empresarial: borrador y oficial con hash de plantilla y releído (`TablaVacia` intacta); BMG real del repo (`plantillas/reporte_bmg_1st_2st.xlsx`) con tabla formal en `Rangos` ⇒ borrador + hash del repo intacto; oficial vs borrador asertado por ruta de salida y nombre `.borrador_no_publicable` |
| 8 | No modificar vídeo, ROI, zoom, consenso, aprendizaje ni las seis skills, salvo documentación/pruebas estrictamente necesarias | **CUMPLE** | Diff V15.9.9→V15.9.10 = 11 archivos: `utilidades/identidad_excel.py`, 2 pruebas nuevas, 1 prueba de autor volteada con `SUPERSEDE` documentado, 5 documentos, `VERSION.txt`. Vídeo/ROI/zoom/consenso/aprendizaje/backend/frontend byte-idénticos; los 6 `SKILL.md` sin cambios (sólo `AGENTS.md`/`.agents/AGENTS.md` con documentación, como permite la condición) |

## Pruebas obligatorias — estado

| Prueba exigida | Resultado |
|---|---|
| `PRUEBAS_ROJAS_V15_9_9_N17.py` (7 pruebas) sobre el repo V15.9.9 completo, ANTES de modificar código | **ROJO reproducido: 5 failed / 2 passed**, mismos fallos y valores que `EVIDENCIA_N17_5_FAILED_2_PASSED.txt` (`evidencia_pruebas/RED_sobre_arbol_V15_9_9.txt`, worktree limpio de `8c916ba`). Tras la corrección: **7/7** sin alterar aserciones |
| `test_v15_9_9_auditoria_regresiones.py` + `test_v15_9_9_ampliacion.py` | 21/21 verdes sin editar (N16) |
| `test_v15_9_8_auditoria_regresiones.py` + `test_v15_9_8_ampliacion.py` | 16/16 verdes sin editar (N15) |
| `python -m pytest pruebas/ -q` | **752 passed / 0 failed / 0 skipped** (3 corridas en árbol final + 1 en cada fresh clone) |
| `node --test pruebas/*.cjs` | **43 pass / 0 fail** (árbol final + ambos fresh clones) |
| No alterar/eliminar/relajar aserciones de pruebas de auditoría | **OK**: ninguna prueba del auditor editada; únicos cambios en pruebas anteriores = 2 funciones de ampliación de AUTOR (V15.9.7) con contrato explícitamente reemplazado por la condición 3, documentado con `SUPERSEDE` |
| Cobertura propia añadida: tablas oficiales, cabeceras no previstas, 3 idiomas, combinadas y colisiones | **OK**: 18 casos nuevos (tabla registrada vacía/poblada/varias/autofiltro/cuerpo, «Temperatura»/«Humedad»/«Color»/«Size» fuera de catálogo, ES/EN/DE, combinadas y fórmulas por suite N13, colisión con proyecto llamado «Temperatura») |
| Ninguna regresión nueva | **OK**: 727 pruebas de V15.9.9 verdes (salvo los 2 volteos documentados, reafirmados en verde con su nueva semántica) + N13-N16 56/56 reejecutados explícitamente |

## Entrega requerida — ubicación

| Entregable | Ubicación |
|---|---|
| Patch incremental desde V15.9.9 y completo desde V15.8.1, con base Git y SHA-256 | `V15_9_10_incremental.patch` (base `8c916ba`, SHA `5fdadecf…87e6`), `V15_9_10_completo.patch` (base `5fbef43`, SHA `a8fd758f…47b7`); tabla completa en `CAMBIOS_V15_9_10.md` |
| Código actualizado | `archivos/` (93 archivos del diff acumulado, byte-idénticos al árbol: 93/93 verificados en fresh clone) |
| Log rojo→verde | `evidencia_pruebas/RED_sobre_arbol_V15_9_9.txt`, `GREEN_arbol_final.txt` |
| Matriz de criterios | este documento |
| Muestras Excel guardadas/releídas | `muestra_excel/` (3 libros + `LEEME_MUESTRA.txt` con SHA-256, hashes de plantilla y script reproductible) |
| Procedimiento de reversión | `ACTUALIZACION_Y_REVERSION_V15_9_10.md` (ensayado en ambos fresh clones: reversión a 0 diferencias) |
| Causa raíz + identificación por ESTRUCTURA (no sólo por nombre) | `INFORME_N17_V15_9_10.md` |
| `AGENTS.md`, seis skills y funcionalidades anteriores conservadas | `archivos/AGENTS.md`, `archivos/.agents/` (6 `SKILL.md` sin cambios), suite completa verde |
| Validaciones de campo declaradas pendientes; sin afirmar aptitud productiva | sección final de este documento y de `CAMBIOS_V15_9_10.md` |
| Integridad del paquete | `SHA256SUMS.txt` (verificable con `sha256sum -c` desde dentro del ZIP extraído) |

## Criterio clave del auditor

Un Excel con tabla vacía `Proyecto | Temperatura` **no se transforma** en
`Proyecto | Proyecto B`: verbatim ×3 idiomas (guardando y releyendo, con
`Table.ref` intacto), tabla visual sin `Table` (bloqueo fail-closed),
empresarial real (muestra 1: borrador con cabecera intacta), BMG real
(borrador con `Projekt | Temperatur` intactos) — en hoja declarada y
complementaria, con cero filas o poblada, en cualquier posición.

## Pendientes de campo (sin declarar producción)

NO ejecutado en este entorno (declarado sin asteriscos): Excel corporativos
representativos del entorno del usuario (incluidos libros con tablas
formales reales), AVI reales anotados (precisión temporal), GPU/RTX,
Windows/macOS, navegador real. Las pruebas sintéticas no sustituyen la
validación de campo. **Esta versión NO se declara apta para producción.**
