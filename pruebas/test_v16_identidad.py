"""Identidad y compatibilidad V16 de mantenimiento."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
BUILD = "16.0.2"

def test_v16_version_unica():
    assert (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip() == BUILD
    backend = (ROOT / "dashboard/backend/app.py").read_text(encoding="utf-8")
    assert 'PATCH_BUILD = "16.0.2"' in backend
    assert 'version=PATCH_BUILD' in backend
    html = (ROOT / "dashboard/frontend/index.html").read_text(encoding="utf-8")
    versions = re.findall(r'(?:estilos\.css|app\.js|i18n\.js|visor_precision\.js|red_segura\.js)[?]v=([0-9a-z.\-]+)', html)
    assert len(versions) >= 5 and set(versions) == {BUILD}

def test_v16_no_cambios_algoritmicos_activados_por_version():
    text = (ROOT / "validacion_campo/soak_r157.py").read_text(encoding="utf-8")
    assert 'PATCH_BUILD_R159 = "16.0.2"' in text
    assert 'PATCH_BUILD_R158 = PATCH_BUILD_R159' in text
    assert 'PATCH_BUILD_R157 = PATCH_BUILD_R159' in text

def test_v16_readme_y_instalacion():
    t = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "**Versión V16.0.2" in t
    assert "INSTALAR_V16_0_2_SEMAFORO.bat" in t
