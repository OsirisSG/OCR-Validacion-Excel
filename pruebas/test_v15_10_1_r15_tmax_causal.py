"""R15 · Tmax temporalmente coherente (auditoría R14: ALTA-05 + MEDIA-16).

Pruebas obligatorias 11 y 12:

11. Secuencia ``[1,100,100,100]`` ⇒ Tmax posterior a breakout o estado no
    confirmado; NUNCA fases fuera de orden ni ``t_max < t_breakout``.
12. Máximo al final de clip creciente ⇒ no publicarlo como máximo confirmado.

La mediana móvil de R14 usaba ``bruto[i-1:i+2]``: con dos muestras elegía el
MAYOR, así que el frame 0 heredaba el área del frame futuro y el «máximo»
podía caer en el propio breakout (duración 0 ms, expansión DESPUÉS del
máximo). La corrección usa un filtro causal (ventana actual + dos pasadas)
e invariantes de orden; además distingue el estado publicado:

* ``maximo_inflado_estimado`` — meseta o caída confirmada (evidencia plena);
* ``maximo_visible_observado_no_confirmado`` — clip termina creciendo / sin
  estabilidad confirmada;
* ``sin_maximo_defendible`` — señal insuficiente.
"""
from __future__ import annotations

from utilidades.estandar_apertura import analizar_secuencia_despliegue


def _m(area: int) -> dict:
    return {"area_bolsa_visible_estimada_px": area}


def _secuencia(areas, inicio=0, fps=5000):
    return analizar_secuencia_despliegue([_m(a) for a in areas], inicio, fps)


def _assert_fases_en_orden(r):
    fases = {f["estado"]: f["frame"] for f in r["fases"]}
    assert fases["breakout"] <= fases["expansion"] <= fases["maximo_inflado"], (
        f"fases fuera de orden: {r['fases']}")
    if r["tiempo_max_inflado_ms"] is not None and r["tiempo_breakout_ms"] is not None:
        assert r["tiempo_max_inflado_ms"] >= r["tiempo_breakout_ms"], (
            "t_max < t_breakout está prohibido")


def test_salto_inmediato_no_coloca_maximo_en_breakout():
    """Caso reproducido por el auditor: [1,100,100,100,100] ⇒ max=breakout, 0 ms."""
    r = _secuencia([1, 100, 100, 100, 100])
    assert r["frame_breakout"] == 0
    assert r["frame_max_inflado"] is not None
    # El área cruda en breakout (1) está muy por debajo del pico (100) y hay
    # crecimiento posterior defendible ⇒ el máximo NO puede estar en breakout.
    assert r["frame_max_inflado"] > r["frame_breakout"]
    assert r["duracion_expansion_ms"] > 0.0
    _assert_fases_en_orden(r)


def test_variante_1_99_100_mantiene_orden_de_fases():
    """Segundo caso del auditor: [1,99,100,100,100] ⇒ pico=2 pero max=0."""
    r = _secuencia([1, 99, 100, 100, 100])
    assert r["frame_max_inflado"] >= r["frame_breakout"]
    assert r["frame_max_inflado"] > r["frame_breakout"]
    _assert_fases_en_orden(r)


def test_crecimiento_monotono_suave_sin_maximo_en_breakout():
    r = _secuencia([5, 10, 20, 40, 80, 97, 98, 99])
    assert r["frame_max_inflado"] > r["frame_breakout"]
    _assert_fases_en_orden(r)


def test_clip_creciente_hasta_el_final_no_es_maximo_confirmado():
    """Prueba obligatoria 12: pico pegado al borde final ⇒ NO confirmado."""
    r = _secuencia([2, 5, 15, 30, 60])
    assert "maximo_en_borde_final_del_clip" in r["anomalías"]
    assert r["estado"] == "maximo_visible_observado_no_confirmado"
    assert r["confianza_maximo"] < 1.0
    # El valor observado se publica, pero sin certeza inventada.
    assert r["frame_max_inflado"] is not None
    _assert_fases_en_orden(r)


def test_senal_insuficiente_es_sin_maximo_defendible():
    r = _secuencia([5, 50])
    assert "ventana_post_breakout_corta" in r["anomalías"]
    assert r["estado"] == "sin_maximo_defendible"


def test_meseta_confirmada_sigue_publicando_maximo_estimado():
    """Control R13: meseta defendible ⇒ maximo_inflado_estimado (regresión)."""
    r = _secuencia([0, 0, 0, 0, 0, 1, 8, 25, 60, 100, 99, 97, 85], inicio=5)
    assert r["estado"] == "maximo_inflado_estimado"
    assert r["frame_max_inflado"] in {9, 10}
    assert r["duracion_expansion_ms"] in {0.8, 1.0}
    _assert_fases_en_orden(r)


def test_caida_clara_tras_pico_es_maximo_estimado():
    """Control: caída posterior clara (sin meseta) también confirma el máximo."""
    r = _secuencia([10, 60, 100, 95, 40, 10], fps=1000)
    assert r["estado"] == "maximo_inflado_estimado"
    _assert_fases_en_orden(r)
