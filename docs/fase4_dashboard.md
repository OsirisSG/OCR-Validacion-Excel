# Fase 4 — Dashboard local de validación OCR

## Propósito

Esta fase presenta los resultados de las Fases 0–3 sin obligar al usuario a abrir
el Excel maestro. El dashboard es local y tiene cinco vistas:

1. **Resumen:** KPIs, dona del semáforo y distribución apilada por lote.
2. **Listado:** bandeja unificada de carpetas y pruebas complejas, búsqueda,
   revisión completada/pendiente, paginación y navegación por teclado.
3. **Detalle:** todas las imágenes, texto completo, líneas OCR y comparación;
   permite corregir cualquier línea o bloque o dibujar una región omitida.
4. **Procesar carpeta:** valida una ruta local, ejecuta las Fases 0–3 en segundo
   plano y muestra estado, fase actual, errores y finalización.
5. **Pruebas complejas:** banco externo visible, métricas separadas para códigos
   y texto natural, reevaluación y corrección supervisada.

La Fase 4b trabaja por dirección local: no sube ni duplica los archivos del lote.
Esta decisión evita copiar hasta 8 GB al navegador y conserva el procesamiento
completamente local.

## Arquitectura y decisiones de diseño

- `dashboard/backend/app.py`: FastAPI lee `validacion_resultados.json`, reutiliza
  `configuracion.clasificar()` y sirve el frontend y las imágenes autorizadas.
- `dashboard/frontend/`: React 18 + `htm`, vendorizados localmente. No hay CDN,
  acceso a internet, Node.js ni paso de compilación en producción.
- `estilos.css`: sistema de diseño tipo Tremor (tarjetas KPI, jerarquía visual,
  tablas y gráficas) implementado con CSS nativo. Tremor como paquete requiere
  un proceso de build; se descartó para conservar el requisito explícito de
  frontend sin build.
- Las gráficas usan SVG/CSS nativo. Se descartó agregar Recharts porque la dona
  y la barra apilada actuales no justifican otra dependencia.
- Los resultados se cachean por `mtime`; al terminar una nueva ejecución del
  pipeline, el backend relee el JSON automáticamente.
- El detalle permite confirmar una corrección de token, línea o bloque
  multilinea. FastAPI valida que el texto y la imagen pertenezcan al resultado
  antes de registrar la evidencia supervisada.
- Solo puede ejecutarse un pipeline a la vez. Se rechazan rutas inexistentes y
  la raíz completa del sistema; la tarea corre en un hilo para no bloquear la UI.
- Antes de habilitar el botón, `/api/pipeline/capacidad` comprueba OpenCV,
  NumPy, openpyxl, PyYAML y al menos un motor PaddleOCR/EasyOCR.
- Los fallos iniciados desde la UI crean automáticamente una bitácora Markdown
  en `errores/`, además de mostrarse en el panel de estado.
- Cada fila recibe un id SHA-256 corto derivado de su ruta. Así dos lotes pueden
  contener carpetas con el mismo nombre sin abrir un detalle ambiguo.
- Las rutas de imagen se validan contra las imágenes registradas en el resultado
  y contra la raíz procesada. Los artefactos generados en Windows se pueden
  reubicar bajo `datos_prueba/` al ejecutar el dashboard en otro sistema.
- La interfaz muestra la ruta local efectiva y conserva la ruta original solo
  como metadato de API; no presenta una ruta antigua de Windows como vigente.
- No se habilita CORS global: el frontend se sirve desde el mismo FastAPI y el
  proceso escucha únicamente en `127.0.0.1`.

## Instalación y ejecución

Desde la raíz del proyecto:

```bash
python -m venv .venv_dashboard
source .venv_dashboard/bin/activate          # Windows: .venv_dashboard\Scripts\activate
python -m pip install -r dashboard/requirements.txt
python dashboard/backend/app.py
```

Para utilizar **Procesar carpeta**, el dashboard debe iniciarse desde el mismo
entorno Python funcional usado por el pipeline OCR; `dashboard/requirements.txt`
instala solamente la capa web y no los motores pesados de visión.

Para cualquier plataforma se ofrece un entorno completo con EasyOCR:

```bash
python -m pip install -r dashboard/requirements-ocr-fallback.txt
```

Abrir `http://127.0.0.1:8000`. El puerto se cambia en `config.yaml`:

```yaml
dashboard:
  raiz_datos_permitida: null  # null = raíz del último pipeline
  puerto: 8000
```

## Contrato de la API

