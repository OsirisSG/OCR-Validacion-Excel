"""Cómo llega el tiempo de apertura de video a la casilla opening_time_ms.

Sustituye a la prueba de ``_aplicar_campo_apertura_video`` (API V15.0 que ya no
existe); ahora el backend usa ``_aplicar_consenso_video_a_fila``.
"""
from dashboard.backend.app import _aplicar_consenso_video_a_fila


def _fila(campo=None, correcciones=None):
    campo = campo or {"valor": None, "requiere_revision": True}
    return {
        "campos": {"opening_time_ms": dict(campo)},
        "consolidado": {"campos": {"opening_time_ms": dict(campo)}, "campos_faltantes": ["opening_time_ms"]},
        "campos_faltantes": ["opening_time_ms"],
        "correcciones_manual_campos": correcciones or {},
    }


def test_consenso_valido_rellena_la_casilla():
    fila = _fila()
    _aplicar_consenso_video_a_fila(fila, {"estado": "primera_aparicion", "tiempo_ms": 1.6, "soporte": 2})
    dato = fila["campos"]["opening_time_ms"]
    assert dato["valor"] == "1.6"
    assert dato["estado"] == "extraido_video"
    assert "opening_time_ms" not in fila["campos_faltantes"]


def test_sin_consenso_borra_solo_un_valor_que_venia_de_video():
    fila = _fila({"valor": "2.0", "fuente": "video_airbag_consenso"})
    _aplicar_consenso_video_a_fila(fila, {"estado": "sin_consenso", "tiempo_ms": 2.0, "soporte": 1})
    assert fila["campos"]["opening_time_ms"]["valor"] is None
    assert "opening_time_ms" in fila["campos_faltantes"]


def test_correccion_manual_del_campo_prevalece():
    fila = _fila({"valor": "5.7", "fuente": "correccion_manual_confirmada"},
                 {"opening_time_ms": {"valor": "5.7"}})
    _aplicar_consenso_video_a_fila(fila, {"estado": "primera_aparicion", "tiempo_ms": 1.6, "soporte": 2})
    assert fila["campos"]["opening_time_ms"]["valor"] == "5.7"
