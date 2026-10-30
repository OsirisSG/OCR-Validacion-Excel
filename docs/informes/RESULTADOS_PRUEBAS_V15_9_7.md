# Resultados de pruebas · V15.9.7 (correctiva de la auditoría N13-N14)

**Fecha:** 2026-10-13 · **Rama:** `codex/ocr-v15-9-7-correctiva`
**Base:** V15.9.6 (`9bd190b`) sobre V15.8.1 exacta (`5fbef43`).
**Origen:** `AUDITORIA_ESTRICTA_V_MATRIX_V15_9_6.md` (dictamen NO APTO
TODAVÍA: N13 crítica, N14 alta) y
`CORRECCIONES_OBLIGATORIAS_V_MATRIX_V15_9_7.md`.
**Alcance acotado por la auditoría:** contrato de identificación Excel
(`utilidades/identidad_excel.py`); no se reescriben motor de vídeo,
ROI/zoom, frontend ni las seis skills.

## 1. Puerta rojo → verde

Los 4 casos literales del auditor (`PRUEBAS_ROJAS_V15_9_6_N13_N14.py`,
3 funciones con una parametrizada ×2) se incorporaron VERBATIM como
`pruebas/test_v15_9_7_auditoria_regresiones.py` y se ejecutaron ANTES de
corregir sobre el árbol V15.9.6 completo (commit `9bd190b`):

| Paso | Comando | Resultado |
|---|---|---|
| ROJO | `PYTHONPATH=. python -m pytest pruebas/test_v15_9_7_auditoria_regresiones.py -q` (árbol `9bd190b`) | **4 failed in 1.30s** (coincide con el «4 failed» y los tracebacks del auditor, incluido el `AttributeError: 'MergedCell' object attribute 'value' is read-only` en la escritura declarada) |
| VERDE | mismo comando tras la corrección | **4 passed** |

Ninguna aserción fue eliminada ni debilitada. Log rojo completo en el
paquete de entrega (`evidencia_pruebas/RED_sobre_arbol_V15_9_6.txt`), que
reproduce los 4 fallos documentados en
`LOG_PRUEBAS_N13_N14_FALLIDAS.txt` del auditor.

## 2. Correcciones y su cobertura

### N13 (CRÍTICA) — política segura única para TODAS las celdas mapeadas

Causa raíz: `aplicar_identidad_a_salida` escribía el nombre visible en la
celda declarada (`libro[hoja][celda_valor] = visible`) SIN pasar por
`_celda_valor_editable`, que sólo protegía el mapeo complementario de
V15.9.6. Consecuencias reproducidas por el auditor: (1) fórmula
`=CONCAT("Proyecto ","A")` destruida y `publicable=True`; (2) número
`2025` sobrescrito; (3) `MergedCell` ⇒ `AttributeError` no controlado.

Contrato implementado (único para declaradas y complementarias):

- Cada destino se valida ANTES de escribir: fórmula (`data_type == "f"`,
  incluidas referencias externas a otras hojas), valor no textual
  (números, fechas, booleanos) o celda combinada (tanto `MergedCell` de
  sólo lectura como la celda inicial del rango) ⇒ NO se escribe.
- El campo queda intacto, se EXCLUYE de las celdas identificadas (una
  celda no validada jamás cuenta para `identidad_verificada`) y se
  registra contradicción estructural `_registro_campo_no_editable` con
  hoja/celda/motivo legible; `publicable=False`, `estado_identidad=
  bloqueada_contradiccion`.
- Ninguna excepción de bajo nivel llega al usuario; los generadores
  (empresarial y BMG) propagan el bloqueo a borrador oficial
  `.borrador_no_publicable` (nunca a `generados`).
- Los demás pares declarados editables del mismo libro SÍ se mapean (el
  bloqueo es por celda, no global), y la plantilla original no se toca
  (hash verificado en las pruebas con plantillas reales).

Pruebas: 2 casos verbatim del auditor (fórmula/número) + MergedCell
verbatim; ampliación: fórmula con referencias externas intacta y
bloqueada, segundo par declarado editable mapeado mientras el numérico
bloquea, combinada inicial declarada, generador empresarial con fórmula
declarada ⇒ borrador + plantilla intacta, BMG real con fórmula
complementaria (`Rangos!B1`) ⇒ borrador + plantilla del repo intacta.

### N14 (ALTA) — etiqueta «Proyecto» desnuda: evidencia estructural o bloqueo

