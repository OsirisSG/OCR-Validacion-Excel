# OCR V14.7 — Control manual del OCR regional

## Qué cambia

V14.7 mantiene las mejoras de V14.6 y añade control explícito para la revisión de zonas difíciles.

- Selector **Qué estás buscando**: Automático, Código, Fecha, Número/medición o Texto general.
- Umbral editable de **congruencia mínima**.
- Opción para desactivar **Copiar automáticamente la sugerencia a Texto correcto**.
- Botón **Aplicar mejor según este criterio** para que la decisión sea explícita.
- Panel de **Relectura manual** con ajuste angular de **-45° a +45°** alrededor de la orientación cardinal elegida.
- Relectura real, no solo visual, con tratamientos: Original, CLAHE, Binarización adaptativa, Relieve o comparación automática de los cuatro.
- Resultado manual separado, con **confianza OCR** y **congruencia** mostradas de forma independiente.
- La lectura manual nunca se guarda sola: debe pulsarse **Usar esta lectura** y después el flujo normal de **Aplicar supervisión**.
- Comparación visible entre lectura base y lectura con ajuste fino cuando difieren.
- Defensa adicional en frontend para no presentar como código una cadena con símbolos fuertes o mezcla sospechosa de mayúsculas/minúsculas, incluso si llega información antigua desde caché.

## Ajuste automático vs. ajuste manual

El ajuste automático conserva el comportamiento seguro de V14.6: normalmente ±15° y hasta ±30° solo con evidencia geométrica fuerte.

El ajuste manual llega a ±45° porque aquí la decisión es del revisor. Con las cuatro orientaciones cardinales, esto permite inspeccionar cualquier ángulo del círculo sin volver a permitir que el algoritmo automático persiga ruido por sí solo.

## Cómo usarlo en un caso difícil

1. Selecciona la zona.
2. Abre **Más control sobre OCR**.
3. En **Qué estás buscando**, elige el tipo esperado. Si es un serial, selecciona Código; si se ve una fecha, selecciona Fecha.
4. Si no quieres que el sistema cambie el borrador por sí mismo, desactiva la copia automática.
5. Elige la orientación cardinal más cercana.
6. Ajusta el control angular manual hasta que la imagen se vea recta.
7. Deja **Comparar automáticamente** para que pruebe Original, CLAHE, Adaptativa y Relieve, o fuerza un tratamiento específico.
8. Pulsa **Releer este ángulo**.
9. Revisa confianza y congruencia. Si coincide con la imagen, pulsa **Usar esta lectura**.
10. Guarda finalmente con **Aplicar supervisión**.

## Compatibilidad

V14.7 no borra ni migra destructivamente `.aprendizaje`, `.cache_ocr`, checkpoints ni la cola persistente de Excel. El parche está pensado para aplicarse encima de V14.6.
