"""V15.7: tiempo único, FPS real, ROI manual bloqueada y revisor estable."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

import aprendizaje_video_airbag as ava
from video_airbag import (_parsear_fps_grabacion, consenso_valido, consenso_videos,
                          fps_temporal_confiable, normalizar_videos_caso,
                          resolver_tiempo_metadata)

RAIZ = Path(__file__).resolve().parents[1]


def _video(nombre: str, frame: int, *, rec: bool = True, revision: dict | None = None) -> dict:
    """Resultado guardado por una versión antigua: 8 fps de reproducción."""
    item = {
        "nombre": nombre, "estado": "candidato", "frame_evento": frame,
        "fps": 8.0, "fps_archivo": 8.0, "fps_fuente": "archivo",
        "tiempo_ms": frame / 8.0 * 1000.0, "tiempo_fps_ms": frame / 8.0 * 1000.0,
        "overlay_texto": "Rec5000 fps, Shutter 80us" if rec else "EDAG Testlab",
    }
    if revision:
        item["revision_manual"] = revision
    return item


class FpsRealTests(unittest.TestCase):
    def test_fps_del_avi_nunca_se_usa_como_grabacion(self):
        self.assertEqual(fps_temporal_confiable(None, 8.0, {}), (None, "desconocido"))
        self.assertEqual(fps_temporal_confiable(5000.0, 8.0, {}), (5000.0, "overlay_rec"))
        self.assertEqual(fps_temporal_confiable(None, 1000.0, {}), (1000.0, "archivo"))
        forzado = {"video_airbag": {"fps_grabacion_forzado": 5000}}
        self.assertEqual(fps_temporal_confiable(None, 8.0, forzado), (5000.0, "config_forzado"))

    def test_rec_con_dos_puntos(self):
        self.assertEqual(_parsear_fps_grabacion(["Rec:5000fps"]), [5000.0])

    def test_camara_sin_rec_hereda_la_tasa_del_ensayo(self):
        sin_rec = _video("50_FRONTAL.AVI", 11, rec=False)
        con_rec = _video("50_DETAIL.AVI", 10)
        normalizar_videos_caso([sin_rec, con_rec], {})
        self.assertEqual(sin_rec["fps"], 5000.0)
        self.assertEqual(sin_rec["fps_fuente"], "overlay_rec_otra_camara")
        self.assertAlmostEqual(sin_rec["tiempo_ms"], 2.2, places=3)
        self.assertAlmostEqual(sin_rec["resolucion_nativa_ms"], 0.2, places=6)

    def test_sin_rec_en_ningun_video_no_inventa_1375_ms(self):
        item = _video("x_FRONTAL.AVI", 11, rec=False)
        item["tiempo_overlay_ms"] = 2.2
        normalizar_videos_caso([item], {})
        self.assertEqual(item["fps_fuente"], "desconocido")
        self.assertEqual(item["tiempo_ms"], 2.2)
        item2 = _video("y_FRONTAL.AVI", 11, rec=False)
        normalizar_videos_caso([item2], {})
        self.assertIsNone(item2["tiempo_ms"])


class TiempoUnicoTests(unittest.TestCase):
    def test_reloj_descartado_no_se_reporta_como_overlay(self):
        r = resolver_tiempo_metadata(frame_index=11, fps=5000.0, timestamp_actual_ms=20.0, config={})
        self.assertFalse(r["overlay_valido"])
        self.assertIsNone(r["tiempo_overlay_ms"])
        self.assertEqual(r["tiempo_overlay_leido_ms"], 20.0)
        self.assertAlmostEqual(r["tiempo_ms"], 2.2, places=3)

    def test_revision_negativa_guardada_se_repara(self):
        """R15 (SUPERSEDE documentado del contrato V15.7).

        V15.7 «reparaba» una revisión humana negativa reescribiéndola a 2.0
        ms (``tiempo_reparado``). Desde V15.10 los datos humanos NUNCA se
        reescriben (plan R15: cero pérdida de datos manuales; «no inventar
        certeza»): el valor histórico se conserva intacto, se marca
        NO_POSITIVO con motivo visible y no se publica.
        """
        item = _video("081_LATERAL.AVI", 11, revision={
            "estado": "confirmado", "frame_index": 10, "tiempo_ms": -122.8})
        normalizar_videos_caso([item], {})
        rev = item["revision_manual"]
        self.assertEqual(rev["tiempo_ms"], -122.8)
        self.assertEqual(rev["raw_time_ms"], -122.8)
        self.assertEqual(rev["estado_tiempo"], "NO_POSITIVO")
        self.assertIn("no es positivo", rev["motivo_rechazo"])
        self.assertNotIn("tiempo_reparado", rev)

    def test_revision_con_8_fps_se_repara(self):
        """R15 (SUPERSEDE documentado del contrato V15.7).

        V15.7 recalculaba a 2.2 ms una revisión humana sospechosa de haber
        sido guardada con fps de archivo (8 fps => 1375.0). La doctrina
        vigente no reescribe datos humanos: conserva 1375.0 como raw, lo
        marca REFERENCIA_INVALIDA y lo deja para revisión manual explícita.
        """
        item = _video("x_LATERAL.AVI", 11, revision={
            "estado": "confirmado", "frame_index": 11, "tiempo_ms": 1375.0})
        normalizar_videos_caso([item], {})
        rev = item["revision_manual"]
        self.assertEqual(rev["tiempo_ms"], 1375.0)
        self.assertEqual(rev["raw_time_ms"], 1375.0)
        self.assertEqual(rev["estado_tiempo"], "REFERENCIA_INVALIDA")
        self.assertIn("revisión manual", rev["motivo_rechazo"])

    def test_confirmacion_coherente_no_se_reescribe(self):
        """R15 (SUPERSEDE documentado): la confirmación coherente sigue sin
        reescribirse; la comparación es de SUBCONJUNTE porque V15.10 enriquece
        la revisión con claves de auditoría temporal (``raw_time_ms``,
        ``estado_tiempo``, ``motivo_rechazo``) sin alterar los datos humanos.
        """
        item = _video("x_LATERAL.AVI", 14, revision={
            "estado": "confirmado", "frame_index": 11, "tiempo_ms": 2.2})
        normalizar_videos_caso([item], {})
        rev = item["revision_manual"]
        esperado = {"estado": "confirmado", "frame_index": 11, "tiempo_ms": 2.2}
        self.assertEqual({k: rev[k] for k in esperado}, esperado)
        self.assertEqual(rev["estado_tiempo"], "VALIDO")
        self.assertEqual(rev["raw_time_ms"], 2.2)


class ConsensoPrimeraAparicionTests(unittest.TestCase):
    def test_scheibe_no_define_el_tiempo(self):
        items = [_video("09_DETAIL.AVI", 12), _video("09_FRONTAL.AVI", 12),
                 _video("09_LATERAL.AVI", 13), _video("09_SCHEIBE.AVI", 2)]
        c = consenso_videos(items, {})
        self.assertEqual(c["estado"], "primera_aparicion")
        self.assertEqual(c["tiempo_ms"], 2.4)
        self.assertIn("SCHEIBE", c["camaras_excluidas"])
        # V15.9.1: tres cámaras principales coinciden dentro de tolerancia →
        # confirmado limpio y publicable; SCHEIBE jamás define el tiempo.
        self.assertEqual(c["estado_consenso"], "confirmado")
        self.assertEqual(c["soporte"], 3)
        self.assertNotEqual(c["camara_referencia"], "SCHEIBE")
        self.assertFalse(c["requiere_revision"])
        self.assertTrue(consenso_valido(c))

    def test_deteccion_aislada_mas_temprana_pide_revision(self):
        items = [_video("04_DETAIL.AVI", 8), _video("04_FRONTAL.AVI", 10),
                 _video("04_LATERAL.AVI", 10), _video("04_SCHEIBE.AVI", 23)]
        c = consenso_videos(items, {})
        self.assertEqual(c["tiempo_ms"], 2.0)
        self.assertEqual(c["camara_anterior_sin_respaldo"]["camara"], "DETAIL")
        self.assertTrue(c["requiere_revision"])

    def test_confirmacion_manual_manda(self):
        items = [_video("1_DETAIL.AVI", 8), _video("1_FRONTAL.AVI", 8),
                 _video("1_LATERAL.AVI", 11, revision={
                     "estado": "confirmado", "frame_index": 10, "tiempo_ms": 2.0})]
        c = consenso_videos(items, {})
        self.assertEqual(c["estado"], "confirmado_manual")
        self.assertEqual(c["tiempo_ms"], 2.0)

    def test_nunca_negativo(self):
        """R15 (SUPERSEDE documentado del contrato V15.7).

        V15.7 exigía ``tiempo_ms >= 0`` (en la práctica, clamp a 0.0). La
        doctrina vigente (plan R15, caso sintético B: «sin breakout ⇒ NO
        DETECTADO, nunca 0 ms») prohíbe inventar un tiempo: dos vídeos en
        frame 0 sin evidencia suficiente producen ``sin_datos`` con
        ``tiempo_ms is None`` y revisión requerida; jamás un 0 fabricado.
        """
        items = [_video("n_DETAIL.AVI", 0), _video("n_FRONTAL.AVI", 0)]
        c = consenso_videos(items, {})
        self.assertIsNone(c["tiempo_ms"])
        self.assertEqual(c["estado"], "sin_datos")
        self.assertEqual(c["estado_consenso"], "sin_evento")
        self.assertTrue(c["requiere_revision"])


def _escribir_avi(ruta: Path, desplazamiento: int = 0) -> None:
    rng = np.random.default_rng(7)
    base = (rng.random((240, 320)) * 255).astype(np.uint8)
    base = cv2.GaussianBlur(base, (3, 3), 0)
    for i in range(0, 320, 40):
        cv2.rectangle(base, (i, 60), (i + 18, 90), 255, -1)
    base = np.roll(base, desplazamiento, axis=1)
    escritor = cv2.VideoWriter(str(ruta), cv2.VideoWriter_fourcc(*"MJPG"), 8.0, (320, 240))
    for _ in range(4):
        escritor.write(cv2.cvtColor(base, cv2.COLOR_GRAY2BGR))
    escritor.release()


class RoiBloqueadaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        raiz = Path(self.tmp.name)
        self.parches = [
            mock.patch.object(ava, "RAIZ_PROYECTO", raiz),
            mock.patch.object(ava, "RUTA_APRENDIZAJE", raiz / "zonas.json"),
            mock.patch.object(ava, "RUTA_REFERENCIAS", raiz / "refs"),
        ]
        for p in self.parches:
            p.start()
        self.raiz = raiz

    def tearDown(self):
        for p in self.parches:
            p.stop()
        self.tmp.cleanup()

    def test_roi_dibujada_se_usa_exacta_en_su_video(self):
        video = self.raiz / "30_LATERAL.AVI"
        _escribir_avi(video)
        bbox = [0.241346, 0.452981, 0.385577, 0.527047]
        ava.guardar_zona_aprendida(video, bbox, tipo_camara="LATERAL")
        frame = ava._leer_frame(video, 0)
        zona = ava.seleccionar_zona_aprendida(video, frame, {})
        self.assertTrue(zona["bloqueada"])
        self.assertEqual(zona["fuente"], "manual_bloqueada")
        self.assertEqual(zona["bbox_norm"], bbox)
        self.assertEqual(zona["porcentajes"], {"x": 24.1, "y": 45.3, "w": 14.4, "h": 7.4})

    def test_roi_heredada_no_se_mueve_sin_permiso(self):
        origen = self.raiz / "30_LATERAL.AVI"
        otro = self.raiz / "31_LATERAL.AVI"
        _escribir_avi(origen)
        _escribir_avi(otro, desplazamiento=24)
        bbox = [0.2, 0.2, 0.5, 0.5]
        ava.guardar_zona_aprendida(origen, bbox, tipo_camara="LATERAL")
        frame = ava._leer_frame(otro, 0)
        zona = ava.seleccionar_zona_aprendida(otro, frame, {})
        self.assertTrue(zona["activa"])
        self.assertTrue(zona["bloqueada"])
        self.assertEqual(zona["bbox_norm"], bbox)
        self.assertFalse(zona["transformada_por_similitud"])
        if zona.get("bbox_sugerida_norm"):
            auto = ava.seleccionar_zona_aprendida(
                otro, frame, {"video_airbag": {"autoalineacion_roi": True}})
            self.assertEqual(auto["bbox_norm"], zona["bbox_sugerida_norm"])
            self.assertEqual(auto["bbox_original_norm"], bbox)


class RevisorEstableTests(unittest.TestCase):
    def test_frontend_sin_saltos(self):
        app = (RAIZ / "dashboard" / "frontend" / "app.js").read_text(encoding="utf-8")
        css = (RAIZ / "dashboard" / "frontend" / "estilos.css").read_text(encoding="utf-8")
        self.assertIn("}, [video.id]);", app)  # guardar no reinicia el cuadro
        self.assertIn("anclarTarjeta()", app)
        self.assertIn("rutaFrameMostrada", app)  # doble búfer de imagen
        self.assertIn("aspectRatio: proporcion", app)
        self.assertIn("REGIÓN MANUAL BLOQUEADA", app)
        self.assertIn("Aceptar ROI sugerida", app)
        self.assertIn(".video-aviso-tiempo-reservado{min-height", css)
        self.assertIn(".video-roi-estado{", css)


if __name__ == "__main__":
    unittest.main()
