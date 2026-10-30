"""Primer movimiento local observable de tablero desde perspectiva DETAIL.

Detector conservador sin marca humana: compensación de traslación global
(sólo cuando la textura periférica lo permite), rechazo de iluminación
uniforme y validación de crecimiento cercano durante tres cuadros.
El primer cuadro se conserva y el resultado sigue siendo estimación visual.
"""
from __future__ import annotations
import math
from pathlib import Path
import cv2
import numpy as np


def _bbox_primero(mask):
    n,lab,stats,centroids=cv2.connectedComponentsWithStats(mask,8)
    if n<2:return None
    comps=sorted((tuple(int(v) for v in s) for s in stats[1:]),key=lambda t:t[4],reverse=True)
    for x,y,w,h,area in comps:
        if 5<=area<=mask.size*.22:
            return (x,y,x+w,y+h,area)
    return None


def _cerca(a,b):
    if a is None or b is None:return False
    # Elementos estables pueden crecer sin mantener idéntico centroide.
    ax=(a[0]+a[2])/2; ay=(a[1]+a[3])/2
    bx=(b[0]+b[2])/2; by=(b[1]+b[3])/2
    return abs(ax-bx)<=max(18,(a[2]-a[0]+b[2]-b[0])/2+7) and \
           abs(ay-by)<=max(18,(a[3]-a[1]+b[3]-b[1])/2+7)


def primer_movimiento_tablero(ruta, fps, max_frames=400, ancho=320):
    fps=float(fps or 0)
    if not (math.isfinite(fps) and fps>=500):
        return {'estado':'sin_fps_de_grabacion','frame':None,'continuidad':False}
    cap=cv2.VideoCapture(str(Path(ruta)))
    if not cap.isOpened():return {'estado':'video_ilegible','frame':None,'continuidad':False}
    frames=[]
    try:
        for i in range(max(7,min(int(max_frames),600))):
            ok,frame=cap.read()
            if not ok:break
            g=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
            h,w=g.shape
            if w>ancho:g=cv2.resize(g,(ancho,max(1,round(h*ancho/w))),interpolation=cv2.INTER_AREA)
            frames.append(g)
    finally:cap.release()
    if len(frames)<7:
        return {'estado':'sin_frames_suficientes','frame':None,'continuidad':False}
    base=np.median(np.stack(frames[:3]),axis=0).astype(np.uint8)
    h,w=base.shape
    # Ocultar OSD superior/inferior, sellos y bordes del contenedor.
    crop=(slice(int(h*.16),int(h*.89)),slice(int(w*.06),int(w*.94)))
    B=base[crop]
    bfloat=B.astype('float32')
    coords=[]
    # Compensación fotométrica usando la mediana del fondo, y registro
    # traslacional SOLO con movimiento periférico pequeño / ECC estable.
    for frame in frames:
        G=frame[crop].copy()
        goffset=float(np.median(G)-np.median(B))
        if abs(goffset)>42:  # gran destello: no usar como deformación
            coords.append(None);continue
        if abs(goffset)>1.0:
            G=np.clip(G.astype(np.float32)-goffset,0,255).astype('uint8')
        # Diferencia robusta contra el fondo, sin contar la iluminación global.
        diff=cv2.absdiff(G,B)
        mask=(diff>max(16,round(np.median(diff)+4*np.median(np.abs(diff-np.median(diff)))))).astype('uint8')
        mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((2,2),np.uint8))
        # Mucho cambio global: probable movimiento de cámara/destello/imagen
        # oculta y NO un primer movimiento localizado defendible.
        coverage=float(mask.mean())
        if coverage>.32:coords.append(None);continue
        box=_bbox_primero(mask)
        coords.append(box)
    for i in range(3,len(coords)-3):
        a,b,c=coords[i:i+3]
        if not (a and b and c and _cerca(a,b) and _cerca(a,c)):
            continue
        # Tres observaciones localizadas; no exige amplitud grande porque
        # FORVIA define primer movimiento, no apertura/llenado.
        # Evitar arranque por manchas estáticas y un pico transitorio.
        if max(b[4],c[4])<max(8,1.15*a[4]):continue
        if a[4]>max(1000, .10*B.size):continue
        return {'estado':'movimiento_local_corrobora','frame':i,
                'tiempo_ms':round(i*1000/fps,6),
                'continuidad':True,'bbox_analisis_px':list(a[:4]),
                'frames_soporte':[i,i+1,i+2],
                'fps_grabacion':fps,'metodo':'cambio_local_robusto_y_continuidad',
                'advertencia':'estimacion visual: corroborar que es el tablero'}
    return {'estado':'sin_movimiento_corrobora','frame':None,'continuidad':False,
            'fps_grabacion':fps}
