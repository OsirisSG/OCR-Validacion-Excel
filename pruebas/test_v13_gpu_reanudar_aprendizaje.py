from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from aprendizaje import GestorAprendizaje
from ocr_engine import MotorEasyOCR


def _gestor(tmp_path):
    return GestorAprendizaje({"aprendizaje": {
        "activar": True,
        "registrar_observaciones": True,
    }}, directorio=tmp_path / "aprendizaje")


def test_aprendizaje_incremental_es_idempotente_al_reanudar(tmp_path):
    imagen = tmp_path / "foto.jpg"
    imagen.write_bytes(b"contenido-estable")
    gestor = _gestor(tmp_path)
    resultado = {
        "imagen": str(imagen), "motor": "easyocr",
        "tokens": [{"texto": "ABC123", "confianza": .91, "bbox": [1, 2, 30, 10]}],
        "lineas_texto": [],
    }

    primera = gestor.registrar_observacion_incremental(
        resultado, raiz=str(tmp_path), ejecucion_id="exec-v13")
    segunda = gestor.registrar_observacion_incremental(
        resultado, raiz=str(tmp_path), ejecucion_id="exec-v13")

    assert primera["tokens_nuevos"] == 1
    assert segunda["tokens_nuevos"] == 0
    final = gestor.finalizar_ejecucion_incremental("exec-v13")
    assert final["imagenes"] == 1
    assert final["tokens"] == 1

    # Una ejecución realmente nueva conserva su propio historial.
    tercera = gestor.registrar_observacion_incremental(
        resultado, raiz=str(tmp_path), ejecucion_id="exec-v13-nueva")
    assert tercera["tokens_nuevos"] == 1
    with sqlite3.connect(gestor.db) as con:
        assert con.execute("SELECT COUNT(*) FROM observaciones").fetchone()[0] == 2


class _ReaderOOM:
    def __init__(self):
        self.batch_usados = []

    def readtext(self, imagen, detail, batch_size, workers, **kwargs):
        self.batch_usados.append(batch_size)
        if batch_size > 2:
            raise RuntimeError("CUDA out of memory")
        return [([[0, 0], [10, 0], [10, 5], [0, 5]], "ABC", 0.9)]


def test_gpu_reduce_batch_ante_oom_sin_abandonar_cuda():
    motor = MotorEasyOCR.__new__(MotorEasyOCR)
    motor._reader = _ReaderOOM()
    motor._allowlist = None
    motor._batch_size = 8
    motor._batch_max = 12
    motor._workers = 0
    motor.dispositivo = "cuda"
    motor.advertencias = []
    motor._perfil_gpu = "agresivo"

    lineas = motor._leer(object(), usar_allowlist=False)

    assert motor.dispositivo == "cuda"
    assert motor._reader.batch_usados == [8, 4, 2]
    assert motor._batch_size == 2
    assert lineas[0]["texto"] == "ABC"
    assert any("VRAM" in aviso for aviso in motor.advertencias)
