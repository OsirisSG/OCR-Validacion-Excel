@echo off
setlocal
cd /d "%~dp0"

echo.
echo ============================================================
echo   V-Matrix - Crear ZIP limpio de diagnostico
echo ============================================================
echo.
echo Carpeta del proyecto:
echo %CD%
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0\CREAR_ZIP_OCR_DIAGNOSTICO_V3.ps1"

if errorlevel 1 (
    echo.
    echo El proceso termino con un error.
    pause
    exit /b 1
)

echo.
echo Proceso terminado correctamente.
pause
endlocal
