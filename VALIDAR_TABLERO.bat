@echo off
rem P43 - Validacion LOCAL con fotos del cliente. No instala nada, no usa red y no modifica el libro.
rem Uso:
rem   VALIDAR_TABLERO.bat "<carpeta de fotos del lote>" "<libro de partida .xlsx>" "<carpeta de salida>" [opciones]
rem Opciones (se pasan tal cual a validar_corrida_p43.py):
rem   --referencia "<Book corregido .xlsx>"   solo para EVALUAR, nunca para escribir
rem   --tipo-st 1ST^|2ST   --perfil-edag   --sin-segunda-pasada   --presupuesto-s 300   --limpiar-recortes
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
if "%~3"=="" (
  echo Uso: VALIDAR_TABLERO.bat "carpeta de fotos" "libro.xlsx" "carpeta de salida" [--referencia "Book.xlsx"] [--perfil-edag]
  exit /b 2
)
"%PY%" -X utf8 "%PROYECTO%comprobar_entorno_p42.py"
"%PY%" -X utf8 "%PROYECTO%validar_corrida_p43.py" --fotos "%~1" --libro "%~2" --salida "%~3" %4 %5 %6 %7 %8 %9
set "CODIGO=%ERRORLEVEL%"
echo.
if "%CODIGO%"=="0" (echo VERIFICACION OBLIGATORIA: OK) else (echo VERIFICACION OBLIGATORIA: FALLA codigo %CODIGO%)
exit /b %CODIGO%
