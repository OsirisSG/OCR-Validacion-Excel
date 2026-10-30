"""Análisis local de videos de despliegue de airbag.

V15.6 analiza el nacimiento del airbag como un evento temporal y unifica la
fuente de tiempo para que frame, reloj visible y casilla del dashboard no puedan
contradecirse. Primero busca
evidencia fuerte y persistente de despliegue y después retrocede hasta el primer
cuadro con evidencia débil coherente. Esto permite conservar como tiempo de
apertura la primera punta visible, sin aceptar reflejos aislados como evento.

La resolución temporal real siempre se conserva. Un archivo a 1000 fps aporta
muestras cada 1.0 ms; el estimador sub-frame puede devolver décimas, pero no se
presenta como exactitud física de 0.1 ms salvo que el timestamp visible o la tasa
nativa del archivo la sustenten.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Iterable

import cv2
import numpy as np

from configuracion import RAIZ_PROYECTO, cargar_config
from utilidades import firma_video
from utilidades.persistencia import escribir_json_seguro
from utilidades.evidencia_apertura import generar_candidatos
try:
    from utilidades.roi_deformacion import buscar_roi_deformacion, VERSION_ROI_DEFORMACION
except ImportError:
    buscar_roi_deformacion = None
    VERSION_ROI_DEFORMACION = 'no_disponible'
try:
    from utilidades.estandar_apertura import evaluar_evidencia_estandar, estimar_llenado_visual, analizar_secuencia_despliegue
except Exception:
    def evaluar_evidencia_estandar(candidato, verificacion=None, metrica=None, **kwargs):
        return {
            'nivel': 'baja', 'score_evidencia': 0.0, 'score_es_probabilidad': False,
            'auto_colorable': False, 'auto_publicable': False,
            'razones': [], 'riesgos': ['estandar_apertura_no_disponible'],
            'version_estandar': 'fallback-video_airbag',
        }
    def estimar_llenado_visual(metricas, frame_inicio, fps_captura, **kwargs):
        return {'estado': 'estandar_apertura_no_disponible', 'frame_llenado': None,
                'duracion_llenado_frames': None, 'duracion_llenado_ms': None}
    def analizar_secuencia_despliegue(metricas, frame_breakout, fps_captura, **kwargs):
        return {'estado': 'estandar_apertura_no_disponible', 'frame_breakout': frame_breakout,
                'frame_max_inflado': None, 'tiempo_breakout_ms': None,
                'tiempo_max_inflado_ms': None, 'duracion_expansion_ms': None,
                'anomalías': ['estandar_apertura_no_disponible']}
try:
    from utilidades.verificador_apertura import verificar_candidato
except Exception:
    def verificar_candidato(candidato, metricas, **kwargs):
        return {
            'estado_revision': 'no_evaluable',
            'razones_a_favor': [],
            'razones_en_contra': ['verificador_apertura_no_disponible'],
            'fotogramas_evidencia': [],
            'calidad_registro': 'desconocida',
            'es_independiente_del_detector': False,
            'auto_confirmable': False,
            'probabilidad_calibrada': None,
            'version_verificador': 'fallback-video_airbag',
        }
try:
    from utilidades.politica_apertura import decidir_apertura
except Exception:
    def decidir_apertura(**kwargs):
        candidato = kwargs.get('candidato') or {}
        tiempo = candidato.get('tiempo_local_ms') or candidato.get('tiempo_ms')
        return {
            'estado': 'no_evaluable',
            'tiempo_ms': None,
            'tiempo_propuesto_ms': tiempo,
            'motivos': ['politica_apertura_no_disponible'],
            'auto_confirmable': False,
            'probabilidad_calibrada': None,
            'version_politica': 'fallback-video_airbag',
        }

EXTENSIONES_VIDEO = {".avi", ".mp4", ".mov", ".mkv", ".wmv", ".m4v"}
CARPETAS_VIDEO = {"video", "videos"}
RUTA_CACHE = RAIZ_PROYECTO / ".cache_ocr" / "video_airbag.json"
RUTA_REVISIONES = RAIZ_PROYECTO / ".aprendizaje" / "revisiones_video.json"
ALGORITMO_VERSION = "v16.0.19-tres-eventos-camaras-especificas"
# V15.9.2 (C1): versión de la REGLA DE CONSOLIDACIÓN/CONFIRMACIÓN. Todo
# consenso calculado se sella con ella; un consenso persistido con un sello
# distinto (o sin sello, p.ej. legados 2/4 de V15.8.x) se reevalúa con la
# regla vigente antes de volver a publicarse, conservando el valor anterior
# como evidencia (video_apertura_anterior).
CONSENSO_ALGORITMO_VERSION = "consenso-v11-frontal-lateral-exclusivas"


def _cfg(config: dict | None = None) -> dict:
    config = config or cargar_config()
    base = {
        "activar": True,
        "leer_timestamp_overlay": True,
        # V15.1: se conserva más detalle para no perder el primer borde blanco
        # de la bolsa al reducir demasiado la imagen.
        "max_ancho_analisis": 960,
        # La reducción puede borrar el primer píxel. Los umbrales se aplican
        # sobre la ROI nativa; sólo el cálculo de flujo puede reducirse.
        "analisis_resolucion_nativa": True,
        "fraccion_superior_overlay": 0.18,
        "fraccion_inferior_overlay": 0.18,
        "margen_vertical_deteccion": 0.12,
        # La línea de tiempo de estos AVI puede indicar 8 fps de reproducción
        # aunque hayan sido grabados a 5000 fps. Por eso el baseline ya no se
        # dimensiona con CAP_PROP_FPS: debe ser corto y anterior al despliegue.
        # V15.7: con Rec5000 la bolsa aparece desde ~1.4 ms; un baseline de 8
        # cuadros (0-1.4 ms) la contaminaba y fijaba un suelo en el cuadro 8.
        "frames_baseline_min": 3,
        "frames_baseline_max": 6,
        "baseline_duracion_objetivo_ms": 0.6,
        # Tope duro cuando se conoce la tasa real: protege contra valores
        # antiguos de config.yaml (p.ej. frames_baseline_min: 8).
        "baseline_max_ms": 1.0,
        # V15.7: un tablero que se hincha se deforma y mueve sus brillos, pero
        # no aporta material nuevo. Se compensa ese movimiento con flujo óptico
        # y sólo cuenta como bolsa lo que el movimiento no explica.
        "compensar_movimiento": True,
        "residuo_min_compensado": 18,
        "flujo_ancho_max": 480,
        "flujo_max_px": 10.0,
        # R10: estándar geométrico-temporal reutilizable. Se localiza la deformación
        # mediante movimiento residual y se busca material nuevo alrededor.
        "estandar_apertura_activo": True,
        # V16.0.8: búsqueda temporal en toda la parte útil del fotograma,
        # ANTES de analizar la ROI final. Una ROI manual propia permanece fija.
        "roi_deformacion_activa": True,
        "roi_deformacion_ancho": 320,
        "roi_deformacion_max_frames": 240,
        "roi_deformacion_max_eventos": 12,
        "roi_deformacion_comparar_regiones": True,
        "roi_deformacion_ventana_secundaria": 750,

        "deformacion_movimiento_min_px": 0.35,
        "deformacion_mad_factor": 2.5,
        "deformacion_fraccion_min": 0.0005,
        "deformacion_fraccion_max": 0.45,
        "deformacion_max_componentes": 1,
        "deformacion_rel_area_min": 0.25,
        "margen_deformacion_norm": 0.06,
        "margen_deformacion_px_max": 36,
        "requerir_proximidad_deformacion_si_confiable": True,
        "auto_color_evidencia_min": 0.56,
        # R11: el primer indicio puede permanecer pequeño varios cuadros antes
        # de crecer. La corroboración puede mirar hacia delante sin mover el onset.
        "onset_corrobora_max_frames": 48,
        # R10: un solo video con evidencia fisica fuerte puede sostener color
        # estimado. El consenso multicamara sigue reservado para publicacion.
        "permitir_color_video_unico_defendible": True,
        # Medicion visual del llenado: desde onset hasta meseta visible.
        "medir_llenado_visual": True,
        "llenado_fraccion_objetivo": 0.90,
        "llenado_estabilidad_frames": 3,
        "llenado_tolerancia_rel": 0.18,
        "llenado_max_frames": 160,
        # R13: breakout y máximo visible son eventos separados. El máximo se
        # busca sobre área de bolsa estimada y una meseta cercana al pico.
        "maximo_inflado_fraccion": 0.97,
        "maximo_inflado_estabilidad_frames": 3,
        "maximo_inflado_caida_confirmacion": 0.04,
        "maximo_inflado_max_frames": 240,
        # V16.0.3: detector GLOBAL experimental, desacoplado del onset.
        # No sustituye automáticamente la medición histórica ni el semáforo.
        "maximo_global_habilitado": True,
        "maximo_global_ancho_max": 640,
        "maximo_global_max_frames": 800,
        "maximo_global_ventana_ms": 150.0,
        "maximo_global_umbral_cambio": 18,

        # Segmentación fotométrica amplia sólo para medir expansión/máximo; el
        # breakout sigue exigiendo discontinuidad, trayectoria y previos limpios.
        "umbral_luminancia_bolsa": 120,
        "umbral_incremento_bolsa": 12,
        "umbral_incremento_bolsa_max": 42,
        # Umbrales relativos al ruido medido en los cuadros del baseline.
        "ruido_factor_pixeles": 3.0,
        "ruido_margen_pixeles": 3,
        # Antes del primer cuadro con bolsa debe haber cuadros limpios.
        "frames_previos_limpios": 2,
        "detener_tras_confirmacion": True,
        "umbral_diff_min": 6.0,
        "persistencia_frames": 2,
        # Detector de "primer blanco nuevo". El evento se fija en el PRIMER
        # cuadro y los siguientes sólo sirven para confirmar que no fue ruido.
        "umbral_luminancia_blanco": 135,
        "umbral_incremento_blanco": 18,
        # Una costura también puede abrir como una fisura oscura antes de que
        # asome tela clara. Hace falta un contorno NUEVO, no sólo más brillo.
        "umbral_luminancia_grieta": 120,
        "umbral_discontinuidad_nueva": 6.0,
        "min_pixeles_indicio": 1,
        "radio_indicio_px": 3.0,
        "max_componentes_indicio": 64,
        # V15.7: mínimos absolutos más bajos (unos pocos píxeles) porque ahora
        # el ruido del video y la compensación de movimiento filtran lo falso.
        "min_fraccion_blanco_nuevo": 0.00001,
        "min_fraccion_componente_blanco": 0.000006,
        # V15.3: el primer indicio puede ser menor que el umbral normal. Sólo
        # se acepta si cuadros posteriores confirman crecimiento/persistencia.
        "evidencia_debil_factor": 0.45,
        "ventana_confirmacion_frames": 5,
        "min_frames_confirmacion": 2,
        "crecimiento_ratio_min": 1.8,
        "fuerte_multiplicador_componente": 2.2,
        "fuerte_multiplicador_pixeles": 1.7,
        "backtracking_max_frames": 7,
        "retroceso_hasta_indicio_continuo": True,
        "usar_perfil_evento_aprendido": True,
        "min_ejemplos_perfil_evento": 3,
        "rescate_cambio_general": False,
        "permitir_persistencia_sin_crecimiento": False,
        "tolerancia_consenso_ms": 0.15,
        "min_videos_consenso": 3,
        # V15.2: cuando el nombre no identifica la cámara, una referencia debe
        # superar este nivel de similitud para heredar su zona aprendida.
        "similitud_minima_zona": 0.34,
        "similitud_minima_zona_nombre": 0.18,
        # V15.4: tolerancia mínima para validar el reloj visible contra la
        # posición temporal del frame. Nunca se aceptan tiempos negativos.
        "timestamp_tolerancia_min_ms": 0.25,
        "timestamp_tolerancia_frames": 1.5,
    }
    base.update((config.get("video_airbag") or {}))
    return base


def descubrir_videos_caso(ruta_caso: str | Path) -> list[dict]:
    """Encuentra videos dentro de VIDEO/VIDEOS (sin importar mayúsculas)."""
    caso = Path(ruta_caso)
    carpetas = []
    try:
        carpetas = [p for p in caso.iterdir() if p.is_dir() and p.name.casefold() in CARPETAS_VIDEO]
    except OSError:
        return []
    salida = []
    for base in sorted(carpetas, key=lambda p: p.name.casefold()):
        for archivo in sorted(base.rglob("*")):
            if not archivo.is_file() or archivo.suffix.lower() not in EXTENSIONES_VIDEO:
                continue
            salida.append({
                "ruta": str(archivo.resolve()),
                "ruta_relativa": archivo.relative_to(caso).as_posix(),
                "nombre": archivo.name,
                "carpeta_video": base.name,
            })
    return salida


def _firma(ruta: str | Path) -> str:
    """Firma por contenido: no cambia al copiar o mover la carpeta del lote."""
    return firma_video.firma_contenido(ruta)


def _leer_json(ruta: Path, defecto):
    try:
        if ruta.is_file():
            data = json.loads(ruta.read_text(encoding="utf-8"))
            return data
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return defecto


def _guardar_json(ruta: Path, data) -> None:
    escribir_json_seguro(ruta, data, lanzar=False, compacto=True)


class ErrorPersistenciaRevisiones(RuntimeError):
    """R15 (ALTA-04): el registro durable de revisiones no se guardó.

    La revisión manual de video NUNCA debe reportarse como guardada si su
    archivo durable no quedó escrito y verificado: un procesamiento futuro
    reconstruye el video desde ese registro y la confirmación humana
    desaparecería. Misma política que ErrorPersistenciaAprendizaje.
    """


def _guardar_json_verificado(ruta: Path, data) -> None:
    """Escribe y VERIFICA el resultado; lanza si no se persistió.

    Para almacenes durables (registro de revisiones). Los caches siguen
    usando ``_guardar_json`` tolerante: perder un cache no pierde datos
    humanos ni debe romper una operación válida.
    """
    resultado = escribir_json_seguro(ruta, data, lanzar=False, compacto=True)
    if not getattr(resultado, "guardado", False):
        error = getattr(resultado, "error", None) or "escritura no verificada"
        raise ErrorPersistenciaRevisiones(
            f"No se pudo guardar {ruta.name}: {error}")


def cargar_revisiones() -> dict:
    data = _leer_json(RUTA_REVISIONES, {"version": 1, "revisiones": {}})
    if not isinstance(data, dict) or not isinstance(data.get("revisiones"), dict):
        return {"version": 1, "revisiones": {}}
    return data


def restaurar_revisiones(snapshot: dict) -> None:
    """R15.4 (HIGH-01): restaura fielmente el registro durable de revisiones.

    Compensación cuando el commit del documento de resultados falla después
    de ``guardar_revision_video``: la revisión durable no puede sobrevivir a
    una petición que no llegó al documento. ``snapshot`` es el valor devuelto
    por ``cargar_revisiones()`` ANTES del efecto. Escritura verificada: si la
    restauración no se persiste, lanza ``ErrorPersistenciaRevisiones``.
    """
    _guardar_json_verificado(RUTA_REVISIONES, snapshot)


def guardar_revision_video(ruta_video: str | Path, *, case_key: str | None,
                           frame_index: int | None, tiempo_ms: float | None,
                           estado: str = "confirmado", usuario: str = "dashboard",
                           comentario: str | None = None, fuente_tiempo: str | None = None,
                           referencia_tiempo_valida: bool | None = None,
                           evento_censurado: bool = False,
                           tiempo_overlay_leido_ms: float | None = None,
                           tiempo_overlay_validado_ms: float | None = None,
                           tiempo_fps_ms: float | None = None,
                           discrepancia_tiempo_ms: float | None = None,
                           advertencia_tiempo: str | None = None) -> dict:
    if estado not in {"confirmado", "sin_evento", "pendiente"}:
        raise ValueError("Estado de revisión de video inválido.")
    valor_tiempo = _numero_finito_con_signo(tiempo_ms)
    if estado == "confirmado":
        if evento_censurado:
            raise ValueError("El evento está censurado al inicio del clip; falta evidencia previa del nacimiento.")
        if valor_tiempo is None or valor_tiempo <= 0:
            raise ValueError("El tiempo final de apertura confirmado debe ser finito y > 0 ms.")
        if frame_index is None or int(frame_index) < 0:
            raise ValueError("Una apertura confirmada requiere frame_index válido.")
        if referencia_tiempo_valida is not True:
            raise ValueError("La referencia temporal no está validada; la revisión no puede publicarse.")
    if frame_index is not None and int(frame_index) < 0:
        raise ValueError("frame_index no puede ser negativo.")
    ident = firma_video.identidad(ruta_video)
    firma = ident["firma"]
    data = cargar_revisiones()
    anteriores = [v for v in data["revisiones"].values() if firma_video.coincide(v, ident)]
    historial = []
    for previa in anteriores:
        historial.extend(list(previa.get("historial") or []))
        historial.append({k: v for k, v in previa.items() if k != "historial"})
    # Sustituye la revisión activa del mismo video, pero conserva cada valor
    # crudo histórico y su procedencia en el historial.
    data["revisiones"] = {k: v for k, v in data["revisiones"].items()
                          if not firma_video.coincide(v, ident)}
    revision = {
        "firma": firma, "firma_legacy": ident["firma_legacy"], "tamano": ident["tamano"],
        "ruta_video": str(Path(ruta_video).resolve()),
        "case_key": case_key, "frame_index": None if frame_index is None else int(frame_index),
        "tiempo_ms": None if tiempo_ms is None else round(float(valor_tiempo), 3),
        "raw_time_ms": tiempo_ms,
        "fuente_tiempo": fuente_tiempo,
        "referencia_tiempo_valida": referencia_tiempo_valida,
        "tiempo_overlay_leido_ms": _numero_finito_con_signo(tiempo_overlay_leido_ms),
        "tiempo_overlay_validado_ms": _numero_finito_con_signo(tiempo_overlay_validado_ms),
        "tiempo_fps_ms": _numero_no_negativo(tiempo_fps_ms),
        "discrepancia_tiempo_ms": _numero_finito_con_signo(discrepancia_tiempo_ms),
        "advertencia_tiempo": advertencia_tiempo,
        "estado_tiempo": "VALIDO" if estado == "confirmado" else "NO_CONFIRMADO",
        "estado": estado, "usuario": usuario, "comentario": comentario or "",
        "historial": historial,
    }
    from datetime import datetime
    revision["confirmado_en"] = datetime.now().isoformat(timespec="seconds")
    data["revisiones"][firma] = revision
    # R15 (ALTA-04): escritura VERIFICADA del almacén durable. Si falla, se
    # lanza ErrorPersistenciaRevisiones y el endpoint no puede declarar éxito.
    _guardar_json_verificado(RUTA_REVISIONES, data)
    return revision


def revision_video(ruta_video: str | Path) -> dict | None:
    try:
        ident = firma_video.identidad(ruta_video)
    except OSError:
        return None
    revisiones = cargar_revisiones().get("revisiones", {})
    directa = revisiones.get(ident["firma"]) or revisiones.get(ident["firma_legacy"])
    if directa:
        return directa
    # Revisión guardada antes de mover/copiar la carpeta del lote.
    return firma_video.buscar(revisiones.values(), ident)


def _redimensionar_gris(frame: np.ndarray, max_ancho: int) -> np.ndarray:
    gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    h, w = gris.shape[:2]
    if w > max_ancho:
        escala = max_ancho / float(w)
        gris = cv2.resize(gris, (max_ancho, max(1, int(round(h * escala)))), interpolation=cv2.INTER_AREA)
    return gris


def _roi_deteccion(gris: np.ndarray, margen_vertical: float) -> np.ndarray:
    h, w = gris.shape[:2]
    y1 = max(0, min(h - 1, int(round(h * margen_vertical))))
    y2 = max(y1 + 1, min(h, int(round(h * (1.0 - margen_vertical)))))
    # También se descarta un margen lateral pequeño donde suelen vivir overlays/bordes.
    x1 = max(0, int(round(w * 0.04)))
    x2 = max(x1 + 1, min(w, int(round(w * 0.96))))
    return gris[y1:y2, x1:x2]


def _seleccionar_roi_deformacion(zona: dict | None, propuesta: dict | None) -> dict:
    """Da prioridad absoluta a una ROI humana propia; adapta herencias fiables.

    Una deformación no demuestra ruptura: se usa sólo para acotar la inspección.
    No se escribe la ROI de aprendizaje ni se invalidan anotaciones humanas.
    """
    actual=dict(zona or {})
    if not isinstance(propuesta,dict):
        return actual
    actual['diagnostico_roi_deformacion'] = propuesta
    box=propuesta.get('bbox_norm')
    if not propuesta.get('confiable') or not isinstance(box,list) or len(box)!=4:
        return actual
    try:
        vals=[float(v) for v in box]
        xx,yy,x2,y2=vals
        if not (0<=xx<x2<=1 and 0<=yy<y2<=1):return actual
        area=(x2-xx)*(y2-yy)
        if not (.0015<=area<=.56):return actual
    except (ValueError,TypeError,OverflowError):
        return actual
    fuente=str(actual.get('fuente') or '')
    # Incluso ante desacuerdo, respetar lo que dibujó el usuario en ESTE vídeo.
    if fuente.startswith('manual_bloqueada'):
        actual['bbox_sugerida_norm']=list(box)
        actual['motivo_sugerencia']='deformacion_temporal_sin_anular_roi_manual'
        return actual
    anterior=actual.get('bbox_norm') if actual.get('activa') else None
    if isinstance(anterior,(list,tuple)) and len(anterior)==4:
        actual['bbox_original_norm']=list(anterior)
    actual.update({'activa':True,'bloqueada':False,'bbox_norm':list(box),
                   'fuente':'deformacion_temporal_auto',
                   'confianza':float(propuesta.get('confianza') or 0),
                   'frame_deformacion':propuesta.get('frame_indicio'),
                   'frames_soporte_deformacion':propuesta.get('frames_soporte') or [],
                   'porcentajes':{'x':round(xx*100,1),'y':round(yy*100,1),
                                  'w':round((x2-xx)*100,1), 'h':round((y2-yy)*100,1)},
                   'autoalineacion_activa':True,
                   'bbox_sugerida_norm':None})
    return actual




def _evidencia_fisica_temporal(metricas: list[dict], frame: int, radio: int = 3) -> dict:
    """La evidencia del primer cuadro debe EXISTIR en ese cuadro.

    Los cuadros siguientes sólo corroboran lo ya visible; jamás convierten
    un instante anterior sin material en ruptura fuerte. La continuidad
    exige contornos cercanos, no dos reflejos en partes distintas de la ROI.
    """
    vacio = {"nivel": "ninguna", "cuadros_fisicos": [],
             "cuadros_debiles": [], "cuadros_detectados": [],
             "continuidad_espacial": False, "primer_cuadro_fisico": None}
    if not isinstance(frame, int) or not isinstance(metricas, list) or not (0 <= frame < len(metricas)):
        return vacio
    fin = min(len(metricas), frame + max(1, min(int(radio), 8)) + 1)
    vec = list(range(frame, fin))
    fisicos, debiles, detectados = [], [], []
    for j in vec:
        m = metricas[j] if isinstance(metricas[j],dict) else {}
        material = (int(m.get('pixeles_ruptura') or 0)>0 or
                    int(m.get('pixeles_grieta_nueva') or 0)>0 or
                    int(m.get('componente_ruptura_px') or 0)>0)
        if material: fisicos.append(j)
        if material or m.get('evidencia_debil'): debiles.append(j)
        if material and m.get('detectado'): detectados.append(j)
    salida = {"nivel":"ninguna", "cuadros_fisicos":fisicos,
              "cuadros_debiles":debiles, "cuadros_detectados":detectados,
              "continuidad_espacial":False,
              "primer_cuadro_fisico":fisicos[0] if fisicos else None}
    # Un pixel de fondo que apareció en el futuro no existe aún en 'frame'.
    if frame not in fisicos:
        return salida
    def proximo(a, b):
        ma = metricas[a] if isinstance(metricas[a],dict) else {}
        mb = metricas[b] if isinstance(metricas[b],dict) else {}
        ca = ma.get('bbox_componente_norm')
        cb = mb.get('bbox_componente_norm')
        if not (isinstance(ca,(list,tuple)) and isinstance(cb,(list,tuple))
                and len(ca)==4 and len(cb)==4):
            return False  # Sin posición no hay prueba de continuidad espacial.
        try:
            A=[float(x) for x in ca]; B=[float(x) for x in cb]
            if not all(math.isfinite(x) and 0<=x<=1 for x in A+B):return False
            if A[0]>=A[2] or A[1]>=A[3] or B[0]>=B[2] or B[1]>=B[3]:return False
            # Se tolera crecimiento considerable de bolsa sin validar contornos
            # físicamente inconexos. Distancia en coordenadas normalizadas ROI.
            dx=max(A[0]-B[2],B[0]-A[2],0)
            dy=max(A[1]-B[3],B[1]-A[3],0)
            return dx*dx+dy*dy <= 0.10**2
        except (TypeError,ValueError,OverflowError):return False
    # Hasta un cuadro intermedio puede estar ocluido, pero la confirmación
    # fuerte exige persistencia espacial del MISMO material próximo al onset.
    apoyo = next((j for j in fisicos[1:] if j-frame<=2 and proximo(frame,j)), None)
    if apoyo is not None:
        salida['continuidad_espacial'] = True
        # Dos pixels quietos, aunque algún detector secundario haya marcado
        # 'detectado', no justifican evidencia FUERTE. El primer pixel sí se
        # conserva cuando en los cuadros siguientes aparece material más claro.
        m0 = metricas[frame] if isinstance(metricas[frame], dict) else {}
        m1 = metricas[apoyo] if isinstance(metricas[apoyo], dict) else {}
        n0 = max(0, int(m0.get('pixeles_ruptura') or m0.get('componente_ruptura_px') or 0))
        n1 = max(0, int(m1.get('pixeles_ruptura') or m1.get('componente_ruptura_px') or 0))
        deteccion = frame in detectados or apoyo in detectados
        salida['nivel'] = ('fuerte' if deteccion and max(n0,n1) >= 3
                           else 'compatible')
    else:
        salida['nivel'] = 'debil'
    return salida



def _arbitrar_onset_fisico_1615(metricas: list[dict], global_frame: int,
                                anterior_frame: int | None, *,
                                max_distancia_frames: int = 40) -> dict:
    """Compara el comienzo GLOBAL y LOCAL, sin adoptar la primera mancha.

    Los cuadros siguientes SOLO corroboran material presente en el cuadro
    elegido. No adelanta un tiempo usando material que nace en otro cuadro.
    Si el detector global llega tarde, una cadena de evidencia local
    temprana (misma ROI, persistencia y crecimiento) puede rescatar el onset.
    Nunca interpola tiempo subframe ni deduce apertura a partir de brillo solo.
    """
    if not isinstance(global_frame, int) or global_frame < 1 or global_frame >= len(metricas):
        return {"frame": global_frame, "accion": "global_fuera_de_rango", "alerta": True}

    def fuerte(o):
        return o.get("nivel") in {"fuerte", "compatible"} and o.get("continuidad_espacial") is True

    def carga(frame):
        if not isinstance(frame, int) or not 0 < frame < len(metricas):
            return {"nivel": "ninguna", "continuidad_espacial": False}
        return _evidencia_fisica_temporal(metricas, frame, 4)

    evidencia_global = carga(global_frame)
    previo_valido = (isinstance(anterior_frame, int) and
                    0 < anterior_frame < len(metricas) and
                    abs(global_frame - anterior_frame) <= max_distancia_frames)
    evidencia_previa = carga(anterior_frame) if previo_valido else {"nivel": "ninguna"}
    datos = {"frame": global_frame, "accion": "conservar_global",
             "global_frame": global_frame, "anterior_frame": anterior_frame,
             "nivel_global": evidencia_global.get("nivel"),
             "nivel_anterior": evidencia_previa.get("nivel"),
             "discrepancia_frames": (global_frame - anterior_frame if previo_valido else None),
             "alerta": False}

    def cadena_temprana(frame):
        # Requiere que antes no hubiera material y que despues de ese
        # primer cuadro haya continuidad/growth. Un hot-pixel fijo no basta.
        if frame < 2:
            return False
        anterior = metricas[frame-1] if isinstance(metricas[frame-1], dict) else {}
        if (int(anterior.get("pixeles_ruptura") or 0) > 0 or
            int(anterior.get("componente_ruptura_px") or 0) > 0):
            # Podria haber nacido antes: no marcar arbitrariamente aqui.
            return False
        inicio = metricas[frame] if isinstance(metricas[frame], dict) else {}
        n0 = int(inicio.get("componente_ruptura_px") or inicio.get("pixeles_ruptura") or 0)
        if n0 <= 0:
            return False
        # Rechazar destello declarado y manchas minimas estaticas.
        if float((inicio.get("scores_fuentes") or {}).get("iluminacion_global") or 0) >= 0.60:
            return False
        # Al menos dos apoyos de la misma zona dentro de 6 cuadros; uno
        # muestra crecimiento, evitando que un punto quieto sea ruptura.
        n_apoyos = 0
        crecimiento = False
        for j in range(frame+1, min(len(metricas), frame+7)):
            e = carga(j)
            m = metricas[j] if isinstance(metricas[j], dict) else {}
            n = int(m.get("componente_ruptura_px") or m.get("pixeles_ruptura") or 0)
            if e.get("nivel") in {"fuerte", "compatible"} and n > 0:
                # Cada apoyo tiene al menos continuidad espacial consigo mismo
                # y la trayectoria cercana al primer indicio.
                if _bbox_proximos_1615(inicio.get("bbox_componente_norm"),
                                       m.get("bbox_componente_norm")):
                    n_apoyos += 1
                    crecimiento |= n >= max(3, n0 + 2)
        return n_apoyos >= 2 and crecimiento

    if previo_valido and anterior_frame < global_frame and fuerte(evidencia_previa) and cadena_temprana(anterior_frame):
        datos.update({"frame": anterior_frame,
                      "accion": "rescate_onset_local_temprano_corrobora_material"})
    elif previo_valido and anterior_frame > global_frame and not fuerte(evidencia_global) \
            and fuerte(evidencia_previa):
        datos.update({"frame": anterior_frame,
                      "accion": "global_adelantado_sin_evidencia_local"})
    elif previo_valido and abs(anterior_frame - global_frame) >= 5 and \
            not fuerte(evidencia_global) and not fuerte(evidencia_previa):
        datos.update({"accion": "discrepancia_no_resuelta", "alerta": True})
    return datos


def _bbox_proximos_1615(a, b):
    if not (isinstance(a, (list,tuple)) and isinstance(b, (list,tuple))
            and len(a) == 4 and len(b) == 4):
        return False
    try:
        a, b = [float(x) for x in a], [float(x) for x in b]
        if not all(math.isfinite(x) and 0 <= x <= 1 for x in a+b):
            return False
        if a[0] >= a[2] or a[1] >= a[3] or b[0] >= b[2] or b[1] >= b[3]:
            return False
        dx = max(a[0]-b[2], b[0]-a[2], 0)
        dy = max(a[1]-b[3], b[1]-a[3], 0)
        return dx*dx + dy*dy <= 0.10**2
    except (TypeError, ValueError, OverflowError):
        return False




def _buscar_inicio_fisico_retrospectivo_1616(metricas: list[dict], global_frame: int,
                                            fps_captura: float | None = None,
                                            ventana_ms: float = 8.0) -> dict:
    """Busca el primer trazo realmente presente que precede a un onset tardío.

    Los fotogramas FUTUROS confirman persistencia, no dan evidencia a cuadros
    vacíos. El límite se expresa en ms de grabación (no fps del contenedor),
    para vídeos nuevos de frecuencias distintas. Si la traza no se sostiene,
    no se modifica la decisión anterior. Sólo trabaja sobre métricas de la
    misma ROI, nunca confunde coordenadas de ROI distintas.
    """
    salida = {'frame': None, 'decision': 'sin_rescate', 'evaluados': 0,
              'ventana_frames': 0, 'candidatos_rechazados': 0}
    if not isinstance(metricas, list) or not isinstance(global_frame, int) \
            or not (2 < global_frame < len(metricas)):
        return salida
    try:
        fps = float(fps_captura)
    except (TypeError, ValueError, OverflowError):
        fps = 0.0
    if not math.isfinite(fps) or fps <= 0:
        salida['decision'] = 'fps_grabacion_no_verificado'
        return salida
    try:
        ventana_ms = float(ventana_ms)
    except (ValueError, TypeError, OverflowError):
        ventana_ms = 8.0
    if not math.isfinite(ventana_ms):
        ventana_ms = 8.0
    ventana_ms = max(.2, min(20.0, ventana_ms))
    ventana_frames = min(160, max(1, int(round(fps * ventana_ms / 1000.0))))
    salida['ventana_frames'] = ventana_frames
    inicio = max(2, global_frame - ventana_frames)
    # Se busca desde el PRIMER indicio, no desde el pico de amplitud.
    for j in range(inicio, global_frame):
        salida['evaluados'] += 1
        m = metricas[j] if isinstance(metricas[j], dict) else {}
        n0 = max(0, int(m.get('componente_ruptura_px') or m.get('pixeles_ruptura') or 0))
        if n0 <= 0 or float((m.get('scores_fuentes') or {}).get('iluminacion_global') or 0) >= .60:
            continue
        previos = metricas[max(0, j-2):j]
        if any(isinstance(t,dict) and (int(t.get('componente_ruptura_px') or t.get('pixeles_ruptura') or 0) > 0) for t in previos):
            continue
        bbox = m.get('bbox_componente_norm')
        soporte = []
        crecimientos = 0
        for k in range(j+1, min(len(metricas), j+9)):
            mk = metricas[k] if isinstance(metricas[k], dict) else {}
            nk = max(0, int(mk.get('componente_ruptura_px') or mk.get('pixeles_ruptura') or 0))
            if nk <= 0 or not _bbox_proximos_1615(bbox, mk.get('bbox_componente_norm')):
                continue
            if float((mk.get('scores_fuentes') or {}).get('iluminacion_global') or 0) >= .60:
                continue
            soporte.append(k)
            if nk >= max(3, n0+2):
                crecimientos += 1
        ev = _evidencia_fisica_temporal(metricas, j, 4)
        # Un unico pico de area puede ser un destello, incluso si un pixel
        # estuvo quieto en la misma ROI. Exigir crecimiento sostenido.
        if len(soporte) < 2 or crecimientos < 2 or ev.get('nivel') not in {'fuerte','compatible'}:
            salida['candidatos_rechazados'] += 1
            continue
        # Si ambas métricas poseen contorno, comprobar que se sigue la MISMA
        # región. Si el pico llega >8 frames después puede expandirse mucho;
        # se exige continuidad temprana y la unión con un fotograma más tardío.
        mg = metricas[global_frame] if isinstance(metricas[global_frame],dict) else {}
        bglobal = mg.get('bbox_componente_norm')
        # Un evento lejano no puede secuestrar otra ROI si faltan coordenadas.
        if global_frame - j > 6 and not (isinstance(bglobal, (tuple,list)) and len(bglobal)==4):
            salida['candidatos_rechazados'] += 1
            continue
        if isinstance(bglobal, (list,tuple)) and isinstance(bbox,(list,tuple)) and len(bglobal)==4:
            if not (_bbox_proximos_1615(bbox,bglobal) or
                    any(_bbox_proximos_1615(metricas[k].get('bbox_componente_norm'),bglobal)
                        for k in soporte if k < len(metricas))):
                salida['candidatos_rechazados'] += 1
                continue
        salida.update({'frame':j, 'decision':'primer_material_persistente_con_crecimiento',
                       'soporte_frames': soporte, 'nivel':ev['nivel'],
                       'diferencia_frames':global_frame-j})
        return salida
    return salida


def _analizar_roi_secundaria(ruta: Path, zona: dict, cfg: dict,
                              nbase: int, margen: float, max_ancho: int,
                              ventana_confirmacion: int, tope_frames: int):
    """Prueba la ROI de deformación sin reemplazar la detección histórica.

    Solo se adopta si hay ruptura local en varios cuadros, un inicio confirmado
    por el motor original, y una referencia limpia antes del evento.
    Nunca se acepta el cuadro que solo exhibe deformación de fondo.
    """
    cap = cv2.VideoCapture(str(ruta))
    if not cap.isOpened():
        return {"aceptada": False, "motivo": "video_no_disponible"}
    frames_base, scores, metricas = [], [], []
    baseline, ruido, umbral = None, {}, float(cfg.get("umbral_diff_min", 6.0))
    try:
        for i in range(max(nbase + ventana_confirmacion + 1, min(2500, int(tope_frames)))):
            ok, frame = cap.read()
            if not ok:
                break
            gris = _redimensionar_gris(
                frame, max(frame.shape[1], int(max_ancho))
                if cfg.get("analisis_resolucion_nativa", True) else max_ancho)
            roi = _roi_deteccion_aprendida(gris, zona, margen)
            if i < nbase:
                frames_base.append(roi.astype(np.float32))
                scores.append(0.0)
                metricas.append({"detectado": False, "evidencia_debil": False,
                                 "pixeles_ruptura": 0})
                continue
            if baseline is None:
                if len(frames_base) < 2:
                    return {"aceptada": False, "motivo": "referencia_insuficiente"}
                baseline = np.median(np.stack(frames_base), axis=0).astype(np.uint8)
                ruido = _ruido_baseline(frames_base, cfg)
                umbral = max(umbral, 2.0 * float(ruido.get("score_max") or 0.0))
            diff = cv2.absdiff(roi, baseline)
            delta = cv2.subtract(roi, baseline)
            scores.append(float(np.mean(diff)) + 70.0*float(np.mean(delta > 28)))
            metricas.append(_metricas_primer_blanco(roi, baseline, cfg, ruido))
        if len(metricas) <= nbase + ventana_confirmacion:
            return {"aceptada": False, "motivo": "ventana_corta"}
        confirmado = _buscar_inicio_confirmado(metricas, scores, umbral, nbase, cfg)
        if not isinstance(confirmado, dict):
            return {"aceptada": False, "motivo": "sin_apertura_confirmada"}
        inicio = confirmado.get("frame_inicio")
        if not isinstance(inicio, int) or inicio < nbase:
            return {"aceptada": False, "motivo": "inicio_invalido"}
        # Fisura/material nuevo detectables en dos cuadros cercanos.
        evidencia = [j for j in range(max(nbase, inicio-1), min(len(metricas), inicio+5))
                     if (metricas[j].get("detectado") or
                         int(metricas[j].get("pixeles_ruptura") or 0) > 0 or
                         int(metricas[j].get("pixeles_grieta_nueva") or 0) > 0)]
        validacion = _evidencia_fisica_temporal(metricas, inicio, 4)
        if validacion["nivel"] not in {"fuerte", "compatible"}:
            return {"aceptada": False, "motivo": "sin_ruptura_temporal_defendible",
                    "frame_candidato": inicio, "evidencia_fisica": validacion}
        return {"aceptada": True, "motivo": "inicio_fisico_confirmado_en_roi_alternativa",
                "frame_candidato": inicio, "frames_soporte": evidencia,
                "evidencia_fisica": validacion,
                "scores": scores, "metricas": metricas, "baseline_frames": frames_base,
                "ruido": ruido, "umbral": umbral, "confirmacion": confirmado}
    finally:
        cap.release()


def _rescate_indicios_roi_general(ruta: Path, frame_objetivo: int, nbase: int,
                                   cfg: dict, margen: float, max_ancho: int):
    """Segunda lectura acotada si la ROI dinamica no ve ruptura local.

    Jamás convierte deformacion o brillo en tiempo: sólo devuelve las métricas
    de fisura/material nuevo del detector original, en una ROI general amplia.
    """
    if frame_objetivo < nbase or frame_objetivo > 2500:
        return {}
    cap=cv2.VideoCapture(str(ruta))
    if not cap.isOpened():return {}
    try:
        refs=[];r={};baseline=None;noise={}
        for i in range(frame_objetivo+5):
            ok,f=cap.read()
            if not ok:break
            g=_redimensionar_gris(f,max(f.shape[1],max_ancho)
                                  if cfg.get('analisis_resolucion_nativa',True) else max_ancho)
            roi=_roi_deteccion(g,margen)
            if i<nbase:
                refs.append(roi.astype(np.float32))
                continue
            if i<max(nbase,frame_objetivo-2):continue
            if baseline is None:
                if len(refs)<2:return {}
                baseline=np.median(np.stack(refs),axis=0).astype(np.uint8)
                noise=_ruido_baseline(refs,cfg)
            r[i]=_metricas_primer_blanco(roi,baseline,cfg,noise)
        return r
    finally:
        cap.release()


def _roi_deteccion_aprendida(gris: np.ndarray, zona: dict | None, margen_vertical: float) -> np.ndarray:
    """Recorta la zona supervisada; si no existe, conserva el ROI general V15.1."""
    bbox = (zona or {}).get("bbox_norm") if (zona or {}).get("activa") else None
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return _roi_deteccion(gris, margen_vertical)
    h, w = gris.shape[:2]
    try:
        x1n, y1n, x2n, y2n = [float(v) for v in bbox]
    except (TypeError, ValueError):
        return _roi_deteccion(gris, margen_vertical)
    x1 = max(0, min(w - 1, int(round(x1n * w))))
    y1 = max(0, min(h - 1, int(round(y1n * h))))
    x2 = max(x1 + 1, min(w, int(round(x2n * w))))
    y2 = max(y1 + 1, min(h, int(round(y2n * h))))
    # Un ROI degenerado no debe romper el análisis automático.
    if (x2 - x1) < 3 or (y2 - y1) < 3:
        return _roi_deteccion(gris, margen_vertical)
    return gris[y1:y2, x1:x2]


def _parsear_timestamp_ms(textos: Iterable[str]) -> list[float]:
    valores: list[float] = []
    for texto in textos:
        t = str(texto or "").replace(",", ".")
        # Prioridad a valores explícitamente etiquetados como ms.
        for m in re.finditer(r"(?<!\d)(-?\d{1,5}(?:\.\d{1,3})?)\s*ms\b", t, re.IGNORECASE):
            try:
                valores.append(float(m.group(1)))
            except ValueError:
                pass
        # Formatos tipo t=6.3 sin unidad, sólo si existe una etiqueta temporal.
        for m in re.finditer(r"(?:\bt\b|time|zeit)\s*[:=]\s*(-?\d{1,5}(?:\.\d{1,3})?)", t, re.IGNORECASE):
            try:
                v = float(m.group(1))
            except ValueError:
                continue
            if v not in valores:
                valores.append(v)
    return valores


def _parsear_fps_grabacion(textos: Iterable[str]) -> list[float]:
    """Extrae la tasa REAL de grabación impresa por la cámara.

    Los AVI EDAG de alta velocidad pueden declarar 8 fps como velocidad de
    reproducción, mientras el overlay contiene por ejemplo ``Rec5000 fps``.
    Esa segunda tasa es la que define la separación temporal entre cuadros.
    """
    valores: list[float] = []
    for texto in textos:
        t = str(texto or "").replace(",", ".")
        patrones = (
            # OCR puede confundir 0/O y 1/I/l en la franja inferior. Sólo
            # normalizamos esos caracteres cuando están inmediatamente detrás
            # de Rec/Recording/Capture y delante de "fps".
            r"\bRec\s*[:=]?\s*([0-9OoIl]{2,6}(?:[\.,][0-9OoIl]+)?)\s*fps\b",
            r"\b(?:record(?:ing|ed)?|capture)\s*[:=]?\s*([0-9OoIl]{2,6}(?:[\.,][0-9OoIl]+)?)\s*fps\b",
        )
        for patron in patrones:
            for m in re.finditer(patron, t, re.IGNORECASE):
                bruto = (m.group(1).replace("O", "0").replace("o", "0")
                         .replace("I", "1").replace("l", "1").replace(",", "."))
                try:
                    v = float(bruto)
                except ValueError:
                    continue
                if 1.0 <= v <= 1_000_000 and v not in valores:
                    valores.append(v)
    return valores



TASAS_ESTANDAR_FPS = (250, 500, 1000, 1500, 2000, 2500, 3000, 4000, 5000, 6000, 7500,
                      8000, 10000, 12500, 15000, 20000, 25000, 30000, 40000, 50000, 100000)


def validar_fps_con_reloj(fps_rec: float | None, frame_index: int,
                          reloj_frame_ms: float | None, reloj_inicial_ms: float | None,
                          leer_reloj=None, total_frames: int | None = None,
                          tolerancia: float = 0.2) -> dict:
    """Contrasta Rec…fps con el avance del reloj visible.

    El reloj avanza ``1000 / fps`` ms por cuadro. Si ``Rec5000 fps`` se leyó
    mal (p.ej. ``Rec500``) el tiempo saldría 10 veces mayor. Con el reloj del
    cuadro 0 y del cuadro del evento se calcula la tasa implícita. Como una de
    las dos lecturas puede ser la equivocada, sólo se corrige la tasa si un
    tercer cuadro (``leer_reloj``) confirma al reloj y la tasa resultante es una
    tasa estándar de cámara. Si no hay confirmación, sólo se avisa.
    """
    rec = _numero_no_negativo(fps_rec)
    t1 = _numero_finito_con_signo(reloj_frame_ms)
    t0 = _numero_finito_con_signo(reloj_inicial_ms)
    salida = {"fps": rec, "fps_reloj": None, "fps_reloj_control": None,
              "corregido": False, "advertencia": None}
    if t1 is None or t0 is None or frame_index < 4 or t1 - t0 <= 0:
        return salida
    implicita = 1000.0 * frame_index / (t1 - t0)
    salida["fps_reloj"] = round(implicita, 3)
    if rec and abs(rec - implicita) / implicita <= tolerancia:
        return salida  # Rec…fps y reloj coinciden.

    confirma = None
    if leer_reloj is not None:
        f2 = frame_index + max(10, frame_index)
        if total_frames:
            f2 = min(f2, int(total_frames) - 1)
        if f2 > frame_index:
            try:
                t2 = _numero_finito_con_signo(leer_reloj(f2))
            except Exception:
                t2 = None
            if t2 is not None and t2 > t0:
                control = 1000.0 * f2 / (t2 - t0)
                salida["fps_reloj_control"] = round(control, 3)
                if abs(control - implicita) / implicita <= 0.1:
                    confirma = "reloj"
                elif rec and abs(control - rec) / rec <= tolerancia:
                    confirma = "rec"
    estandar = min(TASAS_ESTANDAR_FPS, key=lambda x: abs(x - implicita))
    if confirma == "reloj" and abs(estandar - implicita) / estandar <= 0.08:
        salida.update(fps=float(estandar), corregido=True, advertencia=(
            f"La tasa leída ({rec:g} fps) no coincide con el avance del reloj en dos "
            f"cuadros ({implicita:.0f} fps); se usa {estandar} fps." if rec else
            f"No se leyó Rec…fps; el avance del reloj en dos cuadros indica {estandar} fps."))
    elif confirma == "rec":
        salida["advertencia"] = ("El reloj del cuadro del evento no cuadra con Rec…fps ni con "
                                 "otro cuadro; se mantiene la tasa leída.")
    elif rec:
        salida["advertencia"] = (
            f"La tasa leída ({rec:g} fps) no coincide con el avance del reloj "
            f"({implicita:.0f} fps). Revisa este video.")
    return salida


def fps_grabacion_desde_item(item: dict | None) -> float | None:
    """Obtiene la tasa REAL de grabación de un resultado de video.

    V15.6 da prioridad al texto del overlay (``Rec5000 fps``) frente a
    ``CAP_PROP_FPS``. Esto repara también resultados antiguos guardados cuando
    OpenCV sólo reportó 8 fps de reproducción.
    """
    item = item or {}
    # V15.7.1: tasa ya contrastada con el reloj del propio video; tiene
    # prioridad sobre un "Rec…fps" mal leído en el texto del overlay.
    validado = _numero_no_negativo(item.get("fps_validado_reloj"))
    if validado and validado > 0:
        return float(validado)
    textos = [
        item.get("overlay_texto"), item.get("overlay_texto_esquina"),
        item.get("texto_overlay"), item.get("texto"),
    ]
    valores = _parsear_fps_grabacion([str(x) for x in textos if x])
    if valores:
        return float(valores[0])
    valor = _numero_no_negativo(item.get("fps_grabacion"))
    if valor and valor > 0:
        return float(valor)
    if str(item.get("fps_fuente") or "") == "overlay_rec":
        valor = _numero_no_negativo(item.get("fps"))
        if valor and valor > 0:
            return float(valor)
    return None

def _parsear_numero_timestamp_esquina(textos: Iterable[str]) -> tuple[float | None, float | None]:
    """Lee un timestamp numérico aislado, como ``2.2`` o ``4.4``.

    Se usa EXCLUSIVAMENTE con el recorte pequeño de la esquina superior
    derecha, donde los videos del banco muestran el reloj en milisegundos.
    Así evitamos confundirlo con IDs, fechas o con el ``0ms`` fijo del pie.
    """
    candidatos: list[tuple[float, int]] = []
    for texto in textos:
        t = str(texto or "").strip().replace(",", ".")
        # Si OCR agregó la unidad, también es válido.
        m_ms = re.search(r"(?<!\d)(-?\d{1,5}(?:\.\d{1,3})?)\s*ms\b", t, re.I)
        if m_ms:
            try:
                valor = float(m_ms.group(1))
                dec = len((m_ms.group(1).split(".", 1) + [""])[1])
                candidatos.append((valor, dec))
            except ValueError:
                pass
            continue
        # En estos videos el reloj suele ser sólo un número: 2.2, 4.4, 5.0...
        m = re.fullmatch(r"\s*(-?\d{1,5}(?:\.\d{1,3})?)\s*", t)
        if not m:
            # Algunos OCR agrupan el rótulo y el reloj en una misma lectura,
            # por ejemplo "EDAG Testlab 2.2". Al estar ya dentro del recorte
            # de esquina, el último decimal sigue siendo el mejor candidato.
            m = re.search(r"(-?\d{1,5}\.\d{1,3})\s*$", t)
        if m:
            try:
                valor = float(m.group(1))
            except ValueError:
                continue
            dec = len((m.group(1).split(".", 1) + [""])[1])
            candidatos.append((valor, dec))
    if not candidatos:
        return None, None
    # El recorte es muy pequeño; normalmente hay uno solo. Se prefiere el que
    # conserve decimales porque es el formato esperado del reloj de ensayo.
    valor, dec = max(candidatos, key=lambda x: (x[1] > 0, x[1]))
    precision = 10 ** (-dec) if dec > 0 else 1.0
    return valor, precision


def _leer_overlay(frame: np.ndarray, config: dict | None = None) -> dict:
    cfg = _cfg(config)
    if not cfg.get("leer_timestamp_overlay", True):
        return {"texto": "", "tiempos_ms": [], "fps_grabacion": [],
                "timestamp_esquina_ms": None, "precision_timestamp_esquina_ms": None,
                "texto_esquina": "", "error": None}
    h, w = frame.shape[:2]
    fs = float(cfg.get("fraccion_superior_overlay", 0.18))
    fi = float(cfg.get("fraccion_inferior_overlay", 0.18))
    superior = frame[:max(1, int(h * fs)), :]
    inferior = frame[max(0, int(h * (1.0 - fi))):, :]
    tiras = [("superior", superior), ("inferior", inferior)]
    lecturas = []
    lecturas_superior = []
    lecturas_esquina = []
    try:
        from ocr_engine import obtener_motor
        motor, _ = obtener_motor(config)
        # Reloj del ensayo: la captura real lo muestra en la esquina superior
        # derecha sin la palabra "ms" (p.ej. 2.2). Se OCRiza aparte para evitar
        # que un 0ms del pie se tome erróneamente como tiempo del cuadro.
        x1 = max(0, int(round(w * 0.72)))
        y2 = max(1, int(round(h * 0.10)))
        esquina = frame[:y2, x1:]
        if esquina.size:
            esc = esquina
            if esc.shape[1] < 700:
                escala = min(4.0, 700.0 / max(1, esc.shape[1]))
                esc = cv2.resize(esc, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
            items_esc = motor.leer_texto_completo(esc)
            lecturas_esquina.extend(str(x.get("texto") or "").strip() for x in items_esc if x.get("texto"))
        for nombre_tira, tira in tiras:
            if tira.size == 0:
                continue
            # Ampliar overlays pequeños sin alterar el cuadro principal.
            if tira.shape[1] < 1600:
                escala = min(2.0, 1600.0 / max(1, tira.shape[1]))
                tira = cv2.resize(tira, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
            items = motor.leer_texto_completo(tira)
            textos_tira = [str(x.get("texto") or "") for x in items if x.get("texto")]
            lecturas.extend(textos_tira)
            if nombre_tira == "superior":
                lecturas_superior.extend(textos_tira)
    except Exception as exc:
        return {"texto": "", "tiempos_ms": [], "fps_grabacion": [],
                "timestamp_esquina_ms": None, "precision_timestamp_esquina_ms": None,
                "texto_esquina": "", "error": f"{type(exc).__name__}: {exc}"}
    texto = " | ".join(lecturas)
    tiempo_esquina, precision_esquina = _parsear_numero_timestamp_esquina(lecturas_esquina)
    origen_timestamp = "esquina_crop" if tiempo_esquina is not None else None
    # Respaldo: en la captura real el OCR general ya devolvía "4.4" como
    # primera lectura, aunque la versión anterior lo ignoraba por no llevar ms.
    # V15.7: el respaldo sólo mira la franja SUPERIOR. La inferior contiene el
    # "0ms" fijo del pie, que nunca es el reloj del cuadro.
    if tiempo_esquina is None:
        tiempo_esquina, precision_esquina = _parsear_numero_timestamp_esquina(lecturas_superior)
        if tiempo_esquina is not None:
            origen_timestamp = "overlay_superior"
    if _numero_finito_con_signo(tiempo_esquina) is None:
        tiempo_esquina, precision_esquina = None, None
        origen_timestamp = None
    return {
        "texto": texto,
        "tiempos_ms": _parsear_timestamp_ms(lecturas),
        "fps_grabacion": _parsear_fps_grabacion(lecturas),
        "timestamp_esquina_ms": tiempo_esquina,
        "precision_timestamp_esquina_ms": precision_esquina,
        "timestamp_origen": origen_timestamp,
        "texto_esquina": " | ".join(lecturas_esquina),
        "error": None,
    }



def _numero_no_negativo(valor) -> float | None:
    """Convierte a float sólo si es finito y no negativo (p. ej. FPS/frames)."""
    try:
        numero = float(valor)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(numero) or numero < 0:
        return None
    return numero


def _numero_finito_con_signo(valor) -> float | None:
    """Valida reloj/offset relativo sin perder timestamps negativos legítimos."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        numero = float(str(valor).strip().replace(",", "."))
    except (TypeError, ValueError, OverflowError):
        return None
    return numero if math.isfinite(numero) else None


