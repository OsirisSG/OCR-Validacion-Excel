"""Aislamiento común: ninguna prueba escribe en el caché ni en el aprendizaje
de video reales del proyecto (.cache_ocr / .aprendizaje)."""
import pytest


@pytest.fixture(autouse=True)
def _aislar_datos_video(tmp_path_factory, monkeypatch):
    base = tmp_path_factory.mktemp("datos_video")
    try:
        import video_airbag as va
        monkeypatch.setattr(va, "RUTA_CACHE", base / "video_airbag.json")
        monkeypatch.setattr(va, "RUTA_REVISIONES", base / "revisiones_video.json")
        va._cache_reloj.clear()
    except ImportError:
        pass
    try:
        import aprendizaje_video_airbag as ava
        monkeypatch.setattr(ava, "RUTA_APRENDIZAJE", base / "zonas_video_airbag.json")
        monkeypatch.setattr(ava, "RUTA_REFERENCIAS", base / "video_airbag_referencias")
        monkeypatch.setattr(ava, "RUTA_DATASET", base / "video_airbag_dataset.json")
        monkeypatch.setattr(ava, "RUTA_DATASET_FRAMES", base / "video_airbag_dataset")
    except ImportError:
        pass
    yield
