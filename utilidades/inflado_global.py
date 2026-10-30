"""V16.0.5 - medición EXPLORATORIA de máximo despliegue visible en la imagen completa.

La bolsa se identifica con una semilla contextual; NO se restringe su máscara a
una ROI. El área de movimiento/contraste es una aproximación 2D y NO equivale
al volumen físico. Este análisis NO publica automáticamente el Tmax.
"""
from __future__ import annotations

import math
from collections import deque
from pathlib import Path

import cv2
import numpy as np


def _gris(frame, max_ancho):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    alto, ancho = gray.shape[:2]
    if ancho > max_ancho:
        scale = max_ancho / float(ancho)
        gray = cv2.resize(gray, (max_ancho, max(1, round(alto * scale))),
                          interpolation=cv2.INTER_AREA)
    return gray


def _borde(shape, fraccion=.19):
    alto, ancho = shape
    py, px = max(7, int(alto * fraccion)), max(7, int(ancho * fraccion))
    mask = np.full((alto, ancho), 255, dtype=np.uint8)
    mask[py:alto-py, px:ancho-px] = 0
    return mask


def _alinea_fondo(ref, actual, mask_borde):
    """Estabiliza contra fondo periférico; evita ajustar cámara a la bolsa.

    1. Si el fondo periférico sigue estable, evita optical flow (rápido).
    2. En caso contrario, LK + RANSAC para estimar el movimiento rígido.
    3. Si faltan rasgos suficientes, no inventa movimiento de cámara fiable.
    """
    periferia = mask_borde > 0
    delta = actual.astype(np.int16) - ref.astype(np.int16)
    dif_borde = delta[periferia]
    brillo = float(np.median(dif_borde))
    resto = np.abs(dif_borde - brillo)
    # Acepta pequeñas variaciones fotométricas sin transformar geometría.
    if np.percentile(resto, 90) < 7.0:
        return actual, True, 'estable'
    puntos = cv2.goodFeaturesToTrack(ref, maxCorners=180, qualityLevel=.012,
                                      minDistance=7, mask=mask_borde, blockSize=5)
    if puntos is None or len(puntos) < 10:
        return actual, False, 'fondo_sin_textura_para_registro'
    siguientes, estado, _ = cv2.calcOpticalFlowPyrLK(
        ref, actual, puntos, None, winSize=(17, 17), maxLevel=2,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 20, .03))
    if siguientes is None or estado is None:
        return actual, False, 'seguimiento_optico_invalido'
    buenos = estado.ravel().astype(bool)
    origen = puntos.reshape(-1, 2)[buenos]
    destino = siguientes.reshape(-1, 2)[buenos]
    if len(origen) < 10:
        return actual, False, 'pocos_rasgos_del_fondo'
    # Rechaza trayectorias con error de ida-vuelta demasiado grande.
    vuelta, e2, _ = cv2.calcOpticalFlowPyrLK(
        actual, ref, destino.reshape(-1, 1, 2), None,
        winSize=(17, 17), maxLevel=2)
    if vuelta is None or e2 is None:
        return actual, False, 'flujo_sin_consistencia'
    errores = np.linalg.norm(vuelta.reshape(-1, 2) - origen, axis=1)
    buenos_2 = e2.ravel().astype(bool) & (errores < 2.0)
    origen, destino = origen[buenos_2], destino[buenos_2]
    if len(origen) < 10:
        return actual, False, 'movimiento_camara_no_verificable'
    matriz, inliers = cv2.estimateAffinePartial2D(
        origen, destino, method=cv2.RANSAC, ransacReprojThreshold=2.5,
        maxIters=1200, confidence=.99)
    if matriz is None or inliers is None or not np.isfinite(matriz).all():
        return actual, False, 'registro_ransac_fallido'
    ratio = float(inliers.mean())
    escala = math.hypot(float(matriz[0,0]), float(matriz[0,1]))
    rot = math.degrees(math.atan2(float(matriz[1,0]), float(matriz[0,0])))
    desplaz = math.hypot(float(matriz[0,2]), float(matriz[1,2]))
    if ratio < .55 or not (.94 <= escala <= 1.06) or abs(rot) > 7.0 or desplaz > .09*min(ref.shape):
        return actual, False, 'movimiento_fondo_inestable'
    inv = cv2.invertAffineTransform(matriz)
    registrado = cv2.warpAffine(actual, inv, (ref.shape[1], ref.shape[0]),
                                 flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    # Comprobación independiente sobre píxeles del fondo (con brillo normalizado).
    resid = (registrado.astype(np.int16) - ref.astype(np.int16))[periferia]
    mediana = np.median(resid)
    if np.percentile(np.abs(resid - mediana), 75) > 24:
        return actual, False, 'registro_fondo_con_residuo_alto'
    return registrado, True, 'lk_ransac'


def _objeto_asociado(actual, referencia, mascara_previa, semilla,
                     minimo_area_fraccion, umbral_cambio):
    h, w = referencia.shape
    # Brillo estimado sólo sobre borde, para que el volumen visible de la
    # bolsa no determine el ajuste de exposición.
    borde = _borde(referencia.shape) > 0
    delta = actual.astype(np.int16) - referencia.astype(np.int16)
    delta = delta - int(round(float(np.median(delta[borde]))))
    fg = (np.abs(delta) >= max(8, int(umbral_cambio))).astype(np.uint8)
    k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3,3))
    k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5,5))
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, k3)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, k5)
    fraccion = float(np.mean(fg))
    if fraccion > .75:
        return None, 'cambio_de_escena_excesivo', False
    n, labels, stats, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
    if n < 2:
        return None, 'sin_objeto_visible', False
    minimo = max(8, int(minimo_area_fraccion*h*w))
    radio = max(6, int(.025*math.hypot(h, w)))
    bbox_anterior = cv2.boundingRect(mascara_previa.astype(np.uint8)) if mascara_previa is not None else None
    mejores=[]
    for idx in range(1,n):
        area = int(stats[idx, cv2.CC_STAT_AREA])
        if area < minimo or area > .72*h*w:
            continue
        componente = (labels == idx)
        anclada = False
        if semilla is not None:
            sx, sy = semilla
            x1,y1=max(0,sx-radio),max(0,sy-radio)
            x2,y2=min(w,sx+radio+1),min(h,sy+radio+1)
            # Verificar contacto local (en lugar de medir distancia al
            # centroide de un objeto que puede crecer mucho).
            if x2>x1 and y2>y1:
                yy,xx=np.ogrid[y1:y2,x1:x2]
                anclada=bool(np.any(componente[y1:y2,x1:x2] & ((xx-sx)**2+(yy-sy)**2 <= radio**2)))
        solapa=int(np.count_nonzero(componente & mascara_previa)) if mascara_previa is not None else 0
        contacto=False
        if bbox_anterior is not None:
            px,py,pw,ph=bbox_anterior
            x,y,bw,bh=[int(stats[idx,j]) for j in range(4)]
            contacto=(x <= px+pw+radio and px <= x+bw+radio and
                      y <= py+ph+radio and py <= y+bh+radio)
        if anclada or solapa>max(4,int(area*.002)) or contacto:
            mejores.append((int(solapa>0), solapa, int(anclada), area, componente))
    if not mejores:
        return None, 'sin_componente_vinculado_al_evento', False
    # Selección espacial estable: priorizar continuidad, después superficie.
    mejores.sort(key=lambda x:(x[0],x[1],x[2]),reverse=True)
    componente = mejores[0][4]
    toca_borde = bool(np.any(componente[0]) or np.any(componente[-1]) or
                      np.any(componente[:,0]) or np.any(componente[:,-1]))
    return componente, 'asociado', toca_borde


