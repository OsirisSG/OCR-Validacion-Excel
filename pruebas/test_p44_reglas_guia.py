"""P44 · Reglas reforzadas con la guía de posición de códigos y las fotos de criterio del usuario.

Los textos son la FORMA que el OCR devolvió sobre esas fotos, con números y fechas sintéticos
(año 2031, series inventadas): ninguna prueba depende de un valor del Book corregido.
"""
from __future__ import annotations

import inspect

import cv2
import numpy as np

import buscar_mas as B
import flujo_empresarial as fe
import tablero_integracion as TI
from utilidades import tablero_anclas as A

IMAGEN = {"confianza_ocr": 0.9, "ruta_relativa": "PHOTOS/NACH/IMG_1.JPG"}
MODULO = ("VW AG | 671ZRZ0000001V | Made in Mexico | T2GJ204 | Airbag Module APM2/1 | "
          "AutolivB.V.&Co.KG | 12.03.31 | GERMANY | ZRZ07S2GJ880204J | 651538300")
STICKER = "N/P:497653401XBS | 17/02/2031 | 40539291 | 2:19:59PM | INT316 IP Part W Barcode Inj Black ST"
STICKER_CON_MANUSCRITO = "LUZ MARIA 85 | MATOK 1ERTUR | 17/FEB0/2031 | " + STICKER


def _valores(texto, perfil=None):
    return {(c["clave"], c["valor_normalizado"]) for c in fe.extraer_candidatos_texto(
        texto.replace(" | ", "\n"), IMAGEN, {"perfil_extraccion": perfil or {}})}


# ----------------------------------------------------------------------------- pestaña azul
def _etiqueta_con(pieza):
    img = np.full((300, 500, 3), 60, np.uint8)               # fondo oscuro (plástico)
    cv2.rectangle(img, (100, 100), (330, 180), (245, 245, 245), -1)   # etiqueta blanca
    pieza(img)
    return img


def test_pestana_azul_existe_y_detecta_la_pestana_pegada_a_la_etiqueta():
    assert hasattr(A, "pestanas_azules"), "tablero_campos.pista_de_tablero la necesita"
    img = _etiqueta_con(lambda i: cv2.rectangle(i, (330, 95), (360, 185), (200, 80, 0), -1))
    pestanas = A.pestanas_azules(img)
    assert len(pestanas) == 1 and pestanas[0].tipo == "pestana_azul"


def test_hilo_azul_y_tela_azul_sin_etiqueta_no_son_pestana():
    hilo = _etiqueta_con(lambda i: cv2.line(i, (400, 20), (402, 290), (200, 80, 0), 3))
    assert A.pestanas_azules(hilo) == []
    tela = np.full((300, 500, 3), 60, np.uint8)
    cv2.rectangle(tela, (200, 50), (260, 250), (200, 80, 0), -1)   # azul sin etiqueta blanca
    assert A.pestanas_azules(tela) == []


def test_pista_de_tablero_ya_no_revienta():
    from utilidades import tablero_campos as T
    img = _etiqueta_con(lambda i: cv2.rectangle(i, (330, 95), (360, 185), (200, 80, 0), -1))
    pista = T.pista_de_tablero(img)
    assert pista["pestanas"] and pista["algo"] is True


# ----------------------------------------------------------------------------- clase de pegatina
def test_sticker_del_tablero_con_mat_ok_manuscrito_sigue_siendo_tablero():
    assert B.clase_de_pegatina(STICKER_CON_MANUSCRITO) == "tablero"
    assert B.clase_de_pegatina(STICKER) == "tablero"


def test_marcas_de_proveedor_y_modulo_siguen_valiendo():
    assert B.clase_de_pegatina("Lieferant: 12 Farbe: 06/02/2031 10:00") == "proveedor"
    assert B.clase_de_pegatina("MAT: 4711 06/02/2031 10:00") == "proveedor"
    assert B.clase_de_pegatina(MODULO) == "modulo"


def test_el_np_del_tablero_con_2gj_ya_no_parece_del_modulo():
    assert not B.parece_del_modulo("052 3KVJ0000ABC 2GJ 857 003 G")
    assert B.parece_del_modulo("2GJ 880 204 J 12.03.31")


