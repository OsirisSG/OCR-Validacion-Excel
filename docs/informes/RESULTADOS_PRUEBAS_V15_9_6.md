# Resultados de pruebas · V15.9.6 (correctiva de la auditoría N10-N12)

**Fecha:** 2026-10-13 · **Rama:** `codex/ocr-v15-9-6-correctiva`
**Base:** V15.9.5 (`d3c1ee6`) sobre V15.8.1 exacta (`5fbef43`).
**Origen:** `AUDITORIA_ESTRICTA_V_MATRIX_V15_9_5.md` (dictamen NO APROBADO:
N10 crítica, N11 alta, N12 media-alta) y
`CORRECCIONES_OBLIGATORIAS_V_MATRIX_V15_9_6.md`.
**Alcance acotado por la auditoría:** contrato de identificación Excel; no se
reescriben motor de vídeo, ROI/zoom ni las seis skills.

## 1. Puerta rojo → verde

Los 5 casos literales del auditor (`PRUEBAS_ROJAS_V15_9_5_N10_N12.py`, 3
funciones con una parametrizada ×3) se incorporaron VERBATIM como
`pruebas/test_v15_9_6_auditoria_regresiones.py` y se ejecutaron ANTES de
corregir sobre el árbol V15.9.5 completo:

| Paso | Comando | Resultado |
|---|---|---|
| ROJO | `PYTHONPATH=. python -m pytest pruebas/test_v15_9_6_auditoria_regresiones.py -q` (árbol `d3c1ee6`) | **5 failed** (coincide con el «5 failed in 0.58s» del auditor) |
| VERDE | mismo comando tras la corrección | **5 passed** |

Ninguna aserción fue eliminada ni debilitada.

## 2. Correcciones y su cobertura

### N10 (CRÍTICA) — mapeo estructural de pares etiqueta/valor en todas las hojas
`utilidades/identidad_excel.py`: nueva función `mapear_pares_etiqueta_valor`
complementa (no sustituye) la revisión de textos libres — el caso auditado
(`Indicadores!A1="Proyecto:"`, `B1="A"`) es invisible para un escáner de texto
porque el valor no lleva la palabra clave.

Contrato implementado:
- Recorre TODAS las hojas elegibles del entregable (V15.9.5: visibles +
  declaradas − exentas), sin límite de filas.
- Sólo etiquetas EXPLÍCITAS con separador (`Proyecto:`/`Project:`/`Projekt:`/
  `Projeto:`, regex `_ETIQUETA_EXPLICITA`). Las cabeceras de tabla SIN
  separador (columna «Proyecto» de trazabilidad/evidencia) no son campos de
  identidad y no se mapean — sin esta distinción se corrompían cabeceras
  generadas y se anulaba P08 en BMG.
- Campo único (fila con etiqueta + valor) y valor editable (texto plano o
  vacío) ⇒ se sustituye SÓLO la celda de valor por el nombre visible
  autoritativo y se REGISTRA en `celdas_complementarias` (hoja, etiqueta,
  celda, valor anterior); el bloque de identidad lista cada celda corregida.
- Valor no resoluble sin riesgo (fórmula, `MergedCell`, valor no textual) ⇒
  contradicción ESTRUCTURAL (`estructural=True`) que bloquea sin reemplazar.
- Fila tabular con etiqueta explícita (más contenido a la derecha) ⇒ ambigua:
  bloquea, salvo que el valor ya coincida con la identidad.
- Las hojas exentas (histórico/evidencia declaradas por el generador)
  conservan sus pares históricos intactos; la exención queda documentada.
- `identidad_verificada` admite ahora celdas identificadas declaradas O
  complementarias (coherencia entre resumen y hojas auxiliares, requisito 4
  de aprobación).

