@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0iniciar_ocr.ps1" %*
set "OCR_EXIT=%ERRORLEVEL%"
if not "%OCR_EXIT%"=="0" pause
exit /b %OCR_EXIT%
