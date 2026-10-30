# Plan de mejora R9 — estándar de apertura física

## Objetivo
Detectar el primer instante físicamente defendible de apertura de forma reutilizable entre piezas y permitir una decisión automática de color sin confundirla con auto-publicación.

## Flujo estándar
1. Construir baseline previo al evento.
2. Estimar movimiento/deformación local de la pieza.
3. Crear una zona de búsqueda normalizada alrededor de la deformación dominante.
4. Comparar cada frame con el baseline compensado.
5. Detectar material nuevo claro u oscuro con discontinuidad local.
6. Excluir el propio material candidato del cálculo de la zona de deformación para evitar auto-validación circular.
7. Mantener sólo la componente dominante de deformación por defecto; configurable para piezas con varias zonas activas.
8. Exigir persistencia posterior y cuadros previos limpios.
9. Penalizar reflejo, iluminación global, abombamiento sin ruptura y movimiento de cámara.
10. Emitir evaluación `alta/media/baja` y razones trazables.
11. Si evidencia=alta + tiempo positivo + referencia válida: permitir color automático estimado.
12. Si hay contradicción o referencia inválida: abstenerse y dejar gris.

## Generalización
No se codifica un nombre de pieza. Los parámetros usan fracciones normalizadas, flujo óptico y configuración reutilizable:
- `deformacion_movimiento_min_px`
- `deformacion_mad_factor`
- `deformacion_fraccion_min/max`
- `deformacion_max_componentes`
- `deformacion_rel_area_min`
- `margen_deformacion_norm`
- `margen_deformacion_px_max`
- `auto_color_evidencia_min`

## Separación de responsabilidades
- Detector visual: encuentra evidencia y primer frame.
- Referencia temporal: valida ms/frame/overlay.
- Política de publicación: decide si puede confirmarse oficialmente.
- Matriz/Excel/dashboard: proyectan la misma decisión canónica.