def _tiempo_apertura_positivo(valor) -> float | None:
    numero = _numero_finito_con_signo(valor)
    return numero if numero is not None and numero > 0 else None


def _referencia_temporal_valida(registro: dict | None) -> bool:
    """Reconoce sólo referencias temporales explícitas; False prevalece sobre legado."""
    dato = registro if isinstance(registro, dict) else {}
    if "referencia_tiempo_valida" in dato:
        return dato.get("referencia_tiempo_valida") is True
    return dato.get("estado_tiempo") == "VALIDO"


def resolver_tiempo_metadata(*, frame_index: int, fps: float | None,
                              timestamp_actual_ms: float | None = None,
                              timestamp_inicial_ms: float | None = None,
                              precision_overlay_ms: float | None = None,
                              config: dict | None = None) -> dict:
    """Resuelve una única fuente de verdad temporal para un frame.

    V15.6 compara dos hipótesis cuando hay reloj visible: tiempo cero en el
    frame 0 y tiempo anclado al timestamp inicial. Se queda con la que mejor
    explica el reloj del MISMO frame. Así un timestamp inicial mal leído no
    puede hacer que un ``2.2 ms`` visible termine convertido en ``1375 ms``.
    """
    cfg = _cfg(config)
    frame = max(0, int(frame_index or 0))
    fps_val = _numero_no_negativo(fps)
    if fps_val is not None and fps_val <= 0:
        fps_val = None
    resolucion = (1000.0 / fps_val) if fps_val else None
    # Timestamps absolutos y offsets relativos pueden ser negativos. Sólo
    # FPS/frames/resolución usan la validación no negativa.
    inicial = _numero_finito_con_signo(timestamp_inicial_ms)
    actual = _numero_finito_con_signo(timestamp_actual_ms)
    precision = _numero_no_negativo(precision_overlay_ms)

    tiempo_fps = (frame * resolucion) if resolucion is not None else None
    if tiempo_fps is not None:
        tiempo_fps = max(0.0, float(tiempo_fps))

    candidatos_esperados: list[tuple[str, float]] = []
    if tiempo_fps is not None:
        candidatos_esperados.append(("cero", tiempo_fps))
        if inicial is not None:
            anclado = float(inicial) + tiempo_fps
            if abs(anclado - tiempo_fps) > 1e-9:
                candidatos_esperados.append(("overlay_inicial", anclado))

    tolerancia = float(cfg.get("timestamp_tolerancia_min_ms", 0.25))
    if resolucion is not None:
        tolerancia = max(tolerancia,
                         float(cfg.get("timestamp_tolerancia_frames", 1.5)) * resolucion)
    if precision is not None:
        tolerancia = max(tolerancia, 1.5 * precision)

    esperado = None
    anclaje = None
    discrepancia = None
    advertencia = None
    overlay_valido = False

    if actual is not None:
        if not candidatos_esperados:
            tiempo = actual
            fuente = "timestamp_overlay_esquina"
            overlay_valido = True
            anclaje = "solo_overlay"
        else:
            anclaje, esperado = min(candidatos_esperados, key=lambda x: abs(actual - x[1]))
            discrepancia = actual - esperado
            if abs(discrepancia) <= tolerancia:
                tiempo = actual
                fuente = "timestamp_overlay_esquina"
                overlay_valido = True
            else:
                tiempo = esperado
                fuente = ("fps_anclado_overlay_inicial" if anclaje == "overlay_inicial"
                          else "fps_grabacion_validado")
                advertencia = (
                    f"El OCR del reloj del cuadro leyó {actual:.3f} ms, pero con la tasa "
                    f"de grabación se esperaban {esperado:.3f} ms. Se descartó esa lectura "
                    "para evitar una contradicción temporal."
                )
    elif candidatos_esperados:
        # Sin reloj legible se conserva el anclaje inicial cuando existe; de
        # lo contrario se usa frame/FPS desde cero.
        if inicial is not None:
            encontrado = next((x for x in candidatos_esperados if x[0] == "overlay_inicial"), None)
        else:
            encontrado = None
        anclaje, esperado = encontrado or candidatos_esperados[0]
        tiempo = esperado
        fuente = ("fps_anclado_overlay_inicial" if anclaje == "overlay_inicial"
                  else "fps_grabacion")
    else:
        tiempo = None
        fuente = "sin_fuente_temporal"

    if tiempo is not None:
        tiempo = float(tiempo)
    tiempo_crudo = None if tiempo is None else round(tiempo, 3)
    referencia_validada = bool((frame >= 0 and resolucion is not None) or overlay_valido)
    return {
        "frame_index": frame,
        # En esta función tiempo_ms es la lectura temporal cruda del frame,
        # no un tiempo final de apertura. El signo se conserva expresamente.
        "tiempo_ms": tiempo_crudo,
        "tiempo_crudo_ms": tiempo_crudo,
        "referencia_tiempo_valida": referencia_validada,
        "estado_referencia_tiempo": "VALIDADA" if referencia_validada else "PENDIENTE",
        # V15.7: sólo un reloj VALIDADO cuenta como tiempo de overlay. La
        # lectura cruda se conserva aparte para mostrarla como "no coincide";
        # así el consenso nunca calibra con una lectura ya descartada.
        "tiempo_overlay_ms": actual if overlay_valido else None,
        "tiempo_overlay_leido_ms": actual,
        "tiempo_fps_ms": None if tiempo_fps is None else round(tiempo_fps, 6),
        "timestamp_inicial_ms": inicial,
        "fuente_tiempo": fuente,
        "overlay_valido": overlay_valido,
        "anclaje_tiempo": anclaje,
        "discrepancia_ms": None if discrepancia is None else round(float(discrepancia), 6),
        "advertencia": advertencia,
        "resolucion_nativa_ms": None if resolucion is None else round(resolucion, 6),
        "precision_overlay_ms": precision,
        "tolerancia_validacion_ms": round(float(tolerancia), 6),
    }


