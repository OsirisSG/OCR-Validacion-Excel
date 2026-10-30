"""Verificador conservador de candidatos de apertura.

R11 verifica la *trayectoria espacial* que produjo el candidato, no la señal
agregada/mayor de cada cuadro. Esto evita que un hot-pixel o un indicio cercano
pero distinto haga parecer que la ruptura real ya existía antes.

El verificador sigue siendo una segunda lectura del mismo vídeo: no se presenta
como voto estadísticamente independiente y nunca autoconfirma por sí solo.
"""
from __future__ import annotations

import math
from typing import Any

VERSION_VERIFICADOR = "verificador-apertura-r11-microzona-v3"


def _finito(valor: Any, defecto: float = 0.0) -> float:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return defecto
    return numero if math.isfinite(numero) else defecto


def _es_indicio(metrica: dict | None) -> bool:
    if not isinstance(metrica, dict):
        return False
    return bool(
        metrica.get("evidencia_debil") or metrica.get("detectado")
        or int(metrica.get("pixeles_ruptura") or 0) > 0
        or int(metrica.get("pixeles_blanco_nuevo") or 0) > 0
        or int(metrica.get("pixeles_grieta_nueva") or 0) > 0
    )


def _centro(metrica: dict | None) -> tuple[float, float] | None:
    if not isinstance(metrica, dict):
        return None
    centro = metrica.get("centro_componente_norm")
    if isinstance(centro, (list, tuple)) and len(centro) == 2:
        x, y = _finito(centro[0], -1), _finito(centro[1], -1)
        if 0 <= x <= 1 and 0 <= y <= 1:
            return x, y
    caja = metrica.get("bbox_componente_norm")
    if isinstance(caja, (list, tuple)) and len(caja) == 4:
        x1, y1, x2, y2 = map(_finito, caja)
        if 0 <= x1 <= x2 <= 1 and 0 <= y1 <= y2 <= 1:
            return (x1 + x2) / 2, (y1 + y2) / 2
    return None


def _bbox(metrica: dict | None) -> tuple[float, float, float, float] | None:
    if not isinstance(metrica, dict):
        return None
    caja = metrica.get("bbox_componente_norm")
    if not (isinstance(caja, (list, tuple)) and len(caja) == 4):
        caja = metrica.get("bbox_norm")
    if isinstance(caja, (list, tuple)) and len(caja) == 4:
        vals = tuple(_finito(x, -1) for x in caja)
        x1, y1, x2, y2 = vals
        if 0 <= x1 <= x2 <= 1 and 0 <= y1 <= y2 <= 1:
            return vals
    return None


def _vista_componente(metrica: dict, componente: dict) -> dict:
    """Proyecta un componente individual sin perder geometría/umbrales."""
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
        "componentes_indicio": None,
    })
    return salida


def _vistas_indicio(metrica: dict | None) -> list[dict]:
    if not isinstance(metrica, dict):
        return []
    componentes = metrica.get("componentes_indicio")
    vistas: list[dict] = []
    if isinstance(componentes, list):
        for comp in componentes:
            if isinstance(comp, dict):
                vista = _vista_componente(metrica, comp)
                if _es_indicio(vista):
                    vistas.append(vista)
    if not vistas and _es_indicio(metrica):
        vistas.append(metrica)
    return vistas


def _radio_px(m: dict | None) -> float:
    if not isinstance(m, dict):
        return 2.0
    try:
        r = float(m.get("radio_indicio_px") or 0)
    except (TypeError, ValueError):
        r = 0.0
    if r > 0 and math.isfinite(r):
        return r
    caja = _bbox(m)
    ancho = max(1, int(m.get("roi_ancho") or 1))
    alto = max(1, int(m.get("roi_alto") or 1))
    if caja:
        x1, y1, x2, y2 = caja
        return max(2.0, 0.5 * math.hypot((x2 - x1) * ancho, (y2 - y1) * alto))
    return 2.0


