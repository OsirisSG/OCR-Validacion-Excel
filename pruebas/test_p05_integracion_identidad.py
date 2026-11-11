"""P05 · El protocolo de identidad enganchado en el flujo real.

No se prueba una función suelta: se prueba el descubrimiento de casos de verdad
(`flujo_empresarial.descubrir_casos`) y la forma exacta de las evidencias que consume
`validacion.py`.
"""
import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def fe():
    import flujo_empresarial
    return flujo_empresarial


@pytest.fixture()
def pi():
    from utilidades import protocolo_identidad
    return protocolo_identidad


def _maqueta(casos):
    """casos: [(nombre_carpeta, carpeta_padre)] -> raíz con PHOTOS/NACH y una foto."""
    raiz = Path(tempfile.mkdtemp())
    for nombre, padre in casos:
        destino = raiz / "1st" / padre / nombre / "PHOTOS" / "NACH"
        destino.mkdir(parents=True, exist_ok=True)
        (destino / "IMG_0001.JPG").write_bytes(b"foto")
    return raiz


def test_el_descubrimiento_marca_la_carpeta_incoherente_sin_bloquear(fe):
    """222550 cierra el bloque NT (22xxxx), así que con HT es una errata de nombre."""
    raiz = _maqueta([("232550 RDW NOM HT", "HT"), ("222550 RDW NOM HT", "HT"),
                     ("222509 RDW NOM NT", "NT")])
    resultado = fe.descubrir_casos(raiz)
    por_nombre = {c["nombre"]: c for c in resultado["casos"]}

    malo = por_nombre["222550 RDW NOM HT"]
    assert malo["coherencia_serie"]["estado"] == "incoherente"
    assert "22 de 222550 corresponde a NT" in malo["avisos_identidad"][0]

    assert por_nombre["232550 RDW NOM HT"]["coherencia_serie"]["estado"] == "coherente"
    assert por_nombre["232550 RDW NOM HT"]["avisos_identidad"] == []
    assert por_nombre["222509 RDW NOM NT"]["coherencia_serie"]["estado"] == "coherente"

    # el aviso NO cambia la validez estructural: las tres carpetas se validan igual
    assert len({c["estructura_valida"] for c in resultado["casos"]}) == 1


def test_la_carpeta_padre_manda_sobre_el_nombre(fe):
    """`HT/222509 RDW NOM NT` es incoherente aunque el número sea de la serie."""
    raiz = _maqueta([("222509 RDW NOM NT", "HT")])
    caso = fe.descubrir_casos(raiz)["casos"][0]
    assert caso["coherencia_serie"]["estado"] == "incoherente"
    assert "carpeta padre dice HT" in caso["coherencia_serie"]["motivo"]


def test_una_carpeta_con_nombre_raro_no_rompe_el_descubrimiento(fe):
    raiz = _maqueta([("cosas sueltas", "HT"), ("232550 RDW NOM HT", "HT")])
    resultado = fe.descubrir_casos(raiz)
    assert resultado["casos_encontrados"] >= 1
    coherentes = [c for c in resultado["casos"] if c["coherencia_serie"]]
    assert all(c["coherencia_serie"]["estado"] in {"coherente", "fuera_de_serie",
                                                   "incoherente", "sin_comprobar"}
               for c in coherentes)


def test_la_evidencia_de_la_barra_tiene_la_misma_forma_que_la_del_ocr(fe, pi):
    """Si la forma no encaja, `validacion.py` la descarta en silencio: hay que compararla."""
    barra = ("VW316/5   222509   RdW   NT   NOM   0ms   EDAG Mex   BMG   28 MAY 25   "
             "Rec5000 fps, Schutter 80us")
    de_barra = pi.candidatos_desde_barra(barra, {"ruta_relativa": "VIDEO/f.mp4", "confianza_ocr": 0.9},
                                         {"project_id": "P1", "tipo_st": "1ST"})
    del_ocr = fe.extraer_candidatos_texto("TEST NO 222509", {"ruta_relativa": "a.jpg",
                                                            "confianza_ocr": 0.8}, {})
    assert de_barra and del_ocr
    claves_ocr = set(del_ocr[0])
    for candidato in de_barra:
        assert set(candidato) <= claves_ocr | {"texto_barra"}, set(candidato) - claves_ocr
        for obligatoria in ("clave", "valor_normalizado", "fuente", "confianza_ocr",
                            "regla_aplicada", "requiere_confirmacion_manual", "votos"):
            assert obligatoria in candidato


def test_la_barra_aporta_los_cuatro_campos_de_identidad(pi):
    barra = ("VW316/5   222509   RdW   NT   NOM   0ms   EDAG Mex   BMG   28 MAY 25   "
             "Rec5000 fps, Schutter 80us")
    claves = {c["clave"]: c["valor_normalizado"] for c in pi.candidatos_desde_barra(barra, {}, {})}
    assert claves == {"test_number": "222509", "module_version": "RDW",
                      "temperature_condition": "NT", "inflator_type": "NOM"}
    assert all(c["fuente"] == "barra_video" for c in pi.candidatos_desde_barra(barra, {}, {}))


def test_un_texto_sin_barra_no_genera_evidencia(pi):
    """Tres rótulos sueltos no son una identidad; cuatro sí."""
    for texto in ("", "RdW NT NOM", "NT NOM OGL", "VW316/5 sin identidad",
                  "Rec5000 fps, Schutter 80us", "EDAG Mex 28 MAY 25"):
        assert pi.candidatos_desde_barra(texto, {}, {}) == [], texto


def test_la_identidad_completa_si_genera_evidencia_aunque_no_diga_vw(pi):
    """Otro proyecto puede rotular distinto: con los cuatro campos basta."""
    claves = {c["clave"]: c["valor_normalizado"]
              for c in pi.candidatos_desde_barra("222509 RDW NOM NT", {}, {})}
    assert claves["test_number"] == "222509"


def test_el_diagrama_no_exige_orden_ni_marca_del_fabricante(pi):
    """Un plano de otro proyecto puede escribir los rótulos en otro orden."""
    r = pi.leer_titulo_diagrama("VW270/2 310055 NAR OGL NT")
    # el orden del plano no altera la lectura: NAR OGL NT -> versión NAR, inflador OGL, temp. NT
    assert (r["test_number"], r["module_version"], r["temperature_condition"],
            r["inflator_type"]) == ("310055", "NAR", "NT", "OGL")
    r2 = pi.leer_titulo_diagrama("BMW G20 222521 RDW NT NOM")
    assert r2["test_number"] == "222521" and r2["inflator_type"] == "NOM"
    # sin número no hay identidad, aunque estén los tres rótulos
    assert pi.leer_titulo_diagrama("RdW NT OGL") == {}
