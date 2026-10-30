"""V16.0.8: propuesta de ROI por deformacion local temporal, sin aprender ni persistir.

Se aplica como un observador: sólo entrega zona si hay movimiento no rígido,
contorno nuevo localizado y continuidad espacial en varias imágenes.
No identifica bolsa ni ruptura; nunca establece tiempos ni colores por sí solo.
"""
from __future__ import annotations

import math
from collections import deque
from pathlib import Path
import cv2
import numpy as np

VERSION_ROI_DEFORMACION = 'v16.0.8-roi-deformacion-temporal-1'


def _gray(frame, width):
    h,w=frame.shape[:2]
    k=min(1.0,float(width)/max(1,w))
    dim=(max(1,int(round(w*k))), max(1,int(round(h*k))))
    b=cv2.resize(frame,dim,interpolation=cv2.INTER_AREA) if k<1 else frame
    return cv2.cvtColor(b,cv2.COLOR_BGR2GRAY) if b.ndim==3 else b.copy()


def _measure(prev,cur):
    """Suprime cambio global; devuelve bbox del movimiento no rigido y su soporte."""
    h,w=prev.shape
    valid=np.zeros((h,w),np.uint8)
    valid[int(h*.13):int(h*.84),int(w*.045):int(w*.955)]=255
    pp=cv2.goodFeaturesToTrack(prev,maxCorners=200,qualityLevel=.015,minDistance=5,mask=valid)
    affine=np.eye(2,3,dtype=np.float32)
    inlier_ratio=0.0
    if pp is not None and len(pp)>=12:
        p2,st,_=cv2.calcOpticalFlowPyrLK(prev,cur,pp,None,winSize=(17,17),maxLevel=2,
                                           criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,20,.03))
        if p2 is not None and st is not None:
            ok=st.reshape(-1).astype(bool)
            if int(ok.sum())>=12:
                aa,inliers=cv2.estimateAffinePartial2D(pp.reshape(-1,2)[ok],p2.reshape(-1,2)[ok],
                                                         method=cv2.RANSAC,ransacReprojThreshold=1.5,
                                                         maxIters=1000,confidence=.98)
                if aa is not None and inliers is not None:
                    inlier_ratio=float(inliers.mean())
                    if inlier_ratio>=.43:
                        affine=aa.astype(np.float32)
    # Resamplear el cuadro previo a las coordenadas actuales, pero NO estimar
    # deformacion a partir de un movimiento uniforme de la camara.
    warped=cv2.warpAffine(prev,affine,(w,h),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT)
    # Quitar cambios globales de iluminacion, conservando cambios locales.
    src=warped.astype(np.float32)
    target=cur.astype(np.float32)
    ref=src[valid>0]; obs=target[valid>0]
    gain=float(np.clip(np.median((obs+8.0)/(ref+8.0)),.66,1.50)) if len(ref) else 1.0
    normalized=np.clip(src*gain,0,255).astype(np.uint8)
    difference=np.abs(cur.astype(np.int16)-normalized.astype(np.int16))
    global_change=float(np.mean(difference[valid>0]>32)) if np.any(valid) else 0.0
    if global_change>.48: # flash, barrido u oclusion masiva
        return None,'cambio_global'
    # Movimiento diferencial (no rigido) sobre un cuadro YA estabilizado.
    flow=cv2.calcOpticalFlowFarneback(normalized,cur,None,.50,3,17,2,5,1.1,0)
    motion=cv2.magnitude(flow[...,0],flow[...,1])
    mm=motion[valid>0]
    med=float(np.median(mm)); mad=float(np.median(np.abs(mm-med)))*1.4826
    threshold=max(.65,med+3*max(.09,mad))
    different=(motion>threshold)&(valid>0)
    # La textura/linea local tambien ha de cambiar: el flujo sin contorno
    # puede ser sombra, ruido, desplazamiento entero u objeto lejano.
    e1=cv2.Canny(normalized,45,115)
    e2=cv2.Canny(cur,45,115)
    newedge=(e2>0)&(cv2.dilate(e1,np.ones((3,3),np.uint8))==0)
    newedge=cv2.dilate(newedge.astype(np.uint8),np.ones((7,7),np.uint8)).astype(bool)
    local=(different&newedge).astype(np.uint8)
    local=cv2.morphologyEx(local,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
    n,lab,stat,_=cv2.connectedComponentsWithStats(local,connectivity=8)
    if n<=1:return None,'sin_deformacion_con_contorno'
    ar=stat[1:,cv2.CC_STAT_AREA]
    idx=int(np.argmax(ar))+1
    x,y,bw,bh,area=map(int,stat[idx,:5])
    if area<max(8,int(valid.sum()/255*.00015)) or area>valid.sum()/255*.11:
        return None,'area_fuera_rango'
    if bw<3 or bh<3:return None,'contorno_sin_extension'
    return {'bbox':(x,y,x+bw,y+bh),'area':area,'motion_px':round(float(np.median(motion[lab==idx])),3),
            'global_change':round(global_change,4),'inliers':round(inlier_ratio,3)},'candidato'


def _overlap(a,b):
    x1=max(a[0],b[0]);y1=max(a[1],b[1]);x2=min(a[2],b[2]);y2=min(a[3],b[3])
    inter=max(0,x2-x1)*max(0,y2-y1)
    aa=max(1,(a[2]-a[0])*(a[3]-a[1]))
    bb=max(1,(b[2]-b[0])*(b[3]-b[1]))
    return inter/max(1,min(aa,bb))


def _expand(b,w,h,margin=.075):
    padx=int(w*margin);pady=int(h*margin)
    x1=max(int(w*.04),b[0]-padx);x2=min(int(w*.96),b[2]+padx)
    y1=max(int(h*.12),b[1]-pady);y2=min(int(h*.85),b[3]+pady)
    return [round(x1/w,6),round(y1/h,6),round(x2/w,6),round(y2/h,6)]


def buscar_roi_deformacion(ruta_video, *, ancho_analisis=400, max_frames=750, max_eventos=12):
    """Propuesta temporal independiente; no toca ROI manual ni resultados oficiales."""
    c=cv2.VideoCapture(str(Path(ruta_video)))
    if not c.isOpened():
        return {'confiable':False,'motivo':'video_no_disponible','bbox_norm':None}
    try:
        prev=None; historial=deque(maxlen=12); grupos=[]; reason={}; frames=0
        for i in range(max(1,int(max_frames))):
            ok,frame=c.read()
            if not ok:break
            frames+=1
            cur=_gray(frame,max(160,min(int(ancho_analisis),600)))
            if prev is None:prev=cur;continue
            if cur.shape!=prev.shape:break
            # El primer par de cuadros puede contener estabilizacion/disparo,
            # pero no inferir onset desde una sola observacion.
            item,motivo=_measure(prev,cur)
            prev=cur
            if item is None:
                reason[motivo]=reason.get(motivo,0)+1
                continue
            item['frame']=i
            h,w=cur.shape
            # Coincidencia espacial con evidencia de movimiento NO rigido en
            # al menos tres cuadros de una ventana maxima de seis. Evita un
            # brillo especular aislado que desaparece en otro lugar.
            cercanos=[k for k in historial if i-k['frame']<=6 and
                      _overlap(k['bbox'],item['bbox'])>=.10]
            historial.append(item)
            if len(cercanos)>=2:
                soporte=cercanos[-3:]+[item]
                # Expandir alrededor de la union de zona estable, no de todo el
                # movimiento posterior (que ya puede ser la bolsa inflada).
                b=[min(z['bbox'][0] for z in soporte),min(z['bbox'][1] for z in soporte),
                   max(z['bbox'][2] for z in soporte),max(z['bbox'][3] for z in soporte)]
                bbox=_expand(b,w,h)
                area=(bbox[2]-bbox[0])*(bbox[3]-bbox[1])
                if .0015<=area<=.56:
                    grupos.append({'bbox_norm':bbox,'frame_indicio':int(soporte[0]['frame']),
                                   'frames_soporte':[int(z['frame']) for z in soporte],
                                   'movimiento_mediano_px':round(float(np.median([z['motion_px'] for z in soporte])),3),
                                   'confianza':round(min(.92,.66+.06*len(soporte)),3)})
                    if len(grupos)>=max_eventos:break
        if not grupos:
            return {'confiable':False,'motivo':'sin_deformacion_temporal_corroborrada',
                    'bbox_norm':None,'frames_examinados':frames,'rechazos':reason,
                    'version':VERSION_ROI_DEFORMACION}
        # El primer indicio espacial confirmado manda; el aumento de area
        # posterior no debe mover la ROI hacia la bolsa totalmente expandida.
        g=min(grupos,key=lambda z:(z['frame_indicio'],-len(z['frames_soporte'])))
        return {'confiable':True,'motivo':'deformacion_local_con_contorno_persistente',
                'bbox_norm':g['bbox_norm'],'frame_indicio':g['frame_indicio'],
                'frames_soporte':g['frames_soporte'],'confianza':g['confianza'],
                'movimiento_mediano_px':g['movimiento_mediano_px'],
                'frames_examinados':frames,'version':VERSION_ROI_DEFORMACION}
    except (cv2.error,ValueError,OverflowError) as err:
        return {'confiable':False,'bbox_norm':None,'motivo':'error_deformacion','detalle':str(err)[:160],
                'version':VERSION_ROI_DEFORMACION}
    finally:c.release()
