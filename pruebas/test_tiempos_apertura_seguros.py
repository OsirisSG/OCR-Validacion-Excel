"""Reglas de signo: relojes/offsets conservan su valor; apertura final exige >0."""
from __future__ import annotations

import pytest

import video_airbag as va
from utilidades.resultado_caso import resolver_apertura


def test_reloj_overlay_negativo_se_conserva_pero_no_es_apertura_final():
    resuelto = va.resolver_tiempo_metadata(
        frame_index=0, fps=None, timestamp_actual_ms=-12.5, config={})
    assert resuelto["tiempo_ms"] == -12.5
    assert resuelto["tiempo_overlay_leido_ms"] == -12.5
    assert resuelto["overlay_valido"] is True
    item = {"estado": "candidato", "tiempo_ms": resuelto["tiempo_ms"],
            "fuente_tiempo": resuelto["fuente_tiempo"]}
    assert va.tiempo_efectivo_video(item) == (None, "tiempo_apertura_no_positivo", False)


def test_offset_negativo_y_referencia_de_reloj_admiten_signo():
    resuelto = va.resolver_tiempo_metadata(
        frame_index=10, fps=5000, timestamp_inicial_ms=-20.0,
        timestamp_actual_ms=-18.0, config={})
    assert resuelto["tiempo_overlay_leido_ms"] == -18.0
    assert resuelto["tiempo_ms"] == -18.0
    assert resuelto["overlay_valido"] is True
    control = va.validar_fps_con_reloj(
        5000, frame_index=100, reloj_frame_ms=10.0, reloj_inicial_ms=-10.0)
    assert control["fps_reloj"] == 5000.0


def test_tiempo_final_manual_requiere_positivo_y_referencia_valida():
    negativo = {"revision_manual": {"estado": "confirmado", "frame_index": 10,
                                     "tiempo_ms": -1.0, "raw_time_ms": -1.0,
                                     "referencia_tiempo_valida": True,
                                     "estado_tiempo": "NO_POSITIVO"}}
    cero = {"revision_manual": {"estado": "confirmado", "frame_index": 10,
                                 "tiempo_ms": 0.0, "referencia_tiempo_valida": True,
                                 "estado_tiempo": "VALIDO"}}
    sin_referencia = {"revision_manual": {"estado": "confirmado", "frame_index": 10,
                                          "tiempo_ms": 1.0}}
    valido = {"revision_manual": {"estado": "confirmado", "frame_index": 10,
                                   "tiempo_ms": 1.0, "referencia_tiempo_valida": True,
                                   "estado_tiempo": "VALIDO"}}
    assert va.tiempo_efectivo_video(negativo)[0] is None
    assert va.tiempo_efectivo_video(cero)[0] is None
    assert va.tiempo_efectivo_video(sin_referencia)[0] is None
    assert va.tiempo_efectivo_video(valido) == (1.0, "revision_manual", True)


def test_caso_preserva_revision_negativa_solo_en_auditoria():
    fila = {"videos": [{"id": "video-1", "revision_manual": {
        "estado": "confirmado", "frame_index": 10, "tiempo_ms": -2.5,
        "raw_time_ms": -2.5, "estado_tiempo": "NO_POSITIVO",
        "referencia_tiempo_valida": False,
        "motivo_rechazo": "No se corrige automáticamente.",
    }}]}
    apertura = resolver_apertura(fila)
    assert apertura["estado"] == "PROPUESTA"
    assert apertura["tiempo_ms"] is None
    assert apertura["tiempo_propuesto_ms"] is None
    assert apertura["tiempo_crudo_ms"] == -2.5
    assert apertura["revisiones_temporales_invalidas"][0]["raw_time_ms"] == -2.5


