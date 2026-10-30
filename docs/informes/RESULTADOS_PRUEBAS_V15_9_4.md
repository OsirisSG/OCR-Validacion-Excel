# Resultados de pruebas · V15.9.4 (correctiva de la auditoría N1-N6)

**Fecha:** 2026-10-12 · **Base:** V15.8.1 exacta (`5fbef43`) + V15.9.3 +
correcciones N1-N6 de `AUDITORIA_ESTRICTA_V_MATRIX_V15_9_3.md` /
`CORRECCIONES_OBLIGATORIAS_V_MATRIX_V15_9_4.md`.
**Rama:** `codex/ocr-v15-9-4-correctiva` (commit de código `1f8cd9a`).
**Entorno:** Linux (sandbox CI), Python 3.13, Node 20; sin videos reales, GPU,
navegador real ni macOS (pendientes de campo, ver final). Ninguna prueba toca
datos reales: todo con fixtures sintéticos en `tmp_path`.

## Puerta test-first: los 7 casos de la auditoría en ROJO antes de corregir

El archivo `PRUEBAS_ROJAS_V15_9_3.py` de la auditoría se incorporó VERBATIM
como `pruebas/test_v15_9_4_auditoria_regresiones.py` y se ejecutó sobre el
árbol V15.9.3 (`b19e8a0`) ANTES de cualquier cambio de código:

```
PYTHONPATH=. python -m pytest pruebas/test_v15_9_4_auditoria_regresiones.py -q
7 failed in 0.65s
```

Las 7 fallas coinciden una a una con los hallazgos N1-N6 (1/1 y 2/2 legados
publicados, título contradictorio publicable con celda mapeada, «Sin asignar»
publicable sobre título histórico, registro parcialmente corrupto que pierde
la entrada inválida, migración que se declara con escritura fallida, y
borrador ofrecido como exportación generada).

## Batería Python (tras la corrección)

`python -m pytest pruebas/ -q`

| Métrica | Resultado |
|---|---|
| Aprobadas | **604** |
| Fallas | **0** |
| Skips | **0** |

Estabilidad: 3+ ejecuciones completas consecutivas en verde. Delta frente a
V15.9.3: **+30 pruebas** (7 de auditoría verbatim, 23 de ampliación).

## Batería Node

`node --test pruebas/*.cjs` → **41/41** (38 previos + 3 contratos nuevos de
`test_v15_9_4_exportacion_ui.cjs`: exportación bloqueada separada del éxito,
borradores parciales por separado, mensajes ES/EN/DE).

## Pruebas nuevas

| Archivo | Cubre |
|---|---|
| `pruebas/test_v15_9_4_auditoria_regresiones.py` | Los 7 casos literales de la auditoría (N1-N6), incorporados verbatim. |
| `pruebas/test_v15_9_4_ampliacion.py` | N1/N2: plantilla empresarial con título A1 + etiqueta A2 en ES/EN/DE (bloqueo, marcador y referencia contradictoria por idioma, título jamás reemplazado, celda etiquetada sí mapeada), título coherente que publica, plantilla BMG REAL con título ajeno en celda libre (bloqueo + control sin falsos positivos), «Sin asignar» con título histórico (bloquea) y con plantilla limpia (publica pendiente), proyectos A/B consecutivos sin fugas ni mezclas de `project_id`, reanudación con checkpoint A vs declarado B (P04) y plantilla con A. N3: 7 estructuras parcialmente corruptas parametrizadas (no objeto, null, incompleto, ID vacío/no texto, nombre no texto, duplicado) con bytes intactos y respaldo íntegro, Unicode válido sin pérdida. N4: matriz completa 3/4, 4/4, 3/3, 2/4, 2/2, 1/1, revisión pendiente y manual auditado; 3/4 con revisión obligatoria; migración de legado 2/2 a pendiente conservando medida. N5: fallo de escritura con advertencia visible, caché invalidada, disco intacto, vista en memoria fail-closed y reintento persistido en la carga siguiente. N6: cola Excel conserva pendiente ante `PublicacionExcelBloqueadaError` y guarda al corregir, `_generar_excel_asociado` lanza ante borrador, descarga oficial rechaza borradores y el borrador va por su ruta (y viceversa), `PermissionError` inyectado en el reemplazo atómico con salida anterior intacta y sin temporales. |
| `pruebas/test_v15_9_4_exportacion_ui.cjs` | Contratos de interfaz N6 (ver arriba). |

## Pruebas existentes actualizadas (cambio de contrato exigido por la auditoría)

| Prueba | Cambio |
|---|---|
| `test_c1_consensos_legados_con_respaldo_suficiente_se_conservan` | INVERTIDO el caso 2/2 (N4: política única, mínimo 3 cámaras); se añade 1/1 ⇒ no publicable. |
| `test_compatibilidad_consenso_historico_v1581` | Ídem: 2/2 legado ⇒ `False` (N4). |
| `test_orientaciones_guardadas_unittest` | Determinismo: pausa de 10 ms antes de reescribir con igual tamaño (misma causa raíz de tick de reloj que `hash_archivo`/`ctime_ns`; no debilita el contrato). |

Contratos anteriores que NO se debilitaron (regresiones en verde): CRIT-01..04
y ALTA-05 de V15.9.3 (18 casos), C1-C7 de V15.9.2, B1/B2 de V15.9.1, P01-P12,
paridad Excel↔dashboard, ROI/zoom/recálculo/matriz/rangos, ES/EN/DE.

## Impacto operativo de V15.9.4 (documentado para el usuario)

- Legados automáticos 1/1 y 2/2 (aunque traigan metadata completa) bajan a
  pendiente al cargarse; se recuperan con confirmación humana o reanálisis con
  3+ cámaras. No existe modo autorizado con menos de tres cámaras.
- Un Excel cuya plantilla conserva un título/encabezado de OTRO proyecto ya no
  se publica aunque la celda etiquetada esté mapeada: sale como borrador con
  la referencia contradictoria listada (hoja, celda, texto). Ningún texto
  existente se reemplaza jamás.
- «Sin asignar» explícito con título histórico visible ⇒ borrador (la decisión
  humana queda en la trazabilidad del bloque).
- La cola de reexportación conserva el estado pendiente con error visible
  («Exportación BLOQUEADA…») hasta corregir plantilla/identidad.
- Los borradores nunca aparecen como Excel oficiales: descargas separadas
  (`/api/resultados/borrador`, `/api/pipeline/borrador-parcial`), campos
  `publicable`/`estado_publicacion`/`bloqueados` en la API y mensajes ES/EN/DE
  en la UI.

## Verificación de paquete (fresh clone)

Clon limpio en `5fbef43` + `git apply V15_9_4_completo.patch`: apply OK,
archivos de `archivos/` byte-idénticos, 0 cambios de modo (`.command` quedan
100755), suite Python 604/0/0 y node 41/41 repetidas en el clon, `git apply -R`
restaura el árbol exacto. `SHA256SUMS.txt` con rutas relativas verificables
con `sha256sum -c` desde la carpeta extraída.

## Pendientes de campo (medios que este entorno no tiene)

Ejecución real en macOS, comprobación visual en navegador real, videos AVI
empresariales de alta velocidad etiquetados con evidencia de FPS reales y
error de apertura por fotograma, benchmark GPU/RTX, dataset real y casos
adversos reales. La puerta de producción final sigue requiriendo esas
evidencias (declarado sin asteriscos en `MATRIZ_ACEPTACION_V15_9_4.md`).
