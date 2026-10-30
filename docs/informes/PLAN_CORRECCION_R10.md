# V-Matrix V15.10.1 R10 — Protocolo de apertura y ergonomía del visor

## Objetivo

Mejorar la autonomía del sistema para detectar el **primer instante físicamente defendible de apertura** y asignar un color estimado cuando un solo video ofrece evidencia suficiente, sin confundir esa decisión visual con publicación automática oficial.

## Protocolo de apertura R10

1. Construir baseline limpio previo al evento.
2. Detectar deformación/movimiento local de la pieza.
3. Buscar material nuevo, fisura o borde nuevo cerca de esa deformación.
4. Conservar el **primer indicio mínimo** como onset; cuadros posteriores sólo lo corroboran.
5. Exigir persistencia, crecimiento o continuidad espacial y cuadros previos limpios.
6. Penalizar reflejos, cambio global de iluminación, movimiento de cámara, evidencia previa y material lejos de la deformación.
7. Un solo video con evidencia visual alta + tiempo basado en FPS de captura defendible puede habilitar color estimado.
8. Dos o más videos fuertes pero temporalmente contradictorios obligan abstención gris.
9. Consenso multicámara y referencia temporal validada siguen siendo más estrictos para publicación automática.

## Tiempo de llenado

R10 añade una segunda métrica independiente del onset:

- `frame_llenado_estimado`
- `duracion_llenado_estimada_ms`

Se calcula desde el onset defendible hasta la primera **meseta visual estable** del despliegue. Es una estimación visual reproducible y no certifica volumen, presión interna ni llenado físico completo.

## Zoom y revisión

- rueda con zoom progresivo centrado en cursor;
- botones +/- con pasos suaves;
- presets rápidos 100/150/200/300/400/600/800 %;
- doble clic alterna 250 % / ajustar;
- pan con arrastre estable;
- reset devuelve zoom y scroll al origen;
- zoom/pan/giro no modifican coordenadas fuente de ROI o microzona.

## Principio de seguridad

R10 separa tres niveles:

- **detección física**: puede sostenerla un solo video defendible;
- **color estimado**: puede aparecer con evidencia alta y tiempo local fiable;
- **publicación automática**: exige criterios temporales/consenso más estrictos.

Ante contradicción o falta de evidencia suficiente, el sistema se abstiene.
