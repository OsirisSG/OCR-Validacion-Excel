import json
import tempfile
import threading
import types
from pathlib import Path

import cv2
import numpy as np

import ocr_engine
import validacion
from estructura import guardar_estructura, mapear_estructura
from flujo_empresarial import (BaseConocimiento, CacheOCR, case_key,
                               clasificar_codigo_operativo,
                               consolidar_caso, detectar_tipos_st,
                               descubrir_casos, evidencias_desde_qr,
                               interpretar_payload_qr, normalizar_numero_parte,
                               normalizar_temperatura, parsear_nombre_caso)


def test_clasificacion_conservadora_distingue_codigos_de_prosa_y_valores():
    assert clasificar_codigo_operativo("RWD") == {
        "valido": True, "texto": "RWD", "normalizado": "RDW",
        "tipo": "catalogo", "razon": "Coincide con el catálogo de versión de módulo.",
    }
    assert clasificar_codigo_operativo("ETQ-2024-A1-V3")["valido"] is True
    assert clasificar_codigo_operativo("1234567")["tipo"] == "serial_numerico"
    assert clasificar_codigo_operativo("prueba de etiqueta lateral")["tipo"] == "oracion"
    assert clasificar_codigo_operativo("23 ms")["valido"] is False


def _caso(raiz: Path, nombre="232561 RDW OGL HT", temperatura="HT", completo=True):
    base = raiz / temperatura / nombre
    (base / "PHOTOS" / "NACH").mkdir(parents=True)
    if completo:
        (base / "PHOTOS" / "VOR" / "TOR 2").mkdir(parents=True)
    return base


def test_detecta_1st_2st_y_seleccion_manual(tmp_path):
    with tempfile.TemporaryDirectory(prefix="ocr-proyecto-") as temporal:
        base = Path(temporal)
        uno = base / "Proyecto_1ST"
        uno.mkdir()
        assert detectar_tipos_st(uno)["tipos"] == ["1ST"]
        (uno / "grupo_2ST").mkdir()
        assert detectar_tipos_st(uno)["tipos"] == ["1ST", "2ST"]
        desconocido = base / "Proyecto"
        desconocido.mkdir()
        assert detectar_tipos_st(desconocido)["requiere_seleccion"] is True
        assert detectar_tipos_st(desconocido, "2ST")["tipos"] == ["2ST"]
        assert detectar_tipos_st(desconocido, "LEGACY")["usar_legacy"] is True


def test_parsea_rdwnar_y_normaliza_rwd():
    assert parsear_nombre_caso("232541 RDW NOM HT")["module_version"] == "RDW"
    assert parsear_nombre_caso("232542 NAR UGL RT")["inflator_type"] == "UGL"
    rwd = parsear_nombre_caso("222501 RWD OGL NT")
    assert rwd["module_version"] == "RDW"
    assert rwd["module_version_original"] == "RWD"
    assert rwd["test_number"] == "222501"


def test_descubre_por_caso_y_recorre_solo_photos(tmp_path):
    raiz = tmp_path / "Proyecto_1ST"
    valido = _caso(raiz)
    incompleto = _caso(raiz, "222501 RDW NOM NT", "NT", completo=False)
    for ruta in [valido / "PHOTOS/NACH/a.jpg", valido / "PHOTOS/VOR/b.png",
                 valido / "PHOTOS/VOR/TOR 2/c.tif", valido / "DIAGRAMM/no.png",
                 valido / "TEMPERATURE/no.jpg", valido / "VIDEOS/no.avi",
                 incompleto / "PHOTOS/NACH/legacy.jpg"]:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(b"x")
    salida = descubrir_casos(raiz)
    assert salida["casos_validos"] == 1
    assert salida["casos_incompletos"] == 1
    casos = {c["nombre"]: c for c in salida["casos"]}
    fotos = casos["232561 RDW OGL HT"]["fotos"]
    assert {f["ruta_relativa"] for f in fotos} == {
        "PHOTOS/NACH/a.jpg", "PHOTOS/VOR/b.png", "PHOTOS/VOR/TOR 2/c.tif"}
    assert casos["232561 RDW OGL HT"]["carpetas_tor"] == ["TOR 2"]
    assert casos["222501 RDW NOM NT"]["modo_procesamiento"] == "legacy"


