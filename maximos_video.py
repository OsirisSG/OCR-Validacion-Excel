"""Confirmaciones humanas del máximo despliegue visible, separadas de apertura.

No entrena el OCR ni estima volumen/inflado completo. El archivo de feedback
es independiente de resultados/checkpoints y se reutiliza por SHA-256 completo
del vídeo, incluso si cambia de carpeta. Nunca se identifica sólo por nombre.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import threading

from configuracion import RAIZ_PROYECTO
from utilidades.persistencia import escribir_json_seguro

RUTA_MAXIMOS = RAIZ_PROYECTO / ".aprendizaje" / "maximos_video.json"
_lock = threading.RLock()
_firmas: dict[tuple, str] = {}
_cache: dict = {"marca": None, "datos": None}


def _firma_completa(ruta: str | Path) -> str:
    archivo = Path(ruta).resolve()
    stat = archivo.stat()
    clave = (str(archivo), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    with _lock:
        if clave not in _firmas:
            digest = hashlib.sha256()
            with archivo.open("rb") as stream:
                for bloque in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(bloque)
            if len(_firmas) > 1024:
                _firmas.clear()
            _firmas[clave] = "sha256-" + digest.hexdigest()
        return _firmas[clave]


def _leer() -> dict:
    with _lock:
        if not RUTA_MAXIMOS.exists():
            return {"version": 1, "revisiones": {}, "historial": []}
        stat = RUTA_MAXIMOS.stat()
        marca = (str(RUTA_MAXIMOS), stat.st_mtime_ns, stat.st_size)
        if _cache["marca"] != marca:
            datos = json.loads(RUTA_MAXIMOS.read_text(encoding="utf-8"))
            if not isinstance(datos, dict) or not isinstance(datos.get("revisiones"), dict):
                raise ValueError("El feedback de máximo despliegue no tiene un formato válido.")
            _cache.update(marca=marca, datos=datos)
        return deepcopy(_cache["datos"])


def revision_maximo(ruta: str | Path) -> dict | None:
    datos = _leer()
    if not datos["revisiones"]:
        return None
    return deepcopy(datos["revisiones"].get(_firma_completa(ruta)))


def guardar_maximo(ruta: str | Path, *, frame_index: int, tiempo_resuelto: dict,
                   usuario: str, case_key: str | None = None) -> dict:
    """Guarda sólo después de validar; un fallo conserva el feedback previo."""
    if isinstance(frame_index, bool) or not isinstance(frame_index, int) or frame_index < 0:
        raise ValueError("El máximo requiere un cuadro entero no negativo.")
    tiempo = tiempo_resuelto.get("tiempo_ms")
    fps = tiempo_resuelto.get("fps")
    if (isinstance(tiempo, bool) or tiempo is None or not math.isfinite(float(tiempo))
            or float(tiempo) < 0 or fps is None or not math.isfinite(float(fps)) or float(fps) <= 0):
        raise ValueError("Falta un tiempo finito y una tasa real de adquisición válida.")
    firma = _firma_completa(ruta)
    revision = {
        "estado": "confirmado", "requiere_revision": False,
        "frame_index": frame_index, "tiempo_ms": float(tiempo), "fps": float(fps),
        "fuente_tiempo": tiempo_resuelto.get("fuente_tiempo"),
        "resolucion_nativa_ms": 1000.0 / float(fps),
        "overlay_validado": bool(tiempo_resuelto.get("overlay_valido")),
        "timestamp_inicial_ms": tiempo_resuelto.get("timestamp_inicial_ms"),
        "metodo": "maximo_visible_confirmado_manual", "usuario": usuario,
        "confirmado_en": datetime.now().isoformat(timespec="microseconds"),
        "ruta_video": str(ruta), "case_key": case_key, "firma": firma,
        "advertencias": [tiempo_resuelto["advertencia"]] if tiempo_resuelto.get("advertencia") else [],
    }
    with _lock:
        datos = _leer()
        datos.setdefault("historial", []).append(deepcopy(revision))
        datos["revisiones"][firma] = revision
        escribir_json_seguro(RUTA_MAXIMOS, datos, lanzar=True)
        _cache.update(marca=None, datos=None)
    return deepcopy(revision)


def incorporar_maximos(fila: dict) -> None:
    """Proyecta feedback durable en una fila sin tocar otros tiempos ni el OCR.

    Si el vídeo no está disponible (p.ej. un lote Windows abierto en Mac), se
    conserva la evidencia ya incluida, pero se revisan contradicciones explícitas
    de sus metadatos. Si sí está y cambió, se marca caducada.
    Un fallo de lectura nunca borra una confirmación ni detiene el pipeline.
    """
    videos = fila.get("videos") or []
    if not videos:
        return
    try:
        registros = _leer()["revisiones"]
        for video in videos:
            ruta = Path(video.get("ruta") or "")
            previa = video.get("despliegue_maximo") or {}
            if ruta.is_file() and (registros or previa.get("firma")):
                firma = _firma_completa(ruta)
                revision = registros.get(firma)
                if revision:
                    video["despliegue_maximo"] = deepcopy(revision)
                elif previa.get("firma") and previa["firma"] != firma:
                    video["despliegue_maximo"] = {**previa, "estado": "archivo_modificado",
                        "requiere_revision": True, "advertencias": ["El vídeo cambió desde la confirmación."]}
            # Offline impide comprobar bytes, no invalida los metadatos
            # disponibles: una apertura descartada o posterior al máximo sigue
            # siendo contradictoria y no puede exportarse como confirmada.
            actual = video.get("despliegue_maximo") or {}
            apertura = video.get("revision_manual") or {}
            motivo, estado = None, None
            if actual.get("estado") == "confirmado":
                if apertura.get("estado") in {"sin_evento", "pendiente"}:
                    estado, motivo = "revisar_apertura", "La apertura dejó de estar confirmada; revisa también el máximo."
                from video_airbag import fps_real_item
                fps_actual = fps_real_item(video)
                fps_guardado = actual.get("fps")
                if (fps_actual and fps_guardado and not math.isclose(
                        float(fps_actual), float(fps_guardado), rel_tol=1e-6, abs_tol=1e-6)):
                    estado, motivo = "revisar_origen_temporal", "Cambió la tasa real de grabación; confirma otra vez el máximo."
                t0 = video.get("overlay_timestamp_inicial_ms")
                t0_previo = actual.get("timestamp_inicial_ms")
                if (t0 is not None and t0_previo is not None
                        and math.isfinite(float(t0)) and math.isfinite(float(t0_previo))
                        and not math.isclose(float(t0), float(t0_previo), abs_tol=1e-6)):
                    estado, motivo = "revisar_origen_temporal", "Cambió el origen temporal del vídeo; confirma otra vez el máximo."
                if motivo:
                    video["despliegue_maximo"] = {**actual, "estado": estado,
                        "requiere_revision": True, "advertencias": [motivo]}
                    continue
            # Corregir apertura después de confirmar máximo no puede dejar un
            # máximo anterior a ella como si siguiera siendo un resultado válido.
            if (actual.get("estado") == "confirmado" and apertura.get("estado") == "confirmado"
                    and apertura.get("frame_index") is not None
                    and actual["frame_index"] < apertura["frame_index"]):
                video["despliegue_maximo"] = {**actual, "estado": "revisar_orden_temporal",
                    "requiere_revision": True,
                    "advertencias": ["La apertura corregida queda después del máximo; revísalo."]}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        fila["advertencia_maximos_video"] = f"Se conservan los máximos previos: {exc}"
