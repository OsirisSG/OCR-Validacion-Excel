"""La documentación no invade la raíz y sus enlaces locales siguen funcionando."""
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


RAIZ = Path(__file__).resolve().parents[1]


def test_raiz_conserva_solo_readme_y_txt_funcionales():
    # V15.9.2 (C6): AGENTS.md debe vivir en la raíz para que Codex lo descubra.
    archivos_md = sorted(p.name for p in RAIZ.glob('*.md'))
    # P42: conservar el paquete diagnóstico solicitado, incluidos sus documentos
    # originales. Lista cerrada: la documentación nueva sigue viviendo en docs/.
    originales_md = {
        'ESTADO_ACTUALIZACION_P42_r3.md', 'INSTRUCCIONES_HOTFIX_ARRANQUE.md',
        'PLAN_Y_CORRECCION_V15_10_1_R3.md', 'PLAN_Y_CORRECCION_V15_10_1_R6.md',
        'README_CORRECCIONES_VERSIONES.md', 'README_CORRECCION_ACUMULADA_V15_10_1.md',
        'README_R11.md', 'README_R12.md', 'README_R8.md',
    }
    originales_txt = {
        'INSTRUCCIONES_APLICAR_PARCHE.txt', 'INSTRUCCIONES_DIAGNOSTICO.txt',
        'LEEME_DIAGNOSTICO_SEMAFORO_V16.txt', 'LEEME_DIAGNOSTICO_V2.txt',
        'MANIFEST_SHA256_ACUMULADO.txt', 'MANIFEST_SHA256_HOTFIX_ARRANQUE.txt',
        'MANIFEST_SHA256_R8.txt', 'MANIFEST_SHA256_V15_10_1_H5_CENSURA.txt',
    }
    assert set(archivos_md) == {'AGENTS.md', 'README.md'} | originales_md
    for p in RAIZ.glob('*.txt'):
        assert p.name == 'VERSION.txt' or p.name.startswith('requirements') or p.name in originales_txt
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
