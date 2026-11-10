#!/usr/bin/env python3
"""P21 · lectura de la pizarra escrita a mano y motivo de prueba (`IT` + `BMG`).

Lo que se comprueba aquí es lo que hace fiable la unión de los dos tokens:

1. el rotulador se lee mal (`BM6`, `BME`, `BMC`, `8MG`) y hay que repararlo **sin** aceptar
   parecidos genéricos (`RO` **no** es `RT`);
2. el motivo sólo se cierra cuando están los dos tokens, y se unen con un espacio;
3. el vocabulario sale del propio libro (`IT BMG` → tipo `IT`, proyecto `BMG`);
4. la temperatura de la pizarra (`+85 °C`) no se confunde con el zoom del visor (`100%`).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utilidades import pizarra as P


class TestReparacionDeTokens:
    def test_rotulador_g_como_seis(self):
        assert P.emparejar("BM6", P.PROYECTOS, largo=3)[0] == "BMG"

    def test_rotulador_g_como_e(self):
        assert P.emparejar("BME", P.PROYECTOS, largo=3) == ("BMG", 1)

    def test_rotulador_g_como_c(self):
        assert P.emparejar("BMC", P.PROYECTOS, largo=3)[0] == "BMG"

    def test_b_como_ocho(self):
        assert P.emparejar("8MG", P.PROYECTOS, largo=3)[0] == "BMG"

    def test_exacto_sin_reparacion(self):
        assert P.emparejar("BMG", P.PROYECTOS, largo=3) == ("BMG", 0)

    def test_no_se_acepta_un_parecido_generico(self):
        # `RO` está a una edición de `RT`, pero O y T no se confunden al escribir a mano
        assert P.emparejar("RO", P.TIPOS_PRUEBA, largo=2) is None

    def test_no_se_acepta_otro_largo(self):
        assert P.emparejar("BMGX", P.PROYECTOS, largo=3) is None

    def test_palabra_larga_no_es_proyecto(self):
        assert P.emparejar("BMGXAYUDA", P.PROYECTOS, largo=3) is None


class TestVocabulario:
    def test_vocabulario_del_libro_sale_de_los_motivos(self):
        vocabulario = P.motivo_del_libro(["IT BMG", "IT BMG", "IT BMG"])
        assert "IT" in vocabulario["tipos"]
        assert "BMG" in vocabulario["proyectos"]

    def test_vocabulario_por_defecto_si_el_libro_esta_vacio(self):
        vocabulario = P.motivo_del_libro([])
        assert set(vocabulario["tipos"]) == set(P.TIPOS_PRUEBA)
        assert set(vocabulario["proyectos"]) == set(P.PROYECTOS)


class TestComposicionDelMotivo:
    def test_maximo_de_pista_falsa_en_una_imagen(self, monkeypatch):
        """Sin pizarra de verdad no se inventa motivo: queda en «faltan»."""
        monkeypatch.setattr(P, "_lineas_utiles", lambda *a, **k: [("BM6", 0.6)])
        lectura = P.leer_pizarra(np.zeros((10, 10, 3), np.uint8), motor=None)
        assert lectura["proyecto"] == "BMG"
        assert lectura["motivo"] == ""
        assert "tipo_prueba" in lectura["faltan"]

    def test_se_unan_los_dos_tokens(self, monkeypatch):
        monkeypatch.setattr(P, "_lineas_utiles",
                            lambda *a, **k: [("VW316/5", 0.6), ("IT 035", 0.6), ("BM6", 0.55)])
        lectura = P.leer_pizarra(np.zeros((10, 10, 3), np.uint8), motor=None)
        assert lectura["motivo"] == "IT BMG"
        assert lectura["faltan"] == []
        assert lectura["proyecto_leido"] == "BM6"

    def test_numero_escrito_a_mano_da_la_semana(self, monkeypatch):
        monkeypatch.setattr(P, "_lineas_utiles", lambda *a, **k: [("23.2550", 0.7)])
        lectura = P.leer_pizarra(np.zeros((10, 10, 3), np.uint8), motor=None)
        assert lectura["numero"] == "232550"
        assert lectura["semana"] == "23"

    def test_la_temperatura_no_es_el_zoom_del_visor(self, monkeypatch):
        monkeypatch.setattr(P, "_lineas_utiles", lambda *a, **k: [("100%", 0.8), ("+85 C", 0.7)])
        lectura = P.leer_pizarra(np.zeros((10, 10, 3), np.uint8), motor=None)
        assert lectura.get("temperatura") == "+85"
