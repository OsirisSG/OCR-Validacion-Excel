"""V10: regiones diagonales conservan las cuatro bases y añaden deskew fino."""
from unittest.mock import patch

import numpy as np

from ocr_engine import _leer_recorte_orientado


class MotorDiagonalFalso:
    nombre = "falso"

    def leer_texto_completo(self, imagen):
        h, w = imagen.shape[:2]
        # Las vistas cardinales mantienen exactamente las dimensiones base o intercambiadas.
        cardinal = (h, w) in {(40, 120), (120, 40)}
        return [{
            "texto": "ETIQUETA" if cardinal else "ETIQUETA-OK",
            "bbox": (5, 5, min(60, max(8, w - 10)), min(16, max(5, h - 10))),
            "confianza": 0.55 if cardinal else 0.93,
        }]


class MotorFinoPeor:
    nombre = "falso"

    def leer_texto_completo(self, imagen):
        h, w = imagen.shape[:2]
        cardinal = (h, w) in {(40, 120), (120, 40)}
        return [{"texto": "BUENO" if cardinal else "PEOR", "bbox": (4, 4, 30, 10),
                 "confianza": 0.90 if cardinal else 0.40}]


def test_ajuste_fino_reconoce_angulos_no_multiplos_de_90():
    imagen = np.zeros((40, 120, 3), dtype=np.uint8)
    with patch("ocr_engine.estimar_skew", return_value=-7.0):
        _, info = _leer_recorte_orientado(
            imagen, MotorDiagonalFalso(), ajuste_fino=True, ajuste_fino_todas=True)

    candidatos = {c["grados"]: c for c in info["candidatos_orientacion"]}
    assert set(candidatos) == {0, 90, 180, 270}
    assert candidatos[0]["grados_efectivos"] == 7.0
    assert candidatos[90]["grados_efectivos"] == 97.0
    assert candidatos[0]["ajuste_fino_grados"] == 7.0
    assert candidatos[0]["texto"] == "ETIQUETA-OK"
    assert info["orientacion_efectiva_grados"] in {7.0, 97.0, 187.0, 277.0}


def test_ajuste_fino_no_reemplaza_una_lectura_mejor_por_una_peor():
    imagen = np.zeros((40, 120, 3), dtype=np.uint8)
    with patch("ocr_engine.estimar_skew", return_value=-7.0):
        _, info = _leer_recorte_orientado(
            imagen, MotorFinoPeor(), ajuste_fino=True, ajuste_fino_todas=True)

    candidatos = {c["grados"]: c for c in info["candidatos_orientacion"]}
    assert candidatos[0]["grados_efectivos"] == 0.0
    assert candidatos[0]["ajuste_fino_grados"] == 0.0
    assert candidatos[0]["texto"] == "BUENO"

def test_estimador_regional_cubre_texto_diagonal_de_30_grados():
    import cv2
    from ocr_engine import estimar_skew, rotar_imagen_libre

    base = np.full((120, 400, 3), 255, dtype=np.uint8)
    cv2.putText(base, "ABC 123", (30, 75), cv2.FONT_HERSHEY_SIMPLEX,
                1.5, (0, 0, 0), 3, cv2.LINE_AA)
    diagonal = rotar_imagen_libre(base, 30)
    estimado = estimar_skew(cv2.cvtColor(diagonal, cv2.COLOR_BGR2GRAY), angulo_max=45)
    assert 25 <= estimado <= 35
