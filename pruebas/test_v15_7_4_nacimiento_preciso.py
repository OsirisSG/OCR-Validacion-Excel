"""V15.7.4: microzona exacta del nacimiento separada de la ROI general."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "dashboard" / "frontend" / "app.js").read_text(encoding="utf-8")
APP_PY = (ROOT / "dashboard" / "backend" / "app.py").read_text(encoding="utf-8")
LEARN = (ROOT / "aprendizaje_video_airbag.py").read_text(encoding="utf-8")
CSS = (ROOT / "dashboard" / "frontend" / "estilos.css").read_text(encoding="utf-8")
INDEX = (ROOT / "dashboard" / "frontend" / "index.html").read_text(encoding="utf-8")


def test_hay_endpoint_de_afinacion_sin_guardar():
    assert '/api/video/refinar-zona-apertura' in APP_PY
    assert 'localizar_nacimiento_evento' in APP_PY
    assert 'guardado": False' in APP_PY


def test_roi_general_y_microzona_se_guardan_separadas():
    assert 'bbox_evento_norm' in APP_PY
    assert 'bbox_evento_norm' in LEARN
    assert 'features_nacimiento' in LEARN
    assert 'recorte = _recortar_norm(frame, bbox_evento or bbox)' in LEARN


def test_zoom_permita_autoafinacion_y_ajuste_manual():
    assert 'Zoom exacto del nacimiento' in APP_JS
    assert 'Afinar automáticamente' in APP_JS
    assert 'Ajustar nacimiento a mano' in APP_JS
    assert 'video-zona-nacimiento-zoom' in APP_JS
    assert 'video-zona-nacimiento-overlay' in CSS


def test_confirmacion_envia_microzona_y_backend_autocompleta_si_falta():
    assert 'bbox_evento_norm: estado === "confirmado"' in APP_JS
    assert 'bbox_evento_norm: Array.isArray(nacimientoExacto)' in APP_JS
    assert 'localizacion_nacimiento = localizar_nacimiento_evento' in APP_PY


def test_frontend_usa_version_sincronizada_para_scripts_y_css():
    versiones = []
    for recurso in ("app.js", "i18n.js", "estilos.css"):
        etiqueta = re.search(r'(?:src|href)="' + re.escape(recurso) + r'\?v=([^"&]+)"', INDEX)
        assert etiqueta, f"Falta versión de caché en {recurso}"
        versiones.append(etiqueta.group(1))
    assert len(set(versiones)) == 1
