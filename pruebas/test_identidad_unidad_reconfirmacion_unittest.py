import ast
import unittest
from pathlib import Path


class IdentidadUnidadReconfirmacionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ruta = Path(__file__).resolve().parents[1] / "dashboard/backend/app.py"
        tree = ast.parse(ruta.read_text(encoding="utf-8"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_buscar_unidad_ocr")
        env = {"normalizar_codigo": lambda s: str(s or "").strip(), "_bbox_igual": lambda a, b: a == b}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "helper", "exec"), env)
        cls.buscar = staticmethod(env["_buscar_unidad_ocr"])

    def test_tipo_unidad_desambigua_token_y_renglon_con_misma_caja(self):
        unidades = [
            {"tipo_unidad": "token", "texto": "85", "bbox": [10, 20, 40, 20]},
            {"tipo_unidad": "renglón", "texto": "3", "bbox": [10, 20, 40, 20]},
        ]
        elegido = self.buscar(unidades, "3", [10, 20, 40, 20], "renglón")
        self.assertIsNotNone(elegido)
        self.assertEqual(elegido["tipo_unidad"], "renglón")
        self.assertEqual(elegido["texto"], "3")

    def test_sin_tipo_se_mantiene_compatibilidad_anterior(self):
        unidades = [{"texto": "3", "bbox": [1, 2, 3, 4]}]
        self.assertEqual(self.buscar(unidades, "3", [1, 2, 3, 4])["texto"], "3")


if __name__ == "__main__":
    unittest.main()
