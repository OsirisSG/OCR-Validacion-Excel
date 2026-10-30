# Documento maestro del sistema OCR

Este documento es el contrato funcional vigente del repositorio. El flujo
legacy se conserva como respaldo y el flujo empresarial se activa por caso.

## Meta operativa

```text
El sistema recolecta.
El sistema interpreta.
El sistema llena.
El sistema valida.
El sistema prepara aprendizaje supervisado.
El humano revisa únicamente excepciones.
```

No se promete exactitud absoluta. El objetivo es reducir progresivamente la
revisión manual mediante evidencia confirmada, sin completar datos sin fuente.

## Aprendizaje

Implementar aprendizaje supervisado real y versionado del reconocedor EasyOCR
utilizando correcciones confirmadas desde el dashboard.

Las reglas aprendidas y la base de conocimiento se mantienen, pero no
sustituyen el entrenamiento visual del OCR.

Las correcciones humanas deben convertirse en datos de entrenamiento
auditables para que la intervención humana disminuya progresivamente.

Una predicción sin confirmar no puede entrenar. El dataset conserva recorte,
imagen de origen, ROI, texto OCR/corregido, campo, ID, fase, TOR, confianza,
modelo, fecha y hash. El entrenamiento se realiza por lotes y divide por ID
para evitar fuga entre entrenamiento, validación y prueba. Un candidato sólo
se activa si mejora las métricas configuradas sin regresiones importantes;
guardar una corrección individual no entrena ni promueve el modelo por sí solo.
siempre existe rollback.

## Fase A: recolección e inventario

La Fase A detecta 1ST/2ST, estructura por caso, metadatos derivados de la ruta,
NACH/VOR/TOR, todas las fotografías y su firma de archivo. Persiste
`inventario_proyecto.json` y `estructura_detectada.json` sin ejecutar OCR ni
generar el llenado final.

## Fase B: extracción, consolidación y llenado

La Fase B puede continuar inmediatamente o reanudarse desde el inventario.
Busca QR antes de descartar, detecta regiones de texto, aplica recorte,
perspectiva y zoom real, reconoce, normaliza y consolida una fila por ID. Los
faltantes no detienen el lote y dos valores incompatibles reales producen un
conflicto auditable.

La revisión distingue dos herramientas que no deben confundirse:

- El zoom de vista sólo cambia la presentación en el navegador.
- El zoom OCR recorta una región de interés y vuelve a analizar sus píxeles.

La rotación manual acepta cualquier ángulo, expande el lienzo para no cortar la
fotografía y prevalece sobre orientación y deskew automáticos. El movimiento se
previsualiza en tiempo real y se persiste con `Aplicar giro`; 0° también puede ser
una decisión manual explícita. `Usar automático` recupera la geometría automática
original. Seleccionar una fotografía en la lista inferior abre el visor, lo centra
y activa de inmediato sus herramientas de edición sin ocultar las demás.

La biblioteca local administra múltiples plantillas, cada una con su copia y
contrato independiente: hojas, claves, diccionario, catálogos, validaciones y
formato. Tipo 1ST/2ST, perfil, marcadores de ruta y estrategias declarativas
permiten seleccionarlas automáticamente. En un empate no se adivina ni se
mezclan contratos: se requiere selección explícita o se usa el formato integrado.

## Códigos operativos

La salida principal prioriza códigos normalizados y corroborables, no oraciones.
Se aceptan catálogos conocidos, números de parte estructurados, seriales numéricos
de longitud suficiente y códigos alfanuméricos que contienen letras y números.
Se descartan de esa salida las frases, unidades sueltas, palabras sin dígitos,
fragmentos demasiado cortos y ruido; la lectura completa permanece disponible
para revisión y cada decisión conserva una razón visible.

## Prioridad de fuentes

1. Corrección manual confirmada.
2. Ruta para campos estructurales.
3. QR válido compatible con el esquema.
4. Nombre de carpeta o archivo.
5. OCR coincidente en varias imágenes.
6. OCR de una imagen.
7. Regla confirmada para completar un faltante.

Las claves estables son identificadores internos: nunca se buscan literalmente
en una fotografía. Los campos opcionales ausentes son `faltante`, los
obligatorios `faltante_requerido` y sólo candidatos reales incompatibles son
`conflicto`.

## Seguridad y portabilidad

Los QR URL se conservan como texto y nunca se abren. Las imágenes originales no
se modifican. EasyOCR usa CUDA cuando existe, MPS en Apple Silicon y CPU como
respaldo. No se crean procesos que dupliquen el modelo. La caché es transaccional
y el entrenamiento usa un bloqueo separado del OCR normal.

Windows 11 con Python 3.12 de 64 bits es el objetivo principal; macOS y Linux
se mantienen compatibles. Los scripts de arranque sólo aplican Bypass de
PowerShell al proceso actual.

El avance operativo se persiste por imagen e ID. Pausa y cancelación nunca se
presentan como error: se informa el último ID terminado y se puede reanudar con
el modelo vigente, reutilizando la caché cuando imagen, configuración y modelo
siguen iguales.