Pruebas: caso literal N10 + `test_n10_par_en_hoja_adicional_se_corrige_y_se_registra`,
`test_n10_par_con_valor_vacio_se_rellena`,
`test_n10_par_con_valor_numerico_bloquea_sin_reemplazar`,
`test_n10_fila_tabular_con_etiqueta_explicita_bloquea` (con variante
coherente), `test_n10_hoja_exenta_conserva_su_par_historico_intacto`,
`test_n10_sin_asignar_rellena_el_par_complementario_como_pendiente`,
`test_n10_empresarial_par_en_hoja_adicional_publica_y_plantilla_intacta`,
`test_n10_bmg_real_par_en_rangos_publica_con_identidad_coherente` (BMG real,
hoja `Rangos`, idioma DE, título con `Stufe 1ST`, plantilla del repo
byte-intacta).

### N11 (ALTA) — comparación del nombre COMPLETO, sin coincidencia parcial
Se eliminó la verificación por tokens compartidos (`permitidos`). Nuevas
funciones: `_plegar` (normalización trivial: casefold + NFD sin diacríticos +
guiones/barras como espacio + colapso), `_nucleo_nombre` (sin palabras
funcionales ni clave de mención inicial: «Project B» y «Proyecto B» tienen el
mismo núcleo), `_representaciones_identidad` (nombre_proyecto, project_id,
nombre visible y alias SÓLO si están registrados explícitamente, cada uno
como unidad completa) y `_analizar_referencia` reescrito: construye la frase
de nombre (mención + segmentos no-metadato) y la compara completa en nivel
estricto y laxo (sin sufijos numéricos/versión sueltos: «B 2026» ≡ «B»).
Coincidencia parcial ⇒ contradicción con detalle («el nombre leído «beta» no
coincide con el nombre completo… la coincidencia parcial no verifica la
identidad»). Sin nombre resoluble ⇒ ambigüedad fail-closed (frase conservada
de V15.9.5).

Pruebas: caso literal N11 + `test_n11_nombre_compuesto_exige_coincidencia_completa`
(Beta Sur válido; Beta/Sur/Beta Norte bloqueados, con detalle),
`test_n11_variantes_triviales_de_tildes_se_aceptan` (Ñu Ägil ≡ NU AGIL),
`test_n11_alias_registrado_explicitamente_valida_y_no_registrado_no` (PB-7
sí, PB-8 no), `test_n11_id_tecnico_distinto_del_nombre_visible_valida_completo`
(PRJ-2026-07 sí; PRJ-2026-70 no).

### N12 (MEDIA-ALTA) — etapas/fases contextuales, no permiso global
`_CLAVES_ETAPA_FASE` (Etapa/Stage/Fase/Phase/Stufe + plurales, ES/EN/DE) y
`_VALORES_ETAPA_FASE` (1st, 2st, 3rd, nach, vor, legacy — valores reales del
flujo V-Matrix). `_segmento_es_metadato` ampliado: un segmento es metadato si
es puramente numérico/fecha/versión, o si contiene una clave (de metadato o
de etapa/fase) y el resto son números/valores de etapa. Un valor de etapa
SUELTO («Reporte del Proyecto 1ST») NO es metadato: se compara como nombre y
bloquea si no coincide (podría ser otro proyecto).

Pruebas: caso literal N12 (×3) + `test_n12_etapa_o_fase_contextual_no_bloquea`
(10 títulos: ES/EN/DE, delimitadores `— | ( ) -`, combinación con año y
revisión), `test_n12_valor_de_etapa_suelto_no_es_permiso_global` (1ST/NACH/
VOR como nombre ajeno bloquean), `test_n12_identidad_con_etapa_legitima_en_su_nombre_valida`
(«Proyecto B 1ST» valida completo; «Proyecto B» contra esa identidad bloquea).

## 3. Archivos nuevos / actualizados

