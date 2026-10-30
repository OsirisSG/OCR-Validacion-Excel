"""R15.3 · F3 — Invariante de magnitud/persistencia de expansión para Tmax (ALTO-04).

Auditoría independiente R15.2: la invariante temporal de R15.2
(``frame_max > frame_breakout ∧ dur > 0``) es necesaria pero NO suficiente.
Reproducción del auditor: área de 10000 px en breakout y 10001 px después
(+1 px = 0.01 %) con breakout en frames 1, 5 y 20 ⇒
``maximo_inflado_estimado``, ``frame_max = breakout + 1``, duración 1.0 ms,
``confianza_maximo = 1.0``, sin anomalías. Una fluctuación de segmentación
puede convertirse en «expansión real» y alimentar el semáforo.

Corrección exigida (P1): evidencia de crecimiento relevante — diferencia
absoluta + diferencia relativa respecto al área de breakout + persistencia
durante varios frames (la meseta/caída ya la exigía R15). Anomalía nueva:
``expansion_post_breakout_insuficiente`` (el auditor sugiere
EXPANSION_POST_BREAKOUT_INSUFICIENTE; el código usa snake_case como el resto
de anomalías). P2: confianza coherente con el estado final (señal plana o
expansión insuficiente no pueden llevar confianza 1.0).

Umbrales: piso relativo 2 % del área de breakout (escala con resolución/ROI),
piso absoluto 25 px (ruido de segmentación en áreas pequeñas) y persistencia
mínima 3 frames. Son puertas CONSERVADORAS documentadas, no una calibración
de campo: la calibración fina con videos reales sigue pendiente (R16/campo).
"""
from __future__ import annotations

import random

import pytest

from utilidades import estandar_apertura
from utilidades.estandar_apertura import analizar_secuencia_despliegue

RELATIVA = 0.02
ABSOLUTA = 25.0
PERSISTENCIA = 3
ANOMALIA = "expansion_post_breakout_insuficiente"
CAP_NO_CONFIRMADO = 0.35


def _secuencia(areas: list[float]) -> list[dict]:
    return [{"area_bolsa_visible_estimada_px": float(a)} for a in areas]


def _analizar(areas, inicio, fps=1000.0):
    return analizar_secuencia_despliegue(_secuencia(areas), inicio, fps)


# ---------------------------------------------------------------------------
# Reproducción exacta del auditor: +1 px no es expansión real
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("inicio", [1, 5, 20])
def test_un_pixel_no_es_expansion_real(inicio):
    # Área EN breakout = 10000 px; posterior = 10001 px (reproducción exacta
    # del auditor: el tramo analizado empieza en el frame de breakout).
    areas = [9000.0] * inicio + [10000.0] + [10001.0] * (99 - inicio)
    r = _analizar(areas, inicio)
    assert r["estado"] != "maximo_inflado_estimado", (
        f"ALTO-04: +1 px (0.01 %) confirmó máximo inflado con breakout={inicio}: "
        f"estado={r['estado']} confianza={r['confianza_maximo']}")
    assert ANOMALIA in r["anomalías"]
    assert r["confianza_maximo"] < 1.0, (
        "P2: la confianza debe ser coherente con el estado no confirmado")
    # Sin crecimiento defendible no hay máximo que defender.
    assert r["estado"] == "sin_maximo_defendible"


def test_crecimiento_relativo_insuficiente():
    """+0.5 % sostenido: pasa el piso absoluto (50 px > 25) pero no el
    relativo (2 % de 10000 = 200 px) ⇒ no confirmado."""
    inicio = 5
    areas = [9000.0] * inicio + [10000.0] + [10050.0] * 39
    r = _analizar(areas, inicio)
    assert r["estado"] != "maximo_inflado_estimado"
    assert ANOMALIA in r["anomalías"]
    assert r["confianza_maximo"] < 1.0


def test_piso_absoluto_en_areas_pequenas():
    """Área pequeña: +10 % relativo pero sólo 10 px (< piso absoluto 25 px)
    ⇒ ruido de segmentación, no confirmado."""
    inicio = 4
    areas = [90.0] * inicio + [100.0] + [110.0] * 39
    r = _analizar(areas, inicio)
    assert r["estado"] != "maximo_inflado_estimado"
    assert ANOMALIA in r["anomalías"]


def test_expansion_breve_sin_persistencia():
    """Magnitud suficiente (+5000 px) pero transitoria: un solo frame y
    vuelve a la base (glitch de segmentación). La mediana causal lo ensancha
    a 2-3 muestras pero no alcanza la persistencia mínima ⇒ observado NO
    confirmado (hay algo visible, no es defendible como máximo inflado)."""
    inicio = 5
    # Área base EN breakout (10000), glitch de un frame (15000) y vuelta.
    areas = [9000.0] * inicio + [10000.0, 15000.0] + [10000.0] * 39
    r = _analizar(areas, inicio)
    assert r["estado"] == "maximo_visible_observado_no_confirmado", r["estado"]
    assert ANOMALIA in r["anomalías"]
    assert r["confianza_maximo"] < 1.0


# ---------------------------------------------------------------------------
# No regresión: la expansión real sigue confirmada
# ---------------------------------------------------------------------------


