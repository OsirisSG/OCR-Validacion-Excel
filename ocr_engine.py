"""
ocr_engine.py — Fase 1: motor de OCR local (sin nube, sin APIs externas).

Propósito
---------
`extraer_texto(imagen_path) -> dict` ejecuta el pipeline completo sobre una foto
de etiqueta y retorna tokens con bounding boxes, la posición del QR (si existe)
y la orientación corregida. Toda función retorna estructuras de datos; imprimir
es solo del CLI.

Contrato (Document Maestro §3):
    {
        "tokens": [{"texto": str, "bbox": (x, y, w, h), "confianza": float}, ...],
        "qr_bbox": (x, y, w, h) | None,
        "orientacion_corregida_grados": float,
    }
Campos adicionales (documentados aquí): imagen, motor, confianza_media,
num_lineas_ocr, dimensiones, roi_usado. Son aditivos y no rompen el contrato.

Reglas duras implementadas:
- El QR es un ancla ESPACIAL OPCIONAL: si no hay QR, el OCR corre sobre la
  imagen completa sin error ni degradación (qr_bbox = None).
- El texto NO tiene posición fija: se OCR-ea toda la imagen (o el ROI amplio
  cuando hay QR) y se devuelven cajas por bloque detectado.
- El motor es intercambiable: PaddleOCR (principal) / EasyOCR (fallback),
  elegido por config.yaml; si el principal no está instalado se usa el
  secundario y se reporta en el campo "motor".

Preprocesamiento (orden): carga unicode-safe → detección 180° (por doble pasada
adaptativa, solo si la primera lectura falla) → deskew → binarización adaptativa
→ recorte de ROI (solo si hay QR y queda espacio).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import sys
from pathlib import Path

import cv2
import numpy as np

from configuracion import RAIZ_PROYECTO, cargar_config

# Silencia el chequeo de conectividad de paddlex (modelos ya en caché) ANTES de
# importar paddleocr: evita segundos de espera por ping en cada arranque.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

_MOTORES: dict = {}  # caché de motores por proceso: instanciar OCR es caro


# ---------------------------------------------------------------------------
# Motores de OCR (adaptadores intercambiables)
# ---------------------------------------------------------------------------

class MotorPaddle:
    """Adaptador de PaddleOCR 3.x (PP-OCRv6 det+rec). Ver errores/2026-08-23_paddle_onednn_windows.md:
    en Windows/oneDNN hay que desactivar MKLDNN o la inferencia lanza NotImplementedError."""

    nombre = "paddle"

    def __init__(self, cfg_fase1: dict):
        from paddleocr import PaddleOCR  # import diferido: arranque rápido del resto del pipeline
        logging.getLogger("paddlex").setLevel(logging.WARNING)
        self._ocr = PaddleOCR(
            use_doc_orientation_classify=True,   # corrige 0/90/180/270 a nivel de documento
            use_doc_unwarping=False,
            use_textline_orientation=False,
            lang=cfg_fase1.get("lang", "en"),
            enable_mkldnn=False,  # workaround documentado en errores/
        )

    def leer(self, imagen_bgr: np.ndarray) -> list[dict]:
        resultados = self._ocr.predict(imagen_bgr)
        lineas = []
        for res in resultados or []:
            polys = res.get("dt_polys") or []
            textos = res.get("rec_texts") or []
            scores = res.get("rec_scores") or []
            for poly, texto, score in zip(polys, textos, scores):
                poly = np.asarray(poly, dtype=np.float32)
                # Caja alineada a ejes a partir del cuadrilátero detectado.
                x1, y1 = poly.min(axis=0)
                x2, y2 = poly.max(axis=0)
                lineas.append({
                    "texto": str(texto),
                    "bbox": (int(x1), int(y1), int(x2 - x1), int(y2 - y1)),
                    "confianza": float(score),
                })
        return lineas


class MotorEasyOCR:
    """Adaptador de EasyOCR (motor de respaldo). Requiere easyocr instalado."""

    nombre = "easyocr"

    def __init__(self, cfg_fase1: dict):
        import easyocr  # import diferido
        self._reader = easyocr.Reader([cfg_fase1.get("lang", "en")], gpu=False, verbose=False)

    def leer(self, imagen_bgr: np.ndarray) -> list[dict]:
        lecturas = self._reader.readtext(imagen_bgr, detail=1)
        lineas = []
        for pts, texto, conf in lecturas:
            pts = np.asarray(pts, dtype=np.float32)
            x1, y1 = pts.min(axis=0)
            x2, y2 = pts.max(axis=0)
            lineas.append({
                "texto": str(texto),
                "bbox": (int(x1), int(y1), int(x2 - x1), int(y2 - y1)),
                "confianza": float(conf),
            })
        return lineas


def obtener_motor(config: dict | None = None):
    """Retorna (instancia de motor, config_fase1). Paddle primero, fallback fácil."""
    config = config or cargar_config()
    f1 = config.get("fase1", {})
    for clave in ("motor", "motor_fallback"):
        nombre = f1.get(clave) if clave == "motor" else f1.get("motor_fallback")
        if not nombre:
            continue
        if nombre in _MOTORES:
            return _MOTORES[nombre], f1
        clase = {"paddle": MotorPaddle, "easyocr": MotorEasyOCR}.get(nombre)
        if clase is None:
            continue
        try:
            _MOTORES[nombre] = clase(f1)
            return _MOTORES[nombre], f1
        except Exception as exc:  # ImportError u otro fallo de arranque del motor
            print(f"[ocr_engine] motor '{nombre}' no disponible ({exc}); probando fallback",
                  file=sys.stderr)
    raise RuntimeError("Ningún motor de OCR disponible (paddle/easyocr). Revisa la instalación.")


# ---------------------------------------------------------------------------
# Preprocesamiento
# ---------------------------------------------------------------------------

def cargar_imagen(imagen_path: str | Path) -> np.ndarray:
    """Carga robusta a rutas con caracteres no ASCII (común en Windows es-ES)."""
    datos = np.fromfile(str(imagen_path), dtype=np.uint8)
    img = cv2.imdecode(datos, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"No se pudo decodificar la imagen: {imagen_path}")
    return img


def detectar_qr(imagen_bgr: np.ndarray, cfg_qr: dict) -> tuple | None:
    """
    Localiza el QR (solo geometría; el contenido JAMÁS se decodifica).
    Detector cv2 por defecto; pyzbar opcional si está en config y instalado.
    Valida cuadratura y tamaño para descartar falsos positivos del detector.
    """
    gris = cv2.cvtColor(imagen_bgr, cv2.COLOR_BGR2GRAY)
    alto, ancho = gris.shape
    lado_max = max(alto, ancho)
    candidatos: list[tuple] = []

    if cfg_qr.get("detector") == "pyzbar":
        try:
            from pyzbar.pyzbar import decode as pyzbar_decode
            for r in pyzbar_decode(gris):
                x, y, w, h = r.rect
                candidatos.append((x, y, w, h))
        except ImportError:
            pass  # cae silenciosamente a cv2

    if not candidatos:
        encontrado, cajas = cv2.QRCodeDetector().detect(gris)
        if encontrado and cajas is not None:
            for caja in np.asarray(cajas).reshape(-1, 4, 2):
                x1, y1 = caja.min(axis=0)
                x2, y2 = caja.max(axis=0)
                candidatos.append((int(x1), int(y1), int(x2 - x1), int(y2 - y1)))

    rmin = float(cfg_qr.get("ratio_cuadrado_min", 0.7))
    rmax = float(cfg_qr.get("ratio_cuadrado_max", 1.3))
    tmin = int(cfg_qr.get("tamano_min_px", 40))
    tmax = float(cfg_qr.get("tamano_max_frac", 0.6))
    for (x, y, w, h) in candidatos:
        if w <= 0 or h <= 0:
            continue
        ratio = w / h
        if not (rmin <= ratio <= rmax):
            continue
        if w < tmin or h < tmin or max(w, h) > tmax * lado_max:
            continue
        return (x, y, w, h)
    return None


def estimar_skew(gris: np.ndarray) -> float:
    """
    Ángulo de rotación fina del texto (±15°). Morfología horizontal + minAreaRect.
    Por encima de ±15° no se corrige aquí (eso es rotación grande / 180°, no skew).
    """
    binaria = cv2.adaptiveThreshold(gris, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY_INV, 31, 15)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, gris.shape[1] // 25), 1))
    dilatada = cv2.dilate(binaria, kernel, iterations=1)
    contornos, _ = cv2.findContours(dilatada, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    angulos = []
    for cnt in contornos:
        if cv2.contourArea(cnt) < 400:
            continue
        (_, _), (w, h), ang = cv2.minAreaRect(cnt)
        if w < h:  # referimos siempre al lado largo (convención OpenCV ≥4.5: ang en [0,90))
            ang = (ang + 90) % 180
        if ang > 90:
            ang -= 180
        if abs(ang) <= 15:
            angulos.append(ang)
    return float(statistics.median(angulos)) if angulos else 0.0


def corregir_geometria(imagen_bgr: np.ndarray, cfg_prep: dict) -> tuple[np.ndarray, float]:
    """Deskew + (opcional) binarización adaptativa. Retorna (imagen_procesada, grados)."""
    grados = 0.0
    gris = cv2.cvtColor(imagen_bgr, cv2.COLOR_BGR2GRAY)
    if cfg_prep.get("deskew", True):
        angulo = estimar_skew(gris)
        if abs(angulo) >= float(cfg_prep.get("angulo_minimo_correccion", 2.0)):
            h, w = imagen_bgr.shape[:2]
            M = cv2.getRotationMatrix2D((w / 2, h / 2), angulo, 1.0)
            imagen_bgr = cv2.warpAffine(imagen_bgr, M, (w, h), flags=cv2.INTER_LINEAR,
                                        borderMode=cv2.BORDER_REPLICATE)
            grados = -angulo  # signo: rotación aplicada para enderezar
            gris = cv2.cvtColor(imagen_bgr, cv2.COLOR_BGR2GRAY)
    if cfg_prep.get("binarizacion_adaptativa", True):
        binaria = cv2.adaptiveThreshold(
            gris, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,
            int(cfg_prep.get("binarizacion_blocksize", 51)),
            int(cfg_prep.get("binarizacion_c", 15)))
        imagen_bgr = cv2.cvtColor(binaria, cv2.COLOR_GRAY2BGR)
    return imagen_bgr, grados


def recortar_roi(imagen_bgr: np.ndarray, qr_bbox: tuple | None, cfg_qr: dict) -> tuple[np.ndarray, tuple | None]:
    """
    ROI conservador alrededor del QR (ancla espacial). Si no hay QR → imagen completa.
    Políticas anti-recorte de texto (lección de la primera iteración, ver docs/fase1_ocr.md):
    - Margen generoso (margen_roi_factor, default 3.0).
    - Si el ROI dejaría menos del 70% del ancho o alto de la imagen, no se recorta.
    - Si aun así un token toca el borde del ROI, extraer_texto reintenta con la
      imagen completa (ver _toca_borde_roi).
    """
    if qr_bbox is None:
        return imagen_bgr, None
    factor = float(cfg_qr.get("margen_roi_factor", 3.0))
    frac_min = float(cfg_qr.get("roi_frac_minima", 0.70))
    x, y, w, h = qr_bbox
    dx, dy = int(w * factor), int(h * factor)
    alto, ancho = imagen_bgr.shape[:2]
    x1, y1 = max(0, x - dx), max(0, y - dy)
    x2, y2 = min(ancho, x + w + dx), min(alto, y + h + dy)
    if (x2 - x1) < ancho * frac_min or (y2 - y1) < alto * frac_min:
        return imagen_bgr, None  # recortar tanto no compensa el riesgo de cortar texto
    return imagen_bgr[y1:y2, x1:x2], (x1, y1, x2 - x1, y2 - y1)


def _toca_borde_roi(lineas: list[dict], roi: tuple | None, margen_px: int = 8) -> bool:
    """True si alguna caja detectada toca el borde del ROI: posible texto truncado."""
    if roi is None:
        return False
    _, _, rw, rh = roi
    for l in lineas:
        x, y, w, h = l["bbox"]
        if x <= margen_px or y <= margen_px or (x + w) >= rw - margen_px or (y + h) >= rh - margen_px:
            return True
    return False


# ---------------------------------------------------------------------------
# Segmentación de tokens tipo código
# ---------------------------------------------------------------------------

def segmentar_tokens(lineas: list[dict], umbral_espacio_px: int) -> list[dict]:
    """
    Reconstruye el orden espacial y agrupa cajas por fila:
    - Filas: líneas cuya superposición vertical es sustancial (salto de línea = fila nueva).
    - Dentro de la fila, hueco horizontal <= umbral_espacio_px → mismo token;
      hueco mayor → tokens separados.
    - Al unir dos fragmentos: sin espacio si el hueco es pequeño (< 25% de la altura,
      típico de una palabra partida por el detector), con espacio si es mayor.
    """
    if not lineas:
        return []
    ordenadas = sorted(lineas, key=lambda l: (l["bbox"][1] + l["bbox"][3] / 2, l["bbox"][0]))
    filas: list[list[dict]] = []
    for linea in ordenadas:
        x, y, w, h = linea["bbox"]
        colocada = False
        for fila in filas:
            fx, fy, fw, fh = fila[-1]["bbox"]
            solape = min(y + h, fy + fh) - max(y, fy)
            if solape > 0.5 * min(h, fh):
                fila.append(linea)
                colocada = True
                break
        if not colocada:
            filas.append([linea])

    tokens = []
    for fila in filas:
        fila.sort(key=lambda l: l["bbox"][0])
        actual = None
        for linea in fila:
            x, y, w, h = linea["bbox"]
            if actual is None:
                actual = {"texto": linea["texto"], "x": x, "y": y, "x2": x + w, "y2": y + h,
                          "confianza": linea["confianza"], "altura": h}
                continue
            hueco = x - actual["x2"]
            altura_ref = max(actual["altura"], h)
            if hueco <= umbral_espacio_px:
                separador = "" if hueco < 0.25 * altura_ref else " "
                actual["texto"] += separador + linea["texto"]
                actual["x2"] = max(actual["x2"], x + w)
                actual["y"] = min(actual["y"], y)
                actual["y2"] = max(actual["y2"], y + h)
                actual["confianza"] = min(actual["confianza"], linea["confianza"])
                actual["altura"] = max(actual["altura"], h)
            else:
                tokens.append(actual)
                actual = {"texto": linea["texto"], "x": x, "y": y, "x2": x + w, "y2": y + h,
                          "confianza": linea["confianza"], "altura": h}
        if actual is not None:
            tokens.append(actual)

    return [{
        "texto": t["texto"].strip(),
        "bbox": (t["x"], t["y"], t["x2"] - t["x"], t["y2"] - t["y"]),
        "confianza": round(float(t["confianza"]), 4),
    } for t in tokens if t["texto"].strip()]


# ---------------------------------------------------------------------------
# API principal
# ---------------------------------------------------------------------------

def _calidad(lineas: list[dict]) -> tuple[int, float]:
    """(número de líneas, confianza media) para comparar pasadas."""
    if not lineas:
        return 0, 0.0
    return len(lineas), float(np.mean([l["confianza"] for l in lineas]))


def _pasada_ocr(imagen_bgr: np.ndarray, f1: dict, motor, forzar_completa: bool = False):
    """
    Preprocesa (deskew + binarización) → detecta QR (sobre la imagen YA corregida,
    para que las coordenadas del ancla y del recorte vivan en el mismo marco) →
    recorta ROI conservador → OCR. Retorna dict parcial con lineas/qr/roi/grados.
    """
    cfg_prep = f1.get("preprocesamiento", {})
    cfg_qr = f1.get("qr", {})
    procesada, grados = corregir_geometria(imagen_bgr, cfg_prep) if cfg_prep.get("activar", True) \
        else (imagen_bgr, 0.0)
    qr_bbox = detectar_qr(procesada, cfg_qr)
    roi_img, roi = (procesada, None) if forzar_completa else recortar_roi(procesada, qr_bbox, cfg_qr)
    lineas = [l for l in motor.leer(roi_img)
              if l["confianza"] >= float(f1.get("umbral_confianza", 0.5))]

    # Reintento anti-truncamiento: texto pegado al borde del ROI (o ROI vacío)
    # → segunda lectura sobre la imagen completa; gana la de mayor calidad.
    if roi is not None and f1.get("qr", {}).get("reintentar_imagen_completa", True) and \
            (not lineas or _toca_borde_roi(lineas, roi)):
        lineas_full = [l for l in motor.leer(procesada)
                       if l["confianza"] >= float(f1.get("umbral_confianza", 0.5))]
        if _calidad(lineas_full) > _calidad(lineas):
            lineas, roi = lineas_full, None

    return {"lineas": lineas, "grados": grados, "qr": qr_bbox, "roi": roi}


def extraer_texto(imagen_path: str, config: dict | None = None) -> dict:
    """
    Pipeline completo sobre una imagen. Ver contrato en el docstring del módulo.

    Corrección de orientación en dos niveles:
    1. Clasificador de orientación de documento del motor (0/90/180/270), interno
       a PaddleOCR (usa doc orientation classify).
    2. Respaldo adaptativo: si la lectura salió vacía o con confianza baja, se
       prueba la imagen rotada 180° y gana la mejor pasada. Solo se dispara ante
       lecturas claramente malas para no duplicar el costo en el caso normal.
    """
    motor, f1 = obtener_motor(config)
    imagen = cargar_imagen(imagen_path)

    pasada = _pasada_ocr(imagen, f1, motor)
    n1, c1 = _calidad(pasada["lineas"])

    umbral_2a = float(f1.get("umbral_confianza_segunda_pasada", 0.60))
    if f1.get("preprocesamiento", {}).get("detectar_invertida_180", True) and \
            (n1 == 0 or c1 < umbral_2a):
        pasada2 = _pasada_ocr(cv2.rotate(imagen, cv2.ROTATE_180), f1, motor)
        n2, c2 = _calidad(pasada2["lineas"])
        if (n2, round(c2, 3)) > (n1, round(c1, 3)):
            pasada = pasada2
            pasada["grados"] = pasada["grados"] + 180.0

    tokens = segmentar_tokens(pasada["lineas"], int(f1.get("umbral_espacio_px", 40)))
    confianzas = [t["confianza"] for t in tokens]
    h, w = imagen.shape[:2]
    return {
        "imagen": str(imagen_path),
        "motor": motor.nombre,
        "tokens": tokens,
        "qr_bbox": tuple(pasada["qr"]) if pasada["qr"] is not None else None,
        "orientacion_corregida_grados": float(pasada["grados"]),
        "confianza_media": round(float(np.mean(confianzas)), 4) if confianzas else None,
        "num_lineas_ocr": len(pasada["lineas"]),
        "dimensiones": (w, h),
        "roi_usado": tuple(pasada["roi"]) if pasada["roi"] is not None else None,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fase 1: extraer texto de una imagen.")
    parser.add_argument("imagenes", nargs="+", help="Rutas de imágenes a procesar.")
    parser.add_argument("--compacto", action="store_true", help="Solo texto de tokens por línea.")
    args = parser.parse_args()
    for ruta in args.imagenes:
        resultado = extraer_texto(ruta)
        if args.compacto:
            print(f"{Path(ruta).name}: " + " | ".join(t["texto"] for t in resultado["tokens"])
                  + f"  [qr={resultado['qr_bbox'] is not None}, "
                    f"conf={resultado['confianza_media']}, rot={resultado['orientacion_corregida_grados']}]")
        else:
            print(json.dumps(resultado, ensure_ascii=False, indent=2, default=list))
