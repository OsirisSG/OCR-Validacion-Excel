#!/usr/bin/env python3
"""P24 · lugar de prueba desde la **cabecera** del vídeo y fecha desde la **barra**.

La cabecera tiene el logotipo a la izquierda (`EDAG México`) y el nombre del laboratorio a la derecha
(`EDAG Testlab`); la barra inferior lleva el número y la fecha (`04 JUN 25`).

Se comprueba:
1. `EDAG Testlab`, `EDAG México`, `EDAG Mex` y `EDAGTESTLAB` son **el mismo lugar** (`EDAG`); `VW…` → `VW`;
2. lo que no es un laboratorio conocido **no** se convierte en lugar;
3. la captura de evidencia se genera con las dos zonas y no falla si el fotograma es pequeño;
4. la barra entrega su texto completo (de ahí sale el proyecto `BMG`).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utilidades import video_cabecera as VC


class TestLugarDeTexto:
    def test_edag_testlab(self):
        assert VC.lugar_de_texto("EDAG Testlab") == "EDAG"

    def test_edag_mexico(self):
        assert VC.lugar_de_texto("三EDAGMexico") == "EDAG"

    def test_edag_mex_de_la_barra(self):
        assert VC.lugar_de_texto("EDAG Mex") == "EDAG"

    def test_pegado_sin_espacios(self):
        assert VC.lugar_de_texto("EDAGTestlab") == "EDAG"

    def test_laboratorio_vw(self):
        assert VC.lugar_de_texto("VW Testlab") == "VW"

    def test_no_inventa_lugar(self):
        assert VC.lugar_de_texto("Rec5000 fps") == ""

    def test_vacio(self):
        assert VC.lugar_de_texto("") == ""


class TestNormalizacion:
    def test_mismo_lugar_con_distintas_formas(self):
        from rellenar_desde_referencia import normalizar_lugar
        assert normalizar_lugar("EDAG MEX") == normalizar_lugar("EDAG Testlab") == "EDAG"

    def test_lugares_distintos(self):
        from rellenar_desde_referencia import normalizar_lugar
        assert normalizar_lugar("EDAG Testlab") != normalizar_lugar("VW")


class TestCapturaDeEvidencia:
    def fotograma(self, alto=200, ancho=400):
        return np.full((alto, ancho, 3), 40, np.uint8)

    def test_escribe_el_archivo(self, tmp_path):
        destino = tmp_path / "captura.png"
        VC.captura_de_evidencia(self.fotograma(), {"lugar": "EDAG", "lugar_leido": "EDAG Testlab"},
                                {"numero": "252590", "fecha": "2025-06-19", "semana": "25",
                                 "texto": "VW316/5 252590 RdW RT NOM 0ms EDAG Mex BMG 19 JUN 25"},
                                destino)
        assert destino.exists() and destino.stat().st_size > 0

    def test_no_falla_con_fotograma_pequeno(self, tmp_path):
        destino = tmp_path / "pequena.png"
        VC.captura_de_evidencia(self.fotograma(30, 60), {}, {}, destino)
        assert destino.exists()


class TestBarraDelCaso:
    def test_la_barra_entrega_su_texto(self, monkeypatch):
        import rellenar_desde_videos as R

        def falso(ruta, muestras=5, banco=None, lexico=None):
            return {"campos": {"test_number": "252590", "test_date": "2025-06-19",
                               "test_place": "EDAG MEX"},
                    "acuerdo": {}, "muestras": 3,
                    "texto": "VW316/5 252590 RdW RT NOM 0ms EDAG Mex BMG 19 JUN 25"}

        monkeypatch.setattr(R, "leer_video", falso)
        salida = R.leer_caso([Path("a.avi")], banco={})
        assert salida["test_number"]["valor"] == "252590"
        assert "EDAG Mex BMG" in salida["__resumen__"]["texto"]

    def test_el_proyecto_sale_de_ese_texto(self):
        from utilidades import pizarra
        texto = "VW316/5 252590 RdW RT NOM 0ms EDAG Mex BMG 19 JUN 25"
        assert pizarra.proyecto_en_barra(texto) == "BMG"
