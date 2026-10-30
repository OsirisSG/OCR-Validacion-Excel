"""Hipótesis múltiples de onset en modo sombra (V15.10.1).

El score sólo ordena candidatos; no es probabilidad ni decisión de publicación.
Las features proceden del mismo video/detector y por ello no se cuentan como
votos estadísticamente independientes.
"""
from __future__ import annotations

import math
from typing import Any

VERSION_CANDIDATOS = "onset-hypotheses-r11-component-tracks-v4"


def _finito(valor: Any, defecto: float = 0.0) -> float:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return defecto
    return numero if math.isfinite(numero) else defecto


def _es_indicio(metrica: dict) -> bool:
    return bool(metrica.get("evidencia_debil") or metrica.get("detectado") or
                int(metrica.get("pixeles_ruptura") or 0) > 0 or
                int(metrica.get("pixeles_blanco_nuevo") or 0) > 0 or
                int(metrica.get("pixeles_grieta_nueva") or 0) > 0)


def _centro(metrica: dict) -> tuple[float, float] | None:
    centro = metrica.get("centro_componente_norm")
    if isinstance(centro, (list, tuple)) and len(centro) == 2:
        x, y = _finito(centro[0], -1), _finito(centro[1], -1)
        if 0 <= x <= 1 and 0 <= y <= 1:
            return x, y
    caja = metrica.get("bbox_componente_norm")
    if isinstance(caja, (list, tuple)) and len(caja) == 4:
        x1, y1, x2, y2 = map(_finito, caja)
        if 0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1:
            return (x1 + x2) / 2, (y1 + y2) / 2
    return None


def _misma_microzona(a: dict, b: dict, tolerancia: float = 0.12) -> bool:
    """Asocia evidencia sólo cuando las regiones son espacialmente compatibles.

    R11 prioriza distancia geométrica real (bbox + radio de seguimiento en
    píxeles) cuando las métricas conservan tamaño de ROI. Esto evita fusionar un
    píxel caliente cercano con una ruptura verdadera que aparece varios píxeles
    después. Si no hay geometría suficiente se conserva el fallback normalizado.
    """
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    bba = a.get("bbox_componente_norm")
    bbb = b.get("bbox_componente_norm")
    ancho = max(int(a.get("roi_ancho") or 0), int(b.get("roi_ancho") or 0))
    alto = max(int(a.get("roi_alto") or 0), int(b.get("roi_alto") or 0))
    if (isinstance(bba, (list, tuple)) and len(bba) == 4
            and isinstance(bbb, (list, tuple)) and len(bbb) == 4
            and ancho > 0 and alto > 0):
        try:
            a1, a2, a3, a4 = map(float, bba)
            b1, b2, b3, b4 = map(float, bbb)
            radio_px = max(float(a.get("radio_indicio_px") or 3.0),
                           float(b.get("radio_indicio_px") or 3.0))
            tx = max(1.0, radio_px) / ancho
            ty = max(1.0, radio_px) / alto
            return not (a3 + tx < b1 or b3 + tx < a1 or a4 + ty < b2 or b4 + ty < a2)
        except (TypeError, ValueError, OverflowError):
            pass
    ca, cb = _centro(a), _centro(b)
    if ca is None or cb is None:
        return True  # Sin geometría, se conserva como evidencia débil, no como corroboración independiente.
    return math.hypot(ca[0] - cb[0], ca[1] - cb[1]) <= tolerancia


