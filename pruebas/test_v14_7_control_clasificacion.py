"""V14.7: el control manual no degrada la clasificación semántica."""
from ocr_engine import _clasificar_informacion_region


def test_simbolos_fuertes_no_se_convierten_en_codigo_por_confianza():
    candidato = _clasificar_informacion_region("I21%5:1", .99)
    assert candidato["tipo_informacion"] != "codigo"
    assert not candidato["probable_codigo"]


def test_codigos_limpios_siguen_siendo_codigos():
    for texto in ("S4054664", "4054664", "abc12345"):
        candidato = _clasificar_informacion_region(texto, .65)
        assert candidato["tipo_informacion"] == "codigo"
        assert candidato["probable_codigo"]


def test_fecha_con_mes_no_compite_como_codigo():
    candidato = _clasificar_informacion_region("16/MAY/2026", .65)
    assert candidato["tipo_informacion"] == "fecha"
    assert not candidato["probable_codigo"]