| Archivo | Cambio |
|---|---|
| `pruebas/test_v15_9_6_auditoria_regresiones.py` | NUEVO: 5 casos literales del auditor (verbatim). |
| `pruebas/test_v15_9_6_ampliacion.py` | NUEVO: 35 casos (N10 ×8, N11 ×13 parametrizados, N12 ×13, integración ×2 + BMG real). |
| `utilidades/identidad_excel.py` | N10/N11/N12 (contratos descritos arriba). |
| `pruebas/test_v15_9_5_ampliacion.py` | UN test volteado documentadamente: `test_n7_celda_mapeada_no_garantiza_las_demas_referencias` — N10 supersede el bloqueo V15.9.5 para pares etiqueta/valor en hojas elegibles (ahora se corrigen y registran); la garantía original se conserva y amplía en el mismo test (título libre ajeno sigue bloqueando intacto; par con fórmula bloquea sin reemplazo). Ningún otro test antiguo fue editado o eliminado. |

Sin cambios en generadores, backend, pipeline ni frontend: los estados
`publicable`/`identidad_verificada`/`estado_identidad`/`pendiente_sin_asignar`
y las rutas de borrador de V15.9.4/V15.9.5 se conservan; `celdas_complementarias`
se añade a los metadatos y al bloque visible.

## 4. Regresiones (N1-N9 y anteriores)

- `pruebas/test_v15_9_5_auditoria_regresiones.py`: 3/3 verdes (sin tocar).
- `pruebas/test_v15_9_4_auditoria_regresiones.py`: 7/7 verdes (sin tocar).
- `pruebas/test_v15_9_4_ampliacion.py`: 23/23 verdes (sin tocar).
- `pruebas/test_v15_9_5_ampliacion.py`: 24/24 verdes (con el volteo
  documentado arriba).
- C1-C7, CRIT-01..04/ALTA-05, consenso/vídeo, ROI, zoom, matriz,
  persistencia, cola Excel, descargas diferenciadas, API de exportación:
  verdes.
- **Suite completa:** `python -m pytest pruebas/ -q` → **671 passed /
  0 failed / 0 skipped** (3 corridas consecutivas, ~57 s).
- **Node:** `node --test pruebas/*.cjs` → **43/43**.

## 5. Verificación sobre árbol exacto (fresh clone)

Clon limpio de la base V15.8.1 (`5fbef43`) + parche acumulado
`V15_9_6_completo.patch`: suite 671/0/0 y node 43/43; `archivos/` del paquete
byte-idéntico al árbol parcheado; `.command` en 100755; `git apply -R`
devuelve el árbol idéntico a la base. Incremental sobre V15.9.5 (`d3c1ee6`)
verificado igualmente (ver `entrega/V15_9_6_CORRECTIVA_N10_N12/evidencia_pruebas/`).

## 6. Impacto operativo

- Un Excel con «Proyecto B» en el resumen y «A» como proyecto visible en
  cualquier otra hoja elegible ya no puede publicarse: o el par
  etiqueta/valor se corrige de forma específica y registrada, o la salida
  queda bloqueada señalando hoja/celda.
- Los nombres compuestos exigen coincidencia completa normalizada; una
  palabra compartida ya no valida la identidad.
- Los títulos con etapa/fase del flujo (1ST/2ST/3RD, NACH, VOR) dejan de
  bloquearse cuando van con su clave contextual, sin permiso global que
  debilite la detección.

## 7. Pendientes de campo (sin asteriscos: no aprobados aquí)

- macOS real (permisos y lanzamiento de `.command`), Windows real.
- Navegador real: seleccionar proyecto, zoom/ROI sin deriva, recálculo,
  exportación bloqueada/pendiente etiquetada.
- AVI empresariales de alta velocidad ANOTADOS: FPS nativo vs reproducción,
  criterio 3/4, falsos positivos/negativos y error temporal por fotograma.
- GPU/RTX y rendimiento; instalación corporativa.
- Verificación visual en Excel real de los bloques de identidad generados
  (las pruebas validan contenido mediante openpyxl).
