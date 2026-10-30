"""Regresiones sintéticas de ruptura; no validan exactitud con cámaras reales.

Se alimentan fotogramas sin compresión para comprobar el caso de exactamente
un píxel. Los vídeos MJPG existentes cubren por separado la ruta del códec.
"""
from pathlib import Path

import cv2
import numpy as np
import pytest

import aprendizaje_video_airbag as ava
import video_airbag as va
from sintetico_airbag import overlay_falso


def _analizar(monkeypatch, tmp_path, frames, config=None):
    class Captura:
        def __init__(self, ruta):
            self.pos = 0

        def isOpened(self):
            return True

        def get(self, clave):
            return {cv2.CAP_PROP_FPS: 8.0, cv2.CAP_PROP_FRAME_COUNT: len(frames),
                    cv2.CAP_PROP_FRAME_WIDTH: frames[0].shape[1],
                    cv2.CAP_PROP_FRAME_HEIGHT: frames[0].shape[0]}.get(clave, 0)

        def set(self, clave, valor):
            if clave == cv2.CAP_PROP_POS_FRAMES:
                self.pos = int(valor)
            return True

        def read(self):
            if self.pos >= len(frames):
                return False, None
            frame = frames[self.pos]
            self.pos += 1
            return True, frame

        def release(self):
            pass

    ruta = tmp_path / "captura.avi"
    ruta.write_bytes(b"identidad-local-para-prueba-sin-codec")
    monkeypatch.setattr(va.cv2, "VideoCapture", Captura)
    monkeypatch.setattr(va, "RUTA_CACHE", tmp_path / "cache.json")
    monkeypatch.setattr(va, "RUTA_REVISIONES", tmp_path / "revisiones.json")
    monkeypatch.setattr(ava, "RUTA_APRENDIZAJE", tmp_path / "zonas.json")
    monkeypatch.setattr(ava, "RUTA_DATASET", tmp_path / "dataset.json")
    monkeypatch.setattr(va, "_leer_overlay", overlay_falso(5000.0))
    return va.analizar_video(ruta, {"video_airbag": dict(config or {})}, usar_cache=False)


def _fotogramas(total=20, ancho=128, alto=96):
    return [np.full((alto, ancho, 3), 100, dtype=np.uint8) for _ in range(total)]


def _ruptura(frames, inicio=6, *, oscuro=False, x=None, y=None):
    alto, ancho = frames[0].shape[:2]
    x, y = x or ancho // 2, y or alto // 2
    for i in range(inicio, len(frames)):
        radio = min(10, i - inicio)
        if oscuro:
            # Una fisura oscura que se alarga antes de que aparezca la tela.
            frames[i][y, x - radio:x + radio + 1] = 20
        else:
            frames[i][y - radio:y + radio + 1, x - radio:x + radio + 1] = 180
    return frames


def test_conserva_primer_pixel_claro_nativo_y_no_lo_retrasa(monkeypatch, tmp_path):
    frames = _ruptura(_fotogramas(ancho=1280, alto=160))
    resultado = _analizar(monkeypatch, tmp_path, frames)
    assert resultado["frame_evento"] == 6
    assert resultado["frame_confirmacion_automatica"] > 6
    assert resultado["analisis_resolucion_nativa"] is True
    assert resultado["componente_blanco_px"] == 1
    # El AVI declara 8 fps de reproducción; la adquisición es Rec5000.
    assert resultado["tiempo_ms"] == pytest.approx(1.2)
    assert resultado["fps_archivo"] == 8.0
    assert resultado["resolucion_nativa_ms"] == pytest.approx(0.2)


def test_fisura_oscura_precede_a_tela_clara(monkeypatch, tmp_path):
    frames = _ruptura(_fotogramas(), oscuro=True)
    for i in range(10, len(frames)):
        radio = i - 8
        frames[i][48 - radio:49 + radio, 64 - radio:65 + radio] = 180
    resultado = _analizar(monkeypatch, tmp_path, frames)
    assert resultado["estado"] == "candidato"
    assert resultado["frame_evento"] == 6
    assert resultado["pixeles_grieta_nueva"] == 1


def test_hinchado_suave_y_brillo_creciente_no_son_ruptura(monkeypatch, tmp_path):
    frames = _fotogramas()
    yy, xx = np.mgrid[:96, :128]
    bulto = np.exp(-(((xx - 64) / 22) ** 2 + ((yy - 48) / 16) ** 2))
    for i in range(4, len(frames)):
        gris = np.clip(100 + min(90, 8 * (i - 3)) * bulto, 0, 255).astype(np.uint8)
        frames[i] = cv2.cvtColor(gris, cv2.COLOR_GRAY2BGR)
    resultado = _analizar(monkeypatch, tmp_path, frames)
    assert resultado["estado"] == "sin_evento"
    assert resultado.get("tiempo_ms") is None