def fps_temporal_confiable(fps_grabacion: float | None, fps_archivo: float | None,
                           config: dict | None = None) -> tuple[float | None, str]:
    """Elige la tasa que define ms/cuadro y dice de dónde salió.

    Orden: ``RecXXXX fps`` del overlay; ``fps_grabacion_forzado`` de
    config.yaml; FPS del contenedor sólo si es plausible para alta velocidad.
    Un AVI que declara 8 fps de reproducción nunca se usa como tasa de
    grabación: devolvería 125 ms/cuadro. En ese caso se devuelve ``None`` y el
    tiempo sale del reloj visible o queda marcado como desconocido.
    """
    cfg = (config or cargar_config()).get("video_airbag") or {}
    rec = _numero_no_negativo(fps_grabacion)
    if rec and rec > 0:
        return float(rec), "overlay_rec"
    forzado = _numero_no_negativo(cfg.get("fps_grabacion_forzado"))
    if forzado and forzado > 0:
        return float(forzado), "config_forzado"
    archivo = _numero_no_negativo(fps_archivo)
    minimo = float(cfg.get("fps_archivo_minimo_confiable", 500.0))
    if archivo and archivo >= minimo:
        return float(archivo), "archivo"
    return None, "desconocido"


def _tiempo_coherente_con_frame(tiempo_ms, frame_index: int, fps: float,
                                timestamp_inicial_ms=None, config: dict | None = None) -> bool:
    """¿El tiempo guardado corresponde a ese cuadro con esa tasa real?"""
    valor = _numero_finito_con_signo(tiempo_ms)
    if valor is None:
        return False
    ref = resolver_tiempo_metadata(frame_index=frame_index, fps=fps,
                                   timestamp_actual_ms=valor,
                                   timestamp_inicial_ms=timestamp_inicial_ms, config=config)
    return bool(ref.get("overlay_valido"))


def normalizar_item_temporal_video(item: dict, config: dict | None = None,
                                   fps_caso: float | None = None) -> bool:
    """Normaliza FPS y etiqueta sin reescribir el tiempo de una revisión humana.

    Los tiempos calculados del análisis se pueden recalcular; una revisión manual
    histórica se conserva byte por byte en ``tiempo_ms`` y sólo recibe estado/motivo
    derivados si es inválida o su referencia no puede sostenerse.
    """
    if not isinstance(item, dict):
        return False
    cambiado = False
    fps_rec = fps_grabacion_desde_item(item)
    fuente_fps = "overlay_rec" if fps_rec else None
    if not fps_rec and fps_caso:
        # V15.7: otra cámara del MISMO ensayo leyó RecXXXX fps. Todas graban a
        # la misma tasa, así que un OCR fallido aquí no vuelve a 125 ms/cuadro.
        fps_rec, fuente_fps = float(fps_caso), "overlay_rec_otra_camara"
    if not fps_rec:
        fps_rec, fuente_fps = fps_temporal_confiable(
            None, item.get("fps_archivo") or item.get("fps"), config)
    fps_declarado = _numero_no_negativo(item.get("fps_archivo") or item.get("fps"))
    if not fps_rec and fps_declarado:
        # Sin tasa fiable no se inventa un tiempo con los FPS de reproducción
        # (8 fps → 125 ms/cuadro). Sin ningún dato de FPS no se toca nada.
        if item.get("fps_fuente") != "desconocido" and item.get("estado") == "candidato":
            item["fps_fuente"] = "desconocido"
            item["advertencia_tiempo"] = (
                "No se pudo leer la tasa real (Rec…fps) y los FPS del archivo no son de alta "
                "velocidad. El tiempo sólo se acepta desde el reloj visible.")
            overlay = _numero_finito_con_signo(item.get("tiempo_overlay_ms"))
            item["tiempo_crudo_ms"] = None if overlay is None else round(overlay, 1)
            overlay_validado = overlay is not None and item.get("overlay_validado") is True
            item["referencia_tiempo_valida"] = bool(overlay_validado)
            item["estado_referencia_tiempo"] = "VALIDADA" if overlay_validado else "PENDIENTE"
            item["tiempo_ms"] = (round(overlay, 1) if overlay is not None and overlay > 0 and overlay_validado
                                  else None)
            if overlay is not None and overlay <= 0:
                item["estado_tiempo"] = "NO_POSITIVO"
                item["motivo_rechazo"] = "El tiempo candidato final debe ser estrictamente mayor que cero; se conserva el raw."
            elif overlay is not None and not overlay_validado:
                item["estado_tiempo"] = "REFERENCIA_INVALIDA"
                item["motivo_rechazo"] = "La lectura de overlay no tiene referencia temporal validada."
            elif overlay is not None:
                item["estado_tiempo"] = "VALIDO"
                item.pop("motivo_rechazo", None)
            else:
                item["estado_tiempo"] = "PENDIENTE"
            item["fuente_tiempo"] = "timestamp_overlay_esquina" if overlay is not None else "sin_fuente_temporal"
            cambiado = True
    if fps_rec and fps_rec > 0:
        resol = 1000.0 / fps_rec
        for clave, valor in (
            ("fps_grabacion", float(fps_rec)),
            ("fps", float(fps_rec)),
            ("fps_fuente", fuente_fps),
            ("resolucion_nativa_ms", round(resol, 6)),
        ):
            if item.get(clave) != valor:
                item[clave] = valor
                cambiado = True

        frame_auto = item.get("frame_evento")
        try:
            frame_auto = max(0, int(frame_auto)) if frame_auto is not None else None
        except (TypeError, ValueError):
            frame_auto = None
        if frame_auto is not None:
            resuelto = resolver_tiempo_metadata(
                frame_index=frame_auto, fps=fps_rec,
                timestamp_actual_ms=item.get("tiempo_overlay_ms"),
                timestamp_inicial_ms=item.get("overlay_timestamp_inicial_ms"),
                precision_overlay_ms=item.get("precision_fuente_ms"), config=config)
            raw_calculado = resuelto.get("tiempo_crudo_ms", resuelto.get("tiempo_ms"))
            referencia_calculada = resuelto.get("referencia_tiempo_valida") is True
            numero_calculado = _numero_finito_con_signo(raw_calculado)
            if numero_calculado is not None and numero_calculado > 0 and referencia_calculada:
                estado_calculado = "VALIDO"
                motivo_calculado = None
                tiempo_final_item = round(numero_calculado, 1)
            elif numero_calculado is not None and numero_calculado <= 0:
                estado_calculado = "NO_POSITIVO"
                motivo_calculado = "El tiempo candidato final debe ser estrictamente mayor que cero; se conserva el raw."
                tiempo_final_item = None
            elif numero_calculado is not None and not referencia_calculada:
                estado_calculado = "REFERENCIA_INVALIDA"
                motivo_calculado = "La referencia temporal de este candidato no está validada; se conserva el raw."
                tiempo_final_item = None
            else:
                estado_calculado = "PENDIENTE"
                motivo_calculado = None
                tiempo_final_item = None
            mapa = {
                # El tiempo final de candidato sólo se ocupa con referencia y >0;
                # la lectura firmada del frame permanece en tiempo_crudo_ms.
                "tiempo_ms": tiempo_final_item,
                "tiempo_crudo_ms": raw_calculado,
                "referencia_tiempo_valida": referencia_calculada,
                "estado_referencia_tiempo": resuelto.get("estado_referencia_tiempo"),
                "estado_tiempo": estado_calculado,
                "motivo_rechazo": motivo_calculado,
                "tiempo_fps_ms": resuelto.get("tiempo_fps_ms"),
                "fuente_tiempo": resuelto.get("fuente_tiempo"),
                "discrepancia_tiempo_ms": resuelto.get("discrepancia_ms"),
                "advertencia_tiempo": resuelto.get("advertencia"),
                "overlay_validado": bool(resuelto.get("overlay_valido")),
            }
            for clave, valor in mapa.items():
                if item.get(clave) != valor:
                    item[clave] = valor
                    cambiado = True

    rev = item.get("revision_manual") or {}
    if rev.get("estado") == "confirmado":
        rev = dict(rev)
        raw = rev.get("tiempo_ms")
        raw_historico_presente = "raw_time_ms" in rev
        rev.setdefault("raw_time_ms", raw)
        valor_manual = _numero_finito_con_signo(raw)
        if raw is None:
            estado_tiempo = "PENDIENTE"
            motivo = "La revisión manual confirmada no conserva un tiempo crudo interpretable."
        elif valor_manual is None:
            estado_tiempo = "NO_FINITO"
            motivo = "El tiempo histórico no es finito o no se puede interpretar; se conserva sin corregir."
        elif valor_manual <= 0:
            estado_tiempo = "NO_POSITIVO"
            motivo = f"No se corrige automáticamente: el tiempo histórico ({raw} ms) no es positivo y no se publica."
        else:
            # Compatibilidad con confirmaciones humanas de versiones antiguas:
            # antes no se persistían referencia_tiempo_valida/estado_tiempo.
            # Si hoy EXISTE una referencia independiente, se vuelve a comprobar;
            # si no existe ninguna, se conserva la autoridad humana sin inventar
            # una validación automática nueva. Una invalidación explícita siempre
            # prevalece.
            legacy_sin_metadata = (
                "referencia_tiempo_valida" not in rev and "estado_tiempo" not in rev
            )
            try:
                f_rev = int(rev.get("frame_index")) if rev.get("frame_index") is not None else None
                if f_rev is not None and f_rev < 0:
                    f_rev = None
            except (TypeError, ValueError, OverflowError):
                f_rev = None
            if rev.get("referencia_tiempo_valida") is False:
                estado_tiempo = "REFERENCIA_INVALIDA"
                motivo = "La revisión se guardó con una referencia temporal inválida."
            elif rev.get("referencia_tiempo_valida") is True:
                estado_tiempo = "VALIDO"
                motivo = ""
            elif f_rev is None:
                if legacy_sin_metadata and not fps_rec:
                    estado_tiempo = "VALIDO"
                    motivo = "Confirmación humana legacy preservada; no existe referencia automática independiente para revalidarla."
                    rev["referencia_legacy_manual"] = True
                else:
                    estado_tiempo = "REFERENCIA_INVALIDA"
                    motivo = "La revisión manual no conserva el cuadro de referencia."
            elif fps_rec and not _tiempo_coherente_con_frame(
                    raw, f_rev, fps_rec, item.get("overlay_timestamp_inicial_ms"), config):
                estado_tiempo = "REFERENCIA_INVALIDA"
                motivo = (f"El tiempo histórico ({raw} ms) no coincide con la referencia del cuadro "
                          f"{f_rev} a {fps_rec:g} fps; se conserva para revisión manual.")
            elif not fps_rec:
                overlay_ref = _numero_finito_con_signo(item.get("tiempo_overlay_ms"))
                precision_ref = _numero_no_negativo(item.get("precision_fuente_ms")) or 0.0
                tolerancia_ref = max(0.25, 1.5 * precision_ref)
                overlay_sostiene = (item.get("overlay_validado") is True
                                    and overlay_ref is not None and overlay_ref > 0
                                    and abs(overlay_ref - valor_manual) <= tolerancia_ref)
                if overlay_sostiene:
                    estado_tiempo = "VALIDO"
                    motivo = ""
                elif legacy_sin_metadata:
                    estado_tiempo = "VALIDO"
                    motivo = "Confirmación humana legacy preservada; no existe referencia automática independiente para revalidarla."
                    rev["referencia_legacy_manual"] = True
                else:
                    estado_tiempo = "PENDIENTE"
                    motivo = "No hay FPS ni reloj overlay positivo y coincidente para sostener la referencia temporal."
            else:
                estado_tiempo = "VALIDO"
                motivo = ""
        if (not raw_historico_presente or rev.get("estado_tiempo") != estado_tiempo
                or rev.get("motivo_rechazo") != motivo):
            rev["estado_tiempo"] = estado_tiempo
            rev["motivo_rechazo"] = motivo
            item["revision_manual"] = rev
            cambiado = True
    return cambiado


FUENTES_FPS_REALES = {"overlay_rec", "overlay_rec_otra_camara", "config_forzado", "archivo",
                      "reloj_overlay"}


def fps_real_item(item: dict | None) -> float | None:
    """FPS de grabación de un video ya normalizado, o None si no es fiable."""
    item = item or {}
    rec = fps_grabacion_desde_item(item)
    if rec:
        return float(rec)
    if item.get("fps_fuente") in FUENTES_FPS_REALES:
        valor = _numero_no_negativo(item.get("fps"))
        if valor and valor > 0:
            return float(valor)
    return None


def fps_grabacion_caso(items: Iterable[dict]) -> float | None:
    """Tasa RecXXXX leída en cualquier cámara del ensayo (la más repetida)."""
    valores = [fps_grabacion_desde_item(x) for x in items if isinstance(x, dict)]
    valores = [v for v in valores if v]
    if not valores:
        return None
    return max(set(valores), key=valores.count)


def normalizar_videos_caso(items: Iterable[dict], config: dict | None = None) -> bool:
    """Normaliza todas las cámaras de un ensayo compartiendo la tasa real."""
    items = [x for x in items if isinstance(x, dict)]
    fps_caso = fps_grabacion_caso(items)
    cambiado = False
    for item in items:
        cambiado = normalizar_item_temporal_video(item, config, fps_caso=fps_caso) or cambiado
    return cambiado

_cache_reloj: dict[tuple, dict] = {}
_CACHE_RELOJ_MAX = 4096


def leer_timestamp_esquina_frame(ruta_video: str | Path, frame_index: int,
                                  config: dict | None = None) -> dict:
    """OCR sólo del reloj superior derecho de un frame concreto.

    No mira el pie del video y por tanto no puede confundir el ``0ms`` fijo de
    la franja inferior con el reloj del cuadro actual. V15.7.1: cada lectura
    correcta se recuerda por (video, cuadro); al ir y volver cuadro a cuadro en
    el revisor no se repite EasyOCR ni se reabre el video.
    """
    ruta = Path(ruta_video)
    try:
        clave = (firma_video.firma_contenido(ruta), max(0, int(frame_index or 0)),
                 bool(_cfg(config).get("leer_timestamp_overlay", True)))
    except OSError:
        clave = None
    if clave is not None and clave in _cache_reloj:
        return dict(_cache_reloj[clave])
    resultado = _leer_timestamp_esquina_frame_sin_cache(ruta, frame_index, config)
    if clave is not None and resultado.get("error") is None:
        if len(_cache_reloj) >= _CACHE_RELOJ_MAX:
            _cache_reloj.pop(next(iter(_cache_reloj)))
        _cache_reloj[clave] = dict(resultado)
    return resultado


def _leer_timestamp_esquina_frame_sin_cache(ruta: Path, frame_index: int,
                                            config: dict | None = None) -> dict:
    cap = cv2.VideoCapture(str(ruta))
    try:
        if not cap.isOpened():
            return {"timestamp_ms": None, "precision_ms": None, "texto": "", "error": "video_no_abierto"}
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        frame = max(0, int(frame_index or 0))
        if total:
            frame = min(frame, max(0, total - 1))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
        ok, imagen = cap.read()
        if not ok or imagen is None:
            return {"timestamp_ms": None, "precision_ms": None, "texto": "", "error": "frame_no_leido"}
    finally:
        cap.release()

    cfg = _cfg(config)
    if not cfg.get("leer_timestamp_overlay", True):
        return {"timestamp_ms": None, "precision_ms": None, "texto": "", "error": None}
    h, w = imagen.shape[:2]
    x1 = max(0, int(round(w * 0.72)))
    y2 = max(1, int(round(h * 0.10)))
    esquina = imagen[:y2, x1:]
    lecturas: list[str] = []
    try:
        from ocr_engine import obtener_motor
        motor, _ = obtener_motor(config)
        esc = esquina
        if esc.size and esc.shape[1] < 700:
            escala = min(4.0, 700.0 / max(1, esc.shape[1]))
            esc = cv2.resize(esc, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
        items = motor.leer_texto_completo(esc) if esc.size else []
        lecturas = [str(x.get("texto") or "").strip() for x in items if x.get("texto")]
        valor, precision = _parsear_numero_timestamp_esquina(lecturas)
        # Se conserva el signo del reloj crudo. La decisión de apertura final
        # aplica su propio gate estricto >0 sin reescribir este timestamp.
        if _numero_finito_con_signo(valor) is None:
            valor = None
        return {"timestamp_ms": valor, "precision_ms": precision,
                "texto": " | ".join(lecturas), "error": None}
    except Exception as exc:
        return {"timestamp_ms": None, "precision_ms": None, "texto": " | ".join(lecturas),
                "error": f"{type(exc).__name__}: {exc}"}


def resolver_tiempo_frame(ruta_video: str | Path, frame_index: int, *,
                           fps_preferido: float | None = None,
                           timestamp_inicial_ms: float | None = None,
                           config: dict | None = None) -> dict:
    """Lee el reloj del frame solicitado y devuelve el tiempo autoritativo."""
    ruta = Path(ruta_video)
    fps_archivo = None
    cap = cv2.VideoCapture(str(ruta))
    try:
        if cap.isOpened():
            fps_archivo = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or None
    finally:
        cap.release()
    # V15.7: nunca caer a los 8 fps de reproducción del AVI.
    fps, fps_fuente = fps_temporal_confiable(fps_preferido, fps_archivo, config)
    lectura = leer_timestamp_esquina_frame(ruta, frame_index, config)
    resuelto = resolver_tiempo_metadata(
        frame_index=frame_index, fps=fps,
        timestamp_actual_ms=lectura.get("timestamp_ms"),
        timestamp_inicial_ms=timestamp_inicial_ms,
        precision_overlay_ms=lectura.get("precision_ms"), config=config,
    )
    resuelto.update({
        "fps": fps,
        "fps_fuente": fps_fuente,
        "fps_archivo": fps_archivo,
        "overlay_texto_esquina": lectura.get("texto", ""),
        "overlay_error": lectura.get("error"),
    })
    return resuelto

def _ajustar_cfg_con_perfil_evento(cfg: dict, perfil: dict | None) -> dict:
    """Ajusta sólo hacia mayor sensibilidad usando ejemplos confirmados.

    El aprendizaje nunca vuelve el detector más estricto que la configuración
    del usuario. Con al menos N ejemplos, puede bajar moderadamente los umbrales
    si las aperturas reales de esa cámara nacen con componentes aún más pequeños.
    """
    salida = dict(cfg)
    perfil = perfil or {}
    minimo = max(1, int(cfg.get("min_ejemplos_perfil_evento", 3)))
    if not bool(cfg.get("usar_perfil_evento_aprendido", True)) or int(perfil.get("ejemplos") or 0) < minimo:
        return salida
    pares = (
        ("min_fraccion_blanco_nuevo", "mediana_fraccion_blanco"),
        ("min_fraccion_componente_blanco", "mediana_fraccion_componente"),
    )
    for clave_cfg, clave_perfil in pares:
        try:
            actual = float(cfg.get(clave_cfg))
            aprendido = float(perfil.get(clave_perfil))
        except (TypeError, ValueError):
            continue
        if actual <= 0 or aprendido <= 0 or not math.isfinite(aprendido):
            continue
        objetivo = aprendido * 0.55
        # Evita que un ejemplo atípico vuelva el detector excesivamente sensible.
        suelo = actual * 0.35
        salida[clave_cfg] = max(suelo, min(actual, objetivo))
    return salida


def _baseline_compensado_y_movimiento(roi: np.ndarray, baseline: np.ndarray,
                                      cfg: dict) -> tuple[np.ndarray, np.ndarray | None]:
    """Alinea el baseline y devuelve también movimiento local residual.

    El flujo explica deformación suave del tablero/pieza. La magnitud residual
    respecto de su mediana permite localizar dónde se está inflando/deformando
    la pieza sin confundir una traslación global de cámara con una zona local.
    """
    h, w = roi.shape[:2]
    if h < 8 or w < 8:
        return baseline, None
    ancho_flujo = max(32, int(cfg.get("flujo_ancho_max", 480)))
    escala = min(1.0, ancho_flujo / float(w))
    if escala < 1.0:
        tam = (max(8, int(round(w * escala))), max(8, int(round(h * escala))))
        a = cv2.resize(roi, tam, interpolation=cv2.INTER_AREA)
        b = cv2.resize(baseline, tam, interpolation=cv2.INTER_AREA)
    else:
        a, b = roi, baseline
    flujo = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 21, 3, 5, 1.1, 0)
    tope = float(cfg.get("flujo_max_px", 10.0)) * escala
    np.clip(flujo, -tope, tope, out=flujo)
    if escala < 1.0:
        flujo = cv2.resize(flujo, (w, h), interpolation=cv2.INTER_LINEAR) / escala
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    deformado = cv2.remap(baseline, xx + flujo[..., 0], yy + flujo[..., 1],
                          cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    magnitud = cv2.magnitude(flujo[..., 0].astype(np.float32), flujo[..., 1].astype(np.float32))
    mediana = float(np.median(magnitud)) if magnitud.size else 0.0
    residual = np.maximum(magnitud - mediana, 0.0).astype(np.float32)
    return deformado, residual


def _baseline_compensado(roi: np.ndarray, baseline: np.ndarray, cfg: dict) -> np.ndarray:
    """Compatibilidad: devuelve sólo el baseline alineado."""
    deformado, _ = _baseline_compensado_y_movimiento(roi, baseline, cfg)
    return deformado


def _mascara_deformacion(movimiento: np.ndarray | None, cfg: dict) -> tuple[np.ndarray | None, dict]:
    """Convierte movimiento residual en una zona local normalizada de búsqueda."""
    if movimiento is None or movimiento.size == 0:
        return None, {"confiable": False, "motivo": "sin_flujo"}
    mov = np.asarray(movimiento, dtype=np.float32)
    med = float(np.median(mov))
    mad = float(np.median(np.abs(mov - med)))
    sigma = 1.4826 * mad
    umbral = max(float(cfg.get("deformacion_movimiento_min_px", 0.35)),
                 med + float(cfg.get("deformacion_mad_factor", 2.5)) * sigma)
    mascara = (mov >= umbral).astype(np.uint8)
    total = max(1, int(mascara.size))
    # Conservar sólo las zonas locales dominantes. Esto evita que un reflejo o
    # el propio material nuevo cree una segunda isla de flujo y se auto-valide.
    n, etiquetas, stats, _centroides = cv2.connectedComponentsWithStats(mascara, connectivity=8)
    componentes_usados = 0
    if n > 1:
        areas = stats[1:, cv2.CC_STAT_AREA].astype(int)
        orden = np.argsort(-areas, kind="stable")
        area_max = int(areas[orden[0]]) if len(orden) else 0
        rel_min = max(0.0, min(1.0, float(cfg.get("deformacion_rel_area_min", 0.25))))
        max_comp = max(1, int(cfg.get("deformacion_max_componentes", 3)))
        limpia = np.zeros_like(mascara)
        for pos in orden[:max_comp]:
            idx = int(pos) + 1
            area = int(stats[idx, cv2.CC_STAT_AREA])
            if area_max > 0 and area < max(4, int(round(area_max * rel_min))):
                continue
            limpia[etiquetas == idx] = 1
            componentes_usados += 1
        mascara = limpia
    fraccion = float(np.count_nonzero(mascara)) / total
    minimo = float(cfg.get("deformacion_fraccion_min", 0.0005))
    maximo = float(cfg.get("deformacion_fraccion_max", 0.45))
    confiable = bool(minimo <= fraccion <= maximo and componentes_usados > 0)
    if not confiable:
        return None, {
            "confiable": False,
            "motivo": "area_deformacion_fuera_rango",
            "fraccion": fraccion,
            "umbral_px": umbral,
        }
    # Cerrar huecos pequeños y ampliar un rango alrededor de donde la pieza se deforma.
    base_radio = int(round(min(mascara.shape[:2]) * float(cfg.get("margen_deformacion_norm", 0.06))))
    radio = max(2, min(int(cfg.get("margen_deformacion_px_max", 36)), base_radio))
    k_cierre = max(3, min(11, 2 * max(1, radio // 4) + 1))
    kernel_cierre = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_cierre, k_cierre))
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, kernel_cierre, iterations=1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radio + 1, 2 * radio + 1))
    rango = cv2.dilate(mascara, kernel, iterations=1).astype(bool)
    return rango, {
        "confiable": True,
        "motivo": "movimiento_local_residual",
        "fraccion": fraccion,
        "umbral_px": umbral,
        "radio_px": radio,
        "pixeles": int(np.count_nonzero(mascara)),
        "pixeles_rango": int(np.count_nonzero(rango)),
        "componentes_usados": componentes_usados,
    }

