# V15.9.2 · Proyecto elegido por el usuario (C7) y correcciones C1-C6

## 1. Elección de proyecto antes de procesar

Al pulsar **«Procesar carpeta»** se abre un paso previo con **dos bloques
independientes**:

1. **Proyecto al que pertenecen las pruebas** (nuevo en V15.9.2)
   - Selector de proyectos ya declarados (registro `.aprendizaje/proyectos.json`).
   - **«Nuevo proyecto…»**: escribes el `nombre_proyecto` visible y el sistema
     muestra el `proyecto_id` estable derivado (minúsculas; espacios y símbolos
     comprimidos a `-`; se conservan `.` `_` `-`).
   - **«Sin asignar»**: decisión expresa de no identificar todavía el lote.
     El lote, el panel y los Excel quedan marcados como *pendientes*; nada se
     publica a nombre de un proyecto.
   - **Sugerencias** (nombre de carpeta, resultados anteriores) aparecen como
     candidatas *pendientes de aceptación*: usarlas requiere tu clic y siguen
     siendo una elección humana. Nunca se asignan a escondidas.
   - Sin una elección explícita los botones de procesar permanecen desactivados.
2. **Rangos de tiempo de apertura** (V15.9.1, sin cambios): límites verde /
   amarillo, vista previa del semáforo y la casilla «Guardar para próximas
   carpetas» que sólo persiste la preferencia si tú la marcas.

**Precedencia autoritativa:** proyecto declarado en esta ejecución > «Sin
asignar» expreso > configuración `empresarial.proyecto_id` (legacy) > nombre de
carpeta (legacy, siempre marcado *pendiente*). La **plantilla Excel nunca es
fuente de identidad**: sólo aporta el contrato de columnas/formato. El OCR o la
carpeta pueden *sugerir*, jamás asignar.

El proyecto viaja en la misma solicitud que los rangos (`POST /api/pipeline`,
campo `proyecto`) y el backend persiste una instantánea con `ejecucion_id`,
origen, fecha y responsable (`proyecto_ejecucion`), visible en
`/api/pipeline/estado`, en el panel de progreso y en `validacion_resultados.json`.

## 2. Datos separados (nunca confundir)

| Concepto | Qué es | Fuente |
|---|---|---|
| `nombre_proyecto` | Texto visible | Elección humana confirmada |
| `project_id` | ID técnico estable | Derivado del nombre declarado |
| `tipo_st` | Etapa 1ST/2ST | Detección estructural o elección; independiente del proyecto |
| `plantilla_id` / `ruta_plantilla` | Contrato de formato | Plantilla elegida/autodetectada; NO decide el proyecto |
| `test_reason` | Motivo de prueba | Sólo evidencia OCR («PROYECTO:/MOTIVO:/TEST REASON:») o corrección humana; nunca copia `nombre_proyecto` |
| `case_key` | Identidad del caso | `proyecto|etapa|numero|nombre|huella`; proyectos distintos no comparten clave |

## 3. Excel de salida: identificación sin tocar la plantilla

- La plantilla original es **inmutable** (se verifica hash en las pruebas).
- La identidad autoritativa se escribe sólo en **celdas de metadatos
  identificadas** de la copia de salida:
  - Celda de proyecto declarada por etiqueta de cabecera («Proyecto:»,
    «Project:», «Projekt:» en las primeras filas de Captura/Resumen u
    Übersicht/Versuchsmatrix en BMG): se sustituye SU valor.
  - Bloque «Identidad del proyecto (autoritativa)» en la hoja resumen, con
    `nombre_proyecto`, `project_id`, origen, estado, `ejecucion_id`, fecha y
    responsable, en ES/EN/DE.
- **Plantilla externa sin campo identificable (P08):** se escribe una
  ADVERTENCIA visible en el bloque de identidad y NO se reemplaza ningún
  título antiguo (reporte identificado bloqueado; la identidad técnica sigue
  expuesta en el bloque). No hay buscar-y-reemplazar global.
- Escritura verificada (P10): si el libro no se guarda, se lanza error; no se
  declara éxito ni queda selección alterada.

## 4. Reanudación y migración (P04)

El checkpoint guarda el proyecto de la ejecución. Reanudar conserva ese
proyecto; intentar reanudar con otro devuelve **409** y exige
`migracion_explicita` (dashboard: vuelve a declarar el proyecto y confirma el
aviso). El inventario (`inventario_proyecto.json`) también lleva el proyecto.
Revisiones manuales, ROI aprendidas, cachés e historiales ligados a otra
identidad no se trasladan ni se borran.

## 5. Colisiones (P12)

Dos nombres distintos no pueden compartir `project_id`: el registro devuelve
**409** con el proyecto existente y no fusiona en silencio. Resolución: elige
otro nombre/ID o corrige el proyecto existente en `.aprendizaje/proyectos.json`
(con respaldo previo).

## 6. Correcciones C1-C6 (resumen operativo)

- **C1**: consensos legados 2/4 ya no se publican: al cargar resultados se
  reevalúan con la regla vigente (3 de 4), conservando el anterior en
  `video_apertura_anterior` y sellando `algoritmo_consenso`. Las
  confirmaciones manuales reales se preservan.
- **C2**: las alertas `requiere_revision` se clasifican: la bandera genérica
  del detector es informativa (`revision_informativa`); una alerta con motivo
  no catalogado **bloquea** el consolidado («Revisión SIN CLASIFICAR») hasta
  revisión humana.
- **C3**: guardar/revertir ROI verifica la escritura; si falla lanza
  `ErrorPersistenciaAprendizaje` y el JSON anterior queda intacto (503 en el
  endpoint, nunca éxito fantasma).
- **C4**: revertir ROI es transaccional: pre-chequeo de decodificación (422),
  snapshot previo, rollback automático si el reanálisis o el JSON fallan (500
  «La reversión se DESHIZO…»), Excel como advertencia no fatal.
- **C5**: `iniciar.command` e `instalar.command` conservan modo 100755.
- **C6**: `AGENTS.md` en la raíz (descubrimiento por Codex) + `.agents/AGENTS.md`.

## 7. Errores visibles y qué hacer

| Error | Causa | Acción |
|---|---|---|
| 400 «Declara el proyecto… o elige «Sin asignar»» | Solicitud sin decisión explícita | Elige proyecto o «Sin asignar» |
| 409 colisión de `project_id` | Mismo ID, otro nombre (P12) | Cambia nombre/ID o corrige el registro |
| 409 «migración explícita» | Reanudar con otro proyecto (P04) | Confirma migración expresa |
| 503 «La ROI no cambió/guardó» | Escritura del aprendizaje fallida (C3) | Reintenta; revisa permisos/disco |
| 500 «La reversión se DESHIZO» | Fallo posterior al reanálisis (C4) | Estado consistente; reintenta |
| ADVERTENCIA en hoja Resumen | Plantilla sin celda de proyecto (P08) | Registra una plantilla con etiqueta «Proyecto:» o acepta el reporte no identificado |
