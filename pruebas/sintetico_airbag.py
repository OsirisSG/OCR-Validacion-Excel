"""Generador de videos sintéticos de despliegue de airbag para pruebas.

Simula lo que distingue el usuario: el tablero primero se hincha (se deforma y
mueve sus brillos sin que aparezca material nuevo) y después asoma la tela de
la bolsa, al principio con muy pocos píxeles.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def _textura(alto: int, ancho: int, semilla: int) -> np.ndarray:
    rng = np.random.default_rng(semilla)
    base = rng.normal(0, 1, (alto, ancho)).astype(np.float32)
    base = cv2.GaussianBlur(base, (0, 0), 3.0)
    base = base / (np.abs(base).max() + 1e-6)
    return base


def generar_video(ruta: str | Path, *, total: int = 60, fps: float = 8.0,
                  frame_hinchado: int | None = 6, frame_bolsa: int = 14,
                  ancho: int = 640, alto: int = 480, ruido: float = 3.0,
                  fondo: float = 95.0, brillo_tablero: bool = True,
                  semilla: int = 7) -> dict:
    """Escribe un AVI MJPG y devuelve los parámetros reales del evento.

    Igual que los AVI EDAG reales, el contenedor declara pocos fps (8 por
    defecto); la tasa real de grabación se simula aparte con un overlay falso.
    """
    rng = np.random.default_rng(semilla)
    tex = _textura(alto, ancho, semilla)
    yy, xx = np.mgrid[0:alto, 0:ancho].astype(np.float32)
    cx, cy = ancho * 0.5, alto * 0.52
    tablero = fondo + 18.0 * tex
    # Costura del tablero por donde rompe la bolsa.
    tablero[int(cy) - 1:int(cy) + 1, int(ancho * 0.3):int(ancho * 0.7)] -= 35
    if brillo_tablero:
        # Reflejo especular sobre el plástico: es lo que se desplaza/crece al hincharse.
        reflejo = np.exp(-(((xx - cx + 40) / 26.0) ** 2 + ((yy - cy + 18) / 9.0) ** 2))
        tablero += 75.0 * reflejo
    tablero = np.clip(tablero, 0, 255).astype(np.float32)
    writer = cv2.VideoWriter(str(ruta), cv2.VideoWriter_fourcc(*"MJPG"), fps, (ancho, alto))
    if not writer.isOpened():
        raise RuntimeError("No se pudo crear el video sintético")
    forma = _textura(alto, ancho, semilla + 1)
    for i in range(total):
        img = tablero
        if frame_hinchado is not None and i >= frame_hinchado:
            # Abultamiento radial creciente: la superficie se mueve hacia la cámara.
            k = min(1.0, (i - frame_hinchado + 1) / 8.0)
            r2 = ((xx - cx) / 120.0) ** 2 + ((yy - cy) / 60.0) ** 2
            bulto = np.exp(-r2) * 6.0 * k
            map_x = xx - bulto * (xx - cx) / 120.0
            map_y = yy - bulto * (yy - cy) / 60.0 * 1.5
            img = cv2.remap(tablero, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        img = img.copy()
        if i >= frame_bolsa:
            # Tela clara que asoma por la costura y crece rápidamente.
            n = i - frame_bolsa
            radio = [1.2, 2.0, 3.2, 5.0, 7.5, 11.0, 15.0, 20.0][min(n, 7)] + max(0, n - 7) * 6.0
            d = np.sqrt(((xx - cx) / 1.6) ** 2 + (yy - cy) ** 2) + 2.0 * forma
            tela = d <= radio
            img[tela] = 205.0 + 15.0 * forma[tela]
        img = img + rng.normal(0, ruido, img.shape).astype(np.float32)
        img8 = np.clip(img, 0, 255).astype(np.uint8)
        writer.write(cv2.cvtColor(img8, cv2.COLOR_GRAY2BGR))
    writer.release()
    return {"frame_bolsa": frame_bolsa, "frame_hinchado": frame_hinchado, "fps": fps}


def overlay_falso(fps_grabacion: float = 5000.0):
    """Sustituto de ``video_airbag._leer_overlay`` sin EasyOCR: sólo aporta Rec…fps."""
    def _leer(frame, config=None):
        return {"texto": f"Rec{int(fps_grabacion)} fps", "tiempos_ms": [],
                "fps_grabacion": [float(fps_grabacion)], "timestamp_esquina_ms": None,
                "precision_timestamp_esquina_ms": None, "timestamp_origen": None,
                "texto_esquina": "", "error": None}
    return _leer
