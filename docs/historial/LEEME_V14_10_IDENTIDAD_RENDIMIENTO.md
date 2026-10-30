# V14.10 — identidad OCR y persistencia más rápida

Esta versión parte de V14.9 y conserva aprendizaje inmediato, autoentrenamiento,
editor, rotaciones, ajuste fino, cola Excel durable y recuperación del pipeline.

## Identidad visual

Se integra el logotipo OCR proporcionado por el usuario y variaciones derivadas
únicamente de esa identidad:

- `dashboard/frontend/assets/logo_original.jpeg`: archivo original recibido.
- `logo_claro.png`: recorte para cabecera clara.
- `logo_oscuro.png`: variante nocturna para cabecera oscura.
- `logo_icono.png`: recorte compacto para usos pequeños.
- `favicon.png`: favicon derivado del mismo símbolo.

La cabecera selecciona automáticamente la versión clara u oscura según el tema.

## Mejoras de tiempo sin cambiar la lógica empresarial

### 1. Checkpoint del pipeline agrupado

Los eventos de progreso que llegan varias veces por segundo ya no fuerzan una
serialización + fsync completa en cada evento. Se conserva únicamente el estado
más reciente y se escribe tras una ventana corta de 350 ms.

Pausa, cancelación, error, finalización y cierre del dashboard siguen forzando
una escritura inmediata. La recuperación segura se conserva.

### 2. JSON consolidado compacto

Los JSON grandes escritos por el dashboard usan serialización compacta. El
contenido lógico es idéntico, pero se escriben menos bytes y se reduce el coste
de serialización y de disco. La escritura continúa siendo atómica y con fsync.

### 3. Cola Excel con debounce deslizante

Una corrección aislada puede empezar su actualización Excel después de ~0.8 s.
Si el usuario hace varias correcciones seguidas, se agrupan y se genera el Excel
una sola vez cuando hay un breve periodo de silencio, con una latencia máxima de
2.5 s antes de iniciar una exportación pendiente.

La cola SQLite, idempotencia, reintentos y recuperación tras reinicio se conservan.

### 4. Caché SHA-256 de imágenes

Confirmar varias zonas de la misma fotografía ya no obliga a releer el archivo
completo para calcular el mismo SHA-256 en cada clic. La caché usa ruta, tamaño y
`mtime_ns`; si el archivo cambia, se invalida automáticamente. Está acotada a
2048 entradas.

### 5. Índice de rutas del dashboard

El backend deja de recorrer todas las imágenes del lote en cada solicitud de
vista previa. Construye un índice reutilizable de las rutas registradas y lo
invalida al cambiar el JSON consolidado.

## Configuración

```yaml
persistencia:
  checkpoint_debounce_segundos: 0.35
  excel_debounce_segundos: 0.80
  excel_latencia_max_segundos: 2.50
```

Estos valores pueden ajustarse, pero no se recomienda hacer el checkpoint mucho
más lento porque aumentaría la ventana de progreso todavía no volcado a disco.

## Compatibilidad

No se elimina ni reemplaza `.aprendizaje`, `.cache_ocr`, checkpoints, cola Excel,
plantillas, aprendizaje visual ni resultados existentes.
