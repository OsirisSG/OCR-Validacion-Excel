#!/bin/sh
cd "$(dirname "$0")" || exit 1
python3 instalar.py --perfil completo
estado=$?
printf '\nPresiona Enter para cerrar...'
read -r _
exit "$estado"
