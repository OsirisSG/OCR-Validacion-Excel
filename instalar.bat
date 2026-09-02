@echo off
cd /d "%~dp0"
py -3 instalar.py --perfil completo
if errorlevel 1 (
  echo.
  echo La instalacion no termino correctamente. Revisa el mensaje anterior.
)
pause
