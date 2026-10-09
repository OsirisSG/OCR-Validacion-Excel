# V15.8: guía de etiquetas, ruptura y máximo visible

Base: `OCR-Validacion-Excel-ocr-gpu-produccion_COMPLETO_LIMPIO_20261009_121301.zip`.
Se conservan los cambios V15.7.4 del ZIP. Tras la preparación inicial separada,
el usuario pidió aplicar el código también a `proyecto_ocr`; esa copia conserva
sus datos locales y preferencias. No se hicieron commits o push. La actualización
no añade dependencias. Consulta [ACTUALIZACION_CARPETA_V15_8.md](../informes/ACTUALIZACION_CARPETA_V15_8.md) para el respaldo.

## Instalación segura

1. Cierra el dashboard y los procesos Python de la instalación que actualizarás.
2. Conserva copia de `.aprendizaje`, `.cache_ocr`, `validacion_resultados.json`,
   inventarios, checkpoints y tus Excel. No borres `avances_ids.json`.
3. La copia completa conserva **los datos incluidos en el ZIP original**. Si tu
   instalación tiene correcciones posteriores a ese ZIP, no sobrescribas sus
   datos con los de la copia completa: actualiza únicamente el código indicado
   en el informe de validación. No mezcles bases SQLite copiándolas una encima
   de otra mientras el programa esté abierto.
4. En Windows inicia con `Iniciar_OCR.bat` o el lanzador habitual. En una máquina
   nueva ejecuta `python instalar.py --perfil completo` y después `python iniciar.py`.
   No copies `.venv` entre equipos. La detección CUDA/CPU existente se conserva.
5. Recarga el navegador para cargar los recursos V15.8.

## Tres tiempos distintos

- **Apertura / ruptura:** primer indicio visible de rotura de la costura, no el
  abombamiento del tablero anterior. El detector propone un fotograma y busca
  evidencia posterior persistente, creciente y cercana antes de retroceder.
- **Máximo despliegue visible:** fotograma que el revisor identifica como mayor
  despliegue visible de la bolsa en esa cámara. No mide volumen ni demuestra por
  sí solo que el inflado esté completo.
- **Inflado completo:** mantiene el campo histórico `full_inflation_time_ms` y
  requiere su propia evidencia/confirmación. Nunca se rellena copiando el máximo.

## Cómo confirmar el máximo y exportarlo

1. Abre el detalle de un ID con vídeos y confirma primero la ruptura en la tarjeta
   de cada vídeo que quieras usar. Revisa cuadro anterior y posterior.
2. Avanza con flechas, línea de tiempo o **Cuadro exacto** hasta el mayor despliegue
   visible. Pulsa **Confirmar máximo visible aquí**. El servidor verifica el vídeo,
   la decodificación, el orden temporal y resuelve el tiempo del cuadro.
3. **Ir al máximo guardado** permite volver a inspeccionarlo. Una nueva confirmación
   corrige la selección y conserva el historial. La confirmación de apertura no cambia.
4. Se encola la actualización del Excel. Si Excel está abierto/bloqueado, el feedback
   sigue guardado aunque la exportación se retrase; consulta la notificación existente.
5. A:AJ conserva sus campos. **AK** contiene máximo visible confirmado y **AL** su
   revisión. Sin confirmación, AK queda vacío. Si las cámaras confirmadas difieren más
   que una resolución de cuadro, queda conflicto y no se inventa un promedio. Dentro
   de esa tolerancia se usa el mayor tiempo confirmado, documentado en el libro.
6. La hoja de evidencia de vídeo conserva archivo, fotogramas, FPS, origen temporal,
   apertura, máximo, regiones, revisión y advertencias en ES/EN/DE.

Los FPS del contenedor pueden ser sólo de reproducción (por ejemplo 8 fps).
Se reutiliza el resolutor temporal del programa: FPS reales de adquisición,
reloj visible validado y origen temporal del ensayo. No se deduce una precisión
física de 0.1 ms por imprimir un decimal: a 1000 fps la separación es 1 ms;
a 5000 fps es 0.2 ms. Si el origen del ensayo o la tasa son desconocidos, deben
calibrarse antes de interpretar el tiempo como una medición del ensayo.

## Persistencia y revisión

El máximo se guarda en `.aprendizaje/maximos_video.json`, con historial y SHA-256
completo del vídeo. Se reutiliza al reprocesar y exportar, aunque el archivo cambie
de carpeta. La escritura usa el helper seguro común con temporales únicos,
fsync, reintentos de PermissionError y RLock para lectura/modificación/escritura.
Un fallo no reemplaza el feedback previo ni se comunica como guardado exitoso.
No se escribe el JSON de resultados para confirmar un máximo, evitando colisiones
con sus escritores de fondo. Esta acción **no entrena** EasyOCR.

