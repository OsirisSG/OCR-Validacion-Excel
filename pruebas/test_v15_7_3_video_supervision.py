"""V15.7.3: supervisión de ROI, zoom y recálculo individual de video."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "dashboard" / "frontend" / "app.js").read_text(encoding="utf-8")
APP_PY = (ROOT / "dashboard" / "backend" / "app.py").read_text(encoding="utf-8")
CSS = (ROOT / "dashboard" / "frontend" / "estilos.css").read_text(encoding="utf-8")
INDEX = (ROOT / "dashboard" / "frontend" / "index.html").read_text(encoding="utf-8")


def test_recalculo_individual_envia_video_id():
    assert 'video_id: video.id' in APP_JS
    assert 'video_id: str | None' in APP_PY
    assert 'videos_objetivo' in APP_PY


def test_roi_tiene_zoom_y_supervision_combinada():
    assert 'Zoom exacto del nacimiento' in APP_JS
    assert 'Esta zona + este cuadro = apertura' in APP_JS
    assert 'guardarZonaYApertura' in APP_JS
    assert 'video-zona-zoom-imagen' in CSS


def test_vista_video_es_toggle_directo_sin_details():
    assert 'boton-vista-videos' in APP_JS
    assert 'Ocultar videos' in APP_JS
    assert 'Mostrar videos' in APP_JS
    assert 'menu-videos-desplegable' not in APP_JS


def test_frontend_rompe_cache_para_version_actual():
    versiones = []
    for recurso in ("app.js", "i18n.js", "estilos.css"):
        etiqueta = re.search(r'(?:src|href)="' + re.escape(recurso) + r'\?v=([^"&]+)"', INDEX)
        assert etiqueta, f"Falta versión de caché en {recurso}"
        versiones.append(etiqueta.group(1))
    assert len(set(versiones)) == 1
