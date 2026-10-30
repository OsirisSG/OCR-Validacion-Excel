"""V15.9 · Fase 5: consenso de 3 de 4 cámaras (o del pool disponible).

Salida doble (primer instante confiable por cámara + resultado consolidado),
estados confirmado/propuesto/discordancia/sin_evento/sin_datos y nunca
reemplazo de una confirmación humana.
"""
import video_airbag as va


def _item(nombre, tiempo, *, estado="candidato", revision=None, inicio=False,
          advertencia=None):
    it = {
        "nombre": nombre, "estado": estado, "tiempo_ms": tiempo,
        "tiempo_fps_ms": tiempo, "resolucion_nativa_ms": 0.1,
        "precision_fuente_ms": 0.1, "fuente_tiempo": "fps_subframe",
    }
    if revision:
        it["revision_manual"] = revision
    if inicio:
        it["estado"] = "evento_al_inicio"
        it["evento_al_inicio"] = True
        it["tiempo_ms"] = None
        it["tiempo_ms_sospechoso"] = tiempo
    if advertencia:
        it["advertencia_fps"] = advertencia
    return it


CAM = {"a": "09_DETAIL.AVI", "b": "09_FRONTAL.AVI", "c": "09_LATERAL.AVI",
       "d": "09_INNEN.AVI", "s": "09_SCHEIBE.AVI", "r": "05_DETAIL.AVI"}


def test_tres_de_cuatro_coinciden_confirma():
    items = [_item(CAM["a"], 5000.0), _item(CAM["b"], 5000.05),
             _item(CAM["c"], 5000.1), _item(CAM["d"], None, estado="no_event")]
    res = va.consenso_videos(items, {})
    assert res["soporte"] == 3 and res["soporte_requerido"] == 3
    assert res["estado"] == "primera_aparicion"
    assert res["estado_consenso"] == "confirmado"
    assert res["requiere_revision"] is False
    assert res["apertura_revelada"] is True
    assert res["tiempo_ms"] == 5000.0
    # Salida 1: primer instante confiable por cámara.
    por_camara = {p["video"]: p for p in res["primer_instante_por_camara"]}
    assert len(por_camara) == 4
    assert por_camara[CAM["a"]]["tiempo_ms"] == 5000.0
    assert por_camara[CAM["a"]]["en_consenso"] is True
    assert por_camara[CAM["a"]]["estado"] == "confirmado"
    assert por_camara[CAM["d"]]["en_consenso"] is False
    assert por_camara[CAM["d"]]["estado"] == "sin_evento"
    assert por_camara[CAM["d"]]["tiempo_ms"] is None
    # Salida 2: resultado consolidado del caso (clave = cámara, no el archivo).
    assert res["valores_por_camara"]["DETAIL"] == 5000.0


def test_dos_de_cuatro_queda_discordancia_y_pide_revision():
    items = [_item(CAM["a"], 5000.0), _item(CAM["b"], 5000.1),
             _item(CAM["c"], 8000.0), _item(CAM["d"], 8000.05)]
    res = va.consenso_videos(items, {})
    assert res["soporte_requerido"] == 3
    assert res["estado"] == "sin_consenso"
    assert res["estado_consenso"] == "discordancia"
    assert res["requiere_revision"] is True
    assert res["apertura_revelada"] is True
    assert res["tiempo_propuesto_ms"] == 5000.0
    assert any("no coinciden" in m for m in res["motivo_revision"])


def test_unico_cluster_sin_soporte_queda_propuesto():
    items = [_item(CAM["a"], 5000.0), _item(CAM["b"], None, estado="no_event"),
             _item(CAM["c"], None, estado="no_event"), _item(CAM["d"], None, estado="no_event")]
    res = va.consenso_videos(items, {})
    assert res["soporte_requerido"] == 3
    assert res["estado_consenso"] == "propuesto"
    assert res["requiere_revision"] is True
    assert res["tiempo_propuesto_ms"] == 5000.0
    assert res["apertura_revelada"] is True


