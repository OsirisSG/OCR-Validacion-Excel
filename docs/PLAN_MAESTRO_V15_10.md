# V-Matrix V15.10 — Plan maestro de automatización integral: apertura, OCR, aprendizaje y Excel

**Estado:** propuesta técnica de implementación; no es software implementado ni certificación de exactitud.  
**Fecha:** 13 de octubre de 2026.  
**Base obligatoria:** V15.9.10 acumulada sobre GitHub `OsirisSG/OCR-Validacion-Excel`, rama original `codex/ocr-v15-8-1-organizacion`. Desarrollar en rama nueva, sin alterar la versión anterior.  
**Problema real:** la extracción OCR y la asignación de información a campos pueden seguir requiriendo corrección humana; además, la herramienta encuentra ROIs útiles, pero aún necesita demasiada intervención para identificar el *primer instante físico visible de apertura*; algunos tiempos no alcanzan el consenso y la matriz los muestra grises; además, la matriz actual crea vacantes artificiales cuando una categoría contiene menos casos que una cuota fija.

> **Misión:** que V-Matrix pueda localizar y extraer los códigos correctos, asignarlos a campos con evidencia, llenar el Excel de manera segura, aprender de correcciones y también detectar, cuestionar, confirmar y explicar **automáticamente** el instante de apertura de un airbag a partir de evidencia visual y temporal; que aprenda de intervenciones humanas y que únicamente pida ayuda cuando exista una incertidumbre real. **Automatizar al máximo sin fabricar certidumbre.**

## 1. Cambio de filosofía: de «detector» a «sistema que se audita a sí mismo»

Actualmente V15.9.10 ya tiene: resolución nativa, compensación de movimiento, indicios claros/oscuros, confirmación con fotogramas posteriores, backtracking, ROI manual y sugerida, aprendizaje del evento, lectura de FPS reales, consenso multicámara, revisión manual y matriz. **Preservar y reutilizar todo lo que funciona.** No vender como nuevas esas capacidades.

Lo que falta es una **capa explícita de decisión autónoma**, con cinco responsabilidades:

1. **Encontrar:** detectar varios posibles instantes y regiones de inicio, no quedarse necesariamente con el primer umbral superado.
2. **Intentar desmentir:** buscar reflejos, vibración, texto overlay, compresión, cámara que no ve el evento, señal anterior al supuesto inicio, escena ya abierta desde el comienzo y movimientos no correspondientes a ruptura.
3. **Corroborar en el tiempo:** verificar cómo evoluciona la fisura/tela material, manteniendo como candidato el *primer indicio* que recibe corroboración posterior; no desplazarlo al fotograma en que la bolsa ya está grande.
4. **Corroborar entre cámaras con relojes verificados:** contrastar la misma referencia temporal; no contar como evidencia independiente la misma cámara duplicada ni forzar acuerdo donde hay oclusión.
5. **Decidir si puede actuar solo:** aceptar automáticamente solo cuando cumple una política versionada, calibrada en datos reales y sin alertas graves; de lo contrario entregar propuesta, razones y los cuadros exactos a revisar.

**Definición operacional:** «Apertura inicial» = primer fotograma en el que aparece evidencia nueva de ruptura/expulsión material atribuible al airbag, con continuidad física razonable en fotogramas posteriores y evidencia previa de que aún no había iniciado. Abombamiento, brillo aislado y despliegue máximo **no son** apertura inicial. Donde el hecho es ambiguo, guardar un intervalo de inicio y no declarar precisión no demostrada.

## 2. Evidencia sobre el código existente y problemas comprobables

| Archivo y componente actual | Fortaleza que se conserva | Mejora concreta |
|---|---|---|
| `video_airbag.py::_metricas_primer_blanco` | Detecta indicios nuevos claros y oscuros y compensa movimiento | Señales multimodales normalizadas por cámara; registrar mapa de residuos y calidad del registro, falsos positivos explicados |
| `video_airbag.py::_evaluar_confirmacion` / `_buscar_inicio_confirmado` | Corroboración posterior + retroceso | Evaluar **varias hipótesis de onset** y buscar contradicciones, no solo una selección de umbral |
| `video_airbag.py::analizar_video` | ROI a resolución nativa, línea de base, lectura de FPS y caché | Análisis grueso→fino con revisión obligatoria nativa del inicio, manejo de baseline contaminado y clips truncados |
| `video_airbag.py::_cfg` | Umbrales configurables; `tolerancia_consenso_ms=0.15`; `min_videos_consenso=3` | Separar tolerancia temporal de resolución y **sincronización real entre cámaras**, no ampliar 0.15 ms arbitrariamente |
| `video_airbag.py::consenso_videos` / `consenso_valido` | Regla de consenso y protección contra resultados no confirmados | Elegibilidad de cámara, desfase temporal, incertidumbre, duplicados, discordancia y decisión autónoma versionada |
| `aprendizaje_video_airbag.py::seleccionar_zona_aprendida` | ROI sugerida y ROI manual bloqueada | Sugerencia jerárquica por cámara/escena; estimación de confianza de alineación; nunca mover una manual guardada |
| `aprendizaje_video_airbag.py::localizar_nacimiento_evento` / `guardar_ejemplo_evento` | Microzona y ejemplos F−3…F+3 | Aprender ejemplos positivos y **negativos difíciles**, trayectoria, punto inicial y contexto de cámara |
| `utilidades/benchmark_detector.py` | Benchmark de rendimiento CPU/RAM y detector | Benchmark de **exactitud**, automatización efectiva y seguridad, por familias de escenas, sin fuga de datos |
| `utilidades/matriz_apertura.py` / `reporte_bmg.py` | Semáforo compartido con Excel | Vista dinámica por **casos existentes** y estados explicables; no inventar casillas ni tiempos |
| `dashboard/backend/app.py` / `dashboard/frontend/app.js` | Revisión video, zoom, listado y matriz | Único estado canónico para detalle/listado/matriz/Excel; revisión por excepción y comparación de cuadros |

**Límite importante:** las capturas muestran p. ej. 1.8 ms y 2.2 ms en cámaras/escenas diferentes. Eso no prueba que una u otra detección sea errónea; tampoco demuestra que las cámaras compartan el mismo cero temporal. Antes de exigir consenso debe verificarse la alineación temporal y si muestran el mismo fenómeno.

## 3. Arquitectura propuesta: «V-Matrix Onset Intelligence»

```text
AVI / proyecto / cámaras / criterios elegidos
         |
         v
[1] Inventario, huella, integridad y contexto temporal
    FPS de adquisición vs reproducción, overlay, origen, calidad, cámara
         |
         v
[2] ROI manual inmutable + ROI sugerida + microzona probable
         |
         v
[3] Detector de candidatos (múltiples evidencias)
    grieta oscura | material claro nuevo | discontinuidad de borde
    residuo no explicable por movimiento | cambio de fase temporal
         |
         v
[4] Refinador de primer fotograma
    inspección nativa F-k ... F ... F+k; retroceso hasta primer indicio
         |
         v
[5] «Verificador adversarial» independiente
    ¿había evidencia antes?, ¿es brillo/reflejo/compresión?,
    ¿hay continuidad física?, ¿ROI confiable?, ¿video censurado?
         |
         v
[6] Alineación temporal y corroboración multicámara
    tiempos comparables, vistas elegibles, intervalos de incertidumbre
         |
         v
[7] Política de decisión / abstención
    CONFIRMADO_AUTOMÁTICO | PROPUESTA_REVISAR | SIN_EVENTO
    EVENTO_ANTES_DEL_CLIP | NO_EVALUABLE | CONFLICTO
         |
         +--> Confirmados: tiempo + evidencia + Excel + matriz
         +--> Dudosos: cola priorizada, cuadros y razones específicas
         +--> Confirmaciones humanas: aprendizaje supervisado versionado
```

No insertar un «modelo de IA» opaco que decida todo. Implementar primero un **sistema híbrido** de visión clásica, señales temporales, reglas verificables y calibración. Introducir un modelo temporal entrenable (por ejemplo, un clasificador liviano sobre secuencias de features o un modelo ONNX local) **solo si supera objetivamente** a la línea base en datos reservados.

## 4. Detector robusto del primer indicio: algoritmos y requisitos

### 4.1 Preparación y análisis de calidad (P0)

- Obtener FPS de **adquisición real** desde evidencia validada (`Rec5000 fps`, metadatos coherentes, y validación del reloj), no confiar en el FPS de playback como si fuera físico.
- Leer frames secuencialmente cerca del evento, controlar decodificación duplicada/perdida y firmas del video. Las búsquedas por `CAP_PROP_POS_FRAMES` pueden caer en cuadros distintos según codec: contrastar índice y tiempo observado; no confirmar con un seek ambiguo.
- Detectar exposición súbita, blur, vibración, cambios globales, overlay fijo, saturación, compresión y oclusión. Guardar `calidad_video` y `calidad_roi` de manera estructurada.
- **Baseline no contaminado:** analizar los frames iniciales; si el airbag ya aparece, emitir `evento_al_inicio`, con instante anterior al primer frame (censurado por izquierda), y no inventar `0.0 ms`. Si la referencia es inestable, usar baseline local previo al candidato solo después de verificar ausencia de evento; comparar ambas estrategias.

