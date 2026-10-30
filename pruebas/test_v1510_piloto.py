"""Regresiones V15.10.1: inyectar en raíz y ejecutar pytest pruebas/test_v1510_piloto.py."""
from __future__ import annotations
import json
import sqlite3
import sys
from pathlib import Path
import pytest

from utilidades.fuente_canonica_v1510 import resolver_campo,resolver_caso
from utilidades.sincronizacion_v1510 import tiempo_fisico,alinear_camara
from utilidades.politica_apertura_v1510 import evaluar_camaras
from utilidades.verificador_apertura_v1510 import verificar_candidatos
from utilidades.evidencia_apertura_v1510 import inspeccionar_frames
from utilidades.auditoria_aprendizaje_v1510 import auditar,sha256_archivo
from utilidades.diagnostico_matriz_v1510 import diagnosticar


def evidencia(campo='serial',valor='123',fuente='imagen_ocr',**extra):
    return {'project_id':'PRJ-2','case_key':'1ST_01','campo':campo,
            'candidato':valor,'fuente':fuente,'archivo_sha256':'a'*64,**extra}


def test_manual_ultima_prevalece_y_no_mezcla_proyectos():
    registro=[evidencia(valor='000',fuente='manual',confirmado_por_humano=True,
                        corregido_en='2026-10-10T10:00:00-06:00'),
              evidencia(valor='999',fuente='manual',confirmado_por_humano=True,
                        corregido_en='2026-10-12T12:00:00-06:00'),
              evidencia(valor='111',fuente='imagen_ocr'),
              {'project_id':'OTRO','case_key':'1ST_01','campo':'serial',
               'candidato':'XYZ','fuente':'manual','confirmado_por_humano':True}]
    r=resolver_campo(registro,project_id='PRJ-2',case_key='1ST_01',campo='serial')
    assert r['estado']=='verificado_humano'
    assert r['valor']=='999'
    assert any(x['motivo']=='identidad_incompatible' for x in r['rechazadas'])


def test_manual_con_fecha_ambigua_no_pierde_historia():
    e=[evidencia(valor='ABC',fuente='manual',confirmado_por_humano=True),
       evidencia(valor='XYZ',fuente='manual',confirmado_por_humano=True)]
    r=resolver_campo(e,project_id='PRJ-2',case_key='1ST_01',campo='serial')
    assert r['estado']=='conflicto' and r['valor'] is None


def test_ocr_no_se_autopublica_ni_autocorrige_con_ambiguedad():
    e=[evidencia(valor='0B123'),evidencia(valor='OB123',archivo_sha256='b'*64)]
    r=resolver_campo(e,project_id='PRJ-2',case_key='1ST_01',campo='serial',auto_publicacion=True)
    assert r['estado']=='conflicto' and r['valor'] is None
    r=resolver_campo([e[0]],project_id='PRJ-2',case_key='1ST_01',campo='serial',auto_publicacion=True)
    assert r['estado']=='propuesta' and 'auto_publicacion_bloqueada_sin_calibracion' in r['motivos']


def test_tiempo_1000_5000_fps_no_inventa_precision():
    x=tiempo_fisico(frame=9,fps_adquisicion=1000)
    y=tiempo_fisico(frame=9,fps_adquisicion=5000)
    assert x['resolucion_ms']==pytest.approx(1)
    assert y['resolucion_ms']==pytest.approx(.2)
    assert y['tiempo_ms']==pytest.approx(1.8)
    assert y['incertidumbre_ms']>=.1
    assert tiempo_fisico(frame=2,fps_adquisicion=0)['valido'] is False


def camara(cid,t=2.0,**kw):
    x={'camara_id':cid,'video_sha256':cid*64,'misma_fase_evento':True,
       'visibilidad':'visible','fps_adquisicion':5000,'tiempo_local_ms':t,
       'calibracion_temporal':{'validada':True,'origen':'disparador','offset_ms':0,
                                'factor':1,'incertidumbre_ms':0.05,'referencia_id':'TRIGGER-1'},'alertas':[]}
    x.update(kw)
    return x


def test_tres_sincronizadas_crean_propuesta_no_publicacion():
    r=evaluar_camaras([camara('A',2),camara('B',2.1),camara('C',2.1),camara('D',3)])
    assert r['soporte']>=3 and r['auto_confirmable']
    assert not r['publicable'] and r['tiempo_ms'] is None
    assert r['tiempo_propuesto_ms']==pytest.approx(2)