def test_consenso_no_publica_apertura_cero_ni_negativa():
    assert va.consenso_valido({"estado": "confirmado_manual", "tiempo_ms": 0.0,
                               "referencia_tiempo_valida": True}) is False
    assert va.consenso_valido({"estado": "confirmado_manual", "tiempo_ms": -0.5,
                               "referencia_tiempo_valida": True}) is False
    assert va.consenso_valido({"estado": "confirmado_manual", "tiempo_ms": 0.5,
                               "referencia_tiempo_valida": False}) is False
    censurado = {"estado": "evento_al_inicio", "evento_al_inicio": True,
                 "tiempo_ms": 0.5, "referencia_tiempo_valida": True,
                 "revision_manual": {"estado": "confirmado", "frame_index": 1,
                                     "tiempo_ms": 0.5, "referencia_tiempo_valida": True}}
    assert va.tiempo_efectivo_video(censurado)[0] is None
    assert va.tiempo_efectivo_video(censurado)[1] == "evento_censurado_al_inicio"


def test_campo_apertura_manual_rechaza_valores_no_positivos_o_no_finitos():
    from dashboard.backend.app import _aplicar_campo_manual_en_fila

    for valor in ("0", "-1", "nan", "inf", "1001"):
        fila = {"campos": {"opening_time_ms": {"valor": None}}}
        with pytest.raises(ValueError, match="finito, > 0"):
            _aplicar_campo_manual_en_fila(fila, "opening_time_ms", valor, "revisor")
    fila = {"campos": {"opening_time_ms": {"valor": None}}}
    salida = _aplicar_campo_manual_en_fila(fila, "opening_time_ms", "0.25", "revisor")
    assert salida["valor"] == "0.25"
    assert salida["estado"] == "pendiente_revision"
    assert salida["raw_time_ms"] == "0.25"
    assert salida["referencia_tiempo_valida"] is False
    evidencia_validada = {"referencia_tiempo_valida": True, "frame_index": 12}
    validada = _aplicar_campo_manual_en_fila(
        {"campos": {"opening_time_ms": {"valor": None}}}, "opening_time_ms",
        "0.25", "revisor", evidencia=evidencia_validada)
    assert validada["estado"] == "confirmado_manual"
    assert validada["referencia_tiempo_valida"] is True


def test_api_sanea_tiempo_positivo_de_evento_censurado():
    from dashboard.backend.app import (_campo_apertura_publico, _video_apertura_publica,
                                       _video_item_publico)
    from utilidades.resultado_caso import resolver_resultado_caso

    salida = _video_apertura_publica({
        "estado": "evento_al_inicio", "tiempo_ms": 2.0,
        "referencia_tiempo_valida": True, "estado_tiempo": "VALIDO",
    })
    assert salida["tiempo_ms"] is None
    assert salida["estado_tiempo"] == "CENSURADO"
    assert salida["raw_time_ms"] == 2.0
    assert "censurado" in salida["motivo_rechazo"]

    fila = {"campos": {"opening_time_ms": {
        "valor": -2.0, "raw_time_ms": -2.0, "estado": "confirmado_manual",
        "referencia_tiempo_valida": False,
    }}}
    canonico = resolver_resultado_caso(fila)
    campo = _campo_apertura_publico(fila["campos"]["opening_time_ms"], canonico)
    assert campo["valor"] is None and campo["tiempo_ms"] is None
    assert campo["tiempo_propuesto_ms"] is None
    assert campo["raw_time_ms"] == -2.0

    item = _video_item_publico({
        "estado": "evento_al_inicio", "evento_al_inicio": True,
        "tiempo_ms": 2.0, "referencia_tiempo_valida": True,
        "revision_manual": {"estado": "confirmado", "frame_index": 2,
                            "tiempo_ms": 2.0, "raw_time_ms": 2.0,
                            "referencia_tiempo_valida": True},
    })
    assert item["tiempo_ms"] is None
    assert item["revision_manual"]["tiempo_ms"] is None
    assert item["revision_manual"]["raw_time_ms"] == 2.0
    assert item["revision_manual"]["estado_tiempo"] == "CENSURADO"


