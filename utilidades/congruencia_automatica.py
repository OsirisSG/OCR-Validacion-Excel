#!/usr/bin/env python3
"""Motor auxiliar de investigación V-Matrix: decisión independiente y trazable.

Motor integrado. Solo calcula evidencia visual, sin guardar cambios externos. Usa OpenCV y numpy.
No presupone que FPS del contenedor = FPS de grabación. No adivina el máximo físico.
"""
from __future__ import annotations
import argparse
import csv
import json
import math
import pathlib
import sys
from dataclasses import asdict, dataclass

import cv2
import numpy as np

VERSION = 'v16.0.7-primer-indicio-debil-fisicamente-corroborrado'
K3 = np.ones((3, 3), dtype=np.uint8)

@dataclass
class Measure:
    frame: int
    area_px: int
    novelty_frac: float
    gain: float
    bbox: tuple | None
    centroid: tuple | None
    edge_touch: bool


def measure_frame(frame, reference, static):
    h,w=reference.shape
    gray=cv2.cvtColor(cv2.resize(frame,(w,h),interpolation=cv2.INTER_AREA),cv2.COLOR_BGR2GRAY)
    # La ventana elimina OSD superior e inferior de la máscara de objeto.
    top,bottom=int(h*.08),int(h*.94)
    left,right=int(w*.02),int(w*.98)
    cur=gray[top:bottom,left:right].astype(np.float32)
    ref=reference[top:bottom,left:right]
    st=static[top:bottom,left:right]
    gain=float(np.clip(np.median(cur[st] / np.maximum(ref[st],1)),.45,3.0)) if np.any(st) else 1.0
    residual=cur-gain*ref
    # Señales complementarias: material claro nuevo y novedad de textura/sombra.
    novelty=float(np.mean(np.abs(residual)>25))
    m=((cur>100) & (residual>25)).astype(np.uint8)
    m=cv2.morphologyEx(m, cv2.MORPH_OPEN, K3)
    n,labels,stats,centroids=cv2.connectedComponentsWithStats(m,connectivity=8)
    if n>1:
        j=int(np.argmax(stats[1:,cv2.CC_STAT_AREA])+1)
        x,y,bw,bh,area=map(int,stats[j,:5])
        centroid=(float(centroids[j][0]+left),float(centroids[j][1]+top))
        bbox=(x+left,y+top,bw,bh)
        touch=(x<=2 or y<=2 or x+bw>=right-left-2 or y+bh>=bottom-top-2)
    else:
        area=0;centroid=None;bbox=None;touch=False
    return area,novelty,gain,bbox,centroid,touch


def _continuous(m, index, *, width=480):
    """Una isla de tela debe seguir físicamente en cuadros siguientes.

    Esta condición discrimina reflejos que cambian bruscamente de lugar.
    No equivale a una segmentación semántica entrenada.
    """
    a=m[index]
    if not a.centroid:return False
    future=m[index+1:index+5]
    valid=[z for z in future if z.centroid and z.area_px>=max(20,a.area_px*.10)]
    if len(valid)<3:return False
    near=sum(1 for z in valid if math.dist(a.centroid,z.centroid)<width*.24)
    if near<3:return False
    # Si una componente temprana salta a otra isla dominante en el siguiente
    # cuadro, era un flash/reflejo o hubo pérdida de identidad.
    if math.dist(a.centroid,valid[0].centroid)>width*.23:return False
    return True


