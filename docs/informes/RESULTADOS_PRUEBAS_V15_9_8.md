# Resultados de pruebas · V15.9.8 (correctiva de la auditoría N15)

**Fecha:** 2026-10-13 · **Rama:** `codex/ocr-v15-9-8-correctiva`
**Base:** V15.9.7 (`a079976`) sobre V15.8.1 exacta (`5fbef43`).
**Origen:** `AUDITORIA_ESTRICTA_V_MATRIX_V15_9_7.md` (dictamen NO APTO AÚN
PARA PRODUCCIÓN: N15 crítica) y
`CORRECCIONES_OBLIGATORIAS_V_MATRIX_V15_9_8.md`.
**Alcance acotado por la auditoría:** contrato de identificación Excel
(`utilidades/identidad_excel.py`); no se reescriben motor de vídeo,
ROI/zoom, backend, pipeline, frontend ni las seis skills.

## 1. Puerta rojo → verde

Los 4 casos literales del auditor (`PRUEBAS_ROJAS_V15_9_7_N15.py`) se
incorporaron VERBATIM como
`pruebas/test_v15_9_8_auditoria_regresiones.py` y se ejecutaron ANTES de
corregir sobre el árbol V15.9.7 completo (commit `a079976`):

| Paso | Comando | Resultado |
|---|---|---|
| ROJO | `PYTHONPATH=. python -m pytest pruebas/test_v15_9_8_auditoria_regresiones.py -q` | **2 failed, 2 passed** — fallan exactamente los dos casos del auditor (`…dos_columnas…`: B2 quedó `Proyecto B` en vez de `Etapa`; `…tres_columnas…`: B1/C1 alterados), con `publicable=True`; pasan los dos controles (campo único desnudo y par explícito), igual que en `RESULTADOS_PRUEBAS_AUDITOR_V15_9_7.txt` |
| VERDE | mismo comando tras la corrección | **4 passed** (2 fallos corregidos + 2 controles conservados) |

Ninguna aserción fue eliminada ni debilitada. Log rojo completo en el
paquete de entrega (`evidencia_pruebas/RED_sobre_arbol_V15_9_7.txt`).

## 2. Corrección y su cobertura

### N15 (CRÍTICA) — cabeceras tabulares sobrescritas en la ruta declarada

Causa raíz: `buscar_celdas_proyecto` usa `ETIQUETAS_PROYECTO`, cuyo
separador es OPCIONAL (`\s*[:=]?$`), de modo que «Proyecto» desnudo en las
primeras filas de `hojas_busqueda` devolvía su celda derecha como valor;
`aplicar_identidad_a_salida` la protegía contra fórmulas/números/combinadas
(N13) pero no contra cabeceras de columna textuales: sobrescribía «Etapa»
con el nombre del proyecto y declaraba `identidad_verificada=True`. La
protección estructural de N14 (`_evidencia_campo_unico`) nunca intervenía
porque `excluidas` apartaba las etiquetas ya encontradas por la ruta
declarada.

Contrato implementado — política estructural ÚNICA centralizada en
`_clasificar_par`, usada por las DOS rutas antes de escribir ninguna celda:

- Fila con ≥3 celdas no vacías y etiqueta desnuda ⇒ CABECERA TABULAR
  (`Proyecto|Etapa|Caso`…): no se mapea, no se bloquea, no entra en
  `celdas`; columnas de casos y datos históricos intactas.
- Fila de ≤2 celdas con etiqueta desnuda ⇒ evidencia estructural:
  `unico` (sin datos debajo) se mapea con la política segura N13;
  `ambigua` (datos debajo) verifica coherencia del contiguo (cabeceras de
  metadatos reconocibles admitidas) y de la columna bajo la etiqueta;
  cualquier valor ajeno o no textual ⇒ contradicción estructural con
  «revisión requerida», sin reemplazo. Una etiqueta de proyecto anidada
  más abajo en la columna no cuenta como dato ajeno (se clasifica en su
  propia fila).