Causa raíz: el mapeo de V15.9.6 sólo aceptaba etiquetas EXPLÍCITAS con
separador (`Proyecto:`), de modo que `Indicadores!A1="Proyecto"` (sin
`:`) con `B1="A"` en hoja visible quedaba invisible para el mapeo Y para
el escáner textual (el valor corto «A» no contiene la palabra clave):
publicación en silencio con un valor ajeno visible.

Contrato implementado (`_evidencia_campo_unico`, ES/EN/DE/PT):

- Fila con ≥3 celdas no vacías ⇒ cabecera TABULAR (Trazabilidad,
  Evidencia, BMG…): no se mapea ni se bloquea; sus columnas de casos y
  datos históricos no se tocan (protección de V15.9.6 íntegramente
  vigente: sin reemplazo masivo).
- Fila de ≤2 celdas SIN contenido debajo en la columna de etiqueta ni en
  la de valor ⇒ CAMPO ÚNICO inequívoco: se sustituye sólo la celda de
  valor (misma política segura de N13: fórmula/combinada/no textual ⇒
  bloqueo) y se registra en `celdas_complementarias` con nota «etiqueta
  desnuda (campo único)» y su valor anterior.
- Fila de ≤2 celdas CON datos debajo ⇒ estructura AMBIGUA: se verifica la
  coherencia del contiguo y de la columna bajo la etiqueta contra las
  representaciones de identidad (cabeceras de metadatos reconocibles —
  «Etapa», «Case», «Datum»… — se aceptan como cabecera de tabla de dos
  columnas); cualquier valor ajeno o no textual ⇒ contradicción
  estructural con las celdas señaladas y «revisión requerida»; nada se
  reemplaza. Estructura coherente ⇒ no se toca.
- Hojas ocultas y `hojas_exentas` (histórico/evidencia declarados por el
  generador, con motivo visible en el bloque) siguen sin examinarse.

Pruebas: caso verbatim del auditor; ampliación: pares desnudos abreviados
(«A», «PRJ-001») en varias hojas mapeados y registrados, cabecera tabular
desnuda intacta y publicable, estructura ambigua con datos históricos
ajenos bloqueada sin reemplazar nada, tabla de dos columnas con cabecera
reconocible («Proyecto|Etapa») y columna coherente intacta y publicable,
hojas ocultas/exentas no examinadas, fórmula y combinada en campo
desnudo ⇒ bloqueo intacto, 3 idiomas (Proyecto/Project/Projekt) y
migración histórica A→B (campo desnudo migrado, título histórico intacto
y bloqueado como hasta ahora).

## 3. Suite completa sobre el árbol exacto

| Suite | Comando | Resultado |
|---|---|---|
| Python (3 corridas) | `PYTHONPATH=. python -m pytest pruebas/ -q` | **690 passed / 0 failed / 0 skipped** (671 de V15.9.6 + 4 verbatim + 15 ampliación), 51-55 s por corrida |
| Node | `node --test pruebas/*.cjs` | **43 pass / 0 fail** (frontend sin cambios) |

Regresiones N1-N12: todas verdes sin editar ninguna prueba anterior
(ningún test volteado en esta versión: el contrato N14 amplía el mapeo
desnudo por exigencia expresa de la auditoría, manteniendo la protección
de cabeceras tabulares que motivó la regla de V15.9.6). Entorno:
Python 3.13, node v20, Linux; dependencias de test: fastapi/httpx.

## 4. Integridad verificada

- Plantilla BMG real del repo (`plantillas/reporte_bmg_1st_2st.xlsx`) y
  plantillas empresariales: hash SHA-256 antes/después idéntico en las
  pruebas que las usan (copias temporales).
- Persistencia de proyectos/consensos/datos humanos: sin cambios en esta
  versión (rutas no tocadas); suite completa verde.
- Offline: ninguna dependencia de red nueva.
- Muestras Excel del paquete (`muestra_excel/`): N13 fórmula declarada
  intacta ⇒ borrador, N13 combinada ⇒ borrador sin excepción, N14 campo
  desnudo corregido ⇒ publicado.

## 5. Pendientes de campo (sin declarar producción)

Se mantienen los límites declarados por la auditoría: AVI reales anotados
(FPS nativo vs reproducción, criterio 3/4, error temporal), validación en
Windows/macOS reales, navegador real para el frontend y entorno de
trabajo del usuario. Nada de ello se declara aprobado en esta versión.
