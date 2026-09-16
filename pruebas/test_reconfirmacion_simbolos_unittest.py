import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from aprendizaje import GestorAprendizaje, hash_archivo


class ReconfirmacionSimbolosTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ruta = Path(self.tmp.name) / "foto.jpg"
        self.ruta.write_bytes(b"foto")
        self.gestor = GestorAprendizaje({"aprendizaje": {}}, directorio=self.tmp.name)
        self.gestor.registrar_muestra_visual = lambda *a, **k: {"entrenable": k.get("entrenable")}

    def test_simbolo_original_puede_corregirse_y_sobrescribirse(self):
        r1 = self.gestor.registrar_correccion(
            ";", "4", ruta_imagen=str(self.ruta), bbox=[10, 20, 30, 40])
        r2 = self.gestor.registrar_correccion(
            ";", "41", ruta_imagen=str(self.ruta), bbox=[10, 20, 30, 40])
        self.assertEqual(r1["tipo"], "layout")
        self.assertEqual(r2["tipo"], "layout")
        ocr = {
            "dimensiones": [100, 100],
            "lineas_texto": [{"texto": ";", "bbox": [10, 20, 30, 40]}],
            "texto_completo": ";",
        }
        publicado = self.gestor.filtrar_no_texto(ocr, self.ruta)
        self.assertEqual(publicado["lineas_texto"][0]["texto"], "41")

    def test_volver_a_correccion_anterior_con_simbolo_original(self):
        for texto in ("4", "41", "4"):
            self.gestor.registrar_correccion(
                ";", texto, ruta_imagen=str(self.ruta), bbox=[10, 20, 30, 40])
        ocr = {"dimensiones": [100, 100],
               "lineas_texto": [{"texto": ";", "bbox": [10, 20, 30, 40]}]}
        publicado = self.gestor.filtrar_no_texto(ocr, self.ruta)
        self.assertEqual(publicado["lineas_texto"][0]["texto"], "4")

    def test_handler_acepta_reconfirmacion_de_puntuacion_por_bbox(self):
        item = {"id": "foto", "ruta": str(self.ruta), "resultado_ocr": {
            "dimensiones": [100, 100],
            "lineas_texto": [{"texto": ";", "bbox": [10, 20, 30, 40]}],
            "texto_completo": ";",
        }}
        env = {
            "SolicitudCorreccion": SimpleNamespace,
            "_cargar_datos": lambda: {"resultados": [{"imagenes": [item]}]},
            "_id_fila": lambda f: "caso",
            "GestorAprendizaje": lambda c: self.gestor,
            "CONFIG": {},
            "_fila_publica": lambda f: {"revision": {"estado": "parcial"}},
            "_resolver_raiz_datos": lambda d: Path(self.tmp.name),
            "_resolver_imagen": lambda *a: self.ruta,
            "_regenerar_excel": lambda r: None,
            "_bbox_igual": lambda a, b: a == b,
            "normalizar_codigo": lambda s: "" if str(s).strip() == ";" else str(s).strip(),
            "hash_archivo": hash_archivo,
        }
        tree = ast.parse((Path(__file__).resolve().parents[1] / "dashboard/backend/app.py").read_text(encoding="utf-8"))
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in
                     ("corregir_lectura", "_buscar_unidad_ocr", "_aplicar_correcciones_publicas")]
        for n in functions:
            n.decorator_list = []
        exec(compile(ast.Module(body=functions, type_ignores=[]), "handler", "exec"), env)

        for correcto in ("4", "41"):
            req = SimpleNamespace(
                prueba_id="caso", imagen_id="foto", campo="etiqueta", texto_ocr=";",
                texto_correcto=correcto, bbox=[10, 20, 30, 40], accion="corregir", usuario="test")
            env["corregir_lectura"](req)

        publicado = self.gestor.filtrar_no_texto(item["resultado_ocr"], self.ruta)
        self.assertEqual(publicado["lineas_texto"][0]["texto"], "41")


if __name__ == "__main__":
    unittest.main()
