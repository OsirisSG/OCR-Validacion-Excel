from __future__ import annotations

from utilidades.estandar_apertura import evaluar_evidencia_estandar
from utilidades.evidencia_apertura import generar_candidatos
from utilidades.matriz_apertura import celda_caso, criterio_desde_limites
from utilidades.resultado_caso import resolver_apertura
from video_airbag import fps_temporal_confiable


def _m(*, pix=0, comp=0, prox=None, deform=False, borde=0.0, material=0.0, detectado=False):
    return {
        "evidencia_debil": bool(pix or comp or detectado),
        "detectado": detectado,
        "pixeles_ruptura": pix,
        "pixeles_blanco_nuevo": pix,
        "pixeles_grieta_nueva": 0,
        "componente_ruptura_px": comp,
        "componente_blanco_px": comp,
        "min_pixeles_debil": 1,
        "min_componente_debil": 1,
        "centro_componente_norm": [0.5, 0.5] if (pix or comp) else None,
        "bbox_componente_norm": [0.49, 0.49, 0.51, 0.51] if (pix or comp) else None,
        "fraccion_material_en_rango": material,
        "fraccion_borde_nuevo": borde,
        "deformacion_confiable": deform,
        "proximidad_deformacion": prox,
        "scores_fuentes": {
            "tela_clara": material,
            "fisura": 0.0,
            "material_en_rango": material,
            "bordes_nuevos": borde,
            "reflejo": 0.0,
            "abombamiento": 0.0,
        },
    }


def test_primer_pixel_se_conserva_y_frames_posteriores_lo_confirman():
    metricas = [_m(), _m(), _m(),
                _m(pix=1, comp=1, prox=True, deform=True, borde=0.0002, material=0.00002),
                _m(pix=4, comp=4, prox=True, deform=True, borde=0.001, material=0.0002, detectado=True),
                _m(pix=9, comp=9, prox=True, deform=True, borde=0.002, material=0.0005, detectado=True)]
    candidatos = generar_candidatos(metricas, nbase=2, fps_adquisicion=5000)
    assert candidatos
    c = candidatos[0]
    assert c["frame"] == 3
    assert c["max_pixeles_ruptura_confirmacion"] >= 9
    ventana = [metricas[i] for i in c["frames_evidencia"]]
    ev = evaluar_evidencia_estandar(c, {"razones_en_contra": []}, metricas[c["frame"]],
                                    metricas_ventana=ventana, umbral_alta=0.64)
    assert ev["nivel"] == "alta"
    assert ev["auto_colorable"] is True
    assert "crecimiento_o_persistencia_posterior" in ev["razones"]


def test_senal_lejana_de_deformacion_no_auto_colorea():
    metricas = [_m(), _m(), _m(),
                _m(pix=2, comp=2, prox=False, deform=True, borde=0.002, material=0.0004),
                _m(pix=6, comp=6, prox=False, deform=True, borde=0.003, material=0.0008, detectado=True)]
    c = generar_candidatos(metricas, nbase=2, fps_adquisicion=5000)[0]
    ventana = [metricas[i] for i in c["frames_evidencia"]]
    ev = evaluar_evidencia_estandar(c, {"razones_en_contra": ["material_fuera_de_zona_deformacion"]},
                                    metricas[c["frame"]], metricas_ventana=ventana)
    assert ev["auto_colorable"] is False
    assert ev["nivel"] != "alta"


def test_fps_de_reproduccion_8_no_es_referencia_para_color():
    fps, fuente = fps_temporal_confiable(None, 8.0, {"video_airbag": {"fps_archivo_minimo_confiable": 500.0}})
    assert fps is None
    assert fuente == "desconocido"


def test_fps_alta_velocidad_si_puede_sostener_color_estimado():
    fps, fuente = fps_temporal_confiable(None, 5000.0, {"video_airbag": {"fps_archivo_minimo_confiable": 500.0}})
    assert fps == 5000.0
    assert fuente == "archivo"


def _fila_color(tiempo=5.8, ref_color=True, score=0.82):
    return {
        "id": "c1", "test_number": "232566", "temperature_condition": "HT", "inflator_type": "UGL",
        "videos": [{
            "id": "cam1", "estado": "candidato",
            "tiempo_ms": None,
            "referencia_tiempo_valida": False,
            "tiempo_color_estimado_ms": tiempo,
            "referencia_color_valida": ref_color,
            "fuente_tiempo_color": "overlay_rec",
            "frame_color_estimado": 29,
            "resolucion_nativa_ms": 0.2,
            "evaluacion_apertura_estandar": {
                "nivel": "alta", "score_evidencia": score,
                "auto_colorable": True, "auto_publicable": False,
                "version_estandar": "apertura-estandar-r10-v2",
            },
        }],
    }


