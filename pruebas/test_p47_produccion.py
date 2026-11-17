"""P47 · Fallos vistos en la máquina del cliente (12/11): `ValueError: Cannot convert {} to Excel`,
tablero sin RapidOCR y marcas de aprendizaje que saltan OCR o tapan datos. Valores sintéticos."""
from __future__ import annotations

import sys
import types

import numpy as np
import pytest
from openpyxl import Workbook


# --- 1. Trazabilidad: votos/confianza no escalares ya no tumban la corrida --------------------
def test_trazabilidad_acepta_votos_dict_vacio_y_lleno():
    import reporte_bmg as R
    libro = Workbook()
    cands = [{"clave": "test_date", "valor_normalizado": "2031-01-02", "fuente": "ocr", "votos": {}},
             {"clave": "test_place", "valor_normalizado": "LUGAR", "votos": {"LUGAR": 2},
              "confianza_ocr": [0.9, 0.8], "bbox_original": (1, 2, 3, 4)},
             {"clave": "x", "valor_normalizado": "y", "votos": 3, "confianza_ocr": 0.7}]
    R._crear_trazabilidad(libro, [{"project_id": "P", "tipo_st": "1ST", "candidatos": cands}], "es")
    ws = libro[R._t("es", "trace")[:31]]
    filas = list(ws.iter_rows(min_row=2, values_only=True))
    assert len(filas) == 3
    assert filas[0][-2] == ""                              # {} -> vacío
    assert '"LUGAR": 2' in filas[1][-2] and "0.9" in filas[1][-1]
    assert filas[2][-2] == 3 and filas[2][-1] == 0.7


def test_celda_convierte_lo_no_escalar():
    from reporte_bmg import _celda
    assert _celda(None) == "" and _celda({}) == "" and _celda([]) == ""
    assert _celda({"a": 1}) == '{"a": 1}' and _celda({"b", "a"}) == '["a", "b"]'
    assert _celda(object()).startswith("<object")


# --- 2. Motor del proyecto con la forma de RapidOCR --------------------------------------------
class _MotorFalso:
    def leer_texto_completo(self, imagen):
        assert imagen.ndim == 3
        return [{"texto": "N/P: 2GJ.857.003.G", "bbox": (10, 20, 100, 12), "confianza": 0.91},
                {"texto": "  ", "bbox": (0, 0, 1, 1), "confianza": 0.2}]


def test_adaptador_devuelve_forma_rapidocr_y_lo_entiende_el_tablero():
    from utilidades.motor_ocr_local import MotorProyectoComoRapid
    from utilidades import tablero_campos as T
    motor = MotorProyectoComoRapid(_MotorFalso())
    resultado, tiempos = motor(np.zeros((30, 40), np.uint8))          # gris -> BGR
    assert tiempos is None and len(resultado) == 1
    caja, texto, conf = resultado[0]
    assert texto == "N/P: 2GJ.857.003.G" and conf == pytest.approx(0.91)
    assert caja == [[10, 20], [110, 20], [110, 32], [10, 32]]
    assert T._textos(np.zeros((30, 40, 3), np.uint8), motor) == [("N/P: 2GJ.857.003.G", pytest.approx(0.91))]


def test_motor_compartido_usa_el_del_proyecto_sin_rapidocr(monkeypatch):
    from utilidades import codigos_modulo as CM
    import ocr_engine
    monkeypatch.setattr(CM, "_MOTOR", None)
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", None)       # import -> ImportError
    monkeypatch.setattr(ocr_engine, "obtener_motor", lambda config=None: (_MotorFalso(), {}))
    motor = CM.motor_compartido()
    assert type(motor).__name__ == "MotorProyectoComoRapid"
    assert motor(np.zeros((5, 5, 3), np.uint8))[0][0][1] == "N/P: 2GJ.857.003.G"


