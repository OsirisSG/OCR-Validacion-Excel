"""V15.7: primer cuadro con bolsa visible, sin confundirlo con el tablero hinchado."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import aprendizaje_video_airbag as ava
import video_airbag as va
from sintetico_airbag import generar_video, overlay_falso


class DetectorAperturaV157Tests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        td = Path(self._td.name)
        # Aísla caché, revisiones y aprendizaje: las pruebas no tocan los datos del usuario.
        self._parches = [
            mock.patch.object(va, "RUTA_CACHE", td / "cache.json"),
            mock.patch.object(va, "RUTA_REVISIONES", td / "revisiones.json"),
            mock.patch.object(ava, "RUTA_APRENDIZAJE", td / "zonas.json"),
            mock.patch.object(ava, "RUTA_DATASET", td / "dataset.json"),
            mock.patch.object(va, "_leer_overlay", overlay_falso(5000.0)),
        ]
        for p in self._parches:
            p.start()
        self.dir = td

    def tearDown(self):
        for p in reversed(self._parches):
            p.stop()
        self._td.cleanup()

    def _analizar(self, nombre, cfg=None, **kwargs):
        ruta = self.dir / nombre
        generar_video(ruta, **kwargs)
        return va.analizar_video(ruta, {"video_airbag": dict(cfg or {})}, usar_cache=False)

    def test_tablero_hinchado_no_adelanta_la_apertura(self):
        r = self._analizar("hinchado.avi", frame_hinchado=6, frame_bolsa=14)
        self.assertEqual(r["estado"], "candidato")
        self.assertEqual(r["frame_evento"], 14)
        self.assertAlmostEqual(r["tiempo_ms"], 2.8, places=1)
        self.assertTrue(r["antes_limpio"])

    def test_discontinuidad_descarta_hinchado_incluso_sin_compensacion(self):
        # El contorno nuevo protege también cuando el flujo se desactiva:
        # el abombamiento suave no debe volver a adelantar el nacimiento.
        r = self._analizar("sin_mc.avi", {"compensar_movimiento": False},
                           frame_hinchado=6, frame_bolsa=14)
        self.assertEqual(r["frame_evento"], 14)

    def test_bolsa_de_pocos_pixeles_en_cuadro_grande(self):
        r = self._analizar("grande.avi", frame_hinchado=4, frame_bolsa=13, ancho=1280, alto=1024)
        self.assertEqual(r["frame_evento"], 13)

    def test_solo_hinchado_no_es_apertura(self):
        r = self._analizar("sin_bolsa.avi", frame_hinchado=5, frame_bolsa=999)
        self.assertEqual(r["estado"], "sin_evento")

    def test_config_antigua_no_crea_suelo_en_cuadro_8(self):
        # config.yaml V15.0 traía frames_baseline_min: 8; con Rec5000 el tope de
        # 1 ms deja como máximo 5 cuadros de referencia.
        r = self._analizar("temprano.avi", {"frames_baseline_min": 8, "frames_baseline_max": 30},
                           frame_hinchado=None, frame_bolsa=7)
        self.assertLessEqual(r["baseline_frames"], 5)
        self.assertEqual(r["frame_evento"], 7)

    def test_evento_pegado_al_baseline_pide_revision(self):
        r = self._analizar("borde.avi", {"frames_baseline_min": 5, "frames_baseline_max": 5},
                           frame_hinchado=None, frame_bolsa=5)
        self.assertTrue(r["inicio_en_borde_baseline"])
        self.assertLessEqual(r["confianza"], 0.6)
        self.assertTrue(r["advertencia_deteccion"])

    def test_mide_maximo_tras_breakout_y_conserva_total(self):
        # R13: por defecto no se corta al confirmar breakout porque ahora el
        # máximo inflado visible es una segunda salida prioritaria.
        r = self._analizar("largo.avi", frame_hinchado=None, frame_bolsa=12, total=80)
        self.assertEqual(r["frame_evento"], 12)
        self.assertEqual(r["total_frames"], 80)
        secuencia = r.get("secuencia_despliegue_r13") or {}
        self.assertEqual(secuencia.get("frame_breakout"), 12)
        self.assertIsNotNone(secuencia.get("frame_max_inflado"))
        self.assertGreaterEqual(secuencia.get("frame_max_inflado"), 12)

    def test_modo_sin_medicion_de_maximo_puede_detenerse_temprano(self):
        r = self._analizar("rapido.avi", {"medir_llenado_visual": False},
                           frame_hinchado=None, frame_bolsa=12, total=80)
        self.assertEqual(r["frame_evento"], 12)
        self.assertLess(r["frames_leidos"], 80)
        self.assertEqual(r["total_frames"], 80)


if __name__ == "__main__":
    unittest.main()
