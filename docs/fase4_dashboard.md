# Fase 4 — Dashboard local de validación OCR

## Propósito

Esta fase presenta los resultados de las Fases 0–3 sin obligar al usuario a abrir
el Excel maestro. El dashboard es local y tiene tres vistas principales:

1. **Resumen:** KPIs, dona del semáforo y distribución apilada por lote.
2. **Listado:** bandeja unificada de carpetas y pruebas complejas, búsqueda,
   cuatro estados de revisión, paginación y navegación por teclado.
3. **Detalle:** todas las imágenes, texto completo, líneas OCR y comparación;
   permite corregir cualquier línea o bloque o dibujar una región omitida.
3. **Procesar carpeta:** valida una ruta local, ejecuta las Fases 0–3 en segundo
   plano y muestra estado, fase actual, errores y finalización.

El banco complejo está unificado en el Listado. Cada fila externa abre un
detalle con métricas para código o texto natural y corrección supervisada.

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
- Las unidades repetidas conservan su `bbox`; la UI y la API usan texto + caja
  para no corregir por accidente otra aparición igual. Un clic en la lectura o
  en su caja la carga en el editor. Una corrección confirmada se pinta en verde.
- Cada imagen tiene giro manual por pasos de 90°. La vista, cajas OCR y regiones
  manuales cambian de inmediato; la preferencia queda asociada al hash y se usa
  al comenzar el OCR siguiente. El detalle también informa la rotación
  automática y el ajuste fino aplicados.
- El texto omitido aparece en la misma lista de aprendizaje supervisado que las
  correcciones OCR, agrupado por la imagen y carpeta actuales.
- La edición solo se habilita durante la revisión y queda bloqueada en
  `completada`; reabrir devuelve el elemento a `parcial`.
- Solo puede ejecutarse un pipeline a la vez. Se rechazan rutas inexistentes y
  la raíz completa del sistema; la tarea corre en un hilo para no bloquear la UI.
- La pausa es cooperativa y segura: termina la inferencia de la imagen actual y
  espera antes de comenzar la siguiente. Continuar reutiliza el modelo cargado.
- La ETA usa una ventana de duraciones recientes y excluye el calentamiento de
  la primera imagen. La pantalla actualiza el reloj cada 250 ms y el backend
  publica avance por imagen.
- La ruta de entrada acepta comillas simples/dobles envolventes. El nombre de
  salida es opcional, se restringe a un nombre de archivo y agrega `.xlsx`.
- Las diez rutas usadas más recientemente se guardan en `localStorage`, junto
  con el nombre de Excel asociado. El usuario puede recuperarlas o quitarlas;
  no se envían a ningún servicio externo.
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

La instalación completa recomendada es `python instalar.py --perfil completo`;
selecciona CUDA, MPS o CPU, crea un entorno aislado cuando corresponde y verifica
PyTorch con una operación real. Los detalles están en
`docs/instalacion_multiplataforma.md`.

Desde la raíz del proyecto:

```bash
python -m venv .venv_dashboard
source .venv_dashboard/bin/activate          # Windows: .venv_dashboard\Scripts\activate
python -m pip install -r dashboard/requirements.txt
python dashboard/backend/app.py
```

El lanzador recomendado y portable es `python iniciar.py`. En macOS/Linux puede
usarse `./iniciar.command` y en Windows `iniciar.bat`; el lanzador elige el
Python local disponible, diagnostica CUDA/MPS/CPU y abre el navegador.

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

La vista de carga permite sobrescribir expresamente un Excel ya existente. Si
la casilla queda desactivada, el backend conserva el archivo y genera una salida
versionada. Las advertencias muestran su motivo al posar el puntero y pueden
marcarse como atendidas; esa decisión persiste en la base de aprendizaje. Las
correcciones confirmadas se reflejan de inmediato en el texto visible y en
verde, sin volver a listar por separado un renglón y sus tokens internos.

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
| `POST /api/pipeline/pausar` | Solicita una pausa segura tras la imagen actual. |
| `POST /api/pipeline/reanudar` | Continúa el mismo lote y modelo cargado. |
| `GET /api/aprendizaje` | Estado, correcciones y versión activa del modelo local. |
| `POST /api/aprendizaje/correcciones` | Registra verdad humana, evalúa y entrena un candidato. |
| `POST /api/aprendizaje/rotaciones` | Memoriza la orientación manual de una imagen. |
| `GET /api/imagen/orientada` | Sirve una vista rotada/enderezada de una imagen autorizada. |
| `POST /api/aprendizaje/rollback` | Reactiva una versión histórica. |
| `GET /api/externas` | Métricas y casos del banco local de imágenes difíciles. |
| `POST /api/externas/evaluar` | Vuelve a ejecutar OCR sobre el banco externo. |
| `GET /api/externas/imagen/{nombre}` | Sirve únicamente una imagen externa permitida. |
| `POST /api/externas/correcciones` | Registra una corrección confirmada del banco externo. |
| `POST /api/externas/regiones` | Guarda una región y texto omitido de una prueba compleja. |

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
