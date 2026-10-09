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
- EasyOCR es el motor de producción. Se mantiene una sola instancia propietaria
  de CUDA; ante presión de VRAM se reduce el batch y, si una tarea aislada no
  cabe, sólo esa tarea se deriva temporalmente a CPU sin abandonar CUDA. El
  adaptador Paddle antiguo sólo conserva compatibilidad histórica;
  la instalación y configuración vigentes no lo requieren ni lo seleccionan.

Preprocesamiento (orden): carga unicode-safe → búsqueda adaptativa en
0°/90°/180°/270° → deskew → variantes para impresión/relieve → recorte de ROI
(solo si hay QR y queda espacio) → selección del candidato con mejor evidencia.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import statistics
import sys
import time
import warnings
from copy import deepcopy
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
    """Adaptador EasyOCR V14 con batch adaptativo y recuperación temporal.

    ``batch_size`` de EasyOCR agrupa recortes/regiones dentro del reconocedor; no
    significa que se estén ejecutando varias fotografías en paralelo. Por eso se
    mantiene un único Reader CUDA y el paralelismo de fotografías ocurre sólo en
    la etapa CPU de preparación.
    """

    nombre = "easyocr"

    def __init__(self, cfg_fase1: dict):
        import easyocr  # import diferido
        from gestor_recursos import obtener_gestor_recursos

        self._easyocr = easyocr
        self._lang = cfg_fase1.get("lang", "en")
        self.recursos = detectar_recursos(cfg_fase1.get("dispositivo", "auto"))
        rendimiento = cfg_fase1.get("rendimiento", {})
        self._perfil_sop = str(rendimiento.get("perfil_sop", "alto")).lower()
        self._gestor = obtener_gestor_recursos(self._perfil_sop)
        self.hilos_cpu = configurar_cpu(rendimiento.get("hilos_cpu"))
        self.dispositivo = self.recursos["seleccionado"]
        self.advertencias = [self.recursos["warning"]] if self.recursos.get("warning") else []
        self.modelo_visual = cfg_fase1.get("_modelo_visual_activo")
        self._reader_cpu = None
        self._fallos_cuda_consecutivos = 0
        self._exitos_desde_ajuste = 0
        self._ventana_batch = max(4, int(rendimiento.get("ventana_batch", 12)))
        self._reintentos_oom = max(1, int(rendimiento.get("reintentos_oom", 3)))
        gpu = False if self.dispositivo == "cpu" else self.dispositivo
        try:
            self._reader = easyocr.Reader(
                [self._lang], gpu=gpu, verbose=False,
                quantize=self.dispositivo == "cpu" and not self.modelo_visual)
        except Exception as exc:
            if self.dispositivo == "cpu":
                raise
            self.advertencias.append(
                f"EasyOCR no pudo iniciar en {self.dispositivo.upper()} "
                f"({type(exc).__name__}); se inició en CPU.")
            self.dispositivo = "cpu"
            self._reader = easyocr.Reader(
                [self._lang], gpu=False, verbose=False,
                quantize=not bool(self.modelo_visual))
        self.dispositivo = str(getattr(self._reader, "device", self.dispositivo))
        solicitado_batch = int(rendimiento.get(
            "batch_cpu" if self.dispositivo == "cpu" else "batch_gpu", 1))
        if self.dispositivo == "cpu":
            self._batch_size = max(1, solicitado_batch)
            self._batch_max = self._batch_size
        else:
            techo_cfg = int(rendimiento.get(
                "batch_gpu_max", self.recursos.get("batch_gpu_max_seguro", solicitado_batch)))
            techo_hw = int(self.recursos.get("batch_gpu_max_seguro", techo_cfg))
            self._batch_max = max(1, min(techo_cfg, techo_hw))
            self._batch_size = max(1, min(solicitado_batch, self._batch_max))
        self._workers = int(rendimiento.get("workers_easyocr", 0))
        self._allowlist = cfg_fase1.get("caracteres_permitidos") or None
        self._gestor_metricas().actualizar_batch(self._batch_size)
        if self.modelo_visual:
            try:
                import torch
                ruta_pesos = Path(self.modelo_visual["ruta_pesos"])
                self._reader.recognizer.load_state_dict(torch.load(
                    ruta_pesos, map_location=self.dispositivo, weights_only=True))
            except Exception as exc:
                self.advertencias.append(
                    f"No se pudo cargar el modelo visual {self.modelo_visual.get('version')} "
                    f"({type(exc).__name__}); se usó EasyOCR base.")
                self.modelo_visual = None

    def _obtener_reader_cpu(self):
        """Crea un Reader CPU sólo cuando una tarea aislada no cabe en GPU."""
        if self.dispositivo == "cpu":
            return self._reader
        if self._reader_cpu is None:
            self._reader_cpu = self._easyocr.Reader(
                [self._lang], gpu=False, verbose=False, quantize=not bool(self.modelo_visual))
            if self.modelo_visual:
                import torch
                self._reader_cpu.recognizer.load_state_dict(torch.load(
                    self.modelo_visual["ruta_pesos"], map_location="cpu", weights_only=True))
        return self._reader_cpu

    def _gestor_metricas(self):
        gestor = getattr(self, "_gestor", None)
        if gestor is None:
            from gestor_recursos import obtener_gestor_recursos
            gestor = obtener_gestor_recursos(getattr(self, "_perfil_sop", "alto"))
            self._gestor = gestor
        return gestor

    @staticmethod
    def _es_oom(exc: Exception) -> bool:
        mensaje = str(exc).lower()
        return "out of memory" in mensaje or "cuda error: out of memory" in mensaje

    def _limpiar_cache_cuda(self) -> None:
        """Libera caché no referenciada; no pretende liberar tensores aún vivos."""
        if self.dispositivo != "cuda":
            return
        try:
            import gc
            import torch
            gc.collect()
            torch.cuda.empty_cache()
        except Exception:
            pass

    def _registrar_exito_gpu(self) -> None:
        if self.dispositivo != "cuda":
            return
        self._fallos_cuda_consecutivos = 0
        self._exitos_desde_ajuste = getattr(self, "_exitos_desde_ajuste", 0) + 1
        if self._exitos_desde_ajuste < getattr(self, "_ventana_batch", 12):
            return
        self._exitos_desde_ajuste = 0
        if self._batch_size >= self._batch_max or self._gestor_metricas().vram_bajo_presion():
            return
        anterior = self._batch_size
        self._batch_size = min(self._batch_max, self._batch_size + 1)
        if self._batch_size != anterior:
            self.advertencias.append(
                f"Batch EasyOCR aumentado de {anterior} a {self._batch_size} tras una ventana estable.")
            self._gestor_metricas().actualizar_batch(self._batch_size)

    def _leer_cpu_temporal(self, imagen_bgr: np.ndarray, opciones: dict, causa: Exception):
        self._gestor_metricas().registrar_fallback_cpu()
        self.advertencias.append(
            f"Una tarea se derivó temporalmente a CPU tras {type(causa).__name__}; "
            "CUDA se conserva para las siguientes imágenes.")
        reader = self._obtener_reader_cpu()
        return reader.readtext(imagen_bgr, detail=1, batch_size=1, workers=0, **opciones)

    def _leer(self, imagen_bgr: np.ndarray, usar_allowlist: bool) -> list[dict]:
        # Import local intencional: algunas pruebas de compatibilidad extraen este
        # método de forma aislada mediante AST. Así sigue siendo autocontenido.
        import time as _time

        opciones = ({"allowlist": self._allowlist}
                    if usar_allowlist and self._allowlist else {})
        inicio = _time.monotonic()
        dispositivo_usado = self.dispositivo
        intentos_oom = 0
        while True:
            try:
                with warnings.catch_warnings():
                    if self.dispositivo == "mps":
                        warnings.filterwarnings(
                            "ignore", message=".*pin_memory.*not supported on MPS.*",
                            category=UserWarning)
                    lecturas = self._reader.readtext(
                        imagen_bgr, detail=1, batch_size=self._batch_size,
                        workers=self._workers, **opciones)
                # En CPU no hay regulación de batch GPU. El hasattr conserva el
                # contrato del adaptador cuando este método se prueba de forma aislada.
                if self.dispositivo != "cpu" and hasattr(self, "_registrar_exito_gpu"):
                    self._registrar_exito_gpu()
                break
            except RuntimeError as exc:
                if self.dispositivo == "cpu":
                    raise
                if self.dispositivo == "cuda" and self._es_oom(exc):
                    intentos_oom += 1
                    self._gestor_metricas().registrar_oom()
                    self._fallos_cuda_consecutivos = getattr(self, "_fallos_cuda_consecutivos", 0) + 1
                    self._exitos_desde_ajuste = 0
                    if self._batch_size > 1 and intentos_oom <= getattr(self, "_reintentos_oom", 3):
                        anterior = self._batch_size
                        self._batch_size = max(1, self._batch_size // 2)
                        self._gestor_metricas().actualizar_batch(self._batch_size)
                        self._limpiar_cache_cuda()
                        self.advertencias.append(
                            f"CUDA OOM por presión de VRAM con batch {anterior}; reintento controlado con batch {self._batch_size}.")
                        continue
                    self._limpiar_cache_cuda()
                    dispositivo_usado = "cpu"
                    lecturas = self._leer_cpu_temporal(imagen_bgr, opciones, exc)
                    break
                # Error CUDA no clasificado: no destruir el Reader GPU por un único fallo.
                self._fallos_cuda_consecutivos = getattr(self, "_fallos_cuda_consecutivos", 0) + 1
                dispositivo_usado = "cpu"
                lecturas = self._leer_cpu_temporal(imagen_bgr, opciones, exc)
                break
        if hasattr(self, "_gestor_metricas"):
            self._gestor_metricas().registrar_etapa(
                "inferencia_gpu" if dispositivo_usado in {"cuda", "mps"} else "inferencia_cpu",
                _time.monotonic() - inicio)
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

    def detectar(self, imagen_bgr: np.ndarray) -> list[dict]:
        """Expone CRAFT sin ejecutar el reconocedor de EasyOCR."""
        inicio = time.monotonic()
        usado_cpu = False
        try:
            horizontales, libres = self._reader.detect(
                imagen_bgr, min_size=10, text_threshold=0.55,
                low_text=0.30, link_threshold=0.35)
        except RuntimeError as exc:
            if self.dispositivo == "cpu":
                raise
            usado_cpu = True
            reader = self._obtener_reader_cpu()
            horizontales, libres = reader.detect(imagen_bgr, min_size=10)
            self._gestor_metricas().registrar_fallback_cpu()
            self.advertencias.append(
                f"Detección CRAFT derivada temporalmente a CPU tras {type(exc).__name__}.")
        self._gestor_metricas().registrar_etapa(
            "deteccion_cpu" if usado_cpu or self.dispositivo == "cpu" else "deteccion_gpu",
            time.monotonic() - inicio)
        hs = horizontales[0] if horizontales and isinstance(horizontales[0], list) else horizontales
        fs = libres[0] if libres and isinstance(libres[0], list) else libres
        cajas = []
        for caja in hs or []:
            if len(caja) != 4:
                continue
            x1, x2, y1, y2 = (int(round(float(v))) for v in caja)
            cajas.append({"bbox": (x1, y1, max(1, x2 - x1), max(1, y2 - y1)),
                          "poligono": None})
        for puntos in fs or []:
            pts = np.asarray(puntos, dtype=np.float32).reshape(-1, 2)
            x1, y1 = pts.min(axis=0)
            x2, y2 = pts.max(axis=0)
            cajas.append({"bbox": (int(x1), int(y1), max(1, int(x2 - x1)),
                                    max(1, int(y2 - y1))),
                          "poligono": pts.tolist()})
        return cajas


def obtener_motor(config: dict | None = None):
    """Retorna el primer motor configurado que pueda inicializarse."""
    config = config or cargar_config()
    f1 = config.get("fase1", {})
    recursos = detectar_recursos(f1.get("dispositivo", "auto"))
    from aprendizaje import GestorAprendizaje
    modelo_visual = GestorAprendizaje(config).modelo_visual_activo()
    for clave in ("motor", "motor_fallback"):
        nombre = f1.get(clave) if clave == "motor" else f1.get("motor_fallback")
        if not nombre:
            continue
        llave = (nombre, recursos["seleccionado"] if nombre == "easyocr" else "auto",
                 (modelo_visual or {}).get("version") if nombre == "easyocr" else None)
        if llave in _MOTORES:
            return _MOTORES[llave], f1
        clase = {"paddle": MotorPaddle, "easyocr": MotorEasyOCR}.get(nombre)
        if clase is None:
            continue
        try:
            cfg_motor = {**f1, "_modelo_visual_activo": modelo_visual}
            _MOTORES[llave] = clase(cfg_motor)
            return _MOTORES[llave], f1
        except Exception as exc:  # ImportError u otro fallo de arranque del motor
            print(f"[ocr_engine] motor '{nombre}' no disponible ({exc}); probando fallback",
                  file=sys.stderr)
    raise RuntimeError("EasyOCR no está disponible. Revisa la instalación del entorno.")


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


def detectar_qrs(imagen_bgr: np.ndarray, cfg_qr: dict) -> list[dict]:
    """Detecta y decodifica uno o varios QR, siempre de forma local y pasiva."""
    alto, ancho = imagen_bgr.shape[:2]
    lado_max = max(alto, ancho)
    detector = cv2.QRCodeDetector()
    resultados: list[dict] = []
    lado_thumb = max(320, int(cfg_qr.get("lado_maximo_deteccion", 1400)))
    escala_thumb = min(1.0, lado_thumb / max(lado_max, 1))
    miniatura = (cv2.resize(imagen_bgr, None, fx=escala_thumb, fy=escala_thumb,
                            interpolation=cv2.INTER_AREA)
                 if escala_thumb < 0.999 else imagen_bgr)

    def agregar(payload: str, puntos, escala: float, intento: str) -> None:
        if puntos is None:
            return
        pts = np.asarray(puntos, dtype=np.float32).reshape(-1, 2) / max(escala, 1e-9)
        x1, y1 = pts.min(axis=0)
        x2, y2 = pts.max(axis=0)
        bbox = (max(0, int(x1)), max(0, int(y1)),
                max(1, int(x2 - x1)), max(1, int(y2 - y1)))
        w, h = bbox[2], bbox[3]
        ratio = w / max(h, 1)
        if not (float(cfg_qr.get("ratio_cuadrado_min", 0.55)) <= ratio <=
                float(cfg_qr.get("ratio_cuadrado_max", 1.55))):
            return
        if max(w, h) > float(cfg_qr.get("tamano_max_frac", 0.9)) * lado_max:
            return
        if not str(payload or "").strip() and min(w, h) < int(cfg_qr.get("tamano_min_px", 24)):
            return
        payload_limpio = str(payload or "").strip()
        for existente in resultados:
            eb = existente.get("bbox")
            if existente.get("payload") != payload_limpio or eb is None:
                continue
            ex, ey, ew, eh = eb
            ix1, iy1 = max(bbox[0], ex), max(bbox[1], ey)
            ix2, iy2 = min(bbox[0] + w, ex + ew), min(bbox[1] + h, ey + eh)
            inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
            union = w * h + ew * eh - inter
            if union and inter / union >= 0.5:
                return
        resultados.append({"payload": payload_limpio, "bbox": bbox,
                           "poligono": pts.round(2).tolist(), "intento": intento})

    for imagen, escala, nombre in ((miniatura, escala_thumb, "miniatura"),
                                    (imagen_bgr, 1.0, "completa")):
        try:
            ok, textos, puntos, _ = detector.detectAndDecodeMulti(imagen)
            if ok and puntos is not None:
                for payload, poligono in zip(textos or (), puntos):
                    agregar(payload, poligono, escala, nombre + "_multiple")
        except (cv2.error, ValueError):
            pass
        try:
            payload, puntos, _ = detector.detectAndDecode(imagen)
            if puntos is not None:
                agregar(payload, puntos, escala, nombre + "_unico")
        except (cv2.error, ValueError):
            pass
        if resultados and any(r["payload"] for r in resultados):
            break

    # Los QR pequeños o girados pueden detectarse sólo tras ampliar/rotar.
    if not any(r["payload"] for r in resultados):
        factor = max(1.0, float(cfg_qr.get("escala_respaldo", 2.0)))
        base = cv2.resize(imagen_bgr, None, fx=factor, fy=factor,
                          interpolation=cv2.INTER_CUBIC)
        for angulo in (0, 90, 180, 270):
            intento = _rotar_recto(base, angulo)
            try:
                payload, puntos, _ = detector.detectAndDecode(intento)
            except cv2.error:
                continue
            if payload and puntos is not None:
                # En respaldo importa preservar el payload; la caja rotada se
                # marca como aproximada para no emplearla como ROI espacial.
                resultados.append({"payload": payload.strip(), "bbox": None,
                                   "poligono": None, "intento": f"respaldo_{angulo}",
                                   "bbox_aproximada": True})
                break
    return resultados


def detectar_qr(imagen_bgr: np.ndarray, cfg_qr: dict) -> tuple | None:
    """Compatibilidad: devuelve la primera caja QR disponible."""
    return next((tuple(qr["bbox"]) for qr in detectar_qrs(imagen_bgr, cfg_qr)
                 if qr.get("bbox") is not None), None)


def estimar_skew(gris: np.ndarray, angulo_max: float = 15.0) -> float:
    """Estima la inclinación dominante del texto con morfología + minAreaRect.

    El deskew global conserva el límite histórico de ±15°. Las regiones de
    etiqueta pueden solicitar hasta ±45° para cubrir texto diagonal sin barrer
    todos los grados ni imponer esa inclinación al resto de la fotografía.
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
        if abs(ang) <= float(angulo_max):
            angulos.append(ang)
    return float(statistics.median(angulos)) if angulos else 0.0



def _evidencia_skew(gris: np.ndarray, estimado: float, angulo_max: float = 30.0) -> dict:
    """Mide soporte geométrico del ángulo sin volver a decidir la lectura OCR.

    Se usa únicamente para permitir correcciones regionales mayores de ±15°.
    Un contorno grande alineado con el ángulo puede ser suficiente; varios
    contornos coherentes aumentan la confianza.  Esto evita aceptar un ±35/45°
    provocado por una arista del fondo o por ruido de la fotografía.
    """
    if gris is None or getattr(gris, "size", 0) == 0:
        return {"soporte": 0, "dispersion": 180.0, "cobertura": 0.0, "fuerte": False}
    binaria = cv2.adaptiveThreshold(gris, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY_INV, 31, 15)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, gris.shape[1] // 25), 1))
    dilatada = cv2.dilate(binaria, kernel, iterations=1)
    contornos, _ = cv2.findContours(dilatada, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    compatibles = []
    area_total = 0.0
    area_imagen = float(max(1, gris.shape[0] * gris.shape[1]))
    objetivo = float(estimado)
    for cnt in contornos:
        area = float(cv2.contourArea(cnt))
        if area < 300:
            continue
        (_, _), (w, h), ang = cv2.minAreaRect(cnt)
        if w < h:
            ang = (ang + 90) % 180
        if ang > 90:
            ang -= 180
        if abs(ang) > float(angulo_max):
            continue
        # Distancia angular en el dominio de líneas (180° equivalentes).
        delta = abs(((float(ang) - objetivo + 90) % 180) - 90)
        if delta <= 7.5:
            compatibles.append((float(ang), area))
            area_total += area
    if not compatibles:
        return {"soporte": 0, "dispersion": 180.0, "cobertura": 0.0, "fuerte": False}
    angulos = [a for a, _ in compatibles]
    dispersion = float(statistics.median(abs(a - objetivo) for a in angulos))
    cobertura = min(1.0, area_total / area_imagen)
    soporte = len(compatibles)
    fuerte = bool((soporte >= 2 and dispersion <= 5.0 and cobertura >= .015)
                  or (soporte >= 1 and dispersion <= 3.0 and cobertura >= .06))
    return {"soporte": soporte, "dispersion": round(dispersion, 3),
            "cobertura": round(cobertura, 4), "fuerte": fuerte}


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
    from flujo_empresarial import clasificar_codigo_operativo
    candidatos = []
    for token in segmentar_tokens(lineas, umbral_espacio_px):
        evaluacion = clasificar_codigo_operativo(token["texto"])
        if evaluacion["valido"]:
            candidatos.append({**token, "clasificacion_codigo": evaluacion})
    return candidatos


def _resumen_codigos(tokens: list[dict]) -> list[dict]:
    from flujo_empresarial import clasificar_codigo_operativo
    salida = []
    vistos = set()
    for token in tokens:
        evaluacion = clasificar_codigo_operativo(token.get("texto", ""))
        firma = (evaluacion["normalizado"], evaluacion["tipo"])
        if firma in vistos:
            continue
        vistos.add(firma)
        salida.append({**evaluacion, "bbox": token.get("bbox"),
                       "confianza": token.get("confianza")})
    return salida


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


def rotar_imagen_libre_con_matriz(imagen_bgr: np.ndarray, grados: float) -> tuple[np.ndarray, np.ndarray]:
    """Gira cualquier ángulo y devuelve también la matriz homogénea entrada→salida.

    El lienzo se expande para no recortar etiquetas diagonales. La matriz permite
    reproyectar posteriormente las cajas OCR a las coordenadas originales.
    """
    angulo = float(grados)
    normalizado = angulo % 360
    alto, ancho = imagen_bgr.shape[:2]
    if abs(normalizado) < 1e-6:
        return imagen_bgr, np.eye(3, dtype=float)
    matriz = cv2.getRotationMatrix2D((ancho / 2.0, alto / 2.0), -angulo, 1.0)
    coseno, seno = abs(matriz[0, 0]), abs(matriz[0, 1])
    nuevo_ancho = int(np.ceil(alto * seno + ancho * coseno))
    nuevo_alto = int(np.ceil(alto * coseno + ancho * seno))
    matriz[0, 2] += nuevo_ancho / 2.0 - ancho / 2.0
    matriz[1, 2] += nuevo_alto / 2.0 - alto / 2.0
    salida = cv2.warpAffine(
        imagen_bgr, matriz, (nuevo_ancho, nuevo_alto), flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE)
    homogenea = np.vstack([matriz, [0.0, 0.0, 1.0]])
    return salida, homogenea


def rotar_imagen_libre(imagen_bgr: np.ndarray, grados: float) -> np.ndarray:
    """Gira en sentido horario cualquier ángulo y expande el lienzo sin recortar."""
    angulo = float(grados) % 360
    if abs(angulo) < 1e-6:
        return imagen_bgr
    if any(abs(angulo - recto) < 1e-6 for recto in (90, 180, 270)):
        return _rotar_recto(imagen_bgr, int(round(angulo)))
    return rotar_imagen_libre_con_matriz(imagen_bgr, grados)[0]


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


def _roi_proporcional(imagen: np.ndarray, roi: dict | None) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """Convierte una ROI 0..1 a píxeles, validando que permanezca dentro de la foto."""
    alto, ancho = imagen.shape[:2]
    roi = roi or {"x": 0, "y": 0, "ancho": 1, "alto": 1}
    valores = [float(roi.get(k, d)) for k, d in (("x", 0), ("y", 0), ("ancho", 1), ("alto", 1))]
    x, y, w, h = valores
    if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1 and x + w <= 1.0001 and y + h <= 1.0001):
        raise ValueError("La ROI manual debe usar proporciones entre 0 y 1.")
    caja = (int(x * ancho), int(y * alto), max(1, int(w * ancho)), max(1, int(h * alto)))
    px, py, pw, ph = caja
    return imagen[py:py + ph, px:px + pw], caja


def _recorte_perspectiva(imagen: np.ndarray, puntos, devolver_matriz=False):
    """Endereza un cuadrilátero de CRAFT; usa el recorte rectangular si es degenerado."""
    pts = np.asarray(puntos, dtype=np.float32).reshape(4, 2)
    suma, diferencia = pts.sum(axis=1), np.diff(pts, axis=1).reshape(-1)
    orden = np.array([pts[np.argmin(suma)], pts[np.argmin(diferencia)],
                      pts[np.argmax(suma)], pts[np.argmax(diferencia)]], dtype=np.float32)
    tl, tr, br, bl = orden
    ancho = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    alto = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    if ancho < 2 or alto < 2:
        vacio = np.empty((0, 0, 3), dtype=imagen.dtype)
        return (vacio, None) if devolver_matriz else vacio
    destino = np.array([[0, 0], [ancho - 1, 0], [ancho - 1, alto - 1], [0, alto - 1]],
                       dtype=np.float32)
    matriz = cv2.getPerspectiveTransform(orden, destino)
    if not np.isfinite(matriz).all() or abs(np.linalg.det(matriz)) < 1e-10:
        vacio = np.empty((0, 0, 3), dtype=imagen.dtype)
        return (vacio, None) if devolver_matriz else vacio
    recorte = cv2.warpPerspective(imagen, matriz, (ancho, alto))
    return (recorte, np.linalg.inv(matriz)) if devolver_matriz else recorte


def _bbox_proyectada(bbox, matriz):
    x, y, w, h = bbox
    puntos = np.array([[[x,y],[x+w,y],[x+w,y+h],[x,y+h]]], dtype=np.float32)
    puntos = cv2.perspectiveTransform(puntos, np.asarray(matriz, dtype=np.float64))[0]
    minimo, maximo = np.floor(puntos.min(axis=0)), np.ceil(puntos.max(axis=0))
    return [int(minimo[0]), int(minimo[1]), max(1,int(maximo[0]-minimo[0])), max(1,int(maximo[1]-minimo[1]))]


def _clasificar_informacion_region(texto: str, confianza: float | None = None) -> dict:
    """Clasifica una lectura regional por utilidad empresarial, sin ocultarla.

    V14.6 separa dos preguntas que antes se mezclaban: ``qué tan confiado está
    el OCR`` y ``qué tan congruente es el contenido``.  Esto evita premiar
    cadenas largas de ruido o fragmentos cortos sólo por un porcentaje alto.
    La clasificación es deliberadamente conservadora: todo candidato sigue
    disponible en el editor, pero puede etiquetarse como código, fecha, valor,
    texto o ruido para facilitar la revisión humana.
    """
    from flujo_empresarial import clasificar_codigo_operativo

    original = str(texto or "").strip()
    conf = max(0.0, min(1.0, float(confianza or 0.0)))
    compacto = re.sub(r"\s+", "", original)
    letras = [c for c in compacto if c.isalpha()]
    digitos = sum(c.isdigit() for c in compacto)
    mayus = any(c.isupper() for c in letras)
    minus = any(c.islower() for c in letras)
    caso_coherente = not (mayus and minus)
    total = max(1, len(compacto))
    permitidos_codigo = sum(bool(re.fullmatch(r"[A-Za-z0-9._/+-]", c)) for c in compacto)
    pureza_codigo = permitidos_codigo / total
    simbolos_fuertes = sum(c in "%:;,=!?@#$&*()[]{}<>\\|\"'" for c in compacto)
    razon = []

    if not original:
        return {"tipo_informacion": "ruido", "etiqueta_informacion": "Sin lectura",
                "score_informacion": 0.0, "es_ruido": True, "razones": ["Sin caracteres"],
                "normalizado": "", "caso_coherente": True, "pureza_codigo": 0.0,
                "probable_codigo": False, "tipo_codigo": "vacio"}

    mayus_texto = original.upper().replace("−", "-")
    meses = r"JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC|ENE|ABR|AGO|DIC"
    patron_fecha = re.compile(
        rf"(?:^|\b)\d{{1,2}}\s*[/.-]\s*(?:\d{{1,2}}|{meses})(?:\s*[/.-]\s*\d{{2,4}})?(?:\b|$)",
        re.IGNORECASE)
    if patron_fecha.search(mayus_texto):
        score = min(98.0, 76.0 + conf * 18.0 + (4.0 if re.search(r"\d{2,4}\s*$", mayus_texto) else 0.0))
        return {"tipo_informacion": "fecha", "etiqueta_informacion": "Fecha probable",
                "score_informacion": round(score, 2), "es_ruido": False,
                "razones": ["Patrón de fecha reconocible"], "normalizado": mayus_texto,
                "caso_coherente": caso_coherente, "pureza_codigo": pureza_codigo,
                "probable_codigo": False, "tipo_codigo": "fecha"}

    if re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?\s*(?:%|MS|S|°?C|V|A|N|MM|CM)?", mayus_texto):
        unidad = bool(re.search(r"(?:%|MS|S|°?C|V|A|N|MM|CM)\s*$", mayus_texto))
        # Secuencias numéricas compactas de cuatro o más dígitos suelen ser
        # seriales/códigos en este proyecto; valores con unidad no se confunden.
        if not unidad and re.fullmatch(r"\d{4,}", compacto):
            score = min(99.0, 82.0 + min(10, len(compacto)) * 0.8 + conf * 9.0)
            return {"tipo_informacion": "codigo", "etiqueta_informacion": "Código numérico probable",
                    "score_informacion": round(score, 2), "es_ruido": False,
                    "razones": ["Secuencia numérica compacta"], "normalizado": compacto,
                    "caso_coherente": True, "pureza_codigo": 1.0,
                    "probable_codigo": True, "tipo_codigo": "numerico_probable"}
        score = min(92.0, 58.0 + conf * 25.0 + (7.0 if unidad else 0.0))
        return {"tipo_informacion": "numero", "etiqueta_informacion": "Valor / medición",
                "score_informacion": round(score, 2), "es_ruido": False,
                "razones": ["Valor numérico" + (" con unidad" if unidad else "")],
                "normalizado": compacto, "caso_coherente": True,
                "pureza_codigo": pureza_codigo, "probable_codigo": False,
                "tipo_codigo": "valor_numerico"}

    evaluacion = clasificar_codigo_operativo(original)
    tipo_codigo = str(evaluacion.get("tipo") or "texto")
    alfanumerico_compacto = bool(
        4 <= len(compacto) <= 32 and letras and digitos and caso_coherente
        and pureza_codigo >= .98 and simbolos_fuertes == 0
        and re.fullmatch(r"[A-Za-z0-9._/+-]+", compacto))
    if evaluacion.get("valido") and tipo_codigo == "catalogo":
        return {"tipo_informacion": "codigo", "etiqueta_informacion": "Código de catálogo",
                "score_informacion": round(min(99.0, 92.0 + conf * 7.0), 2),
                "es_ruido": False, "razones": [str(evaluacion.get("razon") or "Catálogo conocido")],
                "normalizado": str(evaluacion.get("normalizado") or compacto),
                "caso_coherente": caso_coherente, "pureza_codigo": pureza_codigo,
                "probable_codigo": True, "tipo_codigo": tipo_codigo}
    if alfanumerico_compacto or (evaluacion.get("valido") and caso_coherente and simbolos_fuertes == 0):
        score = 80.0 + conf * 10.0 + min(8.0, len(compacto) * .35)
        if not caso_coherente:
            score -= 25.0
        return {"tipo_informacion": "codigo", "etiqueta_informacion": "Código alfanumérico probable",
                "score_informacion": round(min(99.0, score), 2), "es_ruido": False,
                "razones": ["Letras y números compactos", "Mayúsculas/minúsculas coherentes"],
                "normalizado": str(evaluacion.get("normalizado") or compacto),
                "caso_coherente": caso_coherente, "pureza_codigo": pureza_codigo,
                "probable_codigo": True, "tipo_codigo": tipo_codigo if evaluacion.get("valido") else "alfanumerico_probable"}

    # Cadenas alfanuméricas largas con mezcla arbitraria de mayúsculas y
    # minúsculas son un patrón común de falso positivo en las fotos reales.
    mezcla_sospechosa = bool(letras and digitos and not caso_coherente and len(compacto) >= 6)
    densidad_simbolos = simbolos_fuertes / total
    if mezcla_sospechosa or densidad_simbolos > .08 or pureza_codigo < .72:
        if mezcla_sospechosa:
            razon.append("Mezcla irregular de mayúsculas/minúsculas")
        if densidad_simbolos > .08:
            razon.append("Demasiados símbolos para un código")
        if pureza_codigo < .72:
            razon.append("Baja pureza alfanumérica")
        return {"tipo_informacion": "ruido", "etiqueta_informacion": "Ruido probable",
                "score_informacion": round(min(38.0, 12.0 + conf * 20.0), 2),
                "es_ruido": True, "razones": razon or ["Formato poco congruente"],
                "normalizado": compacto, "caso_coherente": caso_coherente,
                "pureza_codigo": pureza_codigo, "probable_codigo": False,
                "tipo_codigo": "ruido"}

    # Texto normal no se descarta: sólo se separa de códigos y mediciones.
    palabras = re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{2,}", original)
    if palabras:
        score = min(88.0, 48.0 + conf * 28.0 + min(10.0, len("".join(palabras)) * .3))
        return {"tipo_informacion": "texto", "etiqueta_informacion": "Texto probable",
                "score_informacion": round(score, 2), "es_ruido": False,
                "razones": ["Texto legible no clasificado como código"],
                "normalizado": original, "caso_coherente": caso_coherente,
                "pureza_codigo": pureza_codigo, "probable_codigo": False,
                "tipo_codigo": tipo_codigo}

    return {"tipo_informacion": "ruido", "etiqueta_informacion": "Fragmento / ruido",
            "score_informacion": round(min(42.0, 10.0 + conf * 28.0), 2),
            "es_ruido": True, "razones": ["Fragmento demasiado corto o ambiguo"],
            "normalizado": compacto, "caso_coherente": caso_coherente,
            "pureza_codigo": pureza_codigo, "probable_codigo": False,
            "tipo_codigo": "fragmento"}


def _clave_perfil_region(perfil: dict) -> tuple:
    """Ordena utilidad semántica antes que la confianza aislada del OCR."""
    tipo = str(perfil.get("tipo_informacion") or "ruido")
    prioridad = {"codigo": 5, "fecha": 4, "numero": 3, "texto": 2, "ruido": 0}.get(tipo, 1)
    consenso = int(perfil.get("consenso") or 1)
    return (
        int(prioridad),
        int(bool(perfil.get("probable_codigo"))),
        int(bool(perfil.get("mayus_minus_coherente", True))),
        int(min(4, consenso)),
        round(float(perfil.get("pureza") or 0.0), 4),
        round(float(perfil.get("score_informacion") or 0.0), 2),
        int(min(24, int(perfil.get("longitud") or 0))),
        round(float(perfil.get("confianza") or 0.0), 4),
    )


def _perfil_congruencia_region(lecturas: list[dict], confianza: float | None = None) -> dict:
    """Evalúa congruencia y tipo de información de una lectura regional."""
    renglones = reconstruir_lineas_texto(lecturas or [])
    textos = [str(l.get("texto") or "").strip() for l in renglones]
    textos = [t for t in textos if t]
    if not textos:
        vacio = {
            "nivel": 0, "longitud": 0, "confianza": float(confianza or 0),
            "probable_codigo": False, "tipo": "vacio", "texto": "",
            "mayus_minus_coherente": True, "pureza": 0.0, "consenso": 1,
            "tipo_informacion": "ruido", "etiqueta_informacion": "Sin lectura",
            "score_informacion": 0.0, "es_ruido": True, "razones": ["Sin caracteres"],
        }
        vacio["clave"] = _clave_perfil_region(vacio)
        return vacio

    opciones = list(textos)
    if len(textos) > 1:
        opciones.append("".join(re.sub(r"\s+", "", t) for t in textos))

    mejor = None
    for texto in opciones:
        compacto = re.sub(r"\s+", "", texto).strip()
        if not compacto:
            continue
        info = _clasificar_informacion_region(texto, confianza)
        tipo_info = info["tipo_informacion"]
        nivel = {"codigo": 4, "fecha": 3, "numero": 2, "texto": 1, "ruido": 0}.get(tipo_info, 0)
        candidato = {
            "nivel": nivel, "longitud": len(compacto),
            "confianza": float(confianza or 0),
            "probable_codigo": bool(info.get("probable_codigo")),
            "tipo": str(info.get("tipo_codigo") or tipo_info), "texto": texto,
            "mayus_minus_coherente": bool(info.get("caso_coherente", True)),
            "pureza": round(float(info.get("pureza_codigo") or 0.0), 4),
            "consenso": 1, "similitud_consenso": 0.0,
            "tipo_informacion": tipo_info,
            "etiqueta_informacion": str(info.get("etiqueta_informacion") or tipo_info),
            "score_informacion": float(info.get("score_informacion") or 0.0),
            "es_ruido": bool(info.get("es_ruido")),
            "razones": list(info.get("razones") or []),
        }
        candidato["clave"] = _clave_perfil_region(candidato)
        if mejor is None or candidato["clave"] > mejor["clave"]:
            mejor = candidato
    return mejor


def _agregar_consenso_orientaciones(candidatas: list[dict], usar_base: bool = True) -> None:
    """Añade un bono pequeño cuando variantes independientes leen algo parecido."""
    from difflib import SequenceMatcher

    perfiles = []
    for c in candidatas:
        p = c.get("congruencia_base" if usar_base else "congruencia") or {}
        normal = re.sub(r"[^A-Za-z0-9]", "", str(p.get("texto") or "")).upper()
        perfiles.append((c, p, normal))
    for _, perfil, normal in perfiles:
        if len(normal) < 4 or perfil.get("es_ruido"):
            perfil["consenso"] = 1
            perfil["similitud_consenso"] = 0.0
            perfil["clave"] = _clave_perfil_region(perfil)
            continue
        coincidencias = 1
        mejor_sim = 0.0
        for _, otro, normal_otro in perfiles:
            if otro is perfil or len(normal_otro) < 4 or otro.get("es_ruido"):
                continue
            ratio = SequenceMatcher(None, normal, normal_otro).ratio()
            mejor_sim = max(mejor_sim, ratio)
            if ratio >= .82:
                coincidencias += 1
        perfil["consenso"] = coincidencias
        perfil["similitud_consenso"] = round(mejor_sim, 3)
        perfil["clave"] = _clave_perfil_region(perfil)

def _clave_orientacion_region(candidata: dict, usar_base: bool = False) -> tuple:
    """Clave estable para comparar orientaciones sin sobrerreaccionar a confianza."""
    perfil = (candidata.get("congruencia_base") if usar_base
              else candidata.get("congruencia")) or {}
    clave = tuple(perfil.get("clave") or (0, 1, 0.0, 0, 0.0))
    # Como desempate final conserva la cobertura OCR ya existente.
    return (*clave, int(candidata.get("caracteres_base" if usar_base else "caracteres") or 0))


def _leer_recorte_orientado(imagen, motor, permitir_giro=True, margen=.08,
                            orientacion_forzada=None, ajuste_fino=True,
                            ajuste_fino_todas=False, angulo_fino_max=15.0,
                            angulo_fino_min=1.25, angulo_fino_extendido_max=30.0,
                            micro_ajuste_grados=2.0, estrategia_preferida=None):
    """Compara orientación cardinal y corrige inclinación fina de la región.

    Se mantienen cuatro orientaciones base (0/90/180/270) para no cambiar el
    flujo del editor. Cuando se detecta una etiqueta sesgada, se prueba además
    un deskew local de hasta ``angulo_fino_max`` grados. En el procesamiento
    normal sólo se refina la mejor orientación cardinal; el panel de variantes
    puede pedir ``ajuste_fino_todas=True`` para que cada una de sus cuatro
    tarjetas tenga su mejor ajuste fino. Las cajas siempre vuelven al marco
    original del recorte.
    """
    # Algunas pruebas de regresión reutilizan esta función aislándola mediante
    # AST. En ese contexto los helpers V14.4 no están en el diccionario global;
    # se recuperan del módulo real sin cambiar el comportamiento de producción.
    perfil_congruencia = globals().get("_perfil_congruencia_region")
    clave_orientacion = globals().get("_clave_orientacion_region")
    agregar_consenso = globals().get("_agregar_consenso_orientaciones")
    evidencia_skew = globals().get("_evidencia_skew")
    if not callable(perfil_congruencia) or not callable(clave_orientacion):
        from ocr_engine import (
            _perfil_congruencia_region as perfil_congruencia,
            _clave_orientacion_region as clave_orientacion,
        )
    if not callable(agregar_consenso):
        try:
            from ocr_engine import _agregar_consenso_orientaciones as agregar_consenso
        except ImportError:
            agregar_consenso = None
    if not callable(evidencia_skew):
        try:
            from ocr_engine import _evidencia_skew as evidencia_skew
        except ImportError:
            evidencia_skew = None

    alto, ancho = imagen.shape[:2]
    matrices_a_original = {
        0: np.eye(3),
        90: np.array([[0,1,0],[-1,0,alto],[0,0,1]], dtype=float),
        180: np.array([[-1,0,ancho],[0,-1,alto],[0,0,1]], dtype=float),
        270: np.array([[0,-1,ancho],[1,0,0],[0,0,1]], dtype=float),
    }

    if orientacion_forzada is not None and orientacion_forzada not in (0,90,180,270):
        raise ValueError("Orientación regional no válida")

    def leer(vista):
        lecturas = motor.leer_texto_completo(vista)
        if not lecturas or max(float(l.get("confianza") or 0) for l in lecturas) < .45:
            alternativa = motor.leer_texto_completo(aplicar_variante(vista, "clahe", {}))
            if _calidad(alternativa) > _calidad(lecturas):
                lecturas = alternativa
        pesos = [min(32, len(str(l.get("texto", "")).strip())) for l in lecturas]
        puntuacion = sum(float(l.get("confianza") or 0)*p for l,p in zip(lecturas,pesos)) / max(1,sum(pesos))
        caracteres = sum(max(0, p) for p in pesos)
        return lecturas, float(puntuacion), int(caracteres)

    bases = ([orientacion_forzada] if orientacion_forzada is not None else
             [0,90,180,270] if permitir_giro else [0])
    candidatas = []
    vistas_base = {}
    for angulo in bases:
        vista = imagen if angulo == 0 else _rotar_recto(imagen, angulo)
        vistas_base[angulo] = vista
        lecturas, puntuacion, caracteres = leer(vista)
        congruencia = perfil_congruencia(lecturas, puntuacion)
        candidatas.append({
            "puntuacion": puntuacion, "caracteres": caracteres,
            "puntuacion_base": puntuacion, "caracteres_base": caracteres,
            "grados": int(angulo), "grados_efectivos": float(angulo),
            "ajuste_fino_grados": 0.0, "lecturas": lecturas,
            "lecturas_base": list(lecturas),
            "congruencia": congruencia, "congruencia_base": dict(congruencia),
            "matriz_a_original": matrices_a_original[int(angulo)],
            "ajuste_fino_confiable": False, "ajuste_fino_modo": "ninguno",
            "evidencia_geometrica": {},
        })

    if callable(agregar_consenso):
        agregar_consenso(candidatas, usar_base=True)

    # La orientación cardinal se decide ANTES del ajuste fino. Así una lectura
    # corta con confianza muy alta (p. ej. "1") no desplaza a un código más
    # completo y congruente (p. ej. "S4054664") sólo por el porcentaje OCR.
    orden_base = sorted(candidatas,
                        key=lambda c: clave_orientacion(c, usar_base=True),
                        reverse=True)
    recomendada_base = orden_base[0] if orden_base else None
    recomendada_grados = int(recomendada_base["grados"]) if recomendada_base else 0

    # V14.8: una estrategia humana consolidada puede inclinar la preferencia cardinal,
    # pero nunca rescata una lectura clasificada como ruido ni una candidata claramente peor.
    estrategia_preferida = dict(estrategia_preferida or {})
    if estrategia_preferida.get("auto_aplicable") and orientacion_forzada is None:
        base_aprendido = int(estrategia_preferida.get("orientacion_base", -1))
        candidata_aprendida_base = next((c for c in candidatas if c["grados"] == base_aprendido), None)
        if candidata_aprendida_base is not None:
            perfil_aprendido = candidata_aprendida_base.get("congruencia_base") or {}
            perfil_mejor_base = (recomendada_base or {}).get("congruencia_base") or {}
            score_aprendido = float(perfil_aprendido.get("score_informacion") or 0)
            score_mejor = float(perfil_mejor_base.get("score_informacion") or 0)
            if (not perfil_aprendido.get("es_ruido") and score_aprendido >= 40
                    and score_aprendido >= score_mejor - 10):
                recomendada_base = candidata_aprendida_base
                recomendada_grados = base_aprendido

    # El ajuste fino V14.6 es adaptativo y acotado. Hasta ±15° se acepta como
    # corrección normal. Entre 15° y 30° sólo se permite con evidencia geométrica
    # fuerte; nunca se usa ±45° como "ajuste fino". Además, sobre la orientación
    # recomendada se hace una micro-búsqueda alrededor del ángulo geométrico para
    # corregir estimaciones que se quedan uno o dos grados cortas.
    if (ajuste_fino and candidatas and "estimar_skew" in globals()
            and "rotar_imagen_libre_con_matriz" in globals()):
        mejor_cardinal = max(candidatas,
                              key=lambda c: clave_orientacion(c, usar_base=True))
        objetivos = (candidatas if (ajuste_fino_todas or mejor_cardinal["puntuacion"] < .60)
                     else [mejor_cardinal])
        limite_normal = max(float(angulo_fino_min), min(15.0, float(angulo_fino_max)))
        limite_extendido = max(limite_normal, min(30.0, float(angulo_fino_extendido_max)))
        micro = max(0.0, min(3.0, float(micro_ajuste_grados)))

        def evaluar_ajuste(candidata, correccion, modo, evidencia):
            vista_base = vistas_base[candidata["grados"]]
            vista_fina, matriz_base_a_fina = rotar_imagen_libre_con_matriz(vista_base, correccion)
            lecturas_finas, punt_fina, chars_finos = leer(vista_fina)
            congruencia_fina = perfil_congruencia(lecturas_finas, punt_fina)
            temporal = {**candidata, "puntuacion": punt_fina, "caracteres": chars_finos,
                        "congruencia": congruencia_fina}
            return temporal, matriz_base_a_fina, lecturas_finas, punt_fina, chars_finos, congruencia_fina

        for candidata in objetivos:
            base = candidata["grados"]
            vista_base = vistas_base[base]
            gris = cv2.cvtColor(vista_base, cv2.COLOR_BGR2GRAY)
            # Se estima hasta 30° para detectar diagonales reales, pero el ángulo
            # sólo se autoriza si cumple las reglas de evidencia de abajo.
            estimado = float(estimar_skew(gris, angulo_max=limite_extendido))
            correccion_central = -estimado  # convención pública: positivo = horario
            magnitud = abs(correccion_central)
            if magnitud < float(angulo_fino_min) or magnitud > limite_extendido:
                continue

            evidencia = (evidencia_skew(gris, estimado, angulo_max=limite_extendido)
                          if callable(evidencia_skew) else {})
            if magnitud <= limite_normal:
                modo = "normal"
                confiable = True
            else:
                modo = "extendido"
                confiable = bool(evidencia.get("fuerte"))
                if not confiable:
                    continue

            intentos = [correccion_central]
            # La micro-búsqueda sólo se hace en la orientación cardinal ganadora;
            # las otras tarjetas mantienen una sola pasada para no disparar tiempo.
            if micro >= .25 and candidata is mejor_cardinal:
                for delta in (-micro, micro):
                    propuesto = correccion_central + delta
                    if float(angulo_fino_min) <= abs(propuesto) <= (limite_normal if modo == "normal" else limite_extendido):
                        intentos.append(propuesto)

            mejor_intento = None
            for correccion in intentos:
                resultado = evaluar_ajuste(candidata, correccion, modo, evidencia)
                temporal, matriz_fina, lecturas_finas, punt_fina, chars_finos, congruencia_fina = resultado
                # Jamás se cambia un código/fecha/texto congruente por ruido sólo
                # porque la confianza del OCR suba. La magnitud del giro es el
                # último desempate: a igualdad, se prefiere la corrección menor.
                if clave_orientacion(temporal) < clave_orientacion(candidata):
                    continue
                clave_intento = (clave_orientacion(temporal),
                                 -abs(float(correccion) - float(correccion_central)),
                                 -abs(float(correccion)))
                if mejor_intento is None or clave_intento > mejor_intento[0]:
                    mejor_intento = (clave_intento, correccion, matriz_fina,
                                     lecturas_finas, punt_fina, chars_finos, congruencia_fina)
            if mejor_intento is None:
                continue
            _, correccion, matriz_fina, lecturas_finas, punt_fina, chars_finos, congruencia_fina = mejor_intento
            candidata.update({
                "puntuacion": punt_fina, "caracteres": chars_finos,
                "grados_efectivos": (float(base) + float(correccion)) % 360,
                "ajuste_fino_grados": float(correccion), "lecturas": lecturas_finas,
                "congruencia": congruencia_fina,
                "ajuste_fino_confiable": bool(confiable),
                "ajuste_fino_modo": modo,
                "evidencia_geometrica": dict(evidencia or {}),
                "matriz_a_original": matrices_a_original[base] @ np.linalg.inv(matriz_fina),
            })

        if callable(agregar_consenso):
            agregar_consenso(candidatas, usar_base=False)

    # V14.8: con al menos el soporte configurado, ensaya también el ángulo/tratamiento
    # confirmado por varias imágenes parecidas. Es una sola pasada adicional y sólo se
    # conserva si no degrada la congruencia de la orientación preferida.
    if (estrategia_preferida.get("auto_aplicable") and candidatas
            and "rotar_imagen_libre_con_matriz" in globals()):
        base_aprendido = int(estrategia_preferida.get("orientacion_base", -1))
        candidata = next((c for c in candidatas if c["grados"] == base_aprendido), None)
        if candidata is not None:
            ajuste_aprendido = max(-45.0, min(45.0, float(estrategia_preferida.get("ajuste") or 0)))
            variante_aprendida = str(estrategia_preferida.get("variante") or "auto")
            vista_base = vistas_base[base_aprendido]
            if abs(ajuste_aprendido) >= .05:
                vista_aprendida, matriz_aprendida = rotar_imagen_libre_con_matriz(vista_base, ajuste_aprendido)
            else:
                vista_aprendida, matriz_aprendida = vista_base, np.eye(3)
            if variante_aprendida == "auto" and abs(ajuste_aprendido) < .05:
                # Ya se leyó exactamente esta vista en la pasada cardinal; no duplica GPU.
                lecturas_aprendidas = list(candidata.get("lecturas") or [])
                punt_aprendido = float(candidata.get("puntuacion") or 0)
                chars_aprendidos = int(candidata.get("caracteres") or 0)
            elif variante_aprendida != "auto":
                procesada = aplicar_variante(vista_aprendida, variante_aprendida, {})
                lecturas_aprendidas = motor.leer_texto_completo(procesada) or []
                pesos = [min(32, len(str(l.get("texto") or "").strip())) for l in lecturas_aprendidas]
                punt_aprendido = sum(float(l.get("confianza") or 0)*p for l,p in zip(lecturas_aprendidas,pesos))/max(1,sum(pesos))
                chars_aprendidos = sum(max(0,p) for p in pesos)
            else:
                lecturas_aprendidas, punt_aprendido, chars_aprendidos = leer(vista_aprendida)
            congr_aprendida = perfil_congruencia(lecturas_aprendidas, punt_aprendido)
            temporal = {**candidata, "puntuacion": punt_aprendido, "caracteres": chars_aprendidos,
                        "congruencia": congr_aprendida}
            if (not congr_aprendida.get("es_ruido") and
                    clave_orientacion(temporal) >= clave_orientacion(candidata)):
                candidata.update({
                    "puntuacion": punt_aprendido, "caracteres": chars_aprendidos,
                    "grados_efectivos": (float(base_aprendido)+ajuste_aprendido)%360,
                    "ajuste_fino_grados": ajuste_aprendido, "lecturas": lecturas_aprendidas,
                    "congruencia": congr_aprendida, "ajuste_fino_confiable": True,
                    "ajuste_fino_modo": "aprendido",
                    "evidencia_geometrica": {"estrategia_aprendida": True,
                        "soporte": int(estrategia_preferida.get("soporte") or 0),
                        "dominancia": float(estrategia_preferida.get("dominancia") or 0),
                        "variante": variante_aprendida},
                    "matriz_a_original": matrices_a_original[base_aprendido] @ np.linalg.inv(matriz_aprendida),
                })
                recomendada_grados = base_aprendido
        if callable(agregar_consenso):
            agregar_consenso(candidatas, usar_base=False)

    # La recomendación sigue anclada a la comparación cardinal previa al
    # deskew. El ajuste fino mejora la lectura elegida, pero no redefine a
    # posteriori cuál orientación era más congruente.
    candidatas.sort(
        key=lambda c: (int(c["grados"] == recomendada_grados),
                       clave_orientacion(c, usar_base=True),
                       clave_orientacion(c)),
        reverse=True)
    mejor = next((c for c in candidatas if c["grados"] == recomendada_grados), candidatas[0])
    texto_mejor = "".join(str(l.get("texto") or "") for l in mejor["lecturas"]).strip()
    perfil_mejor = mejor.get("congruencia_base") or {}
    segunda = next((c for c in candidatas if c is not mejor), None)
    empate_semantico = bool(segunda and
        tuple((segunda.get("congruencia_base") or {}).get("clave") or ())[:4] ==
        tuple(perfil_mejor.get("clave") or ())[:4] and
        abs(float(mejor.get("puntuacion_base") or 0) -
            float(segunda.get("puntuacion_base") or 0)) < margen)
    dudosa = orientacion_forzada is None and (
        empate_semantico or
        (not perfil_mejor.get("probable_codigo") and
         (mejor["puntuacion_base"] < .60 or len(texto_mejor.replace(" ", "")) <= 2)))

    renglones = reconstruir_lineas_texto(mejor["lecturas"])
    matriz_mejor = mejor["matriz_a_original"]
    lecturas = [{**l, "bbox": _bbox_proyectada(l["bbox"], matriz_mejor)}
                for l in renglones if l.get("bbox")]
    for origen, lectura in zip((l for l in renglones if l.get("bbox")), lecturas):
        x,y,w,h = origen["bbox"]
        puntos = np.array([[[x,y],[x+w,y],[x+w,y+h],[x,y+h]]], dtype=np.float32)
        lectura["poligono_lectura"] = cv2.perspectiveTransform(
            puntos, np.asarray(matriz_mejor, dtype=np.float64))[0].tolist()
        lectura["orientacion_base_grados"] = mejor["grados"]
        lectura["ajuste_fino_grados"] = round(float(mejor["ajuste_fino_grados"]), 3)
        lectura["orientacion_efectiva_grados"] = round(float(mejor["grados_efectivos"]), 3)

    candidatos_publicos = []
    for c in candidatas:
        perfil_base = c.get("congruencia_base") or {}
        perfil = c.get("congruencia") or perfil_base
        candidatos_publicos.append({
            "grados": c["grados"],
            "grados_efectivos": round(float(c["grados_efectivos"]), 3),
            "ajuste_fino_grados": round(float(c["ajuste_fino_grados"]), 3),
            "ajuste_fino_confiable": bool(c.get("ajuste_fino_confiable")),
            "ajuste_fino_modo": str(c.get("ajuste_fino_modo") or "ninguno"),
            "evidencia_geometrica": dict(c.get("evidencia_geometrica") or {}),
            "confianza": round(c["puntuacion"], 4),
            "texto": "\n".join(str(l.get("texto") or "") for l in
                                reconstruir_lineas_texto(c["lecturas"]))[:1024],
            "confianza_base": round(float(c.get("puntuacion_base", c["puntuacion"])), 4),
            "texto_base": "\n".join(str(l.get("texto") or "") for l in
                                     reconstruir_lineas_texto(c.get("lecturas_base", c["lecturas"])))[:1024],
            "recomendada": int(c["grados"]) == recomendada_grados,
            "probable_codigo": bool(perfil.get("probable_codigo")),
            "tipo_codigo_probable": str(perfil.get("tipo") or ""),
            "mayus_minus_coherente": bool(perfil.get("mayus_minus_coherente", True)),
            "longitud_util": int(perfil.get("longitud") or 0),
            "tipo_informacion": str(perfil.get("tipo_informacion") or "ruido"),
            "etiqueta_informacion": str(perfil.get("etiqueta_informacion") or "Lectura"),
            "score_informacion": round(float(perfil.get("score_informacion") or 0.0), 2),
            "es_ruido": bool(perfil.get("es_ruido")),
            "recomendacion_util": bool(not perfil.get("es_ruido") and float(perfil.get("score_informacion") or 0) >= 45),
            "razones_congruencia": list(perfil.get("razones") or []),
            "consenso": int(perfil.get("consenso") or 1),
            "similitud_consenso": round(float(perfil.get("similitud_consenso") or 0.0), 3),
            "tipo_informacion_base": str(perfil_base.get("tipo_informacion") or "ruido"),
            "score_informacion_base": round(float(perfil_base.get("score_informacion") or 0.0), 2),
        })
    return lecturas, {
        "orientacion_grados": mejor["grados"],
        "orientacion_recomendada_grados": recomendada_grados,
        "criterio_orientacion": "congruencia_codigo_pre_ajuste",
        "criterio_congruencia": "semantica_v146",
        "orientacion_efectiva_grados": round(float(mejor["grados_efectivos"]), 3),
        "ajuste_fino_grados": round(float(mejor["ajuste_fino_grados"]), 3),
        "orientacion_dudosa": dudosa,
        "orientacion_confirmada": orientacion_forzada is not None,
        "candidatos_orientacion": candidatos_publicos,
        "puntuaciones": {str(c["grados"]): round(c["puntuacion"],4) for c in candidatas},
    }


def extraer_texto_empresarial(imagen_path: str, config: dict | None = None,
                              fase: str = "VOR", modo_recorte: str | None = None,
                              roi_manual: dict | None = None,
                              zoom_forzado: float | None = None,
                              imagen_preparada: np.ndarray | None = None) -> dict:
    """Ruta rápida: CRAFT en miniatura y reconocimiento sólo de los recortes detectados.

    Si no existen cajas se retorna ``descartada_sin_texto`` sin invocar al
    reconocedor. ``completo`` delega al flujo probado anterior.
    """
    config = config or cargar_config()
    f1 = config.get("fase1", {})
    cfg = config.get("ocr", {})
    modo = str(modo_recorte or cfg.get("modo_recorte", "auto")).lower()
    if modo not in {"auto", "manual", "completo"}:
        raise ValueError("modo_recorte debe ser auto, manual o completo.")
    inicio_total = time.monotonic()
    if modo == "completo":
        resultado = extraer_texto(imagen_path, config, imagen_preparada=imagen_preparada)
        imagen_qr = imagen_preparada if imagen_preparada is not None else cargar_imagen(imagen_path)
        qrs = detectar_qrs(imagen_qr, f1.get("qr", {}))
        modelo_completo = getattr(obtener_motor(config)[0], "modelo_visual", None) or {}
        resultado.update({"estado_imagen": ("procesada_con_texto" if resultado.get("lineas_texto")
                                             or resultado.get("tokens") else
                                             "procesada_con_qr" if any(q.get("payload") for q in qrs)
                                             else "descartada_sin_texto"),
                          "modo_recorte": "completo", "tiempo_deteccion_seg": 0.0,
                          "tiempo_ocr_seg": round(time.monotonic() - inicio_total, 4),
                          "numero_regiones": 1, "zoom_aplicado": 1.0,
                          "modelo_visual_version": modelo_completo.get("version"),
                          "qrs": qrs,
                          "recortes": [{"bbox": (0, 0, imagen_qr.shape[1], imagen_qr.shape[0]),
                                        "dimensiones_antes": (imagen_qr.shape[1], imagen_qr.shape[0]),
                                        "dimensiones_despues": (imagen_qr.shape[1], imagen_qr.shape[0]),
                                        "zoom": 1.0}]})
        return resultado

    imagen_fuente = imagen_preparada if imagen_preparada is not None else cargar_imagen(imagen_path)
    from aprendizaje import GestorAprendizaje, hash_archivo
    gestor = GestorAprendizaje(config)
    huella_imagen = hash_archivo(imagen_path)
    preferencias_regionales = gestor.orientaciones_regionales(imagen_path)
    preferencia_manual = gestor.preferencia_rotacion(imagen_path)
    rotacion_manual = float(preferencia_manual["grados"]) if preferencia_manual else 0.0
    rotacion_manual_definida = preferencia_manual is not None
    imagen_original = rotar_imagen_libre(imagen_fuente, rotacion_manual)
    qrs = detectar_qrs(imagen_original, f1.get("qr", {}))
    motor, _ = obtener_motor(config)
    alto, ancho = imagen_original.shape[:2]
    alto_fuente, ancho_fuente = imagen_fuente.shape[:2]
    manual_cfg = roi_manual or cfg.get("roi_manual", {}).get(str(fase).upper())
    if modo == "manual":
        imagen_deteccion, caja_manual = _roi_proporcional(imagen_original, manual_cfg)
        cajas = [{"bbox": caja_manual, "poligono": None, "manual": True}]
        escala = 1.0
        offset_manual = (caja_manual[0], caja_manual[1])
    else:
        lado_maximo = max(320, int(cfg.get("lado_maximo_deteccion", 1280)))
        escala = min(1.0, lado_maximo / max(alto, ancho))
        imagen_deteccion = (cv2.resize(imagen_original, None, fx=escala, fy=escala,
                                       interpolation=cv2.INTER_AREA)
                            if escala < 0.999 else imagen_original)
        detector = getattr(motor, "detectar", None)
        if detector is None:
            regiones = detectar_regiones_texto(
                imagen_deteccion, f1.get("preprocesamiento", {}).get("regiones_texto", {}))
            cajas = [{"bbox": b, "poligono": None} for b in regiones]
        else:
            cajas = detector(imagen_deteccion)
        # Rescate acotado cuando CRAFT no encontró ninguna región. Aumentar
        # resolución para texto pequeño y probar una vista perpendicular.
        if not cajas and detector is not None and cfg.get("rescatar_deteccion_vacia", True):
            escala_rescate = min(1.0, 1920 / max(alto,ancho))
            rescate = (cv2.resize(imagen_original, None, fx=escala_rescate, fy=escala_rescate,
                                  interpolation=cv2.INTER_AREA)
                       if escala_rescate < .999 else imagen_original)
            if escala_rescate > escala:
                cajas = detector(rescate)
                escala = escala_rescate
                imagen_deteccion = rescate
            if not cajas:
                h_rescate = imagen_deteccion.shape[0]
                inversa = np.array([[0,1,0],[-1,0,h_rescate],[0,0,1]], dtype=float)
                for encontrada in detector(_rotar_recto(imagen_deteccion,90)):
                    caja_rescate = {**encontrada, "bbox": _bbox_proyectada(encontrada["bbox"],inversa)}
                    if encontrada.get("poligono"):
                        caja_rescate["poligono"] = cv2.perspectiveTransform(
                            np.array([encontrada["poligono"]],dtype=np.float32),inversa)[0].tolist()
                    cajas.append(caja_rescate)
        offset_manual = (0, 0)
    tiempo_deteccion = time.monotonic() - inicio_total
    if not cajas:
        tiene_qr = any(q.get("payload") for q in qrs)
        from flujo_empresarial import REGLAS_CODIGO_VISIBLES
        return {"imagen": str(imagen_path), "motor": motor.nombre,
                "dispositivo": getattr(motor, "dispositivo", "cpu"),
                "batch_ocr": getattr(motor, "_batch_size", 1), "tokens": [],
                "codigos_detectados": [], "reglas_codigo": list(REGLAS_CODIGO_VISIBLES),
                "lineas_texto": [], "texto_completo": "", "confianza_media": None,
                "dimensiones_originales": (ancho_fuente, alto_fuente),
                "dimensiones": (ancho, alto),
                "rotacion_manual_aplicada_grados": rotacion_manual,
                "orientacion_manual_prioritaria": rotacion_manual_definida,
                "orientacion_base_grados": 0,
                "orientacion_texto_base_grados": 0,
                "deskew_aplicado_grados": 0.0,
                "deskew_texto_aplicado_grados": 0.0,
                "orientacion_corregida_grados": rotacion_manual,
                "orientacion_texto_grados": rotacion_manual,
                "estado_imagen": "procesada_con_qr" if tiene_qr else "descartada_sin_texto",
                "modo_recorte": modo,
                "tiempo_deteccion_seg": round(tiempo_deteccion, 4), "tiempo_ocr_seg": 0.0,
                "numero_regiones": 0, "zoom_aplicado": 1.0, "intentos_ocr": [],
                "qrs": qrs, "recortes": [],
                "modelo_visual_version": ((getattr(motor, "modelo_visual", None) or {}).get("version")),
                "advertencias_motor": list(getattr(motor, "advertencias", []))}

    margen = max(0.0, float(cfg.get("margen_recorte", 0.12)))
    zoom_min, zoom_max = float(cfg.get("zoom_minimo", 1.0)), float(cfg.get("zoom_maximo", 3.0))
    altura_objetivo = int(cfg.get("altura_objetivo_recorte", 160))
    lineas = []
    zooms = []
    recortes_log = []
    inicio_ocr = time.monotonic()
    for caja in cajas:
        x, y, w, h = caja.get("bbox", caja)
        matriz_perspectiva = None
        if modo == "manual":
            x, y, w, h = caja_manual
            recorte = imagen_deteccion
        else:
            x, y, w, h = (int(round(v / escala)) for v in (x, y, w, h))
            mx, my = int(w * margen), int(h * margen)
            x, y = max(0, x - mx), max(0, y - my)
            w, h = min(ancho - x, w + 2 * mx), min(alto - y, h + 2 * my)
            poligono = caja.get("poligono")
            if poligono and cfg.get("corregir_perspectiva", True):
                puntos = np.asarray(poligono, dtype=np.float32) / escala
                recorte, matriz_perspectiva = _recorte_perspectiva(imagen_original, puntos, True)
                if recorte.size == 0:
                    recorte = imagen_original[y:y+h, x:x+w]
                    matriz_perspectiva = None
            else:
                recorte = imagen_original[y:y + h, x:x + w]
        if recorte.size == 0:
            continue
        zoom_calculado = altura_objetivo / max(min(recorte.shape[:2]), 1)
        zoom = min(zoom_max, max(zoom_min,
                   float(zoom_forzado) if zoom_forzado is not None else zoom_calculado))
        zoom = min(zoom, max(1.0, 2560 / max(recorte.shape[:2])))
        zooms.append(zoom)
        preparada = (cv2.resize(recorte, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_CUBIC)
                     if zoom > 1.01 else recorte)
        recortes_log.append({"bbox": (x, y, w, h),
                             "dimensiones_antes": (recorte.shape[1], recorte.shape[0]),
                             "dimensiones_despues": (preparada.shape[1], preparada.shape[0]),
                             "zoom": round(zoom, 3)})
        marco = hashlib.sha256(json.dumps({
            "bbox": [x,y,w,h], "giro_foto": rotacion_manual,
            "perspectiva": (matriz_perspectiva.round(6).tolist()
                            if matriz_perspectiva is not None else None),
        }, sort_keys=True).encode()).hexdigest()
        recortes_log[-1]["marco"] = marco
        recortes_log[-1]["poligono_fuente"] = (
            puntos.tolist() if matriz_perspectiva is not None else None)
        ajuste_cfg = f1.get("preprocesamiento", {}).get("ajuste_fino_regiones", {})
        estrategia_aprendida = gestor.sugerir_estrategia_ocr(
            imagen_path, (x, y, w, h), [ancho, alto], {})
        lecturas, orientacion_region = _leer_recorte_orientado(
            preparada, motor, permitir_giro=True,
            margen=float(cfg.get("margen_orientacion", .08)),
            orientacion_forzada=preferencias_regionales.get(marco),
            ajuste_fino=bool(ajuste_cfg.get("activar", True)),
            ajuste_fino_todas=False,
            angulo_fino_min=float(ajuste_cfg.get("angulo_minimo", 1.25)),
            angulo_fino_max=float(ajuste_cfg.get("angulo_maximo", 15.0)),
            angulo_fino_extendido_max=float(ajuste_cfg.get("angulo_maximo_extendido", 30.0)),
            micro_ajuste_grados=float(ajuste_cfg.get("micro_ajuste_grados", 2.0)),
            estrategia_preferida=estrategia_aprendida)
        recortes_log[-1].update(orientacion_region)
        if estrategia_aprendida:
            recortes_log[-1]["estrategia_ocr_aprendida"] = estrategia_aprendida
        recortes_log[-1]["perspectiva_corregida"] = matriz_perspectiva is not None
        matriz_local = (matriz_perspectiva if matriz_perspectiva is not None else
                        np.array([[1,0,x],[0,1,y],[0,0,1]], dtype=float))
        matriz_local = matriz_local @ np.diag([1/zoom if zoom>1.01 else 1,
                                              1/zoom if zoom>1.01 else 1, 1])
        for lectura in lecturas:
            poligono_lectura = cv2.perspectiveTransform(
                np.array([lectura["poligono_lectura"]], dtype=np.float32), matriz_local)[0].tolist()
            bx,by,bw,bh = _bbox_proyectada(lectura["bbox"], matriz_local)
            x0,y0 = min(ancho-1,max(0,bx)),min(alto-1,max(0,by))
            caja_global = (x0,y0,max(1,min(ancho,bx+bw)-x0),max(1,min(alto,by+bh)-y0))
            lineas.append({**lectura, "bbox": caja_global,
                           "poligono_lectura": poligono_lectura,
                           "marco_region": marco,
                           "orientacion_region_grados": orientacion_region["orientacion_grados"],
                           "orientacion_region_efectiva_grados": orientacion_region.get("orientacion_efectiva_grados", orientacion_region["orientacion_grados"]),
                           "ajuste_fino_region_grados": orientacion_region.get("ajuste_fino_grados", 0.0),
                           "orientacion_region_dudosa": orientacion_region["orientacion_dudosa"],
                           "region_bbox": (x, y, w, h), "origen": "region"})

    umbral = float(f1.get("umbral_confianza_texto_completo", 0.25))
    lineas = [l for l in lineas if float(l.get("confianza") or 0) >= umbral]
    intentos = [{"tipo": "recortes", "variante": "original", "lineas": len(lineas)}]

    # Cada región ya está ordenada en su propio marco. No unir regiones de la
    # foto que puedan tener orientaciones diferentes o códigos independientes.
    reconstruidas = [dict(l) for l in lineas]
    tokens = [dict(l) for l in lineas]
    from aprendizaje import aplicar_modelo_tokens
    cantidad_tokens = len(tokens)
    corregidas = aplicar_modelo_tokens([*tokens, *reconstruidas], config, imagen_path)
    tokens, reconstruidas = corregidas[:cantidad_tokens], corregidas[cantidad_tokens:]
    from flujo_empresarial import REGLAS_CODIGO_VISIBLES
    confianzas = [float(l["confianza"]) for l in lineas]
    return {"imagen": str(imagen_path), "motor": motor.nombre,
            "dispositivo": getattr(motor, "dispositivo", "cpu"),
            "batch_ocr": getattr(motor, "_batch_size", 1), "tokens": tokens,
            "codigos_detectados": _resumen_codigos(tokens),
            "reglas_codigo": list(REGLAS_CODIGO_VISIBLES),
            "lineas_texto": reconstruidas,
            "texto_completo": "\n".join(l["texto"] for l in reconstruidas),
            "confianza_media": round(float(np.mean(confianzas)), 4) if confianzas else None,
            "dimensiones_originales": (ancho_fuente, alto_fuente),
            "dimensiones": (ancho, alto),
            "rotacion_manual_aplicada_grados": rotacion_manual,
            "orientacion_manual_prioritaria": rotacion_manual_definida,
            "orientacion_base_grados": 0,
            "orientacion_texto_base_grados": 0,
            "deskew_aplicado_grados": 0.0,
            "deskew_texto_aplicado_grados": 0.0,
            "orientacion_corregida_grados": rotacion_manual,
            "orientacion_texto_grados": rotacion_manual,
            "estado_imagen": "procesada_con_texto" if lineas else "descartada_sin_texto",
            "modo_recorte": modo, "tiempo_deteccion_seg": round(tiempo_deteccion, 4),
            "tiempo_ocr_seg": round(time.monotonic() - inicio_ocr, 4),
            "numero_regiones": len(cajas), "zoom_aplicado": round(max(zooms or [1.0]), 3),
            "intentos_ocr": intentos, "qrs": qrs, "recortes": recortes_log,
            "orientaciones_regionales_usadas": preferencias_regionales,
            "huella_imagen": huella_imagen,
            "modelo_visual_version": ((getattr(motor, "modelo_visual", None) or {}).get("version")),
            "advertencias_motor": list(getattr(motor, "advertencias", []))}


def extraer_texto(imagen_path: str, config: dict | None = None,
                  imagen_preparada: np.ndarray | None = None) -> dict:
    """
    Pipeline completo sobre una imagen. Ver contrato en el docstring del módulo.

    La búsqueda empieza con la ruta normal a 0°. Si no obtiene un código
    alfanumérico suficientemente confiable, amplía a las demás orientaciones y
    después a variantes de contraste/relieve. ``modo: exhaustivo`` permite
    evaluar todas las combinaciones cuando el costo no sea prioritario.
    """
    motor, f1 = obtener_motor(config)
    imagen_original = imagen_preparada if imagen_preparada is not None else cargar_imagen(imagen_path)
    from aprendizaje import GestorAprendizaje, aplicar_modelo_tokens
    preferencia_manual = GestorAprendizaje(config).preferencia_rotacion(imagen_path)
    rotacion_manual = float(preferencia_manual["grados"]) if preferencia_manual else 0.0
    rotacion_manual_definida = preferencia_manual is not None
    imagen = rotar_imagen_libre(imagen_original, rotacion_manual)
    f1_ejecucion = f1
    if rotacion_manual_definida:
        # Una decisión humana fija el marco de lectura: no se suma otra
        # orientación ni un deskew automático sobre la imagen ya colocada.
        f1_ejecucion = deepcopy(f1)
        preparacion = f1_ejecucion.setdefault("preprocesamiento", {})
        preparacion["deskew"] = False
        busqueda = preparacion.setdefault("busqueda_adaptativa", {})
        busqueda["orientaciones"] = [0]
        busqueda["modo"] = "adaptativo"

    pasada, intentos = _seleccionar_pasada(imagen, f1_ejecucion, motor)

    tokens = segmentar_tokens(pasada["lineas"], int(f1.get("umbral_espacio_px", 40)))
    if f1.get("extraer_texto_completo", True):
        lineas_crudas_texto, orientacion_texto = _extraer_pasada_texto_completo(
            imagen, f1_ejecucion, motor,
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
    from flujo_empresarial import REGLAS_CODIGO_VISIBLES
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
        "batch_ocr": getattr(motor, "_batch_size", 1),
        "advertencias_motor": list(getattr(motor, "advertencias", [])),
        "tokens": tokens,
        "codigos_detectados": _resumen_codigos(tokens),
        "reglas_codigo": list(REGLAS_CODIGO_VISIBLES),
        "lineas_texto": lineas_texto,
        "texto_completo": "\n".join(l["texto"] for l in lineas_texto),
        "qr_bbox": tuple(pasada["qr"]) if pasada["qr"] is not None else None,
        "rotacion_manual_aplicada_grados": rotacion_manual,
        "orientacion_manual_prioritaria": rotacion_manual_definida,
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