# ----------------------------------------------------------------------------- etiqueta del módulo
def test_etiqueta_del_modulo_da_fecha_np_proveedor_y_nivel_con_perfil_declarado():
    valores = _valores(MODULO, {"formato_fecha_modulo": "DMY"})
    assert ("module_date", "2031-03-12") in valores
    assert ("module_part_number", "2GJ.880.204.J") in valores
    assert ("inflator_supplier", "Autoliv") in valores
    # P49 · el «ZRZ 07S» impreso NO es la columna K (K = estampa amarilla): sólo queda para auditoría
    assert ("_nivel_texto_zrz", "07S") in valores
    assert not any(c == "engineering_level" for c, _ in valores)
    assert ("module_serial_number", "671 ZRZ0000001V") in valores


def test_sin_perfil_la_fecha_del_modulo_sigue_ambigua():
    valores = _valores(MODULO)
    assert not any(clave == "module_date" for clave, _ in valores)
    assert ("_fecha_ambigua", "12.03.31") in valores


def test_formato_del_modulo_no_se_aplica_a_otras_etiquetas():
    valores = _valores("Prueba 03.04.31", {"formato_fecha_modulo": "DMY"})
    assert not any(clave in {"module_date", "dashboard_date", "test_date"} for clave, _ in valores)


def test_sticker_del_tablero_se_reconoce_por_sus_marcas():
    assert ("dashboard_date", "2031-02-17") in _valores(STICKER)


def test_texto_con_norte_ya_no_inventa_una_serie():
    assert not any(clave.endswith("serial_number") or clave == "_serial_por_identificar"
                   for clave, _ in _valores("Circuito ElMarguesNorte#257624"))


def test_nivel_del_modulo_sigue_sin_publicarse_solo():
    caso = {"case_key": "P|1ST|x", "project_id": "P", "tipo_st": "1ST", "ruta_relativa": "x",
            "metadata_ruta": {}}
    evid = fe.extraer_candidatos_texto(MODULO.replace(" | ", "\n"), IMAGEN, {})
    evid += fe.extraer_candidatos_texto(MODULO.replace(" | ", "\n"),
                                        {**IMAGEN, "ruta_relativa": "PHOTOS/VOR/IMG_2.JPG"}, {})
    assert fe.consolidar_caso(caso, evid)["campos"]["engineering_level"]["valor"] is None


# ----------------------------------------------------------------------------- OCR genérico → P42
class _LectorQueNoDebeLeer:
    errores_ocr = 0
    ultimo_error = ""

    def __init__(self):
        self.llamadas = 0

    def cargar(self, ruta):
        self.llamadas += 1
        return ruta

    def pista(self, imagen):
        return {"algo": False}

    def leer(self, imagen, pista):
        raise AssertionError("no debería leer")

    def fechas(self, imagen):
        self.llamadas += 1
        return []

    guardar_recorte = staticmethod(lambda d, r: False)


def _caso_y_fotos():
    caso = {"case_key": "P|1ST|HT/232564 X", "project_id": "P", "tipo_st": "1ST", "nombre": "x",
            "metadata_ruta": {"test_number": "232564"}}
    fotos = [{"ruta": f"/f/{r}", "ruta_relativa": r, "fase": "NACH"}
             for r in ("PHOTOS/NACH/IMG_1.JPG", "PHOTOS/NACH/IMG_2.JPG")]
    return caso, fotos


def test_lectura_del_ocr_generico_cierra_la_fecha_sin_segunda_pasada():
    caso, fotos = _caso_y_fotos()
    genericos = fe.extraer_candidatos_texto(STICKER.replace(" | ", "\n"), IMAGEN, {})
    lecturas = TI.lecturas_desde_ocr_generico(genericos, {"PHOTOS/NACH/IMG_1.JPG": STICKER})
    assert lecturas["dashboard_date"][0]["clase"] == "tablero"
    lector = _LectorQueNoDebeLeer()
    resultado = TI.procesar_caso_tablero(caso, fotos, TI.OpcionesTablero(activar=True),
                                         fabrica_lector=lambda: lector, lecturas_genericas=lecturas)
    assert resultado["campos"]["dashboard_date"]["valor"] == "2031-02-17"
    assert resultado["segunda_pasada"]["ejecutada"] is False
    assert resultado["cobertura"]["lecturas_ocr_generico"] == 1


