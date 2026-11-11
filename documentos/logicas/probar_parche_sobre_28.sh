#!/usr/bin/env bash
# Comprueba que el parche se puede aplicar sobre un proyecto **realmente en V16.0.28**.
# Uso: bash probar_parche_sobre_28.sh [ruta_del_paquete]
set -e
PAQUETE="${1:-/home/user/vmatrix/instalador_v16_0_46}"
BASE28="/home/user/vmatrix/instalador_v16_0_28"
TRABAJO="/home/user/vmatrix/trabajo"
PRUEBA="/tmp/prueba_parche_28"
rm -rf "$PRUEBA" && mkdir -p "$PRUEBA"
git -C "$TRABAJO" archive 0f0d84c | tar -x -C "$PRUEBA"
echo "1) proyecto base sin lotes → instalar V16.0.28"
python3 "$BASE28/evidencia/ensayo_instalador.py" "$BASE28" instalar "$PRUEBA" | head -1
echo "2) diagnóstico del parche sobre 28 (tiene que decir INSTALABLE)"
python3 "$PAQUETE/evidencia/ensayo_instalador.py" "$PAQUETE" diagnosticar "$PRUEBA" | head -1
echo "3) instalar el parche"
python3 "$PAQUETE/evidencia/ensayo_instalador.py" "$PAQUETE" instalar "$PRUEBA" | head -1
echo "4) verificar"
python3 "$PAQUETE/evidencia/ensayo_instalador.py" "$PAQUETE" verificar "$PRUEBA" | tail -1
echo "5) reinstalar (tiene que decir «Ya instalada»)"
python3 "$PAQUETE/evidencia/ensayo_instalador.py" "$PAQUETE" instalar "$PRUEBA" | head -1
