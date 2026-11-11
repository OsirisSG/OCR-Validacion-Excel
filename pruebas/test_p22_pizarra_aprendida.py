#!/usr/bin/env python3
"""P22 · la pizarra se compara con lo aprendido en las demás carpetas.

Reglas que se comprueban:

1. el proyecto también se puede leer de la **barra del vídeo** (`EDAG Mex BMG`), con la misma reparación
   de rotulador (`BM6` → `BMG`);
2. lo que se repite entre carpetas se cuenta y se guarda (`aprendizaje/pizarra.json`);
3. si el **tipo de prueba** no se lee, se toma el que más se repite **sólo** si la repetición es alta
   (≥ 0.6) y siempre marcado como `tipo_por_repeticion` — nunca se hace pasar por lectura;
4. una lectura buena **nunca** se sobrescribe con lo aprendido.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utilidades import pizarra as P


class TestProyectoEnLaBarra:
    def test_lee_el_proyecto_de_la_barra(self):
        assert P.proyecto_en_barra("9DM81ex5 252590 RdW RT NOM 0ms EDAG Mex BMG 19 JUN 25") == "BMG"

    def test_repara_el_rotulador_de_la_barra(self):
        assert P.proyecto_en_barra("252590 RdW RT EDAG Mex BM6 19 JUN 25") == "BMG"

    def test_sin_proyecto_no_inventa(self):
        assert P.proyecto_en_barra("252590 RdW RT NOM 0ms 19 JUN 25") == ""

    def test_texto_vacio(self):
        assert P.proyecto_en_barra("") == ""


class TestAprendizajeEntreCarpetas:
    def test_cuenta_lo_que_se_repite(self):
        aprendizaje = P.aprender_de_lecturas([
            {"proyecto": "BMG", "tipo_prueba": "IT", "temperatura": "+85"},
            {"proyecto": "BMG", "tipo_prueba": "IT", "temperatura": "+85"},
            {"proyecto": "BMG", "temperatura": "+23"},
        ])
        assert aprendizaje["casos"] == 3
        assert aprendizaje["proyectos"]["BMG"] == 3
        assert aprendizaje["tipos"]["IT"] == 2
        assert aprendizaje["repeticion"]["proyectos"] == 1.0

    def test_guarda_y_carga(self, tmp_path):
        ruta = tmp_path / "pizarra.json"
        P.guardar_aprendizaje({"casos": 2, "proyectos": {"BMG": 2}}, ruta)
        assert P.cargar_aprendizaje(ruta)["proyectos"] == {"BMG": 2}

    def test_sin_fichero_no_falla(self, tmp_path):
        assert P.cargar_aprendizaje(tmp_path / "no_existe.json") == {}


class TestCompletarConLoAprendido:
    def aprendizaje(self, repeticion=0.8):
        return {"casos": 10, "tipos": {"IT": 8}, "repeticion": {"tipos": repeticion}}

    def test_completa_el_tipo_que_se_repite(self):
        lectura = P.completar_con_lo_aprendido({"proyecto": "BMG", "faltan": ["tipo_prueba"]},
                                               self.aprendizaje())
        assert lectura["tipo_prueba"] == "IT"
        assert lectura["motivo"] == "IT BMG"
        assert lectura["tipo_por_repeticion"] == "8/10 carpetas"
        assert lectura["faltan"] == []

    def test_no_completa_si_la_repeticion_es_baja(self):
        lectura = P.completar_con_lo_aprendido({"proyecto": "BMG", "faltan": ["tipo_prueba"]},
                                               self.aprendizaje(repeticion=0.4))
        assert lectura.get("tipo_prueba") is None

    def test_no_sobrescribe_una_lectura_buena(self):
        lectura = P.completar_con_lo_aprendido({"proyecto": "BMG", "tipo_prueba": "HT"}, self.aprendizaje())
        assert lectura["tipo_prueba"] == "HT"

    def test_sin_proyecto_no_completa(self):
        lectura = P.completar_con_lo_aprendido({"faltan": ["tipo_prueba", "proyecto"]}, self.aprendizaje())
        assert lectura.get("tipo_prueba") is None