def _secuencia_global(metricas, inicio, fps, alertas, min_area=12, *, solo_post=False):
    """Devuelve un *candidato*, nunca un máximo físicamente confirmado."""
    # V16.0.5: no reservar una entrada por cada fotograma anterior al evento.
    datos = metricas if solo_post else metricas[inicio:]
    bruto = [int(m.get('area_bolsa_visible_estimada_px') or 0) for m in datos]
    fiables = [bool(m.get('registro_confiable')) and bool(m.get('coincidencia_semilla')) for m in datos]
    estado = 'sin_maximo_defendible'
    frame_max = None
    razones = list(alertas)
    if len(bruto) < 8 or sum(fiables) < 7 or max(bruto, default=0) < min_area:
        razones.append('evidencia_de_expansion_insuficiente')
    else:
        # Ventana causal, nunca atribuir el máximo a cuadros anteriores por
        # información futura. Un cuadro sin máscara válida NO se trata como 0.
        suav=[]
        for i in range(len(bruto)):
            vals=[bruto[k] for k in range(max(0,i-2),i+1) if fiables[k]]
            suav.append(float(np.median(vals)) if len(vals)>=min(3,i+1) else float('nan'))
        validos=[(a,i) for i,a in enumerate(suav) if math.isfinite(a)]
        if validos:
            pico, i_pico=max(validos, key=lambda x:x[0])
            if pico >= min_area and i_pico >= 2 and max(bruto[:2],default=0) < .8*pico:
                umbral=.97*pico
                candidatos=[i for i,v in enumerate(suav) if math.isfinite(v) and v>=umbral]
                idx=candidatos[0] if candidatos else i_pico
                post=[v for v in suav[i_pico+1:] if math.isfinite(v)]
                declive= len(post)>=3 and sum(v <= .95*pico for v in post[:min(6,len(post))]) >= 3
                cola=[v for v in suav[-8:] if math.isfinite(v)]
                meseta= len(cola)>=7 and min(cola) >= .96*pico and (max(cola)-min(cola))/pico < .05
                if declive or meseta:
                    estado='maximo_visual_global_estimado'
                    frame_max=inicio+idx
                else:
                    estado='maximo_visible_observado_no_confirmado'
                    frame_max=inicio+i_pico
                    razones.append('maximo_sin_caida_o_meseta_sostenida')
            else:
                razones.append('sin_crecimiento_posterior_demostrable')
        else:
            razones.append('sin_muestras_temporales_fiables')
    try:
        fps = float(fps)
        if not math.isfinite(fps) or fps <= 0: fps=None
    except (ValueError, TypeError, OverflowError):
        fps=None
    if fps is None:
        razones.append('fps_captura_no_validado')
        if estado=='maximo_visual_global_estimado': estado='maximo_visible_observado_no_confirmado'
    if inicio==0:
        razones.append('evento_censurado_al_inicio')
        if estado=='maximo_visual_global_estimado':estado='maximo_visible_observado_no_confirmado'
    return {
        'estado':estado,'frame_breakout':inicio,'frame_max_inflado':frame_max,
        'tiempo_breakout_ms':round(inicio*1000/fps,6) if fps else None,
        'tiempo_max_inflado_ms':round(frame_max*1000/fps,6) if fps and frame_max is not None else None,
        'duracion_expansion_ms':round((frame_max-inicio)*1000/fps,6) if fps and frame_max is not None else None,
        'anomalías':list(dict.fromkeys(razones)),
        'metodo':'area_2d_global_estabilizada_con_pico_postverificado',
        'no_publicar_automaticamente':True,
    }


