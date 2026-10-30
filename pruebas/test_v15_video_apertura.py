from pathlib import Path

import cv2
import numpy as np

from analisis_video import analizar_video, buscar_videos_caso, consenso_videos, _parsear_tiempo_overlay


def _crear_video(ruta: Path, fps=1000.0, onset=8, total=20):
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    writer = cv2.VideoWriter(str(ruta), fourcc, fps, (160, 120))
    assert writer.isOpened()
    for i in range(total):
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        frame[:] = 30
        if i >= onset:
            cv2.rectangle(frame, (60, 45), (110, 95), (245, 245, 245), -1)
        writer.write(frame)
    writer.release()


def test_busca_video_y_detecta_apertura(tmp_path):
    caso = tmp_path / "232550 RDW NOM RT"
    carpeta = caso / "VIDEO"
    carpeta.mkdir(parents=True)
    ruta = carpeta / "cam1.avi"
    _crear_video(ruta, fps=1000.0, onset=8)
    encontrados = buscar_videos_caso(caso)
    assert len(encontrados) == 1
    r = analizar_video(ruta, {"video_apertura": {"ocr_timestamp": False, "paso_grueso_ms": 2.0}})
    assert r["estado"] == "candidato_apertura"
    assert abs(r["frame_apertura"] - 8) <= 1
    assert r["resolucion_nativa_ms"] >= 0.9
    assert r["precision_0_1ms"] is False
    assert r["fuente_tiempo"] == "interpolacion_subframe"


def test_consenso_tres_de_cuatro():
    videos = [
        {"id":"a","nombre":"a","tiempo_ms":5.9,"precision_0_1ms":True},
        {"id":"b","nombre":"b","tiempo_ms":6.0,"precision_0_1ms":True},
        {"id":"c","nombre":"c","tiempo_ms":6.0,"precision_0_1ms":True},
        {"id":"d","nombre":"d","tiempo_ms":8.2,"precision_0_1ms":True},
    ]
    c = consenso_videos(videos, {"video_apertura": {"consenso_tolerancia_ms":0.2,"consenso_minimo":3}})
    assert c["replicas"] == 3
    assert c["tiempo_ms"] == 6.0
    assert c["estado"] == "confirmado_automatico"


def test_timestamp_explicito():
    assert _parsear_tiempo_overlay("T = 6.3 ms") == 6.3
    assert _parsear_tiempo_overlay("time 6300 us") == 6.3
    assert _parsear_tiempo_overlay("frame 12345") is None