def test_lectura_generica_de_otra_clase_no_cierra_sola():
    caso, fotos = _caso_y_fotos()
    texto = "Lieferant: 1 | 06/02/2031 | 10:00 | Dashboard"
    genericos = fe.extraer_candidatos_texto(texto.replace(" | ", "\n"), IMAGEN, {})
    lecturas = TI.lecturas_desde_ocr_generico(genericos, {"PHOTOS/NACH/IMG_1.JPG": texto})
    resultado = TI.procesar_caso_tablero(caso, fotos, TI.OpcionesTablero(activar=True),
                                         fabrica_lector=lambda: _LectorQueNoDebeLeer(),
                                         lecturas_genericas=lecturas)
    assert resultado["campos"]["dashboard_date"]["estado"] != "consenso"


def test_segunda_pasada_mira_primero_las_fotos_con_pinta_de_fecha():
    caso, fotos = _caso_y_fotos()
    vistas = []

    class Lector(_LectorQueNoDebeLeer):
        def fechas(self, imagen):
            vistas.append(imagen)
            return []

    TI.procesar_caso_tablero(caso, fotos, TI.OpcionesTablero(activar=True),
                             fabrica_lector=lambda: Lector(),
                             prioridad_segunda={"PHOTOS/NACH/IMG_2.JPG": 2})
    assert vistas[0] == "/f/PHOTOS/NACH/IMG_2.JPG" and len(vistas) == 2


# ----------------------------------------------------------------------------- caché
def test_cache_reutiliza_por_contenido_y_se_invalida_si_cambia_la_foto(tmp_path):
    foto = tmp_path / "IMG_1.JPG"
    foto.write_bytes(b"uno")
    caso = {"case_key": "P|1ST|c", "project_id": "P", "tipo_st": "1ST", "nombre": "c",
            "metadata_ruta": {}}
    fotos = [{"ruta": str(foto), "ruta_relativa": "PHOTOS/NACH/IMG_1.JPG", "fase": "NACH"}]
    cache = TI.CacheLecturasP42(tmp_path / "cache.sqlite3")
    primero = _LectorQueNoDebeLeer()
    TI.procesar_caso_tablero(caso, fotos, TI.OpcionesTablero(activar=True),
                             fabrica_lector=lambda: primero, cache=cache)
    segundo = _LectorQueNoDebeLeer()
    resultado = TI.procesar_caso_tablero(caso, fotos, TI.OpcionesTablero(activar=True),
                                         fabrica_lector=lambda: segundo, cache=cache)
    assert primero.llamadas > 0 and segundo.llamadas == 0
    assert resultado["cobertura"]["desde_cache"] == 2          # pista + fechas
    foto.write_bytes(b"dos")
    tercero = _LectorQueNoDebeLeer()
    TI.procesar_caso_tablero(caso, fotos, TI.OpcionesTablero(activar=True),
                             fabrica_lector=lambda: tercero, cache=cache)
    assert tercero.llamadas > 0
    cache.cerrar()


# ----------------------------------------------------------------------------- legacy
def test_validar_lote_legacy_acepta_contenido():
    import validacion
    assert "contenido" in inspect.signature(validacion.validar_lote).parameters


# ============================================================================ P45 · respuestas
def _estados_serie(lecturas):
    estados = {"dashboard_serial_number": {"estado": "consenso", "valor": "052 3KVJ0000AB1",
                                           "votos": {"052 3KVJ0000AB1": len(lecturas)}}}
    TI.aplicar_regla_ultimo_caracter(estados, {"dashboard_serial_number": lecturas})
    return estados["dashboard_serial_number"]


def test_serie_solo_datamatrix_va_a_duda_con_variante_sin_ultimo_caracter():
    estado = _estados_serie([{"valor": "052 3KVJ0000AB1", "origen": "datamatrix", "foto": "a"}])
    assert estado["estado"] == "en_duda" and estado["valor"] is None
    assert estado["variantes"] == ["052 3KVJ0000AB1", "052 3KVJ0000AB"]


def test_serie_datamatrix_mas_impreso_igual_se_publica():
    estado = _estados_serie([{"valor": "052 3KVJ0000AB1", "origen": "datamatrix", "foto": "a"},
                             {"valor": "052 3KVJ0000AB1", "origen": "052 3KVJ0000AB1", "ruta_relativa": "b"}])
    assert estado["estado"] == "consenso"


def test_serie_impresa_en_dos_fotos_sin_datamatrix_se_publica():
    estado = _estados_serie([{"valor": "052 3KVJ0000AB1", "origen": "x", "ruta_relativa": "a"},
                             {"valor": "052 3KVJ0000AB1", "origen": "x", "ruta_relativa": "b"}])
    assert estado["estado"] == "consenso"


