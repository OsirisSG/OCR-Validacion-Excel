"""R15.1 · Fase 2 — Tmax censurado explícito (auditoría R15: ALTO-06 + MEDIO-09).

ALTO-06: secuencias planas ``[100,100,100,100,100]``, ``[100,99,100,100,100]``
y ``[100,100,99,100,99]`` con breakout en frame 0 producían
``maximo_inflado_estimado`` con duración 0 ms y CERO anomalías: certeza
inventada sobre un evento censurado por derecha (el crecimiento pudo empezar
antes de la grabación). Corrección exigida:

* ``frame_breakout == 0`` ⇒ anomalía ``evento_censurado_al_inicio``;
* máximo en el propio frame 0 (duración 0) ⇒ ``sin_maximo_defendible`` +
  ``sin_evidencia_previa_del_crecimiento``;
* sin evidencia previa limpia (área en frame 0 cercana al pico) ⇒ nunca
  ``maximo_inflado_estimado``; se degrada a
  ``maximo_visible_observado_no_confirmado``;
* el crecimiento plenamente observado desde frame 0 pequeño mantiene el
  estimado (guarda de sobre-corrección).

MEDIO-09: ``resultado_caso`` agregaba CUALQUIER ``frame_max_inflado`` con
tiempo > 0 a la mediana del caso sin exigir ``estado ==
maximo_inflado_estimado``. Corrección: la métrica confirmada del caso sólo
usa videos confirmados; los no confirmados se publican por separado con
etiqueta de estado explícita hasta Excel/UI.
"""
from __future__ import annotations

import pytest

from utilidades.estandar_apertura import analizar_secuencia_despliegue
from utilidades.resultado_caso import resolver_apertura


def _m(area: int) -> dict:
    return {"area_bolsa_visible_estimada_px": area}


def _secuencia(areas, inicio=0, fps=5000):
    return analizar_secuencia_despliegue([_m(a) for a in areas], inicio, fps)


# --------------------------------------------------------------------------
# ALTO-06 — reproducciones directas del auditor
# --------------------------------------------------------------------------

@pytest.mark.parametrize("areas", [
    [100, 100, 100, 100, 100],
    [100, 99, 100, 100, 100],
    [100, 100, 99, 100, 99],
])
def test_evento_plano_en_frame0_nunca_publica_estimado_con_duracion_cero(areas):
    r = _secuencia(areas)
    assert r["frame_breakout"] == 0
    assert "evento_censurado_al_inicio" in r["anomalías"]
    assert r["estado"] in {"sin_maximo_defendible",
                           "maximo_visible_observado_no_confirmado"}
    if r["frame_max_inflado"] == r["frame_breakout"]:
        # Duración 0 ms: ninguna evidencia de crecimiento observada.
        assert r["estado"] == "sin_maximo_defendible"
        assert "sin_evidencia_previa_del_crecimiento" in r["anomalías"]


def test_frame0_con_area_cercana_al_pico_se_degrada_a_no_confirmado():
    """Meseta confirmada, pero frame 0 ya ocupa el 60% del área pico: el
    crecimiento previo a la grabación no puede descartarse ⇒ NO confirmado."""
    r = _secuencia([60, 100, 100, 100, 100])
    assert r["frame_max_inflado"] > r["frame_breakout"]
    assert "evento_censurado_al_inicio" in r["anomalías"]
    assert r["estado"] == "maximo_visible_observado_no_confirmado"


def test_crecimiento_observado_desde_frame0_mantiene_estimado():
    """Guarda de sobre-corrección: área pequeña en breakout + caída clara."""
    r = _secuencia([10, 60, 100, 95, 40, 10], fps=1000)
    assert r["estado"] == "maximo_inflado_estimado"
    # Informativa: el evento toca el frame 0 aunque haya evidencia de crecimiento.
    assert "evento_censurado_al_inicio" in r["anomalías"]


def test_breakout_interior_no_anade_censura():
    r = _secuencia([0, 0, 0, 0, 0, 1, 8, 25, 60, 100, 99, 97, 85], inicio=5)
    assert "evento_censurado_al_inicio" not in r["anomalías"]
    assert r["estado"] == "maximo_inflado_estimado"


def test_video_airbag_expone_estado_del_maximo_por_video():
    """Cableado: el resultado por video publica el estado de la secuencia."""
    from pathlib import Path
    fuente = (Path(__file__).resolve().parents[1] / "video_airbag.py").read_text(
        encoding="utf-8")
    assert '"estado_max_inflado"' in fuente


# --------------------------------------------------------------------------
# MEDIO-09 — agregación por caso con estado explícito
# --------------------------------------------------------------------------

def _video(nombre, *, estado, tiempo, duracion=8.2, frame_max=70, frame_break=29):
    return {
        "id": nombre, "ruta": f"{nombre}.avi",
        "secuencia_despliegue_r13": {
            "estado": estado,
            "frame_breakout": frame_break, "frame_max_inflado": frame_max,
            "tiempo_max_inflado_ms": tiempo, "duracion_expansion_ms": duracion,
            "confianza_maximo": 0.9, "anomalías": [],
        },
    }