### 4.2 Detectores complementarios (P1)

Cada detector emite candidatos `{frame, region, tipo_senal, evidencia, limitaciones}`:

1. **Cambio residual tras registro:** estimar transformación con zonas estáticas de la escena *fuera* del airbag; usar ECC/flujo/phase correlation condicional, con máscaras para que el propio airbag no arrastre el registro. Fallback conservador si el registro falla.
2. **Novedad geométrica local:** aparición de contorno de fisura, segmento oscuro o tela blanca con morfología/continuidad compatible con apertura; admitir señales de 1 píxel solo si hay corroboración posterior y ruido de sensor aceptable.
3. **Persistencia y crecimiento espacial:** asociar componentes próximos F, F+1, F+2... y medir evolución/centro/desplazamiento sin imponer «área creciente en absolutamente todos los cuadros».
4. **Cambio de régimen temporal:** usar una serie de features (`residuo_ROI`, bordes nuevos, área componente, estabilidad, movimiento) y técnicas de change-point como comparador adicional; esto **genera hipótesis**, no etiqueta directamente un despliegue como apertura.
5. **Coherencia con referencia aprendida:** según cámara, orientación, tipo de bolsa, geometría y escena; la falta de parecido debe reducir confianza en una sugerencia, nunca invalidar por sí sola un nacimiento real no visto antes.
6. **Clase negativa explícita:** abombamiento sin grieta, reflejo de ventanilla, brazo/objeto cruzando ROI, texto superpuesto, ruido de compresión, flash, desplazamiento general de cámara y ninguna apertura.

No sumar señales altamente correlacionadas como si fueran «seis votos independientes». Guardar features y, más adelante, aprender una calibración respaldada por ejemplos. Proponer **top-3 hipótesis** si hay duda, no solo un número falso de confianza.

### 4.3 Búsqueda grueso→fino sin perder el primer píxel (P1)

- Primera pasada: miniaturas/regiones y medidas baratas para localizar ventanas de actividad, **con salvaguardas contra eventos precoces** y evento al inicio.
- Segunda pasada: examinar a **resolución nativa, fotograma por fotograma**, toda ventana candidata más margen anterior y posterior; no saltarse el fotograma inicial.
- Tercera pasada: retroceder hasta el **primer cuadro físicamente sustentado** y marcar el siguiente como evidencia de continuidad, no mover la marca de inicio al cuadro más grande.
- Si los detectores discrepan, producir `[f_min, f_max]` o una lista priorizada de cuadros en vez de un falso punto exacto.
- Conservación opcional de mapas de calor solo en copia o vista derivada; el archivo AVI original es de solo lectura.

### 4.4 Revisión adversarial automática (P1)

Desarrollar módulo `utilidades/verificador_apertura.py` que reciba candidatos del detector y **busque señales contrarias** en un recorrido distinto:

- Dos/cuatro cuadros anteriores sin indicio concordante, cuando existan.
- F y posteriores muestran una continuación compatible con ruptura, no mero brillo transitorio.
- La señal no es explicada por movimiento de una superficie que conserva su textura.
- El candidato no pertenece al texto/timestamp/overlay en pantalla ni a zona excluida.
- No existe otra hipótesis anterior más plausible en otra subzona del ROI.
- La imagen no se degradó por el codec/baja calidad hasta impedir una conclusión.

Emitir `razones_a_favor[]`, `razones_en_contra[]`, `calidad_registro`, `estado_revision`, `fotogramas_evidencia[]`, `version_verificador`. **La autoverificación no es una garantía de verdad:** compartir el mismo video, ROI y features puede crear errores correlacionados. Validar su eficacia contra casos difíciles anotados por humanos.

## 5. Tiempo físico y cámaras: no exigir un consenso imposible

Para cámara `i`, definir formalmente:

`tiempo_local_i(f) = t0_i + (f - frame0_i) × (1000 / fps_adquisicion_i)`

La comparación multicámara debe usar un **tiempo común probado**, por ejemplo `tiempo_global_i = a_i × tiempo_local_i + b_i`, cuyos parámetros provienen del disparador/reloj/overlay verificado, no de alinear artificialmente los tiempos detectados de las propias bolsas.

**Puntos críticos:**

- A **5,000 FPS**, cada frame representa **0.2 ms**. En V15.9.10 `tolerancia_consenso_ms` predeterminada es `0.15`, inferior a un frame. Puede ser correcta con relojes bien alineados y medición fina, pero puede descartar acuerdos de cámaras discretizadas/desfasadas. **Medir** el error de sincronización primero. La ventana de acuerdo debería depender de resolución, error de alineación y política explícita.
- A **1,000 FPS**, un frame son **1.0 ms**; mostrar `1.8 ms` no implica que el nacimiento tenga exactitud real de 0.1 ms. Separar `resolucion_ms`, `intervalo_tiempo_ms`, `incertidumbre_ms` y `decimales_visualizacion`.
- Identificar vistas elegibles. Una cámara lateral puede mostrar primero un cambio distinto del detalle de la zona de ruptura; una cámara completamente ocluida no es un «voto negativo», y la misma cámara duplicada no suma dos votos.
- Preservar la política vigente 3/4 para **auto-publicación**, pero registrar `visibilidad`, cámaras excluidas, duplicados y causas; no inventar 3 coincidencias ni reducir silenciosamente el umbral cuando hay 1–2 vistas. Introducir nuevas reglas adaptativas **solo con pruebas y aprobación explícita**.
- Diferenciar `tiempo_de_ruptura`, `tiempo_de_primera_aparicion_en_camara` y `tiempo_maximo_visible`. Pueden diferir por campo de visión; no mezclar máximos, fases de expansión ni primera evidencia periférica en un solo promedio.
- El criterio de consenso es **del evento**, no una media ciega de valores. Si hay una hipótesis temprana y tres posteriores, determinar si la temprana era falsa o detectaba legítimamente antes; guardar discordancia cuando no pueda probarse.

Modelo sugerido por resultado: `tiempo_ms`, `frame`, `intervalo_ms`, `resolucion_ms`, `origen_tiempo`, `calibracion_temporal`, `camaras_elegibles`, `soporte`, `evidencias`, `motivos_pendiente`, `auto_confirmable`, `version_politica`.

## 6. Motor de decisión con incertidumbre y abstención (P0–P1)

El sistema debe separar estas nociones:

- `score_candidato`: intensidad de la evidencia visual. **NO** equivale a «95 % de probabilidad de estar correcto».
- `probabilidad_calibrada` (opcional): solo si se estima y valida frente a etiquetados reales nunca utilizados en entrenamiento/ajuste.
- `calidad_temporal`: FPS, reloj, sincronización, resolución y fotogramas íntegros.
- `evidencia_independiente`: calidad del verificador y respaldo de cámaras elegibles.
- `elegibilidad_publicacion`: decisión determinista y auditable de la política vigente.

Tabla de decisión propuesta:

| Estado | Evidencia | Acción autónoma |
|---|---|---|
| `confirmado_automatico` | Primer indicio local y corroboración temporal; verificador sin alertas graves; tiempo fiable; consenso y política aprobados | Guardar, publicar tiempo, actualizar listado/matriz/Excel, conservar pruebas visuales |
| `propuesta_alta_confianza` | Buena evidencia en una o dos cámaras pero falta respaldo o reloj | Mostrar rango, 3 mejores cuadros y motivo; **no** colorear como tiempo confirmado |
| `revisar_conflicto` | Cámaras válidas se contradicen o existe indicio anterior debatible | Priorizar en cola y mostrar comparación sincronizada |
| `no_evaluable` | FPS dudoso, overlay contradictorio, ROI imposible, codec roto o video censurado | Diagnosticar y pedir una corrección concreta, sin valor ficticio |
| `sin_evento_detectado` | Análisis completo sin evidencia corroborada | Estado distinto de «sin apertura validada». **No convertir ausencia de detección en ausencia certificada** |
| `sin_apertura_confirmada_manual` | Decisión humana explícita | Preservar y excluir del cálculo sin reescribir por automatismo |
| `evento_al_inicio` | Evidencia desde primer cuadro, sin previo limpio | Guardar evento censurado por izquierda y tiempo inicial desconocido |

**Aprendizaje de política de aceptación selectiva:** un sistema inteligente no siempre responde; **sabe abstenerse**. Ajustar umbrales de publicación usando datos retenidos para limitar errores entre las detecciones aceptadas y medir el porcentaje de casos que resuelve solo. Si no existe evidencia suficiente, el comportamiento correcto es solicitar revisión. Las calificaciones `0.9` heurísticas de versiones anteriores no deben mostrarse como probabilidades calibradas.

## 7. Aprendizaje continuo con controles contra regresiones

**Aprender de la intervención humana real, no de sus propias predicciones sin auditar.**

### 7.1 Datos por muestra

Guardar en `dataset_eventos` (versionado, append-only o eventos inmutables): `video_sha256`, `case_key`, `project_id`, cámara y subtipo, ruta relativa, FPS real, frame candidato, frame humano, anotador, fecha, criterio semántico, ROI general, microzona, F−N...F+N *derivados*, frame previo limpio, calidad, motivo de rechazo y resultado confirmado. Distinguir `positivo`, `negativo` y `ambiguo`; un humano que marca «sin evento» debe generar ejemplos negativos, cuando proceda.