def test_menos_de_tres_duplicados_y_desfase_desconocido_bloqueados():
    assert not evaluar_camaras([camara('A'),camara('B')])['auto_confirmable']
    duplicada=camara('B',video_sha256=camara('A')['video_sha256'])
    r=evaluar_camaras([camara('A'),duplicada,camara('C')])
    assert not r['auto_confirmable']
    c=camara('C',calibracion_temporal={'validada':False,'origen':'disparador','offset_ms':0,'factor':1})
    assert not evaluar_camaras([camara('A'),camara('B'),c])['auto_confirmable']


def test_flash_y_candidato_sin_futuro_no_se_certifican():
    arr=[{'novedad_local':0,'persistencia_local':0} for _ in range(7)]
    arr[3]={'novedad_local':2,'persistencia_local':2,'flash_global':True}
    arr[4]['persistencia_local']=3;arr[5]['persistencia_local']=4
    r=verificar_candidatos(arr,[3,6])
    assert r['inicio_sugerido_frame'] is None
    assert not r['auto_publicable']


def test_primera_fisura_un_pixel_pero_no_aceptacion_automatica():
    import numpy as np
    frames=[]
    for k in range(8):
        f=np.zeros((32,40,3),dtype=np.uint8)
        if k>=4:f[10,10]=255
        if k>=5:f[10:12,10:12]=255
        frames.append(f)
    r=inspeccionar_frames(frames,roi=(2,2,20,20),fps_adquisicion=5000,
                         umbral_pixeles=20,minimo_pixeles=1)
    assert r['onset_frame_candidato']==4
    assert not r['publicable']
    assert r['tiempo_fisico_candidato']['tiempo_ms']==pytest.approx(.8)


def test_roi_manual_invalida_no_se_mueve_en_silencio():
    import numpy as np
    with pytest.raises(ValueError,match='ROI'):
        inspeccionar_frames([np.zeros((20,20,3),dtype=np.uint8)],roi=(17,17,10,10))


def test_sqlite_lectura_sin_mutacion(tmp_path):
    carpeta=tmp_path/'.aprendizaje';carpeta.mkdir()
    db=carpeta/'aprendizaje.sqlite3'
    con=sqlite3.connect(db)
    con.execute('CREATE TABLE observaciones (id integer primary key,txt text)')
    con.execute("INSERT INTO observaciones (txt) VALUES ('ejemplo')")
    con.commit();con.close()
    antes=sha256_archivo(db)
    res=auditar(carpeta)
    assert sha256_archivo(db)==antes
    assert res['sqlite'][0]['integridad']=='ok'
    assert {'tabla':'observaciones','registros':1} in res['sqlite'][0]['tablas']


def test_gris_no_finge_motivo_ni_ceros():
    filas=[{'id':1,'semaforo_apertura':'gris','apertura_motivo':'sin_consenso','opening_time_ms':None},
           {'id':2,'semaforo_apertura':'verde','opening_time_ms':5.8}]
    x=diagnosticar(filas)
    assert x['motivos_gris']=={'sin_consenso':1}
    assert x['total_casos_entrada']==2


def test_matriz_dinamica_en_la_base_v15910_si_disponible():
    try:
        from utilidades.matriz_apertura import construir_columnas,criterio_desde_limites
    except ImportError:
        pytest.skip('Esta prueba requiere instalar V15.9.10')
    fn=construir_columnas
    import inspect
    if 'dinamico_sin_vacantes' not in inspect.getsource(fn):
        pytest.skip('Aún no aplicado el parche de matriz al proyecto')
    def fila(i):
        return {'id':i,'test_number':str(i),'tipo_st':'1ST',
                'temperature_condition':'HT','inflator_type':'UGL',
                'campos':{'opening_time_ms':{'valor':5.5}}}
    for cantidad in (0,1,10,50,80,125):
        cols=fn([fila(i) for i in range(cantidad)],criterio_desde_limites(6,7))
        assert sum(len(c['celdas']) for c in cols)==cantidad
        assert all(e['tipo']=='caso' for c in cols for e in c['celdas'])


def test_referencias_distintas_no_generan_consenso():
    c=camara('C')
    c['calibracion_temporal']['referencia_id']='TRIGGER-OTRO'
    r=evaluar_camaras([camara('A'),camara('B'),c])
    assert r['estado']=='revisar_conflicto'
    assert r['tiempo_ms'] is None


def test_separacion_ciega_bloquea_fuga_entre_camaras():
    from utilidades.evaluacion_apertura_v1510 import evaluar
    a=[{'case_key':'A','split':'train','etiqueta_evento':True,
        'predice_evento':True,'referencia_frame':5,'prediccion_frame':5,'camara':'A'},
       {'case_key':'A','split':'test_sellado','etiqueta_evento':True,
        'predice_evento':True,'referencia_frame':5,'prediccion_frame':6,'camara':'B'}]
    r=evaluar(a)
    assert not r['valido'] and r['bloqueo']=='fuga_de_casos_entre_splits'


