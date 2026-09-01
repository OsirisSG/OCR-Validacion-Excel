#!/bin/sh
set -eu
PROYECTO_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$PROYECTO_DIR"
if [ -x ".venv/bin/python" ]; then
  PYTHON_OCR=".venv/bin/python"
elif [ -x ".venv_dashboard/bin/python" ]; then
  PYTHON_OCR=".venv_dashboard/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_OCR="python3"
else
  PYTHON_OCR="python"
fi
exec "$PYTHON_OCR" iniciar.py "$@"
