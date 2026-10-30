"""Reglas de la guía: fuentes explícitas, componentes separados y conflictos."""

import pytest

import flujo_empresarial
from flujo_empresarial import (CacheOCR, consolidar_caso,
                               extraer_candidatos_texto, interpretar_fecha_impresa)


def extraer(texto, imagen=None, contexto=None):
    return extraer_candidatos_texto(
        texto, {"ruta_relativa": "etiqueta.jpg", "confianza_ocr": .96, **(imagen or {})},
        {"project_id": "guia", "case_key": "guia|1ST|232541", **(contexto or {})})


def valores(evidencias, clave):
    return [e["valor_normalizado"] for e in evidencias if e["clave"] == clave]


def caso():
    return {"project_id": "guia", "case_key": "guia|1ST|232541", "tipo_st": "1ST",
            "ruta_relativa": "232541", "metadata_ruta": {}}


def test_overlay_edag_fecha_mes_escrito_semana_y_numero():
    evidencias = extraer("EDAG Testlab\n04 JUN 25\n232541")
    assert valores(evidencias, "test_place") == ["EDAG"]
    assert valores(evidencias, "test_number") == ["232541"]
    assert valores(evidencias, "test_date") == ["2025-06-04"]
    assert valores(evidencias, "week") == ["23"]
    fecha = next(e for e in evidencias if e["clave"] == "test_date")
    assert fecha["valor_original"] == "04 JUN 25"
    salida = consolidar_caso(caso(), evidencias, requeridos={"test_number"})
    assert "week" not in salida["conflictos"]


@pytest.mark.parametrize("fecha", ["11 JUN 25", "03 JUN 26"])
def test_fecha_prueba_contraria_a_semana_o_anio_edag_queda_conflicto(fecha):
    evidencias = extraer(f"EDAG Testlab\n{fecha}\n232541")
    salida = consolidar_caso(caso(), evidencias, requeridos={"week"})
    assert "week" in salida["conflictos"]
    assert salida["campos"]["week"]["valor"] is None
    assert salida["campos"]["week"]["requiere_revision"] is True


def test_numero_no_identifica_semana_edag_sin_laboratorio():
    assert valores(extraer("232541"), "week") == []
    assert valores(extraer("EDAG Testlab\n992541\n002541\n232500"), "week") == []
    assert valores(extraer("EDAG Testlab\nAIRBAG\nSERIAL: 232541"), "week") == []


def test_vw_como_prueba_y_vw_ag_fabricante_no_se_confunden():
    assert valores(extraer("TEST VW123456"), "test_place") == ["VW"]
    assert valores(extraer("TEST VW123456"), "test_number") == ["VW123456"]
    assert valores(extraer("AIRBAG VW AG\n2GJ 880 204 J"), "test_place") == []
    assert valores(extraer("AIRBAG VW AG\n2GJ 880 204 J"), "week") == []
    assert valores(extraer("AIRBAG\nSERIAL: VW123456"), "test_place") == []
    assert valores(extraer("TEST DATE: 2025-06-04", contexto={"laboratorio": "VW"}),
                   "test_place") == ["VW"]


def test_airbag_proveedor_numero_parte_e_ingenieria_separados_de_tablero():
    evidencias = extraer("AIRBAG PAB\nAutoliv\n2GJ 880 204 J\n02S\nSERIAL: *00 AB12*")
    assert valores(evidencias, "module_part_number") == ["2GJ.880.204.J"]
    assert valores(evidencias, "inflator_supplier") == ["Autoliv"]
    assert valores(evidencias, "engineering_level") == ["02S"]
    assert valores(evidencias, "module_serial_number") == ["*00 AB12*"]
    assert valores(evidencias, "dashboard_engineering_level") == []
    assert valores(evidencias, "laser_opening") == []
    assert valores(evidencias, "delay_ms") == []


