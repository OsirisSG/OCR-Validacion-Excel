"""P50 · Protocolos en cascada para llenar el máximo sin copiar del Book (valores sintéticos 2031)."""
from __future__ import annotations

import decisiones_lote as DL
import modulo_integracion as MI
import video_overlay as VO


# --- delay del pie del vídeo -------------------------------------------------------------------
def test_delay_del_pie_cero_es_guiones_y_cinco_es_5ms():
    assert VO.interpretar_pie("VW316/5 993101 RdW RT NOM 0msEDAG MexBMG19 JUN31")["delay_ms"] == "--"
    assert VO.interpretar_pie("VW316/5 993101 RdW RT NOM 5 ms EDAG Mex BMG 19 JUN 31")["delay_ms"] == "5ms"
    # forma real del OCR en 2 de 3 fotogramas: «Oms» con letra O
    assert VO.interpretar_pie("VW316/5 993101 RdW RT NOM OmsEDAG MexBMG19 JUN 31Rec5000 fps")["delay_ms"] == "--"


def test_un_contador_que_cambia_entre_fotogramas_no_se_publica():
    caso = {"case_key": "P|1ST|993101", "project_id": "P", "tipo_st": "1ST"}
    lectura = {"fotogramas": 3, "votos": {"delay_ms": {"--": 1, "12ms": 1, "30ms": 1}}}
    assert not [c for c in VO.candidatos_overlay(caso, {"ruta": "/v/A.AVI"}, lectura) if c["clave"] == "delay_ms"]
    lectura = {"fotogramas": 3, "votos": {"delay_ms": {"--": 3}}}
    assert [c["valor_normalizado"] for c in VO.candidatos_overlay(caso, {"ruta": "/v/A.AVI"}, lectura)
            if c["clave"] == "delay_ms"] == ["--"]


# --- cascada de la etiqueta del módulo ---------------------------------------------------------
class Lector:
    def __init__(self, es_modulo_en=()):
        self.leidas, self.es_modulo_en = [], set(es_modulo_en)

    def leer(self, ruta):
        self.leidas.append(ruta)
        if ruta in self.es_modulo_en:
            return {"es_modulo": True, "date": "2031-04-10", "lineas": [{"texto": "10.04.31", "caja": {}}]}
        return {"es_modulo": False, "lineas": []}


def test_sin_ganchos_se_pasa_a_las_fotos_vor_y_se_para_al_encontrar_la_etiqueta():
    caso = {"case_key": "P|1ST|993101"}
    fotos = [{"ruta": f"/f/{n}.JPG", "ruta_relativa": f"PHOTOS/{fase}/{n}.JPG", "fase": fase}
             for n, fase in (("N1", "NACH"), ("V1", "VOR"), ("V2", "VOR"), ("V3", "VOR"))]
    lector = Lector(es_modulo_en={"/f/V2.JPG"})
    r = MI.procesar_caso_modulo(caso, fotos, {}, lector=lector)
    assert lector.leidas == ["/f/V1.JPG", "/f/V2.JPG", "/f/V3.JPG"]      # NACH sin ganchos no se lee
    assert r["protocolos"] == ["vor_sin_ganchos"]
    assert {c["clave"] for c in r["candidatos"]} == {"module_date"}


def test_con_ganchos_no_se_baja_al_siguiente_protocolo():
    caso = {"case_key": "P|1ST|993101"}
    fotos = [{"ruta": "/f/A.JPG", "ruta_relativa": "PHOTOS/VOR/A.JPG", "fase": "VOR"},
             {"ruta": "/f/B.JPG", "ruta_relativa": "PHOTOS/VOR/B.JPG", "fase": "VOR"}]
    lector = Lector(es_modulo_en={"/f/A.JPG"})
    r = MI.procesar_caso_modulo(caso, fotos, {"PHOTOS/VOR/A.JPG": "Airbag Module\nDachau"}, lector=lector)
    assert lector.leidas == ["/f/A.JPG"] and r["protocolos"] == ["ganchos_2"]


