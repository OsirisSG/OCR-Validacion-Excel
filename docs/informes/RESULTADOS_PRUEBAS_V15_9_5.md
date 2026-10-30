# Resultados de pruebas · V15.9.5 (correctiva de la auditoría N7-N9)

**Fecha:** 2026-10-12 · **Rama:** `codex/ocr-v15-9-5-correctiva`
**Base:** V15.9.4 (`616e55e`) sobre V15.8.1 exacta (`5fbef43`).
**Origen:** `AUDITORIA_ESTRICTA_V_MATRIX_V15_9_4.md` (dictamen NO APROBADO:
N7 crítica, N8 media-alta, N9 alta) y
`CORRECCIONES_OBLIGATORIAS_V_MATRIX_V15_9_5.md`.

## 1. Puerta rojo → verde

Los 3 casos literales del auditor
(`PRUEBAS_ROJAS_V15_9_4_N7_N9.py`) se incorporaron VERBATIM como
`pruebas/test_v15_9_5_auditoria_regresiones.py` y se ejecutaron ANTES de
corregir sobre el árbol V15.9.4 completo:

| Paso | Comando | Resultado |
|---|---|---|
| ROJO | `PYTHONPATH=. python -m pytest pruebas/test_v15_9_5_auditoria_regresiones.py -q` (árbol `616e55e`) | **3 failed** (N7, N8 y N9 reproducidos) |
| VERDE | mismo comando tras la corrección | **3 passed** |

## 2. Correcciones y su cobertura

### N7 (CRÍTICA) — todas las hojas visibles del entregable se examinan
`utilidades/identidad_excel.py`: nuevo contrato `hojas_del_entregable`
(todas las hojas VISIBLES del libro de salida, aunque el generador no las
declare en `hojas_busqueda`) + examen de cabeceras/pies de página
(`oddHeader/evenHeader/firstHeader` y pies). Excepción explícita y
documentada: `hojas_exentas` (histórico/evidencia/documentación estática),
que queda escrita en el bloque de identidad. Las hojas ocultas no son
entregable visible y se conservan intactas. `reporte_bmg.py` exime únicamente
su hoja de diccionario de datos (documentación estática de campos generada
por el propio generador; sus textos describen reglas OCR y no identidad).
Ningún texto se reemplaza jamás (sin buscar-y-reemplazar global).

Pruebas: caso literal N7 + `test_n7_hoja_visible_no_declarada_bloquea_publicacion`,
`test_n7_hoja_oculta_no_forma_parte_del_entregable_visible`,
`test_n7_exencion_documentada_para_hoja_de_historico` (con y sin exención),
`test_n7_cabecera_de_pagina_con_otro_proyecto_bloquea` (cabecera Y pie),
`test_n7_bmg_hoja_rangos_con_titulo_ajeno_bloquea` (plantilla BMG real, hoja
`Rangos` fuera de `hojas_busqueda`; control limpio sin falsos positivos +
exención documentada), `test_n7_celda_mapeada_no_garantiza_las_demas_referencias`.

### N8 (MEDIA-ALTA) — nombre del proyecto separado de metadatos del título
`_analizar_referencia` parte el texto tras la mención en segmentos
(delimitadores `— – | · , ( )`, guion espaciado) y clasifica cada segmento:
metadato (año, semana, mes, trimestre, versión, revisión, fecha, etapa —
palabras clave ES/EN/DE + patrones de año/fecha/versión) o nombre. Sólo un
token alfabético que no pertenezca a la identidad autoritativa (nombre
visible, `project_id`) ni sea metadato constituye contradicción. Una
referencia SIN ningún nombre resoluble (p. ej. sólo «2026») es ambigua ⇒
fail-closed, y el bloque explica exactamente qué no se pudo verificar
(`detalle`). No hay ninguna excepción ad-hoc al texto «Año 2026»: es el
contrato general de metadatos.

Pruebas: caso literal N8 + `test_n8_titulo_correcto_con_anio_publica_en_los_tres_idiomas`
(ES/EN/DE parametrizado), `test_n8_metadatos_de_prueba_no_generan_falsa_contradiccion`
(semana/Week/Woche, versión, fecha, revisión — 6 variantes),
`test_n8_nombre_compuesto_e_id_distinto_al_nombre_visible`,
`test_n8_nombres_parecidos_sigue_bloqueando` (A vs AB y AB vs A),
`test_n8_referencia_ambigua_sin_nombre_resoluble_bloquea_con_explicacion`.

