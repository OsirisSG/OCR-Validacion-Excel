@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo.
echo === V-Matrix: diagnostico de version, apertura y semaforo [V2] ===
echo SOLO LECTURA. No instala parches ni cambia resultados.
echo Carpeta donde esta el BAT: %~dp0
echo.
REM IMPORTANTE: no pasar "%%~dp0" como argumento: termina en barra invertida.
REM Python detecta la carpeta del proyecto a partir de su propia ubicacion.
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0DIAGNOSTICO_SEMAFORO_V16.py"
  goto :final
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0DIAGNOSTICO_SEMAFORO_V16.py"
  goto :final
)
where python >nul 2>nul
if not errorlevel 1 (
  python "%~dp0DIAGNOSTICO_SEMAFORO_V16.py"
  goto :final
)
echo ERROR: No se encuentra Python en este equipo.
exit /b 3
:final
set "CODIGO=%ERRORLEVEL%"
echo.
echo Codigo del diagnostico: %CODIGO%
pause
exit /b %CODIGO%