def _misma_microzona(a: dict | None, b: dict | None) -> bool:
    """Compara microzonas en píxeles cuando hay dimensiones de ROI.

    La tolerancia antigua fija (12 % del frame) fusionaba señales físicamente
    distintas. R11 usa tamaño/radio local y sólo cae a distancia normalizada
    cuando las métricas no conservan dimensiones.
    """
    ca, cb = _centro(a), _centro(b)
    if ca is None or cb is None:
        return False
    ancho = max(int((a or {}).get("roi_ancho") or 0), int((b or {}).get("roi_ancho") or 0))
    alto = max(int((a or {}).get("roi_alto") or 0), int((b or {}).get("roi_alto") or 0))
    if ancho > 1 and alto > 1:
        distancia = math.hypot((ca[0] - cb[0]) * ancho, (ca[1] - cb[1]) * alto)
        tolerancia = max(3.0, 1.75 * max(_radio_px(a), _radio_px(b)))
        return distancia <= tolerancia
    # Compatibilidad con registros antiguos sin tamaño de ROI: mucho más
    # estricta que el 0.12 heredado, pero tolera pequeños movimientos.
    return math.hypot(ca[0] - cb[0], ca[1] - cb[1]) <= 0.035


def _ancla_candidato(candidato: dict, metrica_frame: dict) -> dict:
    """Construye la microzona canónica desde el candidato, no desde la mayor señal."""
    ancla = dict(metrica_frame)
    centro = candidato.get("microzona_centro_norm")
    bbox = candidato.get("bbox_norm")
    if isinstance(centro, (list, tuple)) and len(centro) == 2:
        ancla["centro_componente_norm"] = list(centro)
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        ancla["bbox_componente_norm"] = list(bbox)
    if candidato.get("pixeles_ruptura") is not None:
        ancla["pixeles_ruptura"] = candidato.get("pixeles_ruptura")
        ancla["componente_ruptura_px"] = candidato.get("pixeles_ruptura")
    return ancla


def _hay_indicio_en_microzona(metrica: dict | None, ancla: dict) -> bool:
    return any(_misma_microzona(ancla, vista) for vista in _vistas_indicio(metrica))


