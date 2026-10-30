from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
APP_PATH = ROOT / "dashboard" / "backend" / "app.py"
spec = importlib.util.spec_from_file_location("dashboard_app_v13_resume", APP_PATH)
app = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(app)


class ReanudarV13Tests(unittest.TestCase):
    def test_reanudar_reserva_estado_antes_de_lanzar_nuevo_hilo(self):
        original_estado = dict(app._pipeline_estado)
        original_hilo = app._pipeline_hilo
        original_iniciar = app.iniciar_pipeline
        original_persistir = app._persistir_checkpoint_pipeline
        vistos = {}
        try:
            app._pipeline_hilo = None
            app._pipeline_estado.update({
                "estado": "detenido_con_avance",
                "ejecucion_id": "exec-estable",
                "resultados_parciales": [],
                "ultimo_id": None,
                "ultimo_id_nombre": None,
                "solicitud": {
                    "ruta": str(ROOT),
                    "nombre_excel": None,
                    "sobrescribir_excel": False,
                    "tipo_st": "LEGACY",
                    "plantilla_id": None,
                    "modo_ejecucion": "completo",
                    "idiomas_exportacion": ["es"],
                    "casos_omitidos": [],
                    "ejecucion_id": "exec-estable",
                },
            })
            app._persistir_checkpoint_pipeline = lambda: True

            def falso_iniciar(solicitud):
                vistos["estado_durante"] = app._pipeline_estado["estado"]
                vistos["ejecucion_id"] = solicitud.ejecucion_id
                # Simula lo que haría iniciar_pipeline tras reservar la ejecución.
                app._pipeline_estado["estado"] = "procesando"
                return {"aceptado": True}

            app.iniciar_pipeline = falso_iniciar
            respuesta = app.reanudar_pipeline()
            self.assertTrue(respuesta["desde_checkpoint"])
            self.assertEqual("reanudando", vistos["estado_durante"])
            self.assertEqual("exec-estable", vistos["ejecucion_id"])
        finally:
            app.iniciar_pipeline = original_iniciar
            app._persistir_checkpoint_pipeline = original_persistir
            app._pipeline_hilo = original_hilo
            app._pipeline_estado.clear()
            app._pipeline_estado.update(original_estado)

    def test_segundo_click_mientras_reanuda_se_rechaza(self):
        original = app._pipeline_estado.get("estado")
        try:
            app._pipeline_estado["estado"] = "reanudando"
            with self.assertRaises(HTTPException) as ctx:
                app.reanudar_pipeline()
            self.assertEqual(409, ctx.exception.status_code)
        finally:
            app._pipeline_estado["estado"] = original


if __name__ == "__main__":
    unittest.main()
