"""Protocolo auditado V16.0.20: una fuente física por acontecimiento.

Apertura: FRONTAL + LATERAL, primera tela visible, no mero tablero roto.
FORVIA: DETAIL, primer movimiento localizado del tablero.
Inflado: FRONTAL + LATERAL, meseta/máximo visible y sus limitaciones.

No certifica el volumen físico a partir de área proyectada 2D.
"""
from __future__ import annotations
import math
import re
from pathlib import Path
from typing import Iterable

VERSION = 'tres-eventos-16.0.20'
VISTAS_BOLSA = frozenset({'FRONTAL','LATERAL'})
VISTAS_PERMITIDAS = frozenset({'FRONTAL','LATERAL','DETAIL','SCHEIBE'})


def numero(x):
    if x is None or isinstance(x,bool):return None
    try:
        value=float(x)
        return value if math.isfinite(value) else None
    except (TypeError,ValueError,OverflowError):return None


def camara(item):
    """La cámara viene del AVI, nunca de una ROI reutilizada."""
    name=Path(str(item.get('nombre') or item.get('ruta') or '')).stem.upper()
    match=re.search(r'(?:^|[_\\-])(FRONTAL|LATERAL|DETAIL|SCHEIBE)(?:$|[_\\-])',name)
    by_name=match.group(1) if match else None
    declared=str(item.get('tipo_camara') or '').upper()
    if by_name:return by_name
    return declared if declared in VISTAS_PERMITIDAS else None


def tiempo_cuadro(frame,item):
    n=numero(frame)
    fps=numero(item.get('fps_grabacion'))
    if n is None or n<0 or fps is None or fps<=0:return None
    return round(1000*n/fps,6)


def tiempo_valido(item):
    if item.get('referencia_tiempo_valida') is not True:return False
    if str(item.get('estado_tiempo') or 'VALIDO').upper() in {
        'PENDIENTE','CONFLICTO','REFERENCIA_INVALIDA','NO_FINITO','NO_POSITIVO','NO_INTERPRETABLE'}:return False
    if item.get('advertencia_fps'):return False
    if str(item.get('fps_fuente') or '')=='config_forzado' and item.get('overlay_validado') is not True:return False
    return True


def _revision_humana(item):
    rev=item.get('revision_manual') or {}
    return isinstance(rev,dict) and rev.get('estado')=='confirmado' and (
        rev.get('referencia_tiempo_valida') is True or tiempo_valido(item))


def _tela_visible(item):
    """La grieta/abombamiento por sí solos NO son aparición de bolsa."""
    a=item.get('congruencia_v1606') or {}
    if not isinstance(a,dict):a={}
    p=numero(item.get('pixeles_blanco_nuevo')) or 0
    # La detección de tela nueva se apoya en evidencia temporal/espacial.
    # `evidencia_fisica` o `pixeles_ruptura` solos pueden indicar TABLERO,
    # no tela de la bolsa. No permitirlos como prueba de apertura.
    contexto=bool(a.get('material_presente_en_onset') is True)
    est=item.get('evaluacion_apertura_estandar') or {}
    verificacion=bool(isinstance(est,dict) and est.get('auto_colorable') is True and
                      item.get('frame_evento_confiable') is True)
    confirmacion=_revision_humana(item)
    return bool(confirmacion or contexto or (p>=3 and verificacion))


def apertura_camara(item):
    frame=numero(item.get('frame_evento'))
    t=numero(item.get('tiempo_ms'))
    if t is None and frame is not None:t=tiempo_cuadro(frame,item)
    if t is not None and (t<=0 or (frame is not None and frame<0)):t=None
    n=numero(item.get('resolucion_nativa_ms'))
    if n is None or n<=0:
        fps=numero(item.get('fps_grabacion'))
        n=round(1000/fps,6) if fps and fps>0 else None
    return {'camara':camara(item),'archivo':item.get('nombre'),'firma':item.get('firma'),
            'frame':int(frame) if frame is not None and frame>=0 else None,
            'tiempo_ms':t,'resolucion_ms':n,'tela_visible':_tela_visible(item),
            'tiempo_valido':tiempo_valido(item),'confirmacion_humana':_revision_humana(item),
            'criterio':'primera_bolsa_visible_no_primera_rotura'}


