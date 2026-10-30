from pathlib import Path
import sqlite3
import tempfile

import cv2
import numpy as np

from aprendizaje import GestorAprendizaje, hash_archivo
from utilidades.edicion_zonas import (
    aplicar, guardar, guardar_bloque, interseca_poligono_bbox, tabla,
)


def _imagen(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = np.full((180, 360, 3), 245, dtype=np.uint8)
    cv2.putText(img, "ABC123", (30, 90), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,0), 2, cv2.LINE_AA)
    ok, enc = cv2.imencode('.png', img)
    assert ok
    enc.tofile(str(path))


def test_poligono_preciso_no_absorbe_vecino_por_bbox_envolvente():
    pol = [[10,10],[120,40],[112,62],[5,30]]
    assert interseca_poligono_bbox(pol, [20,18,40,18]) is True
    # Este bloque cae dentro de la bbox envolvente, pero fuera de la franja inclinada.
    assert interseca_poligono_bbox(pol, [90,8,25,12]) is False


def test_union_guarda_poligono_y_lo_reaplica():
    con = sqlite3.connect(':memory:')
    tabla(con)
    ocr = {
        'dimensiones':[200,100],
        'lineas_texto':[
            {'texto':'ABC','bbox':[10,20,50,20]},
            {'texto':'RUIDO','bbox':[80,5,40,12]},
        ],
    }
    ocr['tokens'] = list(ocr['lineas_texto'])
    pol = [[8,18],[65,25],[63,47],[6,39]]
    guardar(con, 'hash', ocr, [6,5,114,42], 'ABC123', poligono=pol)
    salida = aplicar(con, 'hash', ocr)
    textos = [u['texto'] for u in salida['lineas_texto']]
    assert 'ABC123' in textos
    assert 'RUIDO' in textos
    union = next(u for u in salida['lineas_texto'] if u['texto']=='ABC123')
    assert union['poligono_lectura'] == pol


def test_ajuste_division_conserva_poligonos_en_detalle():
    con = sqlite3.connect(':memory:')
    tabla(con)
    ocr = {'dimensiones':[200,100], 'lineas_texto':[{'texto':'ABCD','bbox':[10,20,100,30]}]}
    ocr['tokens'] = list(ocr['lineas_texto'])
    regs = [
        {'bbox':[10,20,48,30], 'poligono':[[10,20],[58,23],[56,50],[8,47]], 'texto':'AB'},
        {'bbox':[60,20,50,30], 'poligono':[[60,23],[110,20],[112,47],[62,50]], 'texto':'CD'},
    ]
    guardar_bloque(con, 'hash', ocr, [10,20,100,30], regs)
    salida = aplicar(con, 'hash', ocr)
    assert [u['texto'] for u in salida['lineas_texto']] == ['AB','CD']
    assert salida['lineas_texto'][0]['poligono_lectura'] == regs[0]['poligono']
    assert salida['lineas_texto'][1]['poligono_lectura'] == regs[1]['poligono']


def test_union_visual_rectifica_cuadrilatero_final():
    with tempfile.TemporaryDirectory() as td:
        base=Path(td)
        ruta=base/'caso'/'foto.png'
        _imagen(ruta)
        gestor=GestorAprendizaje({'aprendizaje':{'activar':True}}, directorio=base/'.aprendizaje')
        pol=[[25,45],[220,62],[216,96],[22,79]]
        r=gestor.registrar_union_visual(ruta,'caso','ABC123',[20,40,205,60],
                                        unidades_originales=[{'texto':'ABC','bbox':[20,40,80,40]},
                                                             {'texto':'123','bbox':[100,45,120,40]}],
                                        poligono=pol)
        assert r['nuevas']==1
        muestra=r['muestras'][0]
        rec=cv2.imdecode(np.fromfile(muestra['ruta_recorte'],dtype=np.uint8),cv2.IMREAD_COLOR)
        assert rec is not None
        assert rec.shape[1] > rec.shape[0] * 4