- Mantener **datos e imágenes originales intactos**. Las máscaras/recortes entrenables son archivos derivados con hash, permisos corporativos y control de acceso.
- Etiquetas contradictorias entre revisores se resuelven con historial y arbitraje, no por sobrescritura.
- No copiar correcciones de un proyecto a otro como verdad incuestionable; distinguir conocimiento transferible de identidad de proyecto y firmas por contenido.

### 7.2 Dos velocidades de aprendizaje

**Rápida (tras cada corrección humana guardada):** actualizar de forma atómica el banco de ejemplos y el perfil de esa cámara/escena; aplicar a siguientes videos compatibles, con rollback. El guardado no debe marcarse completo antes de persistir todo lo indispensable. Jamás alterar la ROI manual ya bloqueada.

**Lenta (modelo global):** entrenar o recalibrar solo después de disponer de suficientes ejemplos de variedad real; ejecutar entrenamiento en segundo plano **solo si existe infraestructura autorizada**, como tarea separada y reversible; comparar modelo retador contra modelo actual sobre conjunto reservado. Promover automáticamente una versión global solo si hay puerta de calidad aprobada y reversible; para producción inicial exigir aceptación humana del cambio de modelo.

### 7.3 Selección inteligente de muestras (active learning)

En lugar de pedir revisión de todo, priorizar:

1. hipótesis con gran desacuerdo visual/temporal;
2. ROI nueva o mala alineación;
3. escena de cámara/tipo de bolsa no vista;
4. alto riesgo de falso positivo temprano (brillo, abombamiento, compresión);
5. tiempo muy cercano al umbral de clasificación **solo para revisión del dato, no para cambiar la física**;
6. muestras representativas de casos autónomos (auditoría humana aleatoria de control).

Aprender también de los **errores evitados**: un frame descartado por el revisor es una observación negativa valiosa.

## 8. Matriz dinámica y trazabilidad: no confundir grises con fallos

- La pantalla muestra **solo casos reales**, en las 7 categorías 1ST/2ST, con `Sin clasificar` separado. Ningún objeto vacante ficticio en la vista dinámica y ningún cupo fijo de 50.
- Los casos sin dato confiable permanecen con estado explicable: `sin_consenso`, `reloj_incierto`, `sin_camaras_elegibles`, `espera_revision`, `sin_evento`, `error_analisis`, `evento_al_inicio`. Nunca llenarlos con `0.0` ni pintarlos como confiables.
- Compartir un **único resolvedor del caso** entre `dashboard/backend/app.py::_fila_publica`, `_matriz_apertura`, `reporte_bmg.py` y el listado. La clasificación por colores usa los rangos elegidos **para esa ejecución** (default verde ≤6 ms, amarillo >6 y ≤7 ms, rojo >7, si no fueron cambiados).
- Al pulsar una celda: abrir el caso, mostrar `fuente`, cámaras, fotogramas, ROI, tiempo, incertidumbre y razón de aprobación/pendencia.
- Mantener la plantilla institucional BMG como contrato. Producir la vista dinámica en hoja nueva/salida separada sin corromper fórmulas, títulos, estilos ni tablas; identidad de proyecto explícita, nunca heredada del Excel de plantilla.

## 9. Interfaz autónoma: «Centro de decisiones de apertura»

La pantalla principal debe ofrecer, sin trabajo adicional por defecto:

**En la corrida:** «N casos procesados; A confirmados automáticamente; M confirmados por experto; R requieren revisión; S sin evidencia; E errores técnicos». Progreso real por video, no estimado por cuotas.

**Para cada caso:** tiempo sugerido/confirmado, estado y razón; miniaturas **F−2, F−1, F, F+1, F+2** con ROI/microzona sincronizada; botón «Confirmar primer indicio», «Corregir al cuadro…», «No hubo apertura», «Reanalizar este video» y «Siguiente pendiente».

**Confianza útil:** sustituir etiquetas ambiguas «99%» por «evidencia alta/media/baja» hasta obtener calibración empírica; mostrar el intervalo temporal y el origen de reloj. Un cuadro marcado «confirmado automáticamente» debe permitir auditar qué descartó el verificador.

**Zoom:** preservar 100/200/400/800 % y pan; la transformación de pantalla es independiente de coordenadas nativas ROI; ni navegar, ni cambiar frame, ni recalcular debe mover una región manual bloqueada.

**Al cerrar:** reporte autónomo con tasa de automatización, revisiones solicitadas, falsos positivos auditados, desfase entre cámaras y discrepancias que impiden pintar/exportar. Guardar evidencia de cada decisión para reproducibilidad.

## 10. Rendimiento real: mucha inteligencia sin volver lento el procesamiento

- Medir CPU, RAM, GPU y tiempo por video **antes y después** en el equipo de uso; conservar el `utilidades/benchmark_detector.py` y extenderlo con fase/ventana por candidato.
- Analizar barato para hallar candidatos, luego a resolución nativa cerca de todos los inicios plausibles. No omitir el primer fotograma por subsampling. Controlar OOM con procesamiento en streaming y ventanas, no cargar AVI completo en RAM.
- Cachear por firma **de contenido del video** + versión de detector/ROI/perfil temporal/modelo/política; al modificar un elemento relevante invalidar únicamente lo afectado.
- `cv2.phaseCorrelate` y registro óptico pueden consumir tiempo; ejecutar cuando el movimiento lo amerite, con máscara de fondo y medición de coste.
- CPU como fallback corporativo, con GPU/CUDA si existe y demuestra ganancia. No añadir PyTorch/ONNX Runtime como dependencia de producción hasta justificar memoria, instalación offline y mejora en conjunto reservado.
- No bloquear UI ni corromper checkpoint al pausar, cancelar o reanudar; ningún entrenamiento modifica resultados ya aprobados silenciosamente.

## 11. Dataset y evaluación: cómo sabremos si la herramienta se volvió inteligente

### 11.1 Datos reales necesarios

Solicitar una muestra **anonimizada o local** con casos de: detalle/volante, lateral, cámara con ángulo malo, no apertura, reflejos, abombamiento previo, escenas oscuras, brillos fuertes, inicio antes del clip, pocos cuadros, 1000 y 5000 FPS, overlay ilegible y cámaras con disparos desfasados. El usuario/experto etiqueta primer cuadro *con evidencia visual*, último previo inequívocamente limpio, microzona y ambigüedad; al menos una parte debe ser revisada por dos expertos para estimar variación humana.

No transmitir archivos empresariales a la nube; la anotación y el benchmark se pueden ejecutar localmente.

### 11.2 Separación obligatoria

- `train`: carpetas/casos para aprendizaje; `validation`: calibración/selección de política; `test`: casos **nunca vistos**, no alterados después de observar resultados.
- Separar por **case_key / prueba / sesión de grabación / cámara asociada** y proyectos cuando sea posible. No colocar distintos fotogramas del mismo AVI entre train y test ni contar sus cuatro cámaras como cuatro experimentos independientes.
- Reportar desempeño por familia de cámara, zona, proveedor, resolución y condición de luz; una tasa global puede ocultar casos peligrosos.

### 11.3 Indicadores mínimos, medidos contra V15.9.10

| Indicador | Definición | Regla de mejora |
|---|---|---|
| Error en cuadros y ms | `predicción - referencia humana`, con signo y valor absoluto | Mediana, p90, p95 y peor caso por cámara/escena; bajar error sin adelantar erróneamente |
| Coincidencia ±1 frame | % de casos elegibles con onset dentro de un frame nativo | Mejora comprobable sobre baseline en test reservado |
| Falso positivo temprano | Detectar ruptura antes de que aparezca evidencia corroborada | **No empeorar** respecto al baseline; auditar individualmente |
| Falso evento | Sistema propone/confirma apertura cuando no ocurrió | Métrica crítica de seguridad de publicación |
| Falso negativo | Evento verdadero no identificado | Menor tasa sin sacrificar precisión |
| Precisión de autoaceptados | Proporción de tiempos autoaceptados correctos bajo tolerancia física acordada | Objetivo de seguridad a acordar con equipo, sustentado con intervalos de confianza |
| Cobertura autónoma | % de casos resueltos sin intervención humana | Debe crecer sin degradar precisión ni esconder casos |
| Trabajo manual | Minutos de experto y clics por 100 casos | Deben bajar mediblemente |
| Rendimiento | Segundos/video, CPU/GPU/RAM/VRAM, p95 latencia | Sin degradación no justificada |
| Consistencia de productos | Mismo `case_key`, tiempo, estado y motivo en detalle/listado/matriz/Excel | Exacta: cero divergencias |

