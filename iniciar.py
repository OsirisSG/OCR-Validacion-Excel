"""Arranque portable del dashboard con diagnóstico de CPU/GPU."""

from __future__ import annotations

import argparse
import importlib.util
import platform
import sys
import threading
import webbrowser


def diagnostico() -> dict:
    """Devuelve capacidad del equipo sin instalar ni modificar el entorno."""
    modulos = ("fastapi", "uvicorn", "cv2", "numpy", "openpyxl", "yaml")
    faltantes = [modulo for modulo in modulos if importlib.util.find_spec(modulo) is None]
    if not any(importlib.util.find_spec(motor) for motor in ("easyocr", "paddleocr")):
        faltantes.append("easyocr o paddleocr")
    recursos = None
    if not faltantes:
        from recursos import detectar_recursos
        recursos = detectar_recursos("auto")
    return {
        "sistema": platform.system(), "arquitectura": platform.machine(),
        "python": platform.python_version(), "ejecutable": sys.executable,
        "faltantes": faltantes, "recursos": recursos,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inicia el dashboard OCR local.")
    parser.add_argument("--puerto", type=int, default=8000)
    parser.add_argument("--sin-abrir", action="store_true",
                        help="No abrir automáticamente el navegador.")
    parser.add_argument("--solo-diagnostico", action="store_true")
    args = parser.parse_args()
    info = diagnostico()
    print(f"Sistema: {info['sistema']} {info['arquitectura']}")
    print(f"Python: {info['python']} ({info['ejecutable']})")
    if sys.version_info < (3, 10):
        print("ERROR: se requiere Python 3.10 o posterior (recomendado: 3.12).")
        return 2
    if info["faltantes"]:
        print("ERROR: faltan dependencias: " + ", ".join(info["faltantes"]))
        print(f"Instálalas con: {sys.executable} -m pip install -r requirements.txt")
        return 2
    recursos = info["recursos"] or {}
    print("Procesamiento elegido: " + str(recursos.get("seleccionado", "cpu")).upper())
    print(str(recursos.get("motivo", "")))
    if recursos.get("warning"):
        print("ADVERTENCIA: " + recursos["warning"])
    if args.solo_diagnostico:
        return 0
    if not 1 <= args.puerto <= 65535:
        print("ERROR: el puerto debe estar entre 1 y 65535.")
        return 2
    from dashboard.backend.app import app
    import uvicorn

    url = f"http://127.0.0.1:{args.puerto}"
    print(f"Dashboard: {url}")
    if not args.sin_abrir:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=args.puerto, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
