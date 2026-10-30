"""Selección de hardware y desambiguación de lecturas repetidas."""

from dashboard.backend.app import _buscar_unidad_ocr
from recursos import detectar_recursos


def test_cpu_explicita_siempre_es_portable():
    recursos = detectar_recursos("cpu")
    assert recursos["seleccionado"] == "cpu"
    assert recursos["cpu_hilos"] >= 1


def test_textos_repetidos_se_seleccionan_por_bbox():
    unidades = [
        {"texto": "ABC-10", "bbox": [1, 2, 30, 10]},
        {"texto": "ABC-10", "bbox": [80, 2, 30, 10]},
    ]
    assert _buscar_unidad_ocr(unidades, "ABC-10") is None
    assert _buscar_unidad_ocr(unidades, "ABC-10", [80, 2, 30, 10]) == unidades[1]