def _senal_principal(metrica: dict) -> tuple[float, list[str]]:
    scores = metrica.get("scores_fuentes") or {}
    pixeles = max(int(metrica.get("pixeles_ruptura") or 0),
                  int(metrica.get("pixeles_blanco_nuevo") or 0),
                  int(metrica.get("pixeles_grieta_nueva") or 0))
    minimo = max(1, int(metrica.get("min_pixeles_debil") or 1))
    componente = max(int(metrica.get("componente_ruptura_px") or 0),
                     int(metrica.get("componente_blanco_px") or 0))
    min_componente = max(1, int(metrica.get("min_componente_debil") or 1))
    ruptura = min(1.0, max(pixeles / minimo, componente / min_componente) / 4.0)
    borde = min(1.0, _finito(scores.get("bordes_nuevos"),
                             _finito(metrica.get("fraccion_borde_nuevo"))) / 0.004)
    material_rango = min(1.0, max(
        _finito(scores.get("material_en_rango")),
        _finito(metrica.get("fraccion_material_en_rango"))) / 0.004)
    señales = []
    if _finito(scores.get("fisura")) > 0 or int(metrica.get("pixeles_grieta_nueva") or 0) > 0:
        señales.append("fisura_oscura")
    if _finito(scores.get("tela_clara")) > 0 or int(metrica.get("pixeles_blanco_nuevo") or 0) > 0:
        señales.append("material_claro_nuevo")
    if borde > 0:
        señales.append("borde_local_nuevo")
    if material_rango > 0:
        señales.append("material_nuevo_en_rango_deformacion")
    return ruptura, señales



def _vista_componente(metrica: dict, componente: dict) -> dict:
    """Proyecta un componente individual como una métrica compatible."""
    salida = dict(metrica)
    try:
        area = int(componente.get("area") or 0)
        blancos = int(componente.get("blancos") or 0)
        grieta = int(componente.get("grieta") or max(0, area - blancos))
    except (TypeError, ValueError, OverflowError):
        area = blancos = grieta = 0
    salida.update({
        "pixeles_ruptura": area,
        "componente_ruptura_px": area,
        "pixeles_blanco_nuevo": blancos,
        "pixeles_grieta_nueva": grieta,
        "componente_blanco_px": area,
        "bbox_componente": componente.get("bbox"),
        "bbox_componente_norm": componente.get("bbox_norm"),
        "centro_componente_norm": componente.get("centro_norm"),
        "evidencia_debil": area >= max(1, int(metrica.get("min_componente_debil") or 1)),
        "detectado": area >= max(1, int(metrica.get("min_componente_blanco") or 1)),
        # Un componente proyectado no debe volver a expandirse recursivamente.
        "componentes_indicio": None,
    })
    return salida


def _vistas_indicio(metrica: dict) -> list[dict]:
    """Devuelve todas las microzonas candidatas de un cuadro, no sólo la mayor.

    R11 evita que un píxel caliente persistente tape una segunda microzona donde
    realmente empieza la ruptura del airbag.
    """
    if not isinstance(metrica, dict):
        return []
    componentes = metrica.get("componentes_indicio")
    vistas: list[dict] = []
    if isinstance(componentes, list):
        for comp in componentes:
            if not isinstance(comp, dict):
                continue
            vista = _vista_componente(metrica, comp)
            if _es_indicio(vista):
                vistas.append(vista)
    if not vistas and _es_indicio(metrica):
        vistas.append(metrica)
    return vistas


def _distancia_microzona(a: dict, b: dict) -> float:
    ca, cb = _centro(a), _centro(b)
    if ca is None or cb is None:
        return 999.0
    ancho = max(int(a.get("roi_ancho") or 1), int(b.get("roi_ancho") or 1))
    alto = max(int(a.get("roi_alto") or 1), int(b.get("roi_alto") or 1))
    return math.hypot((ca[0] - cb[0]) * ancho, (ca[1] - cb[1]) * alto)


def _vista_fuerte(vista: dict) -> bool:
    pix = max(int(vista.get("pixeles_ruptura") or 0),
              int(vista.get("pixeles_blanco_nuevo") or 0),
              int(vista.get("pixeles_grieta_nueva") or 0))
    comp = max(int(vista.get("componente_ruptura_px") or 0),
               int(vista.get("componente_blanco_px") or 0))
    min_pix = max(1, int(vista.get("min_pixeles_debil") or 1))
    min_comp = max(1, int(vista.get("min_componente_debil") or 1))
    return bool(vista.get("detectado") or pix >= 2 * min_pix or comp >= 2 * min_comp)


