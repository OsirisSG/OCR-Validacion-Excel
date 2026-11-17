"""P53 · Robustez de las decisiones: dígito de control en la serie IMPRESA del tablero, freno de
coherencia de fechas, protocolos aislados y lectura exacta de la serie del módulo. Valores
sintéticos (2031); el dígito de control es la regla del estándar Code 39."""
from __future__ import annotations

import decisiones_lote as DL
import tablero_integracion as TI
from test_p43_integracion_tablero import PISTA, _caso, _consolidar, _fotos, _procesar, _ruta


def _con_control(cuerpo: str) -> str:
    return cuerpo + TI.control_code39(cuerpo)


SERIE = _con_control("052 3KVJ0000R7")
MALA = SERIE[:-1] + ("A" if SERIE[-1] != "A" else "B")           # mismo cuerpo, último carácter mal
OTRA = "052 3KVJ0000X7" + ("A" if TI.control_code39("052 3KVJ0000X7") != "A" else "B")  # otro cuerpo, sin control


def _impreso(valor):
    return {"dashboard_serial_number": {"valor": valor, "confianza": .8, "origen": "texto impreso"}}


def _correr(lecturas: dict, politica="completa"):
    caso = _caso()
    fotos = _fotos(caso, list(lecturas))
    guion = {_ruta(caso, r): {"pista": PISTA, "campos": campos} for r, campos in lecturas.items()}
    resultado, _ = _procesar(caso, fotos, guion, segunda_pasada=False, serie_control=politica)
    return caso, resultado, resultado["campos"]["dashboard_serial_number"]


# --- serie impresa del tablero ------------------------------------------------------------------
def test_impreso_con_control_y_cuerpo_en_dos_fotos_se_publica():
    """Antes: una foto dice …X y otra …Y → duda. Ahora el dígito de control elige la buena."""
    caso, resultado, estado = _correr({"NACH/01.JPG": _impreso(SERIE), "NACH/02.JPG": _impreso(MALA)})
    assert estado["estado"] == "consenso" and estado["regla"] == "impreso_control_mod43"
    assert estado["valor"] == TI.sin_simbolo_final(SERIE)
    consolidado = _consolidar(caso, resultado)
    assert consolidado["campos"]["dashboard_serial_number"]["valor"] == TI.sin_simbolo_final(SERIE)


def test_impreso_con_control_politica_sin_control():
    _, _, estado = _correr({"NACH/01.JPG": _impreso(SERIE), "NACH/02.JPG": _impreso(SERIE)}, "sin_control")
    assert estado["estado"] == "consenso" and estado["valor"] == SERIE[:-1].rstrip()


def test_impreso_con_control_en_una_sola_foto_no_se_publica_pero_se_recomienda():
    _, _, estado = _correr({"NACH/01.JPG": _impreso(SERIE)})
    assert estado["estado"] == "en_duda" and estado["valor"] is None
    assert estado["valor_propuesto"] == TI.sin_simbolo_final(SERIE)
    assert estado["verificada_control"]["impreso"] == SERIE


def test_impreso_con_otro_cuerpo_en_otra_foto_queda_en_duda():
    _, _, estado = _correr({"NACH/01.JPG": _impreso(SERIE), "NACH/02.JPG": _impreso(SERIE),
                            "NACH/03.JPG": _impreso(OTRA)})
    assert estado["estado"] == "en_duda" and "otro cuerpo" in estado["motivo"]


def test_impreso_sin_ninguna_serie_valida_sigue_la_regla_anterior():
    _, _, estado = _correr({"NACH/01.JPG": _impreso(MALA)})
    assert estado["estado"] != "consenso" and "verificada_control" not in estado


def test_impreso_valido_con_datamatrix_que_no_cumple_no_decide():
    dm = {"dashboard_serial_number": {"valor": MALA, "confianza": .9, "origen": "datamatrix"}}
    _, _, estado = _correr({"NACH/01.JPG": _impreso(SERIE), "NACH/02.JPG": _impreso(SERIE), "NACH/03.JPG": dm})
    assert estado.get("regla") != "impreso_control_mod43"


def test_politica_preguntar_no_publica_el_impreso():
    _, _, estado = _correr({"NACH/01.JPG": _impreso(SERIE), "NACH/02.JPG": _impreso(SERIE)}, "preguntar")
    # dos fotos impresas iguales ya eran consenso antes de P53; con «preguntar» se ofrece la elección
    assert estado["estado"] == "en_duda" and SERIE[:-1].rstrip() in estado["variantes"]


def test_formulario_ofrece_la_serie_impresa_verificada():
    from utilidades.dudas_y_opciones import construir_dudas
    lecturas = {"232564": {"verificadas": {"dashboard_serial_number": {
        "impreso": SERIE, "completa": TI.sin_simbolo_final(SERIE), "sin_control": SERIE[:-1]}}}}
    opciones = construir_dudas({"232564": {}}, lecturas, campos=("dashboard_serial_number",))[0]["opciones"]
    assert opciones[0]["fuente"] == "serie_verificada" and "impresa" in opciones[0]["respaldo"]


# --- decisiones de lote -------------------------------------------------------------------------
def _fila(numero, campos=None, textos=(), candidatos=()):
    return {"test_number": numero, "case_key": f"P|1ST|{numero}",
            "campos": {k: (v if isinstance(v, dict) else {"valor": v}) for k, v in (campos or {}).items()},
            "candidatos": list(candidatos), "etiqueta_modulo": {"lecturas": []},
            "trazabilidad": [{"ruta_relativa": f"F{i}.JPG", "texto_crudo": t} for i, t in enumerate(textos)]}


