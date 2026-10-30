"""Detector secundario *en sombra* sobre fotogramas nativos en streaming.

Nunca modifica originales ni publica el tiempo. No asume que blanco = airbag:
requiere continuación temporal y descarta flashes globales evidentes.
"""
from __future__ import annotations
from collections import deque
from pathlib import Path

from .sincronizacion_v1510 import tiempo_fisico
from .verificador_apertura_v1510 import verificar_candidatos

VERSION = "15.10.1-shadow"


def _gray(frame):
    import cv2
    import numpy as np
    if frame.ndim == 2:
        return frame.astype(np.uint8, copy=False)
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def inspeccionar_frames(frames, *, roi: tuple[int,int,int,int] | None = None,
                        fps_adquisicion: float | None = None,
                        umbral_pixeles: int = 18,
                        minimo_pixeles: int = 1,
                        max_frames: int = 20000) -> dict:
    """Examina F-1/F/F+1... sin seeks; devuelve top 3 hipótesis, no verdad.

    roi=(x,y,w,h) en píxeles de fotograma original. Límite de memoria O(ROI)
    más lista de métricas O(N), sin cargar todos los fotogramas.
    """
    import cv2
    import numpy as np
    metricas = []
    baseline = None
    ultima = None
    candidata = []
    shape_prev = None
    for idx, frame in enumerate(frames):
        if idx >= max_frames:
            break
        if frame is None:
            break
        gris = _gray(frame)
        h,w = gris.shape
        if roi is not None:
            x,y,an,al = [int(t) for t in roi]
            if an < 3 or al < 3 or x < 0 or y < 0 or x+an > w or y+al > h:
                raise ValueError("ROI fuera de la imagen; no desplazar ROI manual silenciosamente")
            region = gris[y:y+al, x:x+an]
            # Fondo exterior al ROI, para descartar flash de cámara global.
            exterior = np.ones_like(gris, dtype=bool)
            exterior[y:y+al, x:x+an] = False
        else:
            region = gris
            exterior = None
        if shape_prev is not None and shape_prev != region.shape:
            raise ValueError("La resolución/ROI cambió durante el video")
        shape_prev = region.shape
        if baseline is None:
            baseline = region.copy()
            ultima = region.copy()
            metricas.append({"frame":idx,"novedad_local":0,"persistencia_local":0,
                             "flash_global":False})
            anterior_global = float(np.median(gris[exterior])) if exterior is not None and exterior.any() else None
            continue
        # Novedad frente al baseline y cambio positivo frente al fotograma previo.
        d_base = cv2.absdiff(region, baseline)
        d_prev = cv2.absdiff(region, ultima)
        pix = (d_base>=umbral_pixeles) & (d_prev>=umbral_pixeles)
        novedad = int(np.count_nonzero(pix))
        persistencia = int(np.count_nonzero(d_base>=umbral_pixeles))
        flash = False
        if exterior is not None and exterior.any() and anterior_global is not None:
            actual = float(np.median(gris[exterior]))
            flash = abs(actual - anterior_global) >= 25
            anterior_global = actual
        elif exterior is None:
            # En pantalla completa es imposible descartar un flash por fondo.
            flash = False
        ultima = region.copy()
        met = {"frame":idx,"novedad_local":novedad,
               "persistencia_local":persistencia,"flash_global":flash}
        metricas.append(met)
        if novedad >= minimo_pixeles and not flash:
            candidata.append(idx)
    # El candidato es un F con indicio, nunca el F+N donde ya es grande.
    ver = verificar_candidatos(metricas, candidata, max_candidatos=3)
    onset = ver["inicio_sugerido_frame"]
    reloj = (tiempo_fisico(frame=onset,fps_adquisicion=fps_adquisicion)
             if onset is not None and fps_adquisicion is not None else {"valido":False,"motivo":"fps_adquisicion_no_verificado"})
    return {"version":VERSION, "estado":"candidato_en_sombra" if onset is not None else "sin_evento_corroborrado",
            "frames_leidos":len(metricas), "onset_frame_candidato":onset,
            "tiempo_fisico_candidato":reloj,"verificacion":ver,
            "candidatos_considerados":len(candidata),"publicable":False,
            "nota":"Heurística experimental; requiere evaluación real antes de cualquier publicación"}


def inspeccionar_video(ruta: str | Path, *, roi=None, fps_adquisicion=None,
                       max_frames: int = 20000) -> dict:
    import cv2
    cap=cv2.VideoCapture(str(ruta))
    if not cap.isOpened():
        return {"version":VERSION,"estado":"no_evaluable","motivo":"no_se_pudo_abrir_video","publicable":False}
    def iterar():
        while True:
            ok, frame=cap.read()
            if not ok:break
            yield frame
    try:
        return inspeccionar_frames(iterar(),roi=roi,fps_adquisicion=fps_adquisicion,max_frames=max_frames)
    finally:
        cap.release()


def main():
    import argparse
    import json
    p=argparse.ArgumentParser(description='Detector secundario V15.10.1 SOLO MODO SOMBRA')
    p.add_argument('video',help='AVI de prueba, sin modificar')
    p.add_argument('--roi',nargs=4,type=int,metavar=('X','Y','ANCHO','ALTO'))
    p.add_argument('--fps-adquisicion',type=float,
                   help='FPS FÍSICOS verificados externamente; nunca asumir playback')
    p.add_argument('--max-frames',type=int,default=20000)
    p.add_argument('--salida',help='Nuevo JSON para comparar con evaluación humana')
    a=p.parse_args()
    r=inspeccionar_video(a.video,roi=tuple(a.roi) if a.roi else None,
                        fps_adquisicion=a.fps_adquisicion,max_frames=a.max_frames)
    data=json.dumps(r,ensure_ascii=False,indent=2)
    if a.salida:
        out=Path(a.salida)
        if out.exists():p.error('El JSON de salida ya existe; no se sobrescribe')
        if out.resolve()==Path(a.video).resolve():p.error('No sobrescribir el original')
        out.write_text(data,encoding='utf-8')
    print(data)


if __name__=='__main__':
    main()
