"""P49 · Lector dedicado de la etiqueta del módulo en la corrida normal, constantes del proyecto
(FORVIA / láser, pendientes) y aceptar recomendaciones en lote. Valores sintéticos (2031)."""
from __future__ import annotations

import flujo_empresarial as fe
import modulo_integracion as MI

CASO = {"case_key": "P|1ST|993101", "project_id": "P", "tipo_st": "1ST", "ruta_relativa": "x",
        "metadata_ruta": {}}
LINEAS = ["VW AG", "671ZRZ0000001V", "Made in Mexico", "T2GJ204", "Airbag Module APM2/1",
          "AutolivB.V.&Co.KG", "Emmy-Noether-Str.7a", "85221Dachau", "10.04.31", "ZRZ02S2GJ880204J"]


class LectorFalso:
    def __init__(self):
        self.leidas = []

    def leer(self, ruta):
        self.leidas.append(ruta)
        return {"es_modulo": True, "part_number": "2GJ.880.204.J", "serial_number": "671 ZRZ0000001V",
                "date": "2031-04-10", "fuerza": {"part_number": "una_sola_lectura"},
                "lineas": [{"texto": t, "caja": {"x": 10, "y": 10 + 20 * i, "w": 100, "h": 15}}
                           for i, t in enumerate(LINEAS)],
                "estampa": {"nivel": "01S", "confianza": 0.8, "texto": "01S"}}


def _fotos():
    return [{"ruta": f"/f/{n}.JPG", "ruta_relativa": f"PHOTOS/VOR/{n}.JPG", "fase": "VOR"} for n in ("A", "B", "C")]


def test_solo_se_leen_las_fotos_con_ganchos_de_la_etiqueta():
    textos = {"PHOTOS/VOR/A.JPG": "Airbag Module APM\nAutolm B V Co\nZRZ 02S",
              "PHOTOS/VOR/B.JPG": "foto del tablero 2GJ.857.003.G",
              "PHOTOS/VOR/C.JPG": "85221 Dachau\nVW AG"}
    lector = LectorFalso()
    r = MI.procesar_caso_modulo(CASO, _fotos(), textos, lector=lector)
    assert sorted(lector.leidas) == ["/f/A.JPG", "/f/C.JPG"]
    valores = {(c["clave"], c["valor_normalizado"]) for c in r["candidatos"]}
    assert {("module_part_number", "2GJ.880.204.J"), ("module_serial_number", "671 ZRZ0000001V"),
            ("module_date", "2031-04-10"), ("inflator_supplier", "Autoliv"),
            ("engineering_level", "01S")} <= valores
    fecha = next(c for c in r["candidatos"] if c["clave"] == "module_date")
    assert fecha["valor_original"] == "10.04.31" and fecha["bbox_original"] == [10, 170, 100, 15]
    assert fecha["etiqueta"] == "modulo" and fecha["fuente"] == "etiqueta_modulo"


def test_lector_dedicado_manda_sobre_ocr_generico_y_el_nivel_sigue_propuesto():
    lector = LectorFalso()
    evid = MI.procesar_caso_modulo(CASO, _fotos()[:1], {"PHOTOS/VOR/A.JPG": "Airbag Module\nZRZ 02S"},
                                   lector=lector)["candidatos"]
    evid += fe.extraer_candidatos_texto("Airbag Module APM\n26J.880.204.J\nZRZ 02S 26J880204J",
                                        {"confianza_ocr": .9, "ruta_relativa": "PHOTOS/NACH/G.JPG"}, {})
    campos = fe.consolidar_caso(CASO, evid)["campos"]
    assert campos["module_part_number"]["valor"] == "2GJ.880.204.J"
    assert campos["module_date"]["valor"] == "2031-04-10"       # una foto, pero ES la etiqueta del módulo
    assert campos["inflator_supplier"]["valor"] == "Autoliv"
    assert campos["engineering_level"]["valor"] is None
    assert campos["engineering_level"]["valor_propuesto"] == "01S"   # la estampa, no el «ZRZ 02S»


def test_autoliv_por_la_direccion_aunque_la_marca_sea_ilegible():
    valores = {(e["clave"], e["valor_normalizado"]) for e in fe.extraer_candidatos_texto(
        "Airbag Module APM2/1\nA#t%l B V\nEmmy-Noether-Str.7a\n85221 Dachau",
        {"confianza_ocr": .9, "ruta_relativa": "PHOTOS/VOR/D.JPG"}, {})}
    assert ("inflator_supplier", "Autoliv") in valores


def test_zrz_impreso_no_es_la_columna_k():
    valores = {(e["clave"], e["valor_normalizado"]) for e in fe.extraer_candidatos_texto(
        "Airbag Module APM2/1\nZRZ 02S 2GJ 880 204 J", {"confianza_ocr": .9, "ruta_relativa": "X.JPG"}, {})}
    assert not any(c == "engineering_level" for c, _ in valores)


def test_constantes_del_proyecto_estan_en_config_y_marcadas_pendientes():
    from configuracion import cargar_config
    import inspect
    import validacion
    cfg = cargar_config()["empresarial"]["constantes_proyecto"]
    assert cfg == {"dashboard_supplier": "FORVIA", "laser_opening": "3mm ¨C¨"}
    fuente = inspect.getsource(validacion.validar_lote_empresarial)
    assert "constante_proyecto" in fuente and "PENDIENTE" in fuente
