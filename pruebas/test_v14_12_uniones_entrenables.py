from pathlib import Path
import tempfile

import cv2
import numpy as np

from aprendizaje import GestorAprendizaje, hash_archivo
from utilidades.edicion_zonas import guardar


def _imagen(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = np.full((160, 500, 3), 245, dtype=np.uint8)
    cv2.putText(img, "232568", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (0, 0, 0), 2, cv2.LINE_AA)
    cv2.putText(img, "16/MAY/2026", (20, 130), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2, cv2.LINE_AA)
    ok, enc = cv2.imencode('.jpg', img)
    assert ok
    enc.tofile(str(path))


def _gestor(base: Path):
    return GestorAprendizaje({'aprendizaje': {'activar': True, 'directorio': str(base / '.aprendizaje')}},
                             base / '.aprendizaje')


def test_union_una_linea_entra_como_recorte_visual_entrenable():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        ruta = base / 'caso1' / 'foto.jpg'
        _imagen(ruta)
        gestor = _gestor(base)
        unidades = [
            {'texto': '232', 'bbox': [10, 20, 80, 60]},
            {'texto': '568', 'bbox': [90, 20, 100, 60]},
        ]
        r = gestor.registrar_union_visual(ruta, 'caso1', '232568', [10, 20, 180, 60], unidades)
        assert r['nuevas'] == 1
        assert r['muestras'][0]['entrenable'] is True
        filas = gestor.listar_muestras_visuales([ruta])
        entrenables = [f for f in filas if f.get('entrenable')]
        assert len(entrenables) == 1
        assert entrenables[0]['texto_correcto'] == '232568'
        assert entrenables[0]['campo'] == 'union_manual'


def test_union_multilinea_separa_muestras_si_coincide_con_bloques():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        ruta = base / 'caso2' / 'foto.jpg'
        _imagen(ruta)
        gestor = _gestor(base)
        unidades = [
            {'texto': '232S68', 'bbox': [10, 20, 190, 60]},
            {'texto': '16/MAV/2026', 'bbox': [10, 85, 280, 60]},
        ]
        r = gestor.registrar_union_visual(
            ruta, 'caso2', '232568\n16/MAY/2026', [10, 20, 280, 125], unidades)
        assert r['nuevas'] == 2
        filas = [f for f in gestor.listar_muestras_visuales([ruta]) if f.get('entrenable')]
        assert {f['texto_correcto'] for f in filas} == {'232568', '16/MAY/2026'}
        assert {f['campo'] for f in filas} == {'union_manual_linea'}


def test_union_historica_se_migra_al_verificar_sin_duplicarse():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        ruta = base / 'caso3' / 'foto.jpg'
        _imagen(ruta)
        gestor = _gestor(base)
        ocr = {
            'dimensiones': [500, 160],
            'lineas_texto': [
                {'texto': '232', 'bbox': [10, 20, 80, 60]},
                {'texto': '568', 'bbox': [90, 20, 100, 60]},
            ],
        }
        ocr['tokens'] = list(ocr['lineas_texto'])
        with gestor._conectar() as con:
            guardar(con, hash_archivo(ruta), ocr, [10, 20, 180, 60], '232568')
        primero = gestor.incorporar_uniones_guardadas(ruta, 'caso3', ocr)
        segundo = gestor.incorporar_uniones_guardadas(ruta, 'caso3', ocr)
        assert primero['uniones_detectadas'] == 1
        assert primero['nuevas'] == 1
        assert segundo['nuevas'] == 0
        assert segundo['duplicadas'] == 1
        filas = [f for f in gestor.listar_muestras_visuales([ruta]) if f.get('entrenable')]
        assert len(filas) == 1
        assert filas[0]['texto_correcto'] == '232568'