def _preparar_lectura(cap, frame_inicio, baseline):
    """Busca ventana preevento de forma verificable; falla al modo secuencial.

    Seek nunca se da por correcto sólo porque cap.set() devolvió True:
    la posición leída debe coincidir con el fotograma solicitado.
    """
    pre = max(3, min(9, int(baseline)))
    start = max(0, frame_inicio - pre - 3)
    if start < 180:
        return cap, 0, 'secuencial'
    try:
        salto_ok = cap.set(cv2.CAP_PROP_POS_FRAMES, start)
        pos = cap.get(cv2.CAP_PROP_POS_FRAMES)
        if salto_ok and math.isfinite(pos) and abs(pos - start) < .51:
            return cap, start, 'seek_verificado_por_indice'
    except (cv2.error, ValueError, TypeError):
        pass
    # No continuar leyendo desde una posición dudosa, evitar desalinear fps/onset.
    return cap, None, 'seek_no_verificable'


def _validar_timestamps(pares, fps):
    """Señal de alarma, no reemplaza FPS por timestamps de un codec dudoso."""
    if fps is None or len(pares) < 8:
        return 'no_verificable', []
    filtrados = [(i, t) for i, t in pares if math.isfinite(t) and t > 0]
    if len(filtrados) < 8:
        return 'no_disponible', []
    indices, tiempos = zip(*filtrados)
    if any(b <= a for a, b in zip(tiempos, tiempos[1:])):
        return 'no_monotonos', ['timestamps_de_video_no_monotonos']
    di = indices[-1] - indices[0]
    if di <= 0:
        return 'no_verificable', []
    observado = (tiempos[-1] - tiempos[0]) / di
    esperado = 1000 / fps
    if abs(observado - esperado) > .2 * esperado:
        return 'discrepancia', ['timestamps_no_concuerdan_con_fps']
    return 'coherente_aproximado', []