def test_nivel_prototipo_y_numero_compacto_tablero_requieren_componente():
    bolsa = extraer("2GJ 880 204 J\n69K", imagen={"componente": "bolsa_aire"})
    assert valores(bolsa, "engineering_level") == ["69K"]
    tablero = extraer("2GJ857003\n03S\nSERIAL: 00001234", imagen={"componente": "tablero"})
    assert valores(tablero, "dashboard_part_number") == ["2GJ.857.003"]
    assert valores(tablero, "dashboard_engineering_level") == ["03S"]
    assert valores(tablero, "dashboard_serial_number") == ["00001234"]
    assert valores(extraer("2GJ857003 03S"), "dashboard_part_number") == []
    assert valores(extraer("2GJ857003 03S"), "engineering_level") == []
    # El formato separado conserva compatibilidad con el parser empresarial V8.
    assert valores(extraer("2GJ 880 204 J"), "module_part_number") == ["2GJ.880.204.J"]


def test_dos_componentes_en_misma_imagen_no_intercambian_ingenieria():
    evidencias = extraer("AIRBAG\n2GJ 880 204 J\n02S\n\nTABLERO\n2GJ857003\n03S")
    assert valores(evidencias, "engineering_level") == ["02S"]
    assert valores(evidencias, "dashboard_engineering_level") == ["03S"]
    assert valores(evidencias, "module_part_number") == ["2GJ.880.204.J"]
    assert valores(evidencias, "dashboard_part_number") == ["2GJ.857.003"]


def test_formato_dmy_declarado_conserva_originales_y_conflictos_de_etiquetas():
    evidencias = extraer("AIRBAG\n10.04.25\n11/04/2025", contexto={"formato_fecha": "DMY"})
    assert valores(evidencias, "module_date") == ["2025-04-10", "2025-04-11"]
    assert [e["valor_original"] for e in evidencias if e["clave"] == "module_date"] == [
        "10.04.25", "11/04/2025"]
    salida = consolidar_caso(caso(), evidencias, requeridos={"module_date"})
    assert salida["campos"]["module_date"]["estado"] == "conflicto"
    assert salida["campos"]["module_date"]["valor"] is None


def test_fechas_sin_formato_no_se_adivinan_por_proveedor():
    evidencias = extraer("AIRBAG AUTOLIV\n10.04.25\n11/04/2025")
    assert valores(evidencias, "module_date") == []
    assert valores(evidencias, "_fecha_ambigua") == ["10.04.25", "11/04/2025"]
    assert interpretar_fecha_impresa("25-06-19")["estado"] == "ambigua"
    assert interpretar_fecha_impresa("2025-06-19")["interpretacion"] == "2025-06-19"


@pytest.mark.parametrize("imagen,contexto", [
    ({"componente": "tablero", "formato_fecha": "DMY"}, {}),
    ({}, {"perfil_extraccion": {"componente": "tablero", "formato_fecha": "DMY"}}),
])
def test_opciones_imagen_y_perfil_respetan_fecha_y_componente(imagen, contexto):
    evidencias = extraer("03S\n10.04.25", imagen=imagen, contexto=contexto)
    assert valores(evidencias, "dashboard_date") == ["2025-04-10"]
    assert valores(evidencias, "dashboard_engineering_level") == ["03S"]


def test_formato_escrito_y_delay_solo_explicito():
    assert valores(extraer("TABLERO DMY\n10.04.25"), "dashboard_date") == ["2025-04-10"]
    assert valores(extraer("AIRBAG 2GJ 880 204 J\nDELAY: 3,2 ms"), "delay_ms") == ["3.2"]
    assert valores(extraer("AIRBAG 2GJ 880 204 J 3,2 ms"), "delay_ms") == []
    assert interpretar_fecha_impresa("31.02.25", formato="DMY")["estado"] == "invalida"


def test_apertura_conserva_supervision():
    evidencias = extraer("OPENING 5.8 ms")
    apertura = next(e for e in evidencias if e["clave"] == "opening_time_ms")
    assert apertura["requiere_confirmacion_manual"] is True
    assert consolidar_caso(caso(), evidencias, requeridos={"opening_time_ms"})[
        "campos"]["opening_time_ms"]["valor"] is None


def test_motivo_acepta_proyecto_explicito_no_nombre_interno():
    evidencias = extraer("PROYECTO: BMG\n232541")
    assert valores(evidencias, "test_reason") == ["BMG"]
    assert valores(extraer("BMG", contexto={"project_id": "BMG"}), "test_reason") == []
    assert valores(extraer("PROJECT: VW316/5"), "test_reason") == ["VW316/5"]


