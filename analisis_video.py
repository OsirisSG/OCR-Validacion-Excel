"""OBSOLETO desde V15.1: el pipeline y el dashboard usan ``video_airbag.py``.

Se conserva sólo por compatibilidad con pruebas antiguas; no lo importes en
código nuevo. Puede borrarse junto con ``pruebas/test_v15_video_apertura.py``.

Análisis local de videos de despliegue de bolsa de aire (V15.0).

Detecta el primer cambio visual compatible con apertura y calcula el tiempo del
onset. Si la cadencia nativa no alcanza 0.1 ms, puede reportar una estimación
sub-frame cuantizada a 0.1 ms, pero conserva y expone la resolución física del
video para no presentar una precisión inexistente como exacta.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Iterable

VIDEO_EXTENSIONS = {".avi", ".mp4", ".mov", ".mkv", ".wmv", ".m4v"}
VIDEO_DIR_NAMES = {"VIDEO", "VIDEOS"}


def _video_cfg(config: dict | None) -> dict:
    cfg = dict(((config or {}).get("video_apertura") or {}))
    return {
        "activar": bool(cfg.get("activar", True)),
        "max_videos_por_caso": max(1, int(cfg.get("max_videos_por_caso", 4))),
        "max_duracion_ms": max(50.0, float(cfg.get("max_duracion_ms", 5000.0))),
        "ancho_analisis_px": max(160, int(cfg.get("ancho_analisis_px", 480))),
        "paso_grueso_ms": max(0.1, float(cfg.get("paso_grueso_ms", 2.0))),
        "frames_baseline": max(1, int(cfg.get("frames_baseline", 3))),
        "umbral_diferencia": max(1, int(cfg.get("umbral_diferencia", 22))),
        "umbral_brillo": max(1, int(cfg.get("umbral_brillo", 175))),
        "delta_brillo": max(1, int(cfg.get("delta_brillo", 18))),
        "fraccion_cambio_min": max(0.0001, float(cfg.get("fraccion_cambio_min", 0.006))),
        "fraccion_blanco_min": max(0.00005, float(cfg.get("fraccion_blanco_min", 0.0010))),
        "persistencia_frames": max(1, int(cfg.get("persistencia_frames", 2))),
        "margen_superior": min(0.35, max(0.0, float(cfg.get("margen_superior", 0.08)))),
        "margen_inferior": min(0.35, max(0.0, float(cfg.get("margen_inferior", 0.12)))),
        "margen_lateral": min(0.20, max(0.0, float(cfg.get("margen_lateral", 0.03)))),
        "consenso_minimo": max(1, int(cfg.get("consenso_minimo", 3))),
        "consenso_tolerancia_ms": max(0.1, float(cfg.get("consenso_tolerancia_ms", 0.4))),
        "ocr_timestamp": bool(cfg.get("ocr_timestamp", True)),
    }


def buscar_videos_caso(ruta_caso: str | Path, limite: int = 4) -> list[dict]:
    """Busca videos únicamente dentro de carpetas llamadas VIDEO/VIDEOS."""
    caso = Path(ruta_caso)
    encontrados: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(caso):
        actual = Path(dirpath)
        if actual.name.upper() not in VIDEO_DIR_NAMES:
            continue
        for nombre in sorted(filenames):
            archivo = actual / nombre
            if archivo.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            encontrados.append({
                "id": hashlib.sha256(str(archivo).encode("utf-8")).hexdigest()[:16],
                "nombre": archivo.name,
                "ruta": str(archivo),
                "ruta_relativa": archivo.relative_to(caso).as_posix(),
            })
            if len(encontrados) >= limite:
                return encontrados
        # os.walk seguirá descendiendo; no es dañino, pero evitamos carpetas muy profundas.
        dirnames[:] = []
    return encontrados


def _abrir_video(ruta: Path):
    import cv2
    cap = cv2.VideoCapture(str(ruta))
    if not cap.isOpened():
        raise ValueError("OpenCV no pudo abrir el video; revisa el codec/archivo.")
    return cap


def metadatos_video(ruta: str | Path) -> dict:
    import cv2
    ruta = Path(ruta)
    cap = _abrir_video(ruta)
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        cuadros = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        ancho = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        alto = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    finally:
        cap.release()
    paso_ms = 1000.0 / fps if fps > 0 else None
    return {
        "fps": fps,
        "frames": cuadros,
        "ancho": ancho,
        "alto": alto,
        "duracion_ms": (cuadros * paso_ms if paso_ms else None),
        "resolucion_nativa_ms": paso_ms,
        "soporta_0_1ms_nativo": bool(paso_ms is not None and paso_ms <= 0.1005),
    }


def _preparar_gris(frame, cfg):
    import cv2
    h, w = frame.shape[:2]
    y1 = int(round(h * cfg["margen_superior"]))
    y2 = int(round(h * (1.0 - cfg["margen_inferior"])))
    x1 = int(round(w * cfg["margen_lateral"]))
    x2 = int(round(w * (1.0 - cfg["margen_lateral"])))
    if y2 <= y1 + 4 or x2 <= x1 + 4:
        roi = frame
    else:
        roi = frame[y1:y2, x1:x2]
    ancho_obj = cfg["ancho_analisis_px"]
    if roi.shape[1] > ancho_obj:
        escala = ancho_obj / roi.shape[1]
        roi = cv2.resize(roi, (ancho_obj, max(1, int(round(roi.shape[0] * escala)))),
                         interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)


def _metricas_frame(gris, baseline, cfg):
    import cv2
    import numpy as np
    # Cambio absoluto + aparición de píxeles sensiblemente más brillantes.
    dif = cv2.absdiff(gris, baseline)
    cambio = float(np.mean(dif >= cfg["umbral_diferencia"]))
    delta = gris.astype(np.int16) - baseline.astype(np.int16)
    blanco = float(np.mean((gris >= cfg["umbral_brillo"]) & (delta >= cfg["delta_brillo"])))
    # Dar más peso al material claro de la bolsa, conservando movimiento general como respaldo.
    score = 0.72 * blanco + 0.28 * cambio
    return {"cambio": cambio, "blanco": blanco, "score": score}


def _parsear_tiempo_overlay_detalle(texto: str) -> dict | None:
    t = str(texto or "").replace(",", ".")
    mayus = t.upper()
    patrones = [
        (r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:MS|MSEC|MSECS|MILLISECOND(?:S)?)\b", 1.0),
        (r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:US|µS|ΜS|MICROSECOND(?:S)?)\b", 0.001),
        (r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:SEC|SECS|SECOND(?:S)?|S)\b", 1000.0),
    ]
    for patron, factor in patrones:
        m = re.search(patron, mayus)
        if not m:
            continue
        literal = m.group(1)
        try:
            valor = float(literal) * factor
        except ValueError:
            continue
        if not (0 <= valor <= 100000):
            continue
        decimales = len(literal.split(".", 1)[1]) if "." in literal else 0
        resolucion = factor * (10 ** (-decimales) if decimales else 1.0)
        return {"tiempo_ms": valor, "resolucion_ms": resolucion, "literal": m.group(0)}
    # Algunos equipos imprimen un timecode etiquetado, p. ej. TIME 00:00:00.0063.
    m = re.search(r"(?:TIME|ZEIT|TIEMPO)\s*[:=]?\s*(\d{1,2}):(\d{2}):(\d{2}(?:\.\d+)?)", mayus)
    if m:
        horas, minutos, segundos = int(m.group(1)), int(m.group(2)), float(m.group(3))
        valor = ((horas * 60 + minutos) * 60 + segundos) * 1000.0
        literal_seg = m.group(3)
        decimales = len(literal_seg.split(".", 1)[1]) if "." in literal_seg else 0
        resolucion = 1000.0 * (10 ** (-decimales) if decimales else 1.0)
        return {"tiempo_ms": valor, "resolucion_ms": resolucion, "literal": m.group(0)}
    return None


def _parsear_tiempo_overlay(texto: str) -> float | None:
    detalle = _parsear_tiempo_overlay_detalle(texto)
    return None if detalle is None else float(detalle["tiempo_ms"])


def leer_timestamp_overlay(frame, motor=None) -> dict | None:
    """Lee únicamente bandas superior/inferior y acepta tiempos con unidad explícita."""
    if motor is None:
        return None
    import cv2
    h, w = frame.shape[:2]
    bandas = [
        ("superior", frame[:max(20, int(h * 0.22)), :]),
        ("inferior", frame[max(0, int(h * 0.78)):, :]),
    ]
    mejores = []
    for nombre, banda in bandas:
        if banda.size == 0:
            continue
        escala = 2.0 if w < 1800 else 1.35
        procesada = cv2.resize(banda, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
        try:
            lecturas = motor.leer_texto_completo(procesada)
        except Exception:
            continue
        texto = " ".join(str(x.get("texto") or "") for x in lecturas if x.get("texto"))
        detalle_tiempo = _parsear_tiempo_overlay_detalle(texto)
        if detalle_tiempo is not None:
            confianza = max([float(x.get("confianza") or 0) for x in lecturas] or [0.0])
            mejores.append({"banda": nombre, "texto": texto,
                            "tiempo_ms": detalle_tiempo["tiempo_ms"],
                            "resolucion_ms": detalle_tiempo["resolucion_ms"],
                            "literal": detalle_tiempo["literal"],
                            "confianza": confianza})
    return max(mejores, key=lambda x: x["confianza"], default=None)


def _cuantizar_01(valor: float) -> float:
    return round(round(float(valor) * 10.0) / 10.0, 1)


def analizar_video(ruta: str | Path, config: dict | None = None, motor_ocr=None) -> dict:
    """Detecta el inicio del despliegue y devuelve frame/tiempo/trazabilidad."""
    import cv2
    import numpy as np

    ruta = Path(ruta)
    cfg = _video_cfg(config)
    meta = metadatos_video(ruta)
    fps = meta["fps"]
    if fps <= 0:
        return {**meta, "ruta": str(ruta), "nombre": ruta.name, "estado": "error",
                "error": "El video no reporta FPS válidos."}
    paso_ms = 1000.0 / fps
    max_frames = min(meta["frames"], max(1, int(math.ceil(cfg["max_duracion_ms"] / paso_ms))))
    paso_grueso = max(1, int(round(cfg["paso_grueso_ms"] / paso_ms)))

    cap = _abrir_video(ruta)
    baseline_frames = []
    muestras: list[tuple[int, dict]] = []
    candidato = None
    frame_candidato = None
    try:
        idx = 0
        while idx < max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % paso_grueso != 0:
                idx += 1
                continue
            gris = _preparar_gris(frame, cfg)
            if len(baseline_frames) < cfg["frames_baseline"]:
                baseline_frames.append(gris.astype(np.float32))
                idx += 1
                continue
            baseline = np.median(np.stack(baseline_frames, axis=0), axis=0).astype(np.uint8)
            met = _metricas_frame(gris, baseline, cfg)
            muestras.append((idx, met))
            if (met["cambio"] >= cfg["fraccion_cambio_min"] and
                    met["blanco"] >= cfg["fraccion_blanco_min"]):
                candidato = idx
                frame_candidato = frame.copy()
                break
            idx += 1
    finally:
        cap.release()

    if candidato is None:
        return {**meta, "ruta": str(ruta), "nombre": ruta.name,
                "estado": "sin_apertura_detectada", "tiempo_ms": None,
                "frame_apertura": None, "fuente_tiempo": None,
                "precision_0_1ms": False,
                "nota_precision": "No se detectó un cambio visual persistente compatible con apertura."}

    # Refinamiento cuadro a cuadro alrededor del salto grueso.
    inicio_ref = max(cfg["frames_baseline"], candidato - paso_grueso * 2)
    fin_ref = min(max_frames - 1, candidato + paso_grueso)
    cap = _abrir_video(ruta)
    cap.set(cv2.CAP_PROP_POS_FRAMES, inicio_ref)
    base_ref = None
    # Baseline estable desde el primer frame real.
    cap0 = _abrir_video(ruta)
    bases = []
    try:
        for _ in range(cfg["frames_baseline"]):
            ok, f0 = cap0.read()
            if not ok:
                break
            bases.append(_preparar_gris(f0, cfg).astype(np.float32))
    finally:
        cap0.release()
    if not bases:
        cap.release()
        raise ValueError("No fue posible construir la referencia inicial del video.")
    base_ref = np.median(np.stack(bases, axis=0), axis=0).astype(np.uint8)

    candidatos_ref: list[tuple[int, dict, object]] = []
    try:
        for idx in range(inicio_ref, fin_ref + 1):
            ok, frame = cap.read()
            if not ok:
                break
            met = _metricas_frame(_preparar_gris(frame, cfg), base_ref, cfg)
            candidatos_ref.append((idx, met, frame.copy()))
    finally:
        cap.release()

    onset_pos = None
    persist = cfg["persistencia_frames"]
    for i, (_, met, _) in enumerate(candidatos_ref):
        cumple = (met["cambio"] >= cfg["fraccion_cambio_min"] and
                  met["blanco"] >= cfg["fraccion_blanco_min"])
        if not cumple:
            continue
        ventana = candidatos_ref[i:i + persist]
        if len(ventana) >= persist and all(
            m["cambio"] >= cfg["fraccion_cambio_min"] and m["blanco"] >= cfg["fraccion_blanco_min"]
            for _, m, _ in ventana
        ):
            onset_pos = i
            break
    if onset_pos is None:
        onset_pos = min(range(len(candidatos_ref)), key=lambda i: abs(candidatos_ref[i][0] - candidato))

    frame_idx, met_onset, frame_onset = candidatos_ref[onset_pos]
    prev_idx, prev_met = (candidatos_ref[onset_pos - 1][0], candidatos_ref[onset_pos - 1][1]) if onset_pos > 0 else (max(0, frame_idx - 1), {"score": 0.0})
    # Umbral continuo aproximado para una estimación sub-frame; nunca se etiqueta como exactitud física.
    score_threshold = 0.72 * cfg["fraccion_blanco_min"] + 0.28 * cfg["fraccion_cambio_min"]
    den = max(1e-12, met_onset["score"] - prev_met.get("score", 0.0))
    frac = min(1.0, max(0.0, (score_threshold - prev_met.get("score", 0.0)) / den))
    estimado_ms = (prev_idx + frac) * paso_ms
    frame_ms = frame_idx * paso_ms

    overlay = None
    if cfg["ocr_timestamp"] and motor_ocr is not None:
        overlay = leer_timestamp_overlay(frame_onset, motor_ocr)

    if overlay is not None:
        tiempo = _cuantizar_01(overlay["tiempo_ms"])
        fuente = "timestamp_overlay"
        precision_01 = float(overlay.get("resolucion_ms") or 999) <= 0.1005
        nota = (f"Tiempo leído de la sobreimpresión del video (resolución mostrada "
                f"≈ {float(overlay.get('resolucion_ms') or 0):.4g} ms); confirmar visualmente si el OCR del timestamp es dudoso.")
    elif paso_ms <= 0.1005:
        tiempo = _cuantizar_01(frame_ms)
        fuente = "frames_nativos"
        precision_01 = True
        nota = f"Resolución nativa {paso_ms:.4f} ms/cuadro: permite 0.1 ms por cuadro."
    else:
        tiempo = _cuantizar_01(estimado_ms)
        fuente = "interpolacion_subframe"
        precision_01 = False
        nota = (f"El video aporta {paso_ms:.3f} ms/cuadro. El valor a 0.1 ms es una estimación "
                "sub-frame y debe confirmarse; no equivale a una medición física nativa de 0.1 ms.")

    exceso = max(0.0, met_onset["score"] - score_threshold)
    confianza = min(0.99, 0.55 + exceso / max(score_threshold, 1e-6) * 0.10)
    return {
        **meta,
        "ruta": str(ruta), "nombre": ruta.name,
        "estado": "candidato_apertura",
        "frame_apertura": int(frame_idx),
        "frame_anterior": int(prev_idx),
        "tiempo_frame_ms": round(frame_ms, 4),
        "tiempo_estimado_subframe_ms": _cuantizar_01(estimado_ms),
        "tiempo_ms": tiempo,
        "fuente_tiempo": fuente,
        "precision_0_1ms": precision_01,
        "nota_precision": nota,
        "confianza_evento": round(confianza, 3),
        "metricas_onset": {k: round(float(v), 6) for k, v in met_onset.items()},
        "timestamp_overlay": overlay,
        "revision_manual": None,
    }


def consenso_videos(videos: Iterable[dict], config: dict | None = None) -> dict:
    cfg = _video_cfg(config)
    candidatos = []
    for video in videos:
        rev = video.get("revision_manual") or {}
        if rev.get("estado") == "sin_apertura":
            continue
        tiempo = rev.get("tiempo_ms") if rev.get("estado") == "confirmada" else video.get("tiempo_ms")
        if tiempo is None:
            continue
        candidatos.append({
            "id": video.get("id"), "nombre": video.get("nombre"),
            "tiempo_ms": float(tiempo),
            "manual": rev.get("estado") == "confirmada",
            "precision_0_1ms": bool(video.get("precision_0_1ms")) or rev.get("estado") == "confirmada",
        })
    candidatos.sort(key=lambda x: x["tiempo_ms"])
    mejor: list[dict] = []
    tol = cfg["consenso_tolerancia_ms"]
    for i in range(len(candidatos)):
        grupo = [candidatos[i]]
        for j in range(i + 1, len(candidatos)):
            if candidatos[j]["tiempo_ms"] - candidatos[i]["tiempo_ms"] <= tol + 1e-9:
                grupo.append(candidatos[j])
            else:
                break
        if len(grupo) > len(mejor):
            mejor = grupo
        elif len(grupo) == len(mejor) and grupo:
            if sum(x["manual"] for x in grupo) > sum(x["manual"] for x in mejor):
                mejor = grupo
    if not mejor:
        return {"estado": "sin_datos", "replicas": 0, "tiempo_ms": None,
                "tolerancia_ms": tol, "videos": []}
    tiempo = _cuantizar_01(median([x["tiempo_ms"] for x in mejor]))
    replicas = len(mejor)
    suficiente = replicas >= cfg["consenso_minimo"]
    exacto = suficiente and all(x["precision_0_1ms"] for x in mejor)
    manuales = sum(x["manual"] for x in mejor)
    estado = ("confirmado_manual" if suficiente and manuales >= cfg["consenso_minimo"] else
              "confirmado_automatico" if suficiente and exacto else
              "propuesto_revision" if suficiente else "sin_consenso")
    return {
        "estado": estado,
        "replicas": replicas,
        "minimo_requerido": cfg["consenso_minimo"],
        "tiempo_ms": tiempo if suficiente else None,
        "tolerancia_ms": tol,
        "precision_0_1ms": exacto,
        "confirmaciones_manuales": manuales,
        "videos": mejor,
        "requiere_revision": estado in {"propuesto_revision", "sin_consenso"},
    }


def firma_video(ruta: str | Path, config: dict | None = None) -> str:
    ruta = Path(ruta)
    stat = ruta.stat()
    cfg = _video_cfg(config)
    payload = {
        "ruta": str(ruta.resolve()), "mtime_ns": stat.st_mtime_ns, "size": stat.st_size,
        "cfg": cfg, "algoritmo": "v15-airbag-onset-1",
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def analizar_videos_caso(ruta_caso: str | Path, config: dict | None = None,
                          motor_ocr=None, videos: list[dict] | None = None,
                          cache_path: str | Path | None = None,
                          forzar: bool = False) -> dict:
    cfg = _video_cfg(config)
    inventario = videos or buscar_videos_caso(ruta_caso, cfg["max_videos_por_caso"])
    cache = {"version": 1, "videos": {}}
    ruta_cache = Path(cache_path) if cache_path else None
    if ruta_cache and ruta_cache.is_file():
        try:
            cargado = json.loads(ruta_cache.read_text(encoding="utf-8"))
            if isinstance(cargado, dict):
                cache = cargado
                cache.setdefault("videos", {})
        except (OSError, ValueError, json.JSONDecodeError):
            cache = {"version": 1, "videos": {}}
    resultados = []
    cache_cambio = False
    for video in inventario[:cfg["max_videos_por_caso"]]:
        base = dict(video)
        try:
            firma = firma_video(video["ruta"], config)
            guardado = None if forzar else (cache.get("videos") or {}).get(firma)
            if isinstance(guardado, dict):
                analisis = dict(guardado)
                analisis["desde_cache"] = True
            else:
                analisis = analizar_video(video["ruta"], config, motor_ocr=motor_ocr)
                cache.setdefault("videos", {})[firma] = analisis
                cache_cambio = True
            resultados.append({**base, **analisis})
        except Exception as exc:
            resultados.append({**base, "estado": "error", "error": f"{type(exc).__name__}: {exc}",
                               "tiempo_ms": None, "frame_apertura": None})
    if ruta_cache and cache_cambio:
        try:
            ruta_cache.parent.mkdir(parents=True, exist_ok=True)
            temporal = ruta_cache.with_suffix(ruta_cache.suffix + ".tmp")
            temporal.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            os.replace(temporal, ruta_cache)
        except OSError:
            pass
    for item in resultados:
        item.setdefault("id", hashlib.sha256(str(item.get("ruta")).encode()).hexdigest()[:16])
    return {"videos": resultados, "consenso": consenso_videos(resultados, config)}
