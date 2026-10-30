"""R15.2 · ALTO-03: invariante física global de Tmax.

Reproducción del auditor independiente (AUDITORIA_INDEPENDIENTE_R15_1): con
una señal PLANA posterior al breakout y ``frame_breakout != 0``, la meseta se
detecta en el índice 0 del tramo ⇒ ``frame_max == frame_breakout`` ⇒
``duracion_expansion_ms == 0`` y, sin embargo, el estado publicado era
``maximo_inflado_estimado`` (¡confirmado con 0 ms de expansión!). Las reglas
R15.1 sólo censuraban el frame 0 del clip; el mismo defecto aparecía con
breakout en 1, 5, 20…

Invariante exigida (criterio de aceptación 7 de R15.2):

    estado == "maximo_inflado_estimado"  ⇒  frame_max_inflado > frame_breakout
                                            ∧ duracion_expansion_ms > 0

Si no hay evidencia de expansión posterior al breakout, NUNCA se confirma:
señal plana ⇒ ``sin_maximo_defendible`` con anomalías
``maximo_coincide_con_breakout`` + ``sin_evidencia_de_expansion``; expansión
en frames observada pero sin fps (duración no cuantificable) ⇒ degradado a
``maximo_visible_observado_no_confirmado``.
"""
from __future__ import annotations

import random

import pytest

from utilidades.estandar_apertura import analizar_secuencia_despliegue


def _m(area: float) -> dict:
    return {"area_bolsa_visible_estimada_px": area}


def _invariante_global(r: dict) -> None:
    if r["estado"] == "maximo_inflado_estimado":
        assert r["frame_max_inflado"] is not None
        assert r["frame_max_inflado"] > r["frame_breakout"], (
            f"estimado con máximo en el propio breakout: {r['frame_breakout']}")
        assert r["duracion_expansion_ms"] is not None
        assert r["duracion_expansion_ms"] > 0.0, (
            "estimado con duración de expansión 0 ms")


@pytest.mark.parametrize("inicio", [1, 5, 20])
def test_senal_plana_con_breakout_intermedio_no_confirma_cero_ms(inicio):
    """Caso del auditor: 100 frames planos, breakout en 1/5/20 ⇒ 0 ms."""
    r = analizar_secuencia_despliegue([_m(500)] * 100, inicio, 1000.0)
    _invariante_global(r)
    assert r["frame_breakout"] == inicio
    assert r["estado"] == "sin_maximo_defendible", (
        "una señal plana no aporta evidencia de expansión: no hay máximo")
    assert "maximo_coincide_con_breakout" in r["anomalías"]
    assert "sin_evidencia_de_expansion" in r["anomalías"]


def test_casi_plana_con_ruido_de_un_pixel_no_confirma_cero_ms():
    r = analizar_secuencia_despliegue(
        [_m(500 + (i % 2)) for i in range(100)], 7, 500.0)
    _invariante_global(r)
    if r["frame_max_inflado"] == r["frame_breakout"]:
        assert r["estado"] == "sin_maximo_defendible"
        assert "maximo_coincide_con_breakout" in r["anomalías"]
        assert "sin_evidencia_de_expansion" in r["anomalías"]


def test_breakout_cerca_del_final_plano_no_confirma():
    r = analizar_secuencia_despliegue([_m(800)] * 100, 95, 250.0)
    _invariante_global(r)
    assert r["estado"] in {"sin_maximo_defendible",
                           "maximo_visible_observado_no_confirmado"}
    if r["frame_max_inflado"] == r["frame_breakout"]:
        assert r["estado"] == "sin_maximo_defendible"
        assert "sin_evidencia_de_expansion" in r["anomalías"]


def test_expansion_real_post_breakout_se_mantiene_confirmada():
    """No regresión: crecimiento genuino tras breakout ⇒ confirmado >0 ms."""
    areas = ([10] * 5                                     # pre-breakout plegado
             + [20, 60, 150, 400, 700, 900, 950, 960, 960, 960]  # expansión
             + [955, 950, 940, 500, 300])                 # meseta + caída
    r = analizar_secuencia_despliegue([_m(a) for a in areas], 5, 1000.0)
    _invariante_global(r)
    assert r["estado"] == "maximo_inflado_estimado"
    assert r["frame_max_inflado"] > r["frame_breakout"]
    assert r["duracion_expansion_ms"] > 0.0


def test_expansion_real_sin_fps_no_puede_confirmar_milisegundos():
    """Sin fps la duración no es cuantificable ⇒ no hay estimado confirmado."""
    areas = ([10] * 5 + [20, 60, 150, 400, 700, 900, 950, 960, 960, 960]
             + [955, 950, 940, 500, 300])
    r = analizar_secuencia_despliegue([_m(a) for a in areas], 5, None)
    _invariante_global(r)
    assert r["duracion_expansion_ms"] is None
    assert r["estado"] == "maximo_visible_observado_no_confirmado", (
        "sin fps no se puede afirmar una duración > 0 ms")
    assert "sin_evidencia_de_expansion" in r["anomalías"]


def test_invariante_global_fuzz():
    """Ninguna combinación aleatoria publica estimado con 0 ms de expansión."""
    rnd = random.Random(152)
    for _ in range(300):
        n = rnd.randint(4, 120)
        base = rnd.choice([0, 5, 200, 500])
        areas = []
        for _ in range(n):
            areas.append(max(0.0, base + rnd.choice(
                [0, 0, 0, 1, -1, 50, 300, -200]) + rnd.random() * 5))
        inicio = rnd.randrange(0, n)
        fps = rnd.choice([None, 30.0, 240.0, 5000.0])
        r = analizar_secuencia_despliegue([_m(a) for a in areas], inicio, fps)
        _invariante_global(r)
        fases = {f["estado"]: f["frame"] for f in r.get("fases", [])}
        if fases:
            assert fases["breakout"] <= fases["expansion"] <= fases["maximo_inflado"]
