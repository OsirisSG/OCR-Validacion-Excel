"""Ejecuta el handler real con almacenamiento y OCR simulados; no requiere FastAPI/GPU."""
import ast
import sqlite3
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from utilidades.edicion_zonas import aplicar


class HTTPError(Exception):
    def __init__(self, status, detail):
        self.status_code = status
        super().__init__(detail)


class ApiZonasTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.addCleanup(self.con.close)
        self.ocr = {"dimensiones": [100,100], "lineas_texto": [
            {"texto": "10.04", "bbox": [10,10,30,10]}]}
        con = self.con
        class Gestor:
            def __init__(self, config): pass
            def _conectar(self): return con
            def estado_revision(self, *args): return {"estado": "parcial"}
            def listar_correcciones_texto(self, *args): return []
            def listar_anotaciones(self, *args): return []
            def actualizar_revision(self, *args, **kwargs): pass
            def filtrar_no_texto(self, ocr, ruta): return aplicar(con, "hash", ocr)
        item = {"id": "imagen", "ruta": "foto.jpg", "resultado_ocr": self.ocr}
        self.env = {"SolicitudZona": SimpleNamespace, "_zona_lock": threading.Lock(),
                    "_pipeline_hilo": None, "HTTPException": HTTPError,
                    "_cargar_datos": lambda: {"resultados": [{"imagenes": [item]}]},
                    "_id_fila": lambda f: "caso", "GestorAprendizaje": Gestor, "CONFIG": {},
                    "_fila_publica": lambda f: {"revision": {"estado": "parcial"}},
                    "_resolver_raiz_datos": lambda d: Path("."),
                    "_resolver_imagen": lambda *args: Path("foto.jpg"),
                    "hash_archivo": lambda p: "hash", "_aplicar_correcciones_publicas": lambda o,c:o,
                    "_regenerar_excel": lambda r: r.update(excel_pendiente=True),
                    "rotar_imagen_libre": lambda im,g:im, "_orientacion_base_publica": lambda o:0}
        tree = ast.parse((Path(__file__).resolve().parents[1]/"dashboard/backend/app.py").read_text(encoding="utf-8"))
        fun = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "editar_zona")
        fun.decorator_list = []
        exec(compile(ast.Module(body=[fun], type_ignores=[]), "handler", "exec"), self.env)

    def llamar(self, **kwargs):
        data = dict(prueba_id="caso", imagen_id="imagen", bbox=[10,10,40,15],
                    accion="previsualizar", releer=False, firma="", texto="")
        return self.env["editar_zona"](SimpleNamespace(**(data | kwargs)))

    def test_previsualizar_guardar_deshacer(self):
        p = self.llamar()
        self.assertEqual(p["texto"], "10.04")
        r = self.llamar(accion="guardar", firma=p["firma"], texto="10.04.25")
        self.assertTrue(r["excel_pendiente"])
        with self.assertRaises(HTTPError) as e:
            self.llamar(accion="guardar", firma=p["firma"], texto="viejo")
        self.assertEqual(e.exception.status_code, 409)
        p = self.llamar(accion="estado")
        self.llamar(accion="deshacer", firma=p["firma"])
        self.assertEqual(self.llamar()["texto"], "10.04")

    def test_relectura_usa_motor_no_tupla_y_conserva_puntos(self):
        motor = object()
        def leer(im, m):
            self.assertIs(m, motor)
            self.assertEqual(im.shape[:2], (15,40))
            return [{"texto":"10.04.25"}], {"orientacion_dudosa":False}
        ocr = SimpleNamespace(cargar_imagen=lambda p: np.zeros((100,100,3)),
                              obtener_motor=lambda c:(motor, {}), _leer_recorte_orientado=leer)
        cv = SimpleNamespace(INTER_CUBIC=1, resize=lambda im, *a, **kw:im)
        with patch.dict("sys.modules", {"cv2":cv, "ocr_engine":ocr}):
            self.assertEqual(self.llamar(releer=True)["texto"], "10.04.25")

    def test_bloquea_pipeline_vivo(self):
        self.env["_pipeline_hilo"] = SimpleNamespace(is_alive=lambda:True)
        with self.assertRaises(HTTPError) as e: self.llamar()
        self.assertEqual(e.exception.status_code, 409)
        self.assertFalse(self.env["_zona_lock"].locked())

    def test_caja_exacta_no_se_expande_y_guardado_division(self):
        p = self.llamar(bbox=[12,11,10,5], exacta=True)
        self.assertEqual(p["bbox"], [12,11,10,5])
        self.llamar(accion="guardar_bloque", origen=[10,10,30,10], firma=p["firma"],
                    regiones=[SimpleNamespace(bbox=[10,10,15,10],texto="A"),
                              SimpleNamespace(bbox=[25,10,15,10],texto="B")])
        self.assertEqual(self.llamar()["bloques"], 2)


if __name__ == "__main__": unittest.main()
