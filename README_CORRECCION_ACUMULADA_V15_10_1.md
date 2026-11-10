# V-Matrix V15.10.1 — Corrección acumulada R6 (2026-10-14)

## Motivo de R6
R5 no llegaba a instalarse en equipos donde el comando `python` era sólo el alias de Microsoft Store. R6 elimina esa dependencia del instalador.

## Instalación recomendada
1. Cierra por completo V-Matrix, el servidor/dashboard y sus ventanas CMD/PowerShell.
2. Extrae TODO este ZIP en una carpeta temporal.
3. Ejecuta `INSTALAR_R6.bat`. No ejecutes el instalador desde dentro del ZIP.
4. Debe terminar con `PARCHE_R6_COPIADO_Y_VERIFICADO_OK`.
5. Reinicia V-Matrix.
6. Abre `http://127.0.0.1:8000/api/estado` y confirma `"patch_build":"15.10.1-r6"`.

## Qué hace el instalador
- Usa PowerShell de Windows; NO necesita que `python` esté en PATH.
- Crea respaldo de todos los archivos reemplazados.
- Copia sólo archivos listados en el manifiesto; no borra otros archivos.
- No modifica `.aprendizaje`, `.agents/skills` ni `AGENTS.md`.
- Verifica SHA-256 de cada archivo en el destino.
- Comprueba que `utilidades/verificador_apertura.py`, `politica_apertura.py` y `sincronizacion_video.py` existan y no estén vacíos.
- Intenta localizar el Python real que usa V-Matrix (proceso en ejecución, venv/entorno embebido, `py.exe`, instalaciones locales). Si lo encuentra, verifica resolución de imports.
- Si no lo encuentra, la instalación sigue siendo válida si los hashes de disco son correctos; después se valida el backend por `/api/estado`.

## Correcciones acumuladas
R6 incluye R5/R4/R3/H5: dependencias de apertura, fallback conservador, rutas de imágenes, identidad de Excel, tiempos inválidos/censurados, aceptación OCR provisional y semáforo dinámico.

## Semáforo
Con límites 6/7 ms y tiempo publicable/confiable: 5.8 ms = verde, 6.4 ms = amarillo, 7.2 ms = rojo. Conflictos, tiempos inválidos o consenso insuficiente permanecen grises.

## Diagnóstico
`COMPROBAR_R6.bat` vuelve a comprobar hashes sin copiar.
