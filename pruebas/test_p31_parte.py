"""Pruebas del número de parte moldeado del tablero (P31).

Lo que se prueba es la parte que **no** depende del OCR: la normalización de lo leído (la letra
grabada con puntos se lee `2G1`, `201`, `2GL`; el bloque final se lee `(` o `3`) y la detección de
renglones punteados sobre la foto del 222504, que es donde se comprobó a mano el número.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utilidades.grabado_punteado import (  # noqa: E402
    PARTE_TABLERO, cola_del_grabado, interpretar_parte_tablero, localizar_grabado_punteado)

REFERENCIA = Path("/var/tmp/fotos/222504 RDW NOM NT/VOR/IMG_1598.JPG")


class TestNormalizacion:
    def test_lee_el_numero_entero(self):
        assert interpretar_parte_tablero("2GJ.857.003.G") == PARTE_TABLERO

    def test_tolera_la_j_leida_como_uno_y_la_g_como_parentesis(self):
        assert interpretar_parte_tablero("2G1.857.003 (G") == PARTE_TABLERO
        assert interpretar_parte_tablero("2GJ.857.003-(G1") == PARTE_TABLERO

    def test_el_bloque_final_en_digito_se_normaliza_solo_si_se_pide(self):
        assert interpretar_parte_tablero("-201.857.003 (3 1") == "2GJ.857.003.3"
        assert interpretar_parte_tablero("-201.857.003 (3 1",
                                         normalizar_digitos=True) == PARTE_TABLERO

    def test_sin_bloque_final_devuelve_lo_que_se_sostiene(self):
        assert interpretar_parte_tablero("2GJ.857.003") == ""
        assert interpretar_parte_tablero("2GJ.857.003", exigir_cola=False) == "2GJ.857.003"

    def test_no_confunde_el_numero_del_modulo(self):
        # `2GJ.880.204.J` es el del módulo y va impreso en su etiqueta: no es el del tablero
        assert interpretar_parte_tablero("2GJ.880.204.J") == ""
        assert interpretar_parte_tablero("ZRZ02S2GJ880204J") == ""

    def test_la_cola_se_lee_aparte(self):
        assert cola_del_grabado("2GJ.857.003-(G") == "G"
        assert cola_del_grabado("857.003 G") == "G"
        assert cola_del_grabado("4148399X") == ""


@pytest.mark.skipif(not REFERENCIA.exists(), reason="faltan las fotos del 222504")
class TestDeteccion:
    def test_encuentra_renglones_punteados(self):
        import cv2

        imagen = cv2.imread(str(REFERENCIA))
        cajas = localizar_grabado_punteado(imagen, maximo=6)
        assert cajas, "no encontró ninguna zona de letra punteada"
        assert all(c["puntos"] >= 8 for c in cajas)
        # el grabado del número está en la mitad derecha, por debajo del centro
        assert any(c["x"] > imagen.shape[1] * 0.3 and c["y"] > imagen.shape[0] * 0.45
                   for c in cajas)
