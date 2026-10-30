"""V15.9 · Fase 1: detector de dos momentos y evidencia explicable.

El detector retrocede desde la aparición corroborada hasta el primer cambio
conectado y guarda las razones del evento (dos momentos, ROI/microzona,
puntuaciones separadas por fuente y reloj). Si la apertura ya está presente en
el primer cuadro se marca ``evento_al_inicio`` sin inventar un nacimiento.
"""
import numpy as np
import pytest

from test_ruptura_real import _analizar, _fotogramas, _ruptura


def test_razones_evento_explica_dos_momentos_y_fuentes(monkeypatch, tmp_path):
    frames = _fotogramas()
    _ruptura(frames, inicio=6)
    r = _analizar(monkeypatch, tmp_path, frames)
    assert r["estado"] == "candidato"
    assert r["frame_evento"] == 6
    raz = r["razones_evento"]
    # Dos momentos: primer indicio y confirmación, con retroceso declarado.
    assert raz["frame_inicio"] == 6
    assert raz["frame_confirmacion"] >= 6
    assert raz["definicion"]
    # Puntuaciones separadas por fuente (fisura / tela / abombamiento / reflejo…).
    scores = raz["scores_fuentes"]
    for fuente in ("fisura", "tela_clara", "abombamiento", "reflejo",
                   "movimiento_camara_px", "iluminacion_global",
                   "ruido_compresion", "bordes_nuevos"):
        assert fuente in scores
    # Descartes y reloj trazables.
    assert {"iluminacion_global", "abombamiento", "reflejo",
            "movimiento_camara_px", "ruido_compresion"} <= set(raz["descartes"])
    assert raz["reloj"]["fps"] == 5000.0
    assert raz["reloj"]["resolucion_nativa_ms"] == pytest.approx(0.2)
    assert raz["calidad"]["evento_al_inicio"] is False
    # ROI/microzona se reportan (aunque sea sin aprendizaje previo).
    assert "roi_deteccion" in raz
    assert "microzona_bbox_norm" in raz
    assert r["estado_evento"] in {"confirmado", "propuesto"}


def test_evento_al_inicio_marca_y_no_inventa_tiempo(monkeypatch, tmp_path):
    frames = _fotogramas()
    _ruptura(frames, inicio=0)   # la apertura ya está desde el primer cuadro
    r = _analizar(monkeypatch, tmp_path, frames)
    assert r["estado"] == "evento_al_inicio"
    assert r["estado_evento"] == "evento_al_inicio"
    assert r["evento_al_inicio"] is True
    # Nunca se afirma el nacimiento exacto ni se inventa un tiempo.
    assert r["tiempo_ms"] is None
    assert r["frame_evento_confiable"] is False
    assert r["confianza"] <= 0.5
    # El primer indicio visible se conserva (frame 0) con su tiempo sospechoso.
    assert r["frame_evento"] == 0
    assert r["tiempo_ms_sospechoso"] == 0.0
    assert r["razones_evento"]["calidad"]["evento_al_inicio"] is True
    assert r["evidencia_baseline"]


def test_flash_global_no_es_apertura(monkeypatch, tmp_path):
    frames = _fotogramas()
    for i in range(8, len(frames)):
        frames[i][:] = 220          # cambio global de iluminación, sin ruptura local
    r = _analizar(monkeypatch, tmp_path, frames)
    assert r["estado"] != "candidato"
    assert r.get("tiempo_ms") is None


def test_hinchado_suave_tampoco_es_apertura(monkeypatch, tmp_path):
    # Compatibilidad con la definición de evento: abombamiento ≠ ruptura.
    import cv2
    frames = _fotogramas()
    yy, xx = np.mgrid[:96, :128]
    bulto = np.exp(-(((xx - 64) / 22) ** 2 + ((yy - 48) / 16) ** 2))
    for i in range(4, len(frames)):
        gris = np.clip(100 + min(90, 8 * (i - 3)) * bulto, 0, 255).astype(np.uint8)
        frames[i] = cv2.cvtColor(gris, cv2.COLOR_GRAY2BGR)
    r = _analizar(monkeypatch, tmp_path, frames)
    assert r["estado"] == "sin_evento"
    assert r.get("tiempo_ms") is None


def test_version_de_algoritmo_y_dos_momentos_en_resultado(monkeypatch, tmp_path):
    frames = _fotogramas()
    _ruptura(frames, inicio=6)
    r = _analizar(monkeypatch, tmp_path, frames)
    assert r["algoritmo_video"].startswith("v15.10.1-r13")
    assert r["requiere_revision"] is True
    assert r["validado_con_videos_reales"] is False
    assert "no abombamiento" in r["definicion_evento"]