**Metas candidatas, NO logros declarados:** explorar ≥95 % de resultados autónomos dentro de ±1 frame y ≥99 % de corrección entre resultados *autoaceptados*, con crecimiento gradual de cobertura (por ejemplo 30 % → 60 % → 80 %). Ajustar sólo después de conocer desempeño base y riesgo aceptable del negocio. Un piloto pequeño sin fallos no demuestra 99 %: como aproximación, con cero errores entre ~300 casos autoaceptados independientes, el límite superior unilateral aproximado de error al 95 % es ~1 % («regla de tres»). Los cuatro videos de un mismo ensayo no cuentan como cuatro casos independientes.

## 12. Implementación por entregas / versiones

### V15.10.1 — Fuente de verdad, diagnóstico y benchmark (P0)
- Matriz dinámica; cada caso real una única vez; reportes con motivos de gris.
- Diagnóstico de *por qué* se pierde el tiempo: detección, calidad del reloj, revisión, 3/4, persistencia, proyección o Excel.
- Esquema de evento y auditoría trazable; versión base del dataset anotado.
- Medir el detector actual sin modificar sus criterios; establecer línea base por escena.
- **Salida:** matriz y Excel consistentes + informe inicial del detector y puntos débiles concretos.

### V15.10.2 — Primer indicio y autoverificación en modo sombra (P0–P1)
- Detector de múltiples candidatos, compensación/máscaras, retrospectiva nativa y verificador adversarial.
- Nuevo detector corre **en modo sombra**: propone y compara, NO sustituye aún el tiempo usado para el Excel.
- Guardar top-3 candidatos, incertidumbre, pruebas negativas y evidencia espacial/temporal.
- **Salida:** mejora mensurable de candidatos frente a baseline en casos reales, sin falsos positivos añadidos.

### V15.10.3 — Sincronización, consenso y autoaceptación gradual (P0–P1)
- Resolver referencias temporales por cámara, elegibilidad y desfase comprobable.
- Política de publicación separada de heurísticas; revisión/abstención ante advertencias graves.
- Activar autoaceptación con **feature flag**, primero en muestra limitada y luego ampliar cobertura si auditoría humana da resultados.
- **Salida:** más casos automáticamente correctos, con evidencia individual reproducible; ninguna auto-confirmación sin base temporal fiable.

### V15.10.4 — Aprendizaje continuo y calibración (P1)
- Ejemplos positivos/negativos, aprendizaje inmediato por cámara tras corrección humana, rollback y entrenamiento global en modo candidato.
- Calibración de confianza por familia de cámara; evaluación train/validation/test sin fuga de casos.
- **Salida:** versión entrenable mejora frente al detector anterior y no aprende silenciosamente de sus errores.

### V15.10.5 — Centro de decisiones y revisión por excepción (P1)
- Vista F−2…F+2, zoom sincronizado, controles de corrección exacta, cola priorizada, «siguiente pendiente», explicaciones.
- Reconciliación automática de resultado→listado→matriz→Excel; exportaciones sin publicación engañosa.
- **Salida:** reducción de tiempo manual demostrada mediante usuarios reales.

### V15.10.6 — Piloto empresarial y liberación (P0)
- Validar el pipeline completo sobre **copias** de carpetas y Excel/AVI autorizados en Windows corporativo sin Internet, CPU y GPU si disponibles.
- Pruebas de pausa/reanudar, SQLite/JSON, historial ROI, permisos Windows, cero modificaciones a datos productivos y rollback.
- **Salida:** acta de piloto, métricas comparativas, riesgos residuales, versión reproducible y decisión documentada de promoción a producción.

## 13. Pruebas automatizadas obligatorias

**Detector:** F−1 limpio + F con fisura de 1 px + expansión F+1; fisura oscura; abombamiento sin ruptura; reflejo temporal; ruido; blur; oclusión; evento antes del clip; evento en último frame; múltiples candidatos; duplicación/pérdida de frames; overlay cambiante; 1000/5000 FPS; no evento. Ningún test debe aceptar un falso momento anterior solo por más blanco.

**Validador:** `F−2,F−1` en conflicto con supuesto inicio; registro de escena incorrecto; candidato en texto overlay; clasificación de señal correlacionada; top-3 y decisión abstenerse. Versión y motivo de cada descarte registrados.

**Cámaras:** 3/4 realmente sincronizadas; 2/4 sin consenso; 3/4 aparente con offset desconocido; 4 videos pero dos duplicados; lateral ocluida; 3 frames de discrepancia con tolerancias; relojes distintos; cámara con falsa confianza; no promover antiguos 1/1 o 2/2 silenciosamente. Manual verificada conserva su jerarquía sin ocultar contradicción.

**Aprendizaje:** corrección humana guardada, ejemplo negativo guardado, reinicio programa, caché invalidada, ROI manual inmóvil, rollback, corrupción de registro y fallo de escritura; separación por proyecto; no usar datos autoaceptados como etiquetas de verdad sin auditoría.

**UI/Excel:** `0,1,10,50,80,125` casos; 1ST y 2ST; grupos vacíos sin «vacante»; gris explicable; color correcto según rangos elegidos; título de proyecto correcto en todas las hojas; fórmulas/Tablas/celdas combinadas intactas; identidad igual en listado y Excel; clic lleva al caso y a evidencia. Reanudar una corrida no adopta criterios/proyecto de otra.

**Pruebas de aceptación del piloto:** exigir ejecución reproducible de toda la suite; análisis ciego de test reservado; doble revisión humana en casos ambiguos; desempeño por grupos; revisión aleatoria de autoaceptados; ninguna discrepancia no explicada de `opening_time_ms`; compatibilidad con equipos sin red.

## 14. Requisitos de integración y skills existentes

Conservar `.agents/skills/v-matrix-airbag-onset`, `v-matrix-roi-supervision`, `v-matrix-video-zoom-ux`, `v-matrix-matrix-excel`, `v-matrix-safe-change`, `v-matrix-evaluation-lab` y `AGENTS.md` raíz. Reforzar **Airbag Onset** y **Evaluation Lab** con protocolo de autoverificación, validación temporal y test reservado; **Safe Change** debe exigir regresiones y bloqueo de resultados inconsistentes. No basta incluir archivos `SKILL.md`: registrar qué pruebas y controles se ejecutaron realmente.

Crear contratos nuevos sin romper los existentes. Propuesta de módulos aditivos: `utilidades/evidencia_apertura.py` (features/candidatos), `utilidades/verificador_apertura.py` (contraevidencias), `utilidades/sincronizacion_video.py`, `utilidades/politica_apertura.py`, `utilidades/evaluacion_apertura.py`. Integrar gradualmente con `video_airbag.py`, `aprendizaje_video_airbag.py`, `dashboard/backend/app.py`, frontend, matriz, `reporte_bmg.py` y persistencia. No duplicar validadores o crear dos «fuentes de verdad».

Ninguna dependencia nueva sin justificar beneficio, licencia, VRAM, tamaño offline y fallback. Libs opcionales para prototipos en desarrollo: OpenCV ECC/optical flow (ya disponible), scikit-image registration/SSIM, `ruptures` para change-point, y calibración con herramientas estadísticas. Empezar con NumPy+OpenCV existentes.

## 15. Referencias técnicas, exclusivamente como inspiración/validación

- OpenCV, *Motion Estimation and Registration*: https://docs.opencv.org/doc/doxygen/html/dc/d6b/group__video__track.html (ECC y registro de imágenes).
- scikit-image, *Registration using optical flow*: https://scikit-image.org/docs/stable/auto_examples/registration/plot_opticalflow.html
- scikit-image, *Structural Similarity*: https://scikit-image.org/docs/stable/api/skimage.metrics.html
- ruptures, *Change-point detection / PELT*: https://github.com/deepcharles/ruptures/blob/master/docs/user-guide/detection/pelt.md
- Fisch et al., *Calibrated Selective Classification*: https://arxiv.org/abs/2208.12084 (abstención y calibración de decisiones).

Estas herramientas **no garantizan** por sí mismas mayor exactitud ni deben instalarse todas en producción. Comparar empíricamente y escoger sólo mejoras comprobadas.

---

## 16. Prompt para automatización de apertura (complementario; el prompt INTEGRAL vigente está en E11)

**Instrucción:**

