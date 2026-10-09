from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from video_airbag import analizar_video, consenso_videos, descubrir_videos_caso


class VideoAirbagV15Tests(unittest.TestCase):
    def _video(self, ruta: Path, frame_evento: int = 50, fps: float = 1000.0):
        writer = cv2.VideoWriter(str(ruta), cv2.VideoWriter_fourcc(*"MJPG"), fps, (320, 240))
        self.assertTrue(writer.isOpened())
        for i in range(100):
            img = np.zeros((240, 320, 3), dtype=np.uint8) + 40
            if i >= frame_evento:
                cv2.circle(img, (160, 130), 40, (240, 240, 240), -1)
            writer.write(img)
        writer.release()

    def test_descubre_video_y_videos(self):
        with tempfile.TemporaryDirectory() as td:
            caso = Path(td)
            (caso / "VIDEO").mkdir()
            (caso / "VIDEOS").mkdir()
            (caso / "VIDEO" / "a.avi").write_bytes(b"x")
            (caso / "VIDEOS" / "b.mp4").write_bytes(b"x")
            encontrados = descubrir_videos_caso(caso)
            self.assertEqual({x["nombre"] for x in encontrados}, {"a.avi", "b.mp4"})

    def test_detecta_primer_cuadro_blanco_y_conserva_resolucion_real(self):
        with tempfile.TemporaryDirectory() as td:
            ruta = Path(td) / "cam.avi"
            self._video(ruta, 50, 1000.0)
            r = analizar_video(ruta, {"video_airbag": {"leer_timestamp_overlay": False}}, usar_cache=False)
            self.assertEqual(r["estado"], "candidato")
            self.assertEqual(r["frame_evento"], 50)
            self.assertAlmostEqual(r["tiempo_ms"], 50.0, places=1)
            self.assertAlmostEqual(r["resolucion_nativa_ms"], 1.0, places=3)
            self.assertFalse(r["exactitud_0_1ms_sustentada"])

    def test_consenso_tres_de_cuatro(self):
        items = [
            {"nombre": "a.avi", "estado": "candidato", "tiempo_ms": 6.2,
             "tiempo_fps_ms": 6.2, "resolucion_nativa_ms": 0.1, "precision_fuente_ms": 0.1, "fuente_tiempo": "fps_subframe"},
            {"nombre": "b.avi", "estado": "candidato", "tiempo_ms": 6.2,
             "tiempo_fps_ms": 6.2, "resolucion_nativa_ms": 0.1, "precision_fuente_ms": 0.1, "fuente_tiempo": "fps_subframe"},
            {"nombre": "c.avi", "estado": "candidato", "tiempo_ms": 6.2,
             "tiempo_fps_ms": 6.2, "resolucion_nativa_ms": 0.1, "precision_fuente_ms": 0.1, "fuente_tiempo": "fps_subframe"},
            {"nombre": "d.avi", "estado": "candidato", "tiempo_ms": 8.0,
             "tiempo_fps_ms": 8.0, "resolucion_nativa_ms": 0.1, "precision_fuente_ms": 0.1, "fuente_tiempo": "fps_subframe"},
        ]
        c = consenso_videos(items)
        # V15.7: regla de primera aparición respaldada (antes 3 de 4).
        self.assertEqual(c["estado"], "primera_aparicion")
        self.assertEqual(c["soporte"], 3)
        self.assertEqual(c["tiempo_ms"], 6.2)
        self.assertTrue(c["exactitud_0_1ms_sustentada"])

    def test_overlay_calibra_camaras_sin_overlay(self):
        items = [
            {"nombre": "ref.avi", "estado": "candidato", "tiempo_ms": 6.0,
             "tiempo_overlay_ms": 6.0, "tiempo_fps_ms": 506.0,
             "resolucion_nativa_ms": 1.0, "precision_fuente_ms": 0.1, "fuente_tiempo": "timestamp_overlay"},
            {"nombre": "b.avi", "estado": "candidato", "tiempo_ms": 506.0,
             "tiempo_fps_ms": 506.0, "resolucion_nativa_ms": 1.0, "precision_fuente_ms": 1.0, "fuente_tiempo": "fps_subframe"},
            {"nombre": "c.avi", "estado": "candidato", "tiempo_ms": 506.0,
             "tiempo_fps_ms": 506.0, "resolucion_nativa_ms": 1.0, "precision_fuente_ms": 1.0, "fuente_tiempo": "fps_subframe"},
            {"nombre": "d.avi", "estado": "candidato", "tiempo_ms": 508.0,
             "tiempo_fps_ms": 508.0, "resolucion_nativa_ms": 1.0, "precision_fuente_ms": 1.0, "fuente_tiempo": "fps_subframe"},
        ]
        c = consenso_videos(items)
        self.assertEqual(c["estado"], "primera_aparicion")
        self.assertEqual(c["tiempo_ms"], 6.0)
        self.assertAlmostEqual(c["calibracion_overlay_ms"], -500.0, places=1)


if __name__ == "__main__":
    unittest.main()
