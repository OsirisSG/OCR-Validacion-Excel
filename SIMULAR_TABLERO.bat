@echo off
rem P43 - Simulacion con evidencia SINTETICA (sin fotos, sin OCR). No es una lectura real.
rem Uso: SIMULAR_TABLERO.bat "<libro de partida .xlsx>" "<carpeta de salida>" [--vaciar-tablero] [--referencia "<Book .xlsx>"]
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
if "%~2"=="" (
  echo Uso: SIMULAR_TABLERO.bat "libro.xlsx" "carpeta de salida" [--vaciar-tablero] [--referencia "Book.xlsx"]
  exit /b 2
)
"%PY%" -X utf8 "%PROYECTO%simular_tablero_p43.py" --libro "%~1" --salida "%~2" %3 %4 %5 %6
exit /b %ERRORLEVEL%