def test_serial_prototipo_conserva_guiones_y_fuente_pn_alv_exige_confirmacion():
    texto = "AIRBAG MODULE\nSERIAL: X651538300C-01-16"
    assert valores(extraer(texto), "module_serial_number") == ["X651538300C-01-16"]
    propuesta = extraer("MODULE: VW316 PAB\nP/N ALV: X651538300C-01-16\nPROTOTYPES")
    assert valores(propuesta, "module_serial_number") == ["X651538300C-01-16"]
    assert propuesta[-1]["requiere_confirmacion_manual"] is True
    salida = consolidar_caso(caso(), propuesta, requeridos={"module_serial_number"})
    assert salida["campos"]["module_serial_number"]["valor"] is None


def test_nomenclatura_nueva_ingenieria_y_laser_del_tablero_son_revisables():
    evidencias = extraer("TABLERO\nNIVEL DE INGENIERÍA: P7-X\nAPERTURA LÁSER: SI")
    assert valores(evidencias, "dashboard_engineering_level") == ["P7-X"]
    assert valores(evidencias, "laser_opening") == ["SI"]
    assert all(e["requiere_confirmacion_manual"] for e in evidencias)
    salida = consolidar_caso(caso(), evidencias, requeridos=set())
    assert salida["campos"]["dashboard_engineering_level"]["valor"] is None
    assert salida["campos"]["laser_opening"]["valor"] is None
    assert salida["campos"]["dashboard_engineering_level"]["requiere_revision"] is True
    assert salida["campos"]["laser_opening"]["pendiente_confirmacion_manual"] is True
    assert salida["requiere_revision"] is True
    assert valores(extraer("TABLERO 2GJ857003 03S"), "laser_opening") == []
    assert valores(extraer("AIRBAG\nAPERTURA LÁSER: SI"), "laser_opening") == []


def test_version_parser_invalida_cache_anterior(tmp_path, monkeypatch):
    ruta = tmp_path / "foto.jpg"
    ruta.write_bytes(b"imagen")
    cache = CacheOCR(tmp_path / "imagenes.sqlite3", {})
    version_actual = flujo_empresarial.VERSION_PARSER
    monkeypatch.setattr(flujo_empresarial, "VERSION_PARSER", "empresarial-4-regiones-independientes")
    cache.guardar(ruta, {"texto_completo": "2GJ857003"})
    assert cache.obtener(ruta) is not None
    monkeypatch.setattr(flujo_empresarial, "VERSION_PARSER", version_actual)
    assert cache.obtener(ruta) is None


def test_pipeline_conecta_perfil_de_extraccion_sin_modelo_real(tmp_path, monkeypatch):
    import validacion
    from estructura import guardar_estructura, mapear_estructura

    raiz = tmp_path / "Proyecto_1ST"
    carpeta = raiz / "HT" / "232541 RDW NOM HT" / "PHOTOS"
    (carpeta / "NACH").mkdir(parents=True)
    (carpeta / "VOR").mkdir()
    foto = carpeta / "NACH" / "etiqueta.jpg"
    foto.write_bytes(b"imagen de prueba sin OCR real")
    estructura = guardar_estructura(mapear_estructura(raiz), tmp_path / "estructura.json")

    def motor_simulado(ruta, _config, **_kwargs):
        return {"imagen": ruta, "texto_completo": "AIRBAG\n10.04.25\n02S",
                "tokens": [], "lineas_texto": [], "confianza_media": .96,
                "dimensiones": [100, 50], "estado_imagen": "procesada_con_texto"}

    monkeypatch.setattr(validacion, "extraer_texto_empresarial", motor_simulado)
    config = {"fase1": {}, "ocr": {}, "normalizacion": {},
              "aprendizaje": {"directorio": str(tmp_path / "aprendizaje")},
              "empresarial": {
                  "perfil_extraccion": {"formato_fecha": "DMY"},
                  "archivo_cache": str(tmp_path / "imagenes.sqlite3"),
                  "archivo_avance_ids": str(tmp_path / "avances.json"),
                  "base_conocimiento": str(tmp_path / "base.json")}}
    resultado = validacion.validar_lote_empresarial(
        estructura, config, archivo_salida=tmp_path / "resultado.json", contenido="fotos")
    campos = resultado["resultados"][0]["campos"]
    assert campos["module_date"]["valor"] == "2025-04-10"
    assert campos["engineering_level"]["valor"] == "02S"