def _fila(videos):
    return {"id": "c1", "test_number": "1", "tipo_st": "1ST",
            "temperature_condition": "HT", "inflator_type": "UGL",
            "estado_proceso": "procesada", "videos": videos}


def test_caso_separa_confirmados_de_no_confirmados():
    apertura = resolver_apertura(_fila([
        _video("cam1", estado="maximo_inflado_estimado", tiempo=14.0),
        _video("cam2", estado="maximo_visible_observado_no_confirmado", tiempo=99.0),
    ]))
    assert apertura["tiempo_max_inflado_estimado_ms"] == 14.0
    assert apertura["tiempo_max_inflado_no_confirmado_ms"] == 99.0
    assert apertura["max_inflado_estado"] == "maximo_inflado_estimado"


def test_caso_sin_confirmados_no_publica_estimado():
    apertura = resolver_apertura(_fila([
        _video("cam1", estado="maximo_visible_observado_no_confirmado", tiempo=99.0),
    ]))
    assert apertura["tiempo_max_inflado_estimado_ms"] is None
    assert apertura["tiempo_max_inflado_no_confirmado_ms"] == 99.0
    assert apertura["max_inflado_estado"] == "maximo_visible_observado_no_confirmado"
    assert apertura["max_inflado_soporte"] == 0


def test_caso_con_censura_en_frame0_no_superficia_metrica():
    sec = analizar_secuencia_despliegue([_m(100)] * 5, 0, 5000)
    assert "evento_censurado_al_inicio" in sec["anomalías"]
    apertura = resolver_apertura(_fila([
        {"id": "cam1", "ruta": "cam1.avi", "secuencia_despliegue_r13": sec}]))
    assert apertura["tiempo_max_inflado_estimado_ms"] is None
    assert apertura["max_inflado_estado"] in {None, "sin_maximo_defendible"}


# --------------------------------------------------------------------------
# MEDIO-09 — Excel: estado explícito, columnas legacy intactas
# --------------------------------------------------------------------------

def test_excel_publica_estado_maximo_inflado(tmp_path):
    from pathlib import Path

    from openpyxl import load_workbook

    from configuracion import cargar_config, cargar_reglas
    from reporte_bmg import generar_reporte_bmg

    fila = {
        "project_id": "P", "case_key": "P|1ST|HT|UGL|42", "tipo_st": "1ST",
        "test_number": "42", "temperature_condition": "HT", "inflator_type": "UGL",
        "campos": {"test_number": {"valor": "42"}},
        "videos": [{
            "id": "cam1", "ruta": "cam1.avi",
            "secuencia_despliegue_r13": {
                "estado": "maximo_visible_observado_no_confirmado",
                "frame_breakout": 0, "frame_max_inflado": 9,
                "tiempo_breakout_ms": 0.0, "tiempo_max_inflado_ms": 99.0,
                "duracion_expansion_ms": 99.0, "confianza_maximo": 0.65,
                "anomalías": ["evento_censurado_al_inicio"],
            },
            "evidencia_apertura_r9": {"auto_colorable": True,
                                      "nivel_evidencia": "alta",
                                      "score_evidencia": .9},
            "tiempo_color_estimado_ms": 5.8, "referencia_color_valida": True,
        }],
    }
    plantilla = (Path(__file__).resolve().parents[1] / "plantillas"
                 / "reporte_bmg_1st_2st.xlsx")
    salida = tmp_path / "r15_2_estado_max.xlsx"
    generar_reporte_bmg(plantilla, salida, [fila], cargar_config(), cargar_reglas(),
                        idioma="es")
    ws = load_workbook(salida)["Apertura V15.10"]
    headers = [c.value for c in ws[1]]
    # Contrato R13 intacto: mismas columnas legacy en las mismas posiciones.
    assert headers[:19][-1] == "Ir al detalle"
    assert headers[19:23] == [
        "Máximo inflado estimado ms", "Duración breakout→máximo ms",
        "Soporte máximo", "Anomalías máximo",
    ]
    # Video NO confirmado ⇒ la métrica "estimado ms" queda vacía y el estado
    # explícito se publica al final.
    assert ws.cell(2, 20).value is None
    assert "Estado máximo inflado" in headers
    idx_estado = headers.index("Estado máximo inflado") + 1
    assert "NO CONFIRMADO" in str(ws.cell(2, idx_estado).value)
    idx_nc = headers.index("Máximo visible NO CONFIRMADO ms") + 1
    assert ws.cell(2, idx_nc).value == 99.0
    idx_anom = headers.index("Anomalías máximo") + 1
    assert "evento_censurado_al_inicio" in str(ws.cell(2, idx_anom).value)
