#!/bin/bash
set -e
cd "$(dirname "$0")"
exec python3 instalar.py --perfil completo