def maximo_camara(item):
    g=item.get('maximo_global_v16') or {}
    if not isinstance(g,dict):g={}
    r=item.get('secuencia_despliegue_r13') or {}
    if not isinstance(r,dict):r={}
    seq=g.get('secuencia') or {}
    if not isinstance(seq,dict):seq={}
    # IMPORTANT: 0 is an actual index and must not be lost with `or`.
    frame=next((v for v in (g.get('frame_max_inflado'),g.get('frame_max'),seq.get('frame_max_inflado'),
                             r.get('frame_max_inflado'),item.get('frame_max_inflado_estimado'))
                if v is not None),None)
    f=numero(frame)
    t=tiempo_cuadro(f,item) if f is not None else None
    if t is None:t=numero(g.get('tiempo_max_inflado_ms')) or numero(r.get('tiempo_max_inflado_ms'))
    estado=str(g.get('estado') or r.get('estado') or '')
    errores=list(g.get('anomalías') or []) + list(r.get('anomalías') or [])
    censurado=bool(g.get('censurado') or g.get('publicacion_bloqueada_por_calidad') or
                   g.get('requiere_validacion_visual') or 'censur' in estado.lower() or
                   any('censur' in str(x).lower() for x in errores))
    inicio=numero(item.get('frame_evento'))
    crecimiento=bool(f is not None and inicio is not None and f>inicio)
    return {'camara':camara(item),'archivo':item.get('nombre'),'firma':item.get('firma'),
            'frame':int(f) if f is not None else None,'tiempo_ms':t,'tiempo_valido':tiempo_valido(item),
            'censurado':censurado,'crecimiento_posterior':crecimiento,'estado_detector':estado,
            'origen':'maximo_visible_2d', 'limitacion':'no_equivale_a_maximo_volumen_fisico'}


def forvia_detail(item):
    mov=item.get('movimiento_tablero_v1619') or {}
    if not isinstance(mov,dict):mov={}
    frame=mov.get('frame')
    t=tiempo_cuadro(frame,item)
    if t is None:t=numero(mov.get('tiempo_ms'))
    coherente=bool(mov.get('continuidad') is True and mov.get('estado')=='movimiento_local_corrobora')
    valid=bool(tiempo_valido(item) and coherente and t is not None)
    return {'camara':'DETAIL','archivo':item.get('nombre'),'firma':item.get('firma'),
            'frame':frame,'tiempo_ms':t,'movimiento_confirmado':coherente,
            'tiempo_valido':tiempo_valido(item),'estado':'medicion_visual_estimada' if valid else 'pendiente',
            'criterio':'primer_movimiento_local_tablero_no_bolsa','propuesta_ms':t,
            'publicable':valid}