def test_evaluacion_no_cuenta_las_camaras_como_casos():
    from utilidades.evaluacion_apertura_v1510 import evaluar
    a=[{'case_key':'A','split':'test_sellado','etiqueta_evento':True,
        'predice_evento':True,'referencia_frame':7,'prediccion_frame':8,'camara':chr(i)}
       for i in range(65,69)]
    r=evaluar(a)
    assert r['valido']
    assert r['splits']['test_sellado']['casos']==1
    assert r['splits']['test_sellado']['coincidencia_mas_menos_1_frame']==1


def test_modificador_matriz_no_encubre_diferencias():
    from APLICAR_PARCHE_V15_10 import modificar_matriz
    with pytest.raises(RuntimeError):
        modificar_matriz('def construir_columnas(filas_etapa: list[dict], criterio: dict) -> list[dict]:\n    pass\n\ndef causa_sin_clasificar(x):pass')


def test_convertir_intervalo_invalidado_por_sincronizacion():
    assert alinear_camara(2,{'origen':'overlay_verificado','validada':False,
                             'offset_ms':0,'factor':1})['valido'] is False
    assert alinear_camara(2,{'origen':'disparador','validada':True,
                             'offset_ms':0,'factor':1,'incertidumbre_ms':-1})['valido'] is False


def test_variantes_ocr_no_alteran_valor_ni_validan_identidad():
    from utilidades.hipotesis_ocr_v1510 import proponer_lecturas
    o=proponer_lecturas('O123',expresion_campo=r'\d{4}')
    assert o['lectura_original']=='O123'
    assert any(x['texto']=='0123' and x['formato_compatible'] for x in o['hipotesis'])
    assert not o['auto_confirmada']


def test_benchmark_portable_windows_sin_resource():
    from APLICAR_PARCHE_V15_10 import modificar_benchmark
    s='import resource\n\ndef _uso_recursos():\n    uso = resource.getrusage(resource.RUSAGE_SELF)\n'
    new=modificar_benchmark(s)
    assert 'except ImportError' in new
    assert 'ram_max_mb": None' in new
    assert 'import os' in new


def test_instalar_y_rollback_transaccional_en_repo_simulado(tmp_path,monkeypatch):
    import APLICAR_PARCHE_V15_10 as i
    r=tmp_path/'OCR';r.mkdir()
    base=r/'dashboard/backend/app.py';base.parent.mkdir(parents=True)
    f=r/'dashboard/frontend/app.js';f.parent.mkdir(parents=True)
    m=r/'utilidades/matriz_apertura.py';m.parent.mkdir(parents=True)
    (r/'video_airbag.py').write_text('# detector original\n',encoding='utf-8')
    base.write_text('"sin tiempo confiable, pendiente/conflicto o posición sin caso"',encoding='utf-8')
    f.write_text('''1ST y 2ST en un solo resumen. Todas las posiciones esperadas se muestran:
          gris tenue = vacante (sin caso asignado). Haz clic en una prueba para localizar su carpeta en el Listado.
        <span><i style=${{ background: paleta.vacante }}></i>Vacante (posición sin caso)</span>
<small class="matriz-columna-cupos">${col.ocupados ?? "?"}/${col.esperados} esperados</small>
''',encoding='utf-8')
    m.write_text('''def construir_columnas(filas_etapa: list[dict], criterio: dict) -> list[dict]:
    por_columna, _ = agrupar_casos(filas_etapa)
    cupos = max(int(spec["esperados"]), len(grupo))
    celdas = [celda_vacante(i + 1) for i in range(cupos-len(grupo))]
    return columnas


def causa_sin_clasificar(x):
    pass

"sin tiempo confiable, pendiente/conflicto o sin caso",
''',encoding='utf-8')
    original={str(p.relative_to(r)):p.read_bytes() for p in (base,f,m)}
    monkeypatch.setattr(i,'REF_SHAS',{p:i.gitsha((r/p).read_bytes()) for p in original})
    stage, origen=i.recolectar(r,None)
    backup=i.instalar(r,stage,origen)
    assert 'dinamico_sin_vacantes' in m.read_text(encoding='utf-8')
    assert 'casos reales' in f.read_text(encoding='utf-8')
    i.revertir(r,backup)
    for p,data in original.items():assert (r/p).read_bytes()==data
    assert not (r/'utilidades/fuente_canonica_v1510.py').exists()
