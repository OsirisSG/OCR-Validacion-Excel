"""Sincronización multicámara conservadora para pruebas/validación."""
from __future__ import annotations

import math
from typing import Any

VERSION_SYNC = "sincronizacion-video-v1"


def _fit_lineal(puntos: list[dict[str, Any]]) -> tuple[float, float] | None:
    pares = []
    for p in puntos or []:
        try:
            x = float(p.get("tiempo_video_ms"))
            y = float(p.get("tiempo_referencia_ms"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(x) and math.isfinite(y):
            pares.append((x, y))
    if len(pares) < 2:
        return None
    xs = [x for x, _ in pares]
    ys = [y for _, y in pares]
    xbar = sum(xs) / len(xs)
    ybar = sum(ys) / len(ys)
    den = sum((x - xbar) ** 2 for x in xs)
    if den == 0:
        return None
    a = sum((x - xbar) * (y - ybar) for x, y in pares) / den
    b = ybar - a * xbar
    return a, b


def sincronizar_vistas(vistas: list[dict], tolerancia_ms: float = 0.25) -> dict:
    vistas = vistas if isinstance(vistas, list) else []
    fuentes_no_elegibles: list[str] = []
    tiempos_globales: list[dict] = []
    camaras_vistas: set[str] = set()
    shas: set[str] = set()

    for vista in vistas:
        if not isinstance(vista, dict):
            continue
        camara = str(vista.get("camara_id") or vista.get("id") or "")
        sha = str(vista.get("sha256") or "")
        if camara and camara in camaras_vistas:
            fuentes_no_elegibles.append(f"mas_de_un_clip_por_camara:{camara}")
            continue
        if camara:
            camaras_vistas.add(camara)
        ajuste = _fit_lineal(vista.get("puntos_calibracion") or [])
        if ajuste is None:
            fuentes_no_elegibles.append(f"reloj_no_calibrado:{camara or '?'}")
            continue
        try:
            t_local = float(vista.get("tiempo_video_ms"))
        except (TypeError, ValueError):
            fuentes_no_elegibles.append(f"tiempo_local_invalido:{camara or '?'}")
            continue
        a, b = ajuste
        t_global = a * t_local + b
        if not math.isfinite(t_global):
            fuentes_no_elegibles.append(f"tiempo_global_invalido:{camara or '?'}")
            continue
        if sha and sha in shas:
            fuentes_no_elegibles.append(f"sha_duplicado:{camara or '?'}")
            continue
        if sha:
            shas.add(sha)
        tiempos_globales.append({
            "camara_id": camara,
            "sha256": sha,
            "tiempo_global_ms": round(t_global, 6),
        })

    soporte = len(tiempos_globales)
    consenso = False
    tiempo_ms = None
    intervalo_ms = None
    if soporte >= 3:
        valores = [v["tiempo_global_ms"] for v in tiempos_globales]
        minimo, maximo = min(valores), max(valores)
        consenso = (maximo - minimo) <= max(0.0, float(tolerancia_ms))
        if consenso:
            tiempo_ms = round(sum(valores) / len(valores), 6)
            intervalo_ms = [round(minimo, 6), round(maximo, 6)]

    return {
        "estado": "consenso_sincronizado" if consenso else "propuesta_no_sincronizada",
        "consenso_sincronizado": consenso,
        "soporte_independiente": soporte,
        "tiempo_ms": tiempo_ms,
        "intervalo_ms": intervalo_ms,
        "fuentes_no_elegibles": fuentes_no_elegibles,
        "tiempo_verificado": consenso,
        "auto_confirmable": False,
        "version_sincronizacion": VERSION_SYNC,
    }
