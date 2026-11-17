"""P52 · Dígito de control Code 39 (mod 43) en las series del tablero y del módulo, fechas como
fechas de Excel, unánime de lote y opciones verificadas en el formulario. Valores sintéticos (2031)
salvo el cálculo del dígito, que es una regla del estándar Code 39."""
from __future__ import annotations

import decisiones_lote as DL
import tablero_integracion as TI
from test_p43_integracion_tablero import PISTA, _caso, _consolidar, _fotos, _procesar, _ruta


def _con_control(cuerpo: str) -> str:
    return cuerpo + TI.control_code39(cuerpo)


SERIE = _con_control("052 3KVJ0000R7")          # serie sintética válida


def test_control_code39():
    assert TI.valida_code39(SERIE)
    assert not TI.valida_code39(SERIE[:-1] + ("A" if SERIE[-1] != "A" else "B"))
    assert TI.control_code39("ABC") == TI.CODE39[(10 + 11 + 12) % 43]


def _dm(valor):
    return {"dashboard_serial_number": {"valor": valor, "confianza": .9, "origen": "datamatrix"}}


def _un_dm(politica):
    caso = _caso()
    fotos = _fotos(caso, ["NACH/01.JPG"])
    guion = {_ruta(caso, "NACH/01.JPG"): {"pista": PISTA, "campos": _dm(SERIE)}}
    resultado, _ = _procesar(caso, fotos, guion, segunda_pasada=False, serie_control=politica)
    return caso, resultado


def test_datamatrix_verificado_se_publica_con_la_politica_completa():
    caso, resultado = _un_dm("completa")
    estado = resultado["campos"]["dashboard_serial_number"]
    assert estado["estado"] == "consenso" and estado["regla"] == "datamatrix_control_mod43"
    consolidado = _consolidar(caso, resultado)
    assert consolidado["campos"]["dashboard_serial_number"]["valor"] == TI.sin_simbolo_final(SERIE)


def test_politica_sin_control_quita_el_ultimo_caracter():
    caso, resultado = _un_dm("sin_control")
    assert resultado["campos"]["dashboard_serial_number"]["valor"] == SERIE[:-1].rstrip()


def test_politica_preguntar_deja_la_duda_con_las_dos_formas():
    _, resultado = _un_dm("preguntar")
    estado = resultado["campos"]["dashboard_serial_number"]
    assert estado["estado"] == "en_duda"
    assert estado["verificada_control"]["completa"] == TI.sin_simbolo_final(SERIE)
    assert SERIE[:-1].rstrip() in estado["variantes"]


def test_datamatrix_sin_control_valido_sigue_la_regla_anterior():
    caso = _caso()
    malo = SERIE[:-1] + ("A" if SERIE[-1] != "A" else "B")
    fotos = _fotos(caso, ["NACH/01.JPG"])
    guion = {_ruta(caso, "NACH/01.JPG"): {"pista": PISTA, "campos": _dm(malo)}}
    resultado, _ = _procesar(caso, fotos, guion, segunda_pasada=False, serie_control="completa")
    assert resultado["campos"]["dashboard_serial_number"]["estado"] != "consenso"


# --- serie del módulo --------------------------------------------------------------------------
def _fila(numero, campos=None, textos=(), candidatos=()):
    return {"test_number": numero, "case_key": f"P|1ST|{numero}",
            "campos": {k: (v if isinstance(v, dict) else {"valor": v}) for k, v in (campos or {}).items()},
            "candidatos": list(candidatos), "etiqueta_modulo": {"lecturas": []},
            "trazabilidad": [{"ruta_relativa": f"F{i}.JPG", "texto_crudo": t} for i, t in enumerate(textos)]}


MODULO = _con_control("671 ZRZ0000123")


def test_serie_del_modulo_desde_el_texto_con_correccion_de_forma():
    # «O» en la parte numérica y sin espacio: se normaliza y el control decide
    sucio = MODULO.replace(" ", "").replace("0000", "O000", 1)
    fila = _fila("1", {"module_serial_number": {"valor": None}}, textos=[f"AIRBAG\n{sucio}\nZRZ 02S"])
    DL.aplicar([fila], {})
    assert fila["campos"]["module_serial_number"]["valor"] == MODULO
    assert fila["campos"]["module_serial_number"]["regla"] == "control_code39_serie_modulo"


def test_serie_del_modulo_corrige_solo_el_ultimo_caracter_parecido():
    cuerpo = next(c for c in (f"671 ZRZ{n:07d}" for n in range(0, 9_000_000, 7919))
                  if TI.control_code39(c) in "B8")
    impreso = cuerpo + ("8" if TI.control_code39(cuerpo) == "B" else "B")
    fila = _fila("1", textos=[impreso])
    DL.aplicar([fila], {})
    assert fila["campos"]["module_serial_number"]["valor"] == cuerpo + TI.control_code39(cuerpo)


