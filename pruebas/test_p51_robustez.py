"""P51 · Peticiones del 13/11: motivo por posición del pie (BMG → IT BMG, comillas, lote), colores
de temperatura, prototipo bien detectado, fechas por desempate de lote, proveedor robusto y búsqueda
extra de la serie del tablero. Valores sintéticos (2031)."""
from __future__ import annotations

import decisiones_lote as DL
import tablero_integracion as TI
import video_overlay as VO
from test_p43_integracion_tablero import PISTA, _caso, _fotos, _procesar, _ruta


def _fila(numero, campos=None, candidatos=None, textos=(), lecturas_modulo=None):
    return {"test_number": numero, "case_key": f"P|1ST|{numero}",
            "campos": {k: (v if isinstance(v, dict) else {"valor": v}) for k, v in (campos or {}).items()},
            "candidatos": list(candidatos or []), "etiqueta_modulo": {"lecturas": lecturas_modulo or []},
            "trazabilidad": [{"ruta_relativa": f"F{i}.JPG", "texto_crudo": t} for i, t in enumerate(textos)]}


def _pie(motivo):
    return [{"clave": "test_reason", "valor_normalizado": motivo, "fuente": "barra_video"}] if motivo else \
           [{"clave": "test_date", "valor_normalizado": "2031-06-05", "fuente": "barra_video"}]


# --- B motivo ----------------------------------------------------------------------------------
def test_motivo_entre_comillas_y_ruido_de_una_letra_en_la_posicion():
    assert VO.interpretar_pie('VW316/5 1 RdW HT NOM 0ms EDAG Mex "BMG" 05 JUN 31')["test_reason"] == "BMG"
    assert VO.interpretar_pie("VW316/5 1 RdW NT NOM 0ms EDAG Mex E BMG 28 MAY 31")["test_reason"] == "BMG"
    assert "test_reason" not in VO.interpretar_pie("VW316/5 1 RdW HT NOM 0ms EDAG Mex 05 JUN 31")


def test_bmg_se_imprime_it_bmg_otro_motivo_tal_cual_y_el_vacio_por_lote():
    filas = [_fila(str(i), candidatos=_pie("BMG")) for i in range(3)]
    otro = _fila("9", candidatos=_pie("XYZ"))
    vacios = [_fila(str(10 + i), candidatos=_pie(None)) for i in range(2)]
    DL.aplicar([*filas, *vacios], {}, {"BMG": "IT BMG"})
    assert [f["campos"]["test_reason"]["valor"] for f in filas] == ["IT BMG"] * 3
    assert all(f["campos"]["test_reason"]["regla"] == "motivo_consenso_lote" for f in vacios)
    DL.aplicar([otro], {}, {"BMG": "IT BMG"})
    assert otro["campos"]["test_reason"]["valor"] == "XYZ"


def test_motivo_por_lote_no_se_usa_si_la_corrida_tiene_dos_motivos():
    filas = [_fila("1", candidatos=_pie("BMG")), _fila("2", candidatos=_pie("BMG")),
             _fila("3", candidatos=_pie("XYZ")), _fila("4", candidatos=_pie(None))]
    DL.aplicar(filas, {}, {"BMG": "IT BMG"})
    assert (filas[3]["campos"].get("test_reason") or {}).get("valor") is None


# --- K: prototipo por la etiqueta del módulo, no por la pegatina del generador -----------------
def test_prototipo_por_texto_de_la_etiqueta_del_modulo_y_no_por_el_generador():
    modulo = "OGL | 66K | F47AQW00852405G | X651538300C-01-14 | PROTOTYPE | 2GJ 880 204 J | 10.04.31"
    generador = "ACHTUNG | AVISO: | Generador | PROTOTYPE AQu | 6516289"
    assert DL.tipo_pieza(_fila("1", textos=[modulo], lecturas_modulo=[{"es_modulo": True}])) == "prototipo"
    assert DL.tipo_pieza(_fila("1", textos=[generador], lecturas_modulo=[{"es_modulo": True}])) == "serie"


