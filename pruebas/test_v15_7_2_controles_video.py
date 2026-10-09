"""V15.7.2: controles del panel para recalcular y ocultar/desplegar videos."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "dashboard" / "frontend" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "dashboard" / "frontend" / "index.html").read_text(encoding="utf-8")


def test_panel_video_expone_boton_recalcular_por_id():
    assert '↻ Recalcular' in APP_JS
    assert re.search(r'enviarJSON\("/api/video/reanalizar",\s*\{\s*prueba_id:\s*detalle\.id,\s*video_id:\s*null\s*\}\)', APP_JS)
    assert re.search(r'enviarJSON\("/api/video/reanalizar",\s*\{\s*prueba_id:\s*pruebaId,\s*video_id:\s*video\.id\s*\}\)', APP_JS)
    assert 'pedirJSON("/api/video/reanalisis/estado")' in APP_JS


def test_panel_video_puede_ocultar_y_desplegar():
    assert 'boton-vista-videos' in APP_JS
    assert 'Ocultar videos' in APP_JS
    assert 'Mostrar videos' in APP_JS
    assert 'setVideosVisibles(v => !v)' in APP_JS
    assert 'aria-expanded=${videosVisibles}' in APP_JS
    assert 'videosVisibles ? html`<div class="lista-videos-airbag">' in APP_JS


def test_frontend_usa_la_misma_version_en_scripts_y_css():
    versiones = []
    for recurso in ("app.js", "i18n.js", "estilos.css"):
        etiqueta = re.search(r'(?:src|href)="' + re.escape(recurso) + r'\?v=([^"&]+)"', INDEX)
        assert etiqueta, f"Falta versión de caché en {recurso}"
        versiones.append(etiqueta.group(1))
    assert len(set(versiones)) == 1
