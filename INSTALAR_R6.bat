@echo off
setlocal
cd /d "%~dp0"
set "TARGET=C:\Programas Base\OCR-Validacion-Excel-ocr-gpu-produccion"
echo.
echo === V-Matrix V15.10.1 R6 - instalador PowerShell ===
echo Destino: %TARGET%
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALAR_R6.ps1" -Target "%TARGET%"
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
  echo ERROR: R6 no quedo instalado/validado. Revisa el mensaje anterior.
  pause
  exit /b %RC%
)
echo R6 instalado y verificado en disco.
echo Cierra COMPLETAMENTE el servidor/dashboard anterior y vuelve a iniciarlo.
pause
