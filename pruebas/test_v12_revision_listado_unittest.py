"""Regresión V12: el Listado debe mostrar la revisión persistida vigente."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

APP_PATH = ROOT / "dashboard" / "backend" / "app.py"
spec = importlib.util.spec_from_file_location("dashboard_app_v12", APP_PATH)
app = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(app)


class RevisionListadoV12Tests(unittest.TestCase):
    def test_revision_persistida_prevalece_sobre_parcial_obsoleto(self):
        parcial = {
            "id": "proyecto|1st|232541",
            "origen": "carpeta",
            "revision": {"estado": "parcial", "oculto": False, "actualizado_en": "10:00"},
        }
        persistidas = {
            ("carpeta", "proyecto|1st|232541"): {
                "tipo": "carpeta",
                "item_id": "proyecto|1st|232541",
                "estado": "completada",
                "oculto": False,
                "actualizado_en": "10:05",
            }
        }
        salida = app._revision_vigente_en_fila_publica(parcial, persistidas)
        self.assertEqual("completada", salida["revision"]["estado"])
        # No muta la instantánea original.
        self.assertEqual("parcial", parcial["revision"]["estado"])

    def test_cache_parcial_se_actualiza_al_completar(self):
        original = app._pipeline_estado.get("resultados_parciales")
        try:
            app._pipeline_estado["resultados_parciales"] = [{
                "id": "proyecto|1st|232541",
                "origen": "carpeta",
                "revision": {"estado": "parcial", "oculto": False},
            }]
            vigente = {
                "tipo": "carpeta", "item_id": "proyecto|1st|232541",
                "estado": "completada", "oculto": False,
                "actualizado_en": "2026-09-22T09:00:00",
            }
            app._actualizar_revision_parcial_en_memoria(
                "carpeta", "proyecto|1st|232541", vigente)
            self.assertEqual(
                "completada",
                app._pipeline_estado["resultados_parciales"][0]["revision"]["estado"],
            )
        finally:
            app._pipeline_estado["resultados_parciales"] = original or []


if __name__ == "__main__":
    unittest.main()
