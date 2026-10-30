from pathlib import Path
import unittest

from video_airbag import (
    _parsear_fps_grabacion,
    fps_grabacion_desde_item,
    normalizar_item_temporal_video,
    resolver_tiempo_metadata,
    consenso_videos,
)


class VideoV156TiempoEstableTests(unittest.TestCase):
    def test_rec5000_domina_sobre_8fps_archivo(self):
        texto = "EDAG Mex | 0ms | BMG | 19 JUN 25 | Rec5000 fps, Schutter 80us"
        item = {
            "overlay_texto": texto,
            "fps": 8.0,
            "fps_archivo": 8.0,
            "fps_grabacion": 8.0,
            "fps_fuente": "archivo",
            "frame_evento": 8,
            "tiempo_ms": 1000.0,
            "tiempo_overlay_ms": 1.6,
            "overlay_timestamp_inicial_ms": 0.0,
        }
        self.assertEqual(fps_grabacion_desde_item(item), 5000.0)
        self.assertTrue(normalizar_item_temporal_video(item))
        self.assertEqual(item["fps_grabacion"], 5000.0)
        self.assertEqual(item["fps"], 5000.0)
        self.assertAlmostEqual(item["resolucion_nativa_ms"], 0.2, places=6)
        self.assertAlmostEqual(item["tiempo_ms"], 1.6, places=1)

    def test_frame_11_es_2_2ms_a_5000fps(self):
        r = resolver_tiempo_metadata(
            frame_index=11,
            fps=5000,
            timestamp_actual_ms=2.2,
            timestamp_inicial_ms=1.6,  # incluso si el OCR inicial fue malo
            precision_overlay_ms=0.1,
        )
        self.assertAlmostEqual(r["tiempo_ms"], 2.2, places=1)
        self.assertTrue(r["overlay_valido"])
        self.assertEqual(r["anclaje_tiempo"], "cero")

    def test_ocr_tolera_o_por_cero_en_rec(self):
        self.assertEqual(_parsear_fps_grabacion(["Rec5O00 fps"]), [5000.0])
        self.assertEqual(_parsear_fps_grabacion(["Recording 1O000 fps"]), [10000.0])

    def test_consenso_autorrepara_items_antiguos(self):
        items = []
        for nombre, frame, t in (("a.avi", 22, 4.4), ("b.avi", 22, 4.4), ("c.avi", 22, 4.4)):
            items.append({
                "nombre": nombre,
                "estado": "candidato",
                "overlay_texto": "Rec5000 fps, Shutter 80us",
                "fps": 8.0,
                "fps_archivo": 8.0,
                "fps_grabacion": 8.0,
                "fps_fuente": "archivo",
                "frame_evento": frame,
                "tiempo_ms": frame / 8.0 * 1000.0,
                "tiempo_fps_ms": frame / 8.0 * 1000.0,
                "tiempo_overlay_ms": t,
                "overlay_timestamp_inicial_ms": 0.0,
                "resolucion_nativa_ms": 125.0,
                "precision_fuente_ms": 0.1,
            })
        c = consenso_videos(items)
        self.assertEqual(c["estado"], "primera_aparicion")
        self.assertEqual(c["soporte"], 3)
        self.assertAlmostEqual(c["tiempo_ms"], 4.4, places=1)
        self.assertTrue(all(x["fps_grabacion"] == 5000.0 for x in items))

    def test_no_devuelve_negativos(self):
        """R15 (SUPERSEDE documentado del contrato V15.6).

        V15.6 exigía ``tiempo_ms >= 0`` mediante recorte/clamp del valor
        crudo. La doctrina vigente (R10-R13, «no inventar certeza») prohíbe
        fabricar un 0.0 que nadie observó: el resolver CONSERVA el raw
        negativo (auditable en ``tiempo_crudo_ms``) y la normalización lo
        marca NO_POSITIVO sin publicarlo (``tiempo_ms is None`` + motivo
        visible). Nunca aparece un tiempo inventado ni se pierde el raw.
        """
        r = resolver_tiempo_metadata(
            frame_index=0, fps=5000,
            timestamp_actual_ms=-0.2,
            timestamp_inicial_ms=-4.0,
            precision_overlay_ms=0.1,
        )
        # Capa 1 (resolver): el crudo negativo se conserva íntegro, sin clamp.
        self.assertEqual(r["tiempo_ms"], -0.2)
        self.assertEqual(r["tiempo_crudo_ms"], -0.2)
        # Capa 2 (normalización): no se publica ningún tiempo no positivo.
        item = {
            "ruta": "x_FRONTAL.AVI", "nombre": "x_FRONTAL.AVI", "frame_evento": 0,
            "fps": 5000, "fps_grabacion": 5000, "fps_fuente": "overlay_rec",
            "overlay_texto": "Rec5000 fps", "tiempo_overlay_ms": -0.2,
            "overlay_timestamp_inicial_ms": -4.0, "precision_overlay_ms": 0.1,
            "timestamp_actual_ms": -0.2, "timestamp_inicial_ms": -4.0,
        }
        self.assertTrue(normalizar_item_temporal_video(item))
        # No publica ningún tiempo no positivo: la clave publicable se retira.
        self.assertNotIn("tiempo_ms", item)
        self.assertEqual(item["estado_tiempo"], "NO_POSITIVO")
        self.assertEqual(item["tiempo_crudo_ms"], -0.2)
        self.assertIn("estrictamente mayor que cero", item["motivo_rechazo"])

    def test_frontend_tiene_fps_overlay_y_panel_estable(self):
        raiz = Path(__file__).resolve().parents[1]
        app = (raiz / "dashboard" / "frontend" / "app.js").read_text(encoding="utf-8")
        css = (raiz / "dashboard" / "frontend" / "estilos.css").read_text(encoding="utf-8")
        self.assertIn("function fpsGrabacionOverlayVideo", app)
        self.assertIn("metadataVieja", app)
        self.assertIn("video-revisor-controles-estables", app)
        self.assertIn("position:sticky", css)
        self.assertIn("video-mensaje-reservado", css)

    def test_backend_autorrepara_al_abrir_detalle(self):
        raiz = Path(__file__).resolve().parents[1]
        backend = (raiz / "dashboard" / "backend" / "app.py").read_text(encoding="utf-8")
        self.assertIn("_normalizar_tiempos_video_fila(fila)", backend)
        self.assertIn("fps_real_item", backend)
        self.assertIn("_aplicar_consenso_video_a_fila(fila, consenso)", backend)


if __name__ == "__main__":
    unittest.main()
