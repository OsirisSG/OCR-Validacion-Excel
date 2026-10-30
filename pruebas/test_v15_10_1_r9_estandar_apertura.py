from __future__ import annotations

import math

import numpy as np

from utilidades.estandar_apertura import evaluar_evidencia_estandar
from utilidades.matriz_apertura import celda_caso, criterio_desde_limites
from utilidades.resultado_caso import resolver_apertura
from video_airbag import _mascara_deformacion, _metricas_primer_blanco, _cfg


def _video(tiempo: float, *, score: float = 0.86, ref: bool = True, video_id: str = "cam1") -> dict:
    return {
        "id": video_id,
        "nombre": f"{video_id}.avi",
        "estado": "candidato",
        "tiempo_ms": tiempo,
        "tiempo_crudo_ms": tiempo,
        "referencia_tiempo_valida": ref,
        "estado_tiempo": "VALIDO" if ref else "REFERENCIA_INVALIDA",
        "frame_evento": 29,
        "resolucion_nativa_ms": 0.2,
        "evaluacion_apertura_estandar": {
            "nivel": "alta" if score >= 0.72 else "media",
            "score_evidencia": score,
            "auto_colorable": score >= 0.72,
            "auto_publicable": False,
            "version_estandar": "apertura-estandar-r9-v1",
        },
    }


def _fila(videos: list[dict], tiempo_propuesto: float) -> dict:
    return {
        "id": "case-1",
        "test_number": "232566",
        "tipo_st": "1ST",
        "temperature_condition": "HT",
        "inflator_type": "UGL",
        "videos": videos,
        "video_apertura": {
            "estado": "candidato",
            "estado_consenso": "propuesto",
            "tiempo_propuesto_ms": tiempo_propuesto,
            "referencia_tiempo_valida": True,
            "estado_tiempo": "VALIDO",
            "soporte": len(videos),
        },
    }


def test_mascara_deformacion_local_crea_rango_alrededor():
    mov = np.zeros((80, 120), dtype=np.float32)
    mov[30:45, 50:70] = 2.5
    rango, info = _mascara_deformacion(mov, {
        "deformacion_movimiento_min_px": 0.35,
        "deformacion_mad_factor": 2.5,
        "deformacion_fraccion_min": 0.0005,
        "deformacion_fraccion_max": 0.45,
        "margen_deformacion_norm": 0.05,
        "margen_deformacion_px_max": 20,
    })
    assert info["confiable"] is True
    assert rango is not None
    assert rango[35, 60]
    assert rango[35, 47]  # margen alrededor de la deformación, no sólo el núcleo
    assert not rango[0, 0]


def test_mascara_deformacion_rechaza_movimiento_global():
    mov = np.ones((60, 100), dtype=np.float32) * 2.0
    rango, info = _mascara_deformacion(mov, {
        "deformacion_movimiento_min_px": 0.35,
        "deformacion_mad_factor": 2.5,
        "deformacion_fraccion_min": 0.0005,
        "deformacion_fraccion_max": 0.45,
    })
    assert rango is None
    assert info["confiable"] is False


def test_evaluacion_estandar_alta_exige_persistencia_y_ausencia_de_riesgo():
    candidato = {
        "score_candidato": 0.92,
        "continuidad_frames": 4,
        "frames_previos_limpios": 3,
        "razones_riesgo": [],
    }
    metrica = {
        "fraccion_material_en_rango": 0.005,
        "fraccion_borde_nuevo": 0.005,
        "deformacion_confiable": True,
        "proximidad_deformacion": True,
        "scores_fuentes": {"material_en_rango": 0.005, "bordes_nuevos": 0.005},
    }
    r = evaluar_evidencia_estandar(candidato, {"razones_en_contra": []}, metrica)
    assert r["nivel"] == "alta"
    assert r["auto_colorable"] is True
    assert r["auto_publicable"] is False
    assert r["score_es_probabilidad"] is False