def test_temperatura_y_numero_parte_son_conservadores():
    assert normalizar_temperatura("Temperature +85 C") == "HT"
    assert normalizar_temperatura("−35°C") == "NT"
    assert normalizar_temperatura("35", "NT") == "NT"
    assert normalizar_temperatura("23°C") == "RT"
    assert normalizar_temperatura("Temperatura 85,0 °C") == "HT"
    assert normalizar_temperatura("261,857") is None
    assert normalizar_temperatura(None) is None
    assert normalizar_temperatura("folio 85") is None
    assert normalizar_numero_parte("2GJ 880 204 J") == "2GJ.880.204.J"
    assert normalizar_numero_parte("2GJ-880-204-J") == "2GJ.880.204.J"


def test_qr_interpreta_formatos_seguros_y_solo_claves_conocidas():
    json_qr = interpretar_payload_qr(
        '{"module_part_number":"2GJ.880.204.J","comando":"borrar"}')
    pares = interpretar_payload_qr("test=232561;temperature:HT;desconocida=NO")
    url = interpretar_payload_qr("https://ejemplo.invalid/no-se-abre")
    assert json_qr["campos"] == {"module_part_number": "2GJ.880.204.J"}
    assert pares["campos"] == {"test_number": "232561", "temperature_condition": "HT"}
    assert url["formato"] == "url_texto" and url["campos"] == {}
    qrs = [{"payload": "module_sn=SN-77"}]
    evidencias = evidencias_desde_qr(qrs, {"ruta": "foto.jpg", "fase": "NACH"})
    assert evidencias[0]["fuente"] == "qr"
    assert evidencias[0]["clave"] == "module_serial_number"


def test_consolida_repeticiones_conflictos_faltantes_y_regla_confirmada(tmp_path):
    ruta = tmp_path / "Proyecto_1ST"
    caso_ruta = _caso(ruta)
    caso = descubrir_casos(ruta)["casos"][0]
    evidencias = [
        {"clave": "module_part_number", "valor_normalizado": "2GJ.880.204.J",
         "valor_original": "2GJ 880 204 J", "fuente": "ocr", "imagen": "a.jpg",
         "confianza_ocr": .91},
        {"clave": "module_part_number", "valor_normalizado": "2GJ.880.204.J",
         "valor_original": "2GJ.880.204.J", "fuente": "ocr", "imagen": "b.jpg",
         "confianza_ocr": .94},
        {"clave": "dashboard_part_number", "valor_normalizado": "2GJ.857.003.G",
         "valor_original": "2GJ.857.003.G", "fuente": "ocr", "imagen": "a.jpg",
         "confianza_ocr": .90},
        {"clave": "dashboard_part_number", "valor_normalizado": "2GJ.857.003.H",
         "valor_original": "2GJ.857.003.H", "fuente": "ocr", "imagen": "b.jpg",
         "confianza_ocr": .90},
    ]
    regla = {"id": "regla-1", "estado": "confirmada", "alcance": {"tipo_st": "1ST"},
             "campo": "inflator_supplier", "valor": "Autoliv", "confianza": .96}
    salida = consolidar_caso(caso, evidencias, requeridos={"test_number", "test_date"},
                             reglas_confirmadas=[regla])
    assert salida["campos"]["module_part_number"]["estado"] == "confirmado_multiples_imagenes"
    assert salida["campos"]["dashboard_part_number"]["estado"] == "conflicto"
    assert salida["campos"]["test_date"]["estado"] == "faltante_requerido"
    assert salida["campos"]["inflator_supplier"]["estado"] == "inferido_regla_confirmada"
    assert salida["campos"]["module_serial_number"]["valor"] is None


def test_cache_invalida_si_cambia_archivo_o_config(tmp_path):
    imagen = tmp_path / "a.jpg"
    imagen.write_bytes(b"uno")
    cache = CacheOCR(tmp_path / "cache.json", {"modo": "auto"})
    cache.guardar(imagen, {"texto": "A"})
    assert cache.obtener(imagen)["texto"] == "A"
    imagen.write_bytes(b"dos-diferente")
    assert cache.obtener(imagen) is None
    assert CacheOCR(tmp_path / "cache.json", {"modo": "manual"}).obtener(imagen) is None


