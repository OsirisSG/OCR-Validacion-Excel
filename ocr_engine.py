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
- El motor es intercambiable: EasyOCR es el valor portable predeterminado y
  PaddleOCR permanece disponible como alternativa, ambos elegidos desde
  config.yaml. Si el principal falla se usa el secundario y se reporta cuál fue.

Preprocesamiento (orden): carga unicode-safe → búsqueda adaptativa en
0°/90°/180°/270° → deskew → variantes para impresión/relieve → recorte de ROI
(solo si hay QR y queda espacio) → selección del candidato con mejor evidencia.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import statistics
import sys
import warnings
from pathlib import Path

import cv2
import numpy as np

from configuracion import RAIZ_PROYECTO, cargar_config
from recursos import configurar_cpu, detectar_recursos

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

    def leer_texto_completo(self, imagen_bgr: np.ndarray) -> list[dict]:
        return self.leer(imagen_bgr)


class MotorEasyOCR:
    """Adaptador del motor EasyOCR portable instalado por defecto."""

    nombre = "easyocr"

    def __init__(self, cfg_fase1: dict):
        import easyocr  # import diferido
        self._easyocr = easyocr
        self._lang = cfg_fase1.get("lang", "en")
        self.recursos = detectar_recursos(cfg_fase1.get("dispositivo", "auto"))
        rendimiento = cfg_fase1.get("rendimiento", {})
        self.hilos_cpu = configurar_cpu(rendimiento.get("hilos_cpu"))
        self.dispositivo = self.recursos["seleccionado"]
        self.advertencias = [self.recursos["warning"]] if self.recursos.get("warning") else []
        gpu = False if self.dispositivo == "cpu" else self.dispositivo
        try:
            self._reader = easyocr.Reader(
                [self._lang], gpu=gpu, verbose=False,
                quantize=self.dispositivo == "cpu")
        except Exception as exc:
            if self.dispositivo == "cpu":
                raise
            self.advertencias.append(
                f"EasyOCR no pudo iniciar en {self.dispositivo.upper()} "
                f"({type(exc).__name__}); se inició en CPU.")
            self.dispositivo = "cpu"
            self._reader = easyocr.Reader(
                [self._lang], gpu=False, verbose=False, quantize=True)
        # La fuente de verdad es el dispositivo que EasyOCR realmente aceptó.
        self.dispositivo = str(getattr(self._reader, "device", self.dispositivo))
        self._batch_size = int(rendimiento.get(
            "batch_cpu" if self.dispositivo == "cpu" else "batch_gpu", 1))
        self._workers = int(rendimiento.get("workers_easyocr", 0))
        self._allowlist = cfg_fase1.get("caracteres_permitidos") or None

    def _fallback_cpu(self, causa: Exception) -> None:
        self.advertencias.append(
            f"La inferencia en {self.dispositivo.upper()} falló ({type(causa).__name__}); "
            "EasyOCR continuó en CPU.")
        self._reader = self._easyocr.Reader(
            [self._lang], gpu=False, verbose=False, quantize=True)
        self.dispositivo = "cpu"
        self._batch_size = 1

    def _leer(self, imagen_bgr: np.ndarray, usar_allowlist: bool) -> list[dict]:
        opciones = ({"allowlist": self._allowlist}
                    if usar_allowlist and self._allowlist else {})
        try:
            with warnings.catch_warnings():
                if self.dispositivo == "mps":
                    warnings.filterwarnings(
                        "ignore", message=".*pin_memory.*not supported on MPS.*",
                        category=UserWarning)
                lecturas = self._reader.readtext(
                    imagen_bgr, detail=1, batch_size=self._batch_size,
                    workers=self._workers, **opciones)
        except RuntimeError as exc:
            if self.dispositivo == "cpu":
                raise
            self._fallback_cpu(exc)
            lecturas = self._reader.readtext(
                imagen_bgr, detail=1, batch_size=1, workers=0, **opciones)
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

    def leer(self, imagen_bgr: np.ndarray) -> list[dict]:
        return self._leer(imagen_bgr, usar_allowlist=True)

    def leer_texto_completo(self, imagen_bgr: np.ndarray) -> list[dict]:
        """Lectura sin allowlist: conserva espacios, acentos y puntuación."""
        return self._leer(imagen_bgr, usar_allowlist=False)