> Quiero convertir V-Matrix V15.9.10 en un sistema de análisis de apertura **verdaderamente autónomo, verificable y capaz de aprender**. Usa íntegramente este documento `PLAN_V_MATRIX_V15_10_INTELIGENCIA_AUTONOMA_APERTURA.md` como contrato de implementación, manteniendo los criterios de seguridad y todas las funciones actuales. No quiero una solución limitada a subir umbrales ni a colorear celdas: la prioridad es reconocer el PRIMER cuadro físico visible de ruptura y demostrar cuándo la decisión automática es correcta. Trabaja en rama nueva y no modifiques datos reales. 
>
> **Empieza por V15.10.1:** matriz dinámica, estado único, trazabilidad de cada caso y benchmark del detector actual con videos etiquetados; identifica exactamente por qué los casos de la última ejecución quedaron grises y cuáles tienen problemas de tiempo físico frente a problemas de proyección al Excel. No asumas que confirmar un frame equivale a consenso de caso. 
>
> **Continúa con V15.10.2** creando un detector de múltiples hipótesis y un verificador adversarial **en modo sombra**, que examine previos/posteriores a resolución nativa, separe abombamiento/reflejo/ruido de ruptura verdadera y conserve el instante más temprano corroborado; no sobrescribas tiempos existentes. Usa la información de ROI bloqueadas, sugeridas, microzona y ejemplos históricos sin mover manuales. 
>
> **Después V15.10.3:** valida FPS de adquisición, overlay y origen de tiempo de cada cámara, introduce sincronización verificable antes del consenso y una política de autoaceptación que se abstenga ante conflicto o evidencia insuficiente. Los 5000 FPS implican 0.2 ms/cuadro; no prometas 0.1 ms físicos por simple redondeo. El consentimiento manual se preserva con historial, y las contradicciones se hacen visibles. 
>
> **Después V15.10.4–6:** aprendizaje inmediato y seguro de correcciones humanas y negativos, validación estadística de confianza, revisión solo por excepción, UI F−2…F+2, piloto offline y validación con datos autorizados. Integra el uso efectivo de las seis skills y registra pruebas. 
>
> Cada fase requiere PR o paquete reproducible, documentación de archivos modificados, datos de pruebas de regresión, evaluación **ciega en casos no vistos**, benchmark de falsos positivos/negativos y tiempo, evidencia de que ninguna corrección, ROI, plantilla o proyecto se perdió, y procedimiento de rollback. No declares mejor desempeño, autoaceptación segura ni cierre de fase con solo ejemplos sintéticos o el paso de tests escritos para la corrección. Asegúrate de que **los resultados del detalle, listado, matriz y Excel coincidan** y que el operador conozca la razón exacta de cualquier resultado gris. Las cámaras no sincronizadas, ocluidas o duplicadas no pueden crear consenso artificial. 
>
> Entrega primero un **diagnóstico de la ejecución actual** y V15.10.1, junto con el diseño de datos y evaluación para la fase de IA. No conviertas todo en una reescritura monolítica ni instales modelos pesados sin demostrar beneficio medido.

## 17. Condición de cierre del proyecto de mejora

La V15.10 **se considerará un éxito** cuando entregue tiempos reales dentro de una tolerancia sustentada por los FPS y el reloj, detecte y explique los casos dudosos, automatice una fracción creciente de la carga sin aumentar errores graves, conserve las decisiones humanas y deje una auditoría reproducible por caso. **Un resultado gris explicado es mejor que un resultado verde falso, pero el sistema debe esforzarse en resolver correctamente cada gris que tenga evidencia suficiente.**


---

# EXTENSIÓN MAESTRA — OCR Intelligence, extracción contextual, autollenado y auditoría del aprendizaje

> **Esta extensión es parte obligatoria del plan integral V15.10**, no una sugerencia opcional. Combina la automatización del primer instante de apertura (secciones anteriores) con el reconocimiento y la captura de información de fotografías, etiquetas, QR, estructura de carpetas y capturas de video. Objetivo único: reducir la captura y corrección humana sin producir datos incorrectos o sin respaldo.

## E1. Diagnóstico técnico de la arquitectura existente (revisión de código, no análisis de la carpeta de aprendizaje)

| Código existente | Ya tiene | Evolución propuesta, sin duplicarlo |
|---|---|---|
| `ocr_engine.py`: `MotorEasyOCR`, `_seleccionar_pasada`, `extraer_texto_empresarial`, `detectar_regiones_texto`, `_clasificar_informacion_region` | EasyOCR, variantes y rotaciones, recortes, distinción código/texto/ruido, consenso de orientaciones, geometría y extracción regional | Generador/rankeador de **hipótesis de lectura por campo** que considere la imagen, forma del código, relaciones espaciales y evidencia cruzada, conservando las lecturas originales |
| `aprendizaje.py::GestorAprendizaje` | SQLite `aprendizaje.sqlite3`, correcciones, observaciones, orientación, ROI, polígonos, uniones, revisiones, muestras visuales, modelos con versiones y rollback | **Auditoría de integridad + procedencia + calidad de etiquetas**, separación conocimiento inmediato y entrenamiento visual; preservar historial y corregir muestras inválidas sin borrar originales |
| `entrenamiento_easyocr.py::entrenar_lote` | Ajuste supervisado CTC del reconocedor EasyOCR (no detector CRAFT), partición por IDs, métricas CER/WER y comprobaciones antes de etiquetar candidato | Validación de datos de recorte y longitudes; partición de prueba **sellada** no reutilizada para seleccionar modelos; estratificación, control de regresiones por campos críticos y despliegue reversibles |
| `flujo_empresarial.py::extraer_candidatos_texto`, `interpretar_payload_qr`, `consolidar_caso` | Extracción empresarial contextual por texto, QR, ruta, metadatos y consolidación | **Fusión de evidencias por campo**, conflictos visibles, consistencia con guía EDAG/VW/prototipos y decisión autónoma calibrada |
| `validacion.py::validar_lote_empresarial` | Procesamiento y persistencia incremental, aprendizaje de observaciones | Control «dato observado != dato verificado»; conciliación posterior con actualizaciones humanas por campo; tareas idempotentes reanudables |
| `utilidades/consolidacion.py`, `utilidades/correcciones_ocr.py` | Fusionan historial y correcciones humanas | Definir política de última corrección **por campo y fecha real**, desempates auditable, no reemplazar una corrección nueva por un valor inferido antiguo |
| `plantilla_empresarial.py`, `reporte_bmg.py`, `generar_excel.py`, `utilidades/identidad_excel.py` | Exportación y protecciones de identidad y cabeceras de Excel | **Contrato tipado por celda/campo**; validación pre-exportación; Excel sin herencia de ejemplos; consistencia con la misma fuente canónica que usa el dashboard |
| `video_airbag.py`, `aprendizaje_video_airbag.py`, matriz y UI | Detector temporal, ROI, revisión manual, criterios y semáforo | Conectar evidencia visual del video al caso, sin confundir información textual de un overlay con una medición física no confirmada |

**Hallazgo especialmente relevante:** `aprendizaje.py::registrar_observacion_incremental` guarda una lectura OCR como **observación** en cada imagen, incluso si no fue corregida. Una observación no se convierte por ello en una etiqueta verdadera. `entrenamiento_easyocr.py::entrenar_lote` entrena con `muestras_visuales` entrenables, que son un conjunto diferente. Revisar ambas cantidades y la correspondencia con recortes existentes.

**Riesgo metodológico a subsanar:** el procedimiento actual calcula métricas sobre el conjunto denominado `test` antes de decidir si el modelo candidato mejora. No debe reutilizarse repetidamente ese test para seleccionar versiones, porque deja de ser una medición independiente. Establecer `train/dev/test_sellado` por grupo de caso/escena (y si procede por proyecto/tiempo), seleccionar solo con `dev` y usar `test_sellado` una vez en evaluación de liberación.

**No afirmar que se analizó ya la carpeta de aprendizaje**: falta que el usuario la aporte. Este apartado caracteriza el código disponible y define la auditoría pendiente.

## E2. Auditoría forense de la carpeta `.aprendizaje` — PRIMER PASO ANTES DE ENTRENAR

### E2.1 Entrega solicitada

Recibir copia ZIP **de la carpeta completa `.aprendizaje`** que use la instalación actual (mantener subdirectorios y nombres; no renombrar tablas ni borrar `.json` ni `*.pth`). Si existen datos de aprendizaje de video en rutas adicionales configuradas fuera de `.aprendizaje`, añadirlos en una carpeta separada `aprendizaje_video_externo/` documentada. Aportar opcionalmente `config.yaml` **revisado para retirar secretos o rutas confidenciales**, informe de ejecución y un conjunto pequeño de fotografías/videos autorizados representativos de errores; sin esas imágenes solo puede auditarse la estructura y trazabilidad, no la calidad visual de las etiquetas.

**Integridad al copiar:** cerrar V-Matrix y sus procesos antes del respaldo cuando sea posible. La base puede estar en modo SQLite WAL: copiar **juntos** `aprendizaje.sqlite3`, `aprendizaje.sqlite3-wal` y `aprendizaje.sqlite3-shm` con la aplicación cerrada, o crear un respaldo consistente mediante la API `sqlite3.Connection.backup`. No forzar el ZIP de una DB abierta ni ejecutar `VACUUM`, `REINDEX`, entrenamientos o cambios en la copia original. Los backups se auditan en directorio temporal, nunca con escrituras al original. Antes de subir, confirmar autorización para compartir información corporativa, recortes y rutas personales; si es necesario, preparar copia saneada sin romper sus relaciones.

### E2.2 Inventario requerido en modo solo lectura

