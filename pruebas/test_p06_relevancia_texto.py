"""P06 · Ruido y «sin datos»: clasificar el texto antes de creérselo.

Los textos de prueba son reales: el ruido sale de una etiqueta fotografiada del corpus
(`IMG_4156.JPG`), y lo demás, de las cadenas que el flujo produce de verdad.
"""
import pytest


@pytest.fixture()
def rt():
    from utilidades import relevancia_texto
    return relevancia_texto


RUIDO_REAL = ("HW: 15 3 D 8 8 0 2 3 2 : BE3 !2 6 8 1 1 1 1 8 ? ~ E 2 & 8 0080 67a 70705399910 "
              "8 4 2 2 1")


def test_una_etiqueta_ilegible_es_ruido(rt):
    c = rt.clasificar(RUIDO_REAL)
    assert c["clase"] in {"solo_ruido", "texto_no_pertinente"}
    assert c["motivo"] in rt.MOTIVOS


def test_sin_ningun_texto(rt):
    for texto in ("", "   ", "7 2 1"):
        c = rt.clasificar(texto)
        assert c["clase"] == "sin_texto"
        assert c["motivo"] == "sin_texto_detectable"


def test_texto_legible_sin_campos_del_contrato(rt):
    c = rt.clasificar("Herramienta sobre la mesa del laboratorio EDAG")
    assert c["clase"] in {"texto_no_pertinente", "con_datos"}


def test_un_solo_campo_bueno_basta_para_que_tenga_datos(rt):
    """Aunque el 90 % del texto sea basura, si hay un serial válido, hay datos."""
    candidatos = [{"clave": "module_serial_number", "valor_normalizado": "671 ZRZ0539991D",
                   "valido_catalogo": True}]
    c = rt.clasificar(RUIDO_REAL + " 671 ZRZ0539991D", candidatos)
    assert c["clase"] == "con_datos"
    assert c["campos"] == ["module_serial_number"]
    assert c["motivo"] is None


def test_un_candidato_invalido_no_convierte_ruido_en_datos(rt):
    candidatos = [{"clave": "test_number", "valor_normalizado": "", "valido_catalogo": True}]
    assert rt.clasificar(RUIDO_REAL, candidatos)["clase"] != "con_datos"


def test_el_motivo_es_de_catalogo_cerrado(rt):
    for texto in ("", RUIDO_REAL, "etiqueta del tablero lado derecho", "671 ZRZ0539991D"):
        assert rt.motivo_para_imagen_sin_datos(texto) in rt.MOTIVOS + (
            "revisar: la imagen contiene campos",), texto


def test_resumen_cuenta_lo_descartable(rt):
    clas = [rt.clasificar(""), rt.clasificar(RUIDO_REAL),
            rt.clasificar("671 ZRZ0539991D",
                          [{"clave": "module_serial_number", "valor_normalizado": "671 ZRZ0539991D"}])]
    r = rt.resumen(clas)
    assert r["imagenes"] == 3 and r["con_datos"] == 1 and r["descartables"] == 2


# --------------------------------------------------------------------------
# Las tres correcciones que salieron de medir el corpus
# --------------------------------------------------------------------------
@pytest.fixture()
def fe():
    import flujo_empresarial
    return flujo_empresarial


IMAGEN = {"ruta_relativa": "caso/foto.jpg", "confianza_ocr": 0.9}


def test_el_nombre_del_proyecto_no_es_numero_de_prueba(fe):
    """'VW316' se publicaba como test_number. Un número de prueba tiene seis dígitos."""
    claves = {c["clave"]: c["valor_normalizado"]
              for c in fe.extraer_candidatos_texto("VW316 ETIKETT", IMAGEN, {})}
    assert "test_number" not in claves
    assert claves.get("_proyecto_designacion") == "VW316"


def test_vw_no_es_un_lugar_de_ensayo_sin_confirmar(fe):
    """El libro dice EDAG. VW como lugar se propone, nunca se da por bueno."""
    lugares = [c for c in fe.extraer_candidatos_texto("VW 222504", IMAGEN, {})
               if c["clave"] == "test_place"]
    assert lugares and all(c["requiere_confirmacion_manual"] for c in lugares)


def test_el_serial_tiene_que_terminar_en_letra(fe):
    """'671 ZRZ05399910' (con cero final) se publicaba como serial: es una D mal leída."""
    assert [c for c in fe.extraer_candidatos_texto("671 ZRZ05399910", IMAGEN, {})
            if c["clave"] == "module_serial_number"] == []
    assert [c["valor_normalizado"] for c in
            fe.extraer_candidatos_texto("671 ZRZ0539991D", IMAGEN, {})
            if c["clave"] == "module_serial_number"] == ["671 ZRZ0539991D"]