def _construir_trayectorias(metricas: list[dict], inicio: int, max_hueco_frames: int) -> list[list[tuple[int, dict]]]:
    """Enlaza componentes por microzona y permite huecos sólo hacia evidencia fuerte.

    Esto separa un píxel caliente de otra ruptura simultánea y, a la vez,
    permite que un frame intermedio perdido por compresión no borre un onset
    real cuando el siguiente soporte ya es fuerte.
    """
    trayectorias: list[list[tuple[int, dict]]] = []
    max_huecos = max(0, int(max_hueco_frames))
    for frame in range(inicio, len(metricas)):
        vistas = _vistas_indicio(metricas[frame])
        usados: set[int] = set()
        for vista in vistas:
            opciones = []
            for idx, tray in enumerate(trayectorias):
                if idx in usados or not tray:
                    continue
                ultimo_frame, ultima_vista = tray[-1]
                salto = frame - ultimo_frame
                if salto <= 0 or salto > max_huecos + 1:
                    continue
                huecos = salto - 1
                if not _misma_microzona(ultima_vista, vista):
                    continue
                # Un salto sobre cuadro(s) limpio(s) sólo se reanuda cuando la
                # evidencia nueva ya es fuerte. Evita F5 ruido -> F7 píxel débil.
                if huecos > 0 and not _vista_fuerte(vista):
                    continue
                opciones.append((_distancia_microzona(ultima_vista, vista), idx))
            if opciones:
                _, elegido = min(opciones, key=lambda x: x[0])
                trayectorias[elegido].append((frame, vista))
                usados.add(elegido)
            else:
                trayectorias.append([(frame, vista)])
    return trayectorias