def _lote_con_fecha(fecha_modulo, fecha_prueba_del_vacio):
    filas = [_fila(str(i), {"module_date": fecha_modulo, "test_date": "2031-06-05"}) for i in range(6)]
    vacio = _fila("99", {"test_date": fecha_prueba_del_vacio}, textos=["Airbag Module 2GJ 880 204 J"])
    return filas + [vacio], vacio


def test_freno_de_coherencia_no_publica_una_fecha_de_pieza_posterior_a_la_prueba():
    filas, vacio = _lote_con_fecha("2031-04-10", "2031-03-01")
    salida = DL.aplicar(filas)
    assert DL._valor(vacio, "module_date") in (None, "")
    assert salida["rechazadas"] and salida["rechazadas"][0]["campo"] == "module_date"
    assert "posterior" in vacio["campos"]["module_date"]["decision_lote_rechazada"]["motivo"]


def test_freno_de_coherencia_deja_pasar_la_fecha_coherente():
    filas, vacio = _lote_con_fecha("2031-04-10", "2031-06-05")
    salida = DL.aplicar(filas)
    assert DL._valor(vacio, "module_date") == "2031-04-10" and not salida["rechazadas"]
    assert salida["por_regla"] == {"unanime_lote_modulo": 1}


def test_sin_fecha_de_prueba_el_freno_no_bloquea():
    assert DL.incoherencia(_fila("1"), "module_date", "2031-04-10") is None
    assert DL.incoherencia(_fila("1", {"test_date": "ilegible"}), "module_date", "2031-04-10") is None
    assert DL.incoherencia(_fila("1", {"test_date": "2031-01-01"}), "engineering_level", "01S") is None


def test_un_protocolo_que_falla_no_arrastra_a_los_demas(monkeypatch):
    def roto(*_a, **_k):
        raise RuntimeError("dato raro")
    monkeypatch.setattr(DL, "_protocolo_nivel_modulo", roto)
    filas, vacio = _lote_con_fecha("2031-04-10", "2031-06-05")
    salida = DL.aplicar(filas)
    assert [e["protocolo"] for e in salida["errores"]] == ["nivel_modulo"]
    assert DL._valor(vacio, "module_date") == "2031-04-10"          # el resto sí se aplicó


def test_serie_del_modulo_exacta_gana_a_la_corregida():
    exacta = _con_control("671 ZRZ0000123")
    # otra serie cuyo último carácter NO cumple pero tiene un parecido que sí: evidencia más débil
    cuerpo = next(c for c in (f"671 ZRZ{n:07d}" for n in range(200, 400))
                  if TI.control_code39(c) in DL.PARECIDOS)
    control = TI.control_code39(cuerpo)
    debil = cuerpo + DL.PARECIDOS[control][0]
    assert not TI.valida_code39(debil) and DL.con_control_valido(debil, TI.valida_code39) == cuerpo + control
    fila = _fila("1", textos=[exacta, debil])
    DL.aplicar([fila])
    assert DL._valor(fila, "module_serial_number") == exacta
    assert fila["campos"]["module_serial_number"]["regla"] == "control_code39_serie_modulo_exacta"


def test_dos_series_del_modulo_exactas_siguen_sin_publicarse():
    fila = _fila("1", textos=[_con_control("671 ZRZ0000123"), _con_control("671 ZRZ0000456")])
    DL.aplicar([fila])
    assert DL._valor(fila, "module_serial_number") in (None, "")


def test_la_salida_conserva_el_contrato_anterior():
    salida = DL.aplicar([])
    assert salida["version"] == DL.VERSION and salida["total"] == 0 and salida["decisiones"] == []
    assert salida["errores"] == [] and salida["rechazadas"] == []


# --- formulario de dudas ------------------------------------------------------------------------
def test_no_lo_tengo_se_acepta_con_valor_nulo():
    """Antes una segunda clase `Decision` (valor obligatorio) tapaba a la primera: por HTTP el
    botón «No lo tengo» se rechazaba con 422."""
    import panel_confirmacion as pc
    assert pc.Decision(id="x").valor is None
    campos = getattr(pc.Decision, "model_fields", None) or pc.Decision.__fields__
    assert not getattr(campos["valor"], "is_required", lambda: campos["valor"].required)()


def test_deshacer_quita_la_decision_sin_guardar():
    import panel_confirmacion as pc

    class _Estado:
        decisiones = {"a": {"valor": "1"}}
    anterior, pc.ESTADO = pc.ESTADO, _Estado()
    try:
        assert pc.api_deshacer(pc.Deshacer(id="a")) == {"id": "a", "deshecha": True}
        assert pc.api_deshacer(pc.Deshacer(id="a"))["deshecha"] is False and not _Estado.decisiones
    finally:
        pc.ESTADO = anterior


def test_la_pagina_cumple_la_guia_visual_y_no_usa_la_red():
    import re

    import panel_confirmacion as pc
    html = pc.PAGINA
    for obligatorio in ("html[data-theme=light]", "prefers-reduced-motion", ":focus-visible",
                        "tema-switch", "[hidden]{display:none", "Otro texto", 'id="visor"', "Pieza:",
                        "/api/deshacer", "/api/decidir_varias", "<noscript>"):
        assert obligatorio in html, obligatorio
    # sin CDNs ni fuentes externas: el cliente no tiene red
    assert not re.search(r"https?://|@import|<link", html)
    # todo lo que llega del servidor se escapa antes de entrar en el HTML
    assert "${d.detalle}" not in html and "<li>${t}</li>" not in html