def test_evaluacion_estandar_se_abstiene_ante_reflejo():
    candidato = {
        "score_candidato": 0.98,
        "continuidad_frames": 4,
        "frames_previos_limpios": 3,
        "razones_riesgo": ["posible_reflejo"],
    }
    metrica = {
        "fraccion_material_en_rango": 0.006,
        "fraccion_borde_nuevo": 0.006,
        "deformacion_confiable": True,
        "proximidad_deformacion": True,
    }
    r = evaluar_evidencia_estandar(candidato, {"razones_en_contra": []}, metrica)
    assert r["auto_colorable"] is False
    assert "posible_reflejo" in r["riesgos"]


def test_propuesta_de_alta_evidencia_puede_colorearse_sin_auto_publicarse():
    fila = _fila([_video(5.8)], 5.8)
    apertura = resolver_apertura(fila)
    assert apertura["estado"] == "PROPUESTA"
    assert apertura["auto_publicable"] is False
    assert apertura["auto_color_elegible"] is True
    assert apertura["tiempo_estimado_auto_ms"] == 5.8

    fila["resultado_caso_canonico"] = {"apertura": apertura}
    celda = celda_caso(fila, criterio_desde_limites(6, 7))
    assert celda["estado"] == "verde"
    assert celda["opening_time_ms"] == 5.8
    assert celda["tiempo_es_estimado"] is True
    assert celda["color_fuente"] == "estimacion_automatica_estandar_r11"
    assert celda["decision_apertura"] == "PROPUESTA"


def test_estimacion_automatica_respeta_amarillo_y_rojo():
    for tiempo, esperado in [(6.4, "amarillo"), (7.2, "rojo")]:
        fila = _fila([_video(tiempo)], tiempo)
        apertura = resolver_apertura(fila)
        fila["resultado_caso_canonico"] = {"apertura": apertura}
        celda = celda_caso(fila, criterio_desde_limites(6, 7))
        assert celda["estado"] == esperado
        assert celda["tiempo_es_estimado"] is True


def test_dos_estimaciones_fuertes_discrepantes_se_abstienen():
    fila = _fila([_video(5.8, video_id="cam1"), _video(7.2, video_id="cam2")], 6.5)
    apertura = resolver_apertura(fila)
    assert apertura["estado"] == "PROPUESTA"
    assert apertura["auto_color_conflicto"] is True
    assert apertura["auto_color_elegible"] is False
    fila["resultado_caso_canonico"] = {"apertura": apertura}
    celda = celda_caso(fila, criterio_desde_limites(6, 7))
    assert celda["estado"] == "gris"


def test_referencia_temporal_invalida_nunca_auto_colorea():
    fila = _fila([_video(5.8, ref=False)], 5.8)
    apertura = resolver_apertura(fila)
    assert apertura["auto_color_elegible"] is False
    fila["resultado_caso_canonico"] = {"apertura": apertura}
    celda = celda_caso(fila, criterio_desde_limites(6, 7))
    assert celda["estado"] == "gris"


def _escena_sintetica(material_x: int):
    rng = np.random.default_rng(1)
    h, w = 120, 180
    base = np.clip(90 + rng.normal(0, 8, (h, w)), 0, 255).astype(np.uint8)
    actual = base.copy()
    region = base[40:80, 70:120]
    actual[40:80, 73:123] = region  # deformación local simulada
    actual[56:62, material_x:material_x + 8] = 220
    return base, actual


def test_material_claro_cerca_deformacion_se_conserva():
    base, actual = _escena_sintetica(116)
    m = _metricas_primer_blanco(actual, base, _cfg({}), {"pixeles": 0, "componente": 0, "score_max": 0})
    assert m["deformacion_confiable"] is True
    assert m["proximidad_deformacion"] is True
    assert m["material_nuevo_en_rango_px"] > 0
    assert m["detectado"] is True


def test_material_claro_lejano_no_se_promueve_como_apertura_fuerte():
    base, actual = _escena_sintetica(10)
    m = _metricas_primer_blanco(actual, base, _cfg({}), {"pixeles": 0, "componente": 0, "score_max": 0})
    assert m["deformacion_confiable"] is True
    assert m["material_nuevo_pre_filtro_px"] > m["material_nuevo_en_rango_px"]
    assert m["detectado"] is False