def test_camaras_adicionales_raras_no_destruyen_el_consenso():
    items = [_item(CAM["a"], 5000.0), _item(CAM["b"], 5000.05), _item(CAM["c"], 5000.1),
             _item(CAM["s"], 2.0), _item(CAM["r"], 20000.0)]
    res = va.consenso_videos(items, {})
    assert res["soporte_requerido"] == 3
    assert res["soporte"] == 3
    assert res["estado"] == "primera_aparicion"
    assert res["estado_consenso"] == "confirmado"
    assert res["requiere_revision"] is False
    assert "SCHEIBE" in res["camaras_excluidas"]


def test_camara_ausente_no_cambia_el_minimo_de_tres():
    items = [_item(CAM["a"], 5000.0), _item(CAM["b"], 5000.05), _item(CAM["c"], 5000.1)]
    res = va.consenso_videos(items, {})
    assert res["soporte_requerido"] == 2  # sólo 3 comparables disponibles
    assert res["estado_consenso"] == "confirmado"  # 3 coinciden
    assert res["requiere_revision"] is False
    assert len(res["primer_instante_por_camara"]) == 3


def test_confirmacion_humana_conserva_la_decision():
    items = [_item(CAM["a"], 5000.0,
                   revision={"estado": "confirmado", "frame_index": 25, "tiempo_ms": 5000.0}),
             _item(CAM["b"], 8000.0), _item(CAM["c"], 8000.05), _item(CAM["d"], 8000.1)]
    res = va.consenso_videos(items, {})
    assert res["estado"] == "confirmado_manual"
    assert res["tiempo_ms"] == 5000.0
    assert res["requiere_revision"] is False
    assert res["estado_consenso"] == "confirmado"
    assert res["apertura_revelada"] is True
    assert any(p["estado"] == "confirmado_manual"
               for p in res["primer_instante_por_camara"])


def test_estados_sin_evento_sin_datos_y_evento_al_inicio():
    items = [_item(CAM["a"], None, estado="no_event"), _item(CAM["b"], None, estado="no_event"),
             _item(CAM["c"], None, estado="no_event"), _item(CAM["d"], None, estado="no_event")]
    res = va.consenso_videos(items, {})
    assert res["estado_consenso"] == "sin_evento"
    assert res["apertura_revelada"] is False
    assert res["tiempo_ms"] is None
    assert all(p["estado"] == "sin_evento" for p in res["primer_instante_por_camara"])
    # Sin ningún item: sin_datos.
    res2 = va.consenso_videos([], {})
    assert res2["estado_consenso"] == "sin_datos"
    # Evento al inicio: cada cámara conserva su estado y no se inventa tiempo.
    items3 = [_item(CAM["a"], 5000.0, inicio=True), _item(CAM["b"], 5000.0, inicio=True),
              _item(CAM["c"], 5000.0, inicio=True)]
    res3 = va.consenso_videos(items3, {})
    assert res3["tiempo_ms"] is None
    assert res3["apertura_revelada"] is False
    assert all(p["estado"] == "evento_al_inicio"
               for p in res3["primer_instante_por_camara"])
    assert all(p["tiempo_ms_sospechoso"] == 5000.0
               for p in res3["primer_instante_por_camara"])


def test_incidencias_de_video_se_reportan():
    items = [_item(CAM["a"], 5000.0, advertencia="Se usaron 12 fps declarados."),
             _item(CAM["b"], 5000.05), _item(CAM["c"], 5000.1)]
    res = va.consenso_videos(items, {})
    assert res["estado_consenso"] == "confirmado"
    assert any("12 fps declarados" in i["detalle"] for i in res["incidencias"])
    assert res["incidencias"][0]["video"] == CAM["a"]


def test_deteccion_anterior_sin_respaldo_sigue_pidiendo_revision():
    items = [_item(CAM["a"], 100.0), _item(CAM["b"], 5000.0),
             _item(CAM["c"], 5000.05), _item(CAM["d"], 5000.1)]
    res = va.consenso_videos(items, {})
    assert res["camara_anterior_sin_respaldo"]["video"] == CAM["a"]
    assert res["requiere_revision"] is True
    assert res["tiempo_ms"] == 5000.0
    assert any("sin respaldo" in m for m in res["motivo_revision"])
