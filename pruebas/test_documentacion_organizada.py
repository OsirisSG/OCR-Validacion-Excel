"""La documentación no invade la raíz y sus enlaces locales siguen funcionando."""
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


RAIZ = Path(__file__).resolve().parents[1]


def test_raiz_conserva_solo_readme_y_txt_funcionales():
    archivos_md = sorted(p.name for p in RAIZ.glob('*.md'))
    assert archivos_md == ['README.md']
    for p in RAIZ.glob('*.txt'):
        assert p.name == 'VERSION.txt' or p.name.startswith('requirements')
    assert (RAIZ / 'VERSION.txt').is_file()
    assert (RAIZ / 'requirements.txt').is_file()
    assert (RAIZ / 'requirements-complete.txt').is_file()


def test_guias_informes_e_historial_tienen_ubicacion_clara():
    for nombre in [
        'docs/README.md',
        'docs/guias/LEEME_V15_8_GUIA_RUPTURA_MAXIMO.md',
        'docs/guias/LEEME_INSTALACION_V15.txt',
        'docs/informes/RESULTADOS_PRUEBAS_V15_8.md',
        'docs/informes/ACTUALIZACION_CARPETA_V15_8.md',
        'docs/historial/README_CORRECCIONES_VERSIONES.md',
        'docs/historial/parches/INSTRUCCIONES_APLICAR_PARCHE.txt',
    ]:
        assert (RAIZ / nombre).is_file(), nombre


def test_enlaces_markdown_locales_resuelven_despues_de_mover():
    archivos = [RAIZ / 'README.md', *sorted((RAIZ / 'docs').rglob('*.md'))]
    patron = re.compile(r'!?\[[^\]\n]*\]\(([^\s)]+)\)')
    for documento in archivos:
        contenido = documento.read_text(encoding='utf-8')
        for enlace in patron.findall(contenido):
            url = urlsplit(enlace.strip('<>'))
            if url.scheme or url.netloc or not url.path:
                continue
            destino = (documento.parent / unquote(url.path)).resolve()
            assert destino.is_relative_to(RAIZ), (documento, enlace)
            assert destino.exists(), (documento.relative_to(RAIZ), enlace)


def test_instalador_conserva_sus_requirements_y_lanzadores():
    for nombre in [
        'requirements.txt', 'requirements-complete.txt', 'requirements-dev.txt',
        'requirements-formats.txt', 'requirements-quality.txt',
        'requirements-training.txt', 'requirements-production.txt',
        'instalar.py', 'instalar.bat', 'instalar.command',
        'iniciar.py', 'iniciar.bat', 'iniciar.command',
    ]:
        assert (RAIZ / nombre).is_file(), nombre
