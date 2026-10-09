import sqlite3
from pathlib import Path

import cv2
import numpy as np

from aprendizaje import GestorAprendizaje
from configuracion import cargar_config


def test_observacion_incremental_es_idempotente(tmp_path):
    imagen = tmp_path / "etiqueta.png"
    cv2.imwrite(str(imagen), np.zeros((24, 80, 3), dtype=np.uint8))
    cfg = {"aprendizaje": {"activar": True, "registrar_observaciones": True,
                            "directorio": str(tmp_path / "apr")}}
    gestor = GestorAprendizaje(cfg)
    resultado = {"imagen": str(imagen), "motor": "easyocr",
                 "tokens": [{"texto": "ABC001", "bbox": [1, 2, 20, 8],
                             "confianza": 0.95}], "lineas_texto": []}
    gestor.registrar_observacion_incremental(resultado, raiz=str(tmp_path), ejecucion_id="ejecucion-1")
    gestor.registrar_observacion_incremental(resultado, raiz=str(tmp_path), ejecucion_id="ejecucion-1")
    with sqlite3.connect(gestor.db) as con:
        assert con.execute("SELECT COUNT(*) FROM observaciones").fetchone()[0] == 1


def test_v13_activa_gpu_agresiva():
    cfg = cargar_config()
    rendimiento = cfg["fase1"]["rendimiento"]
    # V14 sustituyó el interruptor gpu_agresivo por el perfil adaptativo.
    assert rendimiento["perfil_gpu"] == "adaptativo"
    assert rendimiento["batch_gpu"] >= 4
