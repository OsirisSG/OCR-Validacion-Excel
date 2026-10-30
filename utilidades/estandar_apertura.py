"""Estándar reutilizable de evidencia de apertura física (V15.10.1 R10).

Objetivo: localizar el primer indicio físicamente defendible de apertura sin
confundirlo con reflejos, movimiento global o una bolsa ya expandida.

R10 separa dos preguntas:
1) ¿hay evidencia visual suficiente de que empezó la apertura?
2) ¿el tiempo es publicable/sincronizado?

La primera puede habilitar un color ESTIMADO. La segunda sigue siendo más
estricta y controla publicación/consenso. Ningún score se presenta como
probabilidad calibrada.
"""
from __future__ import annotations

import math
from typing import Any

VERSION_ESTANDAR = "apertura-estandar-r13-v5"

# R15.3 (ALTO-04): evidencia mínima de expansión post-breakout para poder
# CONFIRMAR un máximo inflado. La invariante temporal de R15.2 (frame_max >
# frame_breakout ∧ duración > 0) es necesaria pero no suficiente: una
# variación de 1 px (0.01 %) por ruido de segmentación confirmaba un Tmax con
# confianza 1.0. No se fija un porcentaje arbitrario único (recomendación del
# auditor): se combinan piso RELATIVO (escala con resolución/ROI), piso
# ABSOLUTO (ruido de sensor en áreas pequeñas) y PERSISTENCIA temporal.
# Puertas conservadoras documentadas; la calibración fina con videos reales
# es trabajo de campo (R16: trigger eléctrico fuera de alcance).
EXPANSION_MINIMA_RELATIVA = 0.02       # ≥ 2 % del área visible en breakout
EXPANSION_MINIMA_ABSOLUTA_PX = 25.0    # ≥ 25 px de crecimiento (piso de ruido)
PERSISTENCIA_EXPANSION_FRAMES = 3      # frames sostenidos por encima del umbral
CONFIANZA_MAX_NO_CONFIRMADO = 0.35     # P2: confianza coherente con el estado


def _finito(valor: Any, defecto: float = 0.0) -> float:
    try:
        numero = float(valor)
    except (TypeError, ValueError, OverflowError):
        return defecto
    return numero if math.isfinite(numero) else defecto


def _entero(valor: Any, defecto: int = 0) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError, OverflowError):
        return defecto


def _max_metrica(metricas: list[dict], clave: str) -> float:
    valores = [_finito(m.get(clave)) for m in metricas if isinstance(m, dict)]
    return max(valores) if valores else 0.0