def test_detalle_api_sanea_resumen_campos_y_revision_video(tmp_path, monkeypatch):
    import dashboard.backend.app as backend

    class GestorFalso:
        def __init__(self, *_args, **_kwargs):
            pass

        def estado_revision(self, _tipo, _item_id, estado):
            return {"estado": estado}

        def listar_anotaciones(self, *_args, **_kwargs):
            return []

        def listar_correcciones_texto(self, *_args, **_kwargs):
            return []

        def listar_rotaciones(self, *_args, **_kwargs):
            return {}

    revision = {"estado": "confirmado", "frame_index": 2, "tiempo_ms": 2.0,
                "raw_time_ms": 2.0, "referencia_tiempo_valida": True}
    video = {"id": "v1", "nombre": "clip.avi", "ruta": str(tmp_path / "clip.avi"),
             "estado": "evento_al_inicio", "evento_al_inicio": True,
             "tiempo_ms": 2.0, "referencia_tiempo_valida": True,
             "revision_manual": revision, "frame_evento": 2}
    fila = {
        "id": "caso-1", "nombre": "caso-1", "ruta": str(tmp_path / "caso-1"),
        "comparacion": {"resultado": "sin_procesar"}, "alertas": [], "imagenes": [],
        "campos": {"opening_time_ms": {
            "valor": -122.8, "raw_time_ms": -122.8, "estado": "confirmado_manual",
            "referencia_tiempo_valida": False,
        }},
        "video_apertura": {"estado": "evento_al_inicio", "evento_al_inicio": True,
                            "tiempo_ms": 2.0, "referencia_tiempo_valida": True},
        "videos": [video],
    }
    monkeypatch.setattr(backend, "_cargar_datos", lambda: {"resultados": [fila]})
    monkeypatch.setattr(backend, "_id_fila", lambda _fila: "caso-1")
    monkeypatch.setattr(backend, "_normalizar_tiempos_video_fila", lambda _fila: False)
    monkeypatch.setattr(backend, "_fila_publica", lambda _fila: {
        "semaforo": "gris", "revision": {"estado": "por_revisar"}})
    monkeypatch.setattr(backend, "_lote_de", lambda _fila: "lote-test")
    monkeypatch.setattr(backend, "_resolver_raiz_datos", lambda _datos: None)
    monkeypatch.setattr(backend, "_alertas_pendientes", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(backend, "GestorAprendizaje", GestorFalso)

    detalle = backend.detalle("caso-1")
    assert detalle["campos"]["opening_time_ms"]["valor"] is None
    assert detalle["campos"]["opening_time_ms"]["raw_time_ms"] == -122.8
    assert detalle["campos"]["opening_time_ms"]["referencia_tiempo_valida"] is False
    assert detalle["video_apertura"]["tiempo_ms"] is None
    assert detalle["video_apertura"]["raw_time_ms"] == 2.0
    salida_video = detalle["videos"][0]
    assert salida_video["tiempo_ms"] is None
    assert salida_video["revision_manual"]["tiempo_ms"] is None
    assert salida_video["revision_manual"]["raw_time_ms"] == 2.0
    assert salida_video["revision_manual"]["estado_tiempo"] == "CENSURADO"


def test_guardado_no_acepta_final_cero_y_preserva_historia(tmp_path, monkeypatch):
    video = tmp_path / "video.avi"
    video.write_bytes(b"video de prueba")
    monkeypatch.setattr(va, "RUTA_REVISIONES", tmp_path / "revisiones.json")
    with pytest.raises(ValueError, match="finito y > 0"):
        va.guardar_revision_video(
            video, case_key="caso", frame_index=10, tiempo_ms=0.0,
            referencia_tiempo_valida=True)
    with pytest.raises(ValueError, match="censurado"):
        va.guardar_revision_video(
            video, case_key="caso", frame_index=10, tiempo_ms=2.0,
            referencia_tiempo_valida=True, evento_censurado=True)
    primera = va.guardar_revision_video(
        video, case_key="caso", frame_index=10, tiempo_ms=2.0,
        referencia_tiempo_valida=True, fuente_tiempo="fps_grabacion_validado")
    segunda = va.guardar_revision_video(
        video, case_key="caso", frame_index=12, tiempo_ms=2.4,
        referencia_tiempo_valida=True, fuente_tiempo="fps_grabacion_validado")
    assert segunda["raw_time_ms"] == 2.4
    assert segunda["tiempo_ms"] == 2.4
    assert len(segunda["historial"]) == 1
    assert segunda["historial"][0]["raw_time_ms"] == primera["raw_time_ms"] == 2.0