# --- decisiones de lote ------------------------------------------------------------------------
def _fila(numero, campos=None, lecturas_modulo=None, tablero=None, candidatos=None):
    return {"test_number": numero, "case_key": f"P|1ST|{numero}",
            "campos": {k: (v if isinstance(v, dict) else {"valor": v}) for k, v in (campos or {}).items()},
            "etiqueta_modulo": {"lecturas": lecturas_modulo or []},
            "tablero_p42": {"campos": tablero or {}}, "candidatos": candidatos or []}


def test_nivel_por_estampa_con_sufijo_y_nivel_de_partida_en_serie():
    proto = _fila("993101", lecturas_modulo=[{"foto": "a", "es_modulo": True, "prototipo": True, "estampa": "66K"},
                                             {"foto": "b", "es_modulo": True, "prototipo": True, "estampa": "66K"}])
    proto_mal = _fila("993102", campos={"engineering_level": {"valor": None, "valor_propuesto": "02S"}},
                      lecturas_modulo=[{"foto": "a", "es_modulo": True, "prototipo": True}])
    serie = [_fila(str(993110 + i), lecturas_modulo=[{"foto": "a", "es_modulo": True}]) for i in range(3)]
    resultados = [proto, proto_mal, *serie]
    DL.aplicar(resultados, {})
    assert proto["campos"]["engineering_level"]["valor"] == "66K"
    assert proto_mal["campos"]["engineering_level"]["valor"] is None
    assert proto_mal["campos"]["engineering_level"]["valor_propuesto"] is None   # 02S no cabe en prototipo
    assert all(f["campos"]["engineering_level"]["valor"] == "01S" for f in serie)
    assert proto["tipo_pieza"] == "prototipo" and serie[0]["tipo_pieza"] == "serie"


def test_dos_casos_de_serie_sin_estampa_no_bastan_para_el_nivel_de_partida():
    serie = [_fila(str(993110 + i), lecturas_modulo=[{"foto": "a", "es_modulo": True}]) for i in range(2)]
    DL.aplicar(serie, {})
    assert all(f["campos"]["engineering_level"].get("valor") is None for f in serie)


def test_lote_del_tablero_cierra_una_lectura_suelta_y_respeta_la_contraria():
    np = {"dashboard_part_number": "2GJ.857.003.G"}
    a = _fila("1", {**np, "dashboard_engineering_level": "03S"})
    b = _fila("2", {**np, "dashboard_engineering_level": "03S"})
    sola = _fila("3", {**np, "dashboard_engineering_level": {"valor": None}},
                 tablero={"dashboard_engineering_level": {"votos": {"03S": 1}}})
    contraria = _fila("4", {**np, "dashboard_engineering_level": {"valor": None}},
                      tablero={"dashboard_engineering_level": {"votos": {"05S": 1}}})
    sin_lectura = _fila("5", {**np, "dashboard_engineering_level": {"valor": None}})
    informe = DL.aplicar([a, b, sola, contraria, sin_lectura], {})
    assert sola["campos"]["dashboard_engineering_level"]["valor"] == "03S"
    assert contraria["campos"]["dashboard_engineering_level"]["valor"] is None
    assert sin_lectura["campos"]["dashboard_engineering_level"]["valor"] is None
    assert any(d["regla"] == "consenso_lote_tablero" for d in informe["decisiones"])


def test_proveedor_por_numero_de_parte_y_motivo_por_pie_mas_libro():
    np = {"module_part_number": "2GJ.880.204.J"}
    filas = [_fila("1", {**np, "inflator_supplier": "Autoliv"}), _fila("2", {**np, "inflator_supplier": "Autoliv"}),
             _fila("3", {**np, "inflator_supplier": {"valor": None}},
                   candidatos=[{"clave": "test_reason", "valor_normalizado": "BMG", "fuente": "barra_video"}])]
    DL.aplicar(filas, {"test_reason": {"IT BMG": 89}})
    assert filas[2]["campos"]["inflator_supplier"]["valor"] == "Autoliv"
    assert filas[2]["campos"]["test_reason"]["valor"] == "IT BMG"
    assert filas[2]["campos"]["test_reason"]["regla"] == "motivo_regla_usuario"     # P51 · BMG → IT BMG


