# Resultados de pruebas · V15.9.9 (correctiva de la auditoría N16)

**Fecha:** 2026-10-13 · **Rama:** `codex/ocr-v15-9-9-correctiva`
**Base:** V15.9.8 (`7171da1`) sobre V15.8.1 exacta (`5fbef43`).
**Origen:** `AUDITORIA_ESTRICTA_V_MATRIX_V15_9_8.md` (dictamen NO APTA PARA
PRODUCCIÓN: N15 confirmada, N16 crítica) y
`CORRECCIONES_OBLIGATORIAS_V_MATRIX_V15_9_9.md`.
**Alcance acotado por la auditoría:** mapeo de identidad de Excel
(`utilidades/identidad_excel.py`); sin cambios en módulos de vídeo, ROI,
zoom, umbrales, consenso, aprendizaje, checkpoints, frontend ni backend.

## 1. Puerta rojo → verde

Las 7 pruebas literales del auditor (`PRUEBAS_ROJAS_V15_9_8_N16.py`: 1
parametrizada ×4 + 3 funciones) se incorporaron VERBATIM como
`pruebas/test_v15_9_9_auditoria_regresiones.py` y se ejecutaron ANTES de
corregir sobre el árbol V15.9.8 completo (commit `7171da1`):

| Paso | Comando | Resultado |
|---|---|---|
| ROJO | `PYTHONPATH=. python -m pytest pruebas/test_v15_9_9_auditoria_regresiones.py -q` | **4 failed, 3 passed** — mismos 4 fallos y mismos valores que `EVIDENCIA_N16_V15_9_8.txt` del auditor («Se sobreescribió una cabecera de tabla vacía»: `Etapa`/`Stage`/`Stufe`/`Caso` ⇒ «Proyecto B») |
| VERDE | mismo comando tras la corrección | **7 passed** (4 corregidos + 3 controles conservados) |

Ninguna aserción fue eliminada ni debilitada. Log rojo completo en el
paquete (`evidencia_pruebas/RED_sobre_arbol_V15_9_8.txt`).

## 2. Corrección y su cobertura

### N16 (CRÍTICA) — tabla de dos columnas VACÍA tratada como campo único

Causa raíz: `_evidencia_campo_unico` clasifica una etiqueta desnuda como
`unico` cuando no hay datos debajo, y `_clasificar_par` tomaba esa
conclusión como suficiente para editar el contiguo; `_es_cabecera_reconocible`
sólo se consultaba en la rama `ambigua`. Una tabla vacía («Proyecto |
Etapa» sin filas) quedaba expuesta: la cabecera se sobrescribía con
`identidad_verificada=True` y `publicable=True`. Además, el vocabulario de
cabeceras no incluía «Caso/Case/Fall» ni otras claves de columna habituales.

Contrato implementado:

- Nuevo vocabulario centralizado `_CABECERAS_COLUMNA` (ES/EN/DE): etapa/
  stage/stufe/fase/phase, caso/case/fall/prueba/test/versuch/ensayo/
  experiment, id/num/nr, valor/wert/value, resultado/ergebnis/result,
  estado/status/zustand, criterio/kriterium, fecha/date/datum, cámara/
  camera/kamera, observaciones/notas/bemerkungen/comentarios/kommentare.
- `_es_cabecera_reconocible` (clasificador centralizado, consultado por
  AMBAS rutas) incorpora el vocabulario nuevo a los tokens de metadatos y
  de etapa/fase ya existentes.
- `_clasificar_par`, rama `unico` de etiqueta desnuda: si el contiguo es
  cabecera reconocible ⇒ se omite (tabla vacía): no se modifica, no se
  registra en `celdas`/`celdas_complementarias` y no cuenta como identidad.
  Sin otro campo inequívoco ⇒ `identidad_verificada=False`,
  `estado_identidad=no_verificada`, `publicable=False` y borrador no
  publicable (P08), comunicado por la API con el contrato N6 existente.