def test_color_estimado_usa_canal_temporal_separado_sin_publicar():
    fila = _fila_color(5.8, True)
    apertura = resolver_apertura(fila)
    assert apertura["estado"] == "NO_OBSERVADO" or apertura["estado"] == "PROPUESTA"
    assert apertura["auto_color_elegible"] is True
    assert apertura["tiempo_estimado_auto_ms"] == 5.8
    fila["resultado_caso_canonico"] = {"apertura": apertura}
    celda = celda_caso(fila, criterio_desde_limites(6, 7))
    assert celda["estado"] == "verde"
    assert celda["tiempo_es_estimado"] is True
    assert celda["color_fuente"] == "estimacion_automatica_estandar_r11"


def test_sin_referencia_de_color_permanece_gris():
    fila = _fila_color(5.8, False)
    apertura = resolver_apertura(fila)
    assert apertura["auto_color_elegible"] is False
    fila["resultado_caso_canonico"] = {"apertura": apertura}
    celda = celda_caso(fila, criterio_desde_limites(6, 7))
    assert celda["estado"] == "gris"


def test_conflicto_entre_estimaciones_fuertes_se_abstiene():
    fila = _fila_color(5.8, True)
    fila["videos"].append({
        "id": "cam2", "estado": "candidato",
        "tiempo_ms": None, "referencia_tiempo_valida": False,
        "tiempo_color_estimado_ms": 7.2, "referencia_color_valida": True,
        "fuente_tiempo_color": "overlay_rec", "frame_color_estimado": 36,
        "resolucion_nativa_ms": 0.2,
        "evaluacion_apertura_estandar": {
            "nivel": "alta", "score_evidencia": 0.84,
            "auto_colorable": True, "auto_publicable": False,
            "version_estandar": "apertura-estandar-r10-v2",
        },
    })
    apertura = resolver_apertura(fila)
    assert apertura["auto_color_conflicto"] is True
    assert apertura["auto_color_elegible"] is False


def test_un_video_defendible_tiene_prioridad_para_color_estimado():
    fila = _fila_color(5.8, True, score=0.91)
    apertura = resolver_apertura(fila)
    assert apertura["auto_color_elegible"] is True
    assert apertura["auto_color_soporte"] == 1
    assert apertura["auto_color_prioridad"] == "video_unico_defendible"
    assert "un_video_con_apertura_fisica_defendible_habilita_color_estimado" in apertura["motivos"]


def test_estimacion_de_llenado_visual_desde_onset_hasta_meseta():
    from utilidades.estandar_apertura import estimar_llenado_visual
    metricas = [
        _m(pix=1, comp=1, prox=True, deform=True),
        _m(pix=3, comp=3, prox=True, deform=True),
        _m(pix=7, comp=7, prox=True, deform=True),
        _m(pix=10, comp=10, prox=True, deform=True),
        _m(pix=10, comp=10, prox=True, deform=True),
        _m(pix=9, comp=9, prox=True, deform=True),
    ]
    r = estimar_llenado_visual(metricas, 0, 5000.0, fraccion_objetivo=0.90,
                               estabilidad_frames=3, tolerancia_rel=0.18)
    assert r["estado"] == "meseta_visual_estimada"
    assert r["frame_llenado"] == 3
    assert r["duracion_llenado_frames"] == 3
    assert r["duracion_llenado_ms"] == 0.6
    assert r["completo_en_clip"] is True


def test_llenado_visual_se_abstiene_si_no_hay_meseta():
    from utilidades.estandar_apertura import estimar_llenado_visual
    metricas = [
        _m(pix=1, comp=1), _m(pix=3, comp=3), _m(pix=7, comp=7),
        _m(pix=10, comp=10), _m(pix=4, comp=4), _m(pix=12, comp=12),
    ]
    r = estimar_llenado_visual(metricas, 0, 5000.0, fraccion_objetivo=0.90,
                               estabilidad_frames=3, tolerancia_rel=0.10)
    assert r["estado"] == "sin_meseta_visual_confirmada"
    assert r["duracion_llenado_ms"] is None


def test_resolvedor_agrega_duracion_llenado_de_un_video():
    fila = _fila_color(5.8, True)
    fila["videos"][0]["llenado_visual"] = {
        "estado": "meseta_visual_estimada",
        "frame_llenado": 35,
        "duracion_llenado_ms": 1.2,
    }
    apertura = resolver_apertura(fila)
    assert apertura["duracion_llenado_estimada_ms"] == 1.2
    assert apertura["llenado_visual_soporte"] == 1
    assert apertura["llenado_visual_conflicto"] is False