def test_cache_sqlite_coordina_escrituras_y_recupera_json(tmp_path):
    imagenes = []
    for indice in range(8):
        ruta = tmp_path / f"{indice}.jpg"
        ruta.write_bytes(f"foto-{indice}".encode())
        imagenes.append(ruta)
    cache = CacheOCR(tmp_path / "cache.json", {"modo": "auto"})
    hilos = [threading.Thread(target=cache.guardar, args=(ruta, {"texto": ruta.stem}))
             for ruta in imagenes]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()
    assert cache.ruta.suffix == ".sqlite3"
    assert cache.recuperar_pendientes() == []
    assert [cache.obtener(ruta)["texto"] for ruta in imagenes] == [str(i) for i in range(8)]


def test_base_conocimiento_propone_y_solo_confirmada_se_lista(tmp_path):
    base = BaseConocimiento(tmp_path / "base.json", minimo_ids=3, consenso=.9)
    resultados = []
    for numero in ("1", "2", "3"):
        resultados.append({"test_number": numero, "tipo_st": "1ST",
                           "caso": {"metadata_ruta": {"module_version": "RDW"}},
                           "campos": {"module_part_number": {"valor": "2GJ.880.204.J"}}})
    propuestas = base.proponer(resultados)
    assert len(propuestas) >= 1
    assert propuestas[0]["estado"] == "propuesta"
    assert base.confirmadas() == []
    base.cambiar_estado(propuestas[0]["id"], "confirmada", "prueba")
    assert base.confirmadas()[0]["confirmada_por"] == "prueba"


class _MotorFalso:
    nombre = "easyocr"
    dispositivo = "cpu"
    advertencias = []

    def __init__(self, cajas):
        self.cajas = cajas
        self.reconocimientos = 0
        self.formas = []
        self.formas_deteccion = []

    def detectar(self, _imagen):
        self.formas_deteccion.append(_imagen.shape[:2])
        return self.cajas

    def leer_texto_completo(self, _imagen):
        self.reconocimientos += 1
        self.formas.append(_imagen.shape[:2])
        return [{"texto": "2GJ 880 204 J", "bbox": (1, 1, 40, 10), "confianza": .95}]


def test_imagen_sin_cajas_no_llega_al_reconocimiento(monkeypatch, tmp_path):
    ruta = tmp_path / "foto.png"
    cv2.imwrite(str(ruta), np.zeros((100, 200, 3), dtype=np.uint8))
    motor = _MotorFalso([])
    monkeypatch.setattr(ocr_engine, "obtener_motor", lambda config=None: (motor, config["fase1"]))
    salida = ocr_engine.extraer_texto_empresarial(str(ruta), {
        "fase1": {"umbral_confianza_texto_completo": .25}, "ocr": {"modo_recorte": "auto"}})
    assert salida["estado_imagen"] == "descartada_sin_texto"
    assert motor.reconocimientos == 0


def test_imagen_con_caja_recorta_amplia_y_reconoce(monkeypatch, tmp_path):
    ruta = tmp_path / "foto.png"
    cv2.imwrite(str(ruta), np.zeros((200, 400, 3), dtype=np.uint8))
    motor = _MotorFalso([{"bbox": (40, 50, 100, 20), "poligono": None}])
    config = {"fase1": {"umbral_confianza_texto_completo": .25, "umbral_espacio_px": 40},
              "ocr": {"modo_recorte": "auto", "lado_maximo_deteccion": 200,
                      "margen_recorte": .1, "zoom_minimo": 1, "zoom_maximo": 3,
                      "confianza_fallback": .45}}
    monkeypatch.setattr(ocr_engine, "obtener_motor", lambda config=None: (motor, config["fase1"]))
    salida = ocr_engine.extraer_texto_empresarial(str(ruta), config)
    assert salida["estado_imagen"] == "procesada_con_texto"
    assert salida["numero_regiones"] == 1
    assert salida["zoom_aplicado"] > 1
    assert motor.reconocimientos == 1


