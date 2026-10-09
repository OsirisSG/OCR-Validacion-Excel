"""Umbrales elegidos explícitamente por el usuario, sin modificar el YAML base."""
from __future__ import annotations

from datetime import datetime
import json
import math
from pathlib import Path
import threading

from utilidades.persistencia import escribir_json_seguro

RUTA_CRITERIOS = Path(__file__).resolve().parent / ".aprendizaje" / "criterios_usuario.json"
_lock = threading.RLock()


def _validar(verde_max, amarillo_max):
    if (isinstance(verde_max, bool) or isinstance(amarillo_max, bool)
            or not isinstance(verde_max, (int, float))
            or not isinstance(amarillo_max, (int, float))
            or not math.isfinite(verde_max) or not math.isfinite(amarillo_max)
            or not 0 <= verde_max < amarillo_max):
        raise ValueError("Los límites deben ser finitos: 0 ≤ verde < amarillo; rojo queda por encima.")
    return float(verde_max), float(amarillo_max)


def cargar_criterios_usuario() -> dict | None:
    with _lock:
        if not RUTA_CRITERIOS.exists():
            return None
        datos = json.loads(RUTA_CRITERIOS.read_text(encoding="utf-8"))
        if not isinstance(datos, dict) or datos.get("version") != 1:
            raise ValueError("El archivo de umbrales tiene un formato no válido.")
        actual = datos.get("apertura")
        if not isinstance(actual, dict):
            raise ValueError("Faltan los límites de apertura confirmados.")
        _validar(actual.get("verde_max"), actual.get("amarillo_max"))
        return actual


def reglas_apertura(actual: dict) -> dict:
    verde, amarillo = _validar(actual.get("verde_max"), actual.get("amarillo_max"))
    # Verde se evalúa primero; el límite inferior compartido del intervalo
    # amarillo no crea un solapamiento observable ni huecos entre decimales.
    return {"verde": f"<= {verde:g}", "amarillo": f"{verde:g}-{amarillo:g}",
            "rojo": f"> {amarillo:g}"}


def guardar_criterios_apertura(verde_max, amarillo_max, usuario: str) -> dict:
    verde, amarillo = _validar(verde_max, amarillo_max)
    actual = {"verde_max": verde, "amarillo_max": amarillo, "usuario": usuario,
              "confirmado_en": datetime.now().isoformat(timespec="microseconds")}
    with _lock:
        previo = cargar_criterios_usuario()
        historial = []
        if RUTA_CRITERIOS.exists():
            datos = json.loads(RUTA_CRITERIOS.read_text(encoding="utf-8"))
            historial = list(datos.get("historial") or [])
        if previo:
            historial.append(previo)
        escribir_json_seguro(RUTA_CRITERIOS,
            {"version": 1, "apertura": actual, "historial": historial}, lanzar=True)
    return actual
