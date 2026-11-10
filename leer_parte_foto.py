"""Lee el número moldeado en **una** foto. Se llama en subproceso desde `leer_parte_de_tablero.py`.

Uso: python3 leer_parte_foto.py <ruta de la foto>
"""
import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utilidades import codigos_modulo as CM  # noqa: E402
from utilidades.grabado_punteado import leer_parte_moldeada  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({}))
        return 1
    imagen = cv2.imread(sys.argv[1])
    if imagen is None:
        print(json.dumps({}))
        return 1
    motor = CM.motor_compartido()
    lectura = leer_parte_moldeada(imagen, motor, maximo=4)
    print(json.dumps(lectura or {}, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
