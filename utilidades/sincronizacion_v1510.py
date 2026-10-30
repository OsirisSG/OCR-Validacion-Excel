"""Contratos de tiempo físico V15.10: validación estricta; no inventa offsets."""
from __future__ import annotations
import math

VERSION = "15.10.1"


def numero_positivo(valor):
    try:
        if isinstance(valor, bool):
            return None
        v = float(valor)
        return v if math.isfinite(v) and v > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def tiempo_fisico(*, frame: int, fps_adquisicion: float, frame0: int = 0,
                  t0_ms: float = 0.0, incertidumbre_reloj_ms: float = 0.0) -> dict:
    """Tiempo con intervalo de cuantización de un frame (sin subframe ficticio)."""
    fps = numero_positivo(fps_adquisicion)
    if fps is None or not isinstance(frame, int) or isinstance(frame, bool) or frame < frame0:
        return {"valido": False, "motivo": "fps_o_frame_no_validado", "version": VERSION}
    if not math.isfinite(t0_ms) or not math.isfinite(incertidumbre_reloj_ms) or incertidumbre_reloj_ms < 0:
        return {"valido": False, "motivo": "referencia_temporal_invalida", "version": VERSION}
    resolucion = 1000.0 / fps
    t = t0_ms + (frame - frame0) * resolucion
    incertidumbre = resolucion / 2.0 + incertidumbre_reloj_ms
    return {"valido": True, "tiempo_ms": t, "resolucion_ms": resolucion,
            "intervalo_ms": [t - incertidumbre, t + incertidumbre],
            "incertidumbre_ms": incertidumbre, "version": VERSION}


def alinear_camara(t_local: float, calibracion: dict | None) -> dict:
    """Rechaza alineaciones derivadas de las propias aperturas o no verificadas."""
    c = calibracion or {}
    if c.get("validada") is not True or c.get("origen") not in {"disparador", "overlay_verificado", "reloj_comun"}:
        return {"valido": False, "motivo": "sincronizacion_no_verificada"}
    a = numero_positivo(c.get("factor"))
    try:
        b = float(c["offset_ms"])
    except (ValueError, TypeError, KeyError):
        return {"valido": False, "motivo": "offset_no_disponible"}
    if a is None or not math.isfinite(b) or not math.isfinite(t_local):
        return {"valido": False, "motivo": "transformacion_temporal_invalida"}
    try:
        inci=float(c.get("incertidumbre_ms", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return {"valido": False, "motivo": "incertidumbre_invalida"}
    if not math.isfinite(inci) or inci<0:
        return {"valido": False, "motivo": "incertidumbre_invalida"}
    return {"valido": True, "tiempo_global_ms": a*t_local+b,
            "incertidumbre_alineacion_ms": inci,
            "origen": c["origen"]}
