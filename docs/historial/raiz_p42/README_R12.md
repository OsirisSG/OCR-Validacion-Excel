# V-Matrix V15.10.1 R12

R12 es acumulativa sobre R11 y corrige dos problemas visibles durante una ejecución activa:

1. **Azul pendiente real:** una fila inventariada/detectada ya no se muestra gris antes de terminar el análisis.
2. **Decisión explicable:** el color automático sólo se habilita cuando pasan puertas físicas explícitas; el tooltip indica puertas, bloqueos y riesgos.

## Instalación
1. Cierra V-Matrix, servidor y navegador.
2. Extrae todo el ZIP a una carpeta temporal.
3. Ejecuta `INSTALAR_R12.bat`.
4. Debe aparecer `PARCHE_R12_COPIADO_Y_VERIFICADO_OK`.
5. Reinicia V-Matrix y abre `http://127.0.0.1:8000/api/estado`.
6. Confirma `patch_build = 15.10.1-r12`.
7. Haz Ctrl+F5 una vez.

Durante la ejecución: azul = pendiente; gris = abstención/evidencia insuficiente/conflicto; verde/amarillo/rojo = tiempo defendible bajo los límites elegidos.