def tres_eventos(items:Iterable[dict],consenso_apertura:dict|None=None):
    src=[x for x in items if isinstance(x,dict)]
    by={}
    for x in src:
        c=camara(x)
        if c in VISTAS_PERMITIDAS:by.setdefault(c,[]).append(x)
    def unica(nombre):return by.get(nombre,[None])[0] if len(by.get(nombre,[]))==1 else None
    raw_f=unica('FRONTAL');raw_l=unica('LATERAL')
    f=apertura_camara(raw_f) if raw_f else None
    l=apertura_camara(raw_l) if raw_l else None
    distintas=bool(f and l and f['firma'] and l['firma'] and f['firma']!=l['firma'])
    rf=f.get('resolucion_ms') if f else None;rl=l.get('resolucion_ms') if l else None
    tolerancia=round(max(0.1,2*max(rf,rl)),6) if rf and rl else None
    tf=f.get('tiempo_ms') if f else None;tl=l.get('tiempo_ms') if l else None
    diferencia=round(abs(tf-tl),6) if tf is not None and tl is not None else None
    compat=bool(distintas and tolerancia is not None and diferencia is not None and
                diferencia<=tolerancia+1e-9 and all(x['tela_visible'] and x['tiempo_valido']
                for x in (f,l)))
    # Fallback a pruebas más detalladas del consenso v1618 solo cuando las dos
    # vistas originales también son válidas y el desfase cabe en la tolerancia.
    cc=consenso_apertura or {}
    if not compat and distintas and tolerancia is not None and diferencia is not None and diferencia<=tolerancia:
        compat=bool(cc.get('validacion_fisica_dos_camaras') is True and
                    cc.get('camaras_distintas_en_soporte',0)>=2 and cc.get('estado_consenso')=='confirmado'
                    and cc.get('requiere_revision') is False and all(x['tiempo_valido'] for x in (f,l))
                    and all(x['tela_visible'] for x in (f,l)))
    proposals=[x['tiempo_ms'] for x in (f,l) if x and x['tiempo_ms'] is not None and
               x['tela_visible'] and x['tiempo_valido']]
    apertura={'estado':'corroborado_dos_vistas' if compat else (
              'estimado_pendiente' if proposals else 'sin_bolsa_visible_defendible'),
              'tiempo_ms':round(min(tf,tl),6) if compat else None,
              'propuesta_ms':min(proposals,default=None),
              'frontal':f,'lateral':l,'diferencia_ms':diferencia,'tolerancia_ms':tolerancia,
              'camaras_independientes':distintas,'definicion':'primera_bolsa_visible',
              'origen_temporal':'desde_inicio_del_clip'}
    detail=unica('DETAIL')
    forvia=forvia_detail(detail) if detail else {
       'estado':'sin_detail_unico','tiempo_ms':None,'frame':None,'publicable':False,'propuesta_ms':None}
    if (forvia.get('tiempo_ms') is not None and apertura['tiempo_ms'] is not None and
        forvia['tiempo_ms']>apertura['tiempo_ms']+1e-9):
        forvia['estado']='revision_movimiento_posterior_a_apertura'
        forvia['publicable']=False
    mf=maximo_camara(raw_f) if raw_f else None
    ml=maximo_camara(raw_l) if raw_l else None
    vf=mf.get('tiempo_ms') if mf else None;vl=ml.get('tiempo_ms') if ml else None
    dm=round(abs(vf-vl),6) if vf is not None and vl is not None else None
    tm=round(max(0.2,3*max(rf,rl)),6) if rf and rl else None
    max_dos=bool(distintas and mf and ml and dm is not None and tm is not None and dm<=tm+1e-9
                 and all(x['tiempo_valido'] and x['crecimiento_posterior'] and not x['censurado']
                         for x in (mf,ml)))
    # La meseta 2D corroborada es un indicador visual, NO certifica inflado físico.
    llenado={'estado':'maximo_visible_corrobora_no_fisico' if max_dos else 'maximo_visual_pendiente',
             'tiempo_ms':None,'propuesta_ms':round(max(vf,vl),6) if max_dos else None,
             'frontal':mf,'lateral':ml,'diferencia_ms':dm,'tolerancia_ms':tm,
             'significado':'maximo_visible_2d_no_equivale_inflado_fisico_completo',
             'origen_temporal':'desde_inicio_del_clip'}
    if apertura['tiempo_ms'] is not None and llenado['propuesta_ms'] is not None:
        llenado['duracion_desde_apertura_ms']=round(llenado['propuesta_ms']-apertura['tiempo_ms'],6)
    else:llenado['duracion_desde_apertura_ms']=None
    return {'version':VERSION,'apertura':apertura,'forvia':forvia,'inflado_completo':llenado,
            'camara_descartada_para_medicion':'SCHEIBE',
            'excel':{'opening_time_ms':apertura['tiempo_ms'],
                     'forvia_measurement_ms':forvia.get('tiempo_ms') if forvia.get('publicable') else None,
                     'full_inflation_time_ms':None},
            'nota_excel':'El llenado visual corroborado se conserva como propuesta, no como volumen físico confirmado.'}