def test_etiqueta_de_inspeccion_mat_ok_no_es_fecha_del_tablero():
    assert B.clase_de_pegatina("LILI 307 | MAT OK 1er TUR | 15/FEB0/2031") == "inspeccion"


def test_fecha_del_modulo_manda_sobre_prototypes():
    caso = {"case_key": "P|1ST|x", "project_id": "P", "tipo_st": "1ST", "ruta_relativa": "x",
            "metadata_ruta": {}}
    perfil = {"perfil_extraccion": {"formato_fecha_modulo": "DMY"}}
    proto = "VW316PABSS\n2GJ880204J\nPROTOTYPES\n13/03/2031"
    evid = fe.extraer_candidatos_texto(MODULO.replace(" | ", "\n"), IMAGEN, perfil)
    evid += fe.extraer_candidatos_texto(proto, {**IMAGEN, "ruta_relativa": "PHOTOS/VOR/P.JPG"}, perfil)
    fecha = fe.consolidar_caso(caso, evid)["campos"]["module_date"]
    assert (fecha["valor"], fecha["estado"]) == ("2031-03-12", "prioridad_etiqueta_modulo")
    assert fecha["alternativas_prototipo"] == ["2031-03-13"]


def test_dos_prototypes_que_discrepan_siguen_en_conflicto():
    caso = {"case_key": "P|1ST|x", "project_id": "P", "tipo_st": "1ST", "ruta_relativa": "x",
            "metadata_ruta": {}}
    perfil = {"perfil_extraccion": {"formato_fecha_modulo": "DMY"}}
    evid = []
    for i, fecha in enumerate(("13/03/2031", "14/03/2031")):
        evid += fe.extraer_candidatos_texto(f"VW316PABSS\nPROTOTYPES\n{fecha}",
                                            {**IMAGEN, "ruta_relativa": f"{i}.jpg"}, perfil)
    assert fe.consolidar_caso(caso, evid)["campos"]["module_date"]["valor"] is None


def test_vocabulario_del_libro_sale_como_opcion_y_nunca_como_valor(tmp_path):
    from openpyxl import Workbook

    from utilidades.dudas_y_opciones import construir_dudas, lecturas_desde_validacion
    from utilidades.vocabulario_libro import vocabulario
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Versuchsmatrix"
    for fila, motivo in ((8, "IT XYZ"), (9, "IT XYZ"), (10, "OTRO")):
        hoja.cell(fila, 3).value = f"23254{fila - 8}"
        hoja.cell(fila, 2).value = motivo
    ruta = tmp_path / "historico.xlsx"
    libro.save(ruta)
    voc = vocabulario([ruta])
    assert voc["test_reason"] == {"IT XYZ": 2, "OTRO": 1}
    lecturas, _ = lecturas_desde_validacion({"resultados": [
        {"case_key": "k", "test_number": "232564", "candidatos": [],
         "tablero_p42": {"campos": {"dashboard_serial_number": {
             "votos": {"052 3KVJ0000AB1": 1}, "variantes": ["052 3KVJ0000AB1", "052 3KVJ0000AB"]}}}}]}, voc)
    dudas = construir_dudas({"232564": {}}, lecturas,
                            campos=("test_reason", "dashboard_serial_number"))
    motivo = next(d for d in dudas if d["campo"] == "test_reason")
    assert {o["valor"] for o in motivo["opciones"]} >= {"IT XYZ", "OTRO", None}
    assert all(o["fuente"] in {"vocabulario_libro", "no_lo_tengo"} for o in motivo["opciones"])
    serie = next(d for d in dudas if d["campo"] == "dashboard_serial_number")
    assert {"052 3KVJ0000AB1", "052 3KVJ0000AB"} <= {o["valor"] for o in serie["opciones"]}


def test_serie_en_duda_por_discrepancia_ofrece_la_variante_sin_ultimo_caracter():
    estados = {"dashboard_serial_number": {"estado": "en_duda", "valor": None,
                                           "valor_propuesto": "052 3KVJ0000AB1"}}
    TI.aplicar_regla_ultimo_caracter(estados, {"dashboard_serial_number": [
        {"valor": "052 3KVJ0000AB1", "origen": "datamatrix"},
        {"valor": "052 3KVJ0000ABT", "origen": "impreso_junto_a_datamatrix"}]})
    assert "052 3KVJ0000AB" in estados["dashboard_serial_number"]["variantes"]
