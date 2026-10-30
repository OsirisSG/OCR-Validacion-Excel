"""V15.9.1 · A1: reversión real de ROI con historial persistente.

La auditoría encontró que la UI anunciaba «Revertir» sin flujo real. Ahora:
cada ROI guardada conserva la anterior en ``historial_roi``; el endpoint de
reversión restaura una versión previa, reanaliza y nunca destruye la ROI
desplazada (revertir es reversible). La persistencia sobrevive recargas.
"""
import pathlib
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "pruebas"))

import aprendizaje_video_airbag as ava
from sintetico_airbag import generar_video


@pytest.fixture
def video_y_almacen(tmp_path, monkeypatch):
    monkeypatch.setattr(ava, "RUTA_APRENDIZAJE", tmp_path / "zonas.json")
    monkeypatch.setattr(ava, "RUTA_REFERENCIAS", tmp_path / "referencias")
    ruta = tmp_path / "09_DETAIL.AVI"
    generar_video(ruta, total=16, ancho=320, alto=240)
    return ruta


ROI_1 = [0.10, 0.10, 0.50, 0.50]
ROI_2 = [0.20, 0.15, 0.65, 0.60]
ROI_3 = [0.30, 0.20, 0.70, 0.70]


def test_guardar_roi_conserva_la_anterior_en_el_historial(video_y_almacen):
    ruta = video_y_almacen
    p1 = ava.guardar_zona_aprendida(ruta, ROI_1, usuario="qa")
    assert p1["historial_roi"] == []
    p2 = ava.guardar_zona_aprendida(ruta, ROI_2, usuario="qa")
    assert len(p2["historial_roi"]) == 1
    assert p2["historial_roi"][0]["bbox_norm"] == ROI_1
    assert p2["historial_roi"][0]["motivo"] == "reemplazada_por_nueva_roi"
    # El historial persiste en disco (sobrevive recarga del JSON).
    disco = ava.historial_zona_aprendida(ruta)
    assert disco and disco[0]["bbox_norm"] == ROI_1


def test_revertir_restaura_la_roi_previa_y_es_reversible(video_y_almacen):
    ruta = video_y_almacen
    ava.guardar_zona_aprendida(ruta, ROI_1, usuario="qa")
    ava.guardar_zona_aprendida(ruta, ROI_2, usuario="qa")
    perfil = ava.revertir_zona_aprendida(ruta, usuario="qa")
    assert perfil["bbox_norm"] == ROI_1
    assert perfil.get("revertido_en")
    # La ROI desplazada por la reversión entra al historial: reversible.
    historial = ava.historial_zona_aprendida(ruta)
    assert historial[0]["bbox_norm"] == ROI_2
    assert historial[0]["motivo"] == "reemplazada_por_reversion"
    # Revertir de nuevo devuelve la ROI_2.
    perfil2 = ava.revertir_zona_aprendida(ruta, usuario="qa")
    assert perfil2["bbox_norm"] == ROI_2


def test_historial_acotado_y_seleccion_por_indice(video_y_almacen):
    ruta = video_y_almacen
    for roi in (ROI_1, ROI_2, ROI_3):
        ava.guardar_zona_aprendida(ruta, roi, usuario="qa")
    historial = ava.historial_zona_aprendida(ruta)
    assert [h["bbox_norm"] for h in historial] == [ROI_2, ROI_1]
    # índice 1 restaura la más antigua disponible.
    perfil = ava.revertir_zona_aprendida(ruta, usuario="qa", indice=1)
    assert perfil["bbox_norm"] == ROI_1


def test_revertir_sin_historial_devuelve_error_y_no_toca_datos(video_y_almacen):
    ruta = video_y_almacen
    ava.guardar_zona_aprendida(ruta, ROI_1, usuario="qa")
    with pytest.raises(ValueError):
        ava.revertir_zona_aprendida(ruta, usuario="qa")
    with pytest.raises(ValueError):
        ava.revertir_zona_aprendida(ruta, usuario="qa", indice=5)
    data = ava.cargar_aprendizajes()
    assert data["perfiles"][-1]["bbox_norm"] == ROI_1  # intacta


def test_revertir_video_sin_zona_aprendida(video_y_almacen, tmp_path):
    otra = tmp_path / "sin_zona.avi"
    generar_video(otra, total=8, ancho=160, alto=120)
    with pytest.raises(ValueError):
        ava.revertir_zona_aprendida(otra, usuario="qa")
    assert ava.historial_zona_aprendida(otra) == []


def test_zona_manual_bloqueada_expone_historial_al_frontend(video_y_almacen):
    ruta = video_y_almacen
    ava.guardar_zona_aprendida(ruta, ROI_1, usuario="qa")
    ava.guardar_zona_aprendida(ruta, ROI_2, usuario="qa")
    zona = ava.seleccionar_zona_aprendida(ruta, None)
    assert zona["activa"] and zona["bloqueada"]
    assert zona["bbox_norm"] == ROI_2
    assert isinstance(zona["historial_roi"], list) and len(zona["historial_roi"]) == 1
    assert zona["historial_roi"][0]["bbox_norm"] == ROI_1


def test_endpoint_zona_revertir_existe_en_el_backend():
    import dashboard.backend.app as backend
    rutas = {getattr(r, "path", None) for r in backend.app.routes}
    assert "/api/video/zona-revertir" in rutas
