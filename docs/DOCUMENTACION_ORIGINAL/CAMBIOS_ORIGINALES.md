# Cambios V15.9.10 — Correctiva de la auditoría N17

**Fecha:** 2026-10-13 · **Versión:** 15.9.10 (`VERSION.txt`)
**Rama:** `codex/ocr-v15-9-10-correctiva` · **Commits:** `b8bce1f` (código y
pruebas) y `1222be6` (documentación y VERSION). Padre: `8c916ba` (V15.9.9).
**Base:** V15.8.1 exacta (`5fbef43`) + V15.9.1 … V15.9.9 + esta correctiva.
**Origen:** `AUDITORIA_ESTRICTA_V_MATRIX_V15_9_9.md` (dictamen NO APTA PARA
PRODUCCIÓN: N16 corregida en los casos comprobados, N17 crítica) e
instrucciones `CORRECCIONES_OBLIGATORIAS_V_MATRIX_V15_9_10.md`, incluidas
sus 7 pruebas incorporadas VERBATIM al repo.
**Alcance acotado por la auditoría:** mapeo de identidad de Excel
(`utilidades/identidad_excel.py`). Sin cambios en vídeo, ROI/zoom, umbrales,
consenso, aprendizaje, checkpoints, backend, pipeline, frontend ni las seis
skills.

## Dos parches (no aplicar los dos sobre el mismo árbol)

| Parche | Base | Bytes | Archivos | SHA-256 |
|---|---|---|---|---|
| `V15_9_10_incremental.patch` | V15.9.9 (`8c916ba`) | 59,203 | 11 | `5fdadecf296dc1f8ff5f6d6c1149c56a302317d893814d271f400c8a4f2887e6` |
| `V15_9_10_completo.patch` | V15.8.1 exacta (`5fbef43`) | 859,337 | 93 | `a8fd758ffd5f9b8ef4be5a4c1f3aff1b28cfc8d718a650630e7f0dafda7247b7` |

Cambios de modo en el diff acumulado: **0** (los `.command` quedan 100755).
`archivos/` = los 93 archivos del diff acumulado, byte-idénticos al árbol
parcheado (verificados contra fresh clone limpio: 93/93, 0 diferencias).

## Corrección de código (hallazgo N17)

| Hallazgo | Archivo | Cambio |
|---|---|---|
| **N17** (tabla Excel FORMAL registrada —`openpyxl Table`, `ref="A2:B2"`, cero filas de datos— con cabecera «Proyecto \| Temperatura» sobrescrita con «Proyecto B» y publicada con identidad verificada, en ES/EN/DE; tabla VISUAL con columna fuera de vocabulario, igual; y caso inverso: tabla real + campo explícito correcto BLOQUEADOS por contradicción falsa de la cabecera) | `utilidades/identidad_excel.py` | La protección pasa de diccionario a ESTRUCTURA. (1) Nueva función única `_celda_en_cabecera_estructural(hoja, fila, columnas)`: recorre `hoja.tables` (`Table.ref` con `range_boundaries`, `headerRowCount != 0`, posición arbitraria) y `hoja.auto_filter.ref`; se consulta AL INICIO de `_clasificar_par` —por tanto en las rutas DECLARADA y COMPLEMENTARIA, que ya compartían el clasificador— antes de distinguir explícita/desnuda y antes de cualquier escritura. Celda en fila de cabecera de tabla registrada o autofiltro ⇒ `(False, None)`: omisión silenciosa (nunca contradicción), con `ref`, nombres de columna y formato intactos, sin importar texto, idioma, separador o número de filas de datos. (2) Sin objeto `Table` ni contrato explícito, el par DESNUDO `Proyecto \| valor` es ambiguo: nuevo `_evidencia_valor_proyecto` exige evidencia POSITIVA del contiguo (coherencia con la identidad vía `_nucleo_nombre`/texto visible, o mención inicial de proyecto —nuevo `_MENCION_INICIAL`: proyecto/project/projekt/pröjekt/projeto + frontera de palabra). Sin evidencia ⇒ fail-closed: contradicción estructural con hoja/celda y detalle «no se escribe por suposición (revisión o mapeo explícito requerido)», `publicable=False`, nada se modifica. (3) Cabecera legítima + campo explícito correcto ⇒ sólo se actualiza ese campo y se PUBLICA sin contradicciones falsas. (4) Se conservan: contiguo vacío ⇒ relleno (N10), cabecera reconocible por vocabulario ⇒ omisión silenciosa (N16, segunda capa), política de editabilidad N13 (fórmulas/números/combinadas/estilos), ramas ambigua y tabular sin cambios. |