@pytest.mark.parametrize("persistente", [False, True])
def test_un_pixel_de_ruido_sin_crecimiento_no_confirma(monkeypatch, tmp_path, persistente):
    frames = _fotogramas()
    for i in range(6, len(frames) if persistente else 7):
        frames[i][48, 64] = 180
    resultado = _analizar(monkeypatch, tmp_path, frames)
    assert resultado["estado"] == "sin_evento"


def test_ruido_puntual_cercano_no_adelanta_fisura_real(monkeypatch, tmp_path):
    frames = _ruptura(_fotogramas(ancho=640, alto=160), x=320, y=80)
    # Antes caía dentro del margen del 8 % y podía incorporarse al retroceso.
    frames[5][80, 300] = 180
    resultado = _analizar(monkeypatch, tmp_path, frames)
    assert resultado["frame_evento"] == 6


def test_indicio_separado_por_cuadro_limpio_no_se_fusiona(monkeypatch, tmp_path):
    frames = _ruptura(_fotogramas(), inicio=7)
    frames[5][48, 64] = 180
    resultado = _analizar(monkeypatch, tmp_path, frames)
    assert resultado["frame_evento"] == 7


def test_primer_pixel_persistente_mas_de_siete_frames_se_conserva(monkeypatch, tmp_path):
    frames = _fotogramas(total=32)
    for i in range(6, 19):
        frames[i][48, 64] = 180
    _ruptura(frames, inicio=18)
    resultado = _analizar(monkeypatch, tmp_path, frames)
    assert resultado["frame_evento"] == 6
    assert resultado["retroceso_frames"] > 7
    assert resultado["indicio_un_pixel"] is True


def test_pixel_10_crece_30_sin_arrastrar_pixel_caliente_anterior(monkeypatch, tmp_path):
    frames = _fotogramas(total=44)
    for i in range(5, len(frames)):
        frames[i][25, 20] = 180  # ruido fijo y lejano, presente antes de la fisura
    for i in range(10, 31):
        frames[i][48, 64] = 180
    _ruptura(frames, inicio=30)
    resultado = _analizar(monkeypatch, tmp_path, frames)
    assert resultado["frame_evento"] == 10
    assert resultado["frame_confirmacion_automatica"] > 30
    assert resultado["indicio_un_pixel"] is True
    assert resultado["antes_limpio"] is True


def test_indicio_en_ultimo_cuadro_no_se_inventa_como_confirmado(monkeypatch, tmp_path):
    frames = _ruptura(_fotogramas(total=12), inicio=11)
    resultado = _analizar(monkeypatch, tmp_path, frames)
    assert resultado["estado"] == "sin_evento"
    assert resultado.get("frame_evento") is None
    assert resultado.get("tiempo_ms") is None
    assert resultado["requiere_revision"] is True
    assert resultado["validado_con_videos_reales"] is False


def test_cambios_generales_y_persistencia_no_son_fallback_por_defecto():
    cfg = va._cfg({"video_airbag": {}})
    assert cfg["rescate_cambio_general"] is False
    assert cfg["permitir_persistencia_sin_crecimiento"] is False


def _camaras_candidatas():
    return [{"nombre": nombre, "estado": "candidato", "frame_evento": 10,
             "tiempo_ms": 2.0, "tiempo_fps_ms": 2.0, "fps": 5000.0,
             "fps_grabacion": 5000.0, "fps_archivo": 8.0,
             "overlay_texto": "Rec5000fps", "resolucion_nativa_ms": 0.2,
             "requiere_revision": True}
            for nombre in ("01_DETAIL.AVI", "01_FRONTAL.AVI")]


def test_dos_camaras_automaticas_no_borran_revision_pendiente():
    consenso = va.consenso_videos(_camaras_candidatas(), {"video_airbag": {}})
    assert consenso["estado"] == "primera_aparicion"
    assert consenso["requiere_revision"] is True
    # V15.9.1 (B1): una propuesta sin respaldo suficiente ya no se publica
    # «con bandera de revisión»: directamente no genera evidencia hasta que
    # haya confirmación (3 cámaras o revisión humana). La señal pendiente se
    # conserva en el consenso y en el tooltip del dashboard.
    assert consenso["estado_consenso"] == "propuesto"
    assert va.consenso_valido(consenso) is False
    assert va.evidencia_apertura_desde_consenso({"case_key": "c"}, consenso) is None
    assert consenso["tiempo_ms"] == 2.0  # la medida sigue visible como propuesta


def test_confirmacion_humana_prevalece_sobre_flags_automaticos():
    items = _camaras_candidatas()
    items[0]["revision_manual"] = {"estado": "confirmado", "frame_index": 10,
                                    "tiempo_ms": 2.0, "referencia_tiempo_valida": True,
                                    "estado_tiempo": "VALIDO"}
    consenso = va.consenso_videos(items, {"video_airbag": {}})
    assert consenso["estado"] == "confirmado_manual"
    assert consenso["requiere_revision"] is False
    evidencia = va.evidencia_apertura_desde_consenso({"case_key": "c"}, consenso)
    assert evidencia["requiere_confirmacion_manual"] is False
    assert evidencia["confirmacion_manual"] is True