def test_firma_de_cache_depende_del_motor(tmp_path, monkeypatch):
    import tablero_integracion as TI
    from utilidades import motor_ocr_local as M
    monkeypatch.setattr(M, "nombre_motor", lambda: "rapidocr")
    a = TI.CacheLecturasP42(tmp_path / "a.sqlite3")
    monkeypatch.setattr(M, "nombre_motor", lambda: "motor_proyecto")
    b = TI.CacheLecturasP42(tmp_path / "b.sqlite3")
    assert a.firma != b.firma
    a.cerrar(); b.cerrar()


# --- 3. Marcas de aprendizaje -------------------------------------------------------------------
def _gestor(tmp_path, **aprendizaje):
    from aprendizaje import GestorAprendizaje
    from configuracion import cargar_config
    config = cargar_config()
    config = {**config, "aprendizaje": {**config.get("aprendizaje", {}), **aprendizaje,
                                        "directorio": str(tmp_path / "apr")}}
    return GestorAprendizaje(config, directorio=tmp_path / "apr")


@pytest.mark.parametrize("politica,motivo,salta", [
    ("solo_con_motivo", "", False), ("solo_con_motivo", "foto_de_ambiente", True),
    ("respetar", "", True), ("ignorar", "foto_de_ambiente", False)])
def test_politica_imagenes_sin_datos(tmp_path, politica, motivo, salta):
    foto = tmp_path / "IMG_1.jpg"
    foto.write_bytes(b"\xff\xd8 sintetica")
    gestor = _gestor(tmp_path, imagenes_sin_datos=politica)
    gestor.registrar_imagen_sin_datos(foto, "caso", motivo)
    assert (gestor.sin_datos_que_salta_ocr(foto) is not None) is salta
    assert gestor.imagen_sin_datos(foto) is not None        # la marca sigue existiendo


@pytest.mark.parametrize("politica,quedan", [("sin_datos_probables", {"logo"}),
                                             ("respetar", {"logo", "10.04.31"}), ("ignorar", set())])
def test_politica_regiones_no_texto(tmp_path, politica, quedan):
    foto = tmp_path / "IMG_2.jpg"
    foto.write_bytes(b"\xff\xd8 otra sintetica")
    gestor = _gestor(tmp_path, regiones_no_texto=politica)
    gestor.marcar_no_texto(foto, [0, 0, 50, 10], "logo")
    gestor.marcar_no_texto(foto, [0, 40, 50, 10], "10.04.31")
    ocr = {"tokens": [{"texto": "logo", "bbox": [0, 0, 50, 10]},
                      {"texto": "10.04.31", "bbox": [0, 40, 50, 10]}],
           "lineas_texto": [], "codigos_detectados": []}
    salida = gestor.filtrar_no_texto(ocr, foto)
    assert {d["texto_ocr"] for d in salida["regiones_no_texto"]} == quedan
    assert {t["texto"] for t in salida["tokens"]} == {"logo", "10.04.31"} - quedan


def test_revision_de_contaminacion_es_solo_lectura(tmp_path):
    from utilidades import contaminacion_aprendizaje as C
    from aprendizaje import GestorAprendizaje
    from configuracion import cargar_config
    proyecto = tmp_path
    foto = tmp_path / "IMG_3.jpg"
    foto.write_bytes(b"\xff\xd8 tercera")
    gestor = GestorAprendizaje(cargar_config(), directorio=proyecto / ".aprendizaje")
    gestor.registrar_imagen_sin_datos(foto, "caso9", "")
    gestor.marcar_no_texto(foto, [0, 0, 5, 5], "ZRZ 031")
    (proyecto / ".cache_ocr").mkdir()
    (proyecto / ".cache_ocr" / "x.json.tmp").write_text("{}")
    antes = (proyecto / ".aprendizaje" / "aprendizaje.sqlite3").read_bytes()
    informe = C.auditar(proyecto)
    assert (proyecto / ".aprendizaje" / "aprendizaje.sqlite3").read_bytes() == antes
    base = informe["base_aprendizaje"]
    assert base["imagenes_sin_datos"]["sin_motivo_por_caso"] == {"caso9": 1}
    assert base["regiones_no_texto"]["activas_que_parecen_dato"] == 1
    assert any("temporal" in a["nota"] for a in informe["cache_ocr"]["archivos"])
    assert "Nada de esto se modificó" in C.texto(informe)
