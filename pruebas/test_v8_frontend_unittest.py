from pathlib import Path

RAIZ=Path(__file__).resolve().parents[1]
APP=(RAIZ/'dashboard/frontend/app.js').read_text(encoding='utf-8')
HTML=(RAIZ/'dashboard/frontend/index.html').read_text(encoding='utf-8')
I18N=(RAIZ/'dashboard/frontend/i18n.js').read_text(encoding='utf-8')


def test_identidad_e_idiomas_visibles():
    assert 'OCR Versuchsmatrix' in APP and 'OCR Versuchsmatrix' in HTML
    assert 'ocr_versuchsmatrix_idioma' in I18N
    assert '<option value="es">ES</option>' in APP
    assert '<option value="en">EN</option>' in APP
    assert '<option value="de">DE</option>' in APP


def test_exportacion_independiente_y_editor_v6_preservado():
    assert '/api/resultados/exportar' in APP
    assert 'Los tres idiomas' in APP
    assert 'variantes-orientacion' in APP or 'variantes' in APP
    assert 'Aplicar supervisión' in APP
    assert 'Comparar lecturas de esta zona' not in APP


def test_no_quedan_emojis_decorativos_unicode_en_app():
    assert not any(ord(ch) >= 0x1F000 for ch in APP)
