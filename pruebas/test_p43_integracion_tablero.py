"""P43 · Integración de la lectura P42 del tablero en la corrida normal.

Todas las pruebas usan un lector SINTÉTICO inyectado (sin fotos privadas, sin OCR real) y
fechas sintéticas (año 2031) que NO están en el Book corregido: si alguna prueba pasara
copiando la referencia, fallaría.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

import evidencia_tablero as E
import flujo_empresarial as fe
import tablero_integracion as TI

RAIZ_EXPEDIENTE = Path(__file__).resolve().parents[2]
LIBRO_V51 = RAIZ_EXPEDIENTE / "libros" / "versionV16_0_51.xlsx"

PISTA = {"algo": True, "etiqueta": True, "codigos": [{"area": 100, "x": 0, "y": 0, "w": 1, "h": 1}],
         "pestanas": [], "blanco": 0.2, "grabado": False, "datamatrix": False}
SIN_PISTA = {"algo": False}


class LectorFalso:
    """Guion por ruta absoluta: pista, campos de la 1.ª pasada, fechas de la 2.ª y errores."""

    def __init__(self, guion: dict):
        self.guion = guion
        self.errores_ocr = 0
        self.ultimo_error = ""
        self.leidas: list[str] = []
        self.segunda: list[str] = []

    def cargar(self, ruta):
        dato = self.guion.get(ruta, {})
        return None if dato.get("no_legible") else ruta

    def pista(self, imagen):
        return self.guion.get(imagen, {}).get("pista", SIN_PISTA)

    def leer(self, imagen, pista):
        dato = self.guion.get(imagen, {})
        self.leidas.append(imagen)
        if dato.get("errores"):
            self.errores_ocr += dato["errores"]
            self.ultimo_error = "RuntimeError: onnx falló"
        if dato.get("excepcion"):
            raise RuntimeError(dato["excepcion"])
        return dict(dato.get("campos") or {})

    def fechas(self, imagen):
        dato = self.guion.get(imagen, {})
        self.segunda.append(imagen)
        if dato.get("errores_segunda"):
            self.errores_ocr += dato["errores_segunda"]
        return list(dato.get("fechas") or [])

    @staticmethod
    def guardar_recorte(destino, recorte):
        return False


def _caso(numero="232564", etapa="1ST", base="/fotos lote/HT"):
    nombre = f"{numero} RDW OGL HT"
    return {"case_key": f"Proyecto X|{etapa}|HT/{nombre}", "project_id": "Proyecto X",
            "tipo_st": etapa, "nombre": nombre, "ruta": f"{base}/{nombre}",
            "ruta_relativa": f"HT/{nombre}", "metadata_ruta": {"test_number": numero}}


def _fotos(caso, relativas):
    return [{"ruta": f"{caso['ruta']}/PHOTOS/{r}", "ruta_relativa": f"PHOTOS/{r}",
             "fase": r.split("/")[0], "tor": None} for r in relativas]


def _ruta(caso, relativa):
    return f"{caso['ruta']}/PHOTOS/{relativa}"


def _fecha(valor, origen="", **extra):
    return {"dashboard_date": {"valor": valor, "confianza": 0.8, "origen": origen or valor, **extra}}


def _procesar(caso, fotos, guion, **opciones):
    lector = LectorFalso(guion)
    resultado = TI.procesar_caso_tablero(
        caso, fotos, TI.OpcionesTablero(activar=True, **opciones),
        fabrica_lector=lambda: lector)
    return resultado, lector


def _consolidar(caso, resultado, otras=()):
    consolidado = fe.consolidar_caso(caso, [*otras, *resultado["candidatos"]], requeridos=set())
    TI.anotar_consolidado(consolidado["campos"], resultado)
    resultado["dudas"] = TI.dudas_finales(caso, resultado, consolidado["campos"])
    return consolidado


# ----------------------------------------------------------------------------- 1. sin fotos
def test_caso_sin_fotos_deja_dudas_explicitas_y_nunca_sin_dato():
    caso = _caso()
    resultado, _ = _procesar(caso, [], {})
    assert resultado["estado"] == "sin_fotos"
    assert {e["estado"] for e in resultado["campos"].values()} == {"sin_fotos"}
    consolidado = _consolidar(caso, resultado)
    for campo in TI.CAMPOS:
        assert consolidado["campos"][campo]["valor"] is None
    assert {d["campo"] for d in resultado["dudas"]} == set(TI.CAMPOS)
    assert all(d["motivo"] == "sin_fotos" for d in resultado["dudas"])


# ----------------------------------------------------------------------------- 2. foto sin ancla
def test_foto_sin_ancla_no_cuenta_como_examinada_por_la_primera_pasada():
    caso = _caso()
    fotos = _fotos(caso, ["NACH/IMG_0001.JPG"])
    resultado, lector = _procesar(caso, fotos, {}, segunda_pasada=False)
    assert lector.leidas == []                               # sin pista no hay OCR
    assert resultado["cobertura"]["por_foto"]["PHOTOS/NACH/IMG_0001.JPG"]["estado"] == "sin_pista"
    assert resultado["cobertura"]["examinadas"] == 0
    assert len(resultado["cobertura"]["pendientes"]) == 1
    # sin examinar NO es «sin dato»
    assert resultado["campos"]["dashboard_date"]["estado"] == "pendiente_busqueda_incompleta"


def test_foto_sin_ancla_examinada_en_segunda_pasada_si_permite_sin_dato_de_fecha():
    caso = _caso()
    fotos = _fotos(caso, ["NACH/IMG_0001.JPG"])
    resultado, lector = _procesar(caso, fotos, {})
    assert lector.segunda == [_ruta(caso, "NACH/IMG_0001.JPG")]
    assert resultado["campos"]["dashboard_date"]["estado"] == "sin_dato_tras_busqueda"
    # la segunda pasada sólo busca fechas: la serie sigue pendiente, no «sin dato»
    assert resultado["campos"]["dashboard_serial_number"]["estado"] == "pendiente_busqueda_incompleta"


# ----------------------------------------------------------------------------- 3. OCR ausente / error
def test_ocr_no_disponible_deja_todo_pendiente_con_motivo():
    caso = _caso()
    fotos = _fotos(caso, ["NACH/A.JPG", "VOR/B.JPG"])

    def sin_ocr():
        raise ModuleNotFoundError("No module named 'rapidocr_onnxruntime'")

    resultado = TI.procesar_caso_tablero(caso, fotos, TI.OpcionesTablero(activar=True),
                                         fabrica_lector=sin_ocr)
    assert resultado["estado"] == "ocr_no_disponible"
    assert "rapidocr" in resultado["motivo"]
    assert len(resultado["cobertura"]["pendientes"]) == 2
    assert all(e["estado"] == "ocr_no_disponible" for e in resultado["campos"].values())
    assert any(a["codigo"] == "TABLERO_P42_OCR_NO_DISPONIBLE" for a in resultado["alertas"])


def test_error_de_ocr_no_se_confunde_con_foto_sin_texto():
    caso = _caso()
    fotos = _fotos(caso, ["NACH/A.JPG"])
    guion = {_ruta(caso, "NACH/A.JPG"): {"pista": PISTA, "errores": 3}}
    resultado, _ = _procesar(caso, fotos, guion, segunda_pasada=False)
    foto = resultado["cobertura"]["por_foto"]["PHOTOS/NACH/A.JPG"]
    assert foto["estado"] == "error_ocr" and "onnx" in foto["motivo"]
    assert resultado["cobertura"]["examinadas"] == 0
    assert resultado["campos"]["dashboard_serial_number"]["fotos_con_error"] == 1
    assert resultado["campos"]["dashboard_serial_number"]["estado"] == "pendiente_busqueda_incompleta"


def test_error_de_primera_pasada_no_se_borra_al_reexaminar_fechas():
    caso = _caso()
    fotos = _fotos(caso, ["NACH/A.JPG"])
    guion = {_ruta(caso, "NACH/A.JPG"): {"pista": PISTA, "errores": 1}}
    resultado, lector = _procesar(caso, fotos, guion)
    assert _ruta(caso, "NACH/A.JPG") in lector.segunda           # la 2.ª pasada la reintenta
    foto = resultado["cobertura"]["por_foto"]["PHOTOS/NACH/A.JPG"]
    assert (foto["primera"], foto["estado"]) == ("error_ocr", "segunda_sin_fecha")
    assert resultado["campos"]["dashboard_date"]["estado"] == "sin_dato_tras_busqueda"
    serie = resultado["campos"]["dashboard_serial_number"]
    assert serie["estado"] == "pendiente_busqueda_incompleta" and serie["fotos_con_error"] == 1
    assert [e["ruta"] for e in resultado["cobertura"]["errores"]] == ["PHOTOS/NACH/A.JPG"]


def test_excepcion_del_lector_y_foto_ilegible_quedan_como_error_con_motivo():
    caso = _caso()
    fotos = _fotos(caso, ["NACH/A.JPG", "NACH/B.JPG", "NACH/C.tif"])
    guion = {_ruta(caso, "NACH/A.JPG"): {"pista": PISTA, "excepcion": "memoria"},
             _ruta(caso, "NACH/B.JPG"): {"no_legible": True}}
    resultado, _ = _procesar(caso, fotos, guion, segunda_pasada=False)
    por_foto = resultado["cobertura"]["por_foto"]
    assert por_foto["PHOTOS/NACH/A.JPG"]["estado"] == "error_lector"
    assert por_foto["PHOTOS/NACH/B.JPG"]["estado"] == "no_legible"
    assert por_foto["PHOTOS/NACH/C.tif"]["estado"] == "formato_no_soportado"
    assert len(resultado["cobertura"]["errores"]) == 2
    assert len(resultado["cobertura"]["descartadas"]) == 1


def test_pausa_o_cancelacion_no_se_traga():
    class Cancelado(RuntimeError):
        pass

    def control():
        raise Cancelado("el usuario canceló")

    caso = _caso()
    with pytest.raises(Cancelado):
        TI.ejecutar_seguro(caso, _fotos(caso, ["NACH/A.JPG"]), TI.OpcionesTablero(activar=True),
                           fabrica_lector=lambda: LectorFalso({}), control=control)


def test_fallo_interno_inesperado_no_tumba_la_corrida():
    caso = _caso()

    def roto():
        class Roto(LectorFalso):
            def pista(self, imagen):
                return None          # contrato roto: provoca un AttributeError interno
        return Roto({})

    resultado = TI.ejecutar_seguro(caso, _fotos(caso, ["NACH/A.JPG"]),
                                   TI.OpcionesTablero(activar=True), fabrica_lector=roto)
    assert resultado["estado"] == "error"
    assert resultado["cobertura"]["pendientes"]


# ----------------------------------------------------------------------------- 4. clases de fecha
def test_fecha_de_modulo_y_proveedor_no_compiten_con_el_sticker_del_tablero():
    caso = _caso()
    fotos = _fotos(caso, ["NACH/T1.JPG", "NACH/P1.JPG", "NACH/P2.JPG", "NACH/M1.JPG"])
    guion = {
        _ruta(caso, "NACH/P1.JPG"): {"fechas": [{"valor": "2031-02-06", "clase": "proveedor",
                                                  "ancla": "codigo", "texto": "LIEFERANT 06/02/2031"}]},
        _ruta(caso, "NACH/P2.JPG"): {"fechas": [{"valor": "2031-02-06", "clase": "proveedor",
                                                  "ancla": "codigo", "texto": "LIEFERANT 06/02/2031"}]},
        _ruta(caso, "NACH/M1.JPG"): {"fechas": [{"valor": "2031-01-11", "clase": "desconocida",
                                                  "ancla": "codigo", "texto": "11/01/2031"}]},
        _ruta(caso, "NACH/T1.JPG"): {"fechas": [{"valor": "2031-02-17", "clase": "tablero",
                                                  "ancla": "etiqueta_blanca",
                                                  "texto": "17/02/2031 10:32 N/P 2GJ857003"}]},
    }
    resultado, _ = _procesar(caso, fotos, guion)
    fecha = resultado["campos"]["dashboard_date"]
    assert fecha["estado"] == "consenso" and fecha["valor"] == "2031-02-17"
    publicables = [c for c in resultado["candidatos"]
                   if c["clave"] == "dashboard_date" and not c["requiere_confirmacion_manual"]]
    assert [c["valor_normalizado"] for c in publicables] == ["2031-02-17"]
    consolidado = _consolidar(caso, resultado)
    assert consolidado["campos"]["dashboard_date"]["valor"] == "2031-02-17"
    assert consolidado["campos"]["dashboard_date"]["estado"] == "extraido_tablero_p42"


# ----------------------------------------------------------------------------- 5. dos fechas
def test_dos_fechas_contradictorias_del_tablero_quedan_en_duda_sin_publicar():
    caso = _caso()
    fotos = _fotos(caso, ["NACH/A.JPG", "NACH/B.JPG"])
    guion = {
        _ruta(caso, "NACH/A.JPG"): {"fechas": [{"valor": "2031-02-17", "clase": "tablero",
                                                 "texto": "17/02/2031 10:32"}]},
        _ruta(caso, "NACH/B.JPG"): {"fechas": [{"valor": "2031-02-18", "clase": "tablero",
                                                 "texto": "18/02/2031 10:32"}]},
    }
    resultado, _ = _procesar(caso, fotos, guion)
    assert resultado["campos"]["dashboard_date"]["estado"] == "en_duda"
    consolidado = _consolidar(caso, resultado)
    assert consolidado["campos"]["dashboard_date"]["valor"] is None
    duda = next(d for d in resultado["dudas"] if d["campo"] == "dashboard_date")
    assert {o["valor"] for o in duda["opciones"]} == {"2031-02-17", "2031-02-18", None}


# ----------------------------------------------------------------------------- 6. segunda pasada
def test_regresion_232564_segunda_pasada_encuentra_foto_omitida_con_nombre_repetido():
    """Estructura de 232564 SIN su fecha: la foto omitida (sin pestaña) se llama igual que otra
    de VOR. Con el `ya_miradas` por nombre de P42 nunca se habría examinado."""
    caso = _caso("232564")
    fotos = _fotos(caso, ["VOR/IMG_4408.JPG", "NACH/IMG_4408.JPG", "NACH/IMG_1.JPG",
                          "NACH/IMG_2.JPG", "NACH/IMG_3.JPG", "NACH/IMG_4.JPG"])
    guion = {
        _ruta(caso, "VOR/IMG_4408.JPG"): {"pista": PISTA, "campos": {
            "dashboard_serial_number": {"valor": "052 3KVJ0099ZZ", "confianza": 0.9}}},
        _ruta(caso, "NACH/IMG_1.JPG"): {"pista": PISTA, "campos": _fecha("2031-01-11")},
        _ruta(caso, "NACH/IMG_2.JPG"): {"pista": PISTA, "campos": _fecha("2031-02-06")},
        _ruta(caso, "NACH/IMG_3.JPG"): {"pista": PISTA, "campos": _fecha("2031-02-06")},
        _ruta(caso, "NACH/IMG_4.JPG"): {"pista": PISTA, "campos": _fecha("2031-01-11")},
        _ruta(caso, "NACH/IMG_4408.JPG"): {"fechas": [{
            "valor": "2031-02-17", "giro": 0, "ancla": "etiqueta_blanca", "clase": "tablero",
            "texto": "17/02/2031 10:32 N/P 2GJ857003"}]},
    }
    resultado, lector = _procesar(caso, fotos, guion)
    assert resultado["segunda_pasada"]["ejecutada"] is True
    assert _ruta(caso, "NACH/IMG_4408.JPG") in lector.segunda
    assert resultado["cobertura"]["por_foto"]["PHOTOS/NACH/IMG_4408.JPG"]["estado"] == "segunda_con_fecha"
    assert resultado["campos"]["dashboard_date"]["valor"] == "2031-02-17"
    sostiene = [c for c in resultado["candidatos"]
                if c["clave"] == "dashboard_date" and c["estado_p42"] == "consenso"]
    assert [c["imagen"] for c in sostiene] == ["PHOTOS/NACH/IMG_4408.JPG"]


def test_segunda_pasada_con_presupuesto_agotado_deja_pendientes_con_motivo():
    caso = _caso()
    fotos = _fotos(caso, [f"NACH/{i}.JPG" for i in range(5)])
    tiempos = iter([0.0, 0.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0])
    lector = LectorFalso({})
    resultado = TI.procesar_caso_tablero(
        caso, fotos, TI.OpcionesTablero(activar=True, presupuesto_segunda_s=10),
        fabrica_lector=lambda: lector, reloj=lambda: next(tiempos))
    assert resultado["segunda_pasada"]["presupuesto_agotado"] is True
    estados = {d["estado"] for d in resultado["cobertura"]["por_foto"].values()}
    assert "pendiente_limite_segunda" in estados
    assert resultado["campos"]["dashboard_date"]["estado"] == "pendiente_busqueda_incompleta"


# ----------------------------------------------------------------------------- 7. consenso
def test_consenso_completo_nunca_fabrica_una_fecha_que_nadie_leyo():
    lecturas = [{"valor": "2031-04-11", "foto": "a", "carpeta": "N", "confianza": .9},
                {"valor": "2031-05-06", "foto": "b", "carpeta": "N", "confianza": .9},
                {"valor": "2031-05-17", "foto": "c", "carpeta": "N", "confianza": .9}]
    fabricado = E.consensuar(lecturas)["valor"]          # el voto por posición antiguo
    assert fabricado not in {l["valor"] for l in lecturas}  # demuestra el peligro (2031-05-11)
    resultado, _ = E.cerrar_registro({"lecturas": {"dashboard_date": lecturas}}, "x")
    assert resultado["dashboard_date"] in {l["valor"] for l in lecturas}
    assert resultado["dudoso"]["dashboard_date"] is True


def test_dos_lecturas_de_la_misma_foto_no_son_dos_votos():
    misma = [{"valor": "2031-05-17", "foto": "IMG_1.JPG", "carpeta": "PHOTOS/NACH", "confianza": .9},
             {"valor": "2031-05-17", "foto": "IMG_1.JPG", "carpeta": "PHOTOS/NACH", "confianza": .8}]
    resultado, _ = E.cerrar_registro({"lecturas": {"dashboard_date": misma}}, "x")
    assert resultado["dudoso"]["dashboard_date"] is True          # 1 voto de 2 necesarios
    # y en NACH/VOR con el mismo nombre sí son dos fotos
    distintas = [dict(misma[0]), dict(misma[1], carpeta="PHOTOS/VOR")]
    resultado, _ = E.cerrar_registro({"lecturas": {"dashboard_date": distintas}}, "x")
    assert resultado["dudoso"]["dashboard_date"] is False


def test_cerrar_registro_equivale_a_cerrar_y_no_funde_con_json_viejo(tmp_path):
    acumulado = {"232564": {"caso": "232564 RDW OGL HT", "fotos": 3, "con_pista": 2, "lecturas": {
        "dashboard_serial_number": [{"valor": "052 3KVJ0099ZZ", "foto": "a", "confianza": .9},
                                    {"valor": "052 3KVJ0099ZZ", "foto": "b", "confianza": .9}]}}}
    parcial = tmp_path / "parcial.json"
    parcial.write_text(json.dumps(acumulado), encoding="utf-8")
    viejo = tmp_path / "evidencia.json"
    viejo.write_text(json.dumps({"232564": {"dashboard_date": "1999-01-01"}}), encoding="utf-8")
    fundido = E.cerrar(parcial, viejo, tmp_path)["232564"]
    limpio, _ = E.cerrar_registro(acumulado["232564"], "232564", tmp_path)
    assert fundido["dashboard_serial_number"] == limpio["dashboard_serial_number"]
    assert fundido["dashboard_date"] == "1999-01-01"            # `cerrar` sí funde (P42)
    assert "dashboard_date" not in limpio                       # la integración no


# ----------------------------------------------------------------------------- 8. trazabilidad
def test_pendientes_visibles_en_trazabilidad_y_dudas():
    from openpyxl import Workbook

    import reporte_bmg as R
    caso = _caso()
    fotos = _fotos(caso, ["NACH/A.JPG", "NACH/B.JPG"])
    guion = {_ruta(caso, "NACH/A.JPG"): {"pista": PISTA, "campos": {
        "dashboard_serial_number": {"valor": "052 3KVJ0099ZZ", "confianza": .9}}}}
    resultado, _ = _procesar(caso, fotos, guion, segunda_pasada=False)
    consolidado = _consolidar(caso, resultado)
    libro = Workbook()
    R._crear_trazabilidad(libro, [{**caso, "candidatos": consolidado["candidatos"]}], "es")
    hoja = libro["Trazabilidad"]
    cabecera = [c.value for c in hoja[1]]
    assert cabecera[-4:] == ["Estado evidencia", "Motivo", "Votos", "Confianza"]
    filas = [dict(zip(cabecera, [c.value for c in fila])) for fila in hoja.iter_rows(min_row=2)]
    tablero = [f for f in filas if f["Fuente"] == "tablero_p42"]
    assert {f["Campo"] for f in tablero} == set(TI.CAMPOS)
    pendiente = next(f for f in tablero if f["Campo"] == "dashboard_date")
    assert pendiente["Estado evidencia"] == "pendiente_busqueda_incompleta"
    assert "sin examinar" in pendiente["Motivo"]
    serie = next(f for f in tablero if f["Campo"] == "dashboard_serial_number")
    assert serie["Estado evidencia"] == "en_duda"
    assert {d["campo"] for d in resultado["dudas"]} == set(TI.CAMPOS)


def test_nivel_del_tablero_con_consenso_p42_de_dos_fotos_se_publica():
    # P49 · antes no se publicaba nunca; medido el 12/11: 13/13 lecturas P42 del nivel iguales al libro
    caso = _caso()
    fotos = _fotos(caso, ["NACH/A.JPG", "NACH/B.JPG"])
    nivel = {"dashboard_engineering_level": {"valor": "07S", "confianza": .9}}
    guion = {_ruta(caso, r): {"pista": PISTA, "campos": nivel} for r in ("NACH/A.JPG", "NACH/B.JPG")}
    resultado, _ = _procesar(caso, fotos, guion, segunda_pasada=False)
    assert resultado["campos"]["dashboard_engineering_level"]["estado"] == "consenso"
    campo = _consolidar(caso, resultado)["campos"]["dashboard_engineering_level"]
    assert (campo["valor"], campo["estado"]) == ("07S", "consenso_tablero_p42")


def test_nivel_del_tablero_de_una_sola_foto_sigue_sin_publicarse():
    caso = _caso()
    fotos = _fotos(caso, ["NACH/A.JPG"])
    nivel = {"dashboard_engineering_level": {"valor": "07S", "confianza": .9}}
    resultado, _ = _procesar(caso, fotos, {_ruta(caso, "NACH/A.JPG"): {"pista": PISTA, "campos": nivel}},
                             segunda_pasada=False)
    assert _consolidar(caso, resultado)["campos"]["dashboard_engineering_level"]["valor"] is None
    duda = next(d for d in resultado["dudas"] if d["campo"] == "dashboard_engineering_level")
    assert duda["opciones"][0]["valor"] == "07S"


def test_lectura_en_duda_no_se_rescata_por_el_consenso_ponderado():
    caso = _caso()
    fotos = _fotos(caso, ["NACH/A.JPG", "NACH/B.JPG", "NACH/C.JPG"])
    serie = lambda v: {"dashboard_serial_number": {"valor": v, "confianza": .9}}  # noqa: E731
    guion = {_ruta(caso, "NACH/A.JPG"): {"pista": PISTA, "campos": serie("052 3KVJ0099ZZ")},
             _ruta(caso, "NACH/B.JPG"): {"pista": PISTA, "campos": serie("052 3KVJ0099ZZ")},
             _ruta(caso, "NACH/C.JPG"): {"pista": PISTA, "campos": serie("052 3KVJ0099ZZ1")}}
    resultado, _ = _procesar(caso, fotos, guion, segunda_pasada=False)
    assert resultado["campos"]["dashboard_serial_number"]["estado"] == "en_duda"
    consolidado = _consolidar(caso, resultado)
    assert consolidado["campos"]["dashboard_serial_number"]["valor"] is None


# ----------------------------------------------------------------------------- 9. identidad
def test_dos_etapas_con_el_mismo_numero_no_se_mezclan(tmp_path):
    from utilidades.dudas_y_opciones import lecturas_desde_validacion
    uno, dos = _caso("232564", "1ST"), _caso("232564", "2ST", base="/fotos lote/2ST")
    fotos1, fotos2 = _fotos(uno, ["NACH/A.JPG"]), _fotos(dos, ["NACH/A.JPG"])
    guion = {_ruta(uno, "NACH/A.JPG"): {"fechas": [{"valor": "2031-02-17", "clase": "tablero"}]},
             _ruta(dos, "NACH/A.JPG"): {"fechas": [{"valor": "2031-03-01", "clase": "tablero"}]}}
    r1, _ = _procesar(uno, fotos1, guion)
    r2, _ = _procesar(dos, fotos2, guion)
    assert {c["caso"] for c in r1["candidatos"]} == {uno["case_key"]}
    assert {c["caso"] for c in r2["candidatos"]} == {dos["case_key"]}
    lecturas, ambiguos = lecturas_desde_validacion({"resultados": [
        {"case_key": uno["case_key"], "test_number": "232564", "tablero_p42": r1},
        {"case_key": dos["case_key"], "test_number": "232564", "tablero_p42": r2}]})
    assert ambiguos == ["232564"] and "232564" not in lecturas


def test_herramienta_lista_rechaza_carpetas_con_el_mismo_numero(tmp_path):
    for nombre in ("232564 RDW OGL HT", "232564 NAR OGL HT"):
        (tmp_path / nombre).mkdir()
        (tmp_path / nombre / "a.jpg").write_bytes(b"x")
    with pytest.raises(SystemExit, match="identidad ambigua"):
        E.main(["--fotos", str(tmp_path), "--lista", str(tmp_path / "lista.json")])


# ----------------------------------------------------------------------------- 10. aislamiento
def test_artefactos_viejos_en_la_carpeta_no_se_reutilizan(tmp_path):
    caso = _caso()
    viejo = TI._dir_caso(tmp_path, caso["case_key"])
    viejo.mkdir(parents=True)
    (tmp_path / "lecturas_tablero.json").write_text(json.dumps(
        {"232564": {"lecturas": {"dashboard_date": [{"valor": "1999-01-01", "clase": "tablero"}]}}}))
    (tmp_path / "evidencia_tablero_p42.json").write_text(json.dumps(
        {"232564": {"dashboard_date": "1999-01-01"}}))
    lector = LectorFalso({})
    resultado = TI.procesar_caso_tablero(caso, _fotos(caso, ["NACH/A.JPG"]),
                                         TI.OpcionesTablero(activar=True), dir_corrida=tmp_path,
                                         fabrica_lector=lambda: lector)
    assert "1999-01-01" not in json.dumps(resultado, default=str)


def test_leer_tablero_lote_usa_directorio_unico_y_no_funde_en_silencio(tmp_path, capsys):
    import leer_tablero_lote as L
    uno, dos = L.directorio_de_trabajo(str(tmp_path)), L.directorio_de_trabajo(str(tmp_path))
    assert uno != dos and uno.parent == dos.parent == tmp_path
    existente = tmp_path / "evidencia.json"
    existente.write_text("{}", encoding="utf-8")
    assert L.main(["--fotos", str(tmp_path), "--json", str(existente)]) == 2
    assert "--fundir" in capsys.readouterr().err


def test_rutas_con_espacios_y_no_ascii_se_leen(tmp_path):
    import cv2
    import numpy as np

    import buscar_mas as B
    carpeta = tmp_path / "Programas Base" / "Begründung 232564" / "NACH"
    carpeta.mkdir(parents=True)
    ruta = carpeta / "IMG 4408.JPG"
    cv2.imencode(".jpg", np.full((20, 30, 3), 200, np.uint8))[1].tofile(str(ruta))
    assert B.cargar_foto(ruta).shape == (20, 30, 3)
    assert B.clave_de_foto(ruta, tmp_path / "Programas Base" / "Begründung 232564") == "nach/img 4408.jpg"


def test_auditoria_distingue_nach_y_vor_con_el_mismo_nombre(tmp_path):
    import auditar_cobertura as A
    caso = tmp_path / "232564 RDW OGL HT"
    for fase in ("NACH", "VOR"):
        (caso / fase).mkdir(parents=True)
        (caso / fase / "IMG_4408.JPG").write_bytes(b"x")
    presentes = A.por_caso(tmp_path)["232564"]
    assert set(presentes) == {"nach/img_4408.jpg", "vor/img_4408.jpg"}
    parcial = {"232564": {"lecturas": {"dashboard_serial_number": [
        {"foto": "IMG_4408.JPG", "carpeta": "VOR"}]}}}
    assert A.miradas(parcial, "232564", presentes) == {"vor/img_4408.jpg"}
    # una lectura antigua sin carpeta que case con dos fotos NO se da por mirada
    ambigua = {"232564": {"lecturas": {"x": [{"foto": "IMG_4408.JPG"}]}}}
    assert A.miradas(ambigua, "232564", presentes) == set()
    examinadas, con_lectura = A.examinadas_de_segunda(
        {"examinadas_rutas": ["nach/img_4408.jpg"], "lecturas": []}, presentes)
    assert examinadas == {"nach/img_4408.jpg"} and con_lectura == set()


# ----------------------------------------------------------------------------- 11. guarda EDAG
def _caso_edag(numero="222504"):
    return {"case_key": f"P|1ST|{numero}", "project_id": "P", "tipo_st": "1ST",
            "ruta_relativa": numero, "metadata_ruta": {"test_number": numero}}


def _fecha_prueba(valor="2031-05-28"):
    return [{"clave": "test_date", "valor_normalizado": valor, "valor_original": valor,
             "fuente": "ocr", "imagen": f"NACH/{i}.jpg", "confianza_ocr": .9} for i in range(2)]


def test_edag_sin_perfil_no_deriva_semana():
    salida = fe.consolidar_caso(_caso_edag(), _fecha_prueba("2025-05-28"))
    assert salida["campos"]["week"]["valor"] is None
    assert salida["campos"]["week"]["derivacion_semana"] == "no_aplicable"
    assert "week" in salida["campos_faltantes"]


def test_edag_sin_fecha_no_deriva_semana():
    salida = fe.consolidar_caso(_caso_edag(), [], perfil={"laboratorio": "EDAG"})
    assert salida["campos"]["week"]["valor"] is None


def test_edag_contradictorio_queda_en_conflicto():
    salida = fe.consolidar_caso(_caso_edag("512504"), _fecha_prueba("2025-05-28"),
                                perfil={"laboratorio": "EDAG"})
    assert salida["campos"]["week"]["valor"] is None
    assert "week" in salida["conflictos"]
    otro_anio = fe.consolidar_caso(_caso_edag("222604"), _fecha_prueba("2025-05-28"),
                                   perfil={"laboratorio": "EDAG"})
    assert "week" in otro_anio["conflictos"]


def test_edag_corroborado_publica_la_semana_del_numero():
    salida = fe.consolidar_caso(_caso_edag("222504"), _fecha_prueba("2025-05-28"),
                                perfil={"laboratorio": "EDAG"})
    semana = salida["campos"]["week"]
    assert (semana["valor"], semana["estado"], semana["requiere_revision"]) == (22, "derivado_edag", False)


def test_edag_por_rotulo_explicito_tambien_vale():
    evidencias = fe.extraer_candidatos_texto("EDAG Testlab\n28 MAY 25", {"confianza_ocr": .9,
                                             "ruta_relativa": "a.jpg"}, {})
    evidencias += fe.extraer_candidatos_texto("EDAG Testlab\n28 MAY 25", {"confianza_ocr": .9,
                                              "ruta_relativa": "b.jpg"}, {})
    salida = fe.consolidar_caso(_caso_edag("222504"), evidencias)
    assert salida["campos"]["test_place"]["valor"] == "EDAG"
    assert salida["campos"]["week"]["valor"] == 22


# ----------------------------------------------------------------------------- 12. ruta completa
def _proyecto(tmp_path, numero="232564"):
    raiz = tmp_path / "Proyecto con espacios_1ST"
    caso = raiz / "HT" / f"{numero} RDW OGL HT" / "PHOTOS"
    (caso / "NACH").mkdir(parents=True)
    (caso / "VOR").mkdir()
    for relativa in ("NACH/IMG_4408.JPG", "VOR/IMG_4408.JPG", "NACH/IMG_1.JPG"):
        (caso / relativa).write_bytes(b"imagen sintetica")
    return raiz


def _config(tmp_path, activar=True):
    return {"fase1": {}, "ocr": {}, "normalizacion": {},
            "aprendizaje": {"directorio": str(tmp_path / "aprendizaje")},
            "empresarial": {"perfil_extraccion": {},
                            "archivo_cache": str(tmp_path / "imagenes.sqlite3"),
                            "archivo_avance_ids": str(tmp_path / "avances.json"),
                            "base_conocimiento": str(tmp_path / "base.json"),
                            "tablero_p42": {"activar": activar}}}


def _correr(tmp_path, monkeypatch, guion_por_relativa, activar=True, salida="validacion.json"):
    import validacion
    from estructura import guardar_estructura, mapear_estructura
    raiz = _proyecto(tmp_path)
    estructura = guardar_estructura(mapear_estructura(raiz), tmp_path / "estructura.json")

    def ocr_simulado(ruta, _config, **_kwargs):
        return {"imagen": ruta, "texto_completo": "AIRBAG\n10.04.25", "tokens": [],
                "lineas_texto": [], "confianza_media": .9, "estado_imagen": "procesada_con_texto"}

    monkeypatch.setattr(validacion, "extraer_texto_empresarial", ocr_simulado)
    caso_dir = next(raiz.rglob("PHOTOS")).parent
    guion = {str(caso_dir / "PHOTOS" / r): d for r, d in guion_por_relativa.items()}
    dir_corrida = tmp_path / "corrida unica"
    resultado = validacion.validar_lote_empresarial(
        estructura, _config(tmp_path, activar), archivo_salida=tmp_path / salida,
        dir_corrida=dir_corrida, fabrica_lector_tablero=lambda: LectorFalso(guion))
    return resultado, dir_corrida


GUION_232564 = {
    "VOR/IMG_4408.JPG": {"pista": PISTA, "campos": {
        "dashboard_serial_number": {"valor": "052 3KVJ0099ZZ", "confianza": .9}}},
    "NACH/IMG_1.JPG": {"pista": PISTA, "campos": _fecha("2031-01-11")},
    "NACH/IMG_4408.JPG": {"fechas": [{"valor": "2031-02-17", "clase": "tablero",
                                      "ancla": "etiqueta_blanca", "texto": "17/02/2031 10:32"}]},
}


def test_ruta_normal_completa_lleva_el_tablero_a_campos_trazabilidad_e_informe(tmp_path, monkeypatch):
    resultado, dir_corrida = _correr(tmp_path, monkeypatch, GUION_232564)
    fila = resultado["resultados"][0]
    assert fila["campos"]["dashboard_date"]["valor"] == "2031-02-17"
    assert fila["campos"]["dashboard_date"]["tablero_p42"]["estado"] == "consenso"
    assert fila["campos"]["dashboard_serial_number"]["valor"] is None
    fuentes = {(c["clave"], c["fuente"]) for c in fila["candidatos"]}
    assert ("dashboard_date", "tablero_p42") in fuentes
    assert fila["tablero_p42"]["cobertura"]["presentes"] == 3
    informe = json.loads((dir_corrida / "informe_tablero_p42.json").read_text(encoding="utf-8"))
    assert informe["totales"]["presentes"] == 3
    assert (dir_corrida / "informe_tablero_p42.txt").is_file()
    dudas = json.loads((dir_corrida / "dudas_tablero_p42.json").read_text(encoding="utf-8"))
    assert "dashboard_serial_number" in {d["campo"] for d in dudas}


def test_ruta_normal_con_tablero_desactivado_no_cambia_nada(tmp_path, monkeypatch):
    resultado, dir_corrida = _correr(tmp_path, monkeypatch, GUION_232564, activar=False)
    fila = resultado["resultados"][0]
    assert "tablero_p42" not in fila
    assert not any(c.get("fuente") == "tablero_p42" for c in fila["candidatos"])
    assert not dir_corrida.exists()


def _imagenes_y_comentarios(ruta: Path) -> tuple[list[str], dict]:
    """Huellas de las imágenes del .xlsx y comentarios (texto) de Versuchsmatrix y Rangos."""
    with zipfile.ZipFile(ruta) as z:
        medios = sorted(hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist()
                        if n.startswith("xl/media/"))
    from openpyxl import load_workbook
    libro = load_workbook(ruta)
    comentarios = {(h, c.coordinate): c.comment.text for h in ("Versuchsmatrix", "Rangos")
                   for fila in libro[h].iter_rows() for c in fila if c.comment}
    return medios, comentarios


@pytest.mark.skipif(not LIBRO_V51.is_file(), reason="libro V51 del expediente no disponible")
def test_exportacion_real_conserva_humanos_imagenes_y_no_toca_el_original(tmp_path, monkeypatch):
    from openpyxl import load_workbook

    import reporte_bmg as R
    from configuracion import cargar_config, cargar_reglas
    base = tmp_path / "libro del cliente.xlsx"
    shutil.copy(LIBRO_V51, base)
    libro = load_workbook(base)
    for nombre in ("Versuchsmatrix", "Rangos"):
        hoja = libro[nombre]
        fila = next(f for f in range(8, 18) if str(hoja.cell(f, 3).value) == "232564")
        hoja.cell(fila, 16).value = "SERIE HUMANA"      # P: dato humano que no se pisa
        hoja.cell(fila, 17).value = None                # Q: hueco que el tablero puede llenar
    libro.save(base)
    huella_antes = hashlib.sha256(base.read_bytes()).hexdigest()
    medios_antes, comentarios_antes = _imagenes_y_comentarios(base)

    resultado, _ = _correr(tmp_path, monkeypatch, {
        **GUION_232564,
        "NACH/IMG_1.JPG": {"pista": PISTA, "campos": {
            "dashboard_serial_number": {"valor": "052 3KVJ0099ZZ", "confianza": .9}}}})
    fila_resultado = resultado["resultados"][0]
    assert fila_resultado["campos"]["dashboard_serial_number"]["valor"] == "052 3KVJ0099ZZ"
    salida = R.generar_reporte_bmg(base, tmp_path / "salida nueva.xlsx", resultado["resultados"],
                                   cargar_config(), cargar_reglas())
    assert hashlib.sha256(base.read_bytes()).hexdigest() == huella_antes   # original intacto
    nuevo = load_workbook(salida)
    for nombre in ("Versuchsmatrix", "Rangos"):
        hoja = nuevo[nombre]
        fila = next(f for f in range(8, 18) if str(hoja.cell(f, 3).value) == "232564")
        assert hoja.cell(fila, 16).value == "SERIE HUMANA"
        assert hoja.cell(fila, 17).value == "2031-02-17"
    discrepancias = R.ULTIMAS_DISCREPANCIAS["Versuchsmatrix"]
    assert any(d["existente"] == "SERIE HUMANA" for d in discrepancias)
    medios_despues, comentarios_despues = _imagenes_y_comentarios(salida)
    assert medios_despues == medios_antes
    # Versuchsmatrix/Rangos conservan sus comentarios. (Las hojas DERIVADAS «Übersicht» y
    # «Apertura V15.10» se regeneran desde los resultados de la corrida: comportamiento previo a
    # P43, documentado como riesgo aparte; esta propuesta no lo cambia.)
    assert comentarios_despues == comentarios_antes
    traza = nuevo["Trazabilidad"]
    assert any(c.value == "tablero_p42" for fila in traza.iter_rows(min_row=2) for c in fila)


def test_el_codigo_de_la_integracion_no_contiene_fechas_de_la_referencia():
    raiz = Path(__file__).resolve().parents[1]
    # (los comentarios P42 de evidencia_tablero/buscar_mas citan el formato del sticker; aquí se
    # comprueba el código que DECIDE en la corrida normal)
    for nombre in ("tablero_integracion.py", "validacion.py", "flujo_empresarial.py", "pipeline.py"):
        texto = (raiz / nombre).read_text(encoding="utf-8")
        for prohibida in ("2025-05-17", "17/05/2025", "17/MAY/2025"):
            assert prohibida not in texto, f"{nombre} contiene {prohibida}"
