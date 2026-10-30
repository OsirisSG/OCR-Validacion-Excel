"""V14.7: relectura manual exacta sin persistir cambios."""
from pathlib import Path

import numpy as np

import ocr_engine
import dashboard.backend.app as appmod


class _GestorFalso:
    def __init__(self, *args, **kwargs):
        pass

    def listar_correcciones_texto(self, rutas):
        return []

    def filtrar_no_texto(self, ocr, ruta):
        return ocr


class _MotorFalso:
    def leer_texto_completo(self, imagen):
        return [{"texto": "S4054664", "bbox": [2, 2, 50, 12], "confianza": .83}]


def test_relectura_manual_respeta_angulo_variante_y_tipo(monkeypatch):
    monkeypatch.setattr(appmod, "GestorAprendizaje", _GestorFalso)
    monkeypatch.setattr(appmod, "_cargar_datos", lambda: {})
    monkeypatch.setattr(appmod, "_resolver_raiz_datos", lambda datos: Path("/tmp"))
    monkeypatch.setattr(appmod, "_resolver_imagen", lambda ruta, datos, raiz: Path("/tmp/fake.jpg"))
    monkeypatch.setattr(appmod, "_aplicar_correcciones_publicas", lambda ocr, corr: ocr)
    monkeypatch.setattr(appmod, "_orientacion_base_publica", lambda ocr: 0)
    monkeypatch.setattr(ocr_engine, "cargar_imagen", lambda ruta: np.zeros((60, 100, 3), dtype=np.uint8))
    monkeypatch.setattr(ocr_engine, "obtener_motor", lambda cfg: (_MotorFalso(), {}))

    resultado = appmod._leer_angulo_manual_caja_exacta(
        {}, {"ruta": "fake.jpg", "resultado_ocr": {"dimensiones": [100, 60]}},
        [0, 0, 80, 30], orientacion_base=90, ajuste_manual=-4,
        variante="auto", tipo_esperado="codigo")

    assert resultado["texto"] == "S4054664"
    assert resultado["tipo_informacion"] == "codigo"
    assert resultado["coincide_tipo_esperado"] is True
    assert resultado["grados_efectivos"] == 86.0
    assert len(resultado["intentos"]) == 4
