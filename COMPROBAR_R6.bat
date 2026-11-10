@echo off
setlocal
cd /d "%~dp0"
set "TARGET=C:\Programas Base\OCR-Validacion-Excel-ocr-gpu-produccion"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALAR_R6.ps1" -Target "%TARGET%" -VerifyOnly
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
  echo ERROR: la instalacion R6 no coincide con el paquete.
  pause
  exit /b %RC%
)
echo Comprobacion R6 correcta.
pause
