# Resultados de pruebas · V15.9.10 (correctiva de la auditoría N17)

**Fecha:** 2026-10-13 · **Rama:** `codex/ocr-v15-9-10-correctiva`
**Base:** V15.9.9 (`8c916ba`) sobre V15.8.1 exacta (`5fbef43`).
**Origen:** `AUDITORIA_ESTRICTA_V_MATRIX_V15_9_9.md` (dictamen NO APTA PARA
PRODUCCIÓN: N16 corregida en los casos comprobados, N17 crítica) y
`CORRECCIONES_OBLIGATORIAS_V_MATRIX_V15_9_10.md`.
**Alcance acotado por la auditoría:** mapeo de identidad de Excel
(`utilidades/identidad_excel.py`); sin cambios en módulos de vídeo, ROI,
zoom, umbrales, consenso, aprendizaje, checkpoints, frontend ni backend.

## 1. Puerta rojo → verde

Las pruebas literales del auditor (7 funciones) se incorporaron VERBATIM
como `pruebas/test_v15_9_10_auditoria_regresiones.py` y se ejecutaron ANTES
de corregir sobre el árbol V15.9.9 completo (commit `8c916ba`):

| Paso | Comando | Resultado |
|---|---|---|
| ROJO | `PYTHONPATH=. python -m pytest pruebas/test_v15_9_10_auditoria_regresiones.py -q` | **5 failed, 2 passed** — mismos 5 fallos y mismos valores que `EVIDENCIA_N17_5_FAILED_2_PASSED.txt` del auditor (tabla formal ES/EN/DE sobrescrita, tabla formal + campo explícito bloqueada por contradicción falsa, tabla visual con columna fuera de vocabulario sobrescrita) |
| VERDE | mismo comando tras la corrección | **7 passed** (5 corregidos + 2 controles conservados: `Proyecto | Proyecto A` y `Proyecto: | Proyecto A`) |

Ninguna aserción del auditor fue eliminada ni relajada. Log rojo completo
en el paquete (`evidencia_pruebas/RED_sobre_arbol_V15_9_9.txt`).

## 2. Corrección y su cobertura

### N17 (CRÍTICA) — cabecera de tabla FORMAL ignorada; par desnudo ambiguo escrito por suposición

Causa raíz doble:

1. `_clasificar_par` nunca inspeccionaba la estructura formal del libro:
   una celda en la fila de cabecera de una tabla Excel registrada
   (`openpyxl Table`, `Table.ref`) o de un autofiltro se trataba como
   cualquier otro par etiqueta/valor. Con «Proyecto | Temperatura» en
   `ref="A2:B2"` (cero filas de datos), «Temperatura» no estaba en el
   diccionario `_CABECERAS_COLUMNA` de V15.9.9, la rama `unico` lo
   consideraba campo único y se sobrescribía con «Proyecto B» publicando
   con identidad verificada. Un diccionario de palabras nunca puede cerrar
   esta ambigüedad: cualquier cabecera fuera de catálogo la reabre.
2. En el caso inverso (tabla real + par explícito `Proyecto: | Proyecto A`
   debajo), la cabecera se preservaba pero el par desnudo `Proyecto |
   Temperatura` de la fila de cabecera se registraba como CONTRADICCIÓN y
   bloqueaba indebidamente una salida correcta.

Contrato implementado (una única función estructural compartida por la
ruta DECLARADA y la COMPLEMENTARIA, exigencia 6 del auditor):

- `_celda_en_cabecera_estructural(hoja, fila, columnas)`: recorre
  `hoja.tables` (con `headerRowCount != 0`, posición arbitraria vía
  `range_boundaries(Table.ref)`) y `hoja.auto_filter.ref`. Se consulta AL
  INICIO de `_clasificar_par`, antes de distinguir explícita/desnuda y
  antes de cualquier escritura: si la fila es la de cabecera del rango y
  alguna de las dos celdas cae dentro, el par se OMITE en silencio — nunca
  se mapea, nunca se registra como contradicción, la tabla conserva
  `ref`, nombres de columna y formato. Sin importar texto, idioma,
  separador o número de filas de datos (vacías y pobladas, varias tablas
  por hoja).
- Sin objeto `Table` ni autofiltro, un par DESNUDO `Proyecto | valor` es
  ambiguo: sólo se escribe si el contiguo tiene EVIDENCIA POSITIVA de ser
  nombre de proyecto (`_evidencia_valor_proyecto`: coincide con la
  identidad declarada —núcleo o texto visible— o empieza por mención de
  proyecto: `Proyecto`/`Project`/`Projekt`/`Pröjekt`/`Projeto`). En caso
  contrario (`Temperatura`, `Color`, `A`, `PRJ-001`, `Old`) ⇒ fail-closed:
  contradicción estructural con hoja/celda y detalle «no se escribe por
  suposición (revisión o mapeo explícito requerido)», `publicable=False`.
  El contiguo VACÍO sigue rellenándose (comportamiento N10) y la cabecera
  reconocible por vocabulario sigue omitiéndose en silencio (N16, segunda
  capa).
- Cabecera legítima + campo explícito correcto ⇒ se actualiza sólo ese
  campo y se publica SIN contradicciones falsas (la cabecera ya no se
  registra como bloqueo).
- Etiqueta explícita dentro de una cabecera de tabla registrada ⇒ también
  protegida (la estructura manda sobre el texto). En el CUERPO de la tabla
  (filas de datos) rige la política normal: un par explícito se mapea.
- Sólo cabecera, sin ningún campo verificable ⇒ sin celdas mapeadas,
  `identidad_verificada=False`, `estado_identidad=no_verificada`,
  `publicable=False` y borrador no publicable (P08), comunicado por API/UI
  con el contrato N6 existente.