def _metricas_primer_blanco(roi: np.ndarray, baseline: np.ndarray, cfg: dict,
                            ruido: dict | None = None) -> dict:
    """Mide un contorno de ruptura NUEVO respecto al baseline nativo.

    La diferencia de intensidad sola también detecta un tablero que se hincha.
    Exigimos residuo tras compensar ese movimiento y una discontinuidad local
    nueva. Se conserva un indicio de un solo píxel, claro u oscuro, pero sólo
    cuadros posteriores con crecimiento coherente pueden corroborarlo. No se
    desenfoca ni se hace apertura morfológica sobre la señal de ruptura.

    Estas reglas son heurísticas: un brillo, sombra o artefacto de compresión
    aún puede parecer una fisura. No sustituyen una revisión de vídeos reales.
    """
    actual = roi.astype(np.int16)
    base = baseline.astype(np.int16)
    delta_crudo = actual - base
    delta = delta_crudo - int(round(float(np.median(delta_crudo))))
    lum = int(cfg.get("umbral_luminancia_blanco", 135))
    inc_cfg = int(cfg.get("umbral_incremento_blanco", 18))
    ruido_delta = float((ruido or {}).get("delta_p995") or 0.0)
    inc = max(inc_cfg, int(math.ceil(ruido_delta * 1.35)))
    inc = min(int(cfg.get("umbral_incremento_bolsa_max", 42)), inc)
    mascara_brillo = (actual >= lum) & (delta >= inc)
    mascara_oscura = ((actual <= int(cfg.get("umbral_luminancia_grieta", 120))) &
                      (delta <= -inc))
    total = int(mascara_brillo.size)
    pixeles_sin_compensar = int(np.count_nonzero(mascara_brillo))

    min_pix = max(3, int(round(total * float(cfg.get("min_fraccion_blanco_nuevo", 0.00003)))))
    min_comp = max(2, int(round(total * float(cfg.get("min_fraccion_componente_blanco", 0.000015)))))
    if ruido:
        factor = max(1.0, float(cfg.get("ruido_factor_pixeles", 3.0)))
        margen = max(0, int(cfg.get("ruido_margen_pixeles", 3)))
        min_pix = max(min_pix, int(math.ceil(float(ruido.get("pixeles") or 0) * factor)) + margen)
        min_comp = max(min_comp, int(math.ceil(float(ruido.get("componente") or 0) * factor)) + margen)
    min_pix_debil = max(1, int(cfg.get("min_pixeles_indicio", 1)))
    min_comp_debil = 1
    # Los mínimos fuertes sí dependen del ruido/área. El indicio no: hacerlo
    # relativo a toda la imagen volvería a borrar una primera fisura de 1 px.

    compensado = False
    deformado = base
    residuo = delta
    movimiento_residual = None
    if (bool(cfg.get("compensar_movimiento", True)) and
            (pixeles_sin_compensar >= min_pix_debil or np.any(mascara_oscura))):
        deformado_u8, movimiento_residual = _baseline_compensado_y_movimiento(roi, baseline, cfg)
        deformado = deformado_u8.astype(np.int16)
        residuo = actual - deformado
        residuo = residuo - int(round(float(np.median(residuo))))
        compensado = True

    # Centro menos sus cuatro vecinos: retiene íntegra la señal de 1 px.
    # Un abombamiento/iluminación suave no crea esta discontinuidad, aunque
    # supere los umbrales de intensidad y tenga mucha área.
    kernel = np.array([[0, -0.25, 0], [-0.25, 1, -0.25],
                       [0, -0.25, 0]], dtype=np.float32)
    contraste_actual = np.abs(cv2.filter2D(actual.astype(np.float32), -1, kernel,
                                         borderType=cv2.BORDER_REPLICATE))
    contraste_base = np.abs(cv2.filter2D(deformado.astype(np.float32), -1, kernel,
                                       borderType=cv2.BORDER_REPLICATE))
    discontinuidad = (contraste_actual - contraste_base >=
                      float(cfg.get("umbral_discontinuidad_nueva", 6.0)))
    residuo_min = int(cfg.get("residuo_min_compensado", 18))
    blanco_base = mascara_brillo & (residuo >= residuo_min) & discontinuidad
    grieta_base = mascara_oscura & (residuo <= -residuo_min) & discontinuidad

    # R10: si la deformación local puede estimarse de forma fiable, sólo se
    # promueve como evidencia fuerte el material nuevo que aparece alrededor
    # de esa zona. Si no hay mapa fiable, se conserva el detector previo para
    # no perder piezas/cámaras donde el movimiento sea demasiado sutil.
    movimiento_para_deformacion = movimiento_residual
    if movimiento_residual is not None:
        # Evita que el propio material nuevo "fabrique" su zona de soporte en
        # el flujo óptico. La deformación se estima con movimiento suave de la
        # pieza alrededor, excluyendo el contorno fotométrico candidato.
        material_crudo = (blanco_base | grieta_base).astype(np.uint8)
        if np.any(material_crudo):
            exclusion = cv2.dilate(material_crudo, np.ones((5, 5), np.uint8), iterations=1).astype(bool)
            movimiento_para_deformacion = movimiento_residual.copy()
            movimiento_para_deformacion[exclusion] = 0.0
    rango_deformacion, info_deformacion = _mascara_deformacion(movimiento_para_deformacion, cfg)
    deformacion_confiable = bool(info_deformacion.get("confiable"))
    if rango_deformacion is not None:
        blanco_rango = blanco_base & rango_deformacion
        grieta_rango = grieta_base & rango_deformacion
    else:
        blanco_rango = blanco_base
        grieta_rango = grieta_base
    material_rango_px = int(np.count_nonzero(blanco_rango | grieta_rango))
    material_total_pre_filtro = int(np.count_nonzero(blanco_base | grieta_base))
    proximidad_deformacion = (None if not deformacion_confiable
                              else bool(material_rango_px > 0))
    usar_rango = bool(
        cfg.get("estandar_apertura_activo", True)
        and deformacion_confiable
        and cfg.get("requerir_proximidad_deformacion_si_confiable", True)
    )
    blanco = blanco_rango if usar_rango else blanco_base
    grieta = grieta_rango if usar_rango else grieta_base
    mascara = (blanco | grieta).astype(np.uint8)
    pixeles = int(np.count_nonzero(blanco))
    pixeles_grieta = int(np.count_nonzero(grieta))
    pixeles_ruptura = int(np.count_nonzero(mascara))

    mayor = 0
    bbox = None
    bbox_norm = None
    centro = None
    componentes = []
    componentes_truncados = False
    if pixeles_ruptura:
        n, etiquetas, stats, centroides = cv2.connectedComponentsWithStats(mascara, connectivity=8)
        if n > 1:
            orden = np.argsort(-stats[1:, cv2.CC_STAT_AREA], kind="stable") + 1
            limite_componentes = max(1, int(cfg.get("max_componentes_indicio", 64)))
            componentes_truncados = len(orden) > limite_componentes
            for ci in orden[:limite_componentes]:
                cx, cy, cw, ch, area = [int(v) for v in stats[ci]]
                pertenece = etiquetas[cy:cy + ch, cx:cx + cw] == ci
                blancos_ci = int(np.count_nonzero(blanco[cy:cy + ch, cx:cx + cw] & pertenece))
                componentes.append({
                    "area": area, "blancos": blancos_ci, "grieta": area - blancos_ci,
                    "bbox": [cx, cy, cx + cw, cy + ch],
                    "bbox_norm": [cx / roi.shape[1], cy / roi.shape[0],
                                  (cx + cw) / roi.shape[1], (cy + ch) / roi.shape[0]],
                    "centro_norm": [float(centroides[ci][0]) / roi.shape[1],
                                    float(centroides[ci][1]) / roi.shape[0]],
                })
            idx = int(orden[0])
            mayor = int(stats[idx, cv2.CC_STAT_AREA])
            x, y, w, h = [int(v) for v in stats[idx, :4]]
            bbox = [x, y, x + w, y + h]
            if total and roi.shape[1] and roi.shape[0]:
                centro = [round(float(centroides[idx][0]) / roi.shape[1], 6),
                          round(float(centroides[idx][1]) / roi.shape[0], 6)]
                bbox_norm = [round(x / roi.shape[1], 6), round(y / roi.shape[0], 6),
                             round((x + w) / roi.shape[1], 6), round((y + h) / roi.shape[0], 6)]
    detectado = pixeles_ruptura >= min_pix and mayor >= min_comp
    evidencia_debil = pixeles_ruptura >= min_pix_debil and mayor >= min_comp_debil

    # R13: máscara amplia de bolsa visible para medir expansión y máximo. A
    # diferencia del breakout, aquí NO exigimos discontinuidad local: una bolsa
    # ya desplegada es una superficie grande y relativamente homogénea. La
    # máscara sigue comparándose contra baseline compensado y por eso no cuenta
    # objetos claros que ya existían antes.
    lum_bolsa = int(cfg.get("umbral_luminancia_bolsa", 120))
    inc_bolsa = max(int(cfg.get("umbral_incremento_bolsa", 12)),
                    int(math.ceil(ruido_delta * 1.20)))
    inc_bolsa = min(int(cfg.get("umbral_incremento_bolsa_max", 42)), inc_bolsa)
    mascara_bolsa = ((actual >= lum_bolsa) & (residuo >= inc_bolsa)).astype(np.uint8)
    if np.any(mascara_bolsa):
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        mascara_bolsa = cv2.morphologyEx(mascara_bolsa, cv2.MORPH_OPEN, k, iterations=1)
        mascara_bolsa = cv2.morphologyEx(mascara_bolsa, cv2.MORPH_CLOSE, k, iterations=1)
    area_bolsa = 0
    bbox_bolsa_norm = None
    if np.any(mascara_bolsa):
        nb, etb, stb, _ = cv2.connectedComponentsWithStats(mascara_bolsa, connectivity=8)
        if nb > 1:
            candidatos_bolsa = list(range(1, nb))
            # Si ya existe un contorno de ruptura, priorizar la región de bolsa
            # conectada/cercana a ese nacimiento sobre cualquier reflejo lejano.
            if bbox is not None:
                x1,y1,x2,y2 = bbox
                margen_b = max(4, int(round(min(roi.shape[:2]) * 0.04)))
                sx1=max(0,x1-margen_b); sy1=max(0,y1-margen_b)
                sx2=min(roi.shape[1],x2+margen_b); sy2=min(roi.shape[0],y2+margen_b)
                cercanos=[]
                for bi in candidatos_bolsa:
                    bx,by,bw,bh = [int(v) for v in stb[bi,:4]]
                    if bx < sx2 and bx+bw > sx1 and by < sy2 and by+bh > sy1:
                        cercanos.append(bi)
                if cercanos:
                    candidatos_bolsa=cercanos
            bi=max(candidatos_bolsa, key=lambda j:int(stb[j,cv2.CC_STAT_AREA]))
            area_bolsa=int(stb[bi,cv2.CC_STAT_AREA])
            bx,by,bw,bh=[int(v) for v in stb[bi,:4]]
            bbox_bolsa_norm=[round(bx/roi.shape[1],6), round(by/roi.shape[0],6),
                             round((bx+bw)/roi.shape[1],6), round((by+bh)/roi.shape[0],6)]

    # La tela que emerge crea contornos nuevos aun cuando todavía no ocupa gran área.
    gris_actual = np.clip(actual, 0, 255).astype(np.uint8)
    gris_base = np.clip(base, 0, 255).astype(np.uint8)
    e0 = cv2.Canny(gris_base, 45, 120)
    e1 = cv2.Canny(gris_actual, 45, 120)
    e0d = cv2.dilate((e0 > 0).astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1)
    bordes_nuevos = int(np.count_nonzero((e1 > 0) & (e0d == 0)))

    # V15.9: puntuaciones separadas por fuente de señal. Un mismo contorno de
    # ruptura (fisura/tela clara) debe dominar sobre abombamiento, reflejo,
    # movimiento de cámara, iluminación global y ruido de compresión.
    iluminacion_global = float(np.mean(delta_crudo))
    abombamiento_px = int(np.count_nonzero(
        (np.abs(delta_crudo) >= inc) & (np.abs(residuo) < residuo_min))) if compensado \
        else int(np.count_nonzero(np.abs(delta_crudo) >= inc))
    reflejo_mask = (actual >= 245) & (delta_crudo >= inc)
    reflejo_px = int(np.count_nonzero(reflejo_mask))
    movimiento_camara_px = 0.0
    # V15.9.1 (A8): coste real de la correlación de fase queda medido por
    # cuadro para el benchmark V15.8.1 vs V15.9 (utilidades/benchmark_detector).
    t_fase = time.perf_counter()
    try:
        punto, _respuesta = cv2.phaseCorrelate(base.astype(np.float32), actual.astype(np.float32))
        movimiento_camara_px = float(math.hypot(float(punto[0]), float(punto[1])))
        if not math.isfinite(movimiento_camara_px):
            movimiento_camara_px = 0.0
    except (cv2.error, TypeError, ValueError, IndexError):
        movimiento_camara_px = 0.0
    fase_correlate_ms = (time.perf_counter() - t_fase) * 1000.0
    scores_fuentes = {
        "fisura": round(pixeles_grieta / total if total else 0.0, 8),
        "tela_clara": round(pixeles / total if total else 0.0, 8),
        "material_en_rango": round(material_rango_px / total if total else 0.0, 8),
        "deformacion_local": round(float(info_deformacion.get("fraccion") or 0.0), 8),
        "abombamiento": round(abombamiento_px / total if total else 0.0, 8),
        "reflejo": round(reflejo_px / total if total else 0.0, 8),
        "movimiento_camara_px": round(movimiento_camara_px, 4),
        "iluminacion_global": round(iluminacion_global, 4),
        "ruido_compresion": round(float((ruido or {}).get("score_max") or 0.0), 4),
        "bordes_nuevos": round(bordes_nuevos / total if total else 0.0, 8),
    }
    # Cambio suave y global (luz, cámara, tablero que se hincha) sin la
    # discontinuidad local nueva que exige la ruptura: se señala para rechazo.
    cambio_global_sospechoso = bool(
        abs(iluminacion_global) >= float(cfg.get("umbral_iluminacion_global", 25.0))
        and pixeles_ruptura < min_pix)
    return {
        "pixeles_blanco_nuevo": pixeles,
        "pixeles_grieta_nueva": pixeles_grieta,
        "pixeles_ruptura": pixeles_ruptura,
        "componente_ruptura_px": mayor,
        "fase_correlate_ms": round(fase_correlate_ms, 4),
        "roi_ancho": int(roi.shape[1]), "roi_alto": int(roi.shape[0]),
        "radio_indicio_px": float(cfg.get("radio_indicio_px", 3.0)),
        "componentes_indicio": componentes,
        "componentes_indicio_truncados": componentes_truncados,
        "pixeles_sin_compensar": pixeles_sin_compensar,
        "compensado": compensado,
        "material_nuevo_pre_filtro_px": material_total_pre_filtro,
        "material_nuevo_en_rango_px": material_rango_px,
        "fraccion_material_en_rango": (material_rango_px / total if total else 0.0),
        "deformacion_confiable": deformacion_confiable,
        "proximidad_deformacion": proximidad_deformacion,
        "deformacion_local": info_deformacion,
        "estandar_apertura_activo": bool(cfg.get("estandar_apertura_activo", True)),
        "fraccion_blanco_nuevo": (pixeles / total if total else 0.0),
        "componente_blanco_px": mayor,
        "fraccion_componente_blanco": (mayor / total if total else 0.0),
        "bbox_componente": bbox,
        "bbox_componente_norm": bbox_norm,
        "centro_componente_norm": centro,
        "bordes_nuevos_px": bordes_nuevos,
        "fraccion_borde_nuevo": (bordes_nuevos / total if total else 0.0),
        "area_bolsa_visible_estimada_px": area_bolsa,
        "fraccion_bolsa_visible_estimada": (area_bolsa / total if total else 0.0),
        "bbox_bolsa_visible_norm": bbox_bolsa_norm,
        "umbral_incremento_adaptativo": inc,
        "umbral_incremento_bolsa_adaptativo": inc_bolsa,
        "min_pixeles_blanco": min_pix,
        "min_componente_blanco": min_comp,
        "min_pixeles_debil": min_pix_debil,
        "min_componente_debil": min_comp_debil,
        "evidencia_debil": bool(evidencia_debil),
        "detectado": bool(detectado),
        "scores_fuentes": scores_fuentes,
        "cambio_global_sospechoso": cambio_global_sospechoso,
    }


def _ruido_baseline(rois_base: list[np.ndarray], cfg: dict) -> dict:
    """Nivel de "falsa evidencia" que produce el propio sensor sin evento.

    Cada cuadro del baseline se compara con el baseline formado por los demás
    (leave-one-out). Lo que aparezca ahí es ruido, compresión o parpadeo.
    """
    pix, comp, scores, deltas = [0], [0], [0.0], [0.0]
    if len(rois_base) >= 2:
        cfg_crudo = dict(cfg)
        cfg_crudo["compensar_movimiento"] = False
        for i, roi in enumerate(rois_base):
            otros = [r for j, r in enumerate(rois_base) if j != i]
            ref = np.median(np.stack(otros, axis=0), axis=0).astype(np.uint8)
            actual = roi.astype(np.uint8)
            m = _metricas_primer_blanco(actual, ref, cfg_crudo)
            pix.append(int(m.get("pixeles_ruptura", m["pixeles_blanco_nuevo"])))
            comp.append(int(m["componente_blanco_px"]))
            diff = cv2.absdiff(actual, ref)
            scores.append(float(np.mean(diff)) + 70.0 * float(np.mean(cv2.subtract(actual, ref) > 28)))
            if diff.size:
                deltas.append(float(np.percentile(diff, 99.5)))
    return {"pixeles": max(pix), "componente": max(comp), "score_max": max(scores),
            "delta_p995": max(deltas),
            "cuadros": len(rois_base)}


def _baseline_contiene_evento(rois_base: list[np.ndarray], cfg: dict) -> dict:
    """¿Los cuadros de referencia ya muestran el airbag desplegado?

    V15.9: si un cuadro del baseline conserva evidencia fuerte de ruptura
    contra la mediana de los demás, el video empieza con el evento en curso.
    Se devuelve incertidumbre (``evento_al_inicio``) y se requiere revisión,
    sin inventar un origen artificial en el primer cuadro.
    """
    detecciones = []
    if len(rois_base) >= 2:
        cfg_crudo = dict(cfg)
        cfg_crudo["compensar_movimiento"] = False
        for i, roi in enumerate(rois_base):
            otros = [r for j, r in enumerate(rois_base) if j != i]
            ref = np.median(np.stack(otros, axis=0), axis=0).astype(np.uint8)
            m = _metricas_primer_blanco(roi.astype(np.uint8), ref, cfg_crudo)
            if m.get("detectado") or (
                    m.get("evidencia_debil") and
                    int(m.get("componente_ruptura_px") or 0) >=
                    max(2, int(m.get("min_componente_blanco") or 1))):
                detecciones.append({"frame_baseline": i,
                                    "pixeles_ruptura": int(m.get("pixeles_ruptura") or 0),
                                    "componente_px": int(m.get("componente_ruptura_px") or 0)})
    return {"evento_al_inicio": bool(detecciones), "evidencia_baseline": detecciones}


def _cerca(a: dict, b: dict, margen: float = 0.08) -> bool:
    """¿La evidencia ``a`` está en el mismo sitio que la componente ``b``?"""
    ca = a.get("centro_componente_norm")
    bb = b.get("bbox_componente_norm")
    if not ca:
        return False
    # Un ruido puntual situado a decenas de píxeles del nacimiento no debe
    # adelantar el evento sólo por caer dentro del antiguo margen del 8 %.
    if int(a.get("componente_ruptura_px", a.get("componente_blanco_px", 0)) or 0) <= 2:
        ancho, alto = int(a.get("roi_ancho") or 0), int(a.get("roi_alto") or 0)
        if ancho and alto and bb:
            radio = max(0.0, float(a.get("radio_indicio_px", 3.0)))
            return (bb[0] - radio / ancho <= ca[0] <= bb[2] + radio / ancho and
                    bb[1] - radio / alto <= ca[1] <= bb[3] + radio / alto)
    if bb:
        return (bb[0] - margen <= ca[0] <= bb[2] + margen and
                bb[1] - margen <= ca[1] <= bb[3] + margen)
    cb = b.get("centro_componente_norm")
    return bool(cb) and math.hypot(ca[0] - cb[0], ca[1] - cb[1]) <= 0.12


def _trayectoria_coherente(metricas: list[dict], inicio: int, fin: int) -> bool:
    """Descarta destellos que saltan de posición entre cuadros."""
    centros = [metricas[i].get("centro_componente_norm") for i in range(inicio, fin + 1)
               if metricas[i].get("evidencia_debil") and metricas[i].get("centro_componente_norm")]
    if len(centros) < 2:
        return True
    for a, b in zip(centros, centros[1:]):
        distancia = math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))
        if distancia > 0.28:
            return False
    return True


def _vista_componente(metrica: dict, componente: dict) -> dict:
    """Evidencia de una misma fisura; no suma ruidos de otras posiciones."""
    salida = dict(metrica)
    area = int(componente["area"])
    total = max(1, int(metrica.get("roi_ancho") or 1) * int(metrica.get("roi_alto") or 1))
    salida.update({
        "pixeles_ruptura": area, "componente_ruptura_px": area,
        "pixeles_blanco_nuevo": int(componente["blancos"]),
        "pixeles_grieta_nueva": int(componente["grieta"]),
        # Nombre legado preservado para consumidores anteriores.
        "componente_blanco_px": area,
        "fraccion_blanco_nuevo": int(componente["blancos"]) / total,
        "fraccion_componente_blanco": area / total,
        "bbox_componente": componente["bbox"],
        "bbox_componente_norm": componente["bbox_norm"],
        "centro_componente_norm": componente["centro_norm"],
        "detectado": area >= max(int(metrica.get("min_pixeles_blanco") or 1),
                                  int(metrica.get("min_componente_blanco") or 1)),
        "evidencia_debil": area >= max(int(metrica.get("min_pixeles_debil") or 1),
                                        int(metrica.get("min_componente_debil") or 1)),
    })
    return salida


