"""V14.4: selección de orientación por congruencia antes del ajuste fino."""
from unittest.mock import patch

import numpy as np

from ocr_engine import _leer_recorte_orientado, _perfil_congruencia_region


def _lectura(texto, confianza):
    return [{"texto": texto, "bbox": (5, 5, 80, 14), "confianza": confianza}]


class MotorMarcado:
    """Lee un texto distinto según la marca colocada por la rotación simulada."""
    nombre = "falso"

    def leer_texto_completo(self, imagen):
        marcador = int(imagen[0, 0, 0])
        fino = int(imagen[0, 0, 1]) == 255
        if fino:
            return _lectura("1", .99)
        return {
            0: _lectura("1", .959),
            1: _lectura("1CF5Dr", .70),
            2: _lectura("1", .881),
            3: _lectura("S4054664", .806),
        }[marcador]


def _rotar_marcada(imagen, grados):
    salida = imagen.copy()
    salida[0, 0, 0] = int(grados // 90)
    return salida


def test_codigo_completo_gana_a_fragmento_de_mayor_confianza():
    imagen = np.zeros((40, 120, 3), dtype=np.uint8)
    with patch("ocr_engine._rotar_recto", side_effect=_rotar_marcada):
        _, info = _leer_recorte_orientado(imagen, MotorMarcado(), ajuste_fino=False)

    assert info["orientacion_grados"] == 270
    assert info["orientacion_recomendada_grados"] == 270
    assert info["criterio_orientacion"] == "congruencia_codigo_pre_ajuste"
    assert info["candidatos_orientacion"][0]["grados"] == 270
    assert info["candidatos_orientacion"][0]["recomendada"] is True
    assert info["candidatos_orientacion"][0]["texto"] == "S4054664"
    assert info["candidatos_orientacion"][0]["probable_codigo"] is True


def test_alfanumerico_de_caso_uniforme_supera_mezcla_inconsistente():
    uniforme = _perfil_congruencia_region(_lectura("S4054664", .80), .80)
    mixto = _perfil_congruencia_region(_lectura("1CF5Dr", .95), .95)
    minusculas = _perfil_congruencia_region(_lectura("abc12345", .75), .75)

    assert uniforme["clave"] > mixto["clave"]
    assert uniforme["probable_codigo"] is True
    assert mixto["mayus_minus_coherente"] is False
    assert minusculas["probable_codigo"] is True


def test_ajuste_fino_no_sustituye_codigo_por_fragmento_con_mas_confianza():
    imagen = np.zeros((40, 120, 3), dtype=np.uint8)

    def rotar_fino(vista, _grados):
        salida = vista.copy()
        salida[0, 0, 1] = 255
        return salida, np.eye(3, dtype=float)

    with patch("ocr_engine._rotar_recto", side_effect=_rotar_marcada), \
         patch("ocr_engine.estimar_skew", return_value=-6.8), \
         patch("ocr_engine.rotar_imagen_libre_con_matriz", side_effect=rotar_fino):
        _, info = _leer_recorte_orientado(
            imagen, MotorMarcado(), ajuste_fino=True, ajuste_fino_todas=True,
            angulo_fino_max=45.0)

    candidato = next(c for c in info["candidatos_orientacion"] if c["grados"] == 270)
    assert candidato["texto"] == "S4054664"
    assert candidato["ajuste_fino_grados"] == 0.0
    assert candidato["recomendada"] is True
