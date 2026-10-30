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


@pytest.fixture(autouse=True)
def _aislar_centinela_recuperacion(tmp_path_factory, monkeypatch):
    """R15.7 (ALTO-03): el centinela de recuperación se replica en una segunda
    ubicación (directorio de estado del usuario). Ninguna prueba debe escribir
    en el HOME real: la suite lo redirige a un tmp por prueba."""
    base = tmp_path_factory.mktemp("centinela")
    try:
        import dashboard.backend.app as backend
    except ImportError:
        yield
        return
    monkeypatch.setattr(backend, "RUTA_RECUPERACION_ESPEJO",
                        base / "recuperacion_requerida.json", raising=False)
    # R15.8: el guard de recuperación es TRANSVERSAL (dependencia FastAPI de
    # todos los endpoints mutantes); ningún estado de recuperación de una
    # prueba puede filtrarse a la siguiente.
    backend._inconsistencias_activas.clear()
    backend._modo_recuperacion = None
    yield
