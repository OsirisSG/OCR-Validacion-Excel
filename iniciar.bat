@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" iniciar.py %*
) else if exist ".venv_dashboard\Scripts\python.exe" (
  ".venv_dashboard\Scripts\python.exe" iniciar.py %*
) else (
  py -3 iniciar.py %*
)
endlocal
