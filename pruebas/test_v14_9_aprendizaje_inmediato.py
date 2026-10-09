from pathlib import Path
import tempfile

from aprendizaje import GestorAprendizaje


def _img(path: Path, contenido: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((contenido * 40).encode('utf-8'))


def _estrategia():
    return {
        'orientacion_base': 90,
        'ajuste_manual': -7,
        'variante': 'clahe',
        'tipo_esperado': 'codigo',
        'texto_resultado': 'S4054664',
        'confianza': .81,
        'congruencia': 87,
        'origen': 'relectura_manual',
    }


def _gestor(base: Path):
    return GestorAprendizaje({'aprendizaje': {'activar': True, 'estrategias_ocr': {
        'activar': True,
        'minimo_soporte_sugerencia': 1,
        'minimo_soporte_automatico': 4,
        'dominancia_minima': .75,
        'tolerancia_ajuste_grados': 4,
        'aplicar_inmediato_desde_primera_imagen': True,
        'inmediato_exigir_mismo_grupo_ruta': True,
        'inmediato_exigir_bbox_equivalente': True,
    }}}, base / '.aprendizaje')


def test_una_imagen_humana_se_prueba_en_la_siguiente_del_mismo_contexto():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        gestor = _gestor(base)
        a = base / 'proyecto' / '1st' / 'PHOTOS' / '10001' / 'a.jpg'
        b = base / 'proyecto' / '1st' / 'PHOTOS' / '10002' / 'b.jpg'
        _img(a, 'a'); _img(b, 'b')
        bbox, dims = [100, 100, 200, 80], [1000, 800]
        gestor.registrar_estrategia_ocr(a, bbox, dims, _estrategia(), caso_id='10001')
        sug = gestor.sugerir_estrategia_ocr(b, bbox, dims, {})
        assert sug is not None
        assert sug['soporte'] == 1
        assert sug['nivel'] == 'inmediata'
        assert sug['aplicacion_inmediata'] is True
        assert sug['auto_aplicable'] is True
        assert sug['orientacion_base'] == 90
        assert sug['variante'] == 'clahe'


def test_una_imagen_no_se_impone_fuera_de_la_misma_geometria():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        gestor = _gestor(base)
        a = base / 'proyecto' / '1st' / 'PHOTOS' / '10001' / 'a.jpg'
        b = base / 'proyecto' / '1st' / 'PHOTOS' / '10002' / 'b.jpg'
        _img(a, 'a'); _img(b, 'b')
        gestor.registrar_estrategia_ocr(a, [100, 100, 200, 80], [1000, 800], _estrategia())
        sug = gestor.sugerir_estrategia_ocr(b, [650, 500, 200, 80], [1000, 800], {})
        assert sug is None or not sug.get('auto_aplicable', False)


def test_autoentrenamiento_se_programa_sin_boton(monkeypatch):
    import time
    import dashboard.backend.app as backend
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        cfg = {
            'aprendizaje': {
                'activar': True,
                'directorio': str(base / '.aprendizaje'),
                'visual': {
                    'auto_entrenar': True,
                    'minimo_muestras': 1,
                    'minimo_ids': 1,
                    'auto_debounce_segundos': .2,
                }
            }
        }
        gestor = GestorAprendizaje(cfg)
        with gestor._conectar() as con:
            con.execute("""INSERT INTO muestras_visuales
                (id,caso_id,imagen_hash,ruta_imagen,ruta_recorte,bbox_json,texto_ocr,
                 texto_correcto,accion,entrenable,usuario,confirmada,firma,creado_en)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ('m1','caso1','h1','x','x','[0,0,10,10]','A','B','confirmar_entrenar',1,
                 'test',1,'firma1','2026-09-25T10:00:00'))
        monkeypatch.setattr(backend, 'CONFIG', cfg)
        monkeypatch.setattr(backend, '_pipeline_activo_para_entrenamiento', lambda: False)
        llamadas = []
        monkeypatch.setattr(backend, '_lanzar_entrenamiento_visual',
                            lambda modo='manual', objetivo_rowid=None: llamadas.append((modo, objetivo_rowid)) or True)
        backend._entrenamiento_estado.update({'ultimo_rowid_entrenado': 0, 'pendiente_auto': False})
        resultado = backend._programar_entrenamiento_visual_auto('prueba')
        assert resultado['programado'] is True
        time.sleep(.3)
        assert llamadas and llamadas[-1][0] == 'auto'
        if backend._entrenamiento_auto_timer is not None:
            backend._entrenamiento_auto_timer.cancel()