def evaluar_evidencia_estandar(candidato: dict | None,
                               verificacion: dict | None = None,
                               metrica: dict | None = None,
                               *,
                               metricas_ventana: list[dict] | None = None,
                               umbral_alta: float = 0.56,
                               umbral_media: float = 0.44) -> dict:
    """Evalúa el onset usando el primer frame + su ventana de corroboración.

    El primer indicio puede ser diminuto. Por eso R10 NO exige que el frame de
    onset ya tenga gran área; permite que cuadros posteriores corroboren el
    evento conservando el tiempo del primer frame.
    """
    candidato = candidato if isinstance(candidato, dict) else {}
    verificacion = verificacion if isinstance(verificacion, dict) else {}
    metrica = metrica if isinstance(metrica, dict) else {}
    ventana = [m for m in (metricas_ventana or []) if isinstance(m, dict)]
    if not ventana and metrica:
        ventana = [metrica]

    continuidad = max(0, _entero(candidato.get("continuidad_frames")))
    previos_limpios = max(0, _entero(candidato.get("frames_previos_limpios")))
    score_candidato = max(0.0, min(1.0, _finito(candidato.get("score_candidato"))))

    min_pix = max(1, _entero(metrica.get("min_pixeles_debil"), 1))
    min_comp = max(1, _entero(metrica.get("min_componente_debil"), 1))
    pix_inicio = max(_entero(metrica.get("pixeles_ruptura")),
                     _entero(metrica.get("pixeles_blanco_nuevo")),
                     _entero(metrica.get("pixeles_grieta_nueva")))
    comp_inicio = max(_entero(metrica.get("componente_ruptura_px")),
                      _entero(metrica.get("componente_blanco_px")))

    max_pix = max([pix_inicio] + [
        max(_entero(m.get("pixeles_ruptura")), _entero(m.get("pixeles_blanco_nuevo")),
            _entero(m.get("pixeles_grieta_nueva"))) for m in ventana
    ])
    max_comp = max([comp_inicio] + [
        max(_entero(m.get("componente_ruptura_px")), _entero(m.get("componente_blanco_px")))
        for m in ventana
    ])

    base_inicio = max(pix_inicio, comp_inicio, 1)
    max_soporte = max(max_pix, max_comp)
    crecimiento_ratio = max_soporte / base_inicio if base_inicio > 0 else 0.0
    crecimiento_real = bool(max_soporte > base_inicio and crecimiento_ratio >= 3.0)
    inicio_fuerte = bool(
        pix_inicio >= max(2, 2 * min_pix)
        or comp_inicio >= max(2, 2 * min_comp)
    )

    # El onset recibe crédito por superar el mínimo débil, aunque sólo sea 1 px.
    onset_abs = min(1.0, max(pix_inicio / min_pix, comp_inicio / min_comp))
    # La ventana posterior confirma que ese mínimo creció/persistió.
    soporte_abs = min(1.0, max(max_pix / min_pix, max_comp / min_comp) / 2.0)

    scores = metrica.get("scores_fuentes") if isinstance(metrica.get("scores_fuentes"), dict) else {}
    material_frac = max(
        _finito(metrica.get("fraccion_material_en_rango")),
        _finito(scores.get("material_en_rango")),
        _max_metrica(ventana, "fraccion_material_en_rango"),
    )
    # R9 usaba 0.004 (0.4% de ROI), demasiado alto para un primer indicio.
    # R10 usa el área sólo como corroboración secundaria, no como requisito.
    material_area_score = min(1.0, material_frac / 0.0005) if material_frac > 0 else 0.0

    borde_frac = max(
        _finito(metrica.get("fraccion_borde_nuevo")),
        _finito(scores.get("bordes_nuevos")),
        _max_metrica(ventana, "fraccion_borde_nuevo"),
    )
    borde_score = min(1.0, borde_frac / 0.002) if borde_frac > 0 else 0.0

    # Compatibilidad con métricas agregadas/legadas que sólo conservan fracciones
    # y no los conteos de píxel. Una señal local fuerte no debe perderse por
    # ausencia de esos campos de auditoría.
    if max_pix == 0 and max_comp == 0 and material_area_score > 0:
        onset_abs = max(onset_abs, material_area_score)
        soporte_abs = max(soporte_abs, material_area_score)

    deform_frames = sum(1 for m in ventana if m.get("deformacion_confiable") is True)
    prox_frames = sum(1 for m in ventana if m.get("proximidad_deformacion") is True)
    deformacion_confiable = bool(metrica.get("deformacion_confiable") or deform_frames)
    proximidad = metrica.get("proximidad_deformacion")
    if proximidad is not True and prox_frames:
        proximidad = True

    continuidad_score = min(1.0, max(0, continuidad - 1) / 2.0)
    previos_score = min(1.0, previos_limpios / 2.0)
    proximidad_score = 1.0 if proximidad is True else (0.55 if proximidad is None else 0.0)
    deformacion_score = (min(1.0, deform_frames / max(1, continuidad))
                         if deformacion_confiable else 0.40)

    riesgo = list(candidato.get("razones_riesgo") or [])
    riesgo.extend([str(x) for x in (verificacion.get("razones_en_contra") or [])])
    riesgo = list(dict.fromkeys(riesgo))

    graves = {
        "cambio_global_sospechoso",
        "posible_reflejo",
        "posible_abombamiento_sin_ruptura",
        "posible_abombamiento",
        "material_fuera_de_zona_deformacion",
        "evidencia_previa_en_misma_microzona",
        "roi_ocluida",
        "overlay_contradictorio",
    }
    penalizacion = 0.0
    for r in riesgo:
        if r in graves:
            penalizacion += 0.22
        elif str(r).startswith("advertencia:"):
            penalizacion += 0.035
        else:
            penalizacion += 0.055
    penalizacion = min(0.60, penalizacion)

    # La geometría y la persistencia pesan más que el área absoluta.
    score = (
        0.12 * score_candidato
        + 0.18 * onset_abs
        + 0.16 * soporte_abs
        + 0.18 * continuidad_score
        + 0.12 * previos_score
        + 0.12 * proximidad_score
        + 0.06 * deformacion_score
        + 0.03 * material_area_score
        + 0.03 * borde_score
        - penalizacion
    )
    score = max(0.0, min(1.0, score))

    razones: list[str] = []
    if onset_abs > 0:
        razones.append("indicio_local_nuevo_en_primer_frame")
    if soporte_abs >= 0.5:
        razones.append("crecimiento_o_persistencia_posterior")
    if crecimiento_real:
        razones.append("crecimiento_espacial_posterior_real")
    if material_frac > 0:
        razones.append("material_nuevo_detectado")
    if proximidad is True:
        razones.append("material_nuevo_cerca_deformacion")
    elif deformacion_confiable and proximidad is False:
        razones.append("material_fuera_de_zona_deformacion")
    if continuidad >= 2:
        razones.append("persistencia_temporal")
    if previos_limpios >= 2:
        razones.append("cuadros_previos_limpios")
    if borde_score > 0:
        razones.append("borde_local_nuevo")

    sin_riesgo_grave = not any(r in graves for r in riesgo)
    # Un indicio mínimo persistente pero que nunca crece puede ser un píxel
    # caliente/compresión. Para promover el PRIMER onset mínimo exigimos
    # crecimiento posterior real; si el onset ya nace claramente por encima
    # del mínimo, la persistencia puede bastar.
    legado_sin_conteos_fuerte = bool(
        pix_inicio == 0 and comp_inicio == 0
        and material_area_score >= 0.75
        and borde_score >= 0.25
        and continuidad >= 2
    )
    crecimiento_suficiente = bool(crecimiento_real or inicio_fuerte or legado_sin_conteos_fuerte)
    soporte_local_suficiente = bool(
        onset_abs >= 0.5 and soporte_abs >= 0.5 and crecimiento_suficiente
    )
    tipos_senal = {str(x) for x in (candidato.get("tipo_senales") or []) if x}
    dos_senales_visuales = bool(
        len(tipos_senal) >= 2
        or (material_area_score > 0 and borde_score > 0)
        or (inicio_fuerte and crecimiento_real)
    )
    # Si hay un mapa de deformación disponible, exigimos proximidad real. Si no
    # existe (videos legados/ROI antigua), sólo aceptamos la ausencia de esa
    # geometría cuando hay al menos dos señales visuales coherentes. Así un
    # único píxel blanco aislado no obtiene color por falta de geometría.
    # R13: rutas físicas alternativas. No obligamos a que DIC/flujo sea fiable
    # en todas las piezas; una trayectoria espacial limpia con crecimiento real
    # también puede defender el breakout. Esto reduce grises innecesarios sin
    # rebajar la protección frente a reflejos/hot-pixels.
    geometria_suficiente = bool(
        proximidad is True
        or (not deformacion_confiable and dos_senales_visuales)
    )
    core_temporal = bool(
        onset_abs >= 0.5 and previos_limpios >= 1 and continuidad >= 2
        and crecimiento_suficiente
    )
    ruta_deformacion = bool(core_temporal and proximidad is True)
    ruta_trayectoria = bool(
        core_temporal and not deformacion_confiable
        and (dos_senales_visuales or crecimiento_ratio >= 4.0)
    )
    hay_fisura = "fisura_oscura" in tipos_senal
    hay_tela = ("material_claro_nuevo" in tipos_senal or material_area_score > 0.20)
    ruta_fisura_a_bolsa = bool(
        core_temporal and hay_fisura and (hay_tela or soporte_abs >= 0.75)
        and (proximidad is not False)
    )
    if not crecimiento_suficiente and onset_abs > 0:
        riesgo.append("indicio_minimo_sin_crecimiento_posterior")
        sin_riesgo_grave = False

    rutas = {
        "deformacion_mas_material": ruta_deformacion,
        "trayectoria_temporal": ruta_trayectoria,
        "fisura_a_bolsa": ruta_fisura_a_bolsa,
    }
    ruta_defendible = next((k for k, ok in rutas.items() if ok), None)
    geometria_suficiente = bool(geometria_suficiente or ruta_defendible)
    puertas = {
        "onset_local_nuevo": onset_abs >= 0.5,
        "previo_limpio": previos_limpios >= 1,
        "continuidad_posterior": continuidad >= 2,
        "crecimiento_o_inicio_fuerte": crecimiento_suficiente,
        "geometria_coherente": geometria_suficiente,
        "ruta_fisica_defendible": bool(ruta_defendible),
        "sin_riesgo_grave": sin_riesgo_grave,
    }
    puertas_fallidas = [k for k, ok in puertas.items() if not ok]
    defendible = bool(all(puertas.values()))

    # Una ruta física completa pesa más que el área absoluta del primer frame.
    # El score sigue visible para auditoría, pero ya no puede vetar por sí solo
    # un breakout mínimo bien corroborado.
    if defendible and score >= max(0.50, float(umbral_alta) - 0.06):
        nivel = "alta"
    elif score >= umbral_media and sum(bool(v) for v in puertas.values()) >= 4:
        nivel = "media"
    else:
        nivel = "baja"

    auto_colorable = bool(nivel == "alta" and defendible)

    return {
        "nivel": nivel,
        "score_evidencia": round(score, 6),
        "score_es_probabilidad": False,
        "auto_colorable": auto_colorable,
        "auto_publicable": False,
        "defendible_un_video": defendible,
        "puertas_decision": puertas,
        "puertas_fallidas": puertas_fallidas,
        "rutas_defendibles": rutas,
        "ruta_defendible": ruta_defendible,
        "senales_visuales": sorted(tipos_senal),
        "doble_senal_sin_geometria": dos_senales_visuales,
        "razones": list(dict.fromkeys(razones)),
        "riesgos": riesgo,
        "deformacion_confiable": deformacion_confiable,
        "proximidad_deformacion": proximidad,
        "continuidad_frames": continuidad,
        "frames_previos_limpios": previos_limpios,
        "onset_soporte_abs": round(onset_abs, 6),
        "confirmacion_soporte_abs": round(soporte_abs, 6),
        "crecimiento_ratio": round(float(crecimiento_ratio), 6),
        "crecimiento_real": crecimiento_real,
        "inicio_fuerte": inicio_fuerte,
        "legado_sin_conteos_fuerte": legado_sin_conteos_fuerte,
        "material_area_score": round(material_area_score, 6),
        "borde_score": round(borde_score, 6),
        "umbral_alta": float(umbral_alta),
        "umbral_media": float(umbral_media),
        "version_estandar": VERSION_ESTANDAR,
    }