- Etiqueta explícita en fila tabular ⇒ ambigua: sólo se admite si el valor
  ya coincide; en caso contrario bloqueo estructural (comportamiento que
  antes sólo tenía la ruta complementaria).
- Destino no editable (fórmula, no textual, combinada) ⇒ bloqueo N13 con
  hoja/celda/motivo.
- Sin campo inequívoco no hay `identificadas` ⇒ `identidad_verificada=False`
  y, con origen declarado, `publicable=False` (P08): reporte identificado
  queda en BORRADOR no publicable. `excluidas` sólo evita reclasificar
  pares cuyo resultado ya quedó registrado (mapeado, omitido o bloqueado).

Pruebas: 4 verbatim + 12 de ampliación — hoja declarada de 2 columnas
(cabeceras y registro intactos, `celdas==[]`, `estado_identidad=
no_verificada`, borrador), de 3 columnas con número y formato intactos
RELEYENDO el Excel temporal guardado, estructura ambigua con históricos
ajenos bloqueada sin reemplazar nada, cabecera tabular + par explícito
válido en la misma hoja declarada ⇒ publica con la tabla intacta, explícita
en fila tabular con valor ajeno ⇒ bloqueo, ES/EN/DE
(`Proyecto|Etapa|Caso`, `Project|Stage|Case`, `Projekt|Stufe|Fall`), hojas
ocultas y exentas con cabeceras no examinadas, propagación a borrador en
generador empresarial con hash de plantilla intacto, empresarial con
cabecera complementaria + campo válido ⇒ oficial publicado, y BMG real con
cabecera tabular en `Übersicht Standversuche` (hoja declarada) ⇒ borrador
con cabeceras intactas y hash de la plantilla del repo intacto.

## 3. Suite completa sobre el árbol exacto

| Suite | Comando | Resultado |
|---|---|---|
| Python (3 corridas) | `PYTHONPATH=. python -m pytest pruebas/ -q` | **706 passed / 0 failed / 0 skipped** (690 de V15.9.7 + 4 verbatim + 12 ampliación), ~60-63 s por corrida |
| Node | `node --test pruebas/*.cjs` | **43 pass / 0 fail** (frontend sin cambios) |

Regresiones N1-N14: todas verdes sin editar ninguna prueba anterior
(ningún test volteado en esta versión). Incidencia de entorno documentada
sin atribuir origen al parche: al inicio de la sesión los `.command` del
árbol de trabajo perdieron el bit ejecutable por la restauración del
sandbox (git seguía registrando 100755); se restauró con `chmod 755` y el
test C5 volvió a verde — no es un cambio del parche. Entorno: Python 3.13,
node v20, Linux; fastapi/httpx reinstalados para la suite del backend.

## 4. Integridad verificada

- Plantilla BMG real del repo y plantillas empresariales: hash SHA-256
  antes/después idéntico en las pruebas que las usan (copias temporales).
- Celdas antes/después verificadas releyendo los Excel temporales
  (cabeceras, números, tipos; fórmulas y combinadas por la suite N13).
- Persistencia (`.aprendizaje/`, SQLite, `proyectos.json`, consensos,
  checkpoints, cola): el diff no toca esas rutas; suite completa verde.
- Offline: sin dependencias nuevas.
- Muestras Excel del paquete (`muestra_excel/`): N15 cabecera 2 columnas
  declarada ⇒ borrador con cabeceras intactas, N15 cabecera 3 columnas +
  campo explícito válido ⇒ publicado con tabla intacta, control N15 campo
  único desnudo declarado ⇒ publicado y corregido.

## 5. Pendientes de campo (sin declarar producción)

Se mantienen los límites declarados por la auditoría: validación con los
Excel representativos del entorno del usuario, AVI reales anotados, GPU,
Windows/macOS y navegador real. Las pruebas sintéticas no sustituyen la
validación de campo; nada de ello se declara aprobado en esta versión.