def test_prototipo_no_recibe_01s_y_su_nivel_sale_de_dos_lecturas():
    modulo = "OGL | 66K | PROTOTYPE | 2GJ 880 204 J | 10.04.31"
    proto = _fila("1", textos=[modulo], lecturas_modulo=[{"foto": "a", "es_modulo": True, "estampa": "66K"}])
    serie = [_fila(str(10 + i), lecturas_modulo=[{"foto": "a", "es_modulo": True}]) for i in range(3)]
    DL.aplicar([proto, *serie], {})
    assert proto["campos"]["engineering_level"]["valor"] == "66K"          # estampa + texto de la etiqueta
    assert all(f["campos"]["engineering_level"]["valor"] == "01S" for f in serie)
    solo_texto = _fila("2", textos=[modulo], lecturas_modulo=[{"foto": "a", "es_modulo": True}])
    DL.aplicar([solo_texto, *[_fila(str(20 + i), lecturas_modulo=[{"foto": "a", "es_modulo": True}]) for i in range(3)]], {})
    assert solo_texto["campos"]["engineering_level"].get("valor") is None  # una sola lectura: duda
    assert solo_texto["campos"]["engineering_level"]["valor_propuesto"] == "66K"


# --- fechas y proveedor ------------------------------------------------------------------------
def _mod(valor, fuente="etiqueta_modulo", foto="A"):
    return {"clave": "module_date", "valor_normalizado": valor, "fuente": fuente, "imagen": foto}


def test_desempate_de_fecha_por_lote():
    pub = [_fila(str(i), {"module_date": "2031-04-10"}) for i in range(3)]
    duda = _fila("9", {"module_date": {"valor": None}}, candidatos=[_mod("2031-04-01"), _mod("2031-04-10", foto="B")])
    sola = _fila("8", {"module_date": {"valor": None}}, candidatos=[_mod("2031-04-11")])
    DL.aplicar([*pub, duda, sola], {})
    assert duda["campos"]["module_date"]["valor"] == "2031-04-10"
    assert sola["campos"]["module_date"].get("valor") is None              # sin lectura igual: duda


def test_proveedor_unanime_en_la_corrida_con_etiqueta_vista():
    pub = [_fila(str(i), {"inflator_supplier": "Autoliv"}) for i in range(5)]
    vista = _fila("9", textos=["ZRZ 02S 2GJ 880 204 J"])
    sin_etiqueta = _fila("8", textos=["foto del tablero"])
    DL.aplicar([*pub, vista, sin_etiqueta], {})
    assert vista["campos"]["inflator_supplier"]["valor"] == "Autoliv"
    assert (sin_etiqueta["campos"].get("inflator_supplier") or {}).get("valor") is None


def test_numero_interno_de_autoliv_identifica_el_proveedor():
    import flujo_empresarial as fe
    valores = {(e["clave"], e["valor_normalizado"]) for e in fe.extraer_candidatos_texto(
        "Airbag Module APM2/1\nX651538300C-01-14", {"confianza_ocr": .9, "ruta_relativa": "A.JPG"}, {})}
    assert ("inflator_supplier", "Autoliv") in valores


# --- serie del tablero -------------------------------------------------------------------------
def test_serie_sin_simbolo_final():
    assert TI.sin_simbolo_final("052 3KVJ0000R69$") == "052 3KVJ0000R69S"
    assert TI.sin_simbolo_final("052 3KVJ0000R5D%") == "052 3KVJ0000R5D"
    assert TI.sin_simbolo_final("052 3KVJ0000R5DA") == "052 3KVJ0000R5DA"


def test_busqueda_extra_de_la_serie_lee_fotos_fuera_de_cupo():
    caso = _caso()
    rutas = [f"NACH/{i:02d}.JPG" for i in range(8)]
    fotos = _fotos(caso, rutas)
    serie = {"dashboard_serial_number": {"valor": "052 3KVJ0000ABC", "confianza": .9, "origen": "impreso"}}
    guion = {_ruta(caso, r): {"pista": PISTA, "campos": serie if i >= 2 else {}} for i, r in enumerate(rutas)}
    cupos = {"etiqueta": 2}
    sin, _ = _procesar(caso, fotos, guion, cupos=cupos, segunda_pasada=False, maximo_extra_serie=0)
    con, lector = _procesar(caso, fotos, guion, cupos=cupos, segunda_pasada=False, maximo_extra_serie=12)
    assert sin["campos"]["dashboard_serial_number"]["estado"] != "consenso"
    assert con["extra_serie"]["examinadas"] >= 2
    assert con["campos"]["dashboard_serial_number"]["estado"] == "consenso"


# --- colores de temperatura --------------------------------------------------------------------
def test_colores_de_temperatura():
    from openpyxl import Workbook
    import reporte_bmg as R
    ws = Workbook().active
    for fila, (valor, color) in enumerate((("HT", "FFFF0000"), ("NT", "FF00B0F0"), ("RT", "FF000000")), start=1):
        ws.cell(fila, 1).value = valor
        R._colorear_temperatura(ws.cell(fila, 1), valor)
        assert ws.cell(fila, 1).font.color.rgb == color