- Huellas SHA-256, tamaños, versiones de esquema, estado `PRAGMA integrity_check`, consistencia y número de conexiones residuales.
- Inventario de `observaciones`, `correcciones`, `correcciones_texto`, `anotaciones_regiones`, `muestras_visuales`, `modelos`, `modelos_visuales`, `revisiones`, `rotaciones_imagen`, `orientaciones_region`, `regiones_no_texto`, `estrategias_ocr`, `alertas_atendidas`, `ejecuciones` y tablas adicionales descubiertas dinámicamente. Listar el esquema **real**, no asumir que todas las tablas se llaman así.
- Cuenta de lecturas observadas vs muestras humanas verificadas, positivas/negativas, entrenables/no entrenables, por proyecto, 1ST/2ST, etapa, cámara, tipo de etiqueta, campo, fuente y fecha. Registrar desconocidos sin inventar clasificaciones.
- Duplicados por hash y bbox, evidencia repetida de una misma imagen/caso, recortes ausentes, rutas absolutas rotas tras mover equipos, modelos con pesos inexistentes, valores nulos, conflicto entre correcciones, casillas manualmente modificadas y dataset visual sin imagen vinculable.
- Registros `texto no necesario`, uniones/separaciones, polígonos, rotaciones y estrategias: confirmar si el sistema **los consulta y respeta realmente en inferencia**, no solo si existen en SQLite.
- Confirmación de qué modelo visual está activo: ID, versión, rutas, fecha, historial, métricas registradas y diferencia entre aprendizaje simbólico y ajuste de pesos EasyOCR. No asumir activación porque hay archivos `.pth`.
- Aprendizaje de video: ejemplos por cámara/ROI, evidencia F−3...F+3, negativos, anulaciones humanas, ROI manual inmutable, firmas de videos, desfases temporales.
- Diagnóstico de crecimiento: número de muestras y bytes, equilibrio entre etiquetas, fuga train/test y cambios de distribución con nuevas carpetas.

### E2.3 Informe que se entregará tras recibir la carpeta

1. **Salud de datos**: válido, corrupto, incompleto, desconectado o no evaluable.
2. **Conocimiento aprovechable hoy**: reglas, lecturas, orientaciones y ROIs realmente consumidas.
3. **Qué está entrenado de verdad**: estado de modelos y razones para entrenar o posponer.
4. **Errores y sesgos prioritarios**: campos, tipos, rotaciones, cámaras y subgrupos.
5. **Plan de recuperación no destructiva**: huérfanos, rutas, contradicciones, backup.
6. **Plan experimental de reentrenamiento** con variante candidata, prueba sellada, hardware y fallback.
7. **Mapa de impacto**: cómo cada corrección se transforma en mejor OCR, extracción y campo Excel.

No modificar ni entrenar sobre la única copia. Toda propuesta de depuración o promoción debe ser **reversible** y contar con el consentimiento del usuario.

## E3. Nueva arquitectura «V-Matrix Evidence Intelligence»: lectura → evidencia → dato

```text
Fotografías + QR + video overlay + nombre/estructura de carpeta
       │
       ├── [A] Inventario y clasificación de imagen: etiqueta EDAG/VW,
       │       tablero, módulo, inflador, foto sin texto, video/cámara
       ├── [B] ROI automática por tipo + ROI corregida/bloqueada por humano
       ├── [C] OCR multihipótesis: orientación, recorte flexible,
       │       corrección perspectiva, contraste, EasyOCR actual
       └── [D] Contexto: guía de códigos, laboratorio, prueba, temperatura,
               posición, etapa, fecha, prototipo, ingeniería y versión
                               │
               [E] Evidencias por CAMPO, con origen y coordenadas
                               │
               [F] Conciliador de fuentes (foto/QR/metadata/video/corrección)
                   valida formatos, dependencia entre campos, contradicciones
                               │
               [G] Política de decisión con abstención:
               VERIFICADO_HUMANO | AUTO_VERIFICABLE | PROPUESTA
               CONFLICTO | NO_OBSERVADO | NO_APLICA
                               │
                    ÚNICA instantánea por caso, versionada
                               │
            ┌──────────────────┼───────────────────┐
          dashboard         Excel/Matrix       cola de revisión
            │                                      │
            └────────────── correcciones humanas ─┤
                              │                   │
              perfil inmediato y dataset validado │
                              └──> entrenamiento candidato, prueba y rollback
```

**Separación física de conceptos:** `observacion` (OCR bruto), `hipotesis` (lectura alternativa), `evidencia` (fuente concreta), `dato` (valor candidato para un campo), `resolucion` (aceptar/abstenerse/corregir) y `modelo` (versión entrenada). Ninguna predicción se autocertifica solo porque concuerda consigo misma.

### E3.1 Hipótesis por campo, no solo por texto plano

- Conservar top-k lecturas por región, posición, variante, orientación, caja/polígono, origen, transformación y confianza sin sobrescribir la imagen original.
- Crear perfiles de tipo de imagen/campo: `test_number`, `test_date`, `test_place`, `test_reason`, `part_number`, `serial`, `engineering_level`, `module_version`, `temperature_condition`, `inflator_type`, información del prototipo, etc., **según claves realmente definidas por el contrato de plantilla**. No inventar un campo de Excel si su contrato no lo permite.
- Guía de posiciones: usar las reglas condicionales **EDAG frente a VW**. El fabricante VW y el laboratorio EDAG no son intercambiables. Los seriales, fechas, códigos de ingeniería, prototipos y texto de laser/apertura solo se infieren cuando una fuente lo respalda.
- Recuperar caracteres perdidos (`0/O`, `1/I/l`, `5/S`, `8/B`) como **candidatos**, no como autocorrecciones incondicionales. Seleccionar por formato específico del campo, evidencia de imagen, consenso entre fotos/QR y modelos; si persiste ambigüedad, abstenerse.
- Usar OCR de un recorte ampliado, ROI poligonal, deskew y corrección de perspectiva solo en casos difíciles. No forzar nuevas variantes en todas las ~6,300 imágenes y perjudicar velocidad.
- Clasificación «no hay texto necesario» con evidencia: mantener revisión/etiqueta manual previa; jamás afirmar «sin texto» por fallo de un OCR borroso.
- Soportar extracción de datos textuales relevantes en capturas de video u overlay (número de prueba, cámara y FPS declarados), pero **sin extrapolar** un tiempo de apertura físico de un texto que solo aparece en pantalla.

### E3.2 Ranking y conciliación con reglas verificables

Para cada campo, almacenar un registro de evidencia con (mínimo):

```json
{
  "project_id": "proyecto-confirmado",
  "case_key": "identidad-estable-del-caso",
  "campo": "test_number",
  "candidato": "232566",
  "fuente": "imagen_ocr|qr|ruta|video_overlay|manual",
  "archivo_sha256": "hash-de-la-evidencia",
  "imagen_bbox_o_poligono": "referencia-opcional",
  "version_motor": "...",
  "version_reglas": "...",
  "confianza_calibrada": null,
  "estado": "propuesta",
  "razones": ["formato_compatible"],
  "corregido_en": null
}
```

*El JSON es un contrato conceptual, no datos existentes ni código ejecutado.*

- Validar tipo/formato/rango **por campo** antes de combinar fuentes. No convertir el número de prueba en número de serie ni al fabricante en laboratorio.
- Establecer compatibilidad entre foto y QR de la **misma** etiqueta; QR puede ser fuerte pero no siempre describe la misma entidad. Ante contradicción: mostrar ambas evidencias.
- Si distintas imágenes de la carpeta repiten el mismo identificador correcto, aumentar soporte, pero no tratar variantes del mismo recorte como «múltiples observaciones independientes».
- Usar prioridad: corrección humana por campo vigente > fuentes independientes concordantes verificables > inferencia automática plausible > plantillas históricas. No resolver automáticamente una corrección humana más reciente con resultados automáticos anteriores.
- No llenar silenciosamente campos que están vacíos por ambigüedad; distinguir «no capturado», «no aplica», «rechazado» y «conflicto».
- Trazabilidad para una celda: clic → caso → campo → fuente visual exacta/QR/regla → valor previo, correcciones y versión del motor.

## E4. Cómo mejorar el reconocimiento sin entrenar todo desde cero

### E4.1 Orden de mejora de menor riesgo

1. **Primero diagnosticar** los 20 principales errores OCR por campo, escena y razón (texto no detectado, recorte incompleto, rotación, perspectiva, reflejo, caracteres, contexto/semántica, exportación). Medir qué porcentaje del error explica cada causa.
2. **Mejorar ubicación de texto** con ROI aprendida, clasificación por tipo de imagen y polígonos. Un reconocedor entrenado no corrige una región mal recortada.
3. **Mejorar adquisición/preprocesamiento adaptativo** (deskew, contraste, superresolución solo experimental), evitando desenfoque artificial y detalles inventados.
4. **Reconciliar semántica**: si EasyOCR reconoce bien `232566` pero lo coloca en el campo equivocado, mejorar asignación de campos, no volver a entrenar el OCR.
5. **Afinar reconocedor EasyOCR** cuando los errores restantes sean realmente de caracteres y exista suficiente verdad humana diversa con recortes limpios. Mantener un modelo actual, uno candidato y rollback.
6. **Segundo reconocedor local opcional** solo para casos ambiguos seleccionados; ejecutar como «segunda opinión», comparar licencias, pesos offline, VRAM 6/12 GB, latencia y compatibilidad con el entorno empresarial. No meter un modelo grande por moda.

### E4.2 Etiquetas de entrenamiento confiables