def test_zoom_forzado_cambia_dimensiones_que_recibe_easyocr(monkeypatch, tmp_path):
    ruta = tmp_path / "zoom.png"
    cv2.imwrite(str(ruta), np.zeros((120, 240, 3), dtype=np.uint8))
    motor = _MotorFalso([{"bbox": (20, 30, 80, 20), "poligono": None}])
    config = {"fase1": {"umbral_confianza_texto_completo": .25, "umbral_espacio_px": 40},
              "ocr": {"modo_recorte": "auto", "margen_recorte": 0,
                      "zoom_minimo": 1, "zoom_maximo": 3, "confianza_fallback": .2}}
    monkeypatch.setattr(ocr_engine, "obtener_motor", lambda config=None: (motor, config["fase1"]))
    salida = ocr_engine.extraer_texto_empresarial(str(ruta), config, zoom_forzado=2.5)
    assert motor.formas[0] == (50, 200)
    assert salida["recortes"][0]["dimensiones_antes"] == (80, 20)
    assert salida["recortes"][0]["dimensiones_despues"] == (200, 50)


def test_rotacion_manual_libre_se_aplica_antes_del_ocr_empresarial(monkeypatch, tmp_path):
    from aprendizaje import GestorAprendizaje, dimensiones_rotadas

    ruta = tmp_path / "rotacion.png"
    cv2.imwrite(str(ruta), np.zeros((100, 200, 3), dtype=np.uint8))
    motor = _MotorFalso([])
    config = {
        "fase1": {"umbral_confianza_texto_completo": .25},
        "ocr": {"modo_recorte": "auto"},
        "aprendizaje": {"activar": True, "directorio": str(tmp_path / "aprendizaje")},
    }
    GestorAprendizaje(config).actualizar_rotacion(ruta, 30)
    monkeypatch.setattr(ocr_engine, "obtener_motor", lambda config=None: (motor, config["fase1"]))

    salida = ocr_engine.extraer_texto_empresarial(str(ruta), config)

    ancho, alto = dimensiones_rotadas(200, 100, 30)
    assert motor.formas_deteccion[0] == (alto, ancho)
    assert salida["rotacion_manual_aplicada_grados"] == 30
    assert salida["orientacion_manual_prioritaria"] is True


def test_validacion_empresarial_procesa_todas_y_reanuda_desde_cache(monkeypatch, tmp_path):
    raiz = tmp_path / "Proyecto_1ST"
    caso = _caso(raiz)
    rutas = [caso / "PHOTOS/NACH/a.jpg", caso / "PHOTOS/VOR/b.jpg",
             caso / "PHOTOS/VOR/TOR 2/c.jpg"]
    for ruta in rutas:
        ruta.write_bytes(b"foto")
    estructura = mapear_estructura(raiz)
    archivo_estructura = guardar_estructura(estructura, tmp_path / "estructura.json")
    llamadas = []

    def ocr(ruta, config, **kwargs):
        llamadas.append(ruta)
        return {"imagen": ruta, "motor": "easyocr", "dispositivo": "cpu",
                "tokens": [], "lineas_texto": [{"texto": "2GJ 880 204 J",
                                                   "bbox": [1, 2, 30, 8], "confianza": .95}],
                "texto_completo": "2GJ 880 204 J", "confianza_media": .95,
                "dimensiones": [100, 50], "estado_imagen": "procesada_con_texto",
                "modo_recorte": "auto", "tiempo_deteccion_seg": .01,
                "tiempo_ocr_seg": .02, "numero_regiones": 1, "zoom_aplicado": 2.0}

    monkeypatch.setattr(validacion, "extraer_texto_empresarial", ocr)
    avance_ids = tmp_path / "avance_ids.json"
    config = {"fase1": {}, "ocr": {}, "normalizacion": {}, "empresarial": {
        "archivo_cache": str(tmp_path / "cache.json"),
        "archivo_avance_ids": str(avance_ids),
        "base_conocimiento": str(tmp_path / "base.json")}}
    destino = tmp_path / "resultados.json"
    parciales = []

    def imagen_persistida(*_args):
        parciales.append(json.loads(avance_ids.read_text(encoding="utf-8")))

    primera = validacion.validar_lote_empresarial(
        archivo_estructura, config, archivo_salida=destino,
        al_imagen=imagen_persistida)
    assert len(llamadas) == 3
    assert all(item["avances_ids"] for item in parciales)
    primera_evidencia = next(iter(parciales[0]["avances_ids"].values()))
    assert primera_evidencia["imagenes"][0]["nombre"] == "a.jpg"
    assert primera_evidencia["trazabilidad"][0]["estado_imagen"] == "procesada_con_texto"
    assert json.loads(avance_ids.read_text(encoding="utf-8"))["avances_ids"] == {}
    assert len(primera["resultados"]) == 1
    assert primera["resultados"][0]["progreso"]["revisadas"] == 3
    assert primera["resultados"][0]["campos"]["module_part_number"]["estado"] == \
        "confirmado_multiples_imagenes"
    llamadas.clear()
    segunda = validacion.validar_lote_empresarial(
        archivo_estructura, config, archivo_salida=destino)
    assert llamadas == []
    assert all(t["desde_cache"] for t in segunda["resultados"][0]["trazabilidad"])
    assert len(segunda["resultados"][0]["historial_ejecuciones"]) == 2
    assert segunda["resultados"][0]["historial_ejecuciones"][1]["imagenes_revisadas"] == 3


