@echo off
setlocal
cd /d "%~dp0"

echo.
echo Iniciando empaquetado seguro del proyecto OCR...
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0CREAR_ZIP_OCR_LIMPIO_V2.ps1"

if errorlevel 1 (
    echo.
    echo El proceso termino con un error.
    pause
    exit /b 1
)

endlocal
