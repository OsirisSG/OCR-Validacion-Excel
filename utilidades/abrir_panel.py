"""P50 · Al terminar la corrida se abre solo el formulario de dudas (petición del usuario 12/11).

Se lanza `panel_confirmacion.py` en su propia ventana (Windows: consola nueva) con el libro recién
generado y la validación de esa corrida, en el primer puerto libre desde el configurado, y se abre
el navegador. Nunca bloquea ni tumba la corrida: cualquier fallo se devuelve como aviso.
Se desactiva con `empresarial.panel_dudas.abrir_al_terminar: false` o la variable OCR_SIN_PANEL=1.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _puerto_libre(desde: int, intentos: int = 12) -> int | None:
    for puerto in range(desde, desde + intentos):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", puerto)) != 0:
                return puerto
    return None


def abrir_panel_dudas(libro, validacion_json, config: dict | None = None, *, lanzar=None,
                      abrir_navegador=None) -> dict:
    cfg = (((config or {}).get("empresarial") or {}).get("panel_dudas")) or {}
    if not cfg.get("abrir_al_terminar", True):
        return {"abierto": False, "motivo": "desactivado en config.yaml"}
    if os.environ.get("OCR_SIN_PANEL") or (os.environ.get("PYTEST_CURRENT_TEST") and lanzar is None):
        return {"abierto": False, "motivo": "desactivado en este entorno"}
    libro = Path(str(libro or ""))
    validacion_json = Path(str(validacion_json or RAIZ / "validacion_resultados.json"))
    if not libro.is_file() or not validacion_json.is_file():
        return {"abierto": False, "motivo": f"falta el libro o la validación ({libro.name}, {validacion_json.name})"}
    puerto = _puerto_libre(int(cfg.get("puerto", 8099)))
    if puerto is None:
        return {"abierto": False, "motivo": "no hay puerto libre para el formulario"}
    orden = [sys.executable, "-X", "utf8", str(RAIZ / "panel_confirmacion.py"), "--libro", str(libro),
             "--validacion", str(validacion_json), "--hoja", "Versuchsmatrix", "--puerto", str(puerto)]
    try:
        if lanzar is not None:
            lanzar(orden)
        else:
            banderas = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if os.name == "nt" else 0
            subprocess.Popen(orden, cwd=str(RAIZ), creationflags=banderas,
                             start_new_session=os.name != "nt")
        url = f"http://127.0.0.1:{puerto}"
        abrir = abrir_navegador or webbrowser.open
        threading.Timer(3.0, lambda: abrir(url)).start()
        return {"abierto": True, "url": url, "libro": str(libro), "puerto": puerto}
    except Exception as exc:                                  # noqa: BLE001
        return {"abierto": False, "motivo": f"{type(exc).__name__}: {exc}"[:200]}
