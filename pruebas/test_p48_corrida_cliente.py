"""P48 · Reglas sacadas de la corrida real del cliente (12/11, 10 casos, producción con EasyOCR).
Textos con la FORMA leída en esa corrida; valores sintéticos (año 2031)."""
from __future__ import annotations

import flujo_empresarial as fe

CASO = {"case_key": "P|1ST|993101", "project_id": "P", "tipo_st": "1ST", "ruta_relativa": "x",
        "metadata_ruta": {}}
PERFIL = {"perfil_extraccion": {"formato_fecha_modulo": "DMY"}}


def _img(nombre):
    return {"confianza_ocr": 0.9, "ruta_relativa": f"PHOTOS/NACH/{nombre}.JPG"}


def _claves(texto, nombre="IMG_1"):
    return {(e["clave"], e["valor_normalizado"])
            for e in fe.extraer_candidatos_texto(texto, _img(nombre), PERFIL)}


def test_autoliv_mal_leido_por_easyocr_se_reconoce_en_el_modulo():
    for texto in ("0589 PI 0006 -\nAirbag Module APM\nAutolm B V  Co K(",
                  "T2GJ 20\n0589 5 P\nAirbag M\nAutoln B\nEmmi Ac",
                  "651538300\nMade\nT 2GJ 204\n0589 _ P1 _ 000678\nAutoll"):
        assert ("inflator_supplier", "Autoliv") in _claves(texto), texto


def test_palabras_parecidas_no_son_autoliv():
    assert not any(c == "inflator_supplier" for c, _ in _claves("Airbag Module\nAUTOLOGO\nAU"))


def test_fecha_del_modulo_de_una_sola_foto_y_otra_etiqueta_va_a_dudas():
    evid = fe.extraer_candidatos_texto("Airbag cover\n11/04/2031", _img("A"), PERFIL)
    evid = [e for e in evid if e["clave"] == "module_date"] or [
        {**e, "clave": "module_date", "valido": True} for e in evid if "fecha" in e["clave"]]
    for e in evid:
        e.update(componente="bolsa_aire", clave="module_date")
        e.pop("etiqueta", None)
    campo = fe.consolidar_caso(CASO, evid)["campos"]["module_date"]
    assert campo["valor"] is None and campo["valor_propuesto"] == "2031-04-11"
    assert campo["estado"] == "pendiente_corroboracion"


def test_fecha_de_la_etiqueta_del_modulo_en_una_foto_si_se_publica():
    texto = "VW AG\n671ZRZ0000001V\nAirbag Module APM2/1\nAutoliv B.V.\n10.04.31"
    evid = fe.extraer_candidatos_texto(texto, _img("B"), PERFIL)
    campo = fe.consolidar_caso(CASO, evid)["campos"]["module_date"]
    assert campo["valor"] == "2031-04-10"


def test_fecha_con_formato_de_la_etiqueta_del_modulo_en_una_foto_se_publica():
    evid = [{**e, "componente": "bolsa_aire", "clave": "module_date"}
            for e in fe.extraer_candidatos_texto("AIRBAG\n10.04.31", _img("D"), PERFIL)
            if e["clave"] in ("module_date", "_fecha_por_identificar")]
    assert fe.consolidar_caso(CASO, evid)["campos"]["module_date"]["valor"] == "2031-04-10"


def test_fecha_del_modulo_en_varias_fotos_se_publica():
    evid = []
    for i in range(3):
        evid += [{**e, "componente": "bolsa_aire", "clave": "module_date"}
                 for e in fe.extraer_candidatos_texto("Airbag cover\n10.04.31", _img(f"C{i}"), PERFIL)
                 if e["clave"] in ("module_date", "_fecha_por_identificar")]
    campo = fe.consolidar_caso(CASO, evid)["campos"]["module_date"]
    assert campo["valor"] == "2031-04-10"


def _cand(valor, fuente, imagen):
    return {"proyecto": "P", "etapa": "1ST", "caso": CASO["case_key"], "componente": "bolsa_aire",
            "clave": "inflator_type", "valor_original": valor, "valor_normalizado": valor,
            "fuente": fuente, "imagen": imagen, "confianza_ocr": 0.9, "valido_catalogo": True,
            "valido_regex": True, "regla_aplicada": "x", "confirmacion_manual": False}


def test_carpeta_y_videos_mandan_sobre_una_lectura_ocr_suelta():
    evid = [_cand("OGL", "ruta_carpeta", None)]
    evid += [_cand("OGL", "barra_video", f"VIDEOS/{n}.AVI") for n in "ABCD"]
    evid += [_cand("OGL", "ocr", "PHOTOS/NACH/1.JPG"), _cand("UGL", "ocr", "PHOTOS/NACH/2.JPG")]
    campo = fe.consolidar_caso(CASO, evid)["campos"]["inflator_type"]
    assert (campo["valor"], campo.get("regla")) == ("OGL", "ruta_corroborada_por_video")
    assert campo["alternativas_ocr"] == ["UGL"]


def test_sin_videos_la_discrepancia_sigue_siendo_conflicto():
    evid = [_cand("OGL", "ruta_carpeta", None), _cand("UGL", "ocr", "PHOTOS/NACH/2.JPG")]
    campo = fe.consolidar_caso(CASO, evid)["campos"]["inflator_type"]
    assert campo["estado"] == "conflicto"