| Método y ruta | Propósito |
| --- | --- |
| `GET /api/estado` | Indica si existen resultados, total y fecha de generación. |
| `GET /api/config` | Expone paleta y reglas para que Excel y UI sean coherentes. |
| `GET /api/resumen` | KPIs, porcentajes y distribución por lote. |
| `GET /api/pruebas` | Lista con `q`, `estado`, `limit` y `offset`. |
| `GET /api/pruebas/{id}` | Detalle OCR de una carpeta por id estable. |
| `GET /api/imagen?ruta=...` | Sirve solo una imagen registrada y dentro de la raíz permitida. |
| `GET /api/pipeline/capacidad` | Informa si el entorno contiene las dependencias OCR. |
| `GET /api/pipeline/estado` | Avance, porcentaje, ETA y resultados parciales de la ejecución. |
| `POST /api/pipeline` | Valida una ruta local e inicia las Fases 0–3 en segundo plano. |
| `GET /api/aprendizaje` | Estado, correcciones y versión activa del modelo local. |
| `POST /api/aprendizaje/correcciones` | Registra verdad humana, evalúa y entrena un candidato. |
| `POST /api/aprendizaje/rollback` | Reactiva una versión histórica. |
| `GET /api/externas` | Métricas y casos del banco local de imágenes difíciles. |
| `POST /api/externas/evaluar` | Vuelve a ejecutar OCR sobre el banco externo. |
| `GET /api/externas/imagen/{nombre}` | Sirve únicamente una imagen externa permitida. |
| `POST /api/externas/correcciones` | Registra una corrección confirmada del banco externo. |

Ejemplo abreviado de salida de `GET /api/pruebas?estado=rojo`:

```json
{
  "total": 2,
  "items": [{
    "id": "1591b79b2dd88a80",
    "identificador": "04_B7_variante2",
    "resultado": "discrepancia",
    "confianza_ocr_pct": 99.97,
    "semaforo": "rojo"
  }]
}
```

Una ausencia de datos devuelve `404` en resumen/listado y activa el estado vacío
de la UI. Un JSON ilegible o con estructura incorrecta devuelve `503` y activa
un estado de error con opción de reintento.

## Paleta y accesibilidad

La única fuente de verdad es `config.yaml`:

| Estado | Hex |
| --- | --- |
| Verde | `#22c55e` |
| Amarillo | `#f59e0b` |
| Rojo | `#ef4444` |

Excel usa estos hex como relleno. El dashboard los usa directamente en gráficas,
barras y bordes/swatch de estado; el texto de los chips permanece sobre el color
de superficie para conservar contraste legible en claro y oscuro.

La tabla admite `Tab`, `↑`, `↓` y `Enter`; los controles tienen etiquetas ARIA y
foco visible. Se respeta `prefers-reduced-motion`. En móvil, la tabla deja de ser
horizontal y cada fila se convierte en tarjeta etiquetada.

## Verificación realizada (2026-08-30)

- Contrato automatizado: `25 passed` en la suite completa.
- Sintaxis: `python -m py_compile dashboard/backend/app.py` y
  `node --check dashboard/frontend/app.js` sin errores.
- Escritorio: KPIs, dona, barra por lote, búsqueda `04_B7`, filtro y detalle.
- Imágenes: etiqueta y referencia cargaron a `1040 × 760` desde resultados cuyas
  rutas originales provenían de Windows.
- Tema claro/oscuro: cambio inmediato y persistente, sin recarga.
- Móvil `390 × 844`: cinco KPIs apilados, tabla convertida a tarjetas,
  `scrollWidth = 390` y sin desbordamiento horizontal.
- Consola del navegador: sin errores ni advertencias después del ajuste final.
- Progreso: reloj visual actualizado cada 250 ms, porcentaje por imagen,
  carpetas e imágenes totales/procesadas/restantes, ETA recalculado y tabla que
  recibe cada carpeta terminada antes del cierre del pipeline.
- Detalle: las 13 imágenes del lote de prueba quedaron disponibles, incluidas
  las tres de `01_A1_variante2`, con espacios y saltos de línea editables.
- Revisión: carpetas y banco externo conviven en el listado. Cada registro puede
  completarse, reabrirse, quitarse o restaurarse sin borrar evidencia original.
- Banco complejo: ocho fotografías externas visibles, acceso restringido por
  nombre, cobertura de texto completo y correcciones conectadas al modelo
  supervisado.

Para repetir las pruebas del backend (requiere `pytest` y `httpx` en el entorno):

```bash
python -m pytest -q pruebas/test_dashboard.py
```

## Limitaciones conocidas y parámetros pendientes

- No hay autenticación: el servidor está diseñado para uso local y enlaza solo
  a loopback. Si se publica en una red interna, se debe agregar autenticación,
  HTTPS y política explícita de orígenes.
- Las correcciones se almacenan localmente; todavía no existe autenticación ni
  flujo de aprobación para múltiples revisores.
- La ejecución en segundo plano no tiene cancelación en esta versión. Solo se
  admite una carpeta simultánea para proteger RAM/VRAM y los archivos maestros.
- Los rangos del semáforo siguen parametrizados en `reglas_cumplimiento.yaml` y
  deben calibrarse con lotes reales.
- `raiz_datos_permitida` puede fijarse a una ruta explícita cuando la empresa
  defina el directorio de producción.

## Resumen de cierre de fase (§11)

- **Implementado:** backend FastAPI, frontend React sin build, cinco vistas,
  temas, responsive, estados de carga/vacío/error, filtros, paginación, acceso
  seguro a imágenes, corrección supervisada, paleta unificada con Excel y Fase
  4b por ruta local con comprobación de dependencias, progreso granular y banco
  local de pruebas OCR complejas.
- **Markdown generado:** este archivo `docs/fase4_dashboard.md`.
- **Pendiente/parametrizado:** autenticación si se publica en red, cancelación
  del pipeline, revisión multiusuario y calibración con datos reales.