def test_temperatura_ocr_contraria_a_ruta_genera_conflicto(tmp_path):
    raiz = tmp_path / "Proyecto_1ST"
    _caso(raiz)
    caso = descubrir_casos(raiz)["casos"][0]
    salida = consolidar_caso(caso, [{
        "clave": "temperature_condition", "valor_normalizado": "NT",
        "valor_original": "-35°C", "fuente": "ocr", "imagen": "x.jpg",
        "confianza_ocr": .98,
    }], requeridos={"temperature_condition"})
    assert salida["campos"]["temperature_condition"]["estado"] == "conflicto"
    assert salida["campos"]["temperature_condition"]["valor_seguro_ruta"] == "HT"


def test_consolidacion_respeta_claves_de_un_contrato_nuevo(tmp_path):
    raiz = tmp_path / "Proyecto_1ST"
    _caso(raiz)
    caso = descubrir_casos(raiz)["casos"][0]

    salida = consolidar_caso(
        caso, [{"clave": "customer_code", "valor_normalizado": "CX-2040",
                "valor_original": "CX-2040", "fuente": "manual",
                "imagen": "x.jpg", "confianza_ocr": 1.0}],
        requeridos={"test_number", "customer_code"},
        claves=["test_number", "customer_code"])

    assert set(salida["campos"]) == {"test_number", "customer_code"}
    assert salida["campos"]["customer_code"]["valor"] == "CX-2040"
    assert salida["campos"]["customer_code"]["estado"] == "extraido_manual"


def test_reader_easyocr_se_inicializa_una_sola_vez(monkeypatch):
    creados = []

    class Reader:
        device = "cpu"

        def __init__(self, *args, **kwargs):
            creados.append((args, kwargs))

    monkeypatch.setitem(__import__("sys").modules, "easyocr", types.SimpleNamespace(Reader=Reader))
    monkeypatch.setattr(ocr_engine, "detectar_recursos", lambda *_: {
        "seleccionado": "cpu", "warning": None})
    monkeypatch.setattr(ocr_engine, "configurar_cpu", lambda *_: 1)
    ocr_engine._MOTORES.clear()
    config = {"fase1": {"motor": "easyocr", "dispositivo": "auto", "rendimiento": {}}}
    primero, _ = ocr_engine.obtener_motor(config)
    segundo, _ = ocr_engine.obtener_motor(config)
    assert primero is segundo
    assert len(creados) == 1


def test_modo_manual_usa_roi_proporcional(monkeypatch, tmp_path):
    ruta = tmp_path / "foto.png"
    cv2.imwrite(str(ruta), np.zeros((100, 200, 3), dtype=np.uint8))
    motor = _MotorFalso([])
    monkeypatch.setattr(ocr_engine, "obtener_motor", lambda config=None: (motor, config["fase1"]))
    salida = ocr_engine.extraer_texto_empresarial(str(ruta), {
        "fase1": {"umbral_confianza_texto_completo": .25, "umbral_espacio_px": 40},
        "ocr": {"modo_recorte": "manual", "roi_manual": {
            "VOR": {"x": .25, "y": .5, "ancho": .5, "alto": .5}},
            "zoom_minimo": 1, "zoom_maximo": 3, "confianza_fallback": .45}}, fase="VOR")
    assert salida["modo_recorte"] == "manual"
    assert salida["estado_imagen"] == "procesada_con_texto"
    assert salida["tokens"][0]["bbox"][0] >= 50