- `aceptar lectura` debe indicar explícitamente **qué texto y campo** quedaron confirmados; verificar que los recortes corresponden a esa región; no convertir automáticamente un resultado de «imagen verificada» sin evidencia textual en una etiqueta de reconocimiento.
- `aplicar corrección`, `unir bloques`, `separar`, `texto añadido`, `rotar`, `ROI ajustado`, `texto no necesario` y `no ocurrió apertura` generan eventos diferenciados: algunos entrenan reconocimiento, otros enseñan detección, otros son negativos o preferencias espaciales.
- Una corrección debe poder entrenar el campo correcto **sin confundirse con un texto auxiliar de otras regiones**; conservar trazabilidad de anotador, versión previa, fecha, fuente y posición.
- Excluir muestra sin recorte, etiqueta ilegible, conflicto humano no resuelto, imagen de otra región o ejemplo puramente automático sin confirmación; marcar `no_entrenable` con causa, sin borrarlo.
- Mantener ejemplos difíciles y normales para no «sobreajustar a errores»; un conjunto que solo contiene los casos corregidos no representa necesariamente los casos fáciles.

### E4.3 Dos velocidades de aprendizaje en OCR

**Al guardar una corrección:** registrar evento y actualizar reglas locales/índice de ejemplos y preferencias ROI/rotación **de forma transaccional**, con versionado, auditoría e idempotencia. Esto puede mejorar la siguiente imagen compatible sin entrenar pesos. Nunca prometer que cada clic actualiza los pesos de EasyOCR.

**Entrenamiento visual programado y reversible:** lanzar un experimento cuando haya cantidad y diversidad suficientes, **no después de cada clic**. Optimizar hiperparámetros en `train/dev`; conservar un `test_sellado` independiente; comparar con el mismo conjunto de casos, subgrupos, hardware y versión de preprocesamiento. Guardar pesos y trazas como *candidato*; no activar si degrada campos críticos, aumenta falsos autollenados o falla la integridad.

**Criterio de promoción:** mejora demostrable en al menos un indicador objetivo y no regresión relevante en exactitud/cobertura de datos críticos, por 1ST/2ST, EDAG/VW, grado de rotación, condiciones de cámara, diferentes proyectos y formatos de etiqueta. Modelo candidato no se promueve por ver buenos ejemplos elegidos a mano.

### E4.4 Rendimiento y GPU

- Perfil de 6 GB/12 GB VRAM, batch adaptativo, una sola instancia EasyOCR, colas de frames/fotos con carga progresiva, separación CPU decodificación/GPU reconocimiento.
- Cachear **resultados por hash de imagen + configuración + versión de modelo**, invalidando cuando cambian ROI, rotación, corrección o campo relevante; no reutilizar resultados de proyectos anteriores incorrectamente.
- Preprocesamiento caro, segunda opinión y entrenamiento nunca deben bloquear el procesamiento normal de carpetas; preservar modo offline. Medir imágenes/minuto, uso GPU, tiempo de guardado y recuperación tras pausa/cancelación.

## E5. Autollenado de Excel y matriz: confiable, dinámico y explicable

### E5.1 Motor único de «datos finales»

- Construir un único `resultado_caso_canonico` del que se alimenten la UI, el listado, la matriz, la exportación empresarial y BMG. Los exportadores no deben re-interpretar lecturas brutas con reglas propias divergentes.
- Por campo exponer `valor`, `estado`, `procedencia`, `corregido_en`, `regla_version`, `confianza_calibrada`, `motivo_bloqueo`, `fuente_sha256`. Cuando una corrección humana se guarda, actualizar solo los campos afectados y reconstruir las vistas afectadas, sin re-OCR innecesario.
- La matriz de apertura debe usar **solo casos existentes** y no rellenar categorías con vacantes teóricas. Casos reales con tiempo inválido muestran motivo de gris; un caso con verificación humana válida aparece en listado, matriz y Excel solo después de validación coherente de estado.
- Prohibir que ejemplos/encabezados precargados de una plantilla se conviertan en proyecto, tiempo, motivo o lectura. El proyecto lo define la selección humana anterior a «Procesar carpeta».
- Proteger fórmulas, celdas combinadas, tablas formales y cabeceras (correcciones N7–N17 conservadas); guardado atómico de nueva salida. BMG, Excel genérico y dashboard deben compartir identidad y criterios.

### E5.2 Reglas de decisión por campo (no mezclar confianza OCR con exactitud)

- `VERIFICADO_HUMANO`: aplicar valor manual confirmado y mantener historial; si algo contradictorio es crítico, exhibir el conflicto sin borrar la corrección.
- `AUTO_VERIFICABLE`: solo con validación de formato, evidencia suficiente, control de conflictos y política calibrada específica del campo. Un OCR con «0.99» no garantiza 99 % de corrección: calibrar con verdad humana reservada.
- `PROPUESTA`: mostrar candidato y origen sin rellenar como confirmado; permitir aceptar/corregir desde la misma interfaz.
- `CONFLICTO`: conservar alternativas y pedir la mínima intervención necesaria.
- `NO_OBSERVADO`: vacío honesto; no copiar de otra carpeta.
- `NO_APLICA`: estado justificado, distinto de «no se pudo leer».

### E5.3 Calidad automática antes de generar archivo

1. Todos los casos identificados están clasificados o en sección explícita `Sin clasificar`.
2. Identidad proyecto/etapa/caso consistente en todas las hojas y dashboard.
3. Sin sobrescritura de contenido no destinado al contrato.
4. Cada campo autollenado puede rastrearse a una evidencia real con hash, no a un ejemplo de plantilla.
5. `opening_time_ms` se publica solo con evidencia temporal y política de consenso válida; `maximum_deployment_ms` es independiente.
6. Conteo de casos existentes = conteo proyectado en vistas y salidas (salvo exclusiones expresas registradas).
7. Con conflicto crítico, emitir borrador bloqueado o estado de exportación limitado **explícito**, no confundirlo con archivo oficial.
8. Reexportar tras corrección humana debe cambiar exactamente los campos afectados y conservar todos los demás.

## E6. Panel de aprendizaje y automatización real

Proponer una página **«Centro de inteligencia y aprendizaje»** con indicadores interpretables, no un número artificial de «IA entrenada»:

- **Extracción:** porcentaje de campos totales con evidencia, autollenados verificables, humanos, pendientes y conflictos; precisión auditada por campo; caracteres incorrectos CER/WER.
- **Apertura:** casos auto-confirmados válidos, pendiente por cámara/tiempo/ROI, error por frame en videos anotados y tiempo humano ahorrado.
- **Datos de aprendizaje:** observaciones vs etiquetas verificadas, recortes entrenables, muestras huérfanas, modelos activos/candidatos, tipos de fallos frecuentes y divergencias entre proyectos/etapas.
- **Cambios:** «mejoró», «sin cambio demostrable» o «degradó» comparando la misma cohorte reservada; ofrecer rollback real.
- **Revisión por excepción:** cola de campos/casos de mayor incertidumbre, agrupación de acciones por carpeta, previsualización de la evidencia y botones «Aceptar lectura», «Aplicar corrección», «No aplica», «Texto no necesario», «Apertura aquí», «Sin evento» según contexto.

**Privacidad y seguridad:** modo local, sin transferir imágenes ni aprendizaje a APIs externas; no exponer rutas/datos sensibles en reportes exportables o logs compartidos.

## E7. Evaluación: demostrar mejoras reales en la extracción y tiempo total

**Partición:** agrupar por caso (y comparar conjuntos por proyecto/fecha/plantilla cuando sea posible), conservar fuera de entrenamiento y tuning todos los ejemplos del `test_sellado`, incluida la misma fotografía recortada o girada. Evitar que una corrección de la misma imagen aparezca tanto en entrenamiento como en evaluación.

| Dimensión | Indicadores y control de calidad |
|---|---|
| Localización | recall de textos/códigos por región y campo, cobertura de ROI, falsos «sin texto» |
| Reconocimiento OCR | CER, WER, exactitud exacta por código/serial/parte y por rotación/subgrupo |
| Extracción semántica | precisión y cobertura por cada campo Excel, confusiones EDAG/VW y fechas/códigos |
| Autollenado seguro | tasa de campos autollenados, tasa de *errores silenciosos*, conflictos no visibles, tasa de abstención |
| Persistencia | no pérdida de revisiones/ROI/versiones, cero fusiones entre proyectos, datos idénticos tras pausar/reanudar |
| Video | error absoluto de onset en frames, tasa de falsos tempranos, false negatives, autoaceptación condicionada a errores calibrados |
| Productividad | imágenes/hora, tiempo total del lote, trabajo humano en minutos por carpeta y costo GPU/CPU |

**Condiciones para aprobar:** comparativa cuantificada contra V15.9.10 en la MISMA muestra reservada; sin regresiones críticas, sin cambios incorrectos de proyecto, plantilla o `test_reason`, sin celdas inventadas y con mejoras medibles en precisión o tiempo de revisión. Objetivos numéricos se fijan al obtener la línea base real; no inventar un 99.9 % sin datos ni confundir confianza del modelo con frecuencia empírica de acierto.

**Piloto sugerido:** primera evaluación rápida estratificada de varios tipos de casos/escenas y cámaras, seguida de una cohorte aparte de carpetas reales nunca utilizadas para afinar; comparar trabajo manual de registro y corrección antes/después. Pedir autorización para usar datos reales corporativos.

