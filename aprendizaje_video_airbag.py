"""Aprendizaje supervisado de video para detección de airbag (V15.3).

La lógica tiene dos rutas:
1. Si el nombre del video identifica la cámara (DETAIL/FRONTAL/LATERAL/SCHEIBE),
   reutiliza ejemplos confirmados de esa misma vista.
2. Si el nombre no ayuda, compara el primer cuadro con referencias aprendidas y
   reutiliza la zona de la toma visualmente más parecida. Cuando hay suficientes
   puntos ORB, la zona se alinea mediante una transformación afín para tolerar
   pequeños desplazamientos de cámara.

Las cajas se guardan normalizadas (0..1) para no depender de una resolución fija.

V15.3 añade un dataset incremental: cada confirmación manual guarda una secuencia
de cuadros alrededor del nacimiento del airbag y extrae métricas del evento. Esas
métricas se reutilizan para calibrar la sensibilidad por tipo de cámara.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from configuracion import RAIZ_PROYECTO
from utilidades import firma_video
from utilidades.persistencia import escribir_json_seguro

RUTA_APRENDIZAJE = RAIZ_PROYECTO / ".aprendizaje" / "zonas_video_airbag.json"
RUTA_REFERENCIAS = RAIZ_PROYECTO / ".aprendizaje" / "video_airbag_referencias"
RUTA_DATASET = RAIZ_PROYECTO / ".aprendizaje" / "video_airbag_dataset.json"
RUTA_DATASET_FRAMES = RAIZ_PROYECTO / ".aprendizaje" / "video_airbag_dataset"

_ALIAS_CAMARA = {
    "DETAIL": "DETAIL",
    "DETALLE": "DETAIL",
    "CLOSEUP": "DETAIL",
    "CLOSE-UP": "DETAIL",
    "FRONTAL": "FRONTAL",
    "FRONT": "FRONTAL",
    "FRONTVIEW": "FRONTAL",
    "FRONT-VIEW": "FRONTAL",
    "LATERAL": "LATERAL",
    "SIDE": "LATERAL",
    "SIDEVIEW": "LATERAL",
    "SIDE-VIEW": "LATERAL",
    "SCHEIBE": "SCHEIBE",
    "WINDSHIELD": "SCHEIBE",
    "WINDSCREEN": "SCHEIBE",
    "PARABRISAS": "SCHEIBE",
}


def _ruta_guardable(ruta: Path) -> str:
    """Relativa al proyecto cuando es posible (portable); absoluta si no."""
    try:
        return str(Path(ruta).relative_to(RAIZ_PROYECTO).as_posix())
    except ValueError:
        return str(Path(ruta).as_posix())


def _leer_json(ruta: Path, defecto: Any) -> Any:
    try:
        if ruta.is_file():
            return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return defecto


def _guardar_json(ruta: Path, data: Any) -> None:
    escribir_json_seguro(ruta, data, lanzar=False, compacto=False)


def cargar_aprendizajes() -> dict:
    data = _leer_json(RUTA_APRENDIZAJE, {"version": 2, "perfiles": []})
    if not isinstance(data, dict):
        data = {"version": 2, "perfiles": []}
    perfiles = data.get("perfiles")
    if not isinstance(perfiles, list):
        perfiles = []
    data["version"] = 2
    data["perfiles"] = [p for p in perfiles if isinstance(p, dict)]
    return data


def version_aprendizajes(ruta_video: str | Path | None = None) -> str:
    """Versión barata para invalidar caché al cambiar zonas o ejemplos.

    V15.7.1: con ``ruta_video`` y un nombre de cámara reconocible, sólo cuentan
    las zonas/ejemplos de esa cámara y los del propio video. Enseñar una zona
    LATERAL ya no obliga a reanalizar todos los DETAIL, FRONTAL y SCHEIBE.
    Sin cámara reconocible se usa todo, porque la zona puede heredarse por
    similitud de cualquier perfil.
    """
    tipo = inferir_tipo_camara_nombre(Path(str(ruta_video)).name) if ruta_video else None
    if not tipo:
        partes: list[str] = []
        for etiqueta, ruta in (("zonas", RUTA_APRENDIZAJE), ("eventos", RUTA_DATASET)):
            try:
                st = ruta.stat()
                partes.append(f"{etiqueta}:{st.st_size}:{st.st_mtime_ns}")
            except OSError:
                partes.append(f"{etiqueta}:sin-datos")
        return "|".join(partes)
    try:
        ident = firma_video.identidad(ruta_video)
    except OSError:
        ident = {}
    def relevante(registro: dict) -> bool:
        return (str(registro.get("tipo_camara") or "").upper() == tipo or
                bool(ident and firma_video.coincide(registro, ident, "firma_video")))
    zonas = [p for p in cargar_aprendizajes().get("perfiles", []) if relevante(p)]
    eventos = [e for e in cargar_dataset_eventos().get("ejemplos", []) if relevante(e)]
    contenido = json.dumps({"tipo": tipo, "zonas": zonas,
                            "eventos": [(e.get("id"), e.get("frame_evento"), e.get("features"))
                                        for e in eventos]},
                           sort_keys=True, default=str)
    return f"{tipo}:" + hashlib.sha256(contenido.encode()).hexdigest()[:24]


def inferir_tipo_camara_nombre(nombre: str | Path) -> str | None:
    stem = Path(str(nombre)).stem.upper()
    # Conserva guiones internos pero separa prefijos numéricos y otros signos.
    tokens = [t for t in re.split(r"[_\s.]+", stem) if t]
    for token in tokens:
        limpio = re.sub(r"[^A-ZÄÖÜ-]", "", token)
        if limpio in _ALIAS_CAMARA:
            return _ALIAS_CAMARA[limpio]
    # Respaldo para nombres como 50FRONTAL o TEST-LATERAL-01.
    compacto = re.sub(r"[^A-Z]", "", stem)
    for alias, canonico in _ALIAS_CAMARA.items():
        clave = re.sub(r"[^A-Z]", "", alias)
        if clave and clave in compacto:
            return canonico
    return None


def _bbox_normalizada(bbox: list[float] | tuple[float, ...]) -> list[float]:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise ValueError("La zona debe contener x1, y1, x2, y2 normalizados.")
    vals = [float(x) for x in bbox]
    if not all(math.isfinite(x) for x in vals):
        raise ValueError("La zona contiene coordenadas inválidas.")
    x1, y1, x2, y2 = vals
    x1, x2 = sorted((max(0.0, min(1.0, x1)), max(0.0, min(1.0, x2))))
    y1, y2 = sorted((max(0.0, min(1.0, y1)), max(0.0, min(1.0, y2))))
    if x2 - x1 < 0.015 or y2 - y1 < 0.015:
        raise ValueError("La zona aprendida es demasiado pequeña.")
    return [round(x1, 6), round(y1, 6), round(x2, 6), round(y2, 6)]


def _firma_archivo(ruta: str | Path) -> str:
    """Firma por contenido (ver ``utilidades.firma_video``)."""
    return firma_video.firma_contenido(ruta)


def _leer_frame(ruta_video: str | Path, indice: int = 0) -> np.ndarray:
    cap = cv2.VideoCapture(str(ruta_video))
    try:
        if not cap.isOpened():
            raise ValueError("No se pudo abrir el video para guardar la referencia visual.")
        if indice > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(indice))
        ok, frame = cap.read()
        if not ok or frame is None:
            raise ValueError("No se pudo leer el cuadro de referencia del video.")
        return frame
    finally:
        cap.release()


def guardar_zona_aprendida(ruta_video: str | Path, bbox_norm: list[float], *,
                            tipo_camara: str | None = None,
                            frame_index: int | None = None,
                            usuario: str = "dashboard") -> dict:
    """Guarda/actualiza el ejemplo supervisado correspondiente a este video."""
    ruta = Path(ruta_video).resolve()
    bbox = _bbox_normalizada(bbox_norm)
    tipo = (str(tipo_camara or "").strip().upper() or inferir_tipo_camara_nombre(ruta.name) or "SIN_ETIQUETA")
    firma = _firma_archivo(ruta)
    # Para reconocer la posición de cámara se guarda el primer cuadro, no el de
    # despliegue, de forma que la bolsa no contamine la identidad visual.
    frame_ref = _leer_frame(ruta, 0)
    alto, ancho = frame_ref.shape[:2]
    RUTA_REFERENCIAS.mkdir(parents=True, exist_ok=True)
    perfil_id = hashlib.sha256(f"{firma}|{tipo}".encode()).hexdigest()[:20]
    ruta_ref = RUTA_REFERENCIAS / f"{perfil_id}.jpg"
    # Limita tamaño sin cambiar la geometría relativa.
    ref = frame_ref
    if ancho > 960:
        escala = 960.0 / ancho
        ref = cv2.resize(ref, (960, max(1, int(round(alto * escala)))), interpolation=cv2.INTER_AREA)
    ok = cv2.imwrite(str(ruta_ref), ref, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise ValueError("No se pudo guardar la referencia visual de la cámara.")
    ahora = datetime.now().isoformat(timespec="seconds")
    perfil = {
        "id": perfil_id,
        "tipo_camara": tipo,
        "nombre_origen": ruta.name,
        "firma_video": firma,
        "firma_legacy": firma_video.firma_legacy(ruta),
        "ruta_video": str(ruta),
        "tamano": int(ruta.stat().st_size),
        "bbox_norm": bbox,
        "frame_confirmado": None if frame_index is None else int(frame_index),
        "referencia": _ruta_guardable(ruta_ref),
        "ancho_origen": int(ancho),
        "alto_origen": int(alto),
        "usuario": usuario,
        "actualizado_en": ahora,
    }
    data = cargar_aprendizajes()
    # Reenseñar el mismo video reemplaza el ejemplo anterior; no acumula basura.
    ident = firma_video.identidad(ruta)
    anteriores = [p for p in data["perfiles"] if not firma_video.coincide(p, ident, "firma_video")]
    anteriores.append(perfil)
    data["perfiles"] = anteriores[-500:]
    data["actualizado_en"] = ahora
    _guardar_json(RUTA_APRENDIZAJE, data)
    return perfil


def _ruta_referencia(perfil: dict) -> Path | None:
    valor = perfil.get("referencia")
    if not valor:
        return None
    p = Path(str(valor))
    if not p.is_absolute():
        p = RAIZ_PROYECTO / p
    return p if p.is_file() else None


def _normalizar_para_features(frame: np.ndarray, max_ancho: int = 640) -> np.ndarray:
    if frame is None or frame.size == 0:
        return np.zeros((1, 1), dtype=np.uint8)
    gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame.copy()
    h, w = gris.shape[:2]
    if w > max_ancho:
        escala = max_ancho / float(w)
        gris = cv2.resize(gris, (max_ancho, max(1, int(round(h * escala)))), interpolation=cv2.INTER_AREA)
    # Las bandas de texto/timestamp no deben dominar la similitud de la escena.
    hh, ww = gris.shape[:2]
    mascara = np.zeros_like(gris)
    y1, y2 = int(hh * 0.10), int(hh * 0.90)
    x1, x2 = int(ww * 0.03), int(ww * 0.97)
    mascara[y1:max(y1 + 1, y2), x1:max(x1 + 1, x2)] = 255
    return cv2.bitwise_and(gris, mascara)


def _comparar_referencia(ref_color: np.ndarray, actual_color: np.ndarray) -> dict:
    ref = _normalizar_para_features(ref_color)
    actual = _normalizar_para_features(actual_color)
    orb = cv2.ORB_create(nfeatures=1200, scaleFactor=1.2, nlevels=8, fastThreshold=12)
    kp1, des1 = orb.detectAndCompute(ref, None)
    kp2, des2 = orb.detectAndCompute(actual, None)
    buenos = []
    if des1 is not None and des2 is not None and len(kp1) >= 4 and len(kp2) >= 4:
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        try:
            pares = matcher.knnMatch(des1, des2, k=2)
        except cv2.error:
            pares = []
        for par in pares:
            if len(par) < 2:
                continue
            m, n = par
            if m.distance < 0.76 * n.distance:
                buenos.append(m)
    afin = None
    inlier_ratio = 0.0
    if len(buenos) >= 6:
        src = np.float32([kp1[m.queryIdx].pt for m in buenos]).reshape(-1, 1, 2)
        dst = np.float32([kp2[m.trainIdx].pt for m in buenos]).reshape(-1, 1, 2)
        try:
            afin, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                                                        ransacReprojThreshold=3.5,
                                                        maxIters=2000, confidence=0.99)
            if inliers is not None and len(inliers):
                inlier_ratio = float(np.mean(inliers.ravel() > 0))
        except cv2.error:
            afin = None
    # Histograma aporta una pista cuando hay pocos puntos (escenas oscuras/lisas).
    hist1 = cv2.calcHist([ref], [0], None, [32], [0, 256])
    hist2 = cv2.calcHist([actual], [0], None, [32], [0, 256])
    cv2.normalize(hist1, hist1)
    cv2.normalize(hist2, hist2)
    hist_corr = float(cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL))
    hist01 = max(0.0, min(1.0, (hist_corr + 1.0) / 2.0))
    base = max(1, min(len(kp1), len(kp2)))
    tasa_buenos = len(buenos) / base
    orb_score = max(0.0, min(1.0, tasa_buenos / 0.12))
    score = 0.58 * orb_score + 0.27 * inlier_ratio + 0.15 * hist01
    return {
        "score": round(float(max(0.0, min(1.0, score))), 4),
        "buenos": len(buenos),
        "inlier_ratio": round(inlier_ratio, 4),
        "afin": afin,
        "ref_shape": ref.shape[:2],
        "actual_shape": actual.shape[:2],
    }


def _transformar_bbox(bbox_norm: list[float], comparacion: dict) -> tuple[list[float], bool]:
    bbox = _bbox_normalizada(bbox_norm)
    afin = comparacion.get("afin")
    if afin is None:
        return bbox, False
    rh, rw = comparacion.get("ref_shape") or (1, 1)
    ah, aw = comparacion.get("actual_shape") or (1, 1)
    x1, y1, x2, y2 = bbox
    puntos = np.float32([
        [x1 * rw, y1 * rh], [x2 * rw, y1 * rh],
        [x2 * rw, y2 * rh], [x1 * rw, y2 * rh],
    ]).reshape(-1, 1, 2)
    try:
        trans = cv2.transform(puntos, np.asarray(afin, dtype=np.float32)).reshape(-1, 2)
    except cv2.error:
        return bbox, False
    xs = np.clip(trans[:, 0] / max(1.0, float(aw)), 0.0, 1.0)
    ys = np.clip(trans[:, 1] / max(1.0, float(ah)), 0.0, 1.0)
    nueva = [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]
    area0 = max(1e-9, (x2 - x1) * (y2 - y1))
    area1 = max(0.0, (nueva[2] - nueva[0]) * (nueva[3] - nueva[1]))
    ratio = area1 / area0
    if area1 < 0.0005 or not (0.35 <= ratio <= 2.8):
        return bbox, False
    try:
        return _bbox_normalizada(nueva), True
    except ValueError:
        return bbox, False


def _bbox_a_porcentajes(bbox: list[float] | None) -> dict | None:
    """X/Y/W/H en % para mostrar la ROI bloqueada tal como la ve el usuario."""
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    x1, y1, x2, y2 = [float(v) for v in bbox]
    return {"x": round(x1 * 100, 1), "y": round(y1 * 100, 1),
            "w": round((x2 - x1) * 100, 1), "h": round((y2 - y1) * 100, 1)}


def _bbox_casi_igual(a: list[float] | None, b: list[float] | None, tol: float = 0.003) -> bool:
    if not a or not b:
        return False
    return all(abs(float(x) - float(y)) <= tol for x, y in zip(a, b))


def _zona_manual_bloqueada(perfil: dict, tipo_nombre: str | None, total: int,
                            fuente: str, similitud: float | None = None) -> dict:
    bbox = list(perfil["bbox_norm"])
    return {
        "activa": True,
        "bloqueada": True,
        "bbox_norm": bbox,
        "bbox_original_norm": bbox,
        "bbox_sugerida_norm": None,
        "porcentajes": _bbox_a_porcentajes(bbox),
        "tipo_camara": tipo_nombre or perfil.get("tipo_camara"),
        "tipo_camara_perfil": perfil.get("tipo_camara"),
        "fuente": fuente,
        "confianza": 1.0,
        "similitud_visual": None if similitud is None else round(float(similitud), 4),
        "perfil_id": perfil.get("id"),
        "referencia_nombre": perfil.get("nombre_origen"),
        "transformada_por_similitud": False,
        "autoalineacion_activa": False,
        "total_aprendizajes": total,
    }


def seleccionar_zona_aprendida(ruta_video: str | Path, primer_frame: np.ndarray,
                                config: dict | None = None) -> dict:
    """Selecciona la mejor zona aprendida para un video nuevo.

    V15.7: una ROI dibujada por el usuario queda BLOQUEADA. Si el video es el
    mismo donde se dibujó, se usa la caja exacta, sin transformación alguna.
    En videos que heredan la zona de otro ejemplo, la caja también se usa tal
    cual salvo que ``autoalineacion_roi`` esté activado; el ajuste ORB se
    devuelve sólo como ``bbox_sugerida_norm`` para que el usuario decida.
    """
    cfg = (config or {}).get("video_airbag", config or {}) if isinstance(config, dict) else {}
    autoalinear = bool(cfg.get("autoalineacion_roi", False))
    data = cargar_aprendizajes()
    perfiles = [p for p in data.get("perfiles", []) if p.get("bbox_norm") and _ruta_referencia(p)]
    tipo_nombre = inferir_tipo_camara_nombre(Path(ruta_video).name)
    if not perfiles:
        return {"activa": False, "tipo_camara": tipo_nombre, "fuente": "sin_aprendizaje",
                "bbox_norm": None, "confianza": 0.0, "total_aprendizajes": 0}

    # 1) La ROI que el usuario dibujó en ESTE video manda siempre.
    try:
        ident = firma_video.identidad(ruta_video)
    except OSError:
        ident = None
    # También reconoce zonas guardadas antes de copiar/mover la carpeta.
    propio = firma_video.buscar(perfiles, ident, "firma_video") if ident else None
    if propio is not None:
        return _zona_manual_bloqueada(propio, tipo_nombre, len(perfiles), "manual_bloqueada")

    por_tipo = [p for p in perfiles if tipo_nombre and str(p.get("tipo_camara")) == tipo_nombre]
    candidatos = por_tipo or perfiles
    resultados = []
    for perfil in candidatos:
        ruta_ref = _ruta_referencia(perfil)
        if not ruta_ref:
            continue
        ref = cv2.imread(str(ruta_ref), cv2.IMREAD_COLOR)
        if ref is None:
            continue
        comp = _comparar_referencia(ref, primer_frame)
        resultados.append((float(comp["score"]), perfil, comp))
    if not resultados:
        return {"activa": False, "tipo_camara": tipo_nombre, "fuente": "sin_referencias_validas",
                "bbox_norm": None, "confianza": 0.0, "total_aprendizajes": len(perfiles)}
    resultados.sort(key=lambda x: (x[0], str(x[1].get("actualizado_en") or "")), reverse=True)

    # 2) Mismo archivo copiado o movido (la firma cambia con la ruta): mismo
    # nombre y escena prácticamente idéntica también cuenta como ROI propia.
    nombre = Path(ruta_video).name.casefold()
    for score_i, perfil_i, _ in resultados:
        if str(perfil_i.get("nombre_origen") or "").casefold() == nombre and score_i >= 0.85:
            return _zona_manual_bloqueada(perfil_i, tipo_nombre, len(perfiles),
                                          "manual_bloqueada_mismo_video", score_i)

    score, perfil, comp = resultados[0]
    exacto_nombre = bool(por_tipo)
    minimo = float(cfg.get("similitud_minima_zona", 0.34))
    minimo_nombre = float(cfg.get("similitud_minima_zona_nombre", 0.18))
    # V15.4: el nombre de archivo es una pista fuerte, no permiso para aplicar
    # una ROI de otra escena a ciegas. DETAIL/FRONTAL/LATERAL/SCHEIBE sólo
    # reutilizan una zona si la imagen conserva un mínimo de semejanza visual.
    if (not exacto_nombre and score < minimo) or (exacto_nombre and score < minimo_nombre):
        return {
            "activa": False, "tipo_camara": tipo_nombre,
            "fuente": ("nombre_no_coincide_visualmente" if exacto_nombre else "similitud_insuficiente"),
            "bbox_norm": None, "confianza": round(score, 4),
            "perfil_candidato": perfil.get("id"), "tipo_candidato": perfil.get("tipo_camara"),
            "total_aprendizajes": len(perfiles),
        }
    original = list(perfil["bbox_norm"])
    sugerida, transformada = _transformar_bbox(original, comp)
    if not transformada or _bbox_casi_igual(sugerida, original):
        sugerida = None
    bbox = sugerida if (autoalinear and sugerida) else original
    fuente = "nombre_archivo" if exacto_nombre else "similitud_visual"
    confianza = max(score, 0.78 if exacto_nombre else 0.0)
    return {
        "activa": True,
        "bloqueada": not (autoalinear and sugerida),
        "bbox_norm": bbox,
        "bbox_original_norm": original,
        "bbox_sugerida_norm": sugerida,
        "porcentajes": _bbox_a_porcentajes(bbox),
        "tipo_camara": tipo_nombre or perfil.get("tipo_camara"),
        "tipo_camara_perfil": perfil.get("tipo_camara"),
        "fuente": fuente,
        "confianza": round(float(min(1.0, confianza)), 4),
        "similitud_visual": round(score, 4),
        "perfil_id": perfil.get("id"),
        "referencia_nombre": perfil.get("nombre_origen"),
        "transformada_por_similitud": bool(autoalinear and sugerida),
        "autoalineacion_activa": autoalinear,
        "matches_orb": int(comp.get("buenos") or 0),
        "total_aprendizajes": len(perfiles),
    }


def cargar_dataset_eventos() -> dict:
    data = _leer_json(RUTA_DATASET, {"version": 1, "ejemplos": []})
    if not isinstance(data, dict):
        data = {"version": 1, "ejemplos": []}
    ejemplos = data.get("ejemplos")
    if not isinstance(ejemplos, list):
        ejemplos = []
    data["version"] = 1
    data["ejemplos"] = [x for x in ejemplos if isinstance(x, dict)]
    return data


def _recortar_norm(frame: np.ndarray, bbox_norm: list[float] | None) -> np.ndarray:
    if frame is None or frame.size == 0:
        raise ValueError("Cuadro vacío al generar aprendizaje de video.")
    h, w = frame.shape[:2]
    if not bbox_norm:
        return frame
    bbox = _bbox_normalizada(bbox_norm)
    x1, y1, x2, y2 = bbox
    xa = max(0, min(w - 1, int(round(x1 * w))))
    ya = max(0, min(h - 1, int(round(y1 * h))))
    xb = max(xa + 1, min(w, int(round(x2 * w))))
    yb = max(ya + 1, min(h, int(round(y2 * h))))
    return frame[ya:yb, xa:xb]


def _gris_reducido(frame: np.ndarray, max_ancho: int = 640) -> np.ndarray:
    gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame.copy()
    h, w = gris.shape[:2]
    if w > max_ancho:
        escala = max_ancho / float(w)
        gris = cv2.resize(gris, (max_ancho, max(1, int(round(h * escala)))), interpolation=cv2.INTER_AREA)
    return gris


def _mayor_componente(mascara: np.ndarray) -> int:
    if not np.any(mascara):
        return 0
    n, _, stats, _ = cv2.connectedComponentsWithStats(mascara.astype(np.uint8), connectivity=8)
    return int(np.max(stats[1:, cv2.CC_STAT_AREA])) if n > 1 else 0


def _features_evento(frames: dict[int, np.ndarray], frame_evento: int,
                      bbox_norm: list[float] | None) -> dict:
    """Extrae una huella simple y explicable del nacimiento confirmado."""
    offsets_pre = [o for o in (-3, -2, -1) if frame_evento + o in frames]
    pre = [_gris_reducido(_recortar_norm(frames[frame_evento + o], bbox_norm)).astype(np.float32)
           for o in offsets_pre]
    if not pre:
        # Si el evento está al principio, usa el primer cuadro disponible como referencia.
        primero = min(frames)
        pre = [_gris_reducido(_recortar_norm(frames[primero], bbox_norm)).astype(np.float32)]
    baseline = np.median(np.stack(pre, axis=0), axis=0).astype(np.uint8)
    actual = _gris_reducido(_recortar_norm(frames[frame_evento], bbox_norm))
    if actual.shape != baseline.shape:
        actual = cv2.resize(actual, (baseline.shape[1], baseline.shape[0]), interpolation=cv2.INTER_AREA)
    delta = actual.astype(np.int16) - baseline.astype(np.int16)
    delta = delta - int(round(float(np.median(delta))))
    mascara = ((actual >= 135) & (delta >= 18)).astype(np.uint8)
    total = max(1, int(mascara.size))
    pix = int(np.count_nonzero(mascara))
    comp = _mayor_componente(mascara)
    diff_media = float(np.mean(cv2.absdiff(actual, baseline)))
    e0 = cv2.Canny(baseline, 45, 120)
    e1 = cv2.Canny(actual, 45, 120)
    dil = cv2.dilate((e0 > 0).astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1)
    nuevos_bordes = int(np.count_nonzero((e1 > 0) & (dil == 0)))

    areas = []
    for off in (0, 1, 2, 3):
        idx = frame_evento + off
        if idx not in frames:
            continue
        g = _gris_reducido(_recortar_norm(frames[idx], bbox_norm))
        if g.shape != baseline.shape:
            g = cv2.resize(g, (baseline.shape[1], baseline.shape[0]), interpolation=cv2.INTER_AREA)
        d = g.astype(np.int16) - baseline.astype(np.int16)
        d = d - int(round(float(np.median(d))))
        m = ((g >= 135) & (d >= 18)).astype(np.uint8)
        areas.append(_mayor_componente(m))
    area0 = max(1, areas[0] if areas else comp)
    crecimiento = (max(areas) / float(area0)) if areas else 1.0
    return {
        "fraccion_blanco_evento": round(pix / total, 8),
        "fraccion_componente_evento": round(comp / total, 8),
        "diff_media_evento": round(diff_media, 5),
        "fraccion_borde_nuevo": round(nuevos_bordes / total, 8),
        "crecimiento_3f": round(float(crecimiento), 4),
        "area_componente_px": int(comp),
        "pixeles_blanco_nuevo": int(pix),
    }


def _bbox_evento_normalizada(bbox: list[float] | tuple[float, ...]) -> list[float]:
    """Normaliza una microzona del nacimiento sin forzar el 1.5 % de una ROI general."""
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise ValueError("La zona exacta de nacimiento debe contener x1, y1, x2, y2.")
    vals = [float(x) for x in bbox]
    if not all(math.isfinite(x) for x in vals):
        raise ValueError("La zona exacta contiene coordenadas inválidas.")
    x1, y1, x2, y2 = vals
    x1, x2 = sorted((max(0.0, min(1.0, x1)), max(0.0, min(1.0, x2))))
    y1, y2 = sorted((max(0.0, min(1.0, y1)), max(0.0, min(1.0, y2))))
    # Una microzona puede ser pequeña, pero nunca un punto de uno o dos píxeles.
    if x2 - x1 < 0.002 or y2 - y1 < 0.002:
        raise ValueError("La zona exacta de nacimiento es demasiado pequeña.")
    return [round(x1, 6), round(y1, 6), round(x2, 6), round(y2, 6)]


def localizar_nacimiento_evento(ruta_video: str | Path, *, frame_index: int,
                                 bbox_norm: list[float] | None = None,
                                 ventana_pre: int = 3, ventana_post: int = 2) -> dict:
    """Localiza la primera microzona que cambia dentro de una ROI supervisada.

    La ROI grande sigue siendo el *dónde mirar*. Esta función intenta encontrar
    dentro de ella el *punto donde nace* la bolsa usando el cuadro confirmado,
    una mediana de F-3..F-1 y persistencia en los cuadros posteriores. El
    resultado no se guarda automáticamente: el dashboard puede mostrarlo y el
    usuario puede corregirlo antes de entrenar.
    """
    ruta = Path(ruta_video).resolve()
    frame_index = max(0, int(frame_index))
    roi = _bbox_normalizada(bbox_norm) if bbox_norm else [0.0, 0.0, 1.0, 1.0]
    ventana_pre = max(1, min(6, int(ventana_pre)))
    ventana_post = max(0, min(4, int(ventana_post)))

    cap = cv2.VideoCapture(str(ruta))
    if not cap.isOpened():
        raise ValueError("No se pudo abrir el video para afinar la zona de nacimiento.")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    indices = list(range(max(0, frame_index - ventana_pre), frame_index + ventana_post + 1))
    if total > 0:
        indices = [i for i in indices if i < total]
    frames: dict[int, np.ndarray] = {}
    try:
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, fr = cap.read()
            if ok and fr is not None:
                frames[idx] = fr
    finally:
        cap.release()
    if frame_index not in frames:
        raise ValueError("No se pudo leer el cuadro indicado para localizar el nacimiento.")

    h0, w0 = frames[frame_index].shape[:2]
    x1n, y1n, x2n, y2n = roi
    xa = max(0, min(w0 - 1, int(round(x1n * w0))))
    ya = max(0, min(h0 - 1, int(round(y1n * h0))))
    xb = max(xa + 1, min(w0, int(round(x2n * w0))))
    yb = max(ya + 1, min(h0, int(round(y2n * h0))))
    rw, rh = xb - xa, yb - ya

    def gris_roi(fr: np.ndarray) -> np.ndarray:
        crop = fr[ya:yb, xa:xb]
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop.copy()
        # Mantiene precisión espacial pero evita operar sobre millones de píxeles.
        if g.shape[1] > 1200:
            esc = 1200.0 / g.shape[1]
            g = cv2.resize(g, (1200, max(1, int(round(g.shape[0] * esc)))), interpolation=cv2.INTER_AREA)
        return g

    actual = gris_roi(frames[frame_index])
    pre_indices = [i for i in range(frame_index - ventana_pre, frame_index) if i in frames]
    if pre_indices:
        pre = [gris_roi(frames[i]).astype(np.float32) for i in pre_indices]
        base = np.median(np.stack(pre, axis=0), axis=0).astype(np.uint8)
    else:
        # Si el evento está al principio del archivo, usa el cuadro más antiguo
        # disponible. Se reporta menor confianza porque no hay historia real.
        primero = min(frames)
        base = gris_roi(frames[primero])
    if actual.shape != base.shape:
        actual = cv2.resize(actual, (base.shape[1], base.shape[0]), interpolation=cv2.INTER_AREA)

    delta = actual.astype(np.int16) - base.astype(np.int16)
    # Quita cambios globales de exposición/iluminación.
    delta = delta - int(round(float(np.median(delta))))
    positivo = np.maximum(delta, 0).astype(np.uint8)
    p97 = float(np.percentile(positivo, 97.0)) if positivo.size else 0.0
    p995 = float(np.percentile(positivo, 99.5)) if positivo.size else 0.0
    umbral_delta = int(max(10, min(34, max(p97 * 0.60, p995 * 0.33))))
    umbral_blanco = int(max(105, min(175, float(np.percentile(actual, 70.0)) + 18.0)))

    mascara = ((delta >= umbral_delta) & (actual >= umbral_blanco)).astype(np.uint8)
    # Incluye bordes muy nuevos aun cuando el primer filamento todavía no sea
    # completamente blanco. Esto ayuda en el cuadro exacto de nacimiento.
    e0 = cv2.Canny(base, 40, 115)
    e1 = cv2.Canny(actual, 40, 115)
    viejos_dilatados = cv2.dilate((e0 > 0).astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1)
    borde_nuevo = ((e1 > 0) & (viejos_dilatados == 0) & (delta >= max(7, umbral_delta - 4))).astype(np.uint8)
    mascara = np.maximum(mascara, borde_nuevo)
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)

    # La persistencia/growth en F+1/F+2 reduce falsos positivos por ruido.
    futuras = np.zeros_like(mascara)
    for idx in range(frame_index + 1, frame_index + ventana_post + 1):
        if idx not in frames:
            continue
        g = gris_roi(frames[idx])
        if g.shape != base.shape:
            g = cv2.resize(g, (base.shape[1], base.shape[0]), interpolation=cv2.INTER_AREA)
        d = g.astype(np.int16) - base.astype(np.int16)
        d = d - int(round(float(np.median(d))))
        m = ((d >= max(8, umbral_delta - 3)) & (g >= max(100, umbral_blanco - 10))).astype(np.uint8)
        futuras = np.maximum(futuras, cv2.dilate(m, np.ones((5, 5), np.uint8), iterations=1))

    n, labels, stats, centros = cv2.connectedComponentsWithStats(mascara, connectivity=8)
    mejor = None
    area_roi = max(1, int(mascara.size))
    min_area = max(3, int(round(area_roi * 0.00003)))
    for lab in range(1, n):
        x, y, w, h, area = [int(v) for v in stats[lab]]
        if area < min_area:
            continue
        comp = labels == lab
        media_delta = float(np.mean(np.maximum(delta[comp], 0))) if np.any(comp) else 0.0
        media_luz = float(np.mean(actual[comp])) if np.any(comp) else 0.0
        persist = float(np.mean(futuras[comp] > 0)) if np.any(comp) and np.any(futuras) else 0.0
        # Favorece señales pequeñas pero claras/persistentes; no premia sólo área.
        score = (math.sqrt(max(1.0, float(area))) * (0.55 + media_delta / 42.0) *
                 (0.70 + media_luz / 510.0) * (1.0 + 0.65 * persist))
        cand = (score, x, y, w, h, area, media_delta, media_luz, persist, centros[lab])
        if mejor is None or cand[0] > mejor[0]:
            mejor = cand

    metodo = "componente_temporal"
    if mejor is None:
        # Respaldo conservador: centra una microzona sobre el píxel con mayor
        # incremento. Así el usuario siempre recibe una sugerencia editable.
        yy, xx = np.unravel_index(int(np.argmax(positivo)), positivo.shape)
        lado = max(10, int(round(min(actual.shape[:2]) * 0.08)))
        x = max(0, xx - lado // 2); y = max(0, yy - lado // 2)
        w = min(actual.shape[1] - x, lado); h = min(actual.shape[0] - y, lado)
        area = max(1, w * h)
        media_delta = float(positivo[yy, xx])
        media_luz = float(actual[yy, xx])
        persist = 0.0
        mejor = (0.0, x, y, w, h, area, media_delta, media_luz, persist, np.array([xx, yy], dtype=float))
        metodo = "maximo_delta_respaldo"

    score, x, y, w, h, area, media_delta, media_luz, persist, centro = mejor
    # Añade contexto alrededor del primer fragmento sin volver a la ROI grande.
    margen_x = max(8, int(round(w * 0.45)))
    margen_y = max(8, int(round(h * 0.45)))
    ex1 = max(0, x - margen_x); ey1 = max(0, y - margen_y)
    ex2 = min(actual.shape[1], x + w + margen_x); ey2 = min(actual.shape[0], y + h + margen_y)
    # Tamaño mínimo práctico para que los recortes de F-3..F+3 tengan contexto.
    min_w = max(12, int(round(actual.shape[1] * 0.025)))
    min_h = max(12, int(round(actual.shape[0] * 0.025)))
    if ex2 - ex1 < min_w:
        cx = (ex1 + ex2) / 2.0; ex1 = int(max(0, round(cx - min_w / 2))); ex2 = min(actual.shape[1], ex1 + min_w); ex1 = max(0, ex2 - min_w)
    if ey2 - ey1 < min_h:
        cy = (ey1 + ey2) / 2.0; ey1 = int(max(0, round(cy - min_h / 2))); ey2 = min(actual.shape[0], ey1 + min_h); ey1 = max(0, ey2 - min_h)

    # Convierte de la imagen reducida a coordenadas del ROI original y después
    # a coordenadas normalizadas del frame completo.
    sx = rw / float(max(1, actual.shape[1])); sy = rh / float(max(1, actual.shape[0]))
    fx1 = (xa + ex1 * sx) / float(w0); fy1 = (ya + ey1 * sy) / float(h0)
    fx2 = (xa + ex2 * sx) / float(w0); fy2 = (ya + ey2 * sy) / float(h0)
    bbox_evento = _bbox_evento_normalizada([fx1, fy1, fx2, fy2])
    cx_full = (xa + float(centro[0]) * sx) / float(w0)
    cy_full = (ya + float(centro[1]) * sy) / float(h0)

    area_frac = float(area) / float(area_roi)
    confianza = 0.20 + min(0.42, media_delta / 85.0) + min(0.18, persist * 0.18)
    if pre_indices:
        confianza += 0.10
    if metodo == "maximo_delta_respaldo":
        confianza = min(confianza, 0.42)
    confianza = max(0.05, min(0.98, confianza))
    return {
        "bbox_norm": bbox_evento,
        "punto_norm": [round(max(0.0, min(1.0, cx_full)), 6), round(max(0.0, min(1.0, cy_full)), 6)],
        "bbox_contexto_norm": roi,
        "frame_index": int(frame_index),
        "metodo": metodo,
        "confianza": round(float(confianza), 4),
        "delta_media": round(float(media_delta), 3),
        "luz_media": round(float(media_luz), 3),
        "persistencia": round(float(persist), 4),
        "fraccion_area_roi": round(area_frac, 8),
        "pixeles_componente": int(area),
        "umbral_delta": int(umbral_delta),
        "umbral_blanco": int(umbral_blanco),
    }


def guardar_ejemplo_evento(ruta_video: str | Path, *, frame_index: int,
                            bbox_norm: list[float] | None = None,
                            bbox_evento_norm: list[float] | None = None,
                            tipo_camara: str | None = None,
                            tiempo_ms: float | None = None,
                            fps: float | None = None,
                            usuario: str = "dashboard", ventana: int = 3) -> dict:
    """Guarda F-3..F+3 de una confirmación manual y sus métricas.

    Reconfirmar el mismo archivo reemplaza su ejemplo previo. Así el dataset
    mejora con las correcciones sin acumular etiquetas contradictorias.
    """
    ruta = Path(ruta_video).resolve()
    firma = _firma_archivo(ruta)
    tipo = (str(tipo_camara or "").strip().upper() or inferir_tipo_camara_nombre(ruta.name) or "SIN_ETIQUETA")
    frame_index = max(0, int(frame_index))
    ventana = max(1, min(6, int(ventana)))
    cap = cv2.VideoCapture(str(ruta))
    if not cap.isOpened():
        raise ValueError("No se pudo abrir el video para guardar el ejemplo confirmado.")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    frames: dict[int, np.ndarray] = {}
    inicio = max(0, frame_index - ventana)
    fin = (min(total - 1, frame_index + ventana) if total else frame_index + ventana)
    try:
        for idx in range(inicio, fin + 1):
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if ok and frame is not None:
                frames[idx] = frame
    finally:
        cap.release()
    if frame_index not in frames:
        raise ValueError("No se pudo leer el cuadro confirmado para aprendizaje.")

    bbox = _bbox_normalizada(bbox_norm) if bbox_norm else None
    bbox_evento = _bbox_evento_normalizada(bbox_evento_norm) if bbox_evento_norm else None
    ejemplo_id = hashlib.sha256(firma.encode()).hexdigest()[:20]
    carpeta = RUTA_DATASET_FRAMES / ejemplo_id
    carpeta.mkdir(parents=True, exist_ok=True)
    secuencia = []
    for idx, frame in sorted(frames.items()):
        offset = idx - frame_index
        # Para el dataset visual se conserva la microzona exacta cuando fue
        # confirmada; la ROI grande queda separada como contexto del detector.
        recorte = _recortar_norm(frame, bbox_evento or bbox)
        destino = carpeta / f"{offset:+d}.jpg"
        if recorte.shape[1] > 960:
            escala = 960.0 / recorte.shape[1]
            recorte = cv2.resize(recorte, (960, max(1, int(round(recorte.shape[0] * escala)))), interpolation=cv2.INTER_AREA)
        ok = cv2.imwrite(str(destino), recorte, [cv2.IMWRITE_JPEG_QUALITY, 88])
        if ok:
            secuencia.append({
                "offset": int(offset), "frame": int(idx),
                "ruta": _ruta_guardable(destino),
                "clase": ("primer_con_airbag" if offset == 0 else
                           "sin_airbag" if offset < 0 else "despliegue_posterior"),
            })
    # Las métricas principales se calculan sobre la ROI general porque son las
    # que calibran el detector. Además guardamos una huella de la microzona para
    # aprender específicamente cómo aparece el primer fragmento de bolsa.
    features = _features_evento(frames, frame_index, bbox)
    features_nacimiento = _features_evento(frames, frame_index, bbox_evento) if bbox_evento else None
    ahora = datetime.now().isoformat(timespec="seconds")
    ejemplo = {
        "id": ejemplo_id,
        "firma_video": firma,
        "firma_legacy": firma_video.firma_legacy(ruta),
        "tamano": int(ruta.stat().st_size),
        "nombre_origen": ruta.name,
        "ruta_video": str(ruta),
        "tipo_camara": tipo,
        "frame_evento": int(frame_index),
        "tiempo_ms": None if tiempo_ms is None else round(float(tiempo_ms), 3),
        "fps": None if fps is None else float(fps),
        "bbox_norm": bbox,
        "bbox_evento_norm": bbox_evento,
        "features": features,
        "features_nacimiento": features_nacimiento,
        "secuencia": secuencia,
        "usuario": usuario,
        "confirmado_en": ahora,
    }
    data = cargar_dataset_eventos()
    ident = firma_video.identidad(ruta)
    data["ejemplos"] = [x for x in data["ejemplos"] if not firma_video.coincide(x, ident, "firma_video")]
    data["ejemplos"].append(ejemplo)
    data["ejemplos"] = data["ejemplos"][-1000:]
    data["actualizado_en"] = ahora
    _guardar_json(RUTA_DATASET, data)
    return ejemplo


def perfil_evento_aprendido(tipo_camara: str | None) -> dict:
    """Resume ejemplos confirmados de una vista para calibrar el detector."""
    data = cargar_dataset_eventos()
    tipo = str(tipo_camara or "").strip().upper()
    ejemplos = [x for x in data.get("ejemplos", [])
                if (not tipo or str(x.get("tipo_camara") or "").upper() == tipo)]
    valores: dict[str, list[float]] = {
        "fraccion_blanco_evento": [], "fraccion_componente_evento": [],
        "diff_media_evento": [], "fraccion_borde_nuevo": [], "crecimiento_3f": [],
    }
    for e in ejemplos:
        f = e.get("features") or {}
        for k in valores:
            try:
                v = float(f.get(k))
            except (TypeError, ValueError):
                continue
            if math.isfinite(v):
                valores[k].append(v)
    def med(k: str) -> float | None:
        arr = sorted(valores[k])
        if not arr:
            return None
        n = len(arr)
        return float(arr[n // 2]) if n % 2 else float((arr[n // 2 - 1] + arr[n // 2]) / 2.0)
    return {
        "tipo_camara": tipo or None,
        "ejemplos": len(ejemplos),
        "mediana_fraccion_blanco": med("fraccion_blanco_evento"),
        "mediana_fraccion_componente": med("fraccion_componente_evento"),
        "mediana_diff": med("diff_media_evento"),
        "mediana_borde_nuevo": med("fraccion_borde_nuevo"),
        "mediana_crecimiento_3f": med("crecimiento_3f"),
        "actualizado_en": data.get("actualizado_en"),
    }


def resumen_aprendizajes() -> dict:
    data = cargar_aprendizajes()
    conteo: dict[str, int] = {}
    for p in data.get("perfiles", []):
        tipo = str(p.get("tipo_camara") or "SIN_ETIQUETA")
        conteo[tipo] = conteo.get(tipo, 0) + 1
    dataset = cargar_dataset_eventos()
    eventos: dict[str, int] = {}
    for e in dataset.get("ejemplos", []):
        tipo = str(e.get("tipo_camara") or "SIN_ETIQUETA")
        eventos[tipo] = eventos.get(tipo, 0) + 1
    return {
        "total": sum(conteo.values()), "por_tipo": conteo,
        "eventos_confirmados": sum(eventos.values()), "eventos_por_tipo": eventos,
        "actualizado_en": max(str(data.get("actualizado_en") or ""),
                              str(dataset.get("actualizado_en") or "")) or None,
    }