def obtener_motor(config: dict | None = None):
    """Retorna el primer motor configurado que pueda inicializarse."""
    config = config or cargar_config()
    f1 = config.get("fase1", {})
    recursos = detectar_recursos(f1.get("dispositivo", "auto"))
    for clave in ("motor", "motor_fallback"):
        nombre = f1.get(clave) if clave == "motor" else f1.get("motor_fallback")
        if not nombre:
            continue
        llave = (nombre, recursos["seleccionado"] if nombre == "easyocr" else "auto")
        if llave in _MOTORES:
            return _MOTORES[llave], f1
        clase = {"paddle": MotorPaddle, "easyocr": MotorEasyOCR}.get(nombre)
        if clase is None:
            continue
        try:
            _MOTORES[llave] = clase(f1)
            return _MOTORES[llave], f1
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


def _corregir_deskew(imagen_bgr: np.ndarray, cfg_prep: dict) -> tuple[np.ndarray, float]:
    """Corrige únicamente la inclinación fina y conserva la imagen en color."""
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
    return imagen_bgr, grados


def aplicar_variante(imagen_bgr: np.ndarray, nombre: str, cfg_prep: dict) -> np.ndarray:
    """
    Genera una representación visual para el OCR.

    ``original`` conserva color; ``adaptativa`` cubre etiquetas impresas;
    ``clahe`` recupera contraste local y ``relieve`` realza cambios claros y
    oscuros producidos por letras grabadas o moldeadas sobre plástico.
    """
    if nombre == "original":
        return imagen_bgr

    gris = cv2.cvtColor(imagen_bgr, cv2.COLOR_BGR2GRAY)
    if nombre == "adaptativa":
        binaria = cv2.adaptiveThreshold(
            gris, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,
            int(cfg_prep.get("binarizacion_blocksize", 51)),
            int(cfg_prep.get("binarizacion_c", 15)))
        return cv2.cvtColor(binaria, cv2.COLOR_GRAY2BGR)

    clip = float(cfg_prep.get("clahe_clip_limit", 3.0))
    rejilla = int(cfg_prep.get("clahe_grid_size", 8))
    clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=(rejilla, rejilla))
    contrastada = clahe.apply(gris)
    if nombre == "clahe":
        return cv2.cvtColor(contrastada, cv2.COLOR_GRAY2BGR)

    if nombre == "relieve":
        k = int(cfg_prep.get("relieve_kernel", 9))
        # OpenCV exige un kernel positivo e impar.
        k = max(3, k if k % 2 else k + 1)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        claro = cv2.morphologyEx(contrastada, cv2.MORPH_TOPHAT, kernel)
        oscuro = cv2.morphologyEx(contrastada, cv2.MORPH_BLACKHAT, kernel)
        relieve = cv2.max(claro, oscuro)
        relieve = cv2.normalize(relieve, None, 0, 255, cv2.NORM_MINMAX)
        return cv2.cvtColor(relieve, cv2.COLOR_GRAY2BGR)

    raise ValueError(f"Variante de preprocesamiento desconocida: {nombre}")


def corregir_geometria(imagen_bgr: np.ndarray, cfg_prep: dict) -> tuple[np.ndarray, float]:
    """Compatibilidad: deskew + variante principal configurada."""
    corregida, grados = _corregir_deskew(imagen_bgr, cfg_prep)
    variante = cfg_prep.get(
        "variante_principal",
        "adaptativa" if cfg_prep.get("binarizacion_adaptativa", True) else "original")
    return aplicar_variante(corregida, variante, cfg_prep), grados


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


