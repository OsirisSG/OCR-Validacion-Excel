import json

import pipeline
from inventario import cargar_inventario, crear_inventario, estructura_desde_inventario


def _estructura(tmp_path):
    foto = tmp_path / "Proyecto_1ST" / "HT" / "1 RDW NOM HT" / "PHOTOS" / "NACH" / "a.jpg"
    foto.parent.mkdir(parents=True)
    foto.write_bytes(b"imagen")
    caso = {"case_key": "proyecto|1ST|HT/1 RDW NOM HT", "nombre": "1 RDW NOM HT",
            "ruta": str(foto.parents[2]), "ruta_relativa": "HT/1 RDW NOM HT",
            "estructura_valida": True, "fotos": [{"ruta": str(foto),
            "ruta_relativa": "PHOTOS/NACH/a.jpg", "fase": "NACH", "tor": None}],
            "tipo_st": "1ST", "metadata_ruta": {"test_number": "1"},
            "modo_procesamiento": "empresarial", "validaciones": {}}
    return {"raiz": str(tmp_path / "Proyecto_1ST"), "perfil": "empresarial",
            "tipo_st": "1ST", "tipos_st": ["1ST"], "total_carpetas": 1,
            "patron_dominante": None, "anomalias": [], "carpetas": [],
            "casos_empresariales": [caso], "casos_validos": 1, "casos_incompletos": 0,
            "requiere_seleccion_tipo_st": False}


def test_inventario_persiste_firmas_y_reconstruye(tmp_path):
    ruta = tmp_path / "inventario.json"
    creado = crear_inventario(_estructura(tmp_path), ruta)
    cargado = cargar_inventario(ruta, tmp_path / "Proyecto_1ST")
    reconstruida = estructura_desde_inventario(cargado)
    assert creado["fotografias"] == 1
    assert cargado["casos"][0]["fotos"][0]["firma_archivo"]["huella"]
    assert reconstruida["casos_empresariales"][0]["total_imagenes"] == 1


def test_modo_solo_inventario_no_ejecuta_ocr_ni_excel(monkeypatch, tmp_path):
    estructura = _estructura(tmp_path)
    monkeypatch.setattr(pipeline, "RAIZ_PROYECTO", tmp_path)
    monkeypatch.setattr(pipeline, "mapear_estructura", lambda *args, **kwargs: estructura)
    monkeypatch.setattr(pipeline, "guardar_estructura", lambda datos: tmp_path / "estructura.json")
    monkeypatch.setattr(pipeline, "validar_lote_empresarial",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("OCR ejecutado")))
    monkeypatch.setattr(pipeline, "generar_excel",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Excel ejecutado")))
    salida = pipeline.ejecutar_pipeline(
        estructura["raiz"], config={"fase1": {}, "fase3": {}, "empresarial": {}},
        modo_ejecucion="inventario", ruta_inventario=tmp_path / "inventario.json")
    assert salida["fases"]["fase_a"]["fotografias"] == 1
    assert "fase2" not in salida["fases"]
