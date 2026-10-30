import inspect

import generar_excel
import pipeline
from dashboard.backend import app as backend


def test_pipeline_y_generador_aceptan_idiomas_sin_repetir_ocr():
    assert "idiomas_exportacion" in inspect.signature(pipeline.ejecutar_pipeline).parameters
    assert "idioma" in inspect.signature(generar_excel.generar_excel).parameters
    assert backend._normalizar_idiomas_exportacion(["es","en","de"]) == ["es","en","de"]


def test_config_publica_idiomas_y_nombre():
    cfg = backend.config_dashboard()
    assert cfg["nombre_herramienta"] == "OCR Versuchsmatrix"
    assert cfg["idiomas_interfaz"] == ["es","en","de"]
    assert cfg["idiomas_exportacion"] == ["es","en","de"]
