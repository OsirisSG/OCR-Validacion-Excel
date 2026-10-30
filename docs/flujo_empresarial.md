# Flujo empresarial 1ST/2ST

## Activación y fallback

`estructura.py` busca `1ST` y `2ST` en la ruta seleccionada, sus superiores y
sus hijas inmediatas. Reconoce cada caso mediante:

```text
<ID> <RDW|RWD|NAR> <NOM|OGL|UGL> <HT|NT|RT>
```

`RWD` se conserva como valor original y se normaliza a `RDW`. Un caso es válido
si su carpeta superior coincide con la temperatura y existen `PHOTOS/NACH` y
`PHOTOS/VOR`. La decisión es por caso: uno incompleto usa el recorrido legacy
sin degradar los demás. Si el tipo ST es ambiguo, el dashboard y el CLI permiten
seleccionar `1ST`, `2ST` o `LEGACY`.

## Recorrido y rendimiento

Un caso válido recorre exclusivamente:

- `PHOTOS/NACH/**`
- `PHOTOS/VOR/**`, incluidas las carpetas `TOR X`

No procesa `DIAGRAMM`, `TEMPERATURE` ni `VIDEOS`. EasyOCR mantiene un único
`Reader` en memoria. CRAFT detecta cajas sobre una miniatura de hasta 1280 px;
si no encuentra cajas, la foto queda `descartada_sin_texto` sin ejecutar el
reconocedor. Si hay cajas, se trasladan a la resolución original, se amplían con
margen, se corrige el cuadrilátero cuando existe y sólo se amplía el recorte.
Una segunda pasada CLAHE/enfoque/rotación se reserva para ausencia o baja
confianza. CUDA se usa primero y una falla de memoria retrocede a CPU.

## Consolidación y trazabilidad

Todas las fotos del mismo `case_key` aportan candidatos a las 36 claves de la
plantilla. Ruta/nombre estructurado tiene prioridad; coincidencias en varias
fotos aumentan la confianza y valores incompatibles generan un conflicto sin
sobrescritura. Los campos ausentes permanecen vacíos y los requeridos quedan
marcados para revisión.

`validacion_resultados.json` conserva casos, candidatos, campos, conflictos,
faltantes, progreso, historial de ejecuciones y acciones manuales. Las
correcciones de campos quedan en `correcciones_manual_campos`, se reflejan de
inmediato en el JSON/Excel y sobreviven al reprocesamiento. `Trazabilidad_OCR` contiene una
fila por fotografía. El caché `.cache_ocr/imagenes.json` usa ruta, tamaño,
`mtime`, versión del parser y hash de la configuración para decidir si reutiliza
una lectura.

## Conocimiento auditable

`base_conocimiento.json` almacena reglas `propuesta`, `confirmada`, `rechazada`
o `desactivada`. Se propone una regla sólo después de al menos tres IDs y 90 %
de consenso. Una propuesta nunca rellena celdas. Incluso confirmadas, las reglas
no pueden heredar seriales, fechas, tiempos, comentarios, evaluaciones,
defectos ni rutas.

## Lista y resultados

El backend publica el mismo identificador estable en `/api/pruebas`,
`/api/casos` y los resultados parciales de `/api/pipeline/estado`. Los casos
aparecen durante el descubrimiento y se reemplazan —no se duplican— al pasar a
procesando/procesado. El detalle muestra fotos, textos, faltantes, conflictos y
trazabilidad; permite corrección, ROI, revisión y reproceso del ID o sólo de sus
errores. También puede reprocesarse únicamente la imagen visible. El apartado
Procesar carpeta enlaza al mismo `#/detalle/<id>`.

## Archivos locales

- `.cache_ocr/imagenes.sqlite3`: caché OCR transaccional reanudable.
- `.cache_ocr/avances_ids.json`: evidencia del ID activo y marcadores de IDs
  completados; no se borra al pausar o detener.
- `.cache_ocr/estado_pipeline.json`: checkpoint del dashboard.
- `base_conocimiento.json`: reglas empresariales versionadas y auditables.
- `.aprendizaje/aprendizaje.sqlite3`: correcciones OCR y regiones supervisadas.
- `estructura_detectada.json`: estructura y casos descubiertos.
- `validacion_resultados.json`: consolidación y trazabilidad.

Estos artefactos contienen rutas o conocimiento local y están excluidos de Git.
Los JSON de caché usan temporales únicos, `fsync`, bloqueo por destino y
reintentos para tolerar antivirus/indexadores de Windows sin abortar el OCR.
