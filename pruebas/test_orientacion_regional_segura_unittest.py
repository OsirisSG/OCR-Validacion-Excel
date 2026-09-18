import unittest
from pathlib import Path


class FlujoOrientacionNoBloqueanteV6Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raiz = Path(__file__).resolve().parents[1]
        cls.backend = (raiz / "dashboard/backend/app.py").read_text(encoding="utf-8")
        cls.frontend = (raiz / "dashboard/frontend/app.js").read_text(encoding="utf-8")

    def test_backend_no_bloquea_correccion_por_orientacion_dudosa(self):
        self.assertNotIn("_orientacion_regional_pendiente", self.backend)
        self.assertNotIn("Confirma primero la orientación regional y reprocesa la imagen", self.backend)

    def test_frontend_no_muestra_barrera_confusa(self):
        self.assertNotIn("Corrección textual bloqueada temporalmente", self.frontend)
        self.assertNotIn("Guardar orientación regional", self.frontend)

    def test_variantes_se_preparan_sin_boton_comparar(self):
        self.assertNotIn("Comparar lecturas de esta zona", self.frontend)
        self.assertIn('/api/aprendizaje/lecturas-orientacion', self.frontend)
        self.assertIn("variantes-siempre-visibles", self.frontend)
        self.assertIn("onTexto(propuesta.texto)", self.frontend)


if __name__ == "__main__":
    unittest.main()
