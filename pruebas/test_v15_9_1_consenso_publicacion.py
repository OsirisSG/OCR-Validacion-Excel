"""V15.9.1 · B1+B2: nunca se publica como confirmado lo propuesto.

Reproduce los bloqueantes de la auditoría estricta:

- B1: dos candidatos coincidentes y un tercero sin evento (3 cámaras
  comparables) daban ``estado_consenso='propuesto'`` pero
  ``consenso_valido`` devolvía ``True`` y el dashboard publicaba el tiempo.
- B2: tres cámaras coincidentes con una marcada por causa grave perdían la
  señal ``requiere_revision`` al consolidar.

Incluye además la compatibilidad con consensos históricos (JSON anteriores a
V15.9 sin ``estado_consenso``) y la cadena completa hasta la fila del
dashboard y la celda de la matriz.
"""
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import video_airbag as va


def _item(nombre, tiempo, *, estado="candidato", revision=None, **extra):
    it = {
        "nombre": nombre, "estado": estado, "tiempo_ms": tiempo,
        "tiempo_fps_ms": tiempo, "resolucion_nativa_ms": 0.1,
        "precision_fuente_ms": 0.1, "fuente_tiempo": "fps_subframe",
    }
    if revision:
        it["revision_manual"] = revision
    it.update(extra)
    return it


CAM_A = "09_DETAIL.AVI"
CAM_B = "09_FRONTAL.AVI"
CAM_C = "09_LATERAL.AVI"
CAM_D = "09_INNEN.AVI"


# ---------------------------------------------------------------- B1


def test_b1_propuesta_no_confirmada_nunca_es_valida():
    """Auditoría B1: 3 cámaras comparables, 2 coinciden, 1 sin evento."""
    items = [_item(CAM_A, 5000.0), _item(CAM_B, 5000.05),
             _item(CAM_C, None, estado="no_event")]
    res = va.consenso_videos(items, {})
    assert res["estado"] == "primera_aparicion"
    assert res["estado_consenso"] == "propuesto"
    assert res["requiere_revision"] is True
    assert res["soporte"] == 2
    # El núcleo del fallo: antes devolvía True y publicaba el tiempo.
    assert va.consenso_valido(res) is False
    assert va.evidencia_apertura_desde_consenso({"case_key": "x"}, res) is None


def test_b1_con_cuatro_camaras_el_mantenimiento_sigue_intacto():
    items = [_item(CAM_A, 5000.0), _item(CAM_B, 5000.05),
             _item(CAM_C, 8000.0), _item(CAM_D, None, estado="no_event")]
    res = va.consenso_videos(items, {})
    assert res["estado_consenso"] == "discordancia"
    assert va.consenso_valido(res) is False


def test_b1_tres_coincidentes_limpio_si_publica():
    items = [_item(CAM_A, 5000.0), _item(CAM_B, 5000.05),
             _item(CAM_C, 5000.1), _item(CAM_D, None, estado="no_event")]
    res = va.consenso_videos(items, {})
    assert res["estado_consenso"] == "confirmado"
    assert res["requiere_revision"] is False
    assert va.consenso_valido(res) is True


def test_b1_precedencia_manual_siempre_manda():
    items = [_item(CAM_A, 5000.0,
                   revision={"estado": "confirmado", "frame_index": 25,
                             "tiempo_ms": 5000.0}),
             _item(CAM_B, 8000.0), _item(CAM_C, None, estado="no_event")]
    res = va.consenso_videos(items, {})
    assert res["estado"] == "confirmado_manual"
    assert va.consenso_valido(res) is True


# ---------------------------------------------------------------- B2


def test_b2_causa_grave_no_se_borra_al_confirmar():
    """Auditoría B2: 3 coincidentes, una con FPS no corroborados."""
    items = [_item(CAM_A, 5000.0, advertencia_fps="Se usaron 12 fps declarados."),
             _item(CAM_B, 5000.05), _item(CAM_C, 5000.1),
             _item(CAM_D, None, estado="no_event")]
    res = va.consenso_videos(items, {})
    assert res["estado_consenso"] == "confirmado"
    # Antes: requiere_revision=False aunque motivo_revision lo mencionaba.
    assert res["requiere_revision"] is True
    assert va.consenso_valido(res) is False
    assert any("FPS no corroborados" in m for m in res["motivo_revision"])
    # El motivo identifica a la cámara responsable.
    assert any("DETAIL" in m and "FPS no corroborados" in m
               for m in res["motivo_revision"])
    assert "FPS no corroborados" in res["causas_revision_consolidado"]
    por_camara = {p["video"]: p for p in res["primer_instante_por_camara"]}
    assert "FPS no corroborados" in por_camara[CAM_A]["causas_revision"]
    assert por_camara[CAM_B]["causas_revision"] == []


