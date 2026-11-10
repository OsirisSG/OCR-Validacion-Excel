# V-Matrix V15.10.1 R11

R11 es acumulativa: incluye las correcciones R7/R8/R9/R10 y añade el cierre del **primer onset físicamente defendible** y un resumen en vivo sin contaminación de corridas anteriores.

## Instalación

1. Cierra completamente V-Matrix, navegador y servidor anterior.
2. Extrae TODO este ZIP a una carpeta temporal.
3. Ejecuta `INSTALAR_R11.bat`.
4. Debe aparecer `PARCHE_R11_COPIADO_Y_VERIFICADO_OK`.
5. Reinicia V-Matrix.
6. Abre `http://127.0.0.1:8000/api/estado` y confirma `patch_build = 15.10.1-r11`.
7. En el navegador usa `Ctrl + F5` una vez.

El instalador crea respaldo, verifica SHA-256 en destino, no incluye/modifica `AGENTS.md`, `.agents` ni `.aprendizaje`, y comprueba los imports con el Python real de V-Matrix cuando lo encuentra.

## Cambio principal

El frame posterior donde la bolsa ya es grande **no puede desplazar** al primer frame donde una ruptura/material nuevo mínimo ya es defendible. El valor legado queda disponible para auditoría.