def test_expansion_real_sigue_confirmada():
    """Crecimiento grande y sostenido con meseta: confirmado, sin la anomalía
    nueva y con duración > 0 (mismo contrato que R15.2)."""
    inicio = 5
    areas = ([300.0] * inicio
             + [2000.0, 9000.0, 20000.0, 35000.0, 45000.0, 50000.0]
             + [50000.0] * 10 + [48000.0] * 6)
    r = _analizar(areas, inicio)
    assert r["estado"] == "maximo_inflado_estimado", (
        f"la expansión real ya no se confirma: {r['estado']} {r['anomalías']}")
    assert ANOMALIA not in r["anomalías"]
    assert r["frame_max_inflado"] > inicio
    assert r["duracion_expansion_ms"] > 0.0
    assert r["confianza_maximo"] == 1.0


# ---------------------------------------------------------------------------
# P2 — confianza coherente con el estado final
# ---------------------------------------------------------------------------


def test_confianza_coherente_senal_plana():
    """R15.2 ya devolvía sin_maximo_defendible en señal plana, pero con
    confianza 1.0 (inconsistencia señalada por el auditor)."""
    r = _analizar([500.0] * 100, 5)
    assert r["estado"] == "sin_maximo_defendible"
    assert r["confianza_maximo"] <= CAP_NO_CONFIRMADO, (
        "P2: estado no confirmado con confianza alta")


def test_confianza_limitada_en_todos_los_no_confirmados():
    casos = {
        "plana": ([500.0] * 100, 5),
        "un_pixel": ([10000.0] * 5 + [10001.0] * 50, 5),
        "transitoria": ([9000.0] * 5 + [10000.0, 15000.0] + [10000.0] * 39, 5),
    }
    for nombre, (areas, inicio) in casos.items():
        r = _analizar(areas, inicio)
        assert r["estado"] != "maximo_inflado_estimado", nombre
        assert r["confianza_maximo"] <= CAP_NO_CONFIRMADO, (
            f"{nombre}: confianza {r['confianza_maximo']} incoherente con "
            f"estado {r['estado']}")


# ---------------------------------------------------------------------------
# Contrato de umbrales + fuzz con la invariante global
# ---------------------------------------------------------------------------


def test_umbrales_documentados():
    """Los umbrales son explícitos, documentados y parametrizables (no un
    porcentaje arbitrario único: piso relativo + piso absoluto + persistencia,
    como pide el auditor)."""
    assert estandar_apertura.EXPANSION_MINIMA_RELATIVA == RELATIVA
    assert estandar_apertura.EXPANSION_MINIMA_ABSOLUTA_PX == ABSOLUTA
    assert estandar_apertura.PERSISTENCIA_EXPANSION_FRAMES == PERSISTENCIA
    assert estandar_apertura.CONFIANZA_MAX_NO_CONFIRMADO == CAP_NO_CONFIRMADO
    # Parametrizables por llamada (calibración futura sin tocar el código).
    inicio = 5
    areas = [9000.0] * inicio + [10000.0] + [10050.0] * 39
    r = analizar_secuencia_despliegue(
        _secuencia(areas), inicio, 1000.0,
        expansion_minima_relativa=0.001, expansion_minima_absoluta_px=1.0,
        persistencia_expansion_frames=2)
    assert r["estado"] == "maximo_inflado_estimado", (
        "con umbrales relajados explícitos el crecimiento sí se confirma")


def test_fuzz_invariante_magnitud_global():
    """300 señales aleatorias: NINGÚN confirmado sin crecimiento significativo
    medible en la propia señal (máximo del tramo - área de breakout)."""
    rng = random.Random(1533)
    confirmados = 0
    for _ in range(300):
        n = rng.randint(12, 120)
        inicio = rng.randint(0, max(0, n - 8))
        if inicio >= n:
            continue
        base = rng.choice([50.0, 400.0, 5000.0, 10000.0, 40000.0])
        estilo = rng.choice(["plana", "ruido", "crece", "glitch", "crece_poco"])
        areas = []
        for i in range(n):
            if i < inicio:
                areas.append(base * rng.uniform(0.2, 0.9))
            elif estilo == "plana":
                areas.append(base + rng.uniform(-1, 1))
            elif estilo == "ruido":
                areas.append(base + rng.uniform(-base * 0.01, base * 0.015))
            elif estilo == "crece":
                areas.append(base + (i - inicio + 1) * base * rng.uniform(0.2, 0.6))
            elif estilo == "crece_poco":
                areas.append(base * rng.uniform(1.0, 1.015))
            else:  # glitch
                areas.append(base * 3 if inicio <= i < inicio + 2 else base)
        fps = rng.choice([25.0, 240.0, 1000.0, None])
        r = analizar_secuencia_despliegue(_secuencia(areas), inicio, fps)
        if r["estado"] != "maximo_inflado_estimado":
            continue
        confirmados += 1
        tramo = areas[inicio:inicio + 240]
        crecimiento_bruto = max(tramo) - areas[inicio]
        umbral = max(ABSOLUTA, RELATIVA * max(areas[inicio], 1.0))
        assert r["frame_max_inflado"] > inicio
        assert r["duracion_expansion_ms"] is None or r["duracion_expansion_ms"] > 0.0
        assert crecimiento_bruto >= umbral, (
            f"confirmado sin crecimiento significativo: base={areas[inicio]} "
            f"max={max(tramo)} umbral={umbral}")
    assert confirmados > 0, "el fuzz no ejercitó ningún caso confirmado"