def detectar_regiones_texto(imagen_bgr: np.ndarray, cfg_regiones: dict) -> list[tuple[int, int, int, int]]:
    """Propone renglones de texto mediante MSER y agrupación horizontal.

    Es especialmente útil para relieve: MSER encuentra interiores claros y
    oscuros aun cuando no existe una separación limpia entre texto y fondo.
    Las regiones solo guían recortes; el OCR sigue decidiendo qué contienen.
    """
    gris = cv2.cvtColor(imagen_bgr, cv2.COLOR_BGR2GRAY)
    alto, ancho = gris.shape
    area = alto * ancho
    delta = int(cfg_regiones.get("mser_delta", 5))
    area_min = max(20, int(area * float(cfg_regiones.get("area_caracter_min_frac", 0.00001))))
    area_max = max(area_min + 1, int(area * float(
        cfg_regiones.get("area_caracter_max_frac", 0.02))))
    mser = cv2.MSER_create(delta, area_min, area_max)
    _, cajas = mser.detectRegions(gris)
    mascara = np.zeros_like(gris)
    for x, y, w, h in cajas:
        if not (8 <= h <= alto * 0.30 and 3 <= w <= ancho * 0.30):
            continue
        ratio = w / max(h, 1)
        if 0.15 <= ratio <= 8.0:
            cv2.rectangle(mascara, (int(x), int(y)), (int(x + w), int(y + h)), 255, -1)

    divisor_x = max(8, int(cfg_regiones.get("agrupacion_horizontal_divisor", 25)))
    divisor_y = max(50, int(cfg_regiones.get("agrupacion_vertical_divisor", 200)))
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (max(12, ancho // divisor_x), max(3, alto // divisor_y)))
    agrupada = cv2.dilate(mascara, kernel, iterations=int(cfg_regiones.get("dilataciones", 2)))
    contornos, _ = cv2.findContours(agrupada, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    margen_x = float(cfg_regiones.get(
        "margen_horizontal_factor", cfg_regiones.get("margen_factor", 0.15)))
    margen_y = float(cfg_regiones.get(
        "margen_vertical_factor", cfg_regiones.get("margen_factor", 0.15)))
    candidatos = []
    for contorno in contornos:
        x, y, w, h = cv2.boundingRect(contorno)
        frac = (w * h) / max(area, 1)
        if not (float(cfg_regiones.get("area_region_min_frac", 0.001)) <= frac <=
                float(cfg_regiones.get("area_region_max_frac", 0.25))):
            continue
        if w / max(h, 1) < float(cfg_regiones.get("ratio_region_min", 1.5)):
            continue
        mx, my = int(w * margen_x), int(h * margen_y)
        x1, y1 = max(0, x - mx), max(0, y - my)
        x2, y2 = min(ancho, x + w + mx), min(alto, y + h + my)
        candidatos.append((x1, y1, x2 - x1, y2 - y1))

    # Las regiones grandes primero; se eliminan casi-duplicados por IoU.
    candidatos.sort(key=lambda b: b[2] * b[3], reverse=True)
    elegidas: list[tuple[int, int, int, int]] = []
    for caja in candidatos:
        x, y, w, h = caja
        duplicada = False
        for ex, ey, ew, eh in elegidas:
            ix1, iy1 = max(x, ex), max(y, ey)
            ix2, iy2 = min(x + w, ex + ew), min(y + h, ey + eh)
            inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
            union = w * h + ew * eh - inter
            if union and inter / union >= 0.65:
                duplicada = True
                break
        if not duplicada:
            elegidas.append(caja)
        if len(elegidas) >= int(cfg_regiones.get("max_regiones", 6)):
            break
    return elegidas


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
    filas = _agrupar_por_filas(lineas)
    tokens = []
    for fila in filas:
        fila.sort(key=lambda l: l["bbox"][0])
        actual = None
        for linea in fila:
            x, y, w, h = linea["bbox"]
            if actual is None:
                actual = {"texto": linea["texto"], "x": x, "y": y, "x2": x + w, "y2": y + h,
                          "confianza": linea["confianza"], "altura": h,
                          "origenes": {linea.get("origen", "global")}}
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
                actual["origenes"].add(linea.get("origen", "global"))
            else:
                tokens.append(actual)
                actual = {"texto": linea["texto"], "x": x, "y": y, "x2": x + w, "y2": y + h,
                          "confianza": linea["confianza"], "altura": h,
                          "origenes": {linea.get("origen", "global")}}
        if actual is not None:
            tokens.append(actual)

    return [{
        "texto": t["texto"].strip(),
        "bbox": (t["x"], t["y"], t["x2"] - t["x"], t["y2"] - t["y"]),
        "confianza": round(float(t["confianza"]), 4),
        **({"origen": "region"} if "region" in t["origenes"] else {}),
    } for t in tokens if t["texto"].strip()]


def _agrupar_por_filas(lineas: list[dict]) -> list[list[dict]]:
    """Agrupa detecciones por renglón usando la caja acumulada de cada fila."""
    ordenadas = sorted(lineas, key=lambda l: (
        l["bbox"][1] + l["bbox"][3] / 2, l["bbox"][0]))
    filas: list[list[dict]] = []
    for linea in ordenadas:
        x, y, w, h = linea["bbox"]
        colocada = False
        for fila in filas:
            ys = [item["bbox"][1] for item in fila]
            y2s = [item["bbox"][1] + item["bbox"][3] for item in fila]
            fy, fy2 = min(ys), max(y2s)
            solape = min(y + h, fy2) - max(y, fy)
            if solape > 0.45 * min(h, fy2 - fy):
                fila.append(linea)
                colocada = True
                break
        if not colocada:
            filas.append([linea])
    return filas


def reconstruir_lineas_texto(lineas: list[dict]) -> list[dict]:
    """Reconstruye renglones, espacios aproximados y saltos de línea."""
    reconstruidas = []
    for fila in _agrupar_por_filas(lineas):
        fila = sorted(fila, key=lambda l: l["bbox"][0])
        partes: list[str] = []
        anterior = None
        for item in fila:
            texto = str(item.get("texto") or "").strip()
            if not texto:
                continue
            if anterior is not None:
                ax, ay, aw, ah = anterior["bbox"]
                x, y, w, h = item["bbox"]
                hueco = x - (ax + aw)
                caracteres = max(len(re.sub(r"\s+", "", str(anterior.get("texto") or ""))), 1)
                ancho_caracter = max(aw / caracteres, min(ah, h) * 0.35, 1.0)
                # Dos cajas distintas suelen representar palabras distintas.
                # Solo se concatenan sin espacio cuando se solapan de forma
                # clara (fragmentación interna del mismo glifo/palabra).
                if hueco >= -0.15 * min(ah, h):
                    partes.append(" " * min(8, max(1, round(max(hueco, 0) / ancho_caracter))))
            partes.append(texto)
            anterior = item
        if not partes:
            continue
        xs = [i["bbox"][0] for i in fila]
        ys = [i["bbox"][1] for i in fila]
        x2s = [i["bbox"][0] + i["bbox"][2] for i in fila]
        y2s = [i["bbox"][1] + i["bbox"][3] for i in fila]
        reconstruidas.append({
            "texto": "".join(partes).strip(),
            "bbox": (min(xs), min(ys), max(x2s) - min(xs), max(y2s) - min(ys)),
            "confianza": round(float(np.mean([i["confianza"] for i in fila])), 4),
            "fragmentos": len(fila),
        })
    return reconstruidas


# ---------------------------------------------------------------------------
# API principal
# ---------------------------------------------------------------------------

def _calidad(lineas: list[dict]) -> tuple[int, float]:
    """(número de líneas, confianza media) para comparar pasadas."""
    if not lineas:
        return 0, 0.0
    return len(lineas), float(np.mean([l["confianza"] for l in lineas]))


def _pasada_ocr(imagen_bgr: np.ndarray, f1: dict, motor, forzar_completa: bool = False,
                variante: str | None = None):
    """
    Preprocesa (deskew + binarización) → detecta QR (sobre la imagen YA corregida,
    para que las coordenadas del ancla y del recorte vivan en el mismo marco) →
    recorta ROI conservador → OCR. Retorna dict parcial con lineas/qr/roi/grados.
    """
    cfg_prep = f1.get("preprocesamiento", {})
    cfg_qr = f1.get("qr", {})
    if cfg_prep.get("activar", True):
        geometria, grados = _corregir_deskew(imagen_bgr, cfg_prep)
        if variante is None:
            variante = cfg_prep.get(
                "variante_principal",
                "adaptativa" if cfg_prep.get("binarizacion_adaptativa", True) else "original")
        procesada = aplicar_variante(geometria, variante, cfg_prep)
    else:
        geometria, procesada, grados, variante = imagen_bgr, imagen_bgr, 0.0, "original"

    # El QR se busca sobre la geometría corregida en color: las variantes de
    # relieve pueden borrar sus módulos aunque el ancla exista en la foto.
    qr_bbox = detectar_qr(geometria, cfg_qr)
    roi_img, roi = (procesada, None) if forzar_completa else recortar_roi(procesada, qr_bbox, cfg_qr)
    umbral_codigo = float(f1.get("umbral_confianza", 0.5))
    umbral_texto = float(f1.get("umbral_confianza_texto_completo", 0.25))
    lecturas_roi = motor.leer(roi_img)
    lineas = [l for l in lecturas_roi if l["confianza"] >= umbral_codigo]
    if roi is None:
        lineas_texto = [l for l in lecturas_roi if l["confianza"] >= umbral_texto]
    else:
        # El texto completo nunca se limita al ROI del QR.
        lecturas_completas = motor.leer(procesada)
        lineas_texto = [l for l in lecturas_completas if l["confianza"] >= umbral_texto]

    # Reintento anti-truncamiento: texto pegado al borde del ROI (o ROI vacío)
    # → segunda lectura sobre la imagen completa; gana la de mayor calidad.
    if roi is not None and f1.get("qr", {}).get("reintentar_imagen_completa", True) and \
            (not lineas or _toca_borde_roi(lineas, roi)):
        lineas_full = [l for l in (lecturas_completas if roi is not None else lecturas_roi)
                       if l["confianza"] >= umbral_codigo]
        if _calidad(lineas_full) > _calidad(lineas):
            lineas, roi = lineas_full, None

    return {"lineas": lineas, "grados": grados, "qr": qr_bbox, "roi": roi,
            "lineas_texto": lineas_texto, "variante": variante,
            "tipo": "global", "bono_region": 0.0}


def _pasada_regiones(imagen_bgr: np.ndarray, f1: dict, motor, variante: str) -> dict:
    """Detecta, amplía y lee regiones; devuelve cajas en el marco orientado."""
    prep = f1.get("preprocesamiento", {})
    cfg_regiones = prep.get("regiones_texto", {})
    geometria, grados = _corregir_deskew(imagen_bgr, prep)
    regiones = detectar_regiones_texto(geometria, cfg_regiones)
    lineas = []
    umbral = float(cfg_regiones.get("umbral_confianza", 0.20))
    altura_objetivo = int(cfg_regiones.get("altura_objetivo_px", 220))
    escala_max = float(cfg_regiones.get("escala_max", 3.0))
    for region in regiones:
        x0, y0, w0, h0 = region
        recorte = geometria[y0:y0 + h0, x0:x0 + w0]
        if recorte.size == 0:
            continue
        escala = min(escala_max, max(1.0, altura_objetivo / max(h0, 1)))
        if escala > 1.05:
            recorte = cv2.resize(recorte, None, fx=escala, fy=escala,
                                 interpolation=cv2.INTER_CUBIC)
        procesada = aplicar_variante(recorte, variante, prep)
        for linea in motor.leer(procesada):
            if linea["confianza"] < umbral:
                continue
            lx, ly, lw, lh = linea["bbox"]
            lineas.append({
                **linea,
                "bbox": (x0 + int(lx / escala), y0 + int(ly / escala),
                         max(1, int(lw / escala)), max(1, int(lh / escala))),
                "origen": "region",
                "region_bbox": region,
            })
    return {
        "lineas": lineas,
        "grados": grados,
        "qr": detectar_qr(geometria, f1.get("qr", {})),
        "roi": None,
        "variante": variante,
        "tipo": "regiones",
        "regiones_evaluadas": len(regiones),
        "bono_region": float(cfg_regiones.get("bono_puntuacion", 0.35)),
    }


_RE_ALFANUMERICO = re.compile(r"^(?=.*[A-Z])(?=.*\d)[A-Z0-9]+$")
_RE_NUMERICO_LARGO = re.compile(r"^\d{5,}$")


def _candidatos_codigo(lineas: list[dict], umbral_espacio_px: int) -> list[dict]:
    """Códigos mixtos o secuencias numéricas largas, sin formato empresarial fijo."""
    candidatos = []
    for token in segmentar_tokens(lineas, umbral_espacio_px):
        limpio = re.sub(r"[^A-Z0-9]", "", token["texto"].upper())
        texto_crudo = re.sub(r"[^A-Za-z0-9]", "", token["texto"])
        posible_relieve = (token.get("origen") == "region" and len(limpio) >= 5 and
                            any(c.islower() for c in texto_crudo) and
                            any(c.isupper() for c in texto_crudo))
        if ((len(limpio) >= 4 and _RE_ALFANUMERICO.match(limpio)) or
                _RE_NUMERICO_LARGO.match(limpio) or posible_relieve):
            candidatos.append(token)
    return candidatos


def _puntuar_pasada(pasada: dict, umbral_espacio_px: int) -> tuple:
    """Prioriza códigos alfanuméricos; después confianza, longitud y cobertura."""
    codigos = _candidatos_codigo(pasada["lineas"], umbral_espacio_px)
    if codigos:
        mejor = max(codigos, key=lambda t: (t["confianza"], len(t["texto"])))
        confianza_ajustada = min(1.0, float(mejor["confianza"]) +
                                 float(pasada.get("bono_region", 0.0)))
        return (1, confianza_ajustada, len(mejor["texto"]), *_calidad(pasada["lineas"]))
    n, confianza = _calidad(pasada["lineas"])
    return (0, 0.0, 0, n, confianza)


def _rotar_recto(imagen_bgr: np.ndarray, grados: int) -> np.ndarray:
    """Rota en múltiplos de 90° sin interpolación ni pérdida de detalle."""
    grados = grados % 360
    if grados == 0:
        return imagen_bgr
    if grados == 90:
        return cv2.rotate(imagen_bgr, cv2.ROTATE_90_CLOCKWISE)
    if grados == 180:
        return cv2.rotate(imagen_bgr, cv2.ROTATE_180)
    if grados == 270:
        return cv2.rotate(imagen_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
    raise ValueError(f"La orientación debe ser múltiplo de 90°, no {grados}")


def _seleccionar_pasada(imagen: np.ndarray, f1: dict, motor) -> tuple[dict, list[dict]]:
    """Ejecuta la búsqueda adaptativa por orientación y tratamiento visual."""
    prep = f1.get("preprocesamiento", {})
    busqueda = prep.get("busqueda_adaptativa", {})
    espacio = int(f1.get("umbral_espacio_px", 40))
    principal = prep.get(
        "variante_principal",
        "adaptativa" if prep.get("binarizacion_adaptativa", True) else "original")
    orientaciones = [int(a) % 360 for a in busqueda.get("orientaciones", [0, 90, 180, 270])]
    orientaciones = list(dict.fromkeys([0, *orientaciones]))
    variantes = list(dict.fromkeys([principal, *busqueda.get(
        "variantes_respaldo", ["original", "clahe", "relieve"])]))
    modo = str(busqueda.get("modo", "adaptativo")).lower()
    confianza_objetivo = float(busqueda.get("confianza_codigo_suficiente", 0.70))
    intentos: list[dict] = []

    def ejecutar(angulo: int, variante: str, regiones: bool = False) -> dict:
        rotada = _rotar_recto(imagen, angulo)
        pasada = (_pasada_regiones(rotada, f1, motor, variante) if regiones
                  else _pasada_ocr(rotada, f1, motor, variante=variante))
        pasada["grados"] += float(angulo)
        pasada["orientacion_base"] = angulo
        puntuacion = _puntuar_pasada(pasada, espacio)
        pasada["puntuacion"] = puntuacion
        intentos.append({
            "orientacion_grados": angulo,
            "variante": variante,
            "tipo": pasada.get("tipo", "global"),
            "lineas": len(pasada["lineas"]),
            "codigos_candidatos": len(_candidatos_codigo(pasada["lineas"], espacio)),
            "confianza_media": round(_calidad(pasada["lineas"])[1], 4),
        })
        return pasada

    candidatos = [ejecutar(0, principal)]

    def suficiente() -> bool:
        mejor = max(candidatos, key=lambda p: p["puntuacion"])
        return bool(mejor["puntuacion"][0] and mejor["puntuacion"][1] >= confianza_objetivo)

    regiones_activas = bool(prep.get("regiones_texto", {}).get("activar", True))
    if regiones_activas and (modo == "exhaustivo" or not suficiente()):
        candidatos.append(ejecutar(0, principal, regiones=True))

    # Primero se prueban las demás orientaciones con el tratamiento normal.
    # Esto resuelve etiquetas a 90°/180°/270° con el menor número de pasadas.
    if modo == "exhaustivo" or not suficiente():
        for angulo in orientaciones:
            if angulo:
                candidatos.append(ejecutar(angulo, principal))

    if regiones_activas and (modo == "exhaustivo" or not suficiente()):
        for variante in variantes:
            if variante != principal:
                candidatos.append(ejecutar(0, variante, regiones=True))
                if modo != "exhaustivo" and suficiente():
                    break

    # Las variantes costosas se reservan para texto débil/grabado, salvo que el
    # operador pida explícitamente una búsqueda exhaustiva.
    if modo == "exhaustivo" or not suficiente():
        for variante in variantes:
            if variante == principal:
                continue
            for angulo in orientaciones:
                candidatos.append(ejecutar(angulo, variante))

    mejor = max(candidatos, key=lambda p: p["puntuacion"])
    globales = [p for p in candidatos if p.get("tipo") == "global"] or candidatos

    def cobertura_texto(pasada: dict) -> tuple:
        lineas = pasada.get("lineas_texto") or pasada["lineas"]
        caracteres = sum(len(re.sub(r"\s+", "", l.get("texto", ""))) for l in lineas)
        ponderados = sum(len(re.sub(r"\s+", "", l.get("texto", ""))) * l["confianza"]
                         for l in lineas)
        return (round(ponderados, 4), caracteres, *_calidad(lineas))

    mejor_texto = max(globales, key=cobertura_texto)
    mejor["lineas_texto_completo"] = (
        mejor_texto.get("lineas_texto") or mejor_texto["lineas"])
    mejor["orientacion_texto_grados"] = mejor_texto["grados"]
    mejor["orientacion_texto_base"] = mejor_texto.get("orientacion_base", 0)
    mejor["variante_texto_completo"] = mejor_texto["variante"]
    mejor.pop("puntuacion", None)
    return mejor, intentos


def _extraer_pasada_texto_completo(imagen: np.ndarray, f1: dict, motor,
                                   orientacion: int, variante: str) -> tuple[list[dict], float]:
    """Una lectura global final sin restricciones de alfabeto ni ROI."""
    prep = f1.get("preprocesamiento", {})
    rotada = _rotar_recto(imagen, orientacion)
    if prep.get("activar", True):
        geometria, deskew = _corregir_deskew(rotada, prep)
        procesada = aplicar_variante(geometria, variante, prep)
    else:
        procesada, deskew = rotada, 0.0
    lector = getattr(motor, "leer_texto_completo", motor.leer)
    umbral = float(f1.get("umbral_confianza_texto_completo", 0.25))
    lineas = [linea for linea in lector(procesada) if linea["confianza"] >= umbral]
    return lineas, float(orientacion) + float(deskew)


def extraer_texto(imagen_path: str, config: dict | None = None) -> dict:
    """
    Pipeline completo sobre una imagen. Ver contrato en el docstring del módulo.

    La búsqueda empieza con la ruta normal a 0°. Si no obtiene un código
    alfanumérico suficientemente confiable, amplía a las demás orientaciones y
    después a variantes de contraste/relieve. ``modo: exhaustivo`` permite
    evaluar todas las combinaciones cuando el costo no sea prioritario.
    """
    motor, f1 = obtener_motor(config)
    imagen_original = cargar_imagen(imagen_path)
    from aprendizaje import GestorAprendizaje, aplicar_modelo_tokens
    rotacion_manual = GestorAprendizaje(config).rotacion_preferida(imagen_path)
    imagen = _rotar_recto(imagen_original, rotacion_manual)

    pasada, intentos = _seleccionar_pasada(imagen, f1, motor)

    tokens = segmentar_tokens(pasada["lineas"], int(f1.get("umbral_espacio_px", 40)))
    if f1.get("extraer_texto_completo", True):
        lineas_crudas_texto, orientacion_texto = _extraer_pasada_texto_completo(
            imagen, f1, motor,
            int(pasada.get("orientacion_texto_base", 0)),
            str(pasada.get("variante_texto_completo", pasada["variante"])),
        )
        intentos.append({
            "orientacion_grados": int(pasada.get("orientacion_texto_base", 0)),
            "variante": pasada.get("variante_texto_completo", pasada["variante"]),
            "tipo": "texto_completo",
            "lineas": len(lineas_crudas_texto),
            "codigos_candidatos": 0,
            "confianza_media": round(_calidad(lineas_crudas_texto)[1], 4),
        })
    else:
        lineas_crudas_texto = pasada.get("lineas_texto_completo") or pasada["lineas"]
        orientacion_texto = float(pasada.get("orientacion_texto_grados", pasada["grados"]))
    lineas_texto = reconstruir_lineas_texto(lineas_crudas_texto)
    # El modelo incremental solo modifica tokens cuando una versión promovida
    # tiene evidencia suficiente; siempre conserva texto_original y versión.
    cantidad_tokens = len(tokens)
    unidades_corregidas = aplicar_modelo_tokens(
        [*tokens, *lineas_texto], config, imagen_path)
    tokens = unidades_corregidas[:cantidad_tokens]
    lineas_texto = unidades_corregidas[cantidad_tokens:]
    confianzas = [t["confianza"] for t in tokens]
    h_original, w_original = imagen_original.shape[:2]
    h, w = imagen.shape[:2]
    base_codigo = int(pasada.get("orientacion_base", 0)) % 360
    base_texto = int(pasada.get("orientacion_texto_base", 0)) % 360
    deskew_codigo_reportado = float(pasada["grados"]) - base_codigo
    deskew_texto_reportado = float(orientacion_texto) - base_texto
    dimensiones_texto = (h, w) if base_texto in {90, 270} else (w, h)
    return {
        "imagen": str(imagen_path),
        "motor": motor.nombre,
        "dispositivo": getattr(motor, "dispositivo", "cpu"),
        "advertencias_motor": list(getattr(motor, "advertencias", [])),
        "tokens": tokens,
        "lineas_texto": lineas_texto,
        "texto_completo": "\n".join(l["texto"] for l in lineas_texto),
        "qr_bbox": tuple(pasada["qr"]) if pasada["qr"] is not None else None,
        "rotacion_manual_aplicada_grados": rotacion_manual,
        "orientacion_base_grados": base_codigo,
        "deskew_aplicado_grados": -deskew_codigo_reportado,
        "orientacion_corregida_grados": (
            rotacion_manual + float(pasada["grados"])) % 360,
        "orientacion_texto_base_grados": base_texto,
        "deskew_texto_aplicado_grados": -deskew_texto_reportado,
        "orientacion_texto_grados": (rotacion_manual + orientacion_texto) % 360,
        "confianza_media": round(float(np.mean(confianzas)), 4) if confianzas else None,
        "num_lineas_ocr": len(pasada["lineas"]),
        "dimensiones_originales": (w_original, h_original),
        "dimensiones": dimensiones_texto,
        "roi_usado": tuple(pasada["roi"]) if pasada["roi"] is not None else None,
        "variante_preprocesamiento": pasada["variante"],
        "variante_texto_completo": pasada.get(
            "variante_texto_completo", pasada["variante"]),
        "intentos_ocr": intentos,
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