## Pruebas

| Archivo | Cambio |
|---|---|
| `pruebas/test_v15_9_10_auditoria_regresiones.py` | NUEVO: las 7 pruebas del auditor, VERBATIM (rojo **5 failed / 2 passed** sobre `8c916ba`, mismos fallos y valores que `EVIDENCIA_N17_5_FAILED_2_PASSED.txt`; verde 7/7 después). Ninguna aserción relajada. |
| `pruebas/test_v15_9_10_ampliacion.py` | NUEVO: 18 casos (tabla formal POBLADA guardada/releída con `Table.ref` intacto, dos tablas por hoja en posiciones arbitrarias releídas, autofiltro `A2:B4` que protege la cabecera y permite publicar con campo explícito, etiqueta explícita en cabecera de tabla no sustituida, par explícito en CUERPO de tabla sí mapeado, tabla visual desconocida + campo explícito ⇒ bloqueo fail-closed con la celda señalada, evidencia positiva ×4 —`Proyecto A`, `Project North`, valor ya coherente, `project_id`—, contiguo vacío se rellena, colisión con proyecto llamado exactamente «Temperatura» —desnuda coherente publica intacta, explícita mapea—, campo explícito ES/EN/DE ×3, empresarial con tabla formal vacía ⇒ borrador + hash + releído con `TablaVacia` intacta, empresarial con tabla + explícito ⇒ oficial publicado + hash, BMG real con tabla formal en `Rangos` ⇒ borrador + cabeceras + hash del repo intactos). |
| `pruebas/test_v15_9_7_ampliacion.py` | VOLTEO DOCUMENTADO (contrato reemplazado explícitamente por la exigencia 3 del auditor): `test_n14_pares_desnudos_abreviados_en_varias_hojas_se_mapean` (contiguos «A»/«PRJ-001» sin evidencia ya no se sobrescriben: intactos + contradicción estructural + `publicable=False`; el par explícito declarado sigue mapeándose) y `test_n14_campo_desnudo_en_tres_idiomas_se_mapea` (contiguo «Old» ya no se sobrescribe en ningún idioma). Conservan nombres y llevan docstring `SUPERSEDE` con la motivación; la cobertura positiva ES/EN/DE se mantiene en la ampliación nueva (`test_n14_campo_explicito_en_tres_idiomas_se_mapea`). |
| Pruebas del AUDITOR (V15.9.2-V15.9.9, verbatim N13-N16 incluidas) | NINGUNA editada, eliminada ni relajada; todas verdes tal cual. |

**Resultado:** `python -m pytest pruebas/ -q` → **752 passed / 0 failed / 0
skipped** (3+ corridas, también en los dos fresh clones) y
`node --test pruebas/*.cjs` → **43/43**. Regresiones de auditoría acumuladas
N13-N16 (56 pruebas) reejecutadas explícitamente. Sin cambios en backend,
pipeline ni frontend.

## Documentación

- `docs/informes/RESULTADOS_PRUEBAS_V15_9_10.md` (rojo→verde y suite).
- `docs/informes/REVISION_SKILLS_V15_9_10.md` (revisión trazable por skill).
- `docs/historial/README_CORRECCIONES_VERSIONES.md` (entrada V15.9.10) y
  `docs/historial/LEEME_V15_9_10_N17_ESTRUCTURA_FORMAL.md`.
- `AGENTS.md` (nueva sección «Estructura formal de las tablas Excel») y
  `.agents/AGENTS.md` (enlaces de evidencia actualizados).
- `VERSION.txt` → 15.9.10.

Sin dependencias nuevas (sólo `openpyxl`, ya requerido); todo offline;
datos persistidos (`.aprendizaje/`, SQLite, `proyectos.json`, consensos,
checkpoints, ROI, zoom, aprendizaje, cola) intactos: el diff no los toca.
Incidencia de entorno documentada (no atribuible al parche): la restauración
del sandbox dejó los `.command` sin bit ejecutable mientras git registraba
100755; restaurado con `chmod 755` antes de las corridas finales.