- Con otro campo inequívoco en el libro (p. ej. `Proyecto: | Proyecto A`),
  ése se actualiza, la cabecera permanece intacta y la publicación se
  autoriza si no hay contradicciones adicionales.
- Colisión semántica genuina (proyecto llamado exactamente «Etapa»): con
  etiqueta desnuda jamás se sobrescribe la posible cabecera (fail-closed,
  borrador); la asignación EXPLÍCITA con separador (contrato de plantilla)
  sí resuelve la identidad y publica.
- Protecciones N7-N15 intactas: fórmulas, números, combinadas, cabeceras
  con ≥3 celdas, estructuras ambiguas con datos, exenciones y escáner
  textual sin cambios.

Pruebas: 7 verbatim + 14 de ampliación — cabecera vacía complementaria
sola (omisión sin contradicciones falsas), combinada debajo de la cabecera
(sin excepción), vocabulario extendido ×6 (Valor/Estado/Case/Date/Fall/
Wert, ES/EN/DE), colisión semántica desnuda vs explícita, paridad con
campo declarado en la misma corrida, Excel temporal guardado y RELEÍDO con
hash de plantilla intacto, generador empresarial con cabecera vacía en
hoja declarada ⇒ borrador + hash, empresarial con cabecera + campo
explícito ⇒ oficial publicado + cabecera intacta + hash, y BMG real con
cabecera «Projekt | Stufe» en `Übersicht Standversuche` ⇒ borrador con
cabeceras y plantilla del repo intactas.

## 3. Suite completa sobre el árbol exacto

| Suite | Comando | Resultado |
|---|---|---|
| Python (3 corridas) | `PYTHONPATH=. python -m pytest pruebas/ -q` | **727 passed / 0 failed / 0 skipped** (706 de V15.9.8 + 7 verbatim + 14 ampliación), ~49-51 s por corrida |
| Node | `node --test pruebas/*.cjs` | **43 pass / 0 fail** (frontend sin cambios; incluye los 20 contratos C7/N6/N9/UI que el auditor verificó por separado) |

Regresiones N1-N15: todas verdes sin editar ninguna prueba anterior
(ningún test volteado). Paridad Excel/dashboard: la distinción borrador
bloqueado vs exportación oficial sigue cubierta por las pruebas de
respuesta API N6 (V15.9.4) y los contratos UI node, sin cambios de
contrato en esta versión.

Incidencia de entorno documentada (no atribuible al parche, igual que en
V15.9.8): la restauración del sandbox dejó los `.command` sin bit
ejecutable en el árbol de trabajo mientras git registraba 100755; se
restauró con `chmod 755` antes de las corridas finales y el test C5 quedó
verde. fastapi/httpx reinstalados para la suite del backend. Entorno:
Python 3.13, node v20, Linux.

## 4. Integridad verificada

- Plantilla BMG real del repo y plantillas empresariales: hash SHA-256
  antes/después idéntico en las pruebas que las usan (copias temporales),
  con Excel guardados y releídos.
- Persistencia (`.aprendizaje/`, SQLite, `proyectos.json`, consensos,
  checkpoints, ROI, zoom, aprendizaje, cola): el diff no toca esas rutas;
  suite completa verde; umbrales y consenso sin cambios.
- Offline: sin dependencias nuevas.
- Muestras Excel del paquete (`muestra_excel/`): N16 cabecera vacía
  declarada ⇒ borrador con cabecera intacta (empresarial real), N16
  cabecera vacía + campo explícito ⇒ publicado, control N16 campo único
  desnudo ⇒ publicado y corregido.

## 5. Pendientes de campo (sin declarar producción)

Se mantienen los límites declarados por la auditoría: Excel corporativos
representativos del entorno del usuario, AVI reales anotados (precisión
temporal), GPU, Windows/macOS y navegador real. Las pruebas sintéticas no
sustituyen la validación de campo; nada de ello se declara aprobado en
esta versión.
