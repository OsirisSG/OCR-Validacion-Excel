"""Umbrales elegidos explícitamente por el usuario, sin modificar el YAML base.

V15.9: además de la preferencia persistida (con historial), se guarda una
instantánea por ejecución que explica con qué rangos se coloreó cada lote:
origen ``predeterminado`` (6/7 ms), ``vigente`` (preferencia guardada) o
``elegido`` (confirmados en el diálogo previo a «Procesar carpeta»).
La instantánea nunca reescribe la preferencia global del usuario.
"""
from __future__ import annotations

from datetime import datetime
import json
import math
from pathlib import Path
import threading

from utilidades.matriz_apertura import (
    AMARILLO_PREDETERMINADO_MS,
    VERDE_PREDETERMINADO_MS,
    criterio_desde_limites,
    limites_predefinidos,
    validar_limites,
)
from utilidades.persistencia import escribir_json_seguro

RUTA_CRITERIOS = Path(__file__).resolve().parent / ".aprendizaje" / "criterios_usuario.json"
RUTA_INSTANTANEAS = Path(__file__).resolve().parent / ".aprendizaje" / "criterios_ejecuciones"
_lock = threading.RLock()

ORIGENES_INSTANTANEA = {"predeterminado", "vigente", "elegido"}


def _validar(verde_max, amarillo_max):
    # Comparte la validación central (finitos, no negativos, 0 ≤ verde < amarillo).
    return validar_limites(verde_max, amarillo_max)


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


def criterios_o_predeterminados() -> dict:
    """Límites vigentes con su origen, sin fallar si no hay preferencia guardada.

    Origen: ``vigente`` si hay criterios del usuario válidos; si no,
    ``predeterminado`` con 6.0 / 7.0 ms (los del proyecto).
    """
    try:
        actual = cargar_criterios_usuario()
    except (OSError, ValueError, TypeError):
        actual = None
    if actual:
        verde, amarillo = _validar(actual.get("verde_max"), actual.get("amarillo_max"))
        return {"verde_max": verde, "amarillo_max": amarillo,
                "origen": "vigente", "usuario": actual.get("usuario"),
                "confirmado_en": actual.get("confirmado_en")}
    verde, amarillo = limites_predefinidos()
    return {"verde_max": verde, "amarillo_max": amarillo, "origen": "predeterminado"}


def reglas_apertura(actual: dict) -> dict:
    verde, amarillo = _validar(actual.get("verde_max"), actual.get("amarillo_max"))
    # Verde se evalúa primero; el límite inferior compartido del intervalo
    # amarillo no crea un solapamiento observable ni huecos entre decimales.
    return criterio_desde_limites(verde, amarillo)


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


def _ruta_instantanea(ejecucion_id: str) -> Path:
    identificador = str(ejecucion_id or "").strip()
    if not identificador or identificador in {".", ".."} or "/" in identificador \
            or "\\" in identificador:
        raise ValueError("El identificador de ejecución no es válido.")
    return RUTA_INSTANTANEAS / f"{identificador}.json"


def guardar_instantanea_ejecucion(ejecucion_id: str, *, verde_max, amarillo_max,
                                  origen: str, usuario: str | None = None) -> dict:
    """Registra los rangos USADOS por una ejecución, sin tocar la preferencia.

    ``origen`` explica de dónde salieron: ``predeterminado`` (6/7 ms),
    ``vigente`` (preferencia guardada) o ``elegido`` (confirmados ahora).
    """
    if origen not in ORIGENES_INSTANTANEA:
        raise ValueError(f"Origen de instantánea no válido: {origen!r}")
    verde, amarillo = _validar(verde_max, amarillo_max)
    instantanea = {
        "version": 1, "ejecucion_id": str(ejecucion_id),
        "verde_max": verde, "amarillo_max": amarillo, "origen": origen,
        "usuario": usuario, "confirmado_en": datetime.now().isoformat(timespec="microseconds"),
    }
    ruta = _ruta_instantanea(ejecucion_id)
    with _lock:
        escribir_json_seguro(ruta, instantanea, lanzar=True)
    return instantanea


def cargar_instantanea_ejecucion(ejecucion_id: str) -> dict | None:
    try:
        ruta = _ruta_instantanea(ejecucion_id)
    except ValueError:
        return None
    with _lock:
        if not ruta.exists():
            return None
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    if not isinstance(datos, dict) or datos.get("version") != 1:
        return None
    try:
        _validar(datos.get("verde_max"), datos.get("amarillo_max"))
    except (ValueError, TypeError):
        return None
    return datos