Si cambian los bytes del vídeo, la apertura confirmada, FPS u origen temporal,
el máximo puede requerir nueva revisión. El feedback original permanece. Si el
vídeo está offline se conserva la evidencia, sin afirmar que se haya verificado
de nuevo. Las revisiones completadas deben reabrirse antes de editar.

## Extracción según la guía

- Proyecto/motivo explícitos en la pizarra o una captura pueden llenar Motivo de
  prueba. El nombre interno de la carpeta no se copia como motivo sin evidencia.
- Se distinguen laboratorio EDAG/VW de fabricante VW AG. El prefijo de número de
  prueba y el texto de laboratorio deben aportar contexto; no basta una marca.
- El patrón EDAG WWYYNN puede aportar semana/año; si contradice la fecha del
  ensayo queda conflicto, no se impone una fuente silenciosamente.
- Se separan PN, serie, proveedor, fecha y nivel de ingeniería de bolsa y tablero.
  Los códigos 02S, 69K, 03S y números de parte de la guía son ejemplos, no valores
  predeterminados. Un PN compacto de tablero requiere contexto de componente.
- Delay, Forvia e inflado completo exigen sus etiquetas o confirmación; no se
  confunden con cualquier número seguido de ms.
- Los seriales conservan guiones y ceros. El P/N ALV de prototipo señalado en la
  guía como Serie se propone con aviso, no se trata automáticamente como serial.
  Una nomenclatura nueva de ingeniería etiquetada queda pendiente de confirmación.
- Apertura láser del tablero se propone sólo con etiqueta explícita y revisión
  propia. No se deriva del PN ni del tiempo de ruptura. Homologar automáticamente
  módulos y tableros necesita un catálogo de combinaciones aprobadas que no está
  en la guía; por ahora se conservan sus evidencias separadas, sin copiar valores.
- Si dos etiquetas del mismo componente concuerdan, se corroboran; si difieren,
  ambas se conservan como conflicto. No se impone una por ser prototipo.
- Se preservan fecha impresa y valor normalizado. Un formato ambiguo no se adivina.
  Para un lote que el responsable confirme como día/mes/año puede configurarse:

  ```yaml
  empresarial:
    perfil_extraccion:
      formato_fecha: DMY
  ```

  El valor por defecto permanece neutral `{}`. No declares un componente global
  para lotes que mezclan bolsa y tablero. Dos fechas discrepantes siguen siendo
  conflicto. Las correcciones humanas existentes tienen prioridad.

## Rangos elegidos por el usuario

En **Resumen → Definir rangos del tiempo de apertura** puedes indicar el límite
verde y el límite amarillo. Verde incluye su límite; amarillo comienza por encima
de verde e incluye el suyo; rojo queda por encima del amarillo. Los valores deben
ser finitos y cumplir `0 ≤ verde < amarillo`. Guardar actualiza la matriz y su
leyenda; vuelve a exportar para aplicar la elección al Excel. No cambia tiempos
medidos ni usa esos límites para FORVIA, inflado completo o máximo visible.

Se guardan en `.aprendizaje/criterios_usuario.json` con responsable/fecha e historial,
sin alterar el YAML base; CLI y dashboard leen las mismas reglas. Si falla el
guardado se conservan las anteriores. No se puede cambiar durante un lote activo
o pausado. Los 6/7 ms iniciales se mantienen como referencia del YAML hasta que
el usuario elija y guarde: no fueron deducidos de la guía ni son una homologación.

La guía menciona delay de uno/dos pasos y homologaciones. No proporciona catálogo
de pasos de disparo ni matriz de combinaciones módulo-tablero: no se deducen desde
NOM/OGL/UGL, ni se inventa un delay de cero. Requieren evidencia explícita o una
regla aprobada por el responsable.

## Límites y rendimiento

El detector nuevo conserva resolución nativa y contempla indicios claros u
oscuros de un píxel **sólo si hay corroboración temporal y espacial posterior**.
No acepta por defecto cambio general o brillo estático como ruptura. El revisor
recibe PNG del fotograma decodificado, sin añadir JPEG ni reducir la imagen.
No puede recuperar detalle perdido en el vídeo original ni garantizar detectar
cualquier píxel con compresión, reflejos, ruido, oclusión o cámara en movimiento.
Los resultados automáticos siguen siendo candidatos revisables.

Conservar resolución puede aumentar CPU/RAM; no se promete menor tiempo. Se
mantiene parada temprana tras corroboración y un buffer acotado; un retroceso
fuera del buffer redecodifica secuencialmente sin cargar todo el vídeo. El máximo
manual no añade una segunda pasada automática a todos los vídeos.

Falta validar sensibilidad/error temporal con vídeos reales etiquetados del
usuario y ejecutar las pruebas nativas en Windows 11/RTX A3000. Las pruebas
sintéticas y la simulación de PermissionError no sustituyen esas mediciones.