Pruebas: 7 verbatim + 18 casos de ampliación — tabla formal POBLADA con
datos y guardado/releído (`Table.ref` intacto), dos tablas por hoja en
posiciones arbitrarias (D5:E5 y B9:C9) releídas, autofiltro `A2:B4` que
protege la cabecera y permite publicar con campo explícito en A1/B1,
etiqueta explícita en cabecera de tabla no sustituida, par explícito en
cuerpo de tabla sí mapeado, tabla VISUAL desconocida + campo explícito ⇒
bloqueo fail-closed con la celda señalada, evidencia positiva ×4
(`Proyecto A`, `Project North`, valor ya coherente, project_id), contiguo
vacío se rellena, colisión semántica con proyecto llamado exactamente
«Temperatura» (desnuda coherente ⇒ publica intacta; explícita ⇒ mapea),
campo explícito ES/EN/DE ×3, generador empresarial con tabla formal vacía
⇒ borrador + hash de plantilla + releído con `TablaVacia` intacta,
empresarial con tabla + campo explícito ⇒ oficial publicado + cabecera
intacta + hash, y BMG real (`plantillas/reporte_bmg_1st_2st.xlsx`) con
tabla formal añadida en `Rangos` ⇒ borrador + cabeceras + hash del repo
intactos.

### Contratos anteriores reemplazados (documentado, sin ediciones silenciosas)

La exigencia 3 del auditor («tratar como AMBIGUO el par desnudo sin
evidencia positiva, en lugar de sobrescribir por defecto») reemplaza
EXPLÍCITAMENTE el comportamiento que afirmaban 2 pruebas de
`pruebas/test_v15_9_7_ampliacion.py` (4 casos parametrizados), escritas
por este mismo autor en V15.9.7:

- `test_n14_pares_desnudos_abreviados_en_varias_hojas_se_mapean`: los
  contiguos «A» y «PRJ-001» ya no se sobrescriben; quedan intactos, se
  registran como contradicción estructural y bloquean la publicación. El
  par explícito declarado de `Resumen` sigue mapeándose.
- `test_n14_campo_desnudo_en_tres_idiomas_se_mapea`: el contiguo «Old» ya
  no se sobrescribe en ningún idioma; la cobertura POSITIVA ES/EN/DE se
  conserva en `test_n14_campo_explicito_en_tres_idiomas_se_mapea` (nueva,
  V15.9.10).

Ambas funciones conservan su nombre y llevan un docstring `SUPERSEDE` con
la motivación. La garantía original de N14 (nunca publicar en silencio con
un valor ajeno visible) queda reforzada: antes se «corregía» el valor por
suposición; ahora no se escribe nada sin evidencia. Ninguna prueba del
AUDITOR (V15.9.2-V15.9.9, incluidos los verbatim N13-N16) fue editada:
todas verdes tal cual.

## 3. Suite completa sobre el árbol exacto

| Suite | Comando | Resultado |
|---|---|---|
| Python (3 corridas) | `PYTHONPATH=. python -m pytest pruebas/ -q` | **752 passed / 0 failed / 0 skipped** (727 de V15.9.9 + 7 verbatim N17 + 18 ampliación), ~53 s por corrida |
| Node | `node --test pruebas/*.cjs` | **43 pass / 0 fail** (frontend sin cambios; incluye los contratos C7/N6/N9/UI) |

Regresiones N1-N16: verdes sin editar ninguna prueba de auditoría. Los 2
volteos documentados son pruebas de ampliación de autor (V15.9.7), no del
auditor. Paridad Excel/dashboard: la distinción borrador bloqueado vs
exportación oficial sigue cubierta por las pruebas de respuesta API N6 y
los contratos UI node, sin cambios de contrato en esta versión.

Incidencia de entorno documentada (no atribuible al parche, igual que en
V15.9.8/V15.9.9): la restauración del sandbox dejó los `.command` sin bit
ejecutable en el árbol de trabajo mientras git registraba 100755; se
restauró con `chmod 755` antes de las corridas finales y el test C5 quedó
verde. fastapi/httpx reinstalados para la suite del backend. Entorno:
Python 3.13, node v20, Linux.

## 4. Integridad verificada

- Plantilla BMG real del repo y plantillas empresariales: hash SHA-256
  antes/después idéntico en las pruebas que las usan (copias temporales),
  con Excel guardados y RELEÍDOS: persistencia de `Table.ref`, nombres de
  columna de las tablas, cabeceras, fórmulas, combinadas, números y
  estilos intactos.
- Persistencia (`.aprendizaje/`, SQLite, `proyectos.json`, consensos,
  checkpoints, ROI, zoom, aprendizaje, cola): el diff no toca esas rutas;
  suite completa verde; umbrales y consenso sin cambios.
- Offline: sin dependencias nuevas (sólo `openpyxl`, ya requerido).
- Muestras Excel del paquete (`muestra_excel/`): N17 tabla formal vacía en
  hoja declarada ⇒ borrador con `TablaVacia` intacta (empresarial real),
  N17 tabla formal + campo explícito ⇒ publicado con cabecera intacta,
  control campo único desnudo con mención ⇒ publicado y corregido.

## 5. Pendientes de campo (sin declarar producción)

Se mantienen los límites declarados por la auditoría: Excel corporativos
representativos del entorno del usuario, AVI reales anotados (precisión
temporal), GPU, Windows/macOS y navegador real. Las pruebas sintéticas no
sustituyen la validación de campo; nada de ello se declara aprobado en
esta versión.