def estimar_llenado_visual(metricas: list[dict] | None, frame_inicio: int | None,
                           fps_captura: float | None, *,
                           fraccion_objetivo: float = 0.90,
                           estabilidad_frames: int = 3,
                           tolerancia_rel: float = 0.18,
                           max_frames: int = 160) -> dict:
    """Estima cuándo el despliegue visible llega a una meseta estable.

    No pretende medir volumen físico ni presión interna. Es una métrica visual
    reproducible: desde el primer onset confirmado busca el primer cuadro que
    alcanza una fracción alta del máximo visible y se mantiene cerca de ese
    nivel varios cuadros. Si el clip termina antes de una meseta, se abstiene.
    """
    metricas = metricas if isinstance(metricas, list) else []
    try:
        inicio = int(frame_inicio) if frame_inicio is not None else None
    except (TypeError, ValueError, OverflowError):
        inicio = None
    try:
        fps = float(fps_captura) if fps_captura is not None else None
    except (TypeError, ValueError, OverflowError):
        fps = None
    if inicio is None or inicio < 0 or inicio >= len(metricas):
        return {"estado": "sin_onset", "frame_llenado": None,
                "duracion_llenado_frames": None, "duracion_llenado_ms": None}
    if fps is None or not math.isfinite(fps) or fps <= 0:
        fps = None

    fin = min(len(metricas), inicio + max(3, int(max_frames)))
    tramo = metricas[inicio:fin]
    if len(tramo) < max(3, int(estabilidad_frames)):
        return {"estado": "clip_insuficiente", "frame_llenado": None,
                "duracion_llenado_frames": None, "duracion_llenado_ms": None}

    def senal(m: dict) -> float:
        if not isinstance(m, dict):
            return 0.0
        return float(max(
            _entero(m.get("area_bolsa_visible_estimada_px")),
            _entero(m.get("componente_ruptura_px")),
            _entero(m.get("componente_blanco_px")),
            _entero(m.get("pixeles_ruptura")),
            _entero(m.get("material_nuevo_en_rango_px")),
        ))

    valores = [senal(m) for m in tramo]
    pico = max(valores) if valores else 0.0
    if pico <= 0:
        return {"estado": "sin_senal_de_llenado", "frame_llenado": None,
                "duracion_llenado_frames": None, "duracion_llenado_ms": None}

    objetivo = max(0.50, min(0.99, float(fraccion_objetivo))) * pico
    estables = max(2, int(estabilidad_frames))
    tolerancia = max(0.02, min(0.50, float(tolerancia_rel)))
    frame_fin = None
    valor_fin = None
    for i in range(0, len(valores) - estables + 1):
        ventana = valores[i:i + estables]
        if ventana[0] < objetivo:
            continue
        minimo = min(ventana)
        maximo = max(ventana)
        if minimo < pico * max(0.50, float(fraccion_objetivo) - tolerancia):
            continue
        if maximo > 0 and (maximo - minimo) / maximo > tolerancia:
            continue
        frame_fin = inicio + i
        valor_fin = ventana[0]
        break

    if frame_fin is None:
        return {
            "estado": "sin_meseta_visual_confirmada",
            "frame_llenado": None,
            "duracion_llenado_frames": None,
            "duracion_llenado_ms": None,
            "pico_visible_px": int(round(pico)),
            "frames_evaluados": len(valores),
            "completo_en_clip": False,
        }

    dur_frames = int(frame_fin - inicio)
    dur_ms = (dur_frames * 1000.0 / fps) if fps else None
    return {
        "estado": "meseta_visual_estimada",
        "frame_llenado": int(frame_fin),
        "duracion_llenado_frames": dur_frames,
        "duracion_llenado_ms": (round(dur_ms, 6) if dur_ms is not None else None),
        "pico_visible_px": int(round(pico)),
        "senal_en_meseta_px": int(round(valor_fin or 0)),
        "fraccion_objetivo": float(fraccion_objetivo),
        "frames_estabilidad": estables,
        "completo_en_clip": True,
        "nota": "Estimacion visual de despliegue estable; no certifica volumen ni presion interna.",
    }