### N9 (ALTA) — decisión confirmada ≠ identidad verificada
Tres estados separados en metadatos y en el bloque visible:
`decision_usuario_confirmada` (el usuario declaró proyecto o eligió «Sin
asignar» expresamente), `identidad_verificada` (celda mapeada Y NO
«Sin asignar» Y sin contradicciones) y `estado_identidad`
(`verificada` / `pendiente_sin_asignar` / `bloqueada_contradiccion` /
`no_verificada`). Política de publicación explícita: verificada ⇒ publica;
«Sin asignar» sin contradicciones ⇒ publica como PENDIENTE con estado
diferenciado (P02, jamás como proyecto verificado); contradicción o
plantilla sin celda identificable ⇒ borrador bloqueado; orígenes legacy
conservan P11. Propagación: `/api/resultados/exportar` añade
`identidad_verificada`, `pendiente_sin_asignar`, `estado_publicacion =
"pendiente_publicada"` y `estado_identidad` por archivo; `pipeline.py` añade
`excel_pendiente_sin_asignar` y mensaje final diferenciado; el frontend
muestra aviso PENDIENTE separado del éxito y del bloqueado (ES/EN/DE).

Pruebas: caso literal N9 + `test_n9_sin_asignar_es_decision_pendiente_no_identidad_verificada`,
`test_n9_proyecto_declarado_con_celda_mapeada_es_verificado`,
`test_n9_sin_asignar_con_titulo_historico_queda_bloqueado`,
`test_n9_plantilla_sin_celda_identificable_no_esta_verificada`,
`test_n9_export_api_distingue_pendiente_de_verificado`.

## 3. Archivos nuevos / actualizados

| Archivo | Cambio |
|---|---|
| `pruebas/test_v15_9_5_auditoria_regresiones.py` | NUEVO: 3 casos literales del auditor (verbatim). |
| `pruebas/test_v15_9_5_ampliacion.py` | NUEVO: 24 casos (N7 ×6, N8 ×13 parametrizados, N9 ×5). |
| `pruebas/test_v15_9_5_estados_ui.cjs` | NUEVO: 2 contratos de interfaz (aviso pendiente + ES/EN/DE). |
| `utilidades/identidad_excel.py` | N7/N8/N9 (contratos y política descritos arriba). |
| `reporte_bmg.py` | Exención documentada de la hoja de diccionario (N7). |
| `dashboard/backend/app.py` | Estados pendientes en `/api/resultados/exportar` (N9). |
| `pipeline.py` | `excel_pendiente_sin_asignar` + mensaje diferenciado (N9). |
| `dashboard/frontend/app.js`, `dashboard/frontend/i18n.js` | Aviso PENDIENTE y textos ES/EN/DE (N9). |

## 4. Regresiones (N1-N6 y anteriores)

- `pruebas/test_v15_9_4_auditoria_regresiones.py`: **7/7 verdes** (sin tocar).
- `pruebas/test_v15_9_4_ampliacion.py`: **23/23 verdes** (el control BMG
  limpio sigue sin falsos positivos gracias a la exención documentada).
- `pruebas/test_v15_9_3_criticos.py`, `test_v15_9_2_proyecto_c7.py`,
  `test_v15_9_2_correcciones_c1_c7.py`, C1-C7, consenso/vídeo, ROI, zoom,
  matriz, persistencia, cola Excel, descargas: verdes sin cambios.
- **Suite completa:** `python -m pytest pruebas/ -q` → **631 passed /
  0 failed / 0 skipped** (3 corridas consecutivas, ~54 s).
- **Node:** `node --test pruebas/*.cjs` → **43/43**.

## 5. Verificación sobre árbol exacto (fresh clone)

Clon limpio de la base V15.8.1 (`5fbef43`) + parche acumulado
`V15_9_5_completo.patch`: suite 631/0/0 y node 43/43 verdes; `archivos/` del
paquete byte-idéntico al árbol parcheado; `git apply -R` devuelve el árbol
idéntico a la base (ver `entrega/V15_9_5_CORRECTIVA_N7_N9/evidencia_pruebas/`).

## 6. Impacto operativo

- Una plantilla con identidad de otro proyecto en CUALQUIER hoja visible (o
  en cabecera/pie) ya no puede publicarse: queda borrador bloqueado con la
  referencia exacta (hoja, celda, texto y motivo).
- Los títulos legítimos con año/semana/versión/fecha dejan de bloquearse
  (falsos positivos N8 eliminados sin abrir nombres ajenos).
- «Sin asignar» se entrega como PENDIENTE con estado diferenciado en Excel,
  API, pipeline y UI; nunca figura como identidad verificada.

## 7. Pendientes de campo (sin asteriscos: no aprobados aquí)

- macOS real (permisos y lanzamiento de `.command`), Windows real.
- Navegador real: seleccionar proyecto, zoom/ROI sin deriva, recálculo,
  exportación bloqueada/pendiente etiquetada.
- AVI empresariales de alta velocidad ANOTADOS: FPS nativo vs reproducción,
  criterio 3/4, falsos positivos/negativos y error temporal por fotograma.
- GPU/RTX y rendimiento; instalación corporativa.
