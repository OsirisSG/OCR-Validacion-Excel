# Resultados de pruebas · V15.9.2 (r2 correctivo de auditoría + C7)

**Fecha:** 2026-10-12 · **Base:** V15.8.1 + V15.9.1 + correcciones C1-C7.
**Rama:** `codex/ocr-v15-9-2-correctiva` (commits `1e0064b`, `2a5632f`,
`71db30e`).
**Entorno:** Linux (sandbox CI), Python 3.13, Node 20; sin videos reales ni
GPU/RTX y sin navegador real (las validaciones de campo siguen pendientes, ver
final).

## Batería Python

`python -m pytest pruebas/ -q`

| Métrica | Resultado |
|---|---|
| Aprobadas | 554 |
| Fallas | 1 (`test_dashboard.py::test_estado_config_y_frontend`) |

La única falla es la conocida de entorno: exige `validacion_resultados.json`
procesado (`hay_datos`) y falla igual en V15.8.1/V15.9.0/V15.9.1 sin datos. No
hay fallas nuevas. Delta frente a V15.9.1: **+49 pruebas** (22 de C1-C6, 27 de
C7).

## Batería Node

`node --test pruebas/*.cjs` → **38/38 en verde**, incluidos los 4 contratos
nuevos de C7 (`pruebas/test_v15_9_2_proyecto_ui.cjs`: bloque de proyecto
obligatorio, guardia de procesamiento sin proyecto, carga desde `/api/proyectos`
con slug paritario al backend, estilos e i18n ES/EN/DE). Las ventanas de slice
de `test_v15_9_apertura_zoom_ui.cjs` se ampliaron porque el diálogo previo
creció con el bloque de proyecto; los contratos V15.9.1 siguen intactos.

## Pruebas nuevas (una por hallazgo de la auditoría)

| Archivo | Cubre |
|---|---|
| `pruebas/test_v15_9_2_correcciones_c1_c7.py` | C1 (repro literal 2/4, migración persistida con evidencia, manuales preservadas, sello `algoritmo_consenso`, recálculo por sello obsoleto), C2 (alerta sin clasificar bloquea 3/4, informativa no bloquea, legacy sin motivo compatible, manual manda, regresión B2, bandera del detector), C3 (escritura fallida en guardar/revertir/endpoint 503, JSON intacto), C4 (fallos inyectados por etapa: análisis, JSON de resultados, video ilegible 422, camino feliz verificado), C5 (bits ejecutables), C6 (`AGENTS.md` raíz). |
| `pruebas/test_v15_9_2_proyecto_c7.py` | C7 completo: precedencia autoritativa, «Sin asignar» expreso, checkpoint, legacy pendiente, `mapear_estructura`, P03 (`case_key` aislado), P05 (`tipo_st` independiente), P06 (`test_reason` no copia proyecto), registro con colisiones P12, escritura fallida del registro, P01/P02/P07/P08/P10 con lectura real de celdas Excel y hash de plantilla, validaciones backend 400/409, snapshot de ejecución, `GET /api/proyectos`, guardia P04 en `ejecutar_pipeline`. |
| `pruebas/test_v15_9_2_proyecto_ui.cjs` | Contratos de interfaz del diálogo previo de dos bloques. |

## Puerta test-first (reproducción antes de corregir)

Con las correcciones C1-C4/C6 revertidas (`git stash` sobre el árbol V15.9.1),
`test_v15_9_2_correcciones_c1_c7.py` → **18 failed / 4 passed**: las pruebas
reproducen los defectos auditados (C1 2/4 válido, C2 alerta evaporada, C3 éxito
fantasma, C4 ROI cambiada sin rollback). Las 4 que pasan son casos de
«conservar» y C5/C6 ya committeados en ese punto. Al restaurar → 22/22.
C7 es requisito nuevo (no existía código que reproducir): se acredita con
27+4 pruebas y la muestra Excel real de la entrega.

## Verificación de paquete (fresh clone)

Clon limpio en la base V15.8.1 (`5fbef43`) + `git apply V15_9_2_completo.patch`:

- `git apply --check` OK; aplicado sin rechazos.
- Los **52 archivos** de `archivos/` son byte-idénticos al árbol parcheado
  (`cmp` sin diferencias).
- `git diff 5fbef43..HEAD --summary | grep -c "mode change"` → **0** (C5);
  `iniciar.command`/`instalar.command` quedan `-rwxr-xr-x` en el clon.
- Suite repetida en el clon: 554/1 entorno + node 38/38.
- `git apply -R --check` OK (reversible).

## Evidencia P01 con Excel real

`entrega/.../muestra_excel/`: plantilla con `Captura_pruebas!A1="Proyecto:"`,
`B1="Proyecto A"`; salida generada con identidad declarada «Proyecto B» →
`B1="Proyecto B"` + bloque «Identidad del proyecto (autoritativa)» en Resumen
(nombre, `project_id`, origen, estado, `ejecucion_id`, fecha, responsable).
Hash SHA-256 de la plantilla idéntico antes/después (inmutabilidad verificada
también en `test_c7_p01_...` y `test_c7_p08_...`).

## Pendiente con datos reales / campo (sin cambios frente a V15.9.1)

- Exactitud ±1 cuadro en 30 casos y acuerdo ≥ 0.95 con revisión humana.
- Lote real de 4 cámaras para el umbral 3-de-4, reflejos reales, dos tasas de
  adquisición, reproducción a 8 fps; caso sin apertura y confirmación manual.
- Benchmark V15.8.1 vs V15.9.x en hardware con RTX (`utilidades/benchmark_detector.py`).
- Interacción real en navegador (pan/zoom/revertir y el nuevo diálogo de
  proyecto en escritorio y panel pequeño) con capturas.
- Ejecución real de `iniciar.command`/`instalar.command` en macOS (C5): el diff
  preserva 100755; la doble verificación en hardware es del operador.

## Skills (S0)

Las seis skills siguen integradas en `.agents/skills/` y V15.9.2 añadió
`AGENTS.md` en la raíz del repo (C6) para el descubrimiento real por Codex, con
la regla de identidad C7 incluida. La revisión trazable por skill ejecutada
durante esta entrega está documentada en
[REVISION_SKILLS_V15_9_2.md](REVISION_SKILLS_V15_9_2.md).
