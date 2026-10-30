# V15.9.10 — Protección ESTRUCTURAL de cabeceras de tablas Excel (N17)

Correctiva tras el RECHAZO para producción de V15.9.9
(`AUDITORIA_ESTRICTA_V_MATRIX_V15_9_9.md`,
`CORRECCIONES_OBLIGATORIAS_V_MATRIX_V15_9_10.md`).

## Qué fallaba

V15.9.9 defendía las cabeceras con un DICCIONARIO de palabras
(`_CABECERAS_COLUMNA`: Etapa/Stage/Stufe, Caso/Case/Fall…). Un catálogo
nunca resuelve la ambigüedad: cualquier cabecera fuera de vocabulario la
reabría. Con una tabla Excel FORMAL registrada (`openpyxl Table`,
`ref="A2:B2"`, cero filas de datos) y cabecera «Proyecto | Temperatura»,
V15.9.9 sobrescribía «Temperatura» con «Proyecto B» y PUBLICABA con
identidad verificada. Lo mismo ocurría con tablas visuales (sin objeto
`Table`) cuya columna no estaba catalogada.

Caso inverso: con una tabla real y un campo explícito correcto
(`Proyecto: | Proyecto A`) debajo, la cabecera se preservaba pero se
registraba como CONTRADICCIÓN y bloqueaba indebidamente una salida válida
(falso negativo).

## Qué se cambió

La verdad ESTRUCTURAL del libro manda sobre cualquier heurística de texto,
con UNA única función compartida por la ruta declarada y la complementaria
(`_celda_en_cabecera_estructural`, consultada al inicio de
`_clasificar_par`):

1. **Tablas registradas y autofiltros.** Se inspeccionan `ws.tables`
   (`Table.ref` vía `range_boundaries`, `headerRowCount != 0`) y
   `ws.auto_filter.ref` ANTES de clasificar una etiqueta como editable. Una
   celda en la fila de cabecera de una tabla declarada NO es campo de
   proyecto, sin importar su texto, idioma, separador, posición en la hoja
   o número de filas de datos: se omite en silencio (nunca se registra como
   contradicción) y la tabla conserva `ref`, nombres de columna y formato.
   Cubre tablas vacías y pobladas y varias tablas por hoja.
2. **Pares desnudos sin estructura formal.** Sin objeto `Table` ni contrato
   explícito, `Proyecto | valor` es AMBIGUO: sólo se escribe si el contiguo
   tiene EVIDENCIA POSITIVA de ser nombre de proyecto —coincide con la
   identidad declarada (`_nucleo_nombre`/texto visible) o empieza por
   mención de proyecto (`Proyecto`/`Project`/`Projekt`/`Pröjekt`/`Projeto`,
   nuevo `_MENCION_INICIAL`). En caso contrario ⇒ fail-closed:
   contradicción estructural con hoja/celda y detalle «no se escribe por
   suposición (revisión o mapeo explícito requerido)», `publicable=False`,
   nada se modifica. Se conservan los campos legítimos verificados por el
   auditor (`Proyecto | Proyecto A`, `Proyecto: | Proyecto A`), el
   rellenado de contiguos VACÍOS (N10) y la omisión silenciosa de cabeceras
   reconocibles por vocabulario (N16, segunda capa).
3. **Cabecera legítima + campo explícito correcto.** Se actualiza sólo ese
   campo y se PUBLICA sin contradicciones falsas.
4. **Sólo cabecera.** Sin celdas mapeadas, `identidad_verificada=False`,
   `estado_identidad=no_verificada`, `publicable=False` y borrador no
   publicable (P08) con aviso visible en UI/API (contrato N6 existente).

Ninguna fórmula, número, celda combinada, histórico, dato de usuario ni
metadato de tabla se altera; la plantilla Excel sigue siendo inmutable
(hashes verificados). Criterio clave del auditor: una tabla vacía
«Proyecto | Temperatura» JAMÁS se transforma en «Proyecto | Proyecto B».

## Pruebas

- Las 7 pruebas literales del auditor
  (`pruebas/test_v15_9_10_auditoria_regresiones.py`) en ROJO sobre el árbol
  V15.9.9 exacto (`8c916ba`): **5 failed / 2 passed**, mismos fallos y
  valores que `EVIDENCIA_N17_5_FAILED_2_PASSED.txt`. Tras la corrección:
  **7/7 verdes**.
- 18 casos nuevos de ampliación
  (`pruebas/test_v15_9_10_ampliacion.py`): tabla poblada, dos tablas por
  hoja en posiciones arbitrarias, autofiltro, etiqueta explícita en
  cabecera de tabla, par explícito en cuerpo de tabla, tabla visual
  desconocida + campo explícito (bloqueo fail-closed), evidencia positiva
  ×4, contiguo vacío, colisión con proyecto llamado «Temperatura»,
  explícito ES/EN/DE, exportador empresarial (borrador y publicado, con
  hash de plantilla y Excel releídos) y BMG real con tabla formal en
  `Rangos`.
- **Suite completa: 752 passed / 0 failed / 0 skipped** (3 corridas) y
  **node 43/43**, sobre el árbol exacto de la revisión.
- Contratos anteriores REEMPLAZADOS (documentado, no silencioso): 2 pruebas
  de ampliación de autor de V15.9.7 afirmaban el mapeo de pares desnudos
  con contiguos sin evidencia («A», «PRJ-001», «Old»); la exigencia 3 del
  auditor sustituye explícitamente ese comportamiento. Se conservan sus
  nombres con docstring `SUPERSEDE` y la cobertura positiva ES/EN/DE se
  mantiene vía etiqueta explícita. Ninguna prueba del AUDITOR
  (V15.9.2-V15.9.9) fue editada, eliminada ni relajada.

## Pendientes de campo (sin declarar producción)

Excel corporativos representativos del entorno del usuario (incluidos
libros con tablas formales reales), AVI reales anotados (precisión
temporal), GPU, Windows/macOS y navegador real. Las pruebas sintéticas no
sustituyen la validación de campo; no se declara aptitud para producción.

Evidencia: `docs/informes/RESULTADOS_PRUEBAS_V15_9_10.md` (rojo→verde) y
`docs/informes/REVISION_SKILLS_V15_9_10.md` (revisión por skill).