def analizar_inflado_global(ruta_video, frame_inicio, fps_captura=None, *,
                            frame_max_ventana=240, ancho_analisis=640,
                            frames_baseline=3, semilla_norm=None,
                            umbral_cambio=18, minimo_area_fraccion=.00015):
    """Mide el área visual global estimada, sin publicar Tmax automáticamente.

    Optimización V16.0.5:
      - acceso directo verificado a una ventana cercana a la ruptura;
      - O(ventana) memoria en lugar de O(onset+ventana);
      - controles de marcas temporales y datos de calidad reproducibles.
    """
    if isinstance(frame_inicio, bool) or not isinstance(frame_inicio, (int, np.integer)) or frame_inicio < 0:
        return {'estado':'sin_onset','metricas':[],'anomalías':['sin_onset'],'experimental':True,
                'no_publicar_automaticamente':True}
    frame_inicio = int(frame_inicio)
    ruta = str(Path(ruta_video))
    cap = cv2.VideoCapture(ruta)
    if not cap.isOpened():
        cap.release()
        return {'estado':'video_no_disponible','metricas':[],
                'anomalías':['video_no_disponible'],'experimental':True,
                'no_publicar_automaticamente':True}
    ancho=max(128,min(1000,int(ancho_analisis)))
    frames_max=max(8,min(1500,int(frame_max_ventana)))
    limite=frame_inicio+frames_max
    pre=max(3,min(9,int(frames_baseline)))
    cap, indice, metodo_lectura = _preparar_lectura(cap,frame_inicio,pre)
    if indice is None:
        cap.release()
        cap=cv2.VideoCapture(ruta)
        if not cap.isOpened():
            cap.release()
            return {'estado':'video_no_disponible','metricas':[],
                    'anomalías':['video_no_disponible'],'experimental':True,
                    'no_publicar_automaticamente':True}
        indice=0
        metodo_lectura='secuencial_por_seek_no_verificable'
    inicio_lectura=indice
    muestras_previas=deque(maxlen=pre)
    referencia=None; mascara_prev=None; mascara_fondo=None; semilla=None
    areas=[]; contadores={}; advertencias=[]; asociacion=False; bordes=0
    total=0; cuadros_post=0; timestamps=[]; video_terminado=False
    try:
        f_validado=float(fps_captura)
        if not math.isfinite(f_validado) or f_validado <= 0: f_validado=None
    except (TypeError,ValueError,OverflowError):
        f_validado=None
    try:
        while indice < limite:
            ok, frame=cap.read()
            if not ok:
                video_terminado=True
                break
            gris=_gris(frame,ancho)
            total+=1
            if indice < frame_inicio:
                muestras_previas.append(gris)
                indice+=1
                continue
            if referencia is None:
                if len(muestras_previas)<2:
                    advertencias.append('referencia_pre_evento_insuficiente')
                    break
                referencia=np.median(np.stack(tuple(muestras_previas)),axis=0).astype(np.uint8)
                mascara_fondo=_borde(referencia.shape)
                if semilla_norm is not None:
                    try:
                        sx,sy=map(float,semilla_norm)
                        if 0<=sx<=1 and 0<=sy<=1 and np.isfinite([sx,sy]).all():
                            semilla=(int(sx*(gris.shape[1]-1)), int(sy*(gris.shape[0]-1)))
                    except (TypeError,ValueError,OverflowError):
                        pass
                if semilla is None: advertencias.append('sin_semilla_de_apertura')
            cuadros_post+=1
            pos_ms=cap.get(cv2.CAP_PROP_POS_MSEC)
            if math.isfinite(pos_ms) and pos_ms > 0:
                timestamps.append((indice,float(pos_ms)))
            registrado,ok_reg,metodo_reg=_alinea_fondo(referencia,gris,mascara_fondo)
            if not ok_reg:
                contadores[metodo_reg]=contadores.get(metodo_reg,0)+1
                areas.append({'area_bolsa_visible_estimada_px':0,
                              'registro_confiable':False,'coincidencia_semilla':False,
                              'frame_index':indice})
                indice+=1
                continue
            comp,causa,toca=_objeto_asociado(registrado,referencia,mascara_prev,
                                               semilla,minimo_area_fraccion,umbral_cambio)
            if comp is not None:
                area=int(np.count_nonzero(comp))
                mascara_prev=comp
                asociacion=True
                if toca: bordes+=1
            else:
                area=0
                contadores[causa]=contadores.get(causa,0)+1
            areas.append({'area_bolsa_visible_estimada_px':area,
                          'fuente_area':'imagen_completa',
                          'registro_confiable':True,'coincidencia_semilla':comp is not None,
                          'frame_index':indice,'metodo_registro':metodo_reg,
                          'objeto_toca_borde':bool(toca)})
            indice+=1
    finally:
        cap.release()
    if cuadros_post and sum(v for k,v in contadores.items() if 'registro' in k or 'fondo' in k or 'camara' in k or 'rasgos' in k or 'flujo' in k)> .2*cuadros_post:
        advertencias.append('registro_de_camara_insuficiente')
    if indice >= limite: advertencias.append('ventana_de_busqueda_agotada')
    if bordes: advertencias.append('bolsa_o_movimiento_alcanza_borde_del_fotograma')
    if not asociacion: advertencias.append('sin_componente_vinculado_al_inicio')
    if semilla is None: advertencias.append('ausencia_de_anclaje_de_identidad')
    estado_ts,alertas_ts=_validar_timestamps(timestamps,f_validado)
    advertencias.extend(alertas_ts)
    secuencia=_secuencia_global(areas,frame_inicio,f_validado,advertencias,solo_post=True)
    if (('registro_de_camara_insuficiente' in advertencias)
            or ('ausencia_de_anclaje_de_identidad' in advertencias)
            or ('timestamps_no_concuerdan_con_fps' in advertencias)
            or ('timestamps_de_video_no_monotonos' in advertencias)
            or bordes):
        if secuencia['estado']=='maximo_visual_global_estimado':
            secuencia['estado']='maximo_visible_observado_no_confirmado'
            secuencia['anomalías'].append('calidad_no_apta_para_confirmar_maximo')
    return {
        'estado':'candidato_global' if asociacion else 'sin_evidencia_global',
        'metricas':areas,'secuencia':secuencia,'experimental':True,
        'no_publicar_automaticamente':True,
        'anomalías':list(dict.fromkeys(advertencias)),
        'diagnostico':contadores,'frames_analizados':total,
        'frames_post_evento':cuadros_post,'frame_inicio':frame_inicio,
        'ancho_max_analisis':ancho,'area_es_proxy_2d':True,
        'referencia_tiempo':'fps_captura_si_es_confiable',
        'fuente':'fotograma_completo_lk_ransac_ventana_optimizada_v16.0.5',
        'metodo_lectura':metodo_lectura, 'primer_frame_decodificado':inicio_lectura,
        'primer_frame_metrica':areas[0]['frame_index'] if areas else None,
        'timestamps_estado':estado_ts,'video_terminado':video_terminado,
        'cuantizacion_temporal_ms':round(1000/f_validado,6) if f_validado else None,
    }