def decide_onset(metrics, *, width=480):
    # Buscar en TODO el clip: no presuponer que la apertura ocurre en 260 cuadros.
    first=metrics
    if len(first)<13:
        return {'estado':'insuficiente','cuadro':None,'intervalo':None,'razones':['clip_demasiado_corto']}
    # Únicamente los primeros cuadros de referencia aportan ruido. Cuadros
    # posteriores no elevan el umbral: impediría detectar el primer hilo de tela.
    baseline=max((x.area_px for x in first[:5]),default=0)
    umbral=max(100,3*baseline+20)
    # Los cuadros 0..3 son baseline. El diagnóstico nunca confunde deformación
    # con tela si ésta carece de desarrollo temporal visible.
    eligible=[]
    for i in range(4,max(4,len(first)-5)):
        v=first[i]
        if v.area_px<umbral or not _continuous(first,i,width=width):continue
        # Evitar un elemento brillante que aparece y se va sin crecer;
        # exigir incremento neto en los siguientes 2-6 fotogramas.
        later=[x.area_px for x in first[i+1:min(len(first),i+7)]]
        if not later or max(later)<max(v.area_px*1.45,v.area_px+80):continue
        eligible.append(i)
    if not eligible:
        return {'estado':'evidencia_insuficiente','cuadro':None,'intervalo':None,
                'razones':['sin_trayectoria_de_tela_nueva_con_crecimiento'], 'umbral_area_px':umbral}
    chosen=int(eligible[0]);v=first[chosen]
    # Retroceso de hasta 30 cuadros (6 ms a 5000 fps) ÚNICAMENTE si el
    # mismo material está ya medido en una trayectoria continua. La salida
    # sigue siendo una HIPÓTESIS débil hasta comprobar ruptura local.
    # No se restan milisegundos ni se extrapolan cuadros de aire.
    # La hipótesis débil requiere validación del detector físico local antes
    # de poder convertirse en el frame oficial del video.
    indicio=None
    for j in range(max(4,chosen-30), chosen):
        z=first[j]
        if z.area_px < max(10, int(0.07*v.area_px)) or not z.centroid or not v.centroid:
            continue
        cadena=first[j:chosen+1]
        if any(not q.centroid for q in cadena):
            continue
        if any(math.dist(a.centroid,b.centroid)>width*0.075
               for a,b in zip(cadena,cadena[1:])):
            continue
        # No arrastrar una isla que aparece y desaparece o cambia de
        # identidad de golpe. El material debe evolucionar de forma gradual.
        if any(b.area_px < max(10,a.area_px*.28)
               for a,b in zip(cadena,cadena[1:])):
            continue
        if max(q.area_px for q in first[chosen+1:min(chosen+7,len(first))]) < z.area_px*1.7:
            continue
        indicio=j
        break
    # Un destello o tapa que se mueve pueden sobrevivir a estos filtros.
    # Mostrar el comienzo observado con incertidumbre de 1-2 cuadros.
    # En lugar de imponer un desfase fijo entre cámaras, cada vista decide sola.
    return {'estado':'candidato_automatico_no_validado','cuadro':chosen,
            'intervalo':[max(0,chosen-1),min(len(first)-1,chosen+1)],
            'razones':['componente_nueva_con_persistencia','crecimiento_local_posterior',
                       'primer_indicio_visible_no_equivale_a_comando_de_disparo'],
            'area_inicio_px':v.area_px,'umbral_area_px':umbral,
            'primer_indicio_debil_cuadro': indicio,
            'primer_indicio_debil_validado': False}


