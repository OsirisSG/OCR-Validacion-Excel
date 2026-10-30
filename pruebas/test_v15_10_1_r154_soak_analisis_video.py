"""R15.4 · F4 — Soak test de análisis de video repetido (MEDIUM/LOW-04).

Auditoría independiente R15.3 (`AUDITORIA_INDEPENDIENTE_R15_3_20261015.md`):

* MEDIUM/LOW-04: en el entorno de auditoría, `test_v15_7_detector_apertura.py`
  completo podía volver anormalmente lenta la última prueba (o exceder su
  timeout), mientras que aislada terminaba en segundos. Reproducido también
  sobre R15.2 ⇒ no es regresión de R15.3. Riesgo señalado: acumulación de
  recursos OpenCV, handles, caché u otro estado tras análisis consecutivos.
* Recomendación: soak test de 50–100 análisis consecutivos midiendo tiempo
  por iteración, memoria, handles/archivos abiertos, estado de caché y
  liberación de `VideoCapture`.

Diagnóstico en el sandbox de desarrollo (Linux, este release): las duraciones
AISLADAS de las 8 pruebas de `test_v15_7_detector_apertura.py` coinciden con
sus duraciones DENTRO del archivo completo (p. ej. 19.98 s aislada vs 20.02 s
en archivo; 1.56 s vs 1.43 s la última) ⇒ no hay degradación dependiente del
orden aquí; el costo total (~56 s) es inherente a la generación + análisis de
videos sintéticos. Este soak test deja la verificación automatizada de
ausencia de fugas/degradación para cualquier entorno futuro.
"""
from __future__ import annotations

import gc
import sys
import time
from pathlib import Path

import pytest

CONFIG = {"aprendizaje": {}}
ITERACIONES = 100
# R15.5 (LOW-06): el primer análisis carga OpenCV/codec de forma perezosa; en
# la auditoría el RSS saltó ~113→278 MB en la PRIMERA invocación y luego quedó
# estable (281–311 MB). Medir rss0 antes de ese warm-up daba falso fallo de
# fuga. Corrección pedida por el auditor: warm-up de 1–3 análisis antes de la
# línea base.
WARMUP = 2
MARGEN_FDS = 5
MARGEN_RSS_MB = 60.0
FACTOR_DEGRADACION = 2.5


def _video_sintetico(ruta: Path, frames: int = 40) -> None:
    import cv2
    import numpy as np
    writer = cv2.VideoWriter(str(ruta), cv2.VideoWriter_fourcc(*"MJPG"), 25,
                             (96, 64))
    assert writer.isOpened(), "cv2 no pudo crear el video sintético"
    for i in range(frames):
        imagen = np.full((64, 96, 3), (i * 5 % 255, 40, 220 - (i * 3) % 200),
                         np.uint8)
        cv2.rectangle(imagen, (5 + i % 20, 20), (12 + i % 20, 30),
                      (255, 255, 255), -1)
        writer.write(imagen)
    writer.release()


def _rss_mb() -> float:
    if sys.platform.startswith("linux"):
        for linea in Path("/proc/self/status").read_text().splitlines():
            if linea.startswith("VmRSS:"):
                return int(linea.split()[1]) / 1024.0
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def _fds() -> int | None:
    if sys.platform.startswith("linux"):
        return len(list(Path("/proc/self/fd").iterdir()))
    return None  # el conteo de descriptores es específico de Linux


@pytest.fixture
def video(tmp_path, monkeypatch):
    import video_airbag
    import aprendizaje_video_airbag
    monkeypatch.setattr(video_airbag, "RUTA_CACHE",
                        tmp_path / "cache" / "video_airbag.json")
    monkeypatch.setattr(video_airbag, "RUTA_REVISIONES",
                        tmp_path / "revisiones_video.json")
    monkeypatch.setattr(aprendizaje_video_airbag, "RUTA_APRENDIZAJE",
                        tmp_path / "aprendizajes" / "zonas.json")
    monkeypatch.setattr(aprendizaje_video_airbag, "RUTA_REFERENCIAS",
                        tmp_path / "aprendizajes" / "referencias")
    ruta = tmp_path / "n_DETAIL.AVI"
    _video_sintetico(ruta)
    return ruta


def test_soak_100_analisis_sin_degradacion_ni_fugas(video):
    """100 análisis consecutivos: tiempo estable, RSS/acotado, fds estables,
    caché interna acotada."""
    import video_airbag
    video_airbag._cache_reloj.clear()
    for _ in range(WARMUP):  # R15.5 (LOW-06): inicialización perezosa fuera de la medida
        resultado_warm = video_airbag.analizar_video(video, CONFIG, usar_cache=False)
        assert isinstance(resultado_warm, dict) and "algoritmo_video" in resultado_warm
    gc.collect()
    fds0, rss0 = _fds(), _rss_mb()
    tiempos: list[float] = []
    for _ in range(ITERACIONES):
        inicio = time.monotonic()
        resultado = video_airbag.analizar_video(video, CONFIG, usar_cache=False)
        tiempos.append(time.monotonic() - inicio)
        assert isinstance(resultado, dict) and "algoritmo_video" in resultado
    gc.collect()
    fds1, rss1 = _fds(), _rss_mb()

    primeras = sorted(tiempos[:10])[5]
    ultimas = sorted(tiempos[-10:])[5]
    assert ultimas <= max(primeras * FACTOR_DEGRADACION, 0.5), (
        f"MEDIUM/LOW-04: degradación dependiente del orden — mediana de las "
        f"10 primeras {primeras*1000:.0f} ms vs {ultimas*1000:.0f} ms en las "
        "10 últimas")
    if fds0 is not None:
        assert fds1 - fds0 <= MARGEN_FDS, (
            f"MEDIUM/LOW-04: fuga de descriptores (¿VideoCapture sin "
            f"liberar?) {fds0} → {fds1} tras {ITERACIONES} análisis")
    assert rss1 - rss0 <= MARGEN_RSS_MB, (
        f"MEDIUM/LOW-04: crecimiento de memoria {rss0:.0f} → {rss1:.0f} MB "
        f"tras {ITERACIONES} análisis")
    assert len(video_airbag._cache_reloj) <= video_airbag._CACHE_RELOJ_MAX, (
        "la caché de reloj superó su cota declarada")


def test_videocapture_libera_descriptores(video):
    """Apertura/lectura/liberación explícita repetida no acumula fds."""
    import cv2
    fds0 = _fds()
    if fds0 is None:
        pytest.skip("conteo de descriptores disponible sólo en Linux")
    for _ in range(50):
        cap = cv2.VideoCapture(str(video))
        try:
            assert cap.isOpened()
            cap.read()
        finally:
            cap.release()
    gc.collect()
    delta = _fds() - fds0
    assert delta <= MARGEN_FDS, (
        f"VideoCapture no libera: {fds0} → {fds0 + delta} fds tras 50 ciclos")