## E8. Desarrollo por fases coordinadas: no entrenar antes de cerrar trazabilidad

| Fase | Entrega obligatoria | Gate de aceptación |
|---|---|---|
| **V15.10.0 — Auditoría** | Diagnóstico `.aprendizaje`, backups, hashes, huérfanos, esquema, modelos, muestras y evaluación reproducible actual | No modificar datos reales. Entregar informe sobre qué aprender y qué no. |
| **V15.10.1 — Información y matriz** | Matriz dinámica, estado de caso/campo unificado y trazabilidad de lectura→resultado→Excel; autodiagnóstico de grises | Todos los casos reales proyectados; ninguna vacante ficticia; ninguna corrección perdida. |
| **V15.10.2 — OCR contextual** | Propuestas por campo, perfiles EDAG/VW, top-k lecturas/recortes y validación contextual; guardado conservador | Subir precisión/cobertura contra referencia sin errores silenciosos en campos críticos. |
| **V15.10.3 — Apertura autónoma** | Detectar varias hipótesis, verificar onset/ROI/tiempo, consenso con incertidumbre, shadow mode | Menor error y menos falsos tempranos en casos anotados; sin tiempo inventado. |
| **V15.10.4 — Aprendizaje** | Dataset depurado/etiquetado y dos velocidades; retraining candidato de EasyOCR y de perfiles de video cuando proceda | Test sellado independiente, no regresión y rollback; no promoción por observar las mismas pruebas. |
| **V15.10.5 — Autollenado controlado** | Excel/Matrix desde fuente canónica, campos auto-verificables, revisión mínima por excepción | Paridad 1ST/2ST, fuentes trazables, archivos oficiales sin corrupción ni datos falsos. |
| **V15.10.6 — Piloto integral** | Comparativa real con V15.9.10, QA y optimización Windows offline en GPU 6/12 GB | Mejora demostrada de esfuerzo humano, precisión y recuperación; aprobación humana antes de producción. |

**Orden de trabajo recomendado:** auditar datos y reparar el flujo de evidencia/Excel **antes** de invertir tiempo de GPU entrenando el reconocedor. La extracción semántica y el detector de apertura son líneas paralelas con un estado canónico compartido, no proyectos aislados.

## E9. Pruebas de regresión obligatorias añadidas al plan original

1. 1ST/2ST y más/menos de 50 casos → matriz sin posiciones inventadas ni datos omitidos.
2. OCR correcto, pero campo equivocado → se corrige extracción contextual sin declarar «error visual» ni entrenar innecesariamente.
3. `0/O`, `1/I`, fecha en formato raro, pieza/série en fuentes distintas → candidatos, evidencia y abstención si conflicto.
4. Laboratorio EDAG y fabricante VW en la misma imagen → no intercambiar entidades.
5. Lectura en QR contradice foto con distinta identidad de etiqueta → no sobrescribir silencio.
6. Una corrección humana más reciente derrota lectura automática y corrección humana anterior **solo para el mismo campo y caso**, preservando historia.
7. «Texto no necesario», bloque unido, rotación y ROI corregida → persisten, reaplican y producen muestras con rol correcto.
8. Imágenes sin texto, borrosas o sin archivo original → no se convierten en etiquetas entrenables; no se marcan como verdad humana.
9. Imagen y recorte duplicados entre splits → falla test de fuga de datos y entrenamiento se bloquea.
10. Dataset visual con archivos inexistentes → estado de auditoría y exclusión segura; no fallo silencioso ni borrado.
11. Guardado de aprendizaje SQLite bloqueado/corrupción → nunca reporta éxito ni destruye base anterior.
12. Entrenamiento candidato empeora un campo crítico aunque mejore CER general → no se promueve.
13. Informe de `test_sellado` no se reutiliza en el proceso de selección de modelos.
14. Proyecto explícito B en UI, plantilla con proyecto A → solo B en informe, plantilla original intacta.
15. Excel con fórmulas, celdas combinadas, tablas vacías y hojas extra → sin pérdida de contenido; rechazar publicación en caso ambiguo.
16. Videos 5,000 FPS contra 8 FPS playback y overlays inconsistentes → no inventar 0.1 ms por redondeo ni confundir cuadros.
17. ROI manual de video bloqueada → no desplazada tras zoom, recalcular, reabrir ni entrenamiento.
18. Reanudar/cancelar procesado sin duplicar carpetas ni aprendizaje; métricas y Excel consistentes.
19. Procesar N imágenes repetidas con hash estable → cache hit solo si modelo/ROI/config no cambiaron.
20. Verificar en Windows offline; uso de VRAM acotado y modo CPU alternativo; tiempo no peor sin justificación.

## E10. Skills V-Matrix: extenderlas, no crear seis duplicadas

- `v-matrix-safe-change`: exigir backup consistente SQLite, no pérdida de historia ni cambios de esquema destructivos.
- `v-matrix-evaluation-lab`: benchmark campo-a-campo, test sellado, detección de fuga y matriz de rendimiento humano.
- `v-matrix-matrix-excel`: contratos de identidad y campo, paridad fuente canónica y Excel sin herencia de plantilla.
- `v-matrix-roi-supervision`: ampliarla para ROI de **texto fotográfico** sin confundir ROI de video; polígonos, perspectiva y aprendizaje correcto.
- `v-matrix-airbag-onset`: conservar línea de video y añadir validación de candidatos/sincronización.
- `v-matrix-video-zoom-ux`: centro de revisión mínimo por excepción, pruebas de mapping y coordenadas.

**Dos skills nuevas, opcionales tras auditoría:** `v-matrix-ocr-field-extraction` para reglas contextualizadas EDAG/VW y conciliación por campo; `v-matrix-learning-auditor` para validación read-only de `.aprendizaje`, data lineage, entrenamientos y rollback. Añadir solo cuando sus procedimientos estén automatizados y validados, no como mera documentación ornamental.

## E11. Prompt maestro integrado para Codex (sustituye el prompt restringido solo a apertura)

> Desarrolla **V-Matrix V15.10 — Evidence Intelligence** a partir del paquete V15.9.10, conservando arquitectura local, EasyOCR, aprendizaje anterior, GUI, video, ROI, Excel y las skills existentes. Lee **todo este documento**, incluidas las secciones del detector y extensión E1–E11, y trátalo como contrato de implementación.
>
> **No empieces entrenando a ciegas.** Primero realiza auditoría READ-ONLY de una COPIA de `.aprendizaje` cuando esté disponible: salud SQLite, esquemas, muestras visuales vs observaciones, pesos/modelos, conflictos, recortes huérfanos, aplicabilidad real de correcciones, ROI y estrategias. Entrega informe y propuesta de limpieza no destructiva. Si aún no se proporcionó la carpeta, marca la auditoría `PENDIENTE` y trabaja en trazabilidad y pruebas, jamás inventes estadísticas de entrenamiento.
>
> Luego implementa por fases: fuente canónica por proyecto/caso/campo, matriz dinámica sin vacantes teóricas, razones de gris, revisión manual→resultado→Excel; OCR top-k con contexto de la guía EDAG/VW, validación de códigos/QR/ruta, ranking de fuentes y autollenado conservador; detector de apertura que plantea candidatos, examina fotogramas anteriores y posteriores y verifica sincronización multicámara; datos de aprendizaje supervisados con negativos y split train/dev/test sellado; revisión por excepción y modelos candidatos reversibles.
>
> Cada campo del Excel debe tener una evidencia trazable y estado de validación. La confianza OCR sin calibrar nunca autoriza automáticamente un campo crítico. Separa `test_reason`, `project_id`, fabricante/laboratorio y tiempo físico; no propagues datos precargados de plantillas a nuevas corridas. Protege tablas/fórmulas/cabeceras Excel y nunca muevas ROI manuales. Registrar observaciones OCR no equivale a entrenar EasyOCR ni a tener etiquetas correctas.
>
> No modifiques datos ni entrenes modelos de producción sin aprobación. Conserva la última versión operativa y genera candidatos en **modo sombra** con rollback. Ejecuta pruebas unitarias, integración, navegador, regresiones N7–N17 y tests con videos/fotos reales autorizados en lotes reservados. Publica métricas reproducibles por campo y cámara, tasa de errores silenciosos, precisión temporal, automatización y tiempo por lote, contra V15.9.10. No declares una mejora por pasar pruebas sintéticas únicamente. Entrega parches por fase en rama nueva con scripts de instalación/rollback, sin sobrescribir el repo original.

## E12. Condición final de aceptación del sistema integral

V-Matrix habrá mejorado de verdad si un lote nuevo puede procesarse **sin que el usuario transcriba manualmente lo que ya es evidente**, entregando Excel y matriz correctos, y si ante un código ilegible, dos fuentes contradictorias o una apertura dudosa **se abstiene y presenta exactamente la evidencia a revisar**. Cada intervención debe quedar registrada y favorecer futuros casos similares, pero solo un experimento controlado decide cuándo cambiar el modelo global.

**No se declara lista para producción antes de la auditoría de aprendizaje, prueba de extremo a extremo en la máquina corporativa, evaluación con fotografías/AVI reales etiquetados y validación humana final de los criterios de liberación.**
