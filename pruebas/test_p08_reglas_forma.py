"""Pruebas de P08: forma de los valores, corroboración, relleno aditivo y doctor local.

Cada prueba está atada a un error REAL medido en la ejecución local de V16.0.21 sobre los
10 casos: `GJ.880.204.J` sin el `2`, `02S` donde el libro dice `01S`, `UGL` donde el libro
dice `NOM`, y 149 celdas vacías porque la hoja se reescribía en vez de rellenarse.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from utilidades import relleno_libro, validacion_formas  # noqa: E402


def _caso(**extra):
    caso = {"case_key": "K1", "project_id": "P", "tipo_st": "1ST",
            "metadata_ruta": {"test_number": "232561", "temperature_condition": "HT",
                              "module_version": "RDW", "inflator_type": "NOM"},
            "ruta_relativa": "232561 RDW NOM HT"}
    caso.update(extra)
    return caso


def _ev(clave, valor, imagen, **extra):
    return {"clave": clave, "valor_normalizado": valor, "fuente": "ocr",
            "imagen": imagen, "confianza_ocr": .9, **extra}


# --------------------------------------------------------------- 1. forma de los valores
@pytest.mark.parametrize("clave,valor,valido", [
    ("module_part_number", "2GJ.880.204.J", True),
    ("module_part_number", "GJ.880.204.J", False),   # el error real del caso 222550
    ("module_part_number", "26J.880.204.J", False),
    ("dashboard_part_number", "2GJ.857.003.G", True),
    ("engineering_level", "01S", True),
    ("engineering_level", "66K", True),              # prototipo: el usuario lo admite
    ("engineering_level", "3S", False),
    ("engineering_level", "OLS", False),
    ("module_serial_number", "671 ZRZ0539983E", True),
    ("module_serial_number", "ORTE", False),
    ("dashboard_serial_number", "052 3KVJ008R6E", True),
    ("test_number", "232561", True),
    ("test_number", "23255", False),
    ("temperature_condition", "HT", True),
    ("inflator_type", "NOM", True),
    ("module_version", "RDW", True),
])
def test_forma_de_los_valores(clave, valor, valido):
    revision = validacion_formas.revisar_forma(clave, valor)
    assert revision["valido"] is valido
    if not valido:
        assert revision["motivo"], "un rechazo sin motivo no se puede consultar"


def test_campo_sin_patron_no_se_inventa_una_regla():
    # Proveedores y apertura láser son texto libre en el libro: no se criban.
    assert validacion_formas.revisar_forma("inflator_supplier", "Autoliv")["valido"] is True
    assert validacion_formas.revisar_forma("laser_opening", "3mm ¨C¨")["valido"] is True


def test_filtrar_candidatos_separa_validos_y_rechazados():
    validos, rechazados = validacion_formas.filtrar_candidatos(
        "module_part_number", ["2GJ.880.204.J", "GJ.880.204.J", "2GJ.880.204.J"])
    assert validos == ["2GJ.880.204.J"]
    assert rechazados and rechazados[0]["valor"] == "GJ.880.204.J"


def test_nivel_necesita_dos_fuentes_independientes():
    assert validacion_formas.corroborado("engineering_level", ["a.jpg"]) is False
    assert validacion_formas.corroborado("engineering_level", ["a.jpg", "b.jpg"]) is True
    # Los demás campos no exigen corroboración.
    assert validacion_formas.corroborado("module_version", ["a.jpg"]) is True


# ------------------------------------------------------------------- 2. consolidado P08
def test_valor_malformado_no_entra_en_el_consenso_pero_queda_anotado():
    import flujo_empresarial as fe
    resultado = fe.consolidar_caso(
        _caso(), [_ev("module_part_number", "GJ.880.204.J", "foto1.jpg")],
        requeridos={"module_part_number"}, claves=("module_part_number",))
    campo = resultado["campos"]["module_part_number"]
    assert campo["valor"] is None, "un número de parte sin el dígito inicial no se publica"
    assert campo["estado"] == "forma_invalida"
    assert campo["requiere_revision"] is True
    assert campo["rechazados"][0]["valor"] == "GJ.880.204.J"
    assert "module_part_number" in resultado["campos_a_confirmar"]


def test_nivel_con_una_sola_lectura_queda_propuesto_y_no_publicado():
    import flujo_empresarial as fe
    resultado = fe.consolidar_caso(
        _caso(), [_ev("engineering_level", "02S", "foto1.jpg")],
        requeridos={"engineering_level"}, claves=("engineering_level",))
    campo = resultado["campos"]["engineering_level"]
    assert campo["valor"] is None
    assert campo["valor_propuesto"] == "02S"
    assert campo["estado"] == "pendiente_corroboracion"
    assert "necesita 2" in campo["motivo"]


def test_nivel_no_se_publica_ni_con_dos_lecturas_concordantes():
    """P09: medido en los 10 casos, 0 de 13 lecturas de nivel coincidieron con el libro.

    Que dos lecturas coincidan en un error sistemático (`01S` leído `02S`, `69K` leído `03S`)
    no lo convierte en acierto: el nivel va a la cola de dudas con sus lecturas como opciones.
    """
    import flujo_empresarial as fe
    resultado = fe.consolidar_caso(
        _caso(), [_ev("engineering_level", "01S", "foto1.jpg"),
                  _ev("engineering_level", "01S", "foto2.jpg")],
        requeridos={"engineering_level"}, claves=("engineering_level",))
    campo = resultado["campos"]["engineering_level"]
    assert campo["valor"] is None
    assert campo["estado"] == "solo_lecturas_automaticas"
    assert campo["opciones_consenso"], "la duda debe poder enseñar qué se leyó"


def test_dos_lecturas_del_mismo_archivo_no_corroboran_un_nivel():
    import flujo_empresarial as fe
    resultado = fe.consolidar_caso(
        _caso(), [_ev("engineering_level", "02S", "foto1.jpg"),
                  _ev("engineering_level", "02S", "foto1.jpg")],
        requeridos={"engineering_level"}, claves=("engineering_level",))
    assert resultado["campos"]["engineering_level"]["valor"] is None


def test_la_confirmacion_humana_no_se_somete_a_la_forma():
    import flujo_empresarial as fe
    resultado = fe.consolidar_caso(
        _caso(), [{"clave": "test_number", "valor_normalizado": "99", "fuente": "manual",
                   "imagen": "foto.jpg", "confirmacion_manual": True}],
        requeridos={"test_number"}, claves=("test_number",))
    campo = resultado["campos"]["test_number"]
    assert campo["valor"] == "99"
    assert campo["estado"] == "extraido_manual"


# --------------------------------------------------------------------- 3. números y libro
def test_test_number_se_escribe_como_numero_en_el_libro():
    import reporte_bmg as rb
    hoja = Workbook().active
    rb._escribir_fila(hoja, 8, {"test_number": "232561", "week": "22",
                                "engineering_level": "01S"}, "es")
    assert hoja.cell(8, 3).value == 232561 and isinstance(hoja.cell(8, 3).value, int)
    assert hoja.cell(8, 1).value == 22 and isinstance(hoja.cell(8, 1).value, int)
    assert hoja.cell(8, 11).value == "01S", "un nivel no es un número"


# ------------------------------------------------------------ 4. relleno aditivo (reglas 2 y 7)
def _hoja_con_datos(claves):
    hoja = Workbook().active
    fila_libro = {"week": 22, "test_reason": "IT BMG", "test_number": 222501,
                  "test_place": "EDAG", "temperature_condition": "NT",
                  "module_part_number": "2GJ.880.204.J", "dashboard_part_number": "2GJ.857.003.G",
                  "dashboard_engineering_level": "03S", "inflator_supplier": "Autoliv"}
    for columna, clave in enumerate(claves, start=1):
        for fila in (8, 9, 10, 11):
            # El número de prueba es lo único que cambia de un caso a otro.
            hoja.cell(fila, columna).value = (222500 + fila - 8 if clave == "test_number"
                                              else fila_libro.get(clave))
    return hoja


def test_constantes_detectadas_y_una_sola_fila_no_es_constante():
    claves = ("test_reason", "test_number", "inflator_supplier")
    hoja = _hoja_con_datos(claves)
    constantes = relleno_libro.leer_constantes(hoja, claves, 8, 107)
    assert constantes["test_reason"]["valor"] == "IT BMG"
    assert "test_number" not in constantes, "cada caso tiene su número: no es constante"


def test_el_plan_no_pisa_lo_que_ya_esta_escrito_y_anota_la_discrepancia():
    claves = ("test_number", "module_part_number", "engineering_level")
    hoja = _hoja_con_datos(claves)
    plan = relleno_libro.planificar(
        hoja, [{"fila": 8, "valores": {"test_number": "222500",
                                       "module_part_number": "GJ.880.204.J",
                                       "engineering_level": "01S"}}], claves)
    assert [e["clave"] for e in plan["escribir"]] == ["engineering_level"]
    assert [e["clave"] for e in plan["conservar"]] == ["test_number"]
    discrepancia = plan["discrepancias"][0]
    assert discrepancia["clave"] == "module_part_number"
    assert discrepancia["valor_libro"] == "2GJ.880.204.J"
    assert discrepancia["valor_propuesto"] == "GJ.880.204.J"
    assert relleno_libro.aplicar(hoja, plan) == 1
    assert hoja.cell(8, 2).value == "2GJ.880.204.J", "el libro manda: no se sobrescribe"


def test_constante_sin_confirmar_se_propone_y_no_se_escribe():
    claves = ("test_reason", "engineering_level")
    hoja = _hoja_con_datos(claves)
    hoja.cell(8, 1).value = None  # hueco en una columna que el libro tiene constante
    plan = relleno_libro.planificar(hoja, [{"fila": 8, "valores": {}}], claves)
    assert plan["escribir"] == []
    assert [c["clave"] for c in plan["constantes_propuestas"]] == ["test_reason"]
    assert hoja.cell(8, 1).value is None


def test_constante_confirmada_por_lote_rellena_todas_las_filas():
    claves = ("test_reason", "engineering_level")
    hoja = _hoja_con_datos(claves)
    hoja.cell(8, 1).value = None
    hoja.cell(9, 1).value = None
    plan = relleno_libro.planificar(
        hoja, [{"fila": 8, "valores": {}}, {"fila": 9, "valores": {}}], claves,
        constante_confirmada=["test_reason"])
    assert plan["constantes"]["test_reason"]["valor"] == "IT BMG"
    assert relleno_libro.aplicar(hoja, plan) == 2
    assert hoja.cell(8, 1).value == "IT BMG" and hoja.cell(9, 1).value == "IT BMG"


def test_emparejar_filas_por_numero_de_prueba_normalizado():
    claves = ("test_number",)
    hoja = Workbook().active
    hoja.cell(8, 1).value = 222501
    uno = {"test_number": "222501"}
    dos = {"test_number": "232599"}
    empareje = relleno_libro.emparejar_filas(hoja, [uno, dos], claves)
    assert empareje["filas"] == {id(uno): 8}
    assert empareje["sin_fila"] == [dos]


# ------------------------------------------------------ 5. modo relleno en el reporte real
def test_modo_relleno_conserva_el_libro_y_solo_rellena_huecos(tmp_path):
    import reporte_bmg as rb
    from openpyxl import load_workbook

    plantilla = RAIZ / "plantillas" / "reporte_bmg_1st_2st.xlsx"
    if not plantilla.is_file():  # pragma: no cover
        pytest.skip("no está la plantilla BMG")
    salida = tmp_path / "salida.xlsx"
    resultado = {"test_number": "222501", "tipo_st": "1ST",
                 "campos": {"test_number": {"valor": "222501"},
                            "engineering_level": {"valor": "01S"},
                            "module_part_number": {"valor": "GJ.880.204.J"}}}
    rb.generar_reporte_bmg(plantilla, salida, [resultado],
                           {"colores": {}, "fase3": {"modo_relleno": True}}, {}, "es")
    libro = load_workbook(salida)
    hoja = libro[rb.HOJA_LISTA]
    indice = {clave: i for i, clave in enumerate(rb.CLAVES_PLANTILLA, start=1)}
    # Lo que ya estaba en el libro sigue ahí (regla 2)…
    assert hoja.cell(8, indice["test_reason"]).value == "IT BMG"
    assert hoja.cell(8, indice["test_place"]).value == "EDAG"
    assert hoja.cell(8, indice["module_part_number"]).value == "2GJ.880.204.J"
    # …y el hueco que sí estaba vacío se rellenó con lo leído.
    assert hoja.cell(8, indice["engineering_level"]).value == "01S"
    # El plan queda al lado, consultable.
    informe = salida.with_suffix(".relleno.json")
    assert informe.is_file()
    texto = informe.read_text(encoding="utf-8")
    assert "discrepancias" in texto and "GJ.880.204.J" in texto


def test_modo_normal_sigue_reescribiendo_la_hoja(tmp_path):
    """El comportamiento histórico no cambia si el usuario no activa `modo_relleno`."""
    import reporte_bmg as rb
    from openpyxl import load_workbook

    plantilla = RAIZ / "plantillas" / "reporte_bmg_1st_2st.xlsx"
    if not plantilla.is_file():  # pragma: no cover
        pytest.skip("no está la plantilla BMG")
    salida = tmp_path / "normal.xlsx"
    rb.generar_reporte_bmg(plantilla, salida,
                           [{"test_number": "232561", "tipo_st": "1ST",
                             "campos": {"test_number": {"valor": "232561"}}}],
                           {"colores": {}}, {}, "es")
    hoja = load_workbook(salida)[rb.HOJA_LISTA]
    indice = {clave: i for i, clave in enumerate(rb.CLAVES_PLANTILLA, start=1)}
    assert hoja.cell(8, indice["test_reason"]).value is None
    assert not salida.with_suffix(".relleno.json").exists()


# ------------------------------------------------------------------- 6. doctor local
def test_doctor_avisa_de_la_cuantizacion_y_lee_los_parametros_reales():
    import doctor_ocr as doc
    parametros = doc.parametros_efectivos(
        {"fase1": {"lang": "en", "cuantizar_cpu": True, "rendimiento": {"batch_cpu": 1}},
         "ocr": {"lado_maximo_deteccion": 1280, "roi_manual": {"NACH": {"x": 0}}}})
    assert parametros["cuantizar_cpu"] is True
    avisos = doc.avisos({"easyocr": "1.7.2", "modelos_descargados": ["craft_mlt_25k.pth"],
                         "dispositivo": "cpu", "memoria_gb": 16,
                         "ruta_modelos": "C:/x"}, parametros)
    assert any("cuantización" in a for a in avisos)
    assert any("inglés" in a for a in avisos)


def test_doctor_coteja_el_canario_y_detecta_la_variante_malformada():
    import doctor_ocr as doc
    lecturas = [{"imagen": "a.jpg", "texto": "2GJ.880.204.J 01S 232561"},
                {"imagen": "b.jpg", "texto": "GJ.880.204.J 01S"}]
    cotejo = doc.evaluar_canario(lecturas, {"module_part_number": "2GJ.880.204.J",
                                            "engineering_level": "01S",
                                            "test_number": "232561"})
    assert cotejo["total"] == 3
    assert cotejo["campos"]["module_part_number"]["imagenes_con_valor"] == 1
    assert cotejo["campos"]["module_part_number"]["imagenes_con_variante_malformada"] == 1
    assert cotejo["campos"]["engineering_level"]["imagenes_con_valor"] == 2


def test_doctor_sin_easyocr_sale_con_codigo_2_y_lo_dice():
    import doctor_ocr as doc
    real = doc.huella_entorno()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(doc, "huella_entorno", lambda: {**real, "easyocr": None})
        assert doc.main(["--config", str(RAIZ / "config.yaml")]) == 2


# ------------------------------------------------------- 7. motor: cuantización opcional
def test_el_motor_no_cuantiza_en_cpu_salvo_que_se_pida(monkeypatch):
    import types

    import ocr_engine

    registrados = []

    class ReaderFalso:
        device = "cpu"

        def __init__(self, *args, **kwargs):
            registrados.append(kwargs)

        def detect(self, *a, **k):
            return [], []

        def readtext(self, *a, **k):
            return []

    modulo = types.ModuleType("easyocr")
    modulo.Reader = ReaderFalso
    monkeypatch.setitem(sys.modules, "easyocr", modulo)
    monkeypatch.setattr(ocr_engine, "detectar_recursos",
                        lambda _d=None: {"seleccionado": "cpu"})

    ocr_engine.MotorEasyOCR({"lang": "en", "dispositivo": "cpu", "rendimiento": {}})
    assert registrados[-1]["quantize"] is False, "por omisión se prioriza la precisión"

    ocr_engine.MotorEasyOCR({"lang": "en", "dispositivo": "cpu", "rendimiento": {},
                             "cuantizar_cpu": True})
    assert registrados[-1]["quantize"] is True


def test_la_constante_detectada_llega_a_la_cola_de_dudas_como_opcion():
    """Regla 7: una constante del libro se confirma una vez y sirve para todas las filas."""
    from utilidades.dudas_y_opciones import construir_dudas

    claves = ("test_reason", "test_number")
    hoja = _hoja_con_datos(claves)
    constantes = relleno_libro.leer_constantes(hoja, claves, 8, 107)
    lecturas = relleno_libro.lecturas_de_constantes({"constantes": constantes}, ["222599"])
    dudas = construir_dudas({"222599": {"test_number": "222599"}}, lecturas,
                            columnas={"test_reason": "B"}, campos=("test_reason",))
    assert len(dudas) == 1
    fuentes = {o["fuente"]: o["valor"] for o in dudas[0]["opciones"]}
    assert fuentes["libro_constante"] == "IT BMG"
    assert dudas[0]["opcion_recomendada"] == "IT BMG"


# ------------------------------------------------------ 8. el medidor de acertividad
def _libro_matriz(tmp_path, nombre, filas):
    """Construye un libro mínimo con la rejilla posicional de 20 campos."""
    from openpyxl import Workbook as _WB

    libro = _WB()
    hoja = libro.active
    hoja.title = "Versuchsmatrix"
    for fila, valores in enumerate(filas, start=8):
        for columna, valor in enumerate(valores, start=1):
            hoja.cell(fila, columna).value = valor
    ruta = tmp_path / nombre
    libro.save(ruta)
    return ruta


def test_el_medidor_cuenta_cobertura_precision_y_errores(tmp_path):
    import comparar_resultado as cr

    referencia = _libro_matriz(tmp_path, "libro.xlsx", [
        [22, "IT BMG", 222550, "2025-05-28", "EDAG", "NT", "2GJ.880.204.J", "RDW",
         "671 ZRZ0539983E", "2025-04-10", "01S"],
    ])
    generado = _libro_matriz(tmp_path, "generado.xlsx", [
        [22, None, 222550, None, None, "NT", "GJ.880.204.J", "RDW", None, None, "02S"],
    ])
    informe = cr.comparar(cr.leer(generado), cr.leer(referencia))
    # generado publica 6: semana, número, temperatura, versión, número de parte y nivel
    assert informe["publicados"] == 6
    assert informe["aciertos"] == 4            # semana, número, temperatura y versión
    assert informe["precision_pct"] == 66.7
    assert informe["cobertura_pct"] == 30.0    # 6 de 20 celdas
    campos = {e["campo"] for e in informe["errores"]}
    assert campos == {"module_part_number", "engineering_level"}


def test_el_medidor_empareja_por_posicion_cuando_el_numero_se_leyo_mal(tmp_path):
    import comparar_resultado as cr

    referencia = _libro_matriz(tmp_path, "ref.xlsx", [[22, "IT BMG", 222550, None, "EDAG"]])
    generado = _libro_matriz(tmp_path, "gen.xlsx", [[22, "IT BMG", 232550, None, "EDAG"]])
    informe = cr.comparar(cr.leer(generado), cr.leer(referencia))
    assert informe["casos_emparejados"] == 1
    assert informe["avisos"] and "por posición" in informe["avisos"][0]
    assert [e["campo"] for e in informe["errores"]] == ["test_number"]


# ---------------------------------------------------------------- 9. consenso ponderado (P09)
def _lectura(clave, valor, imagen="a.jpg", fuente="ocr", **extra):
    return {"clave": clave, "valor_normalizado": valor, "imagen": imagen,
            "fuente": fuente, **extra}


def test_canonizar_unifica_separadores_sin_cambiar_caracteres():
    from utilidades.consenso_valores import canonizar
    assert canonizar("module_part_number", "2GJ 880 204 J") == "2GJ.880.204.J"
    assert canonizar("engineering_level", "3s") == "03S"
    assert canonizar("module_serial_number", "671ZRZ0539983E") == "671 ZRZ0539983E"
    # no se toca ningún carácter: `ZRZO` no se convierte en `ZRZ0`
    assert "O" in canonizar("module_serial_number", "671 ZRZO539999L")


def test_reparar_solo_lo_estructural_y_con_la_prueba_de_otra_lectura():
    from utilidades.consenso_valores import reparar
    assert reparar("module_part_number", "GJ.880.204.J", ["2GJ 880 204 J"])[:2] == \
        ("2GJ.880.204.J", True)
    # sin otra lectura que aporte el dígito, no se adivina
    assert reparar("module_part_number", "GJ.880.204.J", [])[1] is False
    assert reparar("module_serial_number", "671 ZRZO539999L", ["671 ZRZ0539999L"])[1] is False


def test_una_misma_foto_repetida_no_suma_dos_votos():
    from utilidades.consenso_valores import consensuar
    decision = consensuar("module_part_number",
                          [_lectura("module_part_number", "2GJ.880.204.J", "a.jpg"),
                           _lectura("module_part_number", "2GJ.880.204.J", "a.jpg")])
    # el valor se publica (un número de parte bien formado basta), pero pesa UN voto, no dos
    assert decision["peso"] == 1.0
    assert decision["opciones"][0]["imagenes"] == 1


def test_dos_fotos_iguales_sostienen_un_numero_de_parte():
    from utilidades.consenso_valores import consensuar
    decision = consensuar("module_part_number",
                          [_lectura("module_part_number", "2GJ 880 204 J", "a.jpg"),
                           _lectura("module_part_number", "2GJ.880.204.J", "b.jpg")])
    assert decision["valor"] == "2GJ.880.204.J" and decision["estado"] == "consenso"


def test_el_convenio_de_la_carpeta_decide_temperatura_y_version():
    from utilidades.consenso_valores import consensuar
    decision = consensuar("temperature_condition",
                          [_lectura("temperature_condition", "NT", None, "ruta_carpeta"),
                           _lectura("temperature_condition", "RT", "a.jpg"),
                           _lectura("temperature_condition", "RT", "b.jpg")])
    assert decision["valor"] == "NT"


def test_el_inflador_de_la_carpeta_cede_ante_cualquier_lectura_contraria():
    from utilidades.consenso_valores import consensuar
    cede = consensuar("inflator_type",
                      [_lectura("inflator_type", "OGL", None, "ruta_carpeta"),
                       _lectura("inflator_type", "NOM", "a.jpg",
                                regla="catalogo_inflator")])
    assert cede["valor"] is None and cede["estado"] == "carpeta_no_confirmada"
    confirma = consensuar("inflator_type",
                          [_lectura("inflator_type", "NOM", None, "ruta_carpeta"),
                           _lectura("inflator_type", "NOM", "a.jpg",
                                    regla="catalogo_inflator")])
    assert confirma["valor"] == "NOM"


def test_el_numero_de_prueba_solo_cede_ante_dos_fotos_que_digan_otra_cosa():
    from utilidades.consenso_valores import consensuar
    una_sola = consensuar("test_number",
                          [_lectura("test_number", "232561", None, "ruta_carpeta"),
                           _lectura("test_number", "142025", "a.jpg",
                                    regla="numero_prueba_impreso_sin_etiqueta")])
    assert una_sola["valor"] == "232561"
    dos_fotos = consensuar("test_number",
                           [_lectura("test_number", "232561", None, "ruta_carpeta"),
                            _lectura("test_number", "252561", "a.jpg",
                                     regla="numero_prueba_impreso_sin_etiqueta"),
                            _lectura("test_number", "252561", "b.jpg",
                                     regla="numero_prueba_impreso_sin_etiqueta")])
    assert dos_fotos["valor"] is None


def test_el_nivel_exige_una_persona_y_no_lo_decide_el_ocr():
    from utilidades.consenso_valores import consensuar
    automatico = consensuar("engineering_level",
                            [_lectura("engineering_level", "02S", "a.jpg"),
                             _lectura("engineering_level", "02S", "b.jpg")])
    assert automatico["valor"] is None
    assert automatico["estado"] == "solo_lecturas_automaticas"
    humano = consensuar("engineering_level",
                        [_lectura("engineering_level", "01S", "a.jpg", "manual",
                                  confirmacion_manual=True)])
    assert humano["valor"] == "01S"


def test_el_consenso_no_pisa_lo_ya_decidido_ni_los_conflictos_deliberados():
    from utilidades.consenso_valores import rescatar
    campos = {"module_part_number": {"valor": "2GJ.880.204.J", "estado": "extraido_ocr"},
              "week": {"valor": None, "estado": "conflicto"}}
    evidencias = {"module_part_number": [_lectura("module_part_number", "X", "a.jpg")],
                  "week": [_lectura("week", "23", "a.jpg"), _lectura("week", "23", "b.jpg")]}
    rescatados = rescatar(campos, evidencias, excluir={"week"})
    assert campos["module_part_number"]["valor"] == "2GJ.880.204.J"
    assert campos["week"]["valor"] is None
    assert rescatados == {}


# ------------------------------------------- 10. relleno sobre el libro del usuario (P10)
def _libro_con_casos(claves, casos):
    from openpyxl import Workbook as _WB

    hoja = _WB().active
    for fila, datos in enumerate(casos, start=8):
        for columna, clave in enumerate(claves, start=1):
            hoja.cell(fila, columna).value = datos.get(clave)
    return hoja


def test_emparejar_por_identidad_cuando_el_numero_de_prueba_no_cuadra():
    claves = ("week", "test_reason", "test_number", "temperature_condition",
              "module_part_number", "test_place", "test_date", "module_serial_number")
    hoja = _libro_con_casos(claves, [
        {"week": 22, "test_number": 222504, "temperature_condition": "NT",
         "module_part_number": "2GJ.880.204.J", "test_place": "EDAG",
         "test_date": "2025-05-28", "module_serial_number": "671 ZRZ0539983E"},
        {"week": 23, "test_number": 222550, "temperature_condition": "HT",
         "module_part_number": "2GJ.880.204.J", "test_place": "EDAG",
         "test_date": "2025-06-04", "module_serial_number": "671 ZRZ0539991D"},
    ])
    # la carpeta dice 232550 pero el caso es el mismo: se empareja por identidad
    resultado = {"test_number": "232550", "week": "23", "temperature_condition": "HT",
                 "module_part_number": "2GJ.880.204.J", "test_place": "EDAG",
                 "test_date": "2025-06-04", "module_serial_number": "671 ZRZ0539991D"}
    empareje = relleno_libro.emparejar_filas(hoja, [resultado], claves)
    assert empareje["filas"].get(id(resultado)) == 9
    assert empareje["por_identidad"][0]["resultado"] == "232550"


def test_una_identidad_ambigua_no_empareja_nada():
    claves = ("week", "test_number", "temperature_condition", "module_part_number",
              "test_place")
    hoja = _libro_con_casos(claves, [
        {"week": 23, "test_number": 222550, "temperature_condition": "HT",
         "module_part_number": "2GJ.880.204.J", "test_place": "EDAG"},
        {"week": 23, "test_number": 222551, "temperature_condition": "HT",
         "module_part_number": "2GJ.880.204.J", "test_place": "EDAG"},
    ])
    resultado = {"test_number": "999999", "week": "23", "temperature_condition": "HT",
                 "module_part_number": "2GJ.880.204.J", "test_place": "EDAG"}
    empareje = relleno_libro.emparejar_filas(hoja, [resultado], claves)
    assert id(resultado) not in empareje["filas"]
    assert empareje["sin_fila"] == [resultado]


def test_constantes_confiables_exige_repeticion_y_forma():
    claves = ("test_reason", "engineering_level", "module_part_number")
    hoja = _libro_con_casos(claves, [
        {"test_reason": "IT BMG", "engineering_level": "01S",
         "module_part_number": "2GJ.880.204.J"},
        {"test_reason": "IT BMG", "engineering_level": "01S",
         "module_part_number": "2GJ.880.204.J"},
        {"test_reason": "IT BMG", "engineering_level": "01S",
         "module_part_number": "2GJ.880.204.J"},
        {"test_reason": "IT BMG", "engineering_level": "01S",
         "module_part_number": "2GJ.880.204.J"},
    ])
    fiables = relleno_libro.constantes_confiables(hoja, claves)
    assert fiables["test_reason"]["valor"] == "IT BMG"
    assert fiables["engineering_level"]["valor"] == "01S"
    # con dos filas no se considera constante
    hoja2 = _libro_con_casos(claves, [{"test_reason": "IT BMG"}, {"test_reason": "IT BMG"}])
    assert "test_reason" not in relleno_libro.constantes_confiables(hoja2, claves)