def test_b2_overlay_dudoso_bloquea_publicacion():
    # Reloj leído que contradice la tasa del ensayo (validado=False con valor).
    items = [_item(CAM_A, 5000.0, overlay_validado=False, tiempo_overlay_ms=4800.0),
             _item(CAM_B, 5000.05), _item(CAM_C, 5000.1)]
    res = va.consenso_videos(items, {})
    assert res["estado_consenso"] == "confirmado"
    assert res["requiere_revision"] is True
    assert va.consenso_valido(res) is False
    assert "overlay dudoso" in res["causas_revision_consolidado"]


def test_b2_error_de_lectura_del_reloj_bloquea_publicacion():
    items = [_item(CAM_A, 5000.0, overlay_error="frame_no_leido"),
             _item(CAM_B, 5000.05), _item(CAM_C, 5000.1)]
    res = va.consenso_videos(items, {})
    assert res["estado_consenso"] == "confirmado"
    assert res["requiere_revision"] is True
    assert va.consenso_valido(res) is False
    assert "overlay dudoso" in res["causas_revision_consolidado"]


def test_b2_ausencia_de_reloj_no_bloquea_por_si_sola():
    # Sin reloj legible y sin otra advertencia, el consenso limpio confirma.
    items = [_item(CAM_A, 5000.0, overlay_validado=False),
             _item(CAM_B, 5000.05), _item(CAM_C, 5000.1)]
    res = va.consenso_videos(items, {})
    assert res["estado_consenso"] == "confirmado"
    assert res["requiere_revision"] is False
    assert va.consenso_valido(res) is True


def test_b2_roi_incierta_autoalineada_bloquea_publicacion():
    zona = {"activa": True, "bloqueada": False, "bbox_norm": [0.1, 0.1, 0.5, 0.5],
            "fuente": "similitud_visual"}
    items = [_item(CAM_A, 5000.0, zona_deteccion=zona),
             _item(CAM_B, 5000.05), _item(CAM_C, 5000.1)]
    res = va.consenso_videos(items, {})
    assert res["estado_consenso"] == "confirmado"
    assert res["requiere_revision"] is True
    assert va.consenso_valido(res) is False
    assert any("ROI incierta" in c for c in res["causas_revision_consolidado"])


def test_b2_roi_confirmada_no_bloquea():
    zona = {"activa": True, "bloqueada": True, "bbox_norm": [0.1, 0.1, 0.5, 0.5],
            "fuente": "manual_bloqueada"}
    items = [_item(CAM_A, 5000.0, zona_deteccion=zona),
             _item(CAM_B, 5000.05), _item(CAM_C, 5000.1)]
    res = va.consenso_videos(items, {})
    assert res["estado_consenso"] == "confirmado"
    assert res["requiere_revision"] is False
    assert va.consenso_valido(res) is True


def test_b2_revision_manual_limpia_las_causas_de_esa_camara():
    items = [_item(CAM_A, 5000.0, advertencia_fps="12 fps declarados",
                   revision={"estado": "confirmado", "frame_index": 25,
                             "tiempo_ms": 5000.0}),
             _item(CAM_B, 5000.05), _item(CAM_C, 5000.1)]
    res = va.consenso_videos(items, {})
    assert res["estado"] == "confirmado_manual"
    assert res["requiere_revision"] is False
    assert va.consenso_valido(res) is True


# ------------------------------------------- compatibilidad histórica


def test_compatibilidad_consenso_historico_v1581():
    # JSON persistido por V15.8.1: no traía estado_consenso.
    legado_ok = {"estado": "primera_aparicion", "tiempo_ms": 5.0,
                 "soporte": 3, "total_principales": 4, "requiere_revision": False}
    assert va.consenso_valido(legado_ok) is True
    # V15.9.4 (ALTA-N4): política única de publicación automática — 2 de 2 NO
    # basta; ningún legado automático con menos de 3 cámaras se publica
    # (queda como propuesta pendiente; sólo la confirmación humana excepciona).
    assert va.consenso_valido({"estado": "primera_aparicion", "tiempo_ms": 5.0,
                               "soporte": 2, "total_principales": 2,
                               "requiere_revision": False}) is False
    # V15.9.3 (CRIT-01): metadatos INCOMPLETOS (sin total_principales) fallan
    # cerrado aunque el soporte parezca suficiente: no demuestran el respaldo.
    legado_incompleto = {"estado": "primera_aparicion", "tiempo_ms": 5.0,
                         "soporte": 3, "requiere_revision": False}
    assert va.consenso_valido(legado_incompleto) is False
    legado_pendiente = dict(legado_ok, requiere_revision=True)
    assert va.consenso_valido(legado_pendiente) is False
    legado_sin_consenso = {"estado": "sin_consenso", "tiempo_ms": 5.0,
                           "requiere_revision": True}
    assert va.consenso_valido(legado_sin_consenso) is False
    legado_manual = {"estado": "confirmado_manual", "tiempo_ms": 5.0}
    assert va.consenso_valido(legado_manual) is True
    assert va.consenso_valido(None) is False
    assert va.consenso_valido({"estado": "confirmado", "tiempo_ms": None}) is False
    assert va.consenso_valido({"estado": "confirmado", "tiempo_ms": math.nan}) is False