def analizar_secuencia_despliegue(metricas: list[dict] | None,
                                   frame_breakout: int | None,
                                   fps_captura: float | None,
                                   *,
                                   max_frames: int = 240,
                                   fraccion_maximo: float = 0.97,
                                   estabilidad_frames: int = 3,
                                   caida_confirmacion: float = 0.04,
                                   expansion_minima_relativa: float = EXPANSION_MINIMA_RELATIVA,
                                   expansion_minima_absoluta_px: float = EXPANSION_MINIMA_ABSOLUTA_PX,
                                   persistencia_expansion_frames: int = PERSISTENCIA_EXPANSION_FRAMES) -> dict:
    """R13: máquina de estados ligera para breakout -> expansión -> máximo.

    * ``breakout``: primer frame ya defendido por el detector de onset.
    * ``maximo_inflado``: primer frame de la meseta alrededor del máximo visible.

    Sin trigger eléctrico los tiempos son relativos al inicio del video. La
    función no infiere detonación ni presión/volumen internos.
    """
    metricas = metricas if isinstance(metricas, list) else []
    try:
        inicio = int(frame_breakout) if frame_breakout is not None else None
    except (TypeError, ValueError, OverflowError):
        inicio = None
    try:
        fps = float(fps_captura) if fps_captura is not None else None
    except (TypeError, ValueError, OverflowError):
        fps = None
    if fps is not None and (not math.isfinite(fps) or fps <= 0):
        fps = None
    if inicio is None or inicio < 0 or inicio >= len(metricas):
        return {
            "estado": "sin_breakout", "frame_breakout": None,
            "frame_max_inflado": None, "tiempo_breakout_ms": None,
            "tiempo_max_inflado_ms": None, "duracion_expansion_ms": None,
            "anomalías": ["sin_breakout_defendible"],
            "version": VERSION_ESTANDAR,
        }

    fin = min(len(metricas), inicio + max(6, int(max_frames)))
    tramo = metricas[inicio:fin]

    def area(m: dict) -> float:
        if not isinstance(m, dict):
            return 0.0
        return float(max(
            _entero(m.get("area_bolsa_visible_estimada_px")),
            _entero(m.get("material_nuevo_en_rango_px")),
            _entero(m.get("componente_ruptura_px")),
            _entero(m.get("componente_blanco_px")),
            _entero(m.get("pixeles_ruptura")),
        ))

    bruto = [area(m) for m in tramo]
    if not bruto or max(bruto) <= 0:
        t0 = (inicio * 1000.0 / fps) if fps else None
        return {
            "estado": "breakout_sin_maximo", "frame_breakout": inicio,
            "frame_max_inflado": None,
            "tiempo_breakout_ms": round(t0, 6) if t0 is not None else None,
            "tiempo_max_inflado_ms": None, "duracion_expansion_ms": None,
            "anomalías": ["sin_senal_area_bolsa"],
            "version": VERSION_ESTANDAR,
        }

    # R15 (ALTA-05): mediana móvil CAUSAL — frame actual y dos anteriores,
    # nunca anticipa el futuro. R14 recortaba bruto[i-1:i+2] y con sólo dos
    # muestras elegía el MAYOR (len//2==1): el frame 0 heredaba el área del
    # frame siguiente y el «máximo» podía caer en el propio breakout (0 ms,
    # fases fuera de orden).
    suav = []
    for i in range(len(bruto)):
        vals = sorted(bruto[max(0, i - 2): i + 1])
        suav.append(vals[len(vals) // 2])
    pico = max(suav)
    idx_pico = suav.index(pico)
    frame_pico = inicio + idx_pico

    frac = max(0.80, min(0.999, float(fraccion_maximo)))
    estables = max(2, int(estabilidad_frames))
    objetivo = pico * frac
    candidato_meseta = None
    for i in range(0, max(0, len(suav) - estables + 1)):
        vent = suav[i:i+estables]
        if min(vent) < objetivo:
            continue
        # Permitimos una meseta suave, pero no una subida todavía agresiva.
        pendiente = abs(vent[-1] - vent[0]) / max(pico, 1.0)
        if pendiente <= 0.05:
            candidato_meseta = i
            break
    idx_max = candidato_meseta if candidato_meseta is not None else idx_pico
    # R15 (ALTA-05) invariante: si el pico está después del breakout, el
    # máximo no puede quedarse en el frame de breakout; se avanza al primer
    # frame que alcanza el área objetivo (siempre existe: el propio pico).
    if idx_max == 0 and idx_pico > 0:
        idx_max = next((i for i in range(1, len(suav)) if suav[i] >= objetivo), idx_pico)
    frame_max = inicio + idx_max

    anomalias: list[str] = []
    if idx_pico >= len(suav) - 1:
        anomalias.append("maximo_en_borde_final_del_clip")
    posterior = suav[idx_pico + 1: idx_pico + 1 + max(2, estables)]
    caida_confirmada = False
    if posterior:
        caida = (pico - min(posterior)) / max(pico, 1.0)
        caida_confirmada = caida >= max(0.0, float(caida_confirmacion))
        if not caida_confirmada and candidato_meseta is None:
            anomalias.append("maximo_sin_caida_o_meseta_clara")
    if len(suav) < estables + 2:
        anomalias.append("ventana_post_breakout_corta")
    if fps is None:
        anomalias.append("fps_captura_no_disponible")

    # R15.1 (ALTO-06): breakout en el frame 0 del clip = evento censurado por
    # derecha: no existe ningún frame previo limpio que demuestre que la bolsa
    # estaba plegada antes de empezar a crecer.
    censurado_al_inicio = (inicio == 0)
    if censurado_al_inicio:
        anomalias.append("evento_censurado_al_inicio")

    # R15 (MEDIA-16): no inventar certeza. Máximo confirmado sólo con meseta
    # o caída clara tras el pico; si el clip termina creciendo o no se
    # confirma estabilidad, se publica como máximo visible observado NO
    # confirmado; con señal insuficiente, sin máximo defendible.
    if candidato_meseta is not None or caida_confirmada:
        estado_secuencia = "maximo_inflado_estimado"
    elif "ventana_post_breakout_corta" in anomalias:
        estado_secuencia = "sin_maximo_defendible"
    else:
        estado_secuencia = "maximo_visible_observado_no_confirmado"

    # R15.1 (ALTO-06): anulaciones por censura en frame 0.
    # a) El máximo cae en el propio frame censurado (duración 0 ms): no hay
    #    NINGUNA evidencia de crecimiento observada ⇒ sin máximo defendible;
    #    nunca «máximo inflado estimado 0.000 ms».
    # b) Hay crecimiento observado, pero el primer frame ya ocupa una fracción
    #    relevante del pico (>50%): el despliegue pudo empezar antes de la
    #    grabación y la duración es sólo una cota inferior ⇒ el estimado
    #    confirmado se degrada a máximo visible observado NO confirmado.
    if censurado_al_inicio and frame_max == inicio:
        estado_secuencia = "sin_maximo_defendible"
        anomalias.append("sin_evidencia_previa_del_crecimiento")
    elif (censurado_al_inicio and estado_secuencia == "maximo_inflado_estimado"
            and suav[0] > pico * 0.5):
        estado_secuencia = "maximo_visible_observado_no_confirmado"

    t_break = (inicio * 1000.0 / fps) if fps else None
    t_max = (frame_max * 1000.0 / fps) if fps else None
    dur = ((frame_max - inicio) * 1000.0 / fps) if fps else None

    # R15.2 (ALTO-03): invariante física GLOBAL de Tmax, independiente de la
    # posición del breakout (las reglas R15.1 sólo cubrían el frame 0):
    #
    #     maximo_inflado_estimado ⇒ frame_max > frame_breakout ∧ dur > 0 ms
    #
    # Señal plana (o ya máxima) en el breakout ⇒ la «meseta» cae en el índice
    # 0 del tramo y no existe NINGUNA evidencia de expansión posterior ⇒ no
    # se confirma ningún máximo. Con expansión en frames pero sin fps, la
    # duración no es cuantificable ⇒ se degrada a observado NO confirmado.
    if estado_secuencia == "maximo_inflado_estimado" and (
            frame_max <= inicio or dur is None or dur <= 0.0):
        if frame_max <= inicio:
            estado_secuencia = "sin_maximo_defendible"
            anomalias.append("maximo_coincide_con_breakout")
        else:
            estado_secuencia = "maximo_visible_observado_no_confirmado"
        anomalias.append("sin_evidencia_de_expansion")

    # R15.3 (ALTO-04): invariante física de MAGNITUD/PERSISTENCIA de la
    # expansión. Confirmar exige crecimiento relevante respecto al área en el
    # breakout (piso relativo escalable + piso absoluto de ruido) sostenido
    # varios frames. Sin magnitud no hay nada defendible (el «pico» es ruido);
    # con magnitud pero sin persistencia queda como observado NO confirmado
    # (glitch transitorio: algo visible, no defendible como máximo inflado).
    # El auditor sugiere EXPANSION_POST_BREAKOUT_INSUFICIENTE; se usa
    # snake_case como el resto de anomalías del estándar.
    base_expansion = suav[0]
    crecimiento_expansion = pico - base_expansion
    umbral_magnitud = max(float(expansion_minima_absoluta_px),
                          float(expansion_minima_relativa) * max(base_expansion, 1.0))
    frames_expandidos = sum(1 for v in suav
                            if v >= base_expansion + umbral_magnitud)
    if estado_secuencia == "maximo_inflado_estimado" and (
            crecimiento_expansion < umbral_magnitud
            or frames_expandidos < int(persistencia_expansion_frames)):
        anomalias.append("expansion_post_breakout_insuficiente")
        if crecimiento_expansion < umbral_magnitud:
            estado_secuencia = "sin_maximo_defendible"
        else:
            estado_secuencia = "maximo_visible_observado_no_confirmado"

    confianza_max = 1.0
    if "evento_censurado_al_inicio" in anomalias:
        confianza_max -= 0.20
    if "maximo_en_borde_final_del_clip" in anomalias:
        confianza_max -= 0.35
    if "maximo_sin_caida_o_meseta_clara" in anomalias:
        confianza_max -= 0.20
    if "ventana_post_breakout_corta" in anomalias:
        confianza_max -= 0.20
    # R15.3 (ALTO-04, P2): penalización por expansión insuficiente y tope de
    # coherencia: ningún estado NO confirmado puede viajar con confianza alta
    # (en R15.2 una señal plana devolvía sin_maximo_defendible con 1.0).
    if "expansion_post_breakout_insuficiente" in anomalias:
        confianza_max -= 0.40
    confianza_max = max(0.0, min(1.0, confianza_max))
    if estado_secuencia != "maximo_inflado_estimado":
        confianza_max = min(confianza_max, CONFIANZA_MAX_NO_CONFIRMADO)

    fases = [
        {"estado": "breakout", "frame": inicio},
        # R15 (ALTA-05): orden no decreciente; la expansión nunca queda
        # después del máximo.
        {"estado": "expansion", "frame": min(inicio + 1, frame_max, len(metricas) - 1)},
        {"estado": "maximo_inflado", "frame": frame_max},
    ]
    return {
        "estado": estado_secuencia if frame_max is not None else "breakout_sin_maximo",
        "frame_breakout": inicio,
        "frame_pico_area": frame_pico,
        "frame_max_inflado": int(frame_max),
        "tiempo_breakout_ms": round(t_break, 6) if t_break is not None else None,
        "tiempo_max_inflado_ms": round(t_max, 6) if t_max is not None else None,
        "duracion_expansion_ms": round(dur, 6) if dur is not None else None,
        "area_maxima_estimada_px": int(round(pico)),
        "fraccion_maximo": frac,
        "confianza_maximo": round(confianza_max, 6),
        "fases": fases,
        "anomalías": anomalias,
        "tiempo_relativo_al_inicio_video": True,
        "trigger_electrico_disponible": False,
        "nota_tiempo": "Tiempo relativo al inicio del video; no equivale a tiempo desde detonación.",
        "version": VERSION_ESTANDAR,
    }