def verificar_candidato(candidato: dict | None,
                        metricas: list[dict] | None,
                        *,
                        nbase: int = 0,
                        calidad_video: dict | None = None,
                        calidad_roi: dict | None = None,
                        advertencias: list[str] | None = None) -> dict:
    """Evalúa un candidato respetando su trayectoria espacial.

    Un indicio anterior sólo invalida el onset si llega *contiguamente* hasta
    el candidato en la misma microzona. Un cuadro limpio corta esa historia.
    La continuidad posterior se toma primero de ``frames_evidencia`` porque esa
    lista ya fue construida siguiendo componentes individuales.
    """
    candidato = candidato if isinstance(candidato, dict) else {}
    metricas = metricas if isinstance(metricas, list) else []
    calidad_video = calidad_video if isinstance(calidad_video, dict) else {}
    calidad_roi = calidad_roi if isinstance(calidad_roi, dict) else {}
    advertencias = [a for a in (advertencias or []) if a]

    frame = candidato.get("frame")
    try:
        frame = int(frame)
    except (TypeError, ValueError, OverflowError):
        frame = None

    razones_a_favor: list[str] = []
    razones_en_contra: list[str] = []

    if frame is None or frame < 0 or frame >= len(metricas):
        return {
            "estado_revision": "no_evaluable",
            "razones_a_favor": [],
            "razones_en_contra": ["candidato_fuera_de_rango"],
            "fotogramas_evidencia": [],
            "calidad_registro": "desconocida",
            "es_independiente_del_detector": False,
            "auto_confirmable": False,
            "probabilidad_calibrada": None,
            "version_verificador": VERSION_VERIFICADOR,
        }

    ancla = _ancla_candidato(candidato, metricas[frame])

    # Sólo la evidencia CONTIGUA inmediatamente anterior cuenta como prueba de
    # que el onset empezó antes. En cuanto aparece un cuadro limpio, se corta.
    evidencia_previa_contigua: list[int] = []
    for k in range(frame - 1, max(int(nbase or 0), frame - 8) - 1, -1):
        if _hay_indicio_en_microzona(metricas[k], ancla):
            evidencia_previa_contigua.append(k)
        else:
            break

    if evidencia_previa_contigua:
        razones_en_contra.append("evidencia_previa_contigua_misma_microzona")
    else:
        razones_a_favor.append("previo_inmediato_limpio")

    soportes = []
    for raw in candidato.get("frames_evidencia") or []:
        try:
            idx = int(raw)
        except (TypeError, ValueError, OverflowError):
            continue
        if frame <= idx < len(metricas):
            soportes.append(idx)
    soportes = sorted(set(soportes))

    posteriores_track = [k for k in soportes if k > frame]
    if not posteriores_track:
        # Fallback para candidatos antiguos sin frames_evidencia: seguir la
        # microzona hasta 8 cuadros hacia delante, sin usar el componente mayor.
        for k in range(frame + 1, min(len(metricas), frame + 9)):
            if _hay_indicio_en_microzona(metricas[k], ancla):
                posteriores_track.append(k)

    fotogramas_evidencia = sorted(set([frame] + posteriores_track))
    if posteriores_track:
        razones_a_favor.append("continuidad_espacial_posterior")
    else:
        razones_en_contra.append("sin_continuidad_posterior")

    # R10/R11: crecimiento posterior puede corroborar un primer fragmento de
    # un píxel. No exigimos que el onset inicial tenga gran área.
    try:
        inicial_px = max(1, int(candidato.get("pixeles_ruptura") or 1))
        max_px = int(candidato.get("max_pixeles_ruptura_confirmacion") or inicial_px)
        max_comp = int(candidato.get("max_componente_ruptura_confirmacion") or inicial_px)
        crecimiento = max(max_px, max_comp) / inicial_px
    except (TypeError, ValueError, OverflowError):
        crecimiento = 1.0
    if crecimiento >= 2.0:
        razones_a_favor.append("crecimiento_posterior_desde_onset_minimo")

    # Señales geométricas preferentemente desde el candidato/estándar.
    proximidad = candidato.get("proximidad_deformacion")
    deformacion = candidato.get("deformacion_confiable")
    if proximidad is True:
        razones_a_favor.append("material_nuevo_en_rango_deformacion")
    elif deformacion and proximidad is False:
        razones_en_contra.append("material_fuera_de_zona_deformacion")

    primera = ancla
    scores = primera.get("scores_fuentes") or {}
    if _finito(scores.get("reflejo")) > max(0.01, _finito(scores.get("fisura")) * 1.5):
        razones_en_contra.append("posible_reflejo")
    if _finito(scores.get("abombamiento")) > max(0.01, _finito(scores.get("fisura")) * 1.5):
        razones_en_contra.append("posible_abombamiento")
    if primera.get("cambio_global_sospechoso"):
        razones_en_contra.append("cambio_global_sospechoso")

    if calidad_roi.get("alineacion_confiable") is False:
        razones_en_contra.append("alineacion_roi_no_confiable")
    if calidad_roi.get("ocluida") is True:
        razones_en_contra.append("roi_ocluida")
    if calidad_video.get("overlay_contradictorio"):
        razones_en_contra.append("overlay_contradictorio")
    if advertencias:
        razones_en_contra.extend([f"advertencia:{str(a)}" for a in advertencias])

    bloqueos = [r for r in razones_en_contra if not r.startswith("advertencia:")]
    if evidencia_previa_contigua:
        estado = "revisar_conflicto"
    elif posteriores_track and not bloqueos:
        estado = "propuesta_alta_confianza"
    elif posteriores_track:
        estado = "evidencia_corrobora"
    else:
        estado = "propuesta_revisar"

    return {
        "estado_revision": estado,
        "razones_a_favor": razones_a_favor,
        "razones_en_contra": razones_en_contra,
        "fotogramas_evidencia": fotogramas_evidencia,
        "frames_previos_contiguos": sorted(evidencia_previa_contigua),
        "crecimiento_relativo": round(float(crecimiento), 4),
        "calidad_registro": "suficiente" if "alineacion_roi_no_confiable" not in razones_en_contra else "limitada",
        "es_independiente_del_detector": False,
        "auto_confirmable": False,
        "probabilidad_calibrada": None,
        "version_verificador": VERSION_VERIFICADOR,
    }
