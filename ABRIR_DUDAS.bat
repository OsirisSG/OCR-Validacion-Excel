@echo off
rem Panel de dudas y propuestas (formulario) sobre la salida de VALIDAR_TABLERO.bat.
rem Uso: ABRIR_DUDAS.bat "<libro de salida .xlsx>" ["<lecturas_panel.json>"]
rem   Sin el segundo argumento usa validacion_resultados.json de esta carpeta (la ultima corrida
rem   del dashboard). Muestra la foto de cada opcion con el area leida y deja escribir otro valor.
rem Al guardar crea <libro>_CONFIRMADO.xlsx. Nunca toca el libro original del cliente.
setlocal
chcp 65001 >nul
set "PROYECTO=%~dp0"
set "PY=%PROYECTO%.venv_ocr\Scripts\python.exe"
rem P47 - si esta carpeta no tiene .venv_ocr, se usa OCR_PY o el .venv_ocr de una carpeta hermana
if not exist "%PY%" if defined OCR_PY set "PY=%OCR_PY%"
if not exist "%PY%" for /d %%D in ("%PROYECTO%..\OCR-Validacion-Excel*") do if exist "%%~fD\.venv_ocr\Scripts\python.exe" set "PY=%%~fD\.venv_ocr\Scripts\python.exe"
if not exist "%PY%" (
  echo No se encontro el Python del entorno. Defina OCR_PY con la ruta de python.exe del .venv_ocr.
  exit /b 2
)
echo Python: "%PY%"
if "%~1"=="" (
  echo Uso: ABRIR_DUDAS.bat "libro de salida.xlsx" ["lecturas_panel.json"]
  exit /b 2
)
echo Abre http://127.0.0.1:8099 en el navegador. Cierra esta ventana para terminar.
if "%~2"=="" (
  if not exist "%PROYECTO%validacion_resultados.json" (
    echo No se encontro "%PROYECTO%validacion_resultados.json". Pase lecturas_panel.json como segundo argumento.
    exit /b 2
  )
  "%PY%" -X utf8 "%PROYECTO%panel_confirmacion.py" --libro "%~1" --validacion "%PROYECTO%validacion_resultados.json" --hoja Versuchsmatrix
) else (
  "%PY%" -X utf8 "%PROYECTO%panel_confirmacion.py" --libro "%~1" --lecturas "%~2" --hoja Versuchsmatrix
)
exit /b %ERRORLEVEL%