def test_compatibilidad_con_datos_de_cache_antiguos():
    """Los items de caché viejos no traen zona_deteccion ni advertencias."""
    items = [{"nombre": CAM_A, "estado": "candidato", "tiempo_ms": 5000.0,
              "resolucion_nativa_ms": 0.1, "fuente_tiempo": "fps_subframe"},
             {"nombre": CAM_B, "estado": "candidato", "tiempo_ms": 5000.05,
              "resolucion_nativa_ms": 0.1, "fuente_tiempo": "fps_subframe"},
             {"nombre": CAM_C, "estado": "candidato", "tiempo_ms": 5000.1,
              "resolucion_nativa_ms": 0.1, "fuente_tiempo": "fps_subframe"}]
    res = va.consenso_videos(items, {})
    assert res["estado_consenso"] == "confirmado"
    assert va.consenso_valido(res) is True


# ----------------------------- end-to-end hacia la fila y la matriz


def _app_backend():
    import importlib
    return importlib.import_module("dashboard.backend.app")


def test_e2e_propuesto_no_rellena_opening_time_ms(tmp_path, monkeypatch):
    backend = _app_backend()
    fila = {"campos": {}, "videos": []}
    items = [_item(CAM_A, 5000.0), _item(CAM_B, 5000.05),
             _item(CAM_C, None, estado="no_event")]
    consenso = va.consenso_videos(items, {})
    backend._aplicar_consenso_video_a_fila(fila, consenso)
    dato = fila["campos"].get("opening_time_ms") or {}
    # El tiempo propuesto queda PENDIENTE, nunca publicado como extraído.
    assert dato.get("estado") == "pendiente_revision"
    assert dato.get("requiere_revision") is True
    estado, valor, motivo, pendiente = backend._estado_apertura_detalle(fila)
    assert estado == "gris" and valor is None and motivo == "pendiente_revision"
    # La medida sin confirmar sobrevive sólo para el tooltip.
    assert pendiente == 5000.0


def test_e2e_confirmado_si_rellena_y_colorea(tmp_path):
    backend = _app_backend()
    fila = {"campos": {}, "videos": []}
    items = [_item(CAM_A, 5000.0), _item(CAM_B, 5000.05), _item(CAM_C, 5000.1)]
    consenso = va.consenso_videos(items, {})
    backend._aplicar_consenso_video_a_fila(fila, consenso)
    dato = fila["campos"].get("opening_time_ms") or {}
    assert dato.get("estado") == "extraido_video"
    assert float(dato["valor"]) == 5000.0
    estado, valor, _motivo, _pend = backend._estado_apertura_detalle(fila)
    assert estado in {"verde", "amarillo", "rojo"} and valor == 5000.0


def test_e2e_causa_grave_deja_el_tiempo_pendiente_en_la_fila():
    backend = _app_backend()
    fila = {"campos": {}, "videos": []}
    items = [_item(CAM_A, 5000.0, advertencia_fps="12 fps declarados"),
             _item(CAM_B, 5000.05), _item(CAM_C, 5000.1)]
    consenso = va.consenso_videos(items, {})
    backend._aplicar_consenso_video_a_fila(fila, consenso)
    dato = fila["campos"].get("opening_time_ms") or {}
    assert dato.get("estado") == "pendiente_revision"
    assert va.consenso_valido(consenso) is False
    estado, valor, _motivo, pendiente = backend._estado_apertura_detalle(fila)
    assert estado == "gris" and valor is None and pendiente == 5000.0


def test_e2e_sin_evento_previo_de_video_marca_faltante():
    backend = _app_backend()
    fila = {"campos": {"opening_time_ms": {"valor": "5.0", "estado": "extraido_video",
                                           "fuente": "video_airbag_consenso"}},
            "videos": []}
    items = [_item(CAM_A, None, estado="no_event"), _item(CAM_B, None, estado="no_event"),
             _item(CAM_C, None, estado="no_event")]
    consenso = va.consenso_videos(items, {})
    backend._aplicar_consenso_video_a_fila(fila, consenso)
    dato = fila["campos"].get("opening_time_ms") or {}
    assert dato.get("estado") == "faltante_requerido"
    assert "opening_time_ms" in fila["campos_faltantes"]
