import ast
import unittest
from pathlib import Path


class OrientacionRegionalSeguraTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ruta = Path(__file__).resolve().parents[1] / "dashboard/backend/app.py"
        cls.source = ruta.read_text(encoding="utf-8")
        tree = ast.parse(cls.source)
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                  and n.name == "_orientacion_regional_pendiente")
        env = {}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "helper", "exec"), env)
        cls.pendiente = staticmethod(env["_orientacion_regional_pendiente"])

    def test_region_dudosa_no_confirmada_es_provisional(self):
        ocr = {"recortes": [{"marco": "r1", "orientacion_dudosa": True,
                              "orientacion_confirmada": False}]}
        self.assertTrue(self.pendiente(ocr, {"marco_region": "r1"}))

    def test_region_confirmada_habilita_correccion(self):
        ocr = {"recortes": [{"marco": "r1", "orientacion_dudosa": True,
                              "orientacion_confirmada": True}]}
        self.assertFalse(self.pendiente(ocr, {"marco_region": "r1"}))

    def test_unidad_sin_region_no_se_bloquea(self):
        self.assertFalse(self.pendiente({"recortes": []}, {"texto": "232541"}))

    def test_endpoint_aplica_la_barrera(self):
        self.assertIn("_orientacion_regional_pendiente(ocr, token)", self.source)
        self.assertIn("Confirma primero la orientación regional y reprocesa la imagen", self.source)


if __name__ == "__main__":
    unittest.main()
