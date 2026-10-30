from __future__ import annotations

from copy import deepcopy

from flujo_empresarial import consolidar_caso
from utilidades.matriz_apertura import celda_caso, criterio_desde_limites
from utilidades.resultado_caso import resolver_resultado_caso
from video_airbag import evidencia_apertura_desde_consenso


def _caso():
    return {
        "project_id": "ejemplo_vw",
        "case_key": "ejemplo_vw|1ST|HT|NOM|232550",
        "ruta": "/tmp/232550",
        "ruta_relativa": "232550",
        "nombre": "232550",
        "tipo_st": "1ST",
        "metadata_ruta": {"test_number": "232550", "temperature_condition": "HT",
                          "inflator_type": "NOM"},
    }


def _consenso_manual(tiempo=2.2):
    return {
        "estado": "confirmado_manual",
        "tiempo_ms": tiempo,
        "tiempo_crudo_ms": tiempo,
        "estado_tiempo": "VALIDO",
        "referencia_tiempo_valida": True,
        "estado_consenso": "confirmado",
        "soporte": 3,
        "total_validos": 4,
        "videos_coincidentes": ["DETAIL.AVI", "FRONTAL.AVI", "LATERAL.AVI"],
        "algoritmo_consenso": "consenso-v2-soporte-3-de-4",
        "requiere_revision": False,
    }


def test_evidencia_video_conserva_referencia_temporal_al_consolidar():
    caso = _caso()
    evidencia = evidencia_apertura_desde_consenso(caso, _consenso_manual())
    assert evidencia is not None
    assert evidencia["referencia_tiempo_valida"] is True
    assert evidencia["estado_tiempo"] == "VALIDO"
    consolidado = consolidar_caso(
        caso, [evidencia], requeridos=set(), claves=("opening_time_ms",))
    campo = consolidado["campos"]["opening_time_ms"]
    assert campo["valor"] == "2.2"
    assert campo["referencia_tiempo_valida"] is True
    assert campo["estado_tiempo"] == "VALIDO"
    assert campo["soporte"] == 3


def test_consenso_manual_valido_no_se_degrada_por_raw_legacy_inferior():
    fila = {
        **_caso(),
        "video_apertura": _consenso_manual(),
        "videos": [],
        "campos": {
            # Simula exactamente la contaminación observada en la corrida R6:
            # el raw del campo quedó sin metadata aunque el consenso de video sí era válido.
            "opening_time_ms": {
                "valor": "2.2", "raw_time_ms": "2.2", "estado": "extraido_video",
                "fuente_preferida": "video",
            }
        },
    }
    apertura = resolver_resultado_caso(fila)["apertura"]
    assert apertura["estado"] == "VERIFICADO_HUMANO"
    assert apertura["tiempo_ms"] == 2.2
    assert apertura["referencia_tiempo_valida"] is True


def test_matriz_recalcula_snapshot_canonico_obsoleto_si_hay_video_apertura():
    fila = {
        **_caso(),
        "id": "c1",
        "video_apertura": _consenso_manual(5.8),
        "resultado_caso_canonico": {
            "apertura": {
                "estado": "PROPUESTA", "tiempo_ms": None,
                "tiempo_propuesto_ms": None, "estado_tiempo": "REFERENCIA_INVALIDA",
                "referencia_tiempo_valida": False,
            }
        },
    }
    celda = celda_caso(fila, criterio_desde_limites(6, 7))
    assert celda["estado"] == "verde"
    assert celda["opening_time_ms"] == 5.8
    assert celda["decision_apertura"] == "VERIFICADO_HUMANO"


def test_propuesta_dos_de_cuatro_permanece_gris():
    fila = {
        **_caso(), "id": "c2",
        "video_apertura": {
            "estado": "primera_aparicion", "tiempo_ms": 1.8,
            "estado_tiempo": "VALIDO", "referencia_tiempo_valida": True,
            "estado_consenso": "propuesto", "soporte": 2, "total_validos": 4,
            "requiere_revision": True,
        },
    }
    celda = celda_caso(fila, criterio_desde_limites(6, 7))
    assert celda["estado"] == "gris"
    assert celda["opening_time_ms"] is None
    assert celda["tiempo_pendiente_ms"] == 1.8


def test_matriz_no_recalcula_fila_publica_con_video_apertura_null():
    from dashboard.backend.app import _fila_publica
    fila = {
        **_caso(),
        "id": "pub1",
        "campos": {"opening_time_ms": {
            "valor": 6.0, "estado": "confirmado_manual", "fuente_preferida": "manual",
            "confirmacion_manual": True, "referencia_tiempo_valida": True,
            "estado_tiempo": "VALIDO"}},
    }
    publica = _fila_publica(fila)
    assert publica["video_apertura"] is None
    celda = celda_caso(publica, criterio_desde_limites(6, 7))
    assert celda["estado"] == "verde"
    assert celda["opening_time_ms"] == 6.0
    assert celda["decision_apertura"] == "VERIFICADO_HUMANO"
