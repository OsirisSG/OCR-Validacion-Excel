"""Pruebas del pie de vídeo (fecha de prueba) y del escaneo de un caso (P14)."""
from __future__ import annotations

import numpy as np
import pytest

from utilidades.video_pie import capturar, fecha_de_video, informacion, interpretar, recortar_pie


def test_interpreta_las_tres_formas_de_fecha():
    assert interpretar("17/05/2025 10:26:37")["fecha"] == "2025-05-17"
    assert interpretar("2025-05-17")["fecha"] == "2025-05-17"
    assert interpretar("17 MAY 2025 08:11")["fecha"] == "2025-05-17"
    assert interpretar("grabación sin rótulo")["fecha"] is None


def test_interpreta_la_hora():
    assert interpretar("17/05/2025 10:26:37")["hora"] == "10:26:37"
    assert interpretar("17/05/2025")["hora"] is None


def test_fecha_imposible_no_pasa():
    assert interpretar("45/13/2025")["fecha"] is None


def test_recorte_del_pie_es_la_franja_inferior():
    fotograma = np.zeros((200, 300, 3), np.uint8)
    fotograma[168:, :] = 255                      # el 16 % inferior, en blanco
    pie = recortar_pie(fotograma, 0.16)
    assert pie.shape[0] == pytest.approx(32, abs=2)
    assert pie.mean() > 200


def test_video_real_sin_ocr_deja_el_pie_como_imagen(tmp_path):
    from pathlib import Path
    video = Path("datos_prueba/Lote_Pruebas/01_A1_variante2/video_ensayo.mp4")
    if not video.is_file():
        pytest.skip("no hay vídeo de prueba en este árbol")
    datos = informacion(video)
    assert datos["ok"] and datos["fotogramas"] > 0
    resultado = fecha_de_video(video, carpeta_evidencia=tmp_path, caso="prueba")
    assert resultado["estado"] == "sin_leer"
    assert (tmp_path / "prueba_pie_video.png").is_file()


def test_con_ocr_simulado_sale_la_fecha(tmp_path):
    from pathlib import Path
    video = Path("datos_prueba/Lote_Pruebas/01_A1_variante2/video_ensayo.mp4")
    if not video.is_file():
        pytest.skip("no hay vídeo de prueba en este árbol")
    resultado = fecha_de_video(video, motor_ocr=lambda imagen: "2025-05-17 10:26:37",
                               carpeta_evidencia=tmp_path)
    assert resultado["estado"] == "leido"
    assert resultado["fecha"] == "2025-05-17"


def test_fechas_escritas_en_espanol():
    assert interpretar("17 de mayo de 2025")["fecha"] == "2025-05-17"
    assert interpretar("17 DE MAYO DEL 2025")["fecha"] == "2025-05-17"
    assert interpretar("martes 17 de mayo de 2025 10:26")["fecha"] == "2025-05-17"
    assert interpretar("martes 17 de mayo de 2025 10:26")["hora"] == "10:26"
    assert interpretar("Mayo 17, 2025")["fecha"] == "2025-05-17"
    assert interpretar("Jueves 3 de diciembre de 2025")["fecha"] == "2025-12-03"