def decide_max(metrics, onset):
    if onset.get('cuadro') is None:
        return {'estado':'sin_inicio_confiable','cuadro':None,'razones':['falta_inicio_de_despliegue']}
    start=int(onset['cuadro']);n=len(metrics)
    if n-start<30:
        return {'estado':'clip_censurado','cuadro':None,'razones':['sin_suficientes_cuadros_posteriores']}
    # La cantidad de píxeles con contenido nuevo, no sólo los blancos, permite
    # detectar un objetivo cubierto por tela que se ha oscurecido.
    covered=[z.frame for z in metrics[start:] if z.novelty_frac>=.75]
    runs=next((a for a,b in zip(covered,covered[1:]) if b==a+1),None)
    if runs is not None:
        return {'estado':'maximo_censurado_por_encuadre','cuadro':None,
                'limite_visibilidad_cuadro':int(runs),'razones':
                ['material_nuevo_cubre_75pct_o_mas_del_encuadre_2_cuadros',
                 'superficie_proyectada_deja_de_medirse_al_ocultarse_la_bolsa']}
    areas=np.array([z.area_px for z in metrics],dtype=float)
    # Mediana causal de tres: sin fuga del futuro hacia el instante inicial.
    smooth=np.array([float(np.median(areas[max(start,i-2):i+1])) if i>=start else 0
                     for i in range(n)])
    if max(smooth[start:],default=0)<200:
        return {'estado':'sin_maximo_defendible','cuadro':None,'razones':['area_nueva_insuficiente']}
    # Un máximo idéntico al primer fotograma no demuestra que se observó
    # expansión: evita el Tmax=0 injustificado detectado en auditorías previas.
    initial=float(max(smooth[start],areas[start],20))
    if max(smooth[start:],default=0)<initial*1.35:
        return {'estado':'sin_maximo_defendible','cuadro':None,
                'razones':['sin_crecimiento_posterior_a_aparicion']}
    # Pico de toda la secuencia: nunca detenerse en la primera meseta.
    peak=float(np.quantile(smooth[start:],.995))
    required=.92*peak
    chosen=None
    for i in range(start+2,n-12):
        if smooth[i]<required:continue
        # No aceptar la subida a una meseta mientras el objeto aún crece
        # perceptiblemente: FRONTAL f153 todavía aumenta hacia f160.
        if max(smooth[i:min(n,i+7)],default=0)>smooth[i]*1.018:continue
        nearby=smooth[i:i+12]
        if np.count_nonzero(nearby>=.89*peak)<9:continue
        # Si después crece más del 9% frente al candidato, todavía no alcanzó
        # su máximo proyectado; ventana corta evita usar 750 cuadros de futuro.
        if max(smooth[i:min(n,i+30)])>max(smooth[i]*1.10,peak*1.04):continue
        chosen=i;break
    if chosen is None:
        top_i=int(np.argmax(smooth[start:])+start)
        return {'estado':'maximo_observado_no_confirmado','cuadro':top_i,
                'razones':['sin_meseta_global_persistente','no_publicar_como_maximo_fisico'],
                'area_max_observada_px':int(areas[top_i])}
    # Las variaciones posteriores tardías no son automáticamente "más inflado":
    # un giro/reorientación también cambia el área proyectada.
    last_n=30
    later=smooth[chosen+last_n:]
    if later.size and max(later,default=0)>smooth[chosen]*1.20:
        return {'estado':'maximo_observado_no_confirmado','cuadro':chosen,
                'razones':['crecimiento_tardio_excesivo','posible_segunda_fase_o_cambio_de_perspectiva']}
    return {'estado':'meseta_de_area_2d_candidata','cuadro':chosen,
            'razones':['barrido_completo','meseta_persistente_cerca_del_maximo_global',
                       'maximo_fisico_y_presion_no_inferibles_de_video_2d'],
            'area_meseta_px':int(areas[chosen]),'area_pico_robusto_px':int(peak)}


def analyze_one(path: pathlib.Path, *, capture_fps:float|None, max_width:int=480):
    cap=cv2.VideoCapture(str(path))
    if not cap.isOpened():return {'video':str(path),'error':'no_se_pudo_abrir'}
    playback_fps=float(cap.get(cv2.CAP_PROP_FPS) or 0)
    declared=int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    frames=[];base_frames=[];ref=None;st=None;read_error=None
    try:
        i=0
        while True:
            ok,fr=cap.read()
            if not ok:break
            if i<4:
                h,w=fr.shape[:2];out_w=min(max_width,w)
                out_h=max(64,int(round(h*out_w/w)))
                fg=cv2.cvtColor(cv2.resize(fr,(out_w,out_h)),cv2.COLOR_BGR2GRAY)
                base_frames.append(fg.astype(np.float32))
            if i==4:
                ref=np.median(np.stack(base_frames),axis=0).astype(np.float32)
                st=(ref>20)&(ref<215)
            if ref is None:
                frames.append(Measure(i,0,0.0,1.0,None,None,False))
            else:
                area,nov,gain,bbox,center,touch=measure_frame(fr,ref,st)
                frames.append(Measure(i,area,round(nov,5),round(gain,4),bbox,center,touch))
            i+=1
    finally:cap.release()
    onset=decide_onset(frames,width=ref.shape[1] if ref is not None else max_width)
    maximo=decide_max(frames,onset)
    if capture_fps is not None:
        for res in (onset,maximo):
            for field in ('cuadro','limite_visibilidad_cuadro'):
                if res.get(field) is not None:
                    res[field+'_ms']=round(res[field]*1000/capture_fps,4)
        if onset.get('cuadro') is not None and maximo.get('cuadro') is not None:
            maximo['tiempo_aparicion_a_meseta_ms']=round((maximo['cuadro']-onset['cuadro'])*1000/capture_fps,4)
    warnings=[]
    if playback_fps and capture_fps and abs(playback_fps-capture_fps)/capture_fps>.03:
        warnings.append('fps_contenedor_es_reproduccion_no_tiempo_de_captura')
    if declared and abs(declared-len(frames))>1:warnings.append('conteo_fotogramas_inconsistente')
    return {'version':VERSION,'video':str(path),'cuadros_leidos':len(frames),
            'fps_contenedor':playback_fps,'fps_captura_declarado':capture_fps,
            'advertencias':warnings,'aparicion_bolsa':onset,'maximo_visible':maximo,
            'publicacion_oficial_autorizada':False,
            'medidas':[asdict(z) for z in frames]}


