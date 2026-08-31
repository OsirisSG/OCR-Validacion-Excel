# Fase 3 — Consolidación en Excel maestro (`generar_excel.py`)

## Propósito

Lee `validacion_resultados.json` (Fase 2) y genera `resultado_maestro.xlsx`
con **cuatro hojas**: "Estructura completa" (evidencia por carpeta), "Matriz de
cumplimiento" (semáforo), "Textos por imagen" (carpeta → imagen → región) y
"Bandeja de revisión" (carpetas y pruebas complejas unificadas). El motor de
reglas lee `reglas_cumplimiento.yaml`
dinámicamente: **ningún rango está fijo en el código**; cambiar el YAML cambia
el Excel (y el dashboard usa el mismo motor vía `configuracion.clasificar`).

```
python generar_excel.py [--validacion ruta.json] [--salida ruta.xlsx]
```

## Hoja "Estructura completa" (una fila por carpeta procesada)

Columnas (las exigidas por el Documento Maestro §5): Ruta · Identificador ·
Variante · Tipos de archivo · Imágenes procesadas · Texto etiqueta (OCR) ·
Texto referencia (OCR) · Texto de todas las imágenes (OCR) · Resultado
comparación · Confianza OCR (%) · QR detectado · Anomalías Fase 0 ·
Observaciones. El texto completo conserva renglones dentro de la celda. La hoja
usa encabezado fijo (freeze panes) y autofiltro.

Las regiones confirmadas manualmente se añaden con origen `Manual`, coordenadas
y confianza humana. Las pruebas externas usan el grupo `Pruebas complejas`.
Todas las filas incluyen `Completada` o `Por revisar`; los elementos quitados
siguen en la bandeja con la marca `Quitado del listado = Sí`.

## Hoja "Matriz de cumplimiento" (semáforo)

| Mecanismo | Criterio | Implementación openpyxl |
| --- | --- | --- |
| Numérico continuo | Confianza OCR (%) | `ColorScaleRule` 3 paradas: rojo en 70, amarillo en 79.5, verde en 90 (extremos **leídos del YAML** "70-89" y ">= 90") |
| Categórico | Coincidencia texto | `CellIsRule(operator="equal")` con relleno por valor: coincidencia_total→verde, coincidencia_parcial→amarillo, discrepancia/sin_referencia→rojo |
| Global | Semáforo global | columna con relleno sólido = color más restrictivo entre criterios (evaluado por `configuracion.clasificar`, mismo motor que el dashboard) |

Los colores vienen de `config.yaml → colores` (verde #22C55E, amarillo #F59E0B,
rojo #EF4444): **el mismo hex que usa el dashboard** (requisito visual §6).

## Ejemplo de fila real y su color, paso a paso (04_B7_variante2)

Datos de la fila: confianza OCR = **99.97** (etiqueta foto_frontal.jpg,
ETQ-2024-B7-V2), comparación = **discrepancia** (la ficha dice ETQ-2024-B7-V9),
QR = Sí.

1. Criterio `confianza_ocr` (YAML: verde ">= 90", amarillo "70-89", rojo "< 70"):
   99.97 ≥ 90 → **verde**. En la matriz, la escala de color pinta la celda de
   la columna Confianza cerca del extremo verde de la rampa.
2. Criterio `coincidencia_texto` (YAML: rojo "discrepancia,sin_referencia"):
   "discrepancia" ∈ {discrepancia, sin_referencia} → **rojo**. El CellIsRule
   correspondiente rellena la celda de Coincidencia con #EF4444.
3. Semáforo global = el más restrictivo entre {verde, rojo} = **rojo** → la
   celda "Semáforo global" se rellena con #EF4444 en negrita blanca.

Resultado verificado al re-leer el archivo (openpyxl, `pruebas/verificar_excel.py`):

```
Identificador   conf    coinc              semaforo        fill
01_A1           99.98   coincidencia_total verde           FF22c55e
02_A1           99.98   coincidencia_total verde           FF22c55e
03_B7           99.98   coincidencia_total verde           FF22c55e
04_B7           99.97   discrepancia       rojo            FFef4444
05_C2           99.99   sin_referencia     rojo            FFef4444
notas_sueltas   —       sin_procesar       sin clasificar  (sin relleno)
```

Nota el caso 05_C2: confianza 99.99 (verde en confianza) pero sin referencia
→ semáforo global rojo. La fila `notas_sueltas` (carpeta anómala sin imágenes)
queda **sin clasificar** a propósito: no es una prueba fallida, es una carpeta
que la Fase 0 ya marcó; pintarla de rojo invitaría a "corregir" algo que no es
una lectura defectuosa.

## Formato de entrada/salida

- Entrada: `validacion_resultados.json` (formato en docs/fase2_validacion.md).
- Salida: `resultado_maestro.xlsx` (nombre configurable en
  `config.yaml → fase3.archivo_salida`).

## Decisiones de diseño y alternativas descartadas

- **ColorScaleRule con paradas `num` en los umbrales del YAML** (no percentiles):
  la rampa respeta los rangos declarados; con percentiles, el verde/rojo
  dependería de la distribución del lote y dos ejecuciones del mismo criterio
  pintarían distinto.
- **Semáforo global = peor color** (no promedio): una prueba con texto
  discrepante no debe "compensarse" con un OCR excelente; el revisor humano
  prioriza los peores.
- **"sin clasificar" sin relleno**: las filas no evaluables (carpeta anómala,
  sin imágenes) no son rojas ni verdes; quedan explícitamente fuera del
  semáforo con su motivo en Observaciones.
- Alternativa descartada: fórmulas de Excel embebidas (`FormulaRule` con
  umbrales hardcodeados en la fórmula) — rompería la regla de que los rangos
  viven en el YAML.

## Parámetros configurables

| Parámetro | Default |
| --- | --- |
| `fase3.archivo_salida` | resultado_maestro.xlsx |
| `fase3.hoja_estructura` / `fase3.hoja_matriz` | "Estructura completa" / "Matriz de cumplimiento" |
| `reglas_cumplimiento.yaml → criterios` | confianza: verde ≥90 / amarillo 70-89 / rojo <70; coincidencia: total / parcial / discrepancia+sin_referencia (PARÁMETRO ABIERTO §10.1) |
| `config.yaml → colores` | #22C55E / #F59E0B / #EF4444 (compartidos con el dashboard) |

## Limitaciones conocidas

- La escala de color continua solo distingue 3 paradas; si el YAML declarara
  más niveles (p.ej. ">= 98 verde intenso"), habría que extender el generador
  de la regla (paradas adicionales de ColorScaleRule).
- No hay totales ni gráficos dentro del Excel: esa visualización vive en el
  dashboard (Fase 4), que consume estos mismos datos.
