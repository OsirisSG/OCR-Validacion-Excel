# V-Matrix V15.10.1 R11 — Onset canónico y resumen vivo

R11 es acumulativa sobre R10 y corrige dos causas encontradas al profundizar las pruebas:

1. **Onset físico canónico.** El estándar de apertura deja de ser sólo evidencia auxiliar. Cuando existe un primer indicio físicamente defendible, ese frame gobierna `frame_evento`; el frame posterior grande queda como confirmación. El valor legado se conserva en `frame_evento_legacy` para auditoría.
2. **Seguimiento por microzona.** El verificador ya no usa una tolerancia global amplia ni el componente mayor del frame. Sigue la trayectoria espacial del candidato, respeta cuadros limpios y separa hot-pixels/ruido de una ruptura real.
3. **Fisura oscura temprana.** Una fisura mínima que el detector morfológico pierde durante pocos frames puede ser corroborada por crecimiento posterior en la misma microzona sin desplazar el onset.
4. **Resumen durante procesamiento.** El dashboard usa exclusivamente parciales de la ejecución actual. Un caso todavía no analizado se muestra `pendiente`, no gris definitivo, y no hereda color de la corrida anterior.
5. **Trazabilidad de color.** El tooltip expone soporte, score/nivel de evidencia y, cuando existe, duración visual estimada de llenado.
6. **Compatibilidad.** Se mantienen R10: onset defendible con un solo vídeo para color estimado, publicación más estricta, duración de llenado visual y zoom suave sin mover ROI/microzona.

## Regla física preservada

- inicio = primer frame con ruptura/material nuevo defendible, aunque sea mínimo;
- cuadros posteriores corroboran crecimiento/persistencia pero no sustituyen el onset;
- reflejo, cambio global, hot-pixel aislado o abombamiento sin ruptura no deben promoverse;
- una referencia temporal dudosa no habilita color por tiempo;
- consenso multicámara refuerza/publica, pero no es requisito para reconocer un onset fuerte de una sola cámara.