def run(directory,output,capture_fps,max_width):
    paths=sorted(p for p in directory.rglob('*') if p.suffix.lower() in ('.avi','.mp4','.mov'))
    if not paths:raise SystemExit('No se encontraron videos AVI/MP4/MOV en esa carpeta.')
    output.mkdir(parents=True,exist_ok=True)
    results=[]
    for p in paths:
        print('Analizando',p.name,flush=True)
        result=analyze_one(p,capture_fps=capture_fps,max_width=max_width)
        with (output/(p.stem+'_diagnostico.json')).open('w',encoding='utf-8') as f:
            json.dump(result,f,indent=2,ensure_ascii=False,allow_nan=False)
        with (output/(p.stem+'_curva.csv')).open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.writer(f);w.writerow(['frame','area_proyectada_px','novedad_fraccion','ganancia_luz','bbox'])
            for a in result.get('medidas',[]):w.writerow([a['frame'],a['area_px'],a['novelty_frac'],a['gain'],a['bbox']])
        results.append({k:v for k,v in result.items() if k!='medidas'})
    with (output/'RESUMEN_CONGRUENCIA.json').open('w',encoding='utf-8') as f:
        json.dump(results,f,indent=2,ensure_ascii=False)
    with (output/'RESUMEN_CONGRUENCIA.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.writer(f)
        writer.writerow(['video','fps_contenedor','fps_captura','cuadro_aparicion','estado_aparicion','tiempo_aparicion_ms','cuadro_maximo_2d','estado_maximo','tiempo_maximo_ms','advertencias'])
        for r in results:
            o=r.get('aparicion_bolsa',{});m=r.get('maximo_visible',{})
            writer.writerow([pathlib.Path(r['video']).name,r.get('fps_contenedor'),r.get('fps_captura_declarado'),
                             o.get('cuadro'),o.get('estado'),o.get('cuadro_ms'),m.get('cuadro'),m.get('estado'),m.get('cuadro_ms'),'; '.join(r.get('advertencias',[]))])
    for r in results:
        o=r.get('aparicion_bolsa',{});m=r.get('maximo_visible',{})
        print(pathlib.Path(r['video']).name, 'APARICION',o.get('cuadro'),o.get('estado'),
              '| MAX',m.get('cuadro'),m.get('estado'))
    print('Resultados en',output)


def main():
    p=argparse.ArgumentParser(description='V-Matrix LAB: auditoria automát. No modifica datos oficiales.')
    p.add_argument('carpeta',type=pathlib.Path)
    p.add_argument('--salida',type=pathlib.Path,default=pathlib.Path.cwd()/'SALIDA_CONGRUENCIA')
    p.add_argument('--fps-captura',type=float,default=None,help='FPS reales de grabacion (NO FPS de reproduccion AVI)')
    p.add_argument('--ancho',type=int,default=480)
    a=p.parse_args()
    if a.fps_captura is not None and not (math.isfinite(a.fps_captura) and 1<a.fps_captura<100000):
        p.error('--fps-captura debe ser un FPS de grabacion positivo y confiable')
    if not (160<=a.ancho<=1200):p.error('--ancho debe estar entre 160 y 1200')
    if not a.carpeta.is_dir():p.error('La carpeta indicada no existe')
    run(a.carpeta,a.salida,a.fps_captura,a.ancho)
if __name__=='__main__':main()