def generar_candidatos(metricas: list[dict], *, nbase: int = 0,
                        fps_adquisicion: float | None = None,
                        t0_local_ms: float = 0.0,
                        max_candidatos: int = 3,
                        max_hueco_frames: int = 1,
                        ventana_corrobora: int = 5) -> list[dict]:
    """Devuelve hipótesis por trayectoria espacial, conservando el primer onset.

    R11 sigue componentes individuales. Un hot-pixel puede coexistir con una
    segunda microzona real sin secuestrar el candidato principal.
    """
    if not isinstance(metricas, list) or not metricas:
        return []
    inicio = max(0, int(nbase or 0))
    trayectorias = _construir_trayectorias(metricas, inicio, max_hueco_frames)
    if not trayectorias:
        return []

    fps = _finito(fps_adquisicion, 0.0)
    if fps <= 0:
        fps = 0.0
    t0 = _finito(t0_local_ms, 0.0)
    candidatos = []
    ventana_max = max(1, int(ventana_corrobora))

    for tray in trayectorias:
        if not tray:
            continue
        frame = int(tray[0][0])
        primera = tray[0][1]
        limite_frame = frame + ventana_max
        apoyo_tray = [(f, m) for f, m in tray if f <= limite_frame]
        apoyos = [f for f, _ in apoyo_tray]
        ventana_metricas = [m for _, m in apoyo_tray]
        if not ventana_metricas:
            continue
        centro = _centro(primera)
        continuidad = len(apoyos)
        ruptura, señales = _senal_principal(primera)
        scores = primera.get("scores_fuentes") or {}
        reflejo = _finito(scores.get("reflejo"))
        abombamiento = _finito(scores.get("abombamiento"))
        riesgo = []
        if primera.get("cambio_global_sospechoso"):
            riesgo.append("cambio_global_sospechoso")
        if reflejo > max(0.001, ruptura * 1.5):
            riesgo.append("posible_reflejo")
        if abombamiento > max(0.01, ruptura * 1.5) and ruptura < 0.5:
            riesgo.append("posible_abombamiento_sin_ruptura")
        if primera.get("deformacion_confiable") and primera.get("proximidad_deformacion") is False:
            riesgo.append("material_fuera_de_zona_deformacion")

        continuidad_score = min(1.0, max(0, continuidad - 1) / 2.0)
        max_pixeles = max([int(m.get("pixeles_ruptura") or 0) for m in ventana_metricas] or [0])
        max_componente = max([int(m.get("componente_ruptura_px") or 0) for m in ventana_metricas] or [0])
        min_pix = max(1, int(primera.get("min_pixeles_debil") or 1))
        min_comp = max(1, int(primera.get("min_componente_debil") or 1))
        soporte_posterior = min(1.0, max(max_pixeles / min_pix, max_componente / min_comp) / 2.0)
        max_material_frac = max([
            max(_finito((m.get("scores_fuentes") or {}).get("material_en_rango")),
                _finito(m.get("fraccion_material_en_rango")))
            for m in ventana_metricas
        ] or [0.0])
        material_rango = min(1.0, max_material_frac / 0.0005) if max_material_frac > 0 else 0.0
        prox_true = sum(1 for m in ventana_metricas if m.get("proximidad_deformacion") is True)
        deform_true = sum(1 for m in ventana_metricas if m.get("deformacion_confiable") is True)
        proximidad_bonus = (1.0 if (primera.get("proximidad_deformacion") is True or prox_true)
                            else 0.55 if not deform_true else 0.0)
        penalizacion = min(0.56, 0.18 * len(riesgo))
        score = max(0.0, min(1.0,
                    0.26 * ruptura
                    + 0.18 * soporte_posterior
                    + 0.12 * min(1.0, max(
                        [_finito((m.get("scores_fuentes") or {}).get("bordes_nuevos"),
                                 _finito(m.get("fraccion_borde_nuevo"))) for m in ventana_metricas] or [0.0]) / 0.002)
                    + 0.10 * material_rango
                    + 0.22 * continuidad_score
                    + 0.12 * proximidad_bonus
                    - penalizacion))
        resolucion = 1000.0 / fps if fps else None
        tiempo = t0 + frame * resolucion if resolucion is not None else None
        intervalo = ([max(0.0, tiempo - resolucion / 2), tiempo + resolucion / 2]
                     if tiempo is not None and resolucion is not None else None)

        prev_inicio = max(inicio, frame - 4)
        previos_limpios = []
        for k in range(prev_inicio, frame):
            vistas_prev = _vistas_indicio(metricas[k])
            if not any(_misma_microzona(primera, vp) for vp in vistas_prev):
                previos_limpios.append(k)

        candidatos.append({
            "frame": frame,
            "frame_confirmacion_sugerido": int(max(apoyos)),
            "frames_evidencia": sorted(set(apoyos)),
            "tiempo_local_ms": (round(tiempo, 6) if tiempo is not None else None),
            "intervalo_tiempo_local_ms": ([round(x, 6) for x in intervalo]
                                           if intervalo is not None else None),
            "resolucion_ms": round(resolucion, 6) if resolucion is not None else None,
            "origen_tiempo": "fps_adquisicion_local_no_sincronizado" if fps else "sin_fps_adquisicion_verificado",
            "score_candidato": round(score, 6),
            "score_es_probabilidad": False,
            "tipo_senales": señales,
            "bbox_norm": primera.get("bbox_componente_norm"),
            "microzona_centro_norm": list(centro) if centro else None,
            "pixeles_ruptura": int(primera.get("pixeles_ruptura") or 0),
            "material_nuevo_en_rango_px": int(primera.get("material_nuevo_en_rango_px") or 0),
            "fraccion_material_en_rango": _finito(primera.get("fraccion_material_en_rango")),
            "max_pixeles_ruptura_confirmacion": int(max_pixeles),
            "max_componente_ruptura_confirmacion": int(max_componente),
            "max_fraccion_material_confirmacion": round(float(max_material_frac), 8),
            "frames_deformacion_confiable": int(deform_true),
            "frames_proximidad_deformacion": int(prox_true),
            "deformacion_confiable": bool(primera.get("deformacion_confiable") or deform_true),
            "proximidad_deformacion": (True if prox_true else primera.get("proximidad_deformacion")),
            "continuidad_frames": continuidad,
            "frames_previos_limpios": len(previos_limpios),
            "razones_riesgo": riesgo,
            "limitaciones": ["Features correlacionadas del mismo video; no son votos independientes."],
            "version_candidatos": "onset-hypotheses-r11-component-tracks-v4",
        })

    # R11: una fisura oscura mínima puede aparecer antes de que el detector
    # morfológico consiga seguirla de forma continua. Si pocos cuadros después
    # surge una trayectoria fuerte en la MISMA microzona y crece de verdad,
    # usamos esa trayectoria sólo para corroborar el primer frame; nunca para
    # desplazarlo hacia delante. Esto recupera el primer píxel/fisura real sin
    # fusionar ruido claro aislado separado por un cuadro limpio.
    for temprano in candidatos:
        senales_temprano = set(temprano.get("tipo_senales") or [])
        if "fisura_oscura" not in senales_temprano:
            continue
        if int(temprano.get("continuidad_frames") or 0) > 1:
            continue
        c0 = temprano.get("microzona_centro_norm")
        if not (isinstance(c0, (list, tuple)) and len(c0) == 2):
            continue
        try:
            f0 = int(temprano.get("frame"))
            p0 = max(1, int(temprano.get("pixeles_ruptura") or 1))
        except (TypeError, ValueError, OverflowError):
            continue
        opciones = []
        for posterior in candidatos:
            try:
                f1 = int(posterior.get("frame"))
            except (TypeError, ValueError, OverflowError):
                continue
            # La corroboración diferida es corta: sirve para huecos del
            # detector, no para unir eventos independientes.
            if not (1 <= f1 - f0 <= max(4, int(max_hueco_frames) + 2)):
                continue
            if int(posterior.get("continuidad_frames") or 0) < 3:
                continue
            c1 = posterior.get("microzona_centro_norm")
            if not (isinstance(c1, (list, tuple)) and len(c1) == 2):
                continue
            try:
                distancia = math.hypot(float(c0[0]) - float(c1[0]),
                                       float(c0[1]) - float(c1[1]))
            except (TypeError, ValueError, OverflowError):
                continue
            if distancia > 0.06:
                continue
            max_post = max(int(posterior.get("max_pixeles_ruptura_confirmacion") or 0),
                           int(posterior.get("max_componente_ruptura_confirmacion") or 0),
                           int(posterior.get("pixeles_ruptura") or 0))
            if max_post < max(3, 3 * p0):
                continue
            opciones.append((f1, distancia, posterior))
        if opciones:
            _, _, posterior = min(opciones, key=lambda x: (x[0], x[1]))
            soportes = sorted(set(
                [f0] + [int(x) for x in (posterior.get("frames_evidencia") or [])
                        if str(x).lstrip("-").isdigit()]
            ))
            temprano["frames_evidencia"] = soportes
            temprano["continuidad_frames"] = len(soportes)
            temprano["frame_confirmacion_sugerido"] = max(soportes)
            temprano["max_pixeles_ruptura_confirmacion"] = max(
                int(temprano.get("max_pixeles_ruptura_confirmacion") or 0),
                int(posterior.get("max_pixeles_ruptura_confirmacion") or 0))
            temprano["max_componente_ruptura_confirmacion"] = max(
                int(temprano.get("max_componente_ruptura_confirmacion") or 0),
                int(posterior.get("max_componente_ruptura_confirmacion") or 0))
            temprano["max_fraccion_material_confirmacion"] = max(
                float(temprano.get("max_fraccion_material_confirmacion") or 0.0),
                float(posterior.get("max_fraccion_material_confirmacion") or 0.0))
            temprano["corroboracion_diferida_fisura"] = True
            temprano.setdefault("limitaciones", []).append(
                "Onset oscuro mínimo corroborado por crecimiento posterior en la misma microzona.")

    candidatos.sort(key=lambda x: (-x["score_candidato"], x["frame"]))
    limite = max(1, min(16, int(max_candidatos or 3)))
    return candidatos[:limite]
