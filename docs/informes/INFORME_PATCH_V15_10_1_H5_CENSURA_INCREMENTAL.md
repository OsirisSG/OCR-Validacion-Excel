# Informe — V15.10.1 incremental H5: censura temporal

**Fecha de preparación:** 14 de octubre de 2026.  
**Rama:** `codex/vmatrix-v15-10-1-corrective-evidence`.  
**Base:** paquete acumulado V15.10.0 y parche previo V15.10.1; este ZIP es incremental y no autónomo.

## Resultado de implementación

Se cerró la sanitización pendiente del detalle API y los controles visuales para `CENSURADO`:

- El contrato canónico conserva la distinción entre tiempo final, raw, referencia, estado y motivo; evento censurado no aporta un tiempo final ni uno propuesto.
- El backend sanea el resumen de apertura, el campo `opening_time_ms`, `video_apertura_anterior`, cada video y su revisión manual anidada. La serialización pública elimina de `tiempo_ms`/`tiempo_propuesto_ms` valores no finitos, no positivos, ilegibles, sin referencia validada o censurados, y añade el registro de rechazo/raw. Una ruta legacy sin resolver canónico falla cerrada.
- La detección de censura contempla banderas/estados del video y de su revisión anidada. La ruta `/api/video/revision` rechaza confirmar una apertura censurada con HTTP 422.
- La tarjeta visual identifica el estado censurado, conserva el raw para auditoría, desactiva “Confirmar apertura aquí” y bloquea también el flujo combinado ROI + apertura. Guardar una ROI por separado continúa disponible.
- El informe Excel no transforma el raw censurado en tiempo final y expone su estado/motivo. Los overlays/offsets conservan signo; no se recalculan tiempos históricos negativos desde frame/FPS.
- Se actualizó la regresión legacy que antes esperaba reparación automática de `−122.8 ms`: ahora verifica preservación histórica y no publicación. No se borró la intención de las pruebas; se ajustó el contrato esperado sin debilitar el control.

El informe no certifica precisión real, calidad de detector ni aprobación de producción.

## Triage de regresión legacy

En la primera corrida ampliada, **157 pasaron y 1 falló**: `test_c5_comandos_mac_conservan_modo_ejecutable` observó `iniciar.command` con modo `0644`. El archivo original en la base tenía modo ejecutable `100755`; restauré el modo `0755` de `iniciar.command` e `instalar.command`. No edité ni omití esa prueba. La repetición completa del grupo seleccionado terminó con **158 passed**.

## Validación ejecutada en esta sesión

`py_compile` y `node --check` terminaron con código de salida 0. La suite de interfaz Node informó **6/6 passed**. La siguiente selección Python informó **158 passed in 15.48s**:

```sh
python -m pytest -q \
 pruebas/test_v15_10_1_h5_tiempos.py \
 pruebas/test_tiempos_apertura_seguros.py \
 pruebas/test_reporte_tiempos_video.py \
 pruebas/test_v15_video_dashboard.py \
 pruebas/test_v15_10_1_matriz_trazabilidad_excel.py \
 pruebas/test_v15_10_contratos.py \
 pruebas/test_v15_10_1_supervision_integrada.py \
 pruebas/PRUEBAS_REGRESION_EDAG_VW_V15_10_0.py \
 pruebas/test_v15_9_2_correcciones_c1_c7.py \
 pruebas/test_v15_9_2_proyecto_c7.py \
 pruebas/test_v15_6_tiempo_video_estable.py \
 pruebas/test_v15_7_bugs_prioritarios.py \
 pruebas/test_ruptura_real.py \
 pruebas/test_liberacion_modelo_visual.py
```

Comprobaciones adicionales ejecutadas antes de esa selección:

```sh
python -m py_compile utilidades/resultado_caso.py video_airbag.py dashboard/backend/app.py utilidades/matriz_apertura.py reporte_bmg.py
node --check dashboard/frontend/app.js
node --test pruebas/test_v15_10_1_aceptacion_ui.cjs
```

No se ejecutó la suite completa ni R01–R20/Z01–Z26 en su totalidad. Los tests son sintéticos/aislados; no constituyen un piloto real.

## Atribución de evidencia

La auditoría adjunta `docs/adjuntos_usuario/AUDITORIA_APRENDIZAJE_V_MATRIX_RESPUESTAS_INCORPORADAS_20261013.md` reporta, como hallazgo suyo, siete revisiones manuales de video confirmadas y una con `−122.8 ms`. **No** repetí esas mediciones ni abrí la carpeta `.aprendizaje`; el dato negativo se utiliza como escenario de regresión a partir de la auditoría aportada, no como lectura nueva de una base real. No se alteraron datos reales.

## Límites y siguiente paso seguro

- No hubo acceso, copia, inspección ni modificación de `.aprendizaje`.
- No hubo piloto con videos/fotografías reales autorizados ni aprobación de producción.
- Antes de aplicar, verificar el sidecar SHA-256, extraer a staging y respaldar cada ruta reemplazada. Aplicar sólo los paths del manifiesto; no usar operaciones espejo/destructivas.
- Para rollback, restaurar rutas existentes desde respaldo y mover los archivos nuevos del parche a cuarentena. Conservar el respaldo y el ZIP.
- Los ZIP V15.10.0 y el parche V15.10.1 anterior se conservan sin sobrescribir.
