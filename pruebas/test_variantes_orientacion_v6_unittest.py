"""Regresión V6: el bloque exacto obtiene siempre las cuatro variantes de orientación.

No usa GPU ni datos reales: simula la lectura OCR y verifica que la ruta de solo
lectura conserva el orden de calidad y no depende de las reglas de edición de zona.
"""
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

import dashboard.backend.app as app


class _GestorFalso:
    def __init__(self, *_args, **_kwargs):
        pass

    def listar_correcciones_texto(self, *_args):
        return []

    def filtrar_no_texto(self, ocr, _ruta):
        return ocr


class VariantesOrientacionV6Test(unittest.TestCase):
    def test_cuatro_variantes_caja_exacta_en_orden_del_motor(self):
        item = {"ruta": "foto.jpg", "resultado_ocr": {"dimensiones": [100, 100]}}
        orientacion = {"candidatos_orientacion": [
            {"grados": 270, "confianza": .88, "texto": "DOS"},
            {"grados": 0, "confianza": .52, "texto": "CERO"},
            {"grados": 180, "confianza": .49, "texto": "CIENTO OCHENTA"},
            {"grados": 90, "confianza": .22, "texto": "NOVENTA"},
        ]}
        with patch.object(app, "_cargar_datos", return_value={"resultados": []}), \
             patch.object(app, "GestorAprendizaje", _GestorFalso), \
             patch.object(app, "_resolver_raiz_datos", return_value=Path(".")), \
             patch.object(app, "_resolver_imagen", return_value=Path("foto.jpg")), \
             patch.object(app, "_aplicar_correcciones_publicas", side_effect=lambda o, _c: o), \
             patch.object(app, "rotar_imagen_libre", side_effect=lambda im, _g: im), \
             patch.object(app, "_orientacion_base_publica", return_value=0), \
             patch("ocr_engine.cargar_imagen", return_value=np.zeros((100, 100, 3), dtype=np.uint8)), \
             patch("ocr_engine.obtener_motor", return_value=(object(), {})), \
             patch("ocr_engine._leer_recorte_orientado", return_value=([], orientacion)):
            resultado = app._leer_variantes_caja_exacta({}, item, [10, 10, 20, 10])

        self.assertEqual([c["grados"] for c in resultado["candidatos_orientacion"]],
                         [270, 0, 180, 90])
        self.assertEqual(resultado["candidatos_orientacion"][1]["texto"], "CERO")

    def test_rellena_angulos_sin_lectura(self):
        item = {"ruta": "foto.jpg", "resultado_ocr": {"dimensiones": [100, 100]}}
        orientacion = {"candidatos_orientacion": [
            {"grados": 0, "confianza": .75, "texto": "ABC"},
        ]}
        with patch.object(app, "_cargar_datos", return_value={"resultados": []}), \
             patch.object(app, "GestorAprendizaje", _GestorFalso), \
             patch.object(app, "_resolver_raiz_datos", return_value=Path(".")), \
             patch.object(app, "_resolver_imagen", return_value=Path("foto.jpg")), \
             patch.object(app, "_aplicar_correcciones_publicas", side_effect=lambda o, _c: o), \
             patch.object(app, "rotar_imagen_libre", side_effect=lambda im, _g: im), \
             patch.object(app, "_orientacion_base_publica", return_value=0), \
             patch("ocr_engine.cargar_imagen", return_value=np.zeros((100, 100, 3), dtype=np.uint8)), \
             patch("ocr_engine.obtener_motor", return_value=(object(), {})), \
             patch("ocr_engine._leer_recorte_orientado", return_value=([], orientacion)):
            resultado = app._leer_variantes_caja_exacta({}, item, [10, 10, 20, 10])

        self.assertEqual({c["grados"] for c in resultado["candidatos_orientacion"]},
                         {0, 90, 180, 270})
        vacias = [c for c in resultado["candidatos_orientacion"] if c["grados"] != 0]
        self.assertTrue(all(c["texto"] == "" for c in vacias))


if __name__ == "__main__":
    unittest.main()
