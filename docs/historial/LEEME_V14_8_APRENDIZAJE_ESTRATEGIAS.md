# V14.8 — aprendizaje reforzado de estrategias OCR

Esta versión amplía V14.7 sin borrar ni migrar destructivamente `.aprendizaje`.

## Qué aprende

Cuando el revisor elige una orientación, activa/desactiva el ajuste fino o usa una relectura manual con un tratamiento visual y después confirma el bloque con **Aplicar supervisión**, se registra también la estrategia OCR que produjo el borrador confirmado:

- orientación base 0/90/180/270;
- ajuste angular manual/fino;
- tratamiento: automático, original, CLAHE, adaptativa o relieve;
- tipo esperado: automático, código, fecha, número o texto;
- confianza OCR y congruencia observadas;
- contexto empresarial disponible y posición relativa de la región.

Mover controles o probar una lectura sin confirmarla NO entrena el sistema.

## Protección contra sobreaprendizaje

Una misma imagen/caja cuenta una sola vez. Reconfirmarla actualiza su evidencia; no incrementa artificialmente el soporte.

Valores predeterminados:

- 1 imagen: evidencia recordada; no se aplica automáticamente.
- 2 imágenes coherentes: estrategia sugerida.
- 4 imágenes distintas y >=75 % de dominancia: patrón consolidado que puede priorizarse automáticamente.

La estrategia consolidada sólo se conserva en una imagen nueva si su lectura sigue siendo congruente y no está clasificada como ruido. Si empeora el resultado, el OCR conserva su método normal.

## Generalización segura

El editor usa proyecto, fase, tipo ST, versión, campo, componente y posición relativa cuando están disponibles. Durante el OCR inicial, donde no siempre existen todos esos metadatos, sólo se generaliza entre imágenes de un grupo estable de ruta similar y una zona relativa similar.

Los nombres de carpeta que parecen IDs numéricos se excluyen de la firma de ruta para permitir aprendizaje entre casos distintos con la misma estructura (por ejemplo `1ST/.../PHOTOS/NACH`).

## Rendimiento

Las estrategias se cargan una vez por instancia de procesamiento y se reutilizan en memoria durante las regiones de una imagen. No se consulta SQLite por cada intento OCR. Una estrategia consolidada añade como máximo una lectura adicional y evita duplicarla cuando coincide exactamente con una pasada cardinal ya realizada.

## Interfaz

El panel de orientación muestra **Aprendizaje de estrategia OCR** cuando existe evidencia parecida, indicando soporte, dominancia y parámetros aprendidos. `Probar estrategia aprendida` copia el resultado sólo como borrador; vuelve a reforzarse únicamente si el usuario pulsa **Aplicar supervisión**.