def test_serie_del_modulo_sin_control_valido_o_dos_validas_no_se_publica():
    malo = MODULO[:-1] + ("A" if MODULO[-1] != "A" else "C")
    otra = _con_control("671 ZRZ0000999")
    f1, f2 = _fila("1", textos=[malo]), _fila("2", textos=[MODULO, otra])
    DL.aplicar([f1, f2], {})
    assert (f1["campos"].get("module_serial_number") or {}).get("valor") in (None, "") or \
        TI.valida_code39(f1["campos"]["module_serial_number"]["valor"])
    assert (f2["campos"].get("module_serial_number") or {}).get("valor") is None


def test_serie_publicada_no_se_toca():
    fila = _fila("1", {"module_serial_number": "671 ZRZ9999999X"}, textos=[MODULO])
    DL.aplicar([fila], {})
    assert fila["campos"]["module_serial_number"]["valor"] == "671 ZRZ9999999X"


# --- unánime de lote ---------------------------------------------------------------------------
def test_unanime_de_lote_con_etiqueta_vista():
    pub = [_fila(str(i), {"module_date": "2031-04-10"}) for i in range(6)]
    vista = _fila("9", textos=["ZRZ 02S 2GJ 880 204 J"])
    sin_etiqueta = _fila("8", textos=["tablero"])
    DL.aplicar([*pub, vista, sin_etiqueta], {})
    assert vista["campos"]["module_date"]["valor"] == "2031-04-10"
    assert vista["campos"]["module_date"]["regla"] == "unanime_lote_modulo"
    assert (sin_etiqueta["campos"].get("module_date") or {}).get("valor") is None


def test_unanime_de_lote_no_aplica_con_lectura_contraria_o_pocos_casos():
    pub = [_fila(str(i), {"module_date": "2031-04-10"}) for i in range(6)]
    contraria = _fila("7", textos=["ZRZ"], candidatos=[{"clave": "module_date", "valor_normalizado": "2031-04-11",
                                                          "fuente": "ocr"}])
    vista = _fila("9", textos=["ZRZ"])
    DL.aplicar([*pub, contraria, vista], {})
    assert (vista["campos"].get("module_date") or {}).get("valor") is None
    pocos = [_fila(str(i), {"module_date": "2031-04-10"}) for i in range(5)]
    vista2 = _fila("9", textos=["ZRZ"])
    DL.aplicar([*pocos, vista2], {})
    assert (vista2["campos"].get("module_date") or {}).get("valor") is None
    vista3 = _fila("9", textos=["ZRZ"])
    DL.aplicar([*[_fila(str(i), {"module_date": "2031-04-10"}) for i in range(6)], vista3], {}, unanime_lote=0)
    assert (vista3["campos"].get("module_date") or {}).get("valor") is None


# --- fechas como fechas ------------------------------------------------------------------------
def test_fechas_se_escriben_como_fecha_de_excel():
    from datetime import datetime

    from openpyxl import Workbook

    import reporte_bmg as R
    hoja = Workbook().active
    resultado = {"campos": {"module_date": {"valor": "2031-04-10", "estado": "consenso"},
                            "test_date": {"valor": "2031-05-28", "estado": "consenso"}}}
    R._escribir_fila(hoja, 8, resultado)
    columna = R.CLAVES_PLANTILLA.index("module_date") + 1
    celda = hoja.cell(8, columna)
    if celda.value is not None:
        assert isinstance(celda.value, datetime) and celda.value.year == 2031


# --- formulario --------------------------------------------------------------------------------
def test_formulario_ofrece_la_serie_verificada_recomendada():
    from utilidades.dudas_y_opciones import construir_dudas
    lecturas = {"232564": {"verificadas": {"dashboard_serial_number": {
        "datamatrix": SERIE, "completa": TI.sin_simbolo_final(SERIE), "sin_control": SERIE[:-1]}},
        "tablero_p42": {"dashboard_serial_number": {SERIE[:-1] + "Q": 1}}}}
    dudas = construir_dudas({"232564": {}}, lecturas, campos=("dashboard_serial_number",))
    opciones = dudas[0]["opciones"]
    assert opciones[0]["valor"] == TI.sin_simbolo_final(SERIE)
    assert opciones[0]["fuente"] == "serie_verificada"
    assert any(o["valor"] == SERIE[:-1] for o in opciones)


def test_formulario_baja_la_serie_del_modulo_que_no_cumple_el_control():
    from utilidades.dudas_y_opciones import construir_dudas
    malo = MODULO[:-1] + ("A" if MODULO[-1] != "A" else "C")
    lecturas = {"1": {"ocr": {"module_serial_number": {malo: 2, MODULO: 2}}}}
    dudas = construir_dudas({"1": {}}, lecturas, campos=("module_serial_number",))
    assert dudas[0]["opciones"][0]["valor"] == MODULO