def test_motivo_ambiguo_en_el_libro_se_imprime_tal_cual_del_pie():
    # P51 · regla del usuario: lo que haya en la posición del motivo se imprime
    fila = _fila("1", candidatos=[{"clave": "test_reason", "valor_normalizado": "LAB", "fuente": "barra_video"}])
    DL.aplicar([fila], {"test_reason": {"IT LAB": 5, "LAB 2": 4}})
    assert fila["campos"]["test_reason"]["valor"] == "LAB"
    assert fila["campos"]["test_reason"]["regla"] == "motivo_tal_cual_del_pie"


def test_no_se_pisa_un_valor_humano():
    fila = _fila("1", {"inflator_supplier": {"valor": None, "confirmacion_manual": True}})
    otros = [_fila(str(i), {"module_part_number": "X", "inflator_supplier": "Autoliv"}) for i in (2, 3)]
    fila["campos"]["module_part_number"] = {"valor": "X"}
    DL.aplicar([fila, *otros], {})
    assert fila["campos"]["inflator_supplier"]["valor"] is None


# --- formulario --------------------------------------------------------------------------------
def test_formulario_filtra_niveles_por_nomenclatura():
    from utilidades.dudas_y_opciones import construir_dudas
    lecturas = {"993101": {"tipo_pieza": "prototipo", "ocr": {"engineering_level": {"02S": 2, "66K": 2}}}}
    duda = next(d for d in construir_dudas({"993101": {}}, lecturas, campos=("engineering_level",)))
    valores = [o["valor"] for o in duda["opciones"] if o["valor"]]
    assert valores == ["66K"] and "##K" in duda["detalle"]


def test_abrir_panel_al_terminar(tmp_path):
    from utilidades.abrir_panel import abrir_panel_dudas
    libro, val = tmp_path / "l.xlsx", tmp_path / "v.json"
    libro.write_bytes(b"x"); val.write_text("{}")
    lanzadas, abiertas = [], []
    r = abrir_panel_dudas(libro, val, {}, lanzar=lanzadas.append, abrir_navegador=abiertas.append)
    assert r["abierto"] and "--validacion" in lanzadas[0] and str(libro) in lanzadas[0]
    assert abrir_panel_dudas(libro, val, {"empresarial": {"panel_dudas": {"abrir_al_terminar": False}}},
                             lanzar=lanzadas.append)["abierto"] is False


def test_estampa_k_o_etiqueta_prototypes_marcan_prototipo():
    assert DL.tipo_pieza(_fila("1", lecturas_modulo=[{"es_modulo": True, "estampa": "69K"}])) == "prototipo"
    assert DL.tipo_pieza(_fila("1", lecturas_modulo=[{"es_modulo": True, "ganchos": ["np", "prototipo"]}])) == "prototipo"
    assert DL.tipo_pieza(_fila("1", lecturas_modulo=[{"es_modulo": True, "ganchos": ["np"]}])) == "serie"
    assert DL.tipo_pieza(_fila("1")) is None


def test_fecha_leida_en_la_foto_de_prototypes_no_cuenta_como_etiqueta_del_modulo():
    lectura = {"es_modulo": True, "date": "2031-04-11", "lineas": [{"texto": "11/04/2031", "caja": {}}]}
    cands = MI.candidatos_de_lectura({"case_key": "x"}, {"ruta_relativa": "V.JPG"}, lectura, ["np", "prototipo"])
    assert next(c for c in cands if c["clave"] == "module_date")["etiqueta"] == "prototipo"
