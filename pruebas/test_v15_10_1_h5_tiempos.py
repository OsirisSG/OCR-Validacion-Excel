"""Regresiones H5 — temporalidad física: lo inválido SOLO queda en auditoría.

Copiado del contrato H5 aportado por el responsable. Los valores finales
inválidos nunca se publican ni aparecen como propuestas normales.
"""
from utilidades.resultado_caso import resolver_apertura, resolver_resultado_caso


def test_tiempo_manual_negativo_no_se_publica_ni_propone():
    resultado = resolver_apertura({
        "campos": {"opening_time_ms": {
            "valor": -122.8, "raw_time_ms": -122.8,
            "estado": "confirmado_manual", "fuente": "revision_manual",
            "confirmacion_manual": True,
        }}
    })
    assert resultado["tiempo_ms"] is None
    assert resultado["tiempo_propuesto_ms"] is None
    assert resultado["revisiones_temporales_invalidas"]
    assert resultado["revisiones_temporales_invalidas"][0]["raw_time_ms"] == -122.8
    canonico = resolver_resultado_caso({"campos": {"opening_time_ms": {
        "valor": -122.8, "raw_time_ms": -122.8, "estado": "confirmado_manual",
        "fuente": "revision_manual", "confirmacion_manual": True,
    }}})
    assert canonico["campos"]["opening_time_ms"]["valor"] is None
    assert canonico["campos"]["opening_time_ms"]["raw_time_ms"] == -122.8
    assert canonico["apertura"]["tiempo_propuesto_ms"] is None


def test_candidato_video_negativo_no_se_propone():
    resultado = resolver_apertura({
        "video_apertura": {"estado": "propuesto", "tiempo_propuesto_ms": -0.2}
    })
    assert resultado["tiempo_ms"] is None
    assert resultado["tiempo_propuesto_ms"] is None


def test_conflicto_con_valor_negativo_solo_aparece_en_crudo():
    resultado = resolver_apertura({
        "campos": {"opening_time_ms": {
            "valor": -2.2, "estado": "conflicto", "fuente": "revision_manual"
        }}
    })
    assert resultado["tiempo_ms"] is None
    assert resultado["tiempo_propuesto_ms"] is None
    assert resultado["revisiones_temporales_invalidas"]


def test_tiempo_manual_positivo_valido_se_conserva():
    resultado = resolver_apertura({
        "videos": [{"id": "camara1", "revision_manual": {
            "estado": "confirmado", "frame_index": 11, "tiempo_ms": 2.2,
            "referencia_tiempo_valida": True, "estado_tiempo": "VALIDO",
        }}]
    })
    assert resultado["estado"] == "VERIFICADO_HUMANO"
    assert resultado["tiempo_ms"] == 2.2


def test_evento_al_inicio_con_tiempo_positivo_se_conserva_solo_como_censurado():
    resultado = resolver_apertura({"video_apertura": {
        "estado": "evento_al_inicio", "tiempo_ms": 2.2,
        "raw_time_ms": 2.2, "referencia_tiempo_valida": True,
        "estado_tiempo": "VALIDO",
    }})
    assert resultado["tiempo_ms"] is None
    assert resultado["tiempo_propuesto_ms"] is None
    assert resultado["estado_tiempo"] == "CENSURADO"
    assert resultado["tiempo_crudo_ms"] == 2.2
    assert resultado["revisiones_temporales_invalidas"][0]["estado_tiempo"] == "CENSURADO"


def test_revision_manual_en_clip_censurado_no_confirma_apertura():
    resultado = resolver_apertura({"videos": [{
        "id": "camara1", "estado": "evento_al_inicio", "evento_al_inicio": True,
        "tiempo_ms_sospechoso": 2.2,
        "revision_manual": {"estado": "confirmado", "frame_index": 11,
                            "tiempo_ms": 2.2, "raw_time_ms": 2.2,
                            "referencia_tiempo_valida": True, "estado_tiempo": "VALIDO"},
    }]})
    assert resultado["tiempo_ms"] is None
    assert resultado["tiempo_propuesto_ms"] is None
    assert resultado["estado_tiempo"] == "CENSURADO"
    assert any(x["fuente"] == "revision_manual_video"
               and x["estado_tiempo"] == "CENSURADO"
               for x in resultado["revisiones_temporales_invalidas"])