def _componente_cercano(metrica: dict, siguiente: dict) -> dict | None:
    """Conserva un indicio real aunque otro píxel caliente sea más grande."""
    componentes = metrica.get("componentes_indicio")
    if componentes is None:
        return metrica if metrica.get("evidencia_debil") and _cerca(metrica, siguiente) else None
    bb = siguiente.get("bbox_componente_norm")
    if not bb:
        return None
    ancho, alto = int(metrica.get("roi_ancho") or 1), int(metrica.get("roi_alto") or 1)
    radio = max(0.0, float(metrica.get("radio_indicio_px", 3.0)))
    candidatos = []
    for comp in componentes:
        cx, cy = comp["centro_norm"]
        if (bb[0] - radio / ancho <= cx <= bb[2] + radio / ancho and
                bb[1] - radio / alto <= cy <= bb[3] + radio / alto):
            vista = _vista_componente(metrica, comp)
            if vista["evidencia_debil"]:
                candidatos.append(vista)
    if not candidatos:
        return None
    centro = siguiente.get("centro_componente_norm") or [(bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2]
    return min(candidatos, key=lambda m: math.hypot(
        (m["centro_componente_norm"][0] - centro[0]) * ancho,
        (m["centro_componente_norm"][1] - centro[1]) * alto))


def _evaluar_confirmacion(metricas: list[dict], scores: list[float], umbral: float,
                          nbase: int, cfg: dict, confirmacion: int) -> dict | None:
    """Valida un cuadro de evidencia fuerte y retrocede al primer indicio.

    V15.7: el inicio es el principio de la racha continua de evidencia que
    desemboca en la confirmación, en la misma posición, precedida por
    ``frames_previos_limpios`` cuadros sin evidencia. Si la racha llega hasta
    el baseline sin cuadros limpios, se marca para revisión en lugar de
    fingir que ese cuadro es el nacimiento.
    """
    total = len(metricas)
    if confirmacion < nbase or confirmacion >= total:
        return None
    ventana = max(2, int(cfg.get("ventana_confirmacion_frames", 5)))
    min_frames = max(2, int(cfg.get("min_frames_confirmacion", 2)))
    ratio_min = max(1.05, float(cfg.get("crecimiento_ratio_min", 1.8)))
    mult_comp = max(1.0, float(cfg.get("fuerte_multiplicador_componente", 2.2)))
    mult_pix = max(1.0, float(cfg.get("fuerte_multiplicador_pixeles", 1.7)))
    max_back = max(1, int(cfg.get("backtracking_max_frames", 7)))
    limpios_req = max(1, int(cfg.get("frames_previos_limpios", 2)))

    def es_fuerte(m: dict) -> bool:
        return bool(m.get("detectado")) and (
            float(m.get("componente_blanco_px") or 0) >= float(m.get("min_componente_blanco") or 1) * mult_comp
            or float(m.get("pixeles_ruptura", m.get("pixeles_blanco_nuevo")) or 0) >=
            float(m.get("min_pixeles_blanco") or 1) * mult_pix)

    mconf = metricas[confirmacion]
    if mconf.get("componentes_indicio"):
        mconf = _vista_componente(mconf, mconf["componentes_indicio"][0])
    if not es_fuerte(mconf):
        return None
    post_fin = min(total - 1, confirmacion + ventana - 1)
    post = metricas[confirmacion:post_fin + 1]
    post_cercano = [_componente_cercano(m, mconf) for m in post]
    if len(post) < min_frames or not all(m is not None for m in post_cercano[:min_frames]):
        return None

    inicio = confirmacion
    metrica_inicio = mconf
    trayectoria = [mconf]
    huecos = 0
    antes_limpio = False
    limite = (nbase if cfg.get("retroceso_hasta_indicio_continuo", True)
              else max(nbase, confirmacion - max_back))
    k = confirmacion - 1
    while k >= limite:
        mk = metricas[k]
        cercana = _componente_cercano(mk, metrica_inicio)
        if not huecos and cercana is not None:
            inicio = k
            metrica_inicio = cercana
            trayectoria.append(cercana)
            huecos = 0
        else:
            huecos += 1
            if huecos >= limpios_req:
                antes_limpio = all(_componente_cercano(metricas[j], metrica_inicio) is None
                                   for j in range(k, min(total, k + limpios_req)))
                break
        k -= 1
    borde_baseline = (not antes_limpio) and limite == nbase and inicio - nbase < limpios_req

    area0 = max(1.0, float(metrica_inicio.get("componente_blanco_px") or 0))
    max_area = max(float(m.get("componente_blanco_px") or 0)
                   for m in trayectoria + [m for m in post_cercano if m is not None])
    crecimiento = max_area / area0
    # Una punta mínima sólo se acepta si después crece; si el primer cuadro ya
    # es fuerte basta con la persistencia.
    if inicio != confirmacion and crecimiento < ratio_min and not es_fuerte(metrica_inicio):
        return None
    if not _trayectoria_coherente(trayectoria, 0, len(trayectoria) - 1):
        return None
    return {
        "frame_inicio": int(inicio),
        "frame_confirmacion": int(confirmacion),
        "retroceso_frames": int(confirmacion - inicio),
        "crecimiento_ratio": round(float(crecimiento), 4),
        "max_componente_px": int(round(max_area)),
        "antes_limpio": bool(antes_limpio),
        "inicio_en_borde_baseline": bool(borde_baseline),
        "metodo": "crecimiento_backtracking",
        "indicio_un_pixel": int(metrica_inicio.get("pixeles_ruptura") or
                                 metrica_inicio.get("pixeles_blanco_nuevo") or 0) == 1,
        "metricas_inicio": metrica_inicio,
    }


def _buscar_inicio_confirmado(metricas: list[dict], scores: list[float], umbral: float,
                               nbase: int, cfg: dict) -> dict | None:
    """Primer evento confirmado del video (recorrido completo)."""
    for confirmacion in range(nbase, len(metricas)):
        resultado = _evaluar_confirmacion(metricas, scores, umbral, nbase, cfg, confirmacion)
        if resultado:
            return resultado
    return None


def _puntaje_apertura(metricas: dict, score_diff: float, umbral: float,
                      crecimiento: float, zona: dict | None, perfil: dict | None) -> float:
    pix_ratio = float(metricas.get("pixeles_blanco_nuevo") or 0) / max(1.0, float(metricas.get("min_pixeles_debil") or 1))
    comp_ratio = float(metricas.get("componente_blanco_px") or 0) / max(1.0, float(metricas.get("min_componente_debil") or 1))
    blanco = min(1.0, pix_ratio / 3.0)
    componente = min(1.0, comp_ratio / 3.0)
    crec = min(1.0, max(0.0, crecimiento - 1.0) / 2.0)
    diff = min(1.0, max(0.0, score_diff) / max(umbral, 1e-6))
    borde = min(1.0, float(metricas.get("fraccion_borde_nuevo") or 0.0) / 0.003)
    zona_score = float((zona or {}).get("confianza") or 0.0) if (zona or {}).get("activa") else 0.45
    aprendido = 1.0 if int((perfil or {}).get("ejemplos") or 0) >= 3 else 0.0
    score = (0.25 * blanco + 0.25 * componente + 0.18 * crec + 0.12 * diff +
             0.08 * borde + 0.09 * zona_score + 0.03 * aprendido)
    return max(0.0, min(0.99, score))


def _razones_evento(resultado: dict, metricas: list[dict], confirmacion: dict | None,
                    zona: dict | None, deteccion_inicio: dict) -> dict:
    """Evidencia explicable del evento (V15.9): qué se vio, dónde y con qué calidad.

    Incluye primer cuadro y cuadro confirmatorio, ROI y microzona, puntuaciones
    separadas por fuente (fisura/tela clara/abombamiento/reflejo/movimiento de
    cámara/ruido), reloj/FPS usados, calidad y advertencias abiertas.
    """
    indice = resultado.get("frame_evento")
    mb = ((confirmacion or {}).get("metricas_inicio") or
          (metricas[indice] if isinstance(indice, int) and 0 <= indice < len(metricas) else {}))
    scores = mb.get("scores_fuentes") or {}
    advertencias = [a for a in (resultado.get("advertencia_deteccion"),
                                resultado.get("advertencia_tiempo"),
                                resultado.get("advertencia_fps"),
                                resultado.get("advertencia_componentes")) if a]
    return {
        "definicion": resultado.get("definicion_evento"),
        "frame_inicio": indice,
        "frame_confirmacion": resultado.get("frame_confirmacion_automatica"),
        "metodo": (confirmacion or {}).get("metodo") or resultado.get("tipo_deteccion"),
        "roi_deteccion": {
            "bbox_norm": (zona or {}).get("bbox_norm"),
            "fuente": (zona or {}).get("fuente"),
            "tipo_camara": (zona or {}).get("tipo_camara"),
        },
        "microzona_bbox_norm": (mb.get("bbox_componente_norm")
                                or resultado.get("bbox_componente_norm")),
        "scores_fuentes": scores,
        "descartes": {
            "iluminacion_global": float(scores.get("iluminacion_global") or 0.0),
            "abombamiento": float(scores.get("abombamiento") or 0.0),
            "reflejo": float(scores.get("reflejo") or 0.0),
            "movimiento_camara_px": float(scores.get("movimiento_camara_px") or 0.0),
            "ruido_compresion": float(scores.get("ruido_compresion") or 0.0),
        },
        "reloj": {
            "tiempo_ms": resultado.get("tiempo_ms"),
            "tiempo_fps_ms": resultado.get("tiempo_fps_ms"),
            "fuente_tiempo": resultado.get("fuente_tiempo"),
            "fps": resultado.get("fps"),
            "resolucion_nativa_ms": resultado.get("resolucion_nativa_ms"),
            "overlay_validado": resultado.get("overlay_validado"),
        },
        "calidad": {
            "confianza": resultado.get("confianza"),
            "score_apertura": resultado.get("score_apertura"),
            "antes_limpio": resultado.get("antes_limpio"),
            "inicio_en_borde_baseline": resultado.get("inicio_en_borde_baseline"),
            "evento_al_inicio": bool(deteccion_inicio.get("evento_al_inicio")),
            "evidencia_baseline": deteccion_inicio.get("evidencia_baseline") or [],
        },
        "advertencias": advertencias,
    }


def _integrar_decision_v1606(resultado: dict, auton: dict, *, fps_estandar,
                              fps_fuente, revision, metricas_anteriores,
                              ventana_rescate_ms=8.0) -> None:
    """Aplica decisiones visuales al resultado REAL del pipeline y del visor.

    No usa fps del contenedor cuando discrepa con la grabacion, y no rebautiza
    una meseta de area proyectada como volumen, presion ni Tmax fisico.
    """
    previa = {k: resultado.get(k) for k in (
        "frame_evento", "tiempo_ms", "metodo_confirmacion",
        "frame_max_inflado_estimado", "tiempo_max_inflado_estimado_ms",
        "estado_max_inflado", "frame_llenado_estimado", "duracion_llenado_estimada_ms")}
    onset = auton.get("aparicion_bolsa") or {}
    maximo = auton.get("maximo_visible") or {}
    diag = {
        "version": auton.get("version"), "estado": "evaluado",
        "previo": previa, "aparicion_bolsa": onset, "maximo_visible": maximo,
        "advertencias": auton.get("advertencias") or [],
        "decision_apertura_aplicada": False, "decision_maximo_aplicada": False,
        "cuadros_procesados": auton.get("cuadros_leidos"),
        "maximo_no_es_volumen_o_presion": True,
    }
    resultado["congruencia_v1606"] = diag
    if auton.get("error"):
        diag["estado"] = "no_evaluable"; diag["motivo"] = auton.get("error")
        return
    manual = isinstance(revision,dict) and revision.get("estado") in ("confirmado", "sin_evento")
    frame = onset.get("cuadro")
    inicio_valido = (isinstance(frame,int) and frame > 0
                     and onset.get("estado") == "candidato_automatico_no_validado"
                     and frame < int(auton.get("cuadros_leidos") or 0)
                     and not resultado.get("evento_al_inicio"))
    if inicio_valido and not manual:
        # El detector global conserva el primer trazo débil, pero no lo publica
        # por sí mismo. Se retrocede sólo cuando la ROI local también registra
        # discontinuidad física contemporánea; un destello sin ruptura no basta.
        debil = onset.get("primer_indicio_debil_cuadro")
        if isinstance(debil, int) and 0 < debil < frame and frame-debil <= 1:
            metricadebil = (metricas_anteriores[debil] if debil < len(metricas_anteriores) else {})
            cambio_global = float((metricadebil.get('scores_fuentes') or {}).get('iluminacion_global') or 0)
            # Arena halló un destello anterior a la primera tela visible en
            # FRONTAL. Si el fotograma débil coincide con cambio global intenso,
            # no retroceder >1 cuadro basándose en esa señal. Preservar el
            # instante como hipótesis y permitir fusión con otra cámara.
            if cambio_global >= 0.60:
                diag['retroceso_descartado']={'cuadro':debil,'motivo':'cambio_global_de_iluminacion',
                                              'valor':round(cambio_global,4)}
                debil = None
            evidencia_debil = (_evidencia_fisica_temporal(metricas_anteriores,debil,3)
                               if isinstance(debil,int) else {"nivel":"ninguna","cuadros_fisicos":[]})
            frames_ruptura = evidencia_debil['cuadros_fisicos']
            if evidencia_debil['nivel'] in {'fuerte','compatible'}:
                diag["retroceso_evidencia_fisica"] = {"de": frame, "a": debil,
                                                       "cuadros_ruptura": frames_ruptura}
                frame = debil
                onset = dict(onset)
                onset["cuadro_fuerte"] = onset["cuadro"]
                onset["cuadro"] = debil
                onset["primer_indicio_debil_validado"] = True
                diag["aparicion_bolsa"] = onset
        # Comparar los motores, sin forzar artificialmente que coincidan.
        anterior_frame = resultado.get("frame_evento")
        try:
            f_ant = int(anterior_frame) if anterior_frame is not None else None
        except (ValueError,TypeError,OverflowError):
            f_ant = None
        # Priorizar la continuidad y crecimiento de material observado por el
        # motor global. El detector de ruptura local sirve de refuerzo, no es
        # permiso para saltar a una meseta posterior.
        verificacion = _evidencia_fisica_temporal(metricas_anteriores,frame,3)
        # Una aparicion global anterior sin material fisico local no puede
        # recibir la etiqueta 'fuerte' prestada de fotogramas futuros. En ese
        # caso se corrige al PRIMER fotograma con material que sí persiste.
        if verificacion['nivel']=='ninguna':
            primer_fisico = verificacion.get('primer_cuadro_fisico')
            if isinstance(primer_fisico,int) and frame < primer_fisico <= frame+3:
                posterior = _evidencia_fisica_temporal(metricas_anteriores,primer_fisico,3)
                if posterior['nivel'] in {'fuerte','compatible'}:
                    diag['onset_reajustado_por_evidencia_local'] = {
                        'desde':frame,'hasta':primer_fisico,
                        'motivo':'sin_material_local_en_cuadro_original'}
                    frame=primer_fisico
                    verificacion=posterior
                    onset=dict(onset)
                    onset['cuadro']=frame
                    diag['aparicion_bolsa']=onset
        # V16.0.15: no reemplazar un onset LOCAL anterior físicamente
        # corroborado por el instante GLOBAL donde la bolsa ya crecio.
        arbitraje = _arbitrar_onset_fisico_1615(metricas_anteriores, frame, f_ant)
        diag['arbitraje_temporal_1615'] = arbitraje
        arbitraje_frame = arbitraje.get('frame')
        if isinstance(arbitraje_frame, int) and arbitraje_frame != frame:
            frame = arbitraje_frame
            verificacion = _evidencia_fisica_temporal(metricas_anteriores, frame, 4)
            onset = dict(onset)
            onset['cuadro'] = frame
            diag['aparicion_bolsa'] = onset
        # Busqueda retrospectiva: no resta tiempo de manera automatica.
        rescate = _buscar_inicio_fisico_retrospectivo_1616(
            metricas_anteriores, frame, fps_estandar, ventana_rescate_ms)
        diag['busqueda_temprana_1616'] = rescate
        temprana = rescate.get('frame')
        if isinstance(temprana, int) and 0 < temprana < frame:
            frame = temprana
            verificacion = _evidencia_fisica_temporal(metricas_anteriores, frame, 4)
            onset = dict(onset)
            onset['cuadro'] = frame
            diag['aparicion_bolsa'] = onset
            diag['rescate_onset_desde_global_1616'] = {
                'frame_rescatado': frame,
                'frames_soporte': rescate.get('soporte_frames', []),
                'criterio': rescate.get('decision')}
        if arbitraje.get('alerta') and not diag.get('rescate_onset_desde_global_1616'):
            diag['advertencias'].append('discrepancia_onset_sin_resolver')
        if resultado.get('roi_arbitraje_conflicto'):
            verificacion={**verificacion,"nivel":"conflicto_roi"}
        apoyos = (verificacion['cuadros_fisicos'] if verificacion['nivel']
                  in {'fuerte','compatible'} else [])
        diag['evidencia_fisica_temporal_v1610']=verificacion
        diag['nivel_evidencia_fisica']=verificacion['nivel']
        diag['respaldo_detector_local_frames']=apoyos
        diag["diferencia_con_detector_anterior_frames"] = (
            frame - f_ant if f_ant is not None else None)
        # La continuidad global con crecimiento aporta una propuesta automatica.
        # No declarar confirmacion fisica fuerte si el ROI no corrobora.
        resultado["frame_evento"] = frame
        resultado["frame_evento_confiable"] = bool(apoyos)
        resultado["frame_confirmacion_automatica"] = max(frame+1, min(frame+5, int(onset.get("intervalo",[frame,frame+2])[-1]) + 2))
        resultado["metodo_confirmacion"] = "congruencia_material_temporal_v1606"
        resultado["tipo_deteccion"] = "primer_material_visible_con_crecimiento"
        resultado["estado"] = "candidato"
        resultado["estado_evento"] = "confirmado" if apoyos else "propuesto"
        resultado["frame_color_estimado"] = frame if apoyos else None
        resultado["tiempo_color_estimado_ms"] = (
            round(frame*1000.0/float(fps_estandar),6) if apoyos and fps_estandar else None)
        resultado["referencia_color_valida"] = bool(apoyos and fps_estandar)
        resultado["fuente_tiempo_color"] = (fps_fuente if apoyos else None)
        original_evidencia = dict(resultado.get("evaluacion_apertura_estandar") or {})
        original_evidencia["auto_colorable"] = bool(apoyos and fps_estandar)
        original_evidencia["auto_publicable"] = False
        original_evidencia["criterio_version"] = "v16.0.6-corrobora-tela-y-ruptura-local"
        original_evidencia["nota"] = "Evidencia recalculada: no reutilizar el score del cuadro anterior."
        original_evidencia["score_evidencia"] = None
        resultado["evaluacion_apertura_estandar"] = original_evidencia
        resultado["algoritmo_video"] = ALGORITMO_VERSION
        resultado["definicion_evento"] = (
            "Primer material nuevo visible con persistencia y crecimiento posterior; "
            "ruptura estructural evaluada por evidencia local.")
        if fps_estandar is not None and math.isfinite(float(fps_estandar)) and float(fps_estandar) > 0:
            ms = frame * 1000.0 / float(fps_estandar)
            resultado["fps"] = float(fps_estandar)
            resultado["fps_fuente"] = fps_fuente or "fps_grabacion"
            resultado["tiempo_ms"] = round(ms, 6)
            resultado["tiempo_fps_ms"] = round(ms, 6)
            resultado["resolucion_nativa_ms"] = round(1000.0 / float(fps_estandar), 6)
            resultado["fuente_tiempo"] = fps_fuente or "fps_grabacion"
            resultado["referencia_tiempo_valida"] = True
        else:
            resultado["tiempo_ms"] = None
            resultado["tiempo_fps_ms"] = None
            resultado["fuente_tiempo"] = "sin_fps_grabacion_verificado"
            resultado["referencia_tiempo_valida"] = False
        # Nunca reciclar el reloj OSD del cuadro anterior como si fuese el nuevo.
        for k in ("tiempo_overlay_ms", "tiempo_overlay_leido_ms",
                  "offset_overlay_ms", "discrepancia_tiempo_ms", "fps_validado_reloj"):
            resultado[k] = None
        resultado["overlay_validado"] = False
        resultado["version_onset_canonico"] = "v16.0.6-primer-material-congruente"
        resultado["requiere_revision"] = True
        resultado["revision_informativa"] = bool(apoyos) and (not arbitraje.get('alerta') or bool(diag.get('rescate_onset_desde_global_1616')))
        if arbitraje.get('alerta') and not diag.get('rescate_onset_desde_global_1616'):
            resultado["motivo"] = 'discrepancia_onset_entre_motores_sin_evidencia_suficiente'
            resultado["frame_evento_confiable"] = False
            resultado["estado_evento"] = 'propuesto'
            resultado["frame_color_estimado"] = None
            resultado["tiempo_color_estimado_ms"] = None
            resultado["referencia_color_valida"] = False
        resultado["limitacion_detector"] = (
            "La continuidad visual automatica no prueba por si sola la ruptura: "
            "si las senales locales discrepan, revisar evidencia. No hay clasificador calibrado.")
        razones = resultado.get("razones_evento")
        if isinstance(razones, dict):
            razones["frame_inicio"] = frame
            razones["frame_confirmacion"] = resultado["frame_confirmacion_automatica"]
            razones["metodo"] = resultado["metodo_confirmacion"]
            razones["definicion"] = resultado["definicion_evento"]
            if isinstance(razones.get("reloj"),dict):
                razones["reloj"].update({"tiempo_ms": resultado.get("tiempo_ms"),
                                         "tiempo_fps_ms": resultado.get("tiempo_fps_ms"),
                                         "fuente_tiempo": resultado.get("fuente_tiempo"),
                                         "overlay_validado": False})
        diag["decision_apertura_aplicada"] = True
        diag["criterio_ruptura"] = ("material_persistente_mas_evidencia_local"
                                     if verificacion['nivel']=='fuerte' else
                                     "material_local_compatible" if verificacion['nivel']=='compatible'
                                     else "material_sin_respaldo_local")
    else:
        diag["motivo_apertura_no_aplicada"] = (
            "revision_humana_prioritaria" if manual else "sin_aparicion_congruente_o_evento_ya_visible_en_baseline")

    # El máximo usa el onset global, nunca la detección ROI obsoleta.
    if maximo.get("estado") == "meseta_de_area_2d_candidata" and isinstance(maximo.get("cuadro"),int):
        fmax = int(maximo["cuadro"])
        finicio = resultado.get("frame_evento")
        if isinstance(finicio,int) and fmax > finicio:
            resultado["frame_max_inflado_estimado"] = fmax
            resultado["estado_max_inflado"] = "maximo_visible_observado_no_confirmado"
            resultado["frame_llenado_estimado"] = fmax
            resultado["duracion_llenado_estimada_ms"] = None
            resultado["tiempo_max_inflado_estimado_ms"] = None
            resultado["duracion_hasta_max_inflado_ms"] = None
            if fps_estandar and float(fps_estandar)>0:
                resultado["tiempo_max_inflado_estimado_ms"] = round(fmax*1000/float(fps_estandar),6)
                resultado["duracion_hasta_max_inflado_ms"] = round((fmax-finicio)*1000/float(fps_estandar),6)
                resultado["duracion_llenado_estimada_ms"] = resultado["duracion_hasta_max_inflado_ms"]
            diag["decision_maximo_aplicada"] = True
    elif maximo.get("estado") in ("maximo_censurado_por_encuadre", "sin_maximo_defendible", "clip_censurado", "maximo_observado_no_confirmado", "sin_inicio_confiable"):
        # Nunca conservar un máximo legado que el nuevo barrido no pudo validar.
        for k in ("frame_max_inflado_estimado", "tiempo_max_inflado_estimado_ms",
                  "duracion_hasta_max_inflado_ms", "frame_llenado_estimado",
                  "duracion_llenado_estimada_ms"):
            resultado[k] = None
        resultado["estado_max_inflado"] = "sin_maximo_defendible"
        diag["decision_maximo_aplicada"] = True
    else:
        diag["motivo_maximo_no_aplicado"] = "sin_criterio_de_maximo_admisible"
    if diag["decision_maximo_aplicada"]:
        resultado["anomalías_despliegue"] = sorted(set(
            list(resultado.get("anomalías_despliegue") or []) +
            ([str(maximo.get("estado"))] if maximo.get("estado") != "meseta_de_area_2d_candidata" else
             ["meseta_area_2d_experimental_no_maximo_fisico"]) ))
        resultado["medicion_maximo_version"] = "v16.0.6-area-global-con-censura"


def analizar_video(ruta_video: str | Path, config: dict | None = None, *, usar_cache: bool = True) -> dict:
    """Detecta el primer cuadro visible del airbag y lo valida con cuadros futuros."""
    ruta = Path(ruta_video).resolve()
    cfg = _cfg(config)
    firma = _firma(ruta)
    from aprendizaje_video_airbag import version_aprendizajes
    # Sólo las zonas/ejemplos que pueden afectar a ESTE video invalidan su caché.
    version_zonas = version_aprendizajes(ruta)
    cache = _leer_json(RUTA_CACHE, {"version": 4, "items": {}})
    cache_key = hashlib.sha256(json.dumps(
        {"firma": firma, "cfg": cfg, "algoritmo": ALGORITMO_VERSION,
         "sombra_apertura": "onset-hypotheses-r9-v2+deformation-proximity-v1+opening-publication-v1-shadow",
         "zonas": version_zonas},
        sort_keys=True, default=str).encode()).hexdigest()
    if usar_cache and isinstance(cache, dict):
        item = (cache.get("items") or {}).get(cache_key)
        if isinstance(item, dict):
            item = dict(item)
            # La firma es por contenido: el caché puede venir de otra carpeta.
            item["ruta"], item["nombre"] = str(ruta), ruta.name
            normalizar_item_temporal_video(item, config)
            item["desde_cache"] = True
            rev = revision_video(ruta)
            if rev:
                item["revision_manual"] = rev
                normalizar_item_temporal_video(item, config)
            return item

    cap = cv2.VideoCapture(str(ruta))
    if not cap.isOpened():
        return {"ruta": str(ruta), "nombre": ruta.name, "estado": "error",
                "error": "OpenCV no pudo abrir el video.", "firma": firma}
    fps_archivo = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frames_decl = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    ancho = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    alto = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    max_ancho = int(cfg.get("max_ancho_analisis", 960))
    margen = float(cfg.get("margen_vertical_deteccion", 0.12))

    ok_ref, primer_frame_ref = cap.read()
    primer_frame = primer_frame_ref if ok_ref and primer_frame_ref is not None else None
    overlay_inicial = (_leer_overlay(primer_frame, config) if primer_frame is not None
                       else {"texto": "", "tiempos_ms": [], "fps_grabacion": [],
                             "timestamp_esquina_ms": None, "precision_timestamp_esquina_ms": None,
                             "texto_esquina": "", "error": None})
    fps_rec_inicial = (overlay_inicial.get("fps_grabacion") or [None])[0]
    fps_temporal_pre = float(fps_rec_inicial) if fps_rec_inicial else fps_archivo
    resolucion_pre = (1000.0 / fps_temporal_pre) if fps_temporal_pre > 0 else None

    if primer_frame is not None:
        from aprendizaje_video_airbag import seleccionar_zona_aprendida, perfil_evento_aprendido
        zona_aprendida = seleccionar_zona_aprendida(ruta, primer_frame, {"video_airbag": cfg})
        perfil_evento = perfil_evento_aprendido(zona_aprendida.get("tipo_camara"))
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    else:
        zona_aprendida = {"activa": False, "bbox_norm": None, "fuente": "sin_frame_referencia",
                          "tipo_camara": None, "confianza": 0.0, "total_aprendizajes": 0}
        perfil_evento = {"tipo_camara": None, "ejemplos": 0}
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    # V16.0.8: encontrar deformación fuera de una ROI heredada.
    # No reescribe .aprendizaje ni el fotograma del usuario. Al detectarse un
    # candidato estable, el mismo detector de ruptura debe validarlo después.
    if bool(cfg.get('roi_deformacion_activa',True)) and primer_frame is not None:
        if buscar_roi_deformacion is None:
            propuesta_roi = {'confiable':False,'motivo':'modulo_roi_no_disponible'}
        else:
            try:
                propuesta_roi=buscar_roi_deformacion(
                    ruta, ancho_analisis=min(320,int(cfg.get('roi_deformacion_ancho',320))),
                    max_frames=min(240,int(cfg.get('roi_deformacion_max_frames',240))),
                    max_eventos=int(cfg.get('roi_deformacion_max_eventos',12)))
            except (OSError, cv2.error, ValueError, TypeError, RuntimeError) as err:
                propuesta_roi={'confiable':False,'motivo':'excepcion_roi_deformacion',
                               'tipo_error':type(err).__name__}
        zona_candidata_deformacion = _seleccionar_roi_deformacion(zona_aprendida, propuesta_roi)
        # V16.0.9: no sustituir a ciegas una ROI histórica que ya funcionaba.
        # Registrar la candidata y comparar solo si no hubo inicio confirmado.
        if zona_candidata_deformacion.get('fuente') == 'deformacion_temporal_auto':
            zona_alternativa_deformacion = zona_candidata_deformacion
            zona_aprendida = dict(zona_aprendida)
            zona_aprendida['bbox_sugerida_norm'] = list(propuesta_roi['bbox_norm'])
            zona_aprendida['motivo_sugerencia'] = 'deformacion_temporal_en_evaluacion'
            zona_aprendida['diagnostico_roi_deformacion'] = propuesta_roi
        else:
            zona_alternativa_deformacion = None
            zona_aprendida = zona_candidata_deformacion
    else:
        propuesta_roi = {'confiable':False,'motivo':'desactivado_o_sin_frame'}
        zona_alternativa_deformacion = None
    # El preescaneo usa otro VideoCapture: el principal aún está en 0.
    cfg_det = _ajustar_cfg_con_perfil_evento(cfg, perfil_evento)

    # Baseline temporal: unos pocos cuadros iniciales, siempre antes de la
    # apertura. Con la tasa real conocida se acota también por tiempo.
    nbase_min = max(2, int(cfg.get("frames_baseline_min", 3)))
    nbase_max = max(nbase_min, int(cfg.get("frames_baseline_max", 6)))
    objetivo_ms = max(0.1, float(cfg.get("baseline_duracion_objetivo_ms", 0.6)))
    # Misma regla de tasa real que el resto del módulo (Rec…fps, forzado en
    # config.yaml o contenedor plausible); nunca los 8 fps de reproducción.
    fps_baseline, _ = fps_temporal_confiable(fps_rec_inicial, fps_archivo, {"video_airbag": cfg})
    if fps_baseline:
        estimado = int(round(fps_baseline * objetivo_ms / 1000.0))
    else:
        estimado = nbase_min
    nbase_obj = max(nbase_min, min(nbase_max, max(2, estimado)))
    if fps_baseline:
        tope_ms = max(0.1, float(cfg.get("baseline_max_ms", 1.0)))
        nbase_obj = min(nbase_obj, max(2, int(float(fps_baseline) * tope_ms / 1000.0)))

    ventana_conf = max(2, int(cfg_det.get("ventana_confirmacion_frames", 5)))
    max_back = max(1, int(cfg_det.get("backtracking_max_frames", 7)))
    detener = bool(cfg.get("detener_tras_confirmacion", True))
    medir_llenado = bool(cfg_det.get("medir_llenado_visual", True))
    llenado_max_frames = max(8, int(cfg_det.get("llenado_max_frames", 160)))
    limite_llenado_frame = None
    # Cuadros originales recientes: el candidato se toma de aquí y no por seek,
    # que en algunos códecs cae en otro cuadro y desincroniza el overlay.
    recientes: deque[tuple[int, np.ndarray]] = deque(maxlen=max_back + ventana_conf + 1)

    frames_base: list[np.ndarray] = []
    scores: list[float] = []
    metricas_blanco: list[dict] = []
    indice = 0
    baseline = None
    ruido_base: dict = {}
    umbral = float(cfg.get("umbral_diff_min", 6.0))
    confirmacion = None
    detenido_en = None
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        recientes.append((indice, frame))
        gris = _redimensionar_gris(
            frame, max(ancho, frame.shape[1]) if cfg.get("analisis_resolucion_nativa", True) else max_ancho)
        roi = _roi_deteccion_aprendida(gris, zona_aprendida, margen)
        if indice < nbase_obj:
            frames_base.append(roi.astype(np.float32))
            scores.append(0.0)
            metricas_blanco.append({
                "detectado": False, "evidencia_debil": False,
                "pixeles_blanco_nuevo": 0, "fraccion_blanco_nuevo": 0.0,
                "componente_blanco_px": 0, "fraccion_componente_blanco": 0.0,
                "fraccion_borde_nuevo": 0.0, "centro_componente_norm": None,
                "bbox_componente_norm": None,
            })
        else:
            if baseline is None:
                baseline = np.median(np.stack(frames_base, axis=0), axis=0).astype(np.uint8)
                # El ruido se mide sólo con cuadros anteriores a cualquier evento.
                ruido_base = _ruido_baseline(frames_base, cfg_det)
                umbral = max(umbral, 2.0 * float(ruido_base.get("score_max") or 0.0))
            diff = cv2.absdiff(roi, baseline)
            diff_mean = float(np.mean(diff))
            delta_claro = cv2.subtract(roi, baseline)
            frac_clara = float(np.mean(delta_claro > 28))
            score = diff_mean + 70.0 * frac_clara
            scores.append(score)
            metricas_blanco.append(_metricas_primer_blanco(roi, baseline, cfg_det, ruido_base))
            # Evaluación en línea. R10 conserva el primer onset confirmado y,
            # si se solicita medir llenado, sigue leyendo una ventana posterior
            # para estimar cuándo el despliegue visible alcanza una meseta.
            if confirmacion is None and (detener or medir_llenado):
                c = indice - (ventana_conf - 1)
                if c >= nbase_obj:
                    hallada = _evaluar_confirmacion(metricas_blanco, scores, umbral,
                                                    nbase_obj, cfg_det, c)
                    if hallada:
                        confirmacion = hallada
                        if medir_llenado:
                            limite_llenado_frame = int(confirmacion.get("frame_inicio", c)) + llenado_max_frames
                        elif detener:
                            detenido_en = indice
                            indice += 1
                            break
            elif confirmacion is not None and medir_llenado and limite_llenado_frame is not None:
                if indice >= limite_llenado_frame:
                    detenido_en = indice
                    indice += 1
                    break
        indice += 1
    cap.release()
    frames_leidos = len(scores)
    total_frames = max(frames_leidos, frames_decl) if detenido_en is not None else frames_leidos
    # V15.9: los cuadros de referencia también se auditan. Si el baseline ya
    # muestra la bolsa, el nacimiento es anterior al clip: incertidumbre
    # explícita (evento_al_inicio), nunca un origen inventado en el frame 0.
    deteccion_inicio = (_baseline_contiene_evento(frames_base, cfg_det) if len(frames_base) >= 2
                        else {"evento_al_inicio": False, "evidencia_baseline": []})
    evento_al_inicio = bool(deteccion_inicio.get("evento_al_inicio"))
    if frames_leidos <= nbase_obj:
        return {"ruta": str(ruta), "nombre": ruta.name, "estado": "error",
                "error": "El video contiene muy pocos cuadros para analizar.", "firma": firma,
                "fps": fps_temporal_pre, "fps_archivo": fps_archivo, "total_frames": total_frames,
                "zona_deteccion": zona_aprendida, "baseline_frames": nbase_obj}

    if confirmacion is None:
        confirmacion = _buscar_inicio_confirmado(metricas_blanco, scores, umbral, nbase_obj, cfg_det)
    # Si la ROI original falla, ensayar la sugerida por deformación con
    # EXACTAMENTE el mismo criterio físico. Comparar ANTES de calcular el
    # evento, el consenso y el color (en 16.0.8 el rescate sucedía demasiado tarde).
    comparacion_roi = {'seleccion': 'roi_original', 'motivo':
                       'apertura_detectada' if confirmacion else 'sin_apertura_en_roi_original'}
    # V16.0.10: evaluar SIEMPRE la alternativa cuando difiere espacialmente:
    # en 16.0.9 una falsa apertura en la ROI original impedia compararla.
    if (zona_alternativa_deformacion is not None
            and bool(cfg.get('roi_deformacion_comparar_regiones', True))):
        # Una ROI de deformacion tardia no puede compararse usando solo los
        # primeros 90 fotogramas de un evento anterior. Incluir el indicio de
        # deformacion si cae dentro del tope explícito de coste.
        limite_roi = max(90, min(2500, int(cfg.get('roi_deformacion_ventana_secundaria',750))))
        cuadro_def = zona_alternativa_deformacion.get('frame_deformacion')
        cuadro_def = (cuadro_def if isinstance(cuadro_def,int) and cuadro_def>=0 else 0)
        ventana_roi = (min(limite_roi,max(90, int(confirmacion['frame_inicio'])+45,
                                          cuadro_def+45)) if confirmacion else limite_roi)
        alternativa = _analizar_roi_secundaria(
            ruta, zona_alternativa_deformacion, cfg_det, nbase_obj,
            margen, max_ancho, ventana_conf, ventana_roi)
        comparacion_roi = {k:v for k,v in alternativa.items()
                           if k not in {'scores','metricas','baseline_frames','ruido','umbral','confirmacion'}}
        original_frame = confirmacion.get('frame_inicio') if confirmacion else None
        original_evidencia = (_evidencia_fisica_temporal(metricas_blanco,original_frame)
                             if isinstance(original_frame,int) else {"nivel":"ninguna"})
        alterno_frame = alternativa.get('frame_candidato') if alternativa.get('aceptada') else None
        alterna_evidencia = alternativa.get('evidencia_fisica') or {"nivel":"ninguna"}
        comparacion_roi['original'] = {"cuadro":original_frame,"evidencia":original_evidencia}
        comparacion_roi['alternativa'] = {"cuadro":alterno_frame,"evidencia":alterna_evidencia}
        # El ROI de deformacion no gana solo por ser mas temprano.
        # Si ambas señales son fisicamente validas y difieren mucho, no
        # seleccionar una con certeza falsa: lo decidiran otras camaras.
        if (isinstance(original_frame,int) and isinstance(alterno_frame,int) and
                abs(original_frame-alterno_frame)>6 and
                original_evidencia['nivel'] in {'fuerte','compatible'} and
                alterna_evidencia['nivel'] in {'fuerte','compatible'}):
            comparacion_roi['seleccion']='conflicto_dos_rois'
            comparacion_roi['conflicto']=True
        elif (alternativa.get('aceptada') and
              (not isinstance(original_frame,int) or
               (original_evidencia['nivel'] not in {'fuerte','compatible'} and
                alterna_evidencia['nivel'] in {'fuerte','compatible'}))):
            scores=alternativa['scores']
            metricas_blanco=alternativa['metricas']
            frames_base=alternativa['baseline_frames']
            ruido_base=alternativa['ruido']
            umbral=alternativa['umbral']
            confirmacion=alternativa['confirmacion']
            zona_aprendida=dict(zona_alternativa_deformacion)
            zona_aprendida['validacion_ruptura_local']=True
            zona_aprendida['frames_validacion_local']=alternativa['frames_soporte']
            comparacion_roi['seleccion']='roi_deformacion_validada'
        else:
            comparacion_roi['seleccion']='roi_original' if confirmacion else 'sin_roi_confirmada'
    comparacion_roi.setdefault('conflicto',False)
    # Una ROI ya existente puede quedar realmente validada por ruptura local:
    # no mantener la etiqueta de ROI incierta solo porque fue autoalineada.
    if confirmacion and isinstance(zona_aprendida,dict) and zona_aprendida.get('activa'):
        ev_original = _evidencia_fisica_temporal(
            metricas_blanco, int(confirmacion['frame_inicio']))
        if ev_original['nivel']=='fuerte' and not comparacion_roi.get('conflicto'):
            zona_aprendida = dict(zona_aprendida)
            zona_aprendida['validacion_ruptura_local']=True
            zona_aprendida['frames_validacion_local']=ev_original['cuadros_fisicos']
    candidato = confirmacion.get("frame_inicio") if confirmacion else None
    tipo_deteccion = "primer_blanco_nuevo" if candidato is not None else None

    # Fallback conservador V15.2: si no hubo crecimiento cuantificable, acepta
    # una aparición normal sólo cuando persiste de manera consecutiva.
    persistencia = max(1, int(cfg.get("persistencia_frames", 2)))
    if candidato is None and bool(cfg.get("permitir_persistencia_sin_crecimiento", False)):
        for i in range(nbase_obj, frames_leidos - persistencia + 1):
            if not metricas_blanco[i].get("detectado"):
                continue
            if all(metricas_blanco[j].get("detectado") for j in range(i, i + persistencia)):
                candidato = i
                confirmacion = {
                    "frame_inicio": i, "frame_confirmacion": i + persistencia - 1,
                    "retroceso_frames": persistencia - 1, "crecimiento_ratio": 1.0,
                    "max_componente_px": max(int(metricas_blanco[j].get("componente_blanco_px") or 0)
                                              for j in range(i, i + persistencia)),
                    "metodo": "persistencia_sin_crecimiento",
                }
                tipo_deteccion = "primer_blanco_nuevo"
                break

    if candidato is None and bool(cfg.get("rescate_cambio_general", False)):
        for i in range(nbase_obj, frames_leidos - persistencia + 1):
            if all(scores[j] >= umbral for j in range(i, i + persistencia)):
                candidato = i
                confirmacion = {"frame_inicio": i, "frame_confirmacion": i + persistencia - 1,
                                "retroceso_frames": persistencia - 1, "crecimiento_ratio": 1.0,
                                "metodo": "cambio_general"}
                tipo_deteccion = "cambio_general"
                break
    if candidato is None and bool(cfg.get("rescate_cambio_general", False)):
        deltas = [(scores[i] - scores[i - 1], i) for i in range(nbase_obj + 1, frames_leidos)]
        salto, pos = max(deltas, default=(0.0, nbase_obj))
        if salto >= max(3.0, umbral * 0.35):
            candidato = pos
            confirmacion = {"frame_inicio": pos, "frame_confirmacion": pos,
                            "retroceso_frames": 0, "crecimiento_ratio": 1.0,
                            "metodo": "salto_general"}
            tipo_deteccion = "salto_general"

    if candidato is None:
        resultado = {"ruta": str(ruta), "nombre": ruta.name, "firma": firma,
                     "estado": "sin_evento",
                     "estado_evento": "evento_al_inicio" if evento_al_inicio else "sin_evento",
                     "fps": fps_temporal_pre,
                     "fps_archivo": fps_archivo,
                     "fps_grabacion": (float(fps_rec_inicial) if fps_rec_inicial else None),
                     "fps_fuente": ("overlay_rec" if fps_rec_inicial else "archivo"),
                     "total_frames": total_frames,
                     "ancho": ancho, "alto": alto, "umbral": round(umbral, 4),
                     "resolucion_nativa_ms": (round(resolucion_pre, 6) if resolucion_pre else None),
                     "overlay_texto": overlay_inicial.get("texto", ""),
                     "overlay_timestamp_inicial_ms": _numero_finito_con_signo(overlay_inicial.get("timestamp_esquina_ms")),
                     "confianza": 0.0, "score_apertura": 0.0, "desde_cache": False,
                     "algoritmo_video": ALGORITMO_VERSION,
                     "zona_deteccion": zona_aprendida,
                     "tipo_camara": zona_aprendida.get("tipo_camara"),
                     "baseline_frames": nbase_obj,
                     "perfil_evento_aprendido": perfil_evento}
        if evento_al_inicio:
            # Apertura visible desde el primer cuadro: se marca y se conserva el
            # primer indicio, pero no se afirma que el frame 0 sea el nacimiento
            # exacto (tiempo_ms queda vacío y sólo hay tiempo sospechoso).
            resultado["estado"] = "evento_al_inicio"
            resultado["frame_evento"] = 0
            resultado["frame_evento_confiable"] = False
            resultado["tiempo_ms"] = None
            resultado["tiempo_ms_sospechoso"] = 0.0
    else:
        actual = scores[candidato]
        mb = ((confirmacion or {}).get("metricas_inicio") or
              (metricas_blanco[candidato] if candidato < len(metricas_blanco) else {}))
        crecimiento = float((confirmacion or {}).get("crecimiento_ratio") or 1.0)
        score_apertura = _puntaje_apertura(mb, actual, umbral, crecimiento,
                                           zona_aprendida, perfil_evento)
        if (confirmacion or {}).get("metodo") == "crecimiento_backtracking":
            confianza = max(0.72, min(0.99, 0.62 + 0.37 * score_apertura))
        elif tipo_deteccion == "primer_blanco_nuevo":
            confianza = max(0.62, min(0.92, 0.55 + 0.32 * score_apertura))
        else:
            confianza = max(0.45, min(0.88, 0.45 + 0.30 * score_apertura))

        frame_evento = next((f for i, f in recientes if i == candidato), None)
        ok = frame_evento is not None
        if not ok:
            cap2 = cv2.VideoCapture(str(ruta))
            # Un indicio de 1 px puede permanecer más que el ring antes de
            # crecer. Se vuelve a decodificar hasta él sin seek por keyframe:
            # no se guarda todo el vídeo ni se arriesga leer otro fotograma.
            try:
                for _ in range(candidato + 1):
                    ok, frame_evento = cap2.read()
                    if not ok:
                        break
            finally:
                cap2.release()
        advertencia_deteccion = None
        if evento_al_inicio:
            # V15.9: el baseline ya muestra la bolsa. No se fija un nacimiento
            # artificial: queda incertidumbre explícita y revisión humana.
            confianza = min(confianza, 0.5)
            advertencia_deteccion = (
                "Los cuadros de referencia ya muestran evidencia de despliegue: "
                "el nacimiento es anterior al vídeo. Revisa el clip completo; "
                "no se asigna un tiempo de apertura automático.")
        elif (confirmacion or {}).get("inicio_en_borde_baseline"):
            # La bolsa ya podría verse dentro de los cuadros de referencia.
            confianza = min(confianza, 0.6)
            advertencia_deteccion = (
                "La evidencia empieza justo después de los cuadros de referencia; "
                "la bolsa podría ser visible antes. Revísalo cuadro por cuadro.")
        overlay = (_leer_overlay(frame_evento, config) if ok else
                   {"texto": "", "tiempos_ms": [], "fps_grabacion": [],
                    "timestamp_esquina_ms": None, "precision_timestamp_esquina_ms": None,
                    "texto_esquina": "", "error": None})
        fps_rec_vals = list(overlay.get("fps_grabacion") or []) or list(overlay_inicial.get("fps_grabacion") or [])
        fps_grabacion = float(fps_rec_vals[0]) if fps_rec_vals else None
        control_fps = validar_fps_con_reloj(
            fps_grabacion, candidato, overlay.get("timestamp_esquina_ms"),
            overlay_inicial.get("timestamp_esquina_ms"),
            leer_reloj=lambda f: leer_timestamp_esquina_frame(ruta, f, config).get("timestamp_ms"),
            total_frames=total_frames)
        if control_fps.get("corregido"):
            fps_grabacion = float(control_fps["fps"])
        fps_temporal = fps_grabacion or fps_archivo
        resolucion = (1000.0 / fps_temporal) if fps_temporal > 0 else None
        tiempo_fps = (candidato / fps_temporal * 1000.0) if fps_temporal > 0 else None

        tiempo_esquina = overlay.get("timestamp_esquina_ms")
        precision_esquina = overlay.get("precision_timestamp_esquina_ms")
        tiempo_resuelto = resolver_tiempo_metadata(
            frame_index=candidato, fps=fps_temporal,
            timestamp_actual_ms=tiempo_esquina,
            timestamp_inicial_ms=overlay_inicial.get("timestamp_esquina_ms"),
            precision_overlay_ms=precision_esquina, config=config)
        tiempo_overlay = tiempo_resuelto.get("tiempo_overlay_ms")
        tiempo = tiempo_resuelto.get("tiempo_ms")
        fuente = tiempo_resuelto.get("fuente_tiempo")
        precision = (precision_esquina if tiempo_resuelto.get("overlay_valido") else resolucion)
        if tiempo_resuelto.get("overlay_valido"):
            confianza = max(confianza, 0.93)
        offset_overlay = None
        if tiempo_overlay is not None and tiempo_fps is not None and tiempo_resuelto.get("overlay_valido"):
            offset_overlay = float(tiempo_overlay) - float(tiempo_fps)
        resultado = {
            "ruta": str(ruta), "nombre": ruta.name, "firma": firma,
            "estado": ("evento_al_inicio" if evento_al_inicio else "candidato"),
            "estado_evento": ("evento_al_inicio" if evento_al_inicio else
                              "propuesto" if tipo_deteccion != "primer_blanco_nuevo"
                              else "confirmado"),
            "fps": fps_temporal,
            "fps_archivo": fps_archivo, "fps_grabacion": fps_grabacion,
            "fps_fuente": ("reloj_overlay" if control_fps.get("corregido") else
                           "overlay_rec" if fps_grabacion else "archivo"),
            "fps_validado_reloj": (fps_grabacion if control_fps.get("corregido") else None),
            "fps_segun_reloj": control_fps.get("fps_reloj"),
            "advertencia_fps": control_fps.get("advertencia"),
            "total_frames": total_frames, "ancho": ancho, "alto": alto,
            "frame_evento": int(candidato),
            "frame_evento_confiable": not evento_al_inicio,
            "tiempo_ms_sospechoso": (None if tiempo is None or not evento_al_inicio
                                     else round(float(tiempo), 1)),
            "frame_confirmacion_automatica": int((confirmacion or {}).get("frame_confirmacion", candidato)),
            "retroceso_frames": int((confirmacion or {}).get("retroceso_frames", 0)),
            "crecimiento_ratio": round(crecimiento, 4),
            "metodo_confirmacion": (confirmacion or {}).get("metodo"),
            "score_evento": round(float(actual), 4), "umbral": round(float(umbral), 4),
            "score_apertura": round(float(score_apertura), 4),
            "tiempo_ms": (None if tiempo is None or evento_al_inicio
                          else round(float(tiempo), 1)),
            "tiempo_fps_ms": None if tiempo_fps is None else round(float(tiempo_fps), 3),
            "tiempo_subframe_estimado_ms": None,
            "tiempo_overlay_ms": tiempo_overlay,
            "tiempo_overlay_leido_ms": tiempo_resuelto.get("tiempo_overlay_leido_ms"),
            "fuente_tiempo": fuente,
            "resolucion_nativa_ms": None if resolucion is None else round(float(resolucion), 6),
            "precision_fuente_ms": None if precision is None else round(float(precision), 6),
            "exactitud_0_1ms_sustentada": bool(precision is not None and precision <= 0.1000001),
            "estimacion_subframe": False,
            "confianza": round(float(confianza), 4),
            "overlay_texto": overlay.get("texto", ""),
            "overlay_texto_esquina": overlay.get("texto_esquina", ""),
            "overlay_timestamp_inicial_ms": _numero_finito_con_signo(overlay_inicial.get("timestamp_esquina_ms")),
            "offset_overlay_ms": None if offset_overlay is None else round(offset_overlay, 6),
            "discrepancia_tiempo_ms": tiempo_resuelto.get("discrepancia_ms"),
            "advertencia_tiempo": tiempo_resuelto.get("advertencia"),
            "overlay_validado": bool(tiempo_resuelto.get("overlay_valido")),
            "overlay_error": overlay.get("error"), "tipo_deteccion": tipo_deteccion,
            "pixeles_blanco_nuevo": int(mb.get("pixeles_blanco_nuevo") or 0),
            "pixeles_grieta_nueva": int(mb.get("pixeles_grieta_nueva") or 0),
            "pixeles_ruptura": int(mb.get("pixeles_ruptura") or 0),
            "componente_ruptura_px": int(mb.get("componente_ruptura_px") or 0),
            "indicio_un_pixel": bool((confirmacion or {}).get("indicio_un_pixel")),
            "fraccion_blanco_nuevo": round(float(mb.get("fraccion_blanco_nuevo") or 0.0), 8),
            "componente_blanco_px": int(mb.get("componente_blanco_px") or 0),
            "fraccion_componente_blanco": round(float(mb.get("fraccion_componente_blanco") or 0.0), 8),
            "fraccion_borde_nuevo": round(float(mb.get("fraccion_borde_nuevo") or 0.0), 8),
            "material_nuevo_en_rango_px": int(mb.get("material_nuevo_en_rango_px") or 0),
            "fraccion_material_en_rango": round(float(mb.get("fraccion_material_en_rango") or 0.0), 8),
            "area_bolsa_visible_estimada_px": int(mb.get("area_bolsa_visible_estimada_px") or 0),
            "fraccion_bolsa_visible_estimada": round(float(mb.get("fraccion_bolsa_visible_estimada") or 0.0), 8),
            "deformacion_confiable": bool(mb.get("deformacion_confiable")),
            "proximidad_deformacion": mb.get("proximidad_deformacion"),
            "deformacion_local": mb.get("deformacion_local") if isinstance(mb.get("deformacion_local"), dict) else {},
            "desde_cache": False, "algoritmo_video": ALGORITMO_VERSION,
            "zona_deteccion": zona_aprendida, "tipo_camara": zona_aprendida.get("tipo_camara"),
            "baseline_frames": nbase_obj, "perfil_evento_aprendido": perfil_evento,
            "antes_limpio": bool((confirmacion or {}).get("antes_limpio")),
            "inicio_en_borde_baseline": bool((confirmacion or {}).get("inicio_en_borde_baseline")),
            "advertencia_deteccion": advertencia_deteccion,
            "pixeles_sin_compensar": int(mb.get("pixeles_sin_compensar") or 0),
        }
    resultado["comparacion_roi_v1609"] = comparacion_roi
    resultado["comparacion_roi_v1610"] = comparacion_roi
    resultado["roi_arbitraje_conflicto"] = bool(comparacion_roi.get('conflicto'))
    resultado["ruido_baseline"] = ruido_base
    resultado.setdefault("estado_evento",
                         "evento_al_inicio" if evento_al_inicio else "sin_evento")
    resultado["evento_al_inicio"] = evento_al_inicio
    resultado["evidencia_baseline"] = deteccion_inicio.get("evidencia_baseline") or []
    resultado["definicion_evento"] = "Primer contorno visible de ruptura corroborado; no abombamiento."
    resultado["razones_evento"] = _razones_evento(
        resultado, metricas_blanco, confirmacion, zona_aprendida, deteccion_inicio)
    resultado["compensacion_movimiento"] = bool(cfg.get("compensar_movimiento", True))
    resultado["analisis_resolucion_nativa"] = bool(cfg.get("analisis_resolucion_nativa", True))
    resultado["requiere_revision"] = True
    # V15.9.2 (C2): esta bandera del detector heurístico es INFORMATIVA por
    # diseño (pide revisar el fotograma, inherente a todo resultado
    # automático): no es una alerta sin clasificar y no bloquea por sí sola
    # una confirmación limpia en el consolidado.
    resultado["revision_informativa"] = True
    resultado["validado_con_videos_reales"] = False
    resultado["parametros_ruptura"] = {
        "incremento_minimo": int(cfg_det.get("umbral_incremento_blanco", 18)),
        "discontinuidad_local_minima": float(cfg_det.get("umbral_discontinuidad_nueva", 6.0)),
        "pixeles_indicio_minimos": int(cfg_det.get("min_pixeles_indicio", 1)),
        "radio_seguimiento_px": float(cfg_det.get("radio_indicio_px", 3.0)),
        "frames_confirmacion_minimos": int(cfg_det.get("min_frames_confirmacion", 2)),
        "crecimiento_minimo": float(cfg_det.get("crecimiento_ratio_min", 1.8)),
    }
    resultado["limitacion_detector"] = (
        "Candidato heurístico pendiente de validación con vídeos reales: ruido, compresión, "
        "reflejos o sombras pueden ocultar o imitar un píxel de ruptura. Revisar el fotograma propuesto.")
    resultado["frames_leidos"] = frames_leidos
    # V15.9.1 (A8): métricas de rendimiento del detector por video, para el
    # benchmark V15.8.1 vs V15.9 (latencia de la correlación de fase).
    _fase_ms = sorted(float(m.get("fase_correlate_ms") or 0.0) for m in metricas_blanco)
    if _fase_ms:
        _p95 = _fase_ms[max(0, int(round(0.95 * (len(_fase_ms) - 1))))]
        resultado["rendimiento_detector"] = {
            "frames": len(_fase_ms),
            "fase_correlate_ms_total": round(sum(_fase_ms), 3),
            "fase_correlate_ms_media": round(sum(_fase_ms) / len(_fase_ms), 4),
            "fase_correlate_ms_p95": round(_p95, 4),
        }
    if any(m.get("componentes_indicio_truncados") for m in metricas_blanco):
        resultado["advertencia_componentes"] = (
            "Hay más contornos que el límite de seguimiento; un indicio pequeño "
            "podría quedar fuera. Ajustar la ROI a la costura y revisar manualmente.")
    if (candidato is None and metricas_blanco and
            metricas_blanco[-1].get("evidencia_debil")):
        resultado["advertencia_deteccion"] = (
            "El vídeo termina con un indicio sin suficiente crecimiento posterior "
            "para corroborar su primer fotograma. Revisar el final del clip.")
    rev = revision_video(ruta)
    if rev:
        resultado["revision_manual"] = rev

    # V15.10.1: ranking de hipótesis y contra-revisión en modo sombra. No
    # sustituye el detector legado, no cambia su tiempo publicado y no se
    # interpreta como probabilidad. El tiempo calculado aquí es local al clip.
    # R10: para color estimado sólo usamos una tasa de captura defendible.
    # Nunca se convierte un AVI de reproducción a 8 fps en 125 ms/cuadro.
    fps_estandar, fuente_fps_estandar = fps_temporal_confiable(
        fps_rec_inicial, fps_archivo, config)
    candidatos_sombra = generar_candidatos(
        metricas_blanco, nbase=nbase_obj, fps_adquisicion=fps_estandar,
        max_candidatos=12, max_hueco_frames=2,
        ventana_corrobora=max(5, int(cfg_det.get("onset_corrobora_max_frames", 48))))
    for candidato_sombra in candidatos_sombra:
        verificacion = verificar_candidato(
            candidato_sombra, metricas_blanco, nbase=nbase_obj,
            calidad_video=None,
            calidad_roi={
                "alineacion_confiable": not bool(
                    isinstance(zona_aprendida, dict) and zona_aprendida.get("activa")
                    and zona_aprendida.get("bloqueada") is False
                    and not zona_aprendida.get("validacion_ruptura_local")),
                "ocluida": None,
            },
            advertencias=[x for x in (
                resultado.get("advertencia_fps"), resultado.get("advertencia_tiempo"),
                resultado.get("advertencia_deteccion")) if x])
        candidato_sombra["verificacion"] = verificacion
        frame_sombra = candidato_sombra.get("frame")
        try:
            frame_sombra_int = int(frame_sombra)
            metrica_sombra = metricas_blanco[frame_sombra_int]
        except (TypeError, ValueError, IndexError):
            frame_sombra_int = None
            metrica_sombra = {}
        frames_apoyo = candidato_sombra.get("frames_evidencia") or []
        ventana_estandar = []
        for frame_apoyo in frames_apoyo:
            try:
                ventana_estandar.append(metricas_blanco[int(frame_apoyo)])
            except (TypeError, ValueError, IndexError):
                continue
        candidato_sombra["evaluacion_estandar"] = evaluar_evidencia_estandar(
            candidato_sombra, verificacion, metrica_sombra,
            metricas_ventana=ventana_estandar,
            umbral_alta=float(cfg_det.get("auto_color_evidencia_min", 0.56)))
        tiempo_color = candidato_sombra.get("tiempo_local_ms")
        try:
            tiempo_color_num = float(tiempo_color) if tiempo_color is not None else None
        except (TypeError, ValueError, OverflowError):
            tiempo_color_num = None
        referencia_color = bool(
            fps_estandar is not None and tiempo_color_num is not None
            and math.isfinite(tiempo_color_num) and tiempo_color_num > 0
        )
        candidato_sombra["tiempo_color_estimado_ms"] = (
            round(tiempo_color_num, 6) if referencia_color else None)
        candidato_sombra["referencia_color_valida"] = referencia_color
        candidato_sombra["fuente_tiempo_color"] = fuente_fps_estandar or "desconocido"
        candidato_sombra["tiempo_ms"] = candidato_sombra.get("tiempo_local_ms")
    revision_politica = None
    if rev:
        if rev.get("estado") == "confirmado":
            raw_revision = rev.get("raw_time_ms")
            if raw_revision is None:
                raw_revision = rev.get("tiempo_ms")
            try:
                frame_revision_valido = (rev.get("frame_index") is not None
                                         and int(rev.get("frame_index")) >= 0)
            except (TypeError, ValueError, OverflowError):
                frame_revision_valido = False
            tiempo_revision_valido = (_tiempo_apertura_positivo(raw_revision) is not None
                                      and frame_revision_valido
                                      and _referencia_temporal_valida(rev)
                                      and rev.get("estado_tiempo") not in {
                                          "NO_FINITO", "NO_POSITIVO", "NO_INTERPRETABLE",
                                          "REFERENCIA_INVALIDA", "PENDIENTE"})
            revision_politica = ({"estado": "confirmado", "tiempo_ms": raw_revision}
                                 if tiempo_revision_valido else {"estado": "pendiente"})
        elif rev.get("estado") == "sin_evento":
            revision_politica = {"estado": "sin_evento"}
    # Elegir el PRIMER candidato temporal que ya quedó corroborado por el
    # estándar. Si ninguno alcanza alta evidencia, conservar el mejor score para
    # revisión. Así un cuadro posterior más grande no desplaza el onset real.
    candidatos_colorables = [
        c for c in candidatos_sombra
        if isinstance(c.get("evaluacion_estandar"), dict)
        and c["evaluacion_estandar"].get("auto_colorable") is True
    ]
    candidato_estandar = (min(candidatos_colorables, key=lambda c: int(c.get("frame") or 10**9))
                          if candidatos_colorables else
                          (max(candidatos_sombra, key=lambda c: float((c.get("evaluacion_estandar") or {}).get("score_evidencia") or 0.0))
                           if candidatos_sombra else None))

    # R11: el estándar deja de ser sólo una hipótesis paralela. Si existe un
    # candidato de ALTA evidencia, el PRIMER onset defendible gobierna el
    # ``frame_evento`` canónico. El detector legado se conserva como auditoría
    # (frame_evento_legacy/tiempo_ms_legacy), pero un cuadro posterior más
    # grande ya no desplaza el primer instante físico de ruptura.
    eval_estandar = (candidato_estandar.get("evaluacion_estandar")
                     if isinstance(candidato_estandar, dict) else {}) or {}
    promover_estandar = bool(
        isinstance(candidato_estandar, dict)
        and eval_estandar.get("auto_colorable") is True
        and not evento_al_inicio
    )
    if promover_estandar:
        try:
            frame_std = int(candidato_estandar.get("frame"))
        except (TypeError, ValueError, OverflowError):
            frame_std = -1
        try:
            frame_legacy = int(resultado.get("frame_evento")) if resultado.get("frame_evento") is not None else None
        except (TypeError, ValueError, OverflowError):
            frame_legacy = None
        if 0 <= frame_std < len(metricas_blanco) and (frame_legacy is None or frame_std < frame_legacy):
            metrica_std = metricas_blanco[frame_std]
            frame_conf_std = candidato_estandar.get("frame_confirmacion_sugerido")
            try:
                frame_conf_std = int(frame_conf_std)
            except (TypeError, ValueError, OverflowError):
                frame_conf_std = frame_std
            if frame_conf_std <= frame_std:
                apoyos_std = [int(x) for x in (candidato_estandar.get("frames_evidencia") or [])
                               if str(x).lstrip("-").isdigit()]
                frame_conf_std = max(apoyos_std) if apoyos_std else frame_std

            resultado["frame_evento_legacy"] = resultado.get("frame_evento")
            resultado["tiempo_ms_legacy"] = resultado.get("tiempo_ms")
            resultado["metodo_confirmacion_legacy"] = resultado.get("metodo_confirmacion")
            resultado["frame_evento"] = frame_std
            resultado["frame_evento_confiable"] = True
            resultado["frame_confirmacion_automatica"] = frame_conf_std
            resultado["retroceso_frames"] = max(0, frame_conf_std - frame_std)
            resultado["metodo_confirmacion"] = "estandar_r13_breakout_defendible"
            resultado["tipo_deteccion"] = "primer_onset_defendible"
            resultado["estado"] = "candidato"
            resultado["estado_evento"] = "confirmado"
            resultado["antes_limpio"] = bool(int(candidato_estandar.get("frames_previos_limpios") or 0) >= 1)
            # La métrica agregada del cuadro puede sumar otra microzona (p. ej.
            # un hot-pixel lejano). Para saber si el onset canónico fue un solo
            # píxel debemos usar el componente que originó el candidato.
            pix_std = int(candidato_estandar.get("pixeles_ruptura") or
                          metrica_std.get("pixeles_ruptura") or 0)
            resultado["indicio_un_pixel"] = bool(pix_std == 1)
            for clave_std in (
                "pixeles_blanco_nuevo", "pixeles_grieta_nueva", "pixeles_ruptura",
                "componente_ruptura_px", "componente_blanco_px",
                "material_nuevo_en_rango_px", "deformacion_confiable",
                "proximidad_deformacion", "deformacion_local", "pixeles_sin_compensar",
            ):
                if clave_std in metrica_std:
                    resultado[clave_std] = metrica_std.get(clave_std)
            for clave_std in (
                "fraccion_blanco_nuevo", "fraccion_componente_blanco",
                "fraccion_borde_nuevo", "fraccion_material_en_rango",
            ):
                if clave_std in metrica_std:
                    resultado[clave_std] = round(float(metrica_std.get(clave_std) or 0.0), 8)

            resultado["score_apertura"] = round(float(eval_estandar.get("score_evidencia") or 0.0), 4)
            resultado["confianza"] = max(float(resultado.get("confianza") or 0.0),
                                        min(0.96, 0.62 + 0.34 * float(eval_estandar.get("score_evidencia") or 0.0)))
            if fps_estandar is not None and fps_estandar > 0:
                tiempo_std = frame_std * 1000.0 / float(fps_estandar)
                resultado["fps"] = float(fps_estandar)
                resultado["fps_fuente"] = fuente_fps_estandar or resultado.get("fps_fuente")
                resultado["resolucion_nativa_ms"] = round(1000.0 / float(fps_estandar), 6)
                resultado["tiempo_fps_ms"] = round(tiempo_std, 6)
                resultado["tiempo_ms"] = round(tiempo_std, 6)
                resultado["fuente_tiempo"] = fuente_fps_estandar or "fps_captura_estandar"
            else:
                # No conservar el tiempo del frame legado para un onset distinto.
                resultado["tiempo_ms"] = None
                resultado["tiempo_fps_ms"] = None
                resultado["fuente_tiempo"] = "onset_visual_sin_referencia_temporal"
            resultado["onset_promovido_por_estandar"] = True
            resultado["version_onset_canonico"] = "r13-breakout-defendible"
            confirmacion_std = {
                "frame_inicio": frame_std,
                "frame_confirmacion": frame_conf_std,
                "retroceso_frames": max(0, frame_conf_std - frame_std),
                "crecimiento_ratio": eval_estandar.get("crecimiento_ratio"),
                "metodo": "estandar_r13_breakout_defendible",
                "metricas_inicio": metrica_std,
                "antes_limpio": resultado.get("antes_limpio"),
                "indicio_un_pixel": resultado.get("indicio_un_pixel"),
            }
            resultado["razones_evento"] = _razones_evento(
                resultado, metricas_blanco, confirmacion_std, zona_aprendida, deteccion_inicio)

    # R10/R11: el inicio puede quedar defendido por un solo video. A partir de ese
    # onset medimos además cuánto tarda el despliegue visible en llegar a una
    # meseta. Es una duración visual, no una medición de volumen/presión.
    frame_onset_llenado = (candidato_estandar.get("frame") if candidato_estandar else candidato)
    llenado_visual = estimar_llenado_visual(
        metricas_blanco, frame_onset_llenado, fps_estandar,
        fraccion_objetivo=float(cfg_det.get("llenado_fraccion_objetivo", 0.90)),
        estabilidad_frames=int(cfg_det.get("llenado_estabilidad_frames", 3)),
        tolerancia_rel=float(cfg_det.get("llenado_tolerancia_rel", 0.18)),
        max_frames=int(cfg_det.get("llenado_max_frames", 160)),
    ) if bool(cfg_det.get("medir_llenado_visual", True)) else {
        "estado": "deshabilitado", "frame_llenado": None,
        "duracion_llenado_frames": None, "duracion_llenado_ms": None}
    resultado["llenado_visual"] = llenado_visual
    resultado["frame_llenado_estimado"] = llenado_visual.get("frame_llenado")
    resultado["duracion_llenado_estimada_ms"] = llenado_visual.get("duracion_llenado_ms")
    resultado["duracion_llenado_es_estimacion_visual"] = True
    secuencia_r13 = analizar_secuencia_despliegue(
        metricas_blanco, frame_onset_llenado, fps_estandar,
        max_frames=int(cfg_det.get("maximo_inflado_max_frames", 240)),
        fraccion_maximo=float(cfg_det.get("maximo_inflado_fraccion", 0.97)),
        estabilidad_frames=int(cfg_det.get("maximo_inflado_estabilidad_frames", 3)),
        caida_confirmacion=float(cfg_det.get("maximo_inflado_caida_confirmacion", 0.04)),
    )
    resultado["secuencia_despliegue_r13"] = secuencia_r13
    # V16.0.3: el detector de ruptura puede emplear una ROI pequeña para
    # preservar precisión. Para el máximo se abre una segunda lectura que
    # examina el FOTOGRAMA COMPLETO y rastrea el objeto iniciado allí.
    # Nunca degradar un análisis por fallos en esta vía experimental.
    resultado["maximo_global_v16"] = {"estado": "no_ejecutado", "experimental": True}
    if (cfg_det.get("maximo_global_habilitado", True)
            and isinstance(frame_onset_llenado, int)
            and frame_onset_llenado >= 0):
        try:
            from utilidades.inflado_global import analizar_inflado_global
            # Coordenadas globales de la evidencia de onset (la ROI sólo
            # aporta la identidad; el contorno crece sin restricción espacial).
            metrica_semilla = (metricas_blanco[frame_onset_llenado]
                               if frame_onset_llenado < len(metricas_blanco) else {})
            centro = metrica_semilla.get("centro_componente_norm")
            if centro is None:
                caja = metrica_semilla.get("bbox_bolsa_visible_norm")
                if isinstance(caja, (tuple, list)) and len(caja) == 4:
                    centro = [(float(caja[0])+float(caja[2]))/2,
                              (float(caja[1])+float(caja[3]))/2]
            semilla_global = None
            if isinstance(centro,(tuple,list)) and len(centro)==2:
                caja_roi = zona_aprendida.get("bbox_norm") if zona_aprendida.get("activa") else None
                if not isinstance(caja_roi,(tuple,list)) or len(caja_roi)!=4:
                    caja_roi = [0.04, margen, 0.96, 1.0-margen]
                x1,y1,x2,y2 = (float(x) for x in caja_roi)
                semilla_global = (x1+(x2-x1)*float(centro[0]),
                                  y1+(y2-y1)*float(centro[1]))
            max_frames_global = int(cfg_det.get("maximo_global_max_frames",800))
            ventana_ms = float(cfg_det.get("maximo_global_ventana_ms",150.0))
            if fps_estandar and fps_estandar > 0:
                max_frames_global = min(max_frames_global,
                                        max(240,int(math.ceil(fps_estandar*ventana_ms/1000.0))))
            global_raw = analizar_inflado_global(
                ruta, frame_onset_llenado, fps_estandar,
                frame_max_ventana=max_frames_global,
                ancho_analisis=int(cfg_det.get("maximo_global_ancho_max",640)),
                frames_baseline=nbase_obj,
                semilla_norm=semilla_global,
                umbral_cambio=int(cfg_det.get("maximo_global_umbral_cambio",18)))
            global_raw.pop("metricas", None)  # evita guardar cientos de máscaras/métricas en caché
            global_raw["experimental"] = True
            global_raw["no_publicar_automaticamente"] = True
            global_raw["semilla_global_norm"] = semilla_global
            # V16.0.4: la validación de pico pertenece al propio motor global,
            # que puede distinguir fotogramas sin registro fiable de área=0.
            # El estimador ROI previo NO tiene esa información y NO debe
            # reutilizarse aquí como si midiera el mismo tipo de señal.
            if global_raw.get("secuencia"):
                global_raw["publicacion_bloqueada_por_calidad"] = True
            if global_raw.get("anomalías"):
                global_raw["requiere_validacion_visual"] = True
            resultado["maximo_global_v16"] = global_raw
        except (OSError, cv2.error, ValueError, TypeError, KeyError, RuntimeError) as exc:
            resultado["maximo_global_v16"] = {
                "estado":"error_medicion_global", "experimental": True,
                "error":type(exc).__name__, "no_publicar_automaticamente":True}

    resultado["frame_max_inflado_estimado"] = secuencia_r13.get("frame_max_inflado")
    resultado["tiempo_max_inflado_estimado_ms"] = secuencia_r13.get("tiempo_max_inflado_ms")
    resultado["duracion_hasta_max_inflado_ms"] = secuencia_r13.get("duracion_expansion_ms")
    resultado["anomalías_despliegue"] = list(secuencia_r13.get("anomalías") or [])
    # R15.1 (ALTO-06/MEDIO-09): estado explícito del máximo por video; la UI
    # debe poder mostrar «NO CONFIRMADO» sin re-derivar nada.
    resultado["estado_max_inflado"] = secuencia_r13.get("estado")
    resultado["tiempos_relativos_inicio_video"] = True
    resultado["trigger_electrico_disponible"] = False
    decision_sombra = decidir_apertura(
        candidato=candidato_estandar,
        verificacion=(candidato_estandar.get("verificacion") if candidato_estandar else None),
        evento_al_inicio=evento_al_inicio,
        analisis_completo=(detenido_en is None and (frames_decl <= 0 or frames_leidos >= frames_decl)),
        tiempo_verificado=False,
        revision_manual=revision_politica,
        auto_publicacion_habilitada=bool((cfg.get("apertura_v15_10") or {}).get("auto_publicar", False)),
        calibracion_validada=bool((cfg.get("apertura_v15_10") or {}).get("calibracion_validada", False)),
        politica_aprobada=bool((cfg.get("apertura_v15_10") or {}).get("politica_aprobada", False)),
    )
    # El policy evaluator ya consumió el tiempo local para clasificar la
    # hipótesis. Después se expone únicamente como raw/local; nunca como
    # tiempo_ms normal de apertura ni como propuesta.
    for candidato_sombra in candidatos_sombra:
        raw_local = candidato_sombra.get("tiempo_local_ms")
        candidato_sombra["tiempo_crudo_ms"] = raw_local
        candidato_sombra["tiempo_ms"] = None
        candidato_sombra["referencia_tiempo_valida"] = False
        numero_local = _numero_finito_con_signo(raw_local)
        candidato_sombra["estado_tiempo"] = (
            "NO_POSITIVO" if numero_local is not None and numero_local <= 0
            else "REFERENCIA_INVALIDA" if numero_local is not None
            else "NO_INTERPRETABLE" if raw_local is not None else "PENDIENTE")
    resultado["version_sombra_apertura"] = "v15.10.1-r13"
    resultado["candidatos_apertura_sombra"] = candidatos_sombra
    resultado["decision_apertura_v15_10"] = decision_sombra
    resultado["evaluacion_apertura_estandar"] = (
        candidato_estandar.get("evaluacion_estandar") if candidato_estandar else {
            "nivel": "baja", "score_evidencia": 0.0, "auto_colorable": False,
            "auto_publicable": False, "razones": [], "riesgos": ["sin_candidato"],
            "version_estandar": "apertura-estandar-r13-v5",
        })
    resultado["frame_color_estimado"] = (candidato_estandar.get("frame") if candidato_estandar else None)
    resultado["tiempo_color_estimado_ms"] = (
        candidato_estandar.get("tiempo_color_estimado_ms") if candidato_estandar else None)
    resultado["referencia_color_valida"] = bool(
        candidato_estandar and candidato_estandar.get("referencia_color_valida") is True)
    resultado["fuente_tiempo_color"] = (
        candidato_estandar.get("fuente_tiempo_color") if candidato_estandar else None)

    # V16.0.6: decision visual integrada en el analisis del video.
    # El motor anterior se conserva en *_anterior, por auditoria y rollback.
    # Las revisiones humanas y las referencias de tiempo siguen siendo prioritarias.
    if bool(cfg_det.get("congruencia_v1606_activa", True)):
        try:
            from utilidades.congruencia_automatica import analyze_one
            resolucion_ancho = max(160, min(720, int(cfg_det.get("congruencia_ancho_analisis", 480))))
            autonomo = analyze_one(ruta, capture_fps=fps_estandar,
                                   max_width=resolucion_ancho)
            _integrar_decision_v1606(resultado, autonomo,
                                     fps_estandar=fps_estandar,
                                     fps_fuente=fuente_fps_estandar,
                                     revision=rev,
                                     metricas_anteriores=metricas_blanco,
                                     ventana_rescate_ms=cfg_det.get('onset_busqueda_temprana_ms', 8.0))
        except (OSError, cv2.error, ValueError, TypeError, KeyError,
                RuntimeError, ImportError) as exc:
            resultado["congruencia_v1606"] = {
                "estado": "error_motor_congruencia", "error": type(exc).__name__,
                "detalle": str(exc)[:220], "publicado": False}

    # V16.0.19: DETAIL alimenta FORVIA, no apertura. Capturar señal independiente
    # sin alterar el detector existente ni la revisión humana.
    if __import__('utilidades.protocolo_tres_eventos', fromlist=['camara']).camara(resultado) == 'DETAIL':
        try:
            from utilidades.movimiento_tablero_v1619 import primer_movimiento_tablero
            resultado['movimiento_tablero_v1619'] = primer_movimiento_tablero(
                ruta, fps_estandar, max_frames=min(400, frames_decl or 400))
        except (OSError, ValueError, TypeError, cv2.error, RuntimeError, ImportError) as err:
            resultado['movimiento_tablero_v1619'] = {'estado':'error_movimiento_detail',
                                                       'error':type(err).__name__}

    items_cache = cache.setdefault("items", {})
    # Poda: cada video conserva sólo su resultado vigente y se descartan los
    # de algoritmos anteriores (antes el archivo crecía sin límite).
    for clave in [k for k, v in items_cache.items()
                  if not isinstance(v, dict) or v.get("algoritmo_video") != ALGORITMO_VERSION
                  or v.get("firma") == firma]:
        items_cache.pop(clave, None)
    items_cache[cache_key] = {k: v for k, v in resultado.items() if k != "revision_manual"}
    cache["version"] = 8
    _guardar_json(RUTA_CACHE, cache)
    return resultado

def tiempo_efectivo_video(item: dict) -> tuple[float | None, str, bool]:
    """Tiempo candidato final (>0) con referencia validada, si existe."""
    item = item if isinstance(item, dict) else {}
    rev = item.get("revision_manual") or {}
    estados_evento = {str(item.get("estado") or "").casefold(),
                      str(item.get("estado_evento") or "").casefold(),
                      str(item.get("estado_tiempo") or "").casefold()}
    evento_censurado = bool(item.get("evento_al_inicio") or item.get("censurado_por_izquierda")
                            or estados_evento & {"evento_al_inicio", "censurado", "censurado_por_izquierda"})
    if evento_censurado:
        return None, "evento_censurado_al_inicio", rev.get("estado") == "confirmado"
    if rev.get("estado") == "sin_evento":
        return None, "revision_manual_sin_evento", True
    if rev.get("estado") == "confirmado":
        raw = rev.get("raw_time_ms")
        if raw is None:
            raw = rev.get("tiempo_ms")
        valor = _tiempo_apertura_positivo(raw)
        if valor is None:
            numero = _numero_finito_con_signo(raw)
            if numero is not None and numero <= 0:
                return None, "revision_manual_no_positiva", True
            return None, "revision_manual_invalida", True
        try:
            frame_valido = rev.get("frame_index") is not None and int(rev.get("frame_index")) >= 0
        except (TypeError, ValueError, OverflowError):
            frame_valido = False
        referencia_valida = _referencia_temporal_valida(rev)
        # Compatibilidad segura: una confirmación humana legacy puede no guardar
        # frame/referencia. ``normalizar_item_temporal_video`` sólo marca
        # referencia_legacy_manual cuando NO existe una fuente automática
        # independiente capaz de refutarla. Una invalidación explícita nunca se
        # relaja.
        legacy_humano = rev.get("referencia_legacy_manual") is True
        estado_rev = str(rev.get("estado_tiempo") or "").upper()
        if ((not frame_valido and not legacy_humano) or not referencia_valida
                or estado_rev in {"NO_FINITO", "NO_POSITIVO", "NO_INTERPRETABLE",
                                  "REFERENCIA_INVALIDA", "PENDIENTE"}):
            return None, "revision_manual_referencia_invalida", True
        return valor, ("revision_manual_legacy" if legacy_humano else "revision_manual"), True
    if item.get("estado") == "candidato":
        raw = item.get("tiempo_crudo_ms")
        if raw is None:
            raw = item.get("tiempo_ms")
        if raw is None:
            return None, "tiempo_candidato_ausente", False
        valor = _tiempo_apertura_positivo(raw)
        if valor is None:
            numero = _numero_finito_con_signo(raw)
            if numero is not None and numero <= 0:
                return None, "tiempo_apertura_no_positivo", False
            return None, "tiempo_apertura_invalido", False
        referencia_valida = _referencia_temporal_valida(item)
        if (not referencia_valida
                and "referencia_tiempo_valida" not in item
                and not item.get("estado_tiempo")
                and str(item.get("fuente_tiempo") or "") in {
                    "fps_subframe", "fps_grabacion_validado", "fps_calibrado_por_overlay",
                    "timestamp_overlay", "timestamp_overlay_esquina", "fps_anclado_overlay_inicial"
                }
                and (_numero_no_negativo(item.get("resolucion_nativa_ms")) or 0) > 0):
            referencia_valida = True
        if not referencia_valida:
            return None, "referencia_tiempo_invalida", False
        if item.get("estado_tiempo") in {
                "NO_FINITO", "NO_POSITIVO", "NO_INTERPRETABLE", "REFERENCIA_INVALIDA", "PENDIENTE"}:
            return None, "tiempo_candidato_pendiente", False
        return valor, str(item.get("fuente_tiempo") or "automatico"), False
    return None, "sin_evento", False


ESTADOS_CONSENSO_VALIDOS = {"confirmado_manual", "primera_aparicion", "confirmado_3_de_4"}


def consenso_valido(consenso: dict | None) -> bool:
    """¿El consenso de video puede rellenar ``opening_time_ms``?

    V15.9.1 (B1): sólo se publica un tiempo CONFIRMADO. Una propuesta del
    motor (``estado_consenso`` en ``propuesto``/``discordancia``) nunca puede
    publicarse como confirmada, aunque ``estado`` traiga un valor histórico
    publicable: el propio motor ya la marcó como pendiente de revisión.

    Reglas:
    - Confirmación humana (``confirmado_manual``): siempre manda.
    - Automático: exige ``estado_consenso == "confirmado"`` Y ninguna señal
      de revisión pendiente (``requiere_revision``), incluidas las causas
      graves de una cámara integrante (B2).
    - Consensos históricos anteriores a V15.9 (sin ``estado_consenso``):
      se respetan si su estado era publicable y no pedían revisión.
    - V15.9.3 (CRIT-01/CRIT-02): falla cerrado ante metadatos incompletos
      (legado sin ``total_principales``) y ante revisiones integrantes sin
      motivo ni marca informativa explícita.
    - V15.9.4 (ALTA-N4): política única de publicación automática — ningún
      consenso histórico 1/1 o 2/2 se publica; el respaldo mínimo automático
      son 3 cámaras comparables, como en la ruta vigente. Sólo la
      confirmación humana real con evidencia (``confirmado_manual``) excepciona.
    """
    c = consenso or {}
    if _tiempo_apertura_positivo(c.get("tiempo_ms")) is None:
        return False
    # Un booleano true de un cálculo viejo no vence a una marca de tiempo
    # expresamente pendiente, inválida, conflictiva o censurada.
    if str(c.get("estado_tiempo") or "").upper() in {
            "NO_FINITO", "NO_POSITIVO", "NO_INTERPRETABLE",
            "REFERENCIA_INVALIDA", "PENDIENTE", "CENSURADO", "CONFLICTO"}:
        return False
    # Compatibilidad temporal: V15.8.x no persistía estos dos campos. Una
    # invalidación EXPLÍCITA siempre bloquea; la ausencia de ambos se evalúa
    # después con las reglas legacy de soporte/estado. Esto no autoriza nuevos
    # resultados sin referencia, sólo evita degradar JSON históricos íntegros.
    referencia_explicita = ("referencia_tiempo_valida" in c or "estado_tiempo" in c)
    if referencia_explicita and not _referencia_temporal_valida(c):
        return False
    if c.get("estado") == "confirmado_manual":
        return True
    if c.get("revision_no_clasificada") is True:
        return False
    if c.get("causas_revision_consolidado"):
        return False
    estado_consenso = c.get("estado_consenso")
    if estado_consenso is None:
        # Compatibilidad con JSON persistidos por V15.8.1 o anteriores.
        # V15.9.2 (C1) + V15.9.4 (ALTA-N4): un consenso legado ya NO se acepta
        # por su estado histórico: se reevalúa con la regla vigente ÚNICA (3+
        # cámaras comparables; metadata completa obligatoria). Los legados 2/4,
        # 2/2 y 1/1 vuelven a «pendiente de revisión» en vez de publicarse.
        if (c.get("estado") not in ESTADOS_CONSENSO_VALIDOS - {"confirmado_manual"}
                or c.get("requiere_revision")):
            return False
        try:
            soporte = int(c.get("soporte") or 0)
        except (TypeError, ValueError):
            return False
        # V15.9.3 (CRIT-01): metadatos INCOMPLETOS fallan cerrado. Un consenso
        # legado sin ``total_principales`` no demuestra el respaldo exigido
        # (3+ cámaras comparables, política única V15.9.4/N4): con ``total``
        # ausente la regla antigua degradaba el umbral a 1 y publicaba
        # soporte=1. Sin videos originales para recalcular, la evidencia se
        # conserva pero queda pendiente de revisión humana (ver migración en
        # backend).
        total_crudo = c.get("total_principales")
        if total_crudo is None:
            return False
        try:
            total = int(total_crudo)
        except (TypeError, ValueError):
            return False
        if total < 1:
            return False
        # V15.9.4 (ALTA-N4): POLÍTICA ÚNICA de publicación automática. El
        # algoritmo vigente sólo confirma con 3+ cámaras comparables
        # (consenso_videos exige len(soporte_items) >= 3), así que la rama
        # histórica NO puede aplicar un estándar distinto: los legados 1/1 o
        # 2/2 —aunque traigan metadata completa— no se elevan a
        # opening_time_ms confiable; permanecen como propuesta pendiente de
        # revisión humana. No existe ningún modo autorizado con menos de tres
        # cámaras; si llegara a habilitarse, exigirá aceptación humana y
        # configuración versionada con trazabilidad. La confirmación manual
        # real (confirmado_manual) sigue siendo la única excepción.
        return soporte >= 3
    if estado_consenso == "confirmado" and not c.get("requiere_revision"):
        # Un sello ajeno o viejo no demuestra que comprobó independencia de
        # archivos y origen temporal. Forzar reanálisis antes de publicar.
        if c.get("algoritmo_consenso") != CONSENSO_ALGORITMO_VERSION:
            return False
        return bool(c.get("validacion_fisica_dos_camaras") is True
                    and int(c.get("camaras_distintas_en_soporte") or 0) >= 2
                    and int(c.get("soporte") or 0) >= 2)
    return False


def _camara_item(item: dict) -> str | None:
    tipo = item.get("tipo_camara") or (item.get("zona_deteccion") or {}).get("tipo_camara")
    if tipo:
        return str(tipo).upper()
    from aprendizaje_video_airbag import inferir_tipo_camara_nombre
    return inferir_tipo_camara_nombre(item.get("nombre") or item.get("ruta") or "")


def _causas_revision_graves(item: dict) -> list[str]:
    """Causas GRAVES por las que la evidencia de una cámara está en duda.

    V15.9.1 (B2): se distingue la advertencia informativa (el detector
    heurístico pide revisar el cuadro, inherente a todo resultado automático)
    de la causa bloqueante (FPS no corroborados, overlay dudoso, ROI sin
    confirmar…). Si una cámara integrante del consenso trae una causa grave,
    el consolidado no puede borrar esa señal.
    """
    causas: list[str] = []
    if item.get("advertencia_fps"):
        causas.append("FPS no corroborados")
    # El valor forzado por config puede ser correcto para calcular un tiempo
    # PROVISIONAL, pero no prueba de manera independiente la frecuencia real.
    # Un reloj leído y validado contra el mismo cuadro puede corroborarlo.
    if (str(item.get('fps_fuente') or '') == 'config_forzado'
            and not (item.get('overlay_validado') is True
                     and _numero_finito_con_signo(item.get('tiempo_overlay_ms')) is not None)):
        causas.append('FPS forzados sin comprobacion independiente')
    # «Overlay dudoso» es una señal POSITIVA de problema: error al leer el
    # reloj, o reloj leído que contradice la tasa del ensayo. La simple
    # ausencia de reloj legible (items legados o videos sin Rec…fps visible)
    # no es dudosa por sí sola; la cubren advertencia_tiempo/advertencia_fps.
    reloj_leido = item.get("tiempo_overlay_ms")
    error_overlay = str(item.get("overlay_error") or "")
    error_contradiccion = any(w in error_overlay.casefold() for w in
                             ("desfase", "contradic", "discrepancia", "inconsisten"))
    fps_leido_en_video = (item.get('fps_fuente') in {'overlay_rec','reloj_overlay'}
                          and bool(item.get('referencia_tiempo_valida')))
    # Un lector OSD fallido NO es lo mismo que un reloj contradictorio.
    # Si RecXXXX fps se leyó realmente del propio video, la ausencia de
    # timestamp OCR es informativa; una discordancia explícita sí bloquea.
    if ((error_overlay and (error_contradiccion or not fps_leido_en_video)) or
            (item.get("overlay_validado") is False and reloj_leido is not None)):
        causas.append("overlay dudoso")
    if item.get("advertencia_tiempo"):
        causas.append("reloj del cuadro sin verificar")
    if item.get("advertencia_deteccion"):
        causas.append("detección con advertencia")
    estado_evento = {str(item.get("estado") or "").casefold(),
                     str(item.get("estado_evento") or "").casefold()}
    if (item.get("evento_al_inicio") or item.get("censurado_por_izquierda")
            or estado_evento & {"evento_al_inicio", "censurado", "censurado_por_izquierda"}):
        causas.append("evento al inicio del video")
    if item.get("roi_arbitraje_conflicto"):
        causas.append("conflicto entre ROI anteriores y deformacion")
    zona = item.get("zona_deteccion")
    if (isinstance(zona, dict) and zona.get("activa")
            and zona.get("bloqueada") is False
            and not zona.get("validacion_ruptura_local")):
        causas.append("ROI incierta (autoalineada sin confirmar)")
    extra = item.get("causas_revision")
    if isinstance(extra, (list, tuple)):
        causas.extend(str(x) for x in extra if x)
    return causas


def _auditoria_tiempos_video_invalidos(items: Iterable[dict]) -> list[dict]:
    """Resume tiempos finales rechazados sin sustituirlos ni normalizar su signo."""
    salida = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rev = item.get("revision_manual") if isinstance(item.get("revision_manual"), dict) else {}
        estados_evento = {str(item.get("estado") or "").casefold(),
                          str(item.get("estado_evento") or "").casefold()}
        if (item.get("evento_al_inicio") or item.get("censurado_por_izquierda")
                or estados_evento & {"evento_al_inicio", "censurado", "censurado_por_izquierda"}):
            registro = rev if rev.get("estado") == "confirmado" else item
            raw = (rev.get("raw_time_ms", rev.get("tiempo_ms")) if registro is rev else
                   item.get("tiempo_ms_sospechoso", item.get("tiempo_crudo_ms", item.get("tiempo_ms"))))
            numero = _numero_finito_con_signo(raw)
            raw_json = repr(raw) if isinstance(raw, float) and not math.isfinite(raw) else raw
            motivo = (registro.get("motivo_rechazo") or
                      "Evento visible al inicio del clip: el nacimiento queda censurado a la izquierda.")
            salida.append({
                "video": item.get("id") or item.get("nombre"),
                "fuente": "revision_manual_video" if registro is rev else "evento_censurado_video",
                "frame_index": registro.get("frame_index", item.get("frame_evento")),
                "tiempo_ms_crudo": numero, "raw_time_ms": raw_json,
                "estado_tiempo": "CENSURADO",
                "referencia_tiempo_valida": _referencia_temporal_valida(registro),
                "motivo": motivo, "motivo_rechazo": motivo,
            })
            continue
        if rev.get("estado") == "confirmado":
            registro = rev
            fuente = "revision_manual_video"
            raw = rev.get("raw_time_ms") if rev.get("raw_time_ms") is not None else rev.get("tiempo_ms")
            try:
                frame_valido = rev.get("frame_index") is not None and int(rev.get("frame_index")) >= 0
            except (TypeError, ValueError, OverflowError):
                frame_valido = False
        elif item.get("estado") == "candidato":
            registro = item
            fuente = "candidato_video"
            raw = item.get("tiempo_crudo_ms") if item.get("tiempo_crudo_ms") is not None else item.get("tiempo_ms")
            fuente_legacy = str(item.get("fuente_tiempo") or "") in {
                "fps_subframe", "fps_grabacion_validado", "fps_calibrado_por_overlay",
                "timestamp_overlay", "timestamp_overlay_esquina", "fps_anclado_overlay_inicial"
            }
            legacy_sin_metadata = (
                "referencia_tiempo_valida" not in item and not item.get("estado_tiempo")
                and fuente_legacy
                and (_numero_no_negativo(item.get("resolucion_nativa_ms")) or 0) > 0
            )
            # JSON V15.8/V15.9 podía persistir el tiempo/fuente/resolución sin
            # ``frame_evento`` ni el booleano explícito de referencia. Se acepta
            # únicamente como compatibilidad histórica; una invalidación explícita
            # sigue prevaleciendo y las ejecuciones nuevas sí conservan el frame.
            frame_valido = item.get("frame_evento") is not None or legacy_sin_metadata
        else:
            continue
        estado = None
        numero = _numero_finito_con_signo(raw)
        if raw is None:
            estado = "NO_INTERPRETABLE"
        elif numero is None:
            try:
                candidato = float(str(raw).strip().casefold().replace(",", "."))
                estado = "NO_FINITO" if not math.isfinite(candidato) else "NO_INTERPRETABLE"
            except (TypeError, ValueError, OverflowError):
                estado = "NO_INTERPRETABLE"
        elif numero <= 0:
            estado = "NO_POSITIVO"
        else:
            referencia_registro = _referencia_temporal_valida(registro)
            if (not referencia_registro and registro is rev and frame_valido
                    and "referencia_tiempo_valida" not in registro
                    and not registro.get("estado_tiempo")):
                referencia_registro = True
            elif (not referencia_registro and registro is item and frame_valido
                  and "referencia_tiempo_valida" not in registro
                  and not registro.get("estado_tiempo")
                  and str(registro.get("fuente_tiempo") or "") in {
                      "fps_subframe", "fps_grabacion_validado", "fps_calibrado_por_overlay",
                      "timestamp_overlay", "timestamp_overlay_esquina", "fps_anclado_overlay_inicial"
                  }
                  and (_numero_no_negativo(registro.get("resolucion_nativa_ms")) or 0) > 0):
                referencia_registro = True
            if not referencia_registro or not frame_valido:
                estado = "REFERENCIA_INVALIDA"
            elif registro.get("estado_tiempo") in {
                    "NO_FINITO", "NO_POSITIVO", "NO_INTERPRETABLE", "REFERENCIA_INVALIDA", "PENDIENTE"}:
                estado = registro.get("estado_tiempo")
        if estado is None:
            continue
        motivo = registro.get("motivo_rechazo") or {
            "NO_POSITIVO": "El tiempo final de apertura debe ser estrictamente mayor que cero.",
            "NO_FINITO": "El tiempo final de apertura debe ser finito.",
            "NO_INTERPRETABLE": "El tiempo final no se puede interpretar como milisegundos.",
            "REFERENCIA_INVALIDA": "La referencia temporal del candidato no está validada.",
        }.get(estado, "El tiempo candidato queda pendiente de revisión.")
        raw_json = raw
        if isinstance(raw_json, float) and not math.isfinite(raw_json):
            raw_json = repr(raw_json)
        salida.append({
            "video": item.get("id") or item.get("nombre"), "fuente": fuente,
            "frame_index": registro.get("frame_index", item.get("frame_evento")),
            "tiempo_ms_crudo": numero,
            "raw_time_ms": raw_json,
            "estado_tiempo": estado,
            "referencia_tiempo_valida": bool(
                _referencia_temporal_valida(registro)
                or (registro is rev and frame_valido
                    and "referencia_tiempo_valida" not in registro
                    and not registro.get("estado_tiempo"))
            ),
            "motivo": motivo, "motivo_rechazo": motivo,
        })
    return salida


def _ruptura_local_fuerte_1618(item: dict) -> bool:
    """Acepta una segunda ruta FISICA de apertura local, sin depender del motor global.

    Nunca convierte una ROI sugerida, un único píxel, un cuadro sin confirmar,
    ni una alarma genérica de movimiento en ruptura local fuerte.
    """
    if item.get("roi_arbitraje_conflicto") or item.get("evento_al_inicio"):
        return False
    zona = item.get("zona_deteccion") or {}
    if not isinstance(zona, dict) or zona.get("validacion_ruptura_local") is not True:
        return False
    if item.get("frame_evento_confiable") is not True:
        return False
    ev = item.get("evaluacion_apertura_estandar") or {}
    if not isinstance(ev, dict) or ev.get("auto_colorable") is not True:
        return False
    try:
        frame = int(item.get("frame_evento"))
        confirmacion = int(item.get("frame_confirmacion_automatica"))
        componente = int(item.get("componente_ruptura_px") or 0)
        pixeles = int(item.get("pixeles_ruptura") or 0)
    except (ValueError, TypeError, OverflowError):
        return False
    if item.get("frame_color_estimado") is not None:
        try:
            if int(item["frame_color_estimado"]) != frame:
                return False
        except (TypeError, ValueError, OverflowError):
            return False
    return bool(frame > 0 and 1 <= confirmacion-frame <= 8
                and max(componente, pixeles) >= 3)


def _consenso_v1618(items: Iterable[dict], config: dict | None = None) -> dict:
    """Tiempo de apertura del ensayo a partir de sus cámaras.

    V15.7, regla definida por el usuario: la apertura es el PRIMER cuadro en
    que la bolsa es físicamente visible, aunque sean pocos píxeles. Por eso se
    toma la cámara más temprana, no la mediana. La vista trasera (SCHEIBE) es
    la menos fiable y no define el tiempo; sólo se usa si no hay otra cámara.

    - Si alguna cámara principal tiene revisión manual confirmada, manda la
      confirmación manual más temprana (``confirmado_manual``).
    - Si sólo hay detecciones automáticas, se toma la más temprana que al
      menos ``min_camaras_primera_aparicion`` cámaras principales respaldan
      dentro de ±1 cuadro (``primera_aparicion``). Una detección aislada más
      temprana se informa y pide revisión. Sin respaldo: ``sin_consenso``.
    """
    cfg = _cfg(config)
    vcfg = (config or cargar_config()).get("video_airbag") or {}
    items = [x for x in items if isinstance(x, dict)]
    # Una invalidación temporal EXPRESA no debe ser borrada por la
    # normalización compartida de FPS entre cámaras del lote.
    referencias_explicitamente_invalidas = {id(item) for item in items if (
        item.get("referencia_tiempo_valida") is False
        or str(item.get("estado_tiempo") or "").upper() in
            {"NO_FINITO", "NO_POSITIVO", "NO_INTERPRETABLE", "REFERENCIA_INVALIDA"}
    )}
    # Blindaje: todas las cámaras se normalizan con la tasa real del ensayo
    # antes de comparar nada (nunca se mezclan 8 fps con 5000 fps).
    normalizar_videos_caso(items, config)
    revisiones_temporales_invalidas = _auditoria_tiempos_video_invalidos(items)
    excluidas = {str(x).upper() for x in (vcfg.get("camaras_excluidas_consenso") or ["SCHEIBE"])}
    min_camaras = max(1, int(vcfg.get("min_camaras_primera_aparicion", 2)))

    # Calibración overlay: sólo con relojes VALIDADOS y tasa real conocida.
    offsets = []
    for item in items:
        if item.get("overlay_validado") is False or item.get("fps_fuente") == "desconocido":
            continue
        overlay_v = _numero_finito_con_signo(item.get("tiempo_overlay_ms"))
        fps_v = _numero_no_negativo(item.get("tiempo_fps_ms"))
        if overlay_v is None or fps_v is None:
            continue
        # Solo un reloj VALIDADO en ese mismo video puede calibrar tiempos.
        # Un OCR no validado (None), aun si genera numeros, NO es evidencia.
        if item.get("overlay_validado") is not True or not _referencia_temporal_valida(item):
            continue
        resol = _numero_no_negativo(item.get("resolucion_nativa_ms")) or 0.0
        # No trasladar un origen arbitrario del reloj OSD a todas las cámaras:
        # V-Matrix reporta el tiempo desde el cuadro inicial del clip.
        # Sólo es aceptable una corrección pequeña, dentro de dos cuadros.
        desviacion = overlay_v - fps_v
        tolerancia_correccion = max(0.15, min(0.8, 2 * resol + 1e-6))
        if abs(desviacion) <= tolerancia_correccion:
            offsets.append(desviacion)
    offset_overlay = median(offsets) if offsets else None

    datos = []
    for item in items:
        valor, fuente, manual = tiempo_efectivo_video(item)
        if valor is None:
            continue
        resol = _numero_no_negativo(item.get("resolucion_nativa_ms")) or 1.0
        valor_usado = float(valor)
        fuente_usada = fuente
        # No reemplazar una lectura real por otro tiempo de la metadata
        # perteneciente a un cuadro diferente o desfasado.
        tiempo_fps_individual = _numero_no_negativo(item.get("tiempo_fps_ms"))
        desviacion_local_max = max(0.15, min(0.8, 2 * float(resol) + 1e-6))
        if (not manual and not str(fuente).startswith("timestamp_overlay")
                and offset_overlay is not None and tiempo_fps_individual is not None
                and _referencia_temporal_valida(item)
                and abs(tiempo_fps_individual - float(valor)) <= desviacion_local_max):
            candidato_calibrado = tiempo_fps_individual + float(offset_overlay)
            if (math.isfinite(candidato_calibrado) and candidato_calibrado > 0
                    and abs(candidato_calibrado-float(valor)) <= desviacion_local_max):
                valor_usado = candidato_calibrado
                fuente_usada = "fps_calibrado_por_overlay"
        camara = _camara_item(item)
        causas_graves = [] if manual else _causas_revision_graves(item)
        motivo_item = str(item.get("motivo") or "").strip()
        # V15.9.2 (C2) + V15.9.3 (CRIT-02): alerta BLOQUEANTE sin clasificar =
        # revisión activa que no encaja en ninguna causa grave catalogada ni
        # trae la marca explícita y auditable ``revision_informativa``. La
        # AUSENCIA de motivo textual NO la vuelve informativa: un integrante
        # con ``requiere_revision=True`` sin motivo ni marca explícita se
        # conserva pendiente hasta revisión humana.
        alerta_sin_clasificar = bool(
            not manual
            and item.get("requiere_revision")
            and not causas_graves
            and not item.get("revision_informativa")
        )
        registro_tiempo = (item.get("revision_manual") or {}) if manual else item
        referencia_item = _referencia_temporal_valida(registro_tiempo)
        if (manual and not referencia_item
                and "referencia_tiempo_valida" not in registro_tiempo
                and not registro_tiempo.get("estado_tiempo")
                and registro_tiempo.get("frame_index") is not None):
            # Revisiones humanas históricas: preservar jerarquía si nunca hubo
            # una invalidación temporal explícita.
            referencia_item = True
        if (not referencia_item and not manual
                and "referencia_tiempo_valida" not in item
                and not item.get("estado_tiempo")
                and str(item.get("fuente_tiempo") or fuente_usada or "") in {
                    "fps_subframe", "fps_grabacion_validado", "fps_calibrado_por_overlay",
                    "timestamp_overlay", "timestamp_overlay_esquina", "fps_anclado_overlay_inicial"
                }
                and float(resol) > 0):
            # Compatibilidad con resultados V15.9: antes de V15.10 se guardaba
            # la fuente/resolución física, pero no los dos campos explícitos.
            # Un False explícito nunca entra a esta rama.
            referencia_item = True
        referencia_item = bool(referencia_item and (manual or id(item) not in referencias_explicitamente_invalidas))
        datos.append({"valor": round(valor_usado, 3), "fuente": fuente_usada, "manual": manual,
                      "referencia_tiempo_valida": referencia_item,
                      "resolucion": float(resol), "nombre": item.get("nombre"),
                      "camara": camara, "principal": camara not in excluidas,
                      "requiere_revision": bool(item.get("requiere_revision")) and not manual,
                      "causas_graves": causas_graves,
                      "motivo_item": motivo_item,
                      "alerta_sin_clasificar": alerta_sin_clasificar,
                      "congruencia_automatica": bool(
                          (item.get("congruencia_v1606") or {}).get("decision_apertura_aplicada")),
                      "ruptura_local": bool(
                          ((item.get("congruencia_v1606") or {}).get("decision_apertura_aplicada")
                           and (item.get("congruencia_v1606") or {}).get("nivel_evidencia_fisica") == "fuerte"
                           and not item.get("roi_arbitraje_conflicto"))
                          or _ruptura_local_fuerte_1618(item)),
                      "origen_ruptura_fuerte": (
                          "global_y_local" if (
                              (item.get("congruencia_v1606") or {}).get("decision_apertura_aplicada")
                              and (item.get("congruencia_v1606") or {}).get("nivel_evidencia_fisica") == "fuerte"
                              and not item.get("roi_arbitraje_conflicto"))
                          else "local_corrobado" if _ruptura_local_fuerte_1618(item) else None),
                      "compatible_fisica": bool(
                          not item.get("roi_arbitraje_conflicto") and (
                            (item.get("congruencia_v1606") or {}).get("nivel_evidencia_fisica")
                              in {'fuerte','compatible'}
                            or (item.get("zona_deteccion") or {}).get("validacion_ruptura_local")
                            or (bool((item.get("evaluacion_apertura_estandar") or {}).get("auto_colorable"))
                                and (int(item.get("pixeles_ruptura") or 0)>0 or
                                     int(item.get("componente_ruptura_px") or 0)>0))
                          )),
                      "firma_contenido": str(item.get('firma') or ''),
                      "video_referencia": item})
    invalida_primaria = revisiones_temporales_invalidas[0] if revisiones_temporales_invalidas else {}
    vacio = {"tiempo_ms": None, "tiempo_crudo_ms": invalida_primaria.get("raw_time_ms"),
             "tiempo_propuesto_ms": None, "referencia_tiempo_valida": False,
             "estado_tiempo": invalida_primaria.get("estado_tiempo") or "PENDIENTE",
             "motivo_rechazo": invalida_primaria.get("motivo"),
             "revisiones_temporales_invalidas": revisiones_temporales_invalidas,
             "soporte": 0, "total_validos": len(datos),
             "requiere_revision": True, "calibracion_overlay_ms": None,
             "algoritmo_consenso": CONSENSO_ALGORITMO_VERSION,
             "regla": "primera_aparicion", "camaras_excluidas": sorted(excluidas),
             "primer_instante_por_camara": [], "incidencias": [],
             "soporte_requerido": min_camaras, "apertura_revelada": bool(datos),
             "causas_revision_consolidado": [],
             "revision_no_clasificada": False,
             "motivo_revision": ["No hay detecciones confiables en las cámaras del caso."]}
    if not datos:
        base = {"estado": "sin_datos",
                "estado_consenso": ("sin_datos" if not items else "sin_evento"), **vacio}
        base["primer_instante_por_camara"] = [
            {"camara": _camara_item(x), "video": x.get("nombre"), "tiempo_ms": None,
             "fuente": x.get("fuente_tiempo"), "resolucion_ms": None, "manual": False,
             "requiere_revision": bool(x.get("evento_al_inicio") or x.get("censurado_por_izquierda")
                                       or x.get("estado") == "evento_al_inicio"
                                       or x.get("estado_evento") == "evento_al_inicio"),
             "en_consenso": False,
             "estado": ("evento_al_inicio" if x.get("evento_al_inicio")
                        or x.get("censurado_por_izquierda")
                        or x.get("estado") == "evento_al_inicio"
                        or x.get("estado_evento") == "evento_al_inicio" else
                        ("sin_evento" if x.get("estado") in {"no_event", "omitido"} else "sin_datos")),
             "tiempo_ms_sospechoso": x.get("tiempo_ms_sospechoso")}
            for x in items]
        if any(p["estado"] == "evento_al_inicio" for p in base["primer_instante_por_camara"]):
            base["estado_consenso"] = "propuesto"
            base["motivo_revision"] = ["El evento está al inicio del video; falta la evidencia previa."]
        return base
    principales = [x for x in datos if x["principal"]]
    usa_excluidas = not principales
    pool = principales or datos
    manuales = [x for x in pool if x["manual"]]
    tol_base = float(cfg.get("tolerancia_consenso_ms", 0.15))

    def _tolerancia(x: dict) -> float:
        # Margen explícito máximo de cuatro cuadros a 5000 FPS. Se trata
        # de desfase de primera visibilidad ENTRE perspectivas; no se desplaza
        # artificialmente el tiempo elegido.
        return max(tol_base, min(0.8, x["resolucion"] * 4 + 1e-6))

    def _soporte(x: dict) -> list[dict]:
        return [y for y in pool if abs(y["valor"] - x["valor"]) <=
                max(_tolerancia(x), _tolerancia(y))
                and y.get("referencia_tiempo_valida")
                and not y.get("causas_graves")
                and not y.get("alerta_sin_clasificar")]

    def _distintas(soportes):
        # La identidad del archivo debe contar, además del nombre de cámara:
        # un AVI duplicado y renombrado no constituye una segunda perspectiva.
        firmas, camaras = set(), set()
        for y in soportes:
            cam = y.get('camara')
            if not cam or cam in camaras:
                continue
            firma = y.get('firma_contenido')
            # Sin firma de contenido no es demostrable la independencia.
            # El video puede conservarse como candidato, nunca como una
            # segunda perspectiva automática confirmatoria.
            if not firma or firma in firmas:
                continue
            firmas.add(firma)
            camaras.add(cam)
        return camaras

    def _origen_distinto(a, b):
        fa, fb = a.get('firma_contenido'), b.get('firma_contenido')
        return bool(fa and fb and fa != fb and a.get('camara') and b.get('camara')
                    and a.get('camara') != b.get('camara'))

    def _pareja_fisica(soportes):
        # Una cámara visualmente fuerte con ruptura local, más una segunda
        # INDEPENDIENTE y temporalmente coherente. La segunda puede aportar
        # confirmación local tradicional, no necesita usar el motor global.
        if len(_distintas(soportes)) < 2:
            return False
        fuertes = [y for y in soportes if y.get('ruptura_local')
                   and y.get('compatible_fisica')
                   and y.get('referencia_tiempo_valida')]
        if not fuertes:
            return False
        return any(_origen_distinto(y, fuerte)
                   and y.get('compatible_fisica')
                   for fuerte in fuertes for y in soportes)

    # V15.9 (reconciliación 3-de-4): con cuatro cámaras comparables el modo
    # automático confirmable exige respaldo de 3; con menos cámaras disponibles
    # se admite el video faltante y se exige el mínimo configurado (2). Cualquier
    # caso por debajo del respaldo queda «propuesto» (pendiente de revisión),
    # conservando la primera evidencia y todas las cámaras originales. Las
    # cámaras comparables incluyen las que analizaron sin detectar evento.
    comparables = max(len(pool), len([x for x in items
                                      if _camara_item(x) not in excluidas
                                      and x.get("estado") != "error"]))
    # La regla del usuario es dos observaciones independientes, no tres.
    # No significa dos avisos del mismo video ni dos picos de iluminación.
    soporte_requerido = 2 if comparables >= 2 else 2
    vacio["soporte_requerido"] = soporte_requerido
    anterior_sin_respaldo = None
    if manuales:
        primero = min(manuales, key=lambda x: x["valor"])
        estado = "confirmado_manual"
        estado_consenso = "confirmado"
    else:
        # La cámara más temprana con respaldo suficiente (±1 cuadro). Una
        # detección aislada aún más temprana no se descarta en silencio: se
        # informa para que el usuario la revise.
        ordenados = sorted(pool, key=lambda x: x["valor"])
        primero = next((x for x in ordenados if x.get("referencia_tiempo_valida")
                        and x.get('compatible_fisica')
                        and not x.get('causas_graves')
                        and not x.get('alerta_sin_clasificar')
                        and len(_distintas(_soporte(x))) >= soporte_requerido
                        and _pareja_fisica(_soporte(x))), None)
        if primero is None:
            # La propuesta se ancla en la cámara más temprana que SÍ vio
            # material físico con tiempo corroborado. Una señal numérica más
            # pequeña sin ruptura no se convierte en medición del caso.
            primero = next((x for x in ordenados
                            if x.get("compatible_fisica")
                            and x.get("referencia_tiempo_valida")
                            and not x.get("causas_graves")
                            and not x.get("alerta_sin_clasificar")), ordenados[0])
            estado = "sin_consenso"
            tol_cluster = max([_tolerancia(x) for x in ordenados], default=tol_base)
            valores = [x["valor"] for x in ordenados]
            clusters = 1 + sum(1 for i in range(1, len(valores))
                               if valores[i] - valores[i - 1] > max(tol_cluster, 1e-6))
            estado_consenso = "discordancia" if clusters >= 2 else "propuesto"
        else:
            estado = "primera_aparicion"
            estado_consenso = "propuesto"
            previo = ordenados[0]
            # Una lectura adelantada sin evidencia física es una anomalía
            # informativa, no desplaza el primer tiempo defendible ni impide
            # dos vistas que sí observan material. Una apertura física más
            # temprana sin consenso conserva el bloqueo de seguridad.
            previo_fisico = next((x for x in ordenados if x.get('compatible_fisica')
                                  and x.get('referencia_tiempo_valida')), primero)
            if previo_fisico["valor"] < primero["valor"] - _tolerancia(primero):
                anterior_sin_respaldo = {"video": previo_fisico["nombre"], "camara": previo_fisico["camara"],
                                         "tiempo_ms": round(previo_fisico["valor"], 3)}
    tolerancia = _tolerancia(primero)
    soporte_items = _soporte(primero)
    if usa_excluidas and estado != "confirmado_manual":
        # Sólo hay vista trasera: no basta para fijar el tiempo automáticamente.
        estado = "sin_consenso"
        estado_consenso = "propuesto"
    # Confirmable automático: respaldo de dos cámaras limpias con ruptura local, sin detección
    # anterior sin respaldo y sin mezclarse con vistas excluidas.
    validacion_fisica_dos = bool(
        estado == "primera_aparicion"
        and _pareja_fisica(soporte_items)
        and len(_distintas(soporte_items)) >= soporte_requerido
        and anterior_sin_respaldo is None
        and not usa_excluidas
        and primero.get("referencia_tiempo_valida")
    )
    if validacion_fisica_dos:
        estado_consenso = "confirmado"
    precision_sustentada = all(x["resolucion"] <= 0.2000001 for x in soporte_items)
    # V15.9.1 (B2): las cámaras del consenso con causa grave (FPS no
    # corroborados, overlay dudoso, ROI sin confirmar…) conservan su señal de
    # revisión TAMBIÉN cuando el respaldo numérico confirma el consenso. La
    # advertencia informativa genérica del detector heurístico no bloquea.
    graves_en_consenso = [x for x in soporte_items if x["causas_graves"]]
    # V15.9.2 (C2): alertas integrantes cuyo origen NO está catalogado.
    sin_clasificar = [x for x in soporte_items if x["alerta_sin_clasificar"]]
    if estado == "confirmado_manual":
        requiere_revision = False
    elif estado_consenso == "confirmado":
        # 3+ cámaras comparables de acuerdo: el resultado consolidado del caso
        # es confirmable sin revisión humana… salvo que una evidencia
        # integrante esté pendiente por causa grave (B2) o traiga una alerta
        # sin clasificar (C2): ambas se conservan hasta revisión humana.
        requiere_revision = bool(graves_en_consenso or sin_clasificar)
    else:
        requiere_revision = True
    if estado != "confirmado_manual" and any(x["requiere_revision"] for x in soporte_items) \
            and estado_consenso != "confirmado":
        requiere_revision = True
    # Salidas separadas (Fase 5): primer instante visible confiable por cámara
    # y resultado consolidado del caso. Todas las cámaras aparecen aunque no
    # hayan detectado (sin_evento / evento_al_inicio / sin_datos).
    primer_instante = []
    for item in items:
        nombre = item.get("nombre")
        dato = next((x for x in datos if x["nombre"] == nombre), None)
        if dato is None:
            estado_item = ("evento_al_inicio" if item.get("evento_al_inicio")
                           or item.get("censurado_por_izquierda")
                           or item.get("estado") == "evento_al_inicio"
                           or item.get("estado_evento") == "evento_al_inicio" else
                           ("sin_evento" if item.get("estado") in {"no_event", "omitido"}
                            else "sin_datos"))
            primer_instante.append({
                "camara": _camara_item(item), "video": nombre, "tiempo_ms": None,
                "fuente": item.get("fuente_tiempo"), "resolucion_ms": None,
                "manual": False, "requiere_revision": estado_item != "sin_evento",
                "en_consenso": False, "estado": estado_item,
                "tiempo_ms_sospechoso": item.get("tiempo_ms_sospechoso"),
                "causas_revision": [] if estado_item == "sin_evento"
                else _causas_revision_graves(item),
            })
            continue
        en = any(dato is y for y in soporte_items)
        if dato["manual"]:
            estado_item = "confirmado_manual"
        elif en and estado_consenso == "confirmado":
            estado_item = "confirmado"
        elif en:
            estado_item = "propuesto"
        else:
            estado_item = "discordancia"
        primer_instante.append({
            "camara": dato["camara"], "video": dato["nombre"],
            "tiempo_ms": round(dato["valor"], 3),
            "fuente": dato["fuente"], "resolucion_ms": round(dato["resolucion"], 6),
            "manual": bool(dato["manual"]), "requiere_revision": bool(dato["requiere_revision"]),
            "en_consenso": en, "estado": estado_item,
            "causas_revision": list(dato["causas_graves"]),
            "alerta_sin_clasificar": bool(dato["alerta_sin_clasificar"]),
            "motivo_alerta": dato["motivo_item"] or None,
        })
    incidencias = []
    for item in items:
        for clave in ("advertencia_fps", "advertencia_tiempo", "advertencia_deteccion",
                      "overlay_error"):
            if item.get(clave):
                incidencias.append({"video": item.get("nombre"), "detalle": item.get(clave)})
    motivo_revision = []
    if anterior_sin_respaldo:
        motivo_revision.append("Hay una detección anterior sin respaldo suficiente.")
    if usa_excluidas and estado != "confirmado_manual":
        motivo_revision.append("Sólo las vistas excluidas registraron el evento.")
    if estado_consenso == "discordancia":
        motivo_revision.append("Las cámaras no coinciden en un mismo primer instante.")
    elif estado_consenso == "propuesto" and estado != "confirmado_manual":
        motivo_revision.append("Falta respaldo suficiente para confirmar automáticamente.")
    if (estado_consenso != "confirmado" and
            any(x["requiere_revision"] for x in soporte_items) and not graves_en_consenso):
        motivo_revision.append("Alguna cámara del consenso quedó marcada para revisión.")
    for x in graves_en_consenso:
        motivo_revision.append(
            f"La cámara {x['camara'] or x['nombre']} del consenso requiere revisión: "
            f"{'; '.join(x['causas_graves'])}.")
    for x in sin_clasificar:
        detalle = x["motivo_item"] or "marca de revisión sin motivo catalogado"
        motivo_revision.append(
            f"La cámara {x['camara'] or x['nombre']} del consenso tiene una alerta "
            f"de revisión SIN CLASIFICAR (se conserva pendiente hasta revisión "
            f"humana): {detalle}")
    # V16.0.16: la propuesta que ve el operador debe corresponder a una
    # cámara con MATERIAL FÍSICO y reloj válido, no simplemente al tiempo
    # numérico más bajo. No implica publicación ni color automático.
    candidatos_defendibles = [x for x in pool
                              if x.get('compatible_fisica')
                              and x.get('referencia_tiempo_valida')
                              and not x.get('causas_graves')
                              and not x.get('alerta_sin_clasificar')
                              and not x.get('manual')]
    candidato_propuesta = min(candidatos_defendibles, key=lambda x: x['valor']) if candidatos_defendibles else None
    # Traza aditiva para diagnosticar piezas grises, sin promover la propuesta.
    traza_v1618 = []
    for x in sorted(datos, key=lambda d: (d["valor"], str(d.get("camara") or ""))):
        pareja = _soporte(x)
        traza_v1618.append({
            "camara": x.get("camara"), "video": x.get("nombre"),
            "tiempo_ms": x["valor"],
            "firma_presente": bool(x.get("firma_contenido")),
            "referencia_tiempo_valida": bool(x.get("referencia_tiempo_valida")),
            "fuerte_local": bool(x.get("ruptura_local")),
            "origen_fuerte": x.get("origen_ruptura_fuerte"),
            "material_fisico": bool(x.get("compatible_fisica")),
            "graves": x.get("causas_graves") or [],
            "alerta_no_clasificada": bool(x.get("alerta_sin_clasificar")),
            "camaras_independientes_en_ventana": len(_distintas(pareja)),
            "pareja_fisica": bool(_pareja_fisica(pareja)),
            "puede_fijar_tiempo": bool(x.get("compatible_fisica")
                                      and x.get("referencia_tiempo_valida")
                                      and not x.get("causas_graves")
                                      and not x.get("alerta_sin_clasificar")),
        })
    tiempo_resultado = round(float(primero["valor"]), 1)
    referencia_resultado = bool(primero.get("referencia_tiempo_valida")
                                and _tiempo_apertura_positivo(tiempo_resultado) is not None)
    return {
        "estado": estado, "tiempo_ms": tiempo_resultado,
        "tiempo_crudo_ms": tiempo_resultado,
        "estado_tiempo": "VALIDO" if referencia_resultado else "REFERENCIA_INVALIDA",
        "motivo_rechazo": None if referencia_resultado else "La referencia temporal no está validada.",
        "estado_consenso": estado_consenso,
        "referencia_tiempo_valida": referencia_resultado,
        "revisiones_temporales_invalidas": revisiones_temporales_invalidas,
        "algoritmo_consenso": CONSENSO_ALGORITMO_VERSION,
        "soporte_requerido": soporte_requerido,
        "apertura_revelada": bool(datos),
        "motivo_revision": motivo_revision,
        "regla": "primera_aparicion",
        "diagnostico_consenso_v1618": traza_v1618,
        "camara_referencia": primero["camara"], "video_referencia": primero["nombre"],
        "fuente_referencia": primero["fuente"],
        "validacion_fisica_dos_camaras": validacion_fisica_dos,
        "camaras_distintas_en_soporte": len(_distintas(soporte_items)),
        "criterio_apertura_v1607": (
            "primer_indicio_fisico_con_corrobora_dos_camaras"
            if validacion_fisica_dos else "propuesta_sin_dos_evidencias_fisicas_congruentes"),
        "soporte": len(soporte_items), "total_validos": len(datos),
        "total_principales": len(principales),
        "camaras_excluidas": sorted(excluidas),
        "videos_coincidentes": [x["nombre"] for x in soporte_items],
        "valores_coincidentes_ms": [round(x["valor"], 3) for x in soporte_items],
        "fuentes_coincidentes": [x["fuente"] for x in soporte_items],
        "valores_por_camara": {str(x["camara"] or x["nombre"]): round(x["valor"], 3) for x in datos},
        "primer_instante_por_camara": primer_instante,
        "incidencias": incidencias,
        # Preservar la medicion visual como PROPUESTA cuando la prueba no
        # supera las puertas de consenso. Nunca publica ni confirma Excel.
        "tiempo_propuesto_ms": (round(float(candidato_propuesta["valor"]), 1)
                                if estado_consenso != "confirmado" and candidato_propuesta
                                else None),
        "video_candidato_visual": (candidato_propuesta.get('nombre') if candidato_propuesta
                                     and estado_consenso != 'confirmado' else None),
        "estado_candidato_visual": ("estimado_pendiente_corrobora"
                                    if estado_consenso != "confirmado" and candidato_propuesta
                                    else "sin_propuesta_publicable"),
        "tolerancia_ms": round(tolerancia, 4),
        "calibracion_overlay_ms": None if offset_overlay is None else round(float(offset_overlay), 3),
        "camara_anterior_sin_respaldo": anterior_sin_respaldo,
        "lecturas_anteriores_sin_evidencia_fisica": [
            {"video": x['nombre'], "camara": x['camara'], "tiempo_ms": round(x['valor'],3)}
            for x in datos if x['valor'] < primero['valor']
            and not x.get('compatible_fisica')],
        "requiere_revision": requiere_revision,
        # C2: alerta integrante no catalogada ⇒ el caso NO se publica solo.
        "revision_no_clasificada": bool(sin_clasificar),
        # Causas graves que impiden publicar el tiempo aunque haya respaldo (B2).
        "causas_revision_consolidado": sorted({causa for x in graves_en_consenso
                                               for causa in x["causas_graves"]}),
        "exactitud_0_1ms_sustentada": precision_sustentada,
        "nota_precision": ("Resolución de un cuadro o mejor (Rec…fps)." if precision_sustentada else
                           "Al menos un video tiene una resolución temporal más gruesa que 0.2 ms."),
    }

def consenso_videos(items: Iterable[dict], config: dict | None = None) -> dict:
    """V16.0.20: FRONTAL y LATERAL definen apertura por primera tela visible.

    DETAIL se utiliza independientemente para FORVIA. SCHEIBE se conserva
    en el análisis general pero jamás fija estos tres eventos.
    """
    from utilidades.protocolo_tres_eventos import camara, tres_eventos
    originales=[v for v in items if isinstance(v, dict)]
    normalizar_videos_caso(originales, config)
    principales=[v for v in originales if camara(v) in {'FRONTAL','LATERAL'}]
    base=_consenso_v1618(principales, config)
    eventos=tres_eventos(originales, base)
    base['eventos_v1619']=eventos
    base['eventos_v1620']=eventos
    base['camaras_excluidas_de_apertura_v1619']=['DETAIL','SCHEIBE']
    base['version_politica_tres_eventos']='v16.0.20'
    # La evidencia visual por cuadro debe ser congruente con la decision de
    # consenso. No publicar un valor procedente de DETAIL/SCHEIBE.
    ap=eventos['apertura']
    if base.get('estado') != 'confirmado_manual':
        if ap['estado'] != 'corroborado_dos_vistas':
            base['estado']='sin_consenso'
            base['estado_consenso']='propuesto'
            base['requiere_revision']=True
            base['validacion_fisica_dos_camaras']=False
            base['motivo_revision']=list(base.get('motivo_revision') or []) + [
                'V16.0.20: apertura requiere tela visible en FRONTAL y LATERAL con tiempo congruente.']
        elif (not base.get('causas_revision_consolidado') and
              not base.get('revision_no_clasificada') and
              not base.get('revisiones_temporales_invalidas')):
            # El tiempo canónico procede DEL protocolo de tela visible, no
            # del primer cambio/deformación del consenso anterior.
            base['tiempo_ms']=ap['tiempo_ms']
            base['tiempo_crudo_ms']=ap['tiempo_ms']
            base['estado']='primera_aparicion'
            base['estado_consenso']='confirmado'
            base['requiere_revision']=False
            base['referencia_tiempo_valida']=True
            base['estado_tiempo']='VALIDO'
            base['validacion_fisica_dos_camaras']=True
            base['camaras_distintas_en_soporte']=2
            base['soporte']=2
            base['videos_coincidentes']=[ap['frontal']['archivo'],ap['lateral']['archivo']]
            base['valores_coincidentes_ms']=[ap['frontal']['tiempo_ms'],ap['lateral']['tiempo_ms']]
            base['criterio_apertura_v1620']='primer_fotograma_de_tela_visible_corrobora_frontal_lateral'
        else:
            base['estado']='sin_consenso'
            base['estado_consenso']='propuesto'
            base['requiere_revision']=True
            base['validacion_fisica_dos_camaras']=False
    return base


def evidencia_apertura_desde_consenso(caso: dict, consenso: dict) -> dict | None:
    if not consenso_valido(consenso):
        return None
    return {
        "proyecto": caso.get("project_id"), "etapa": caso.get("tipo_st"),
        "caso": caso.get("case_key"), "componente": "bolsa_aire",
        "clave": "opening_time_ms", "valor_original": str(consenso["tiempo_ms"]),
        "valor_normalizado": str(consenso["tiempo_ms"]), "fuente": "video",
        "imagen": None, "video": ", ".join(consenso.get("videos_coincidentes") or []),
        "bbox_original": None, "orientacion_grados": 0, "transformaciones": ["deteccion_video_airbag"],
        "fase": "VIDEO", "tor": None, "confianza_ocr": 0.99 if consenso.get("estado") == "confirmado_manual" else min(0.99, 0.75 + 0.08 * consenso.get("soporte", 0)),
        # R7: la evidencia de video conserva su contrato temporal. Sin esto,
        # consolidar_caso convertía un consenso manual válido en un campo sin
        # referencia temporal y el semáforo terminaba gris.
        "referencia_tiempo_valida": consenso.get("referencia_tiempo_valida") is True,
        "estado_tiempo": consenso.get("estado_tiempo") or ("VALIDO" if consenso.get("referencia_tiempo_valida") is True else "PENDIENTE"),
        "raw_time_ms": consenso.get("tiempo_crudo_ms", consenso.get("tiempo_ms")),
        "estado_consenso": consenso.get("estado_consenso"),
        "soporte": consenso.get("soporte"),
        "algoritmo_consenso": consenso.get("algoritmo_consenso"),
        "valido_catalogo": True, "valido_regex": True,
        "confirmacion_manual": consenso.get("estado") == "confirmado_manual",
        "requiere_confirmacion_manual": bool(consenso.get("requiere_revision")) and
                                         consenso.get("estado") != "confirmado_manual",
    }
