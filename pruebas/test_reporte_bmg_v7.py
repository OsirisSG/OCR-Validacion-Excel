from pathlib import Path

from openpyxl import load_workbook

from configuracion import cargar_config, cargar_reglas
from reporte_bmg import generar_reporte_bmg


def caso(numero, tipo_st, temp, inflador, apertura):
    campos = {
        "test_number": {"valor": str(numero), "estado": "confirmado"},
        "temperature_condition": {"valor": temp, "estado": "confirmado"},
        "inflator_type": {"valor": inflador, "estado": "confirmado"},
        "opening_time_ms": ({"valor": apertura, "estado": "confirmado"}
                            if apertura is not None else
                            {"valor": None, "estado": "sin_dato"}),
    }
    return {
        "id": f"id-{numero}", "case_key": f"case-{numero}", "nombre": str(numero),
        "identificador": str(numero), "test_number": str(numero), "tipo_st": tipo_st,
        "temperature_condition": temp, "inflator_type": inflador, "campos": campos,
    }


def test_reporte_bmg_combina_1st_2st_y_colorea_apertura(tmp_path):
    raiz = Path(__file__).resolve().parents[1]
    plantilla = raiz / "plantillas" / "reporte_bmg_1st_2st.xlsx"
    salida = tmp_path / "resultado.xlsx"
    resultados = [
        caso(1001, "1ST", "HT", "UGL", 5.8),
        caso(1002, "1ST", "HT", "OGL", 6.5),
        caso(1003, "1ST", "HT", "NOM", 7.2),
        caso(2001, "2ST", "RT", "NOM", None),
    ]
    config, reglas = cargar_config(), cargar_reglas()
    generar_reporte_bmg(plantilla, salida, resultados, config, reglas)

    libro = load_workbook(salida, data_only=False)
    resumen = libro["Übersicht Standversuche"]
    lista = libro["Versuchsmatrix"]

    assert resumen["D16"].value == "1001"
    assert resumen["E16"].value == "1002"
    assert resumen["F16"].value == "1003"
    assert resumen["G42"].value == "2001"

    def rgb(celda):
        return (celda.fill.fgColor.rgb or "")[-6:].upper()

    assert rgb(resumen["D16"]) == config["colores"]["verde"].lstrip("#").upper()
    assert rgb(resumen["E16"]) == config["colores"]["amarillo"].lstrip("#").upper()
    assert rgb(resumen["F16"]) == config["colores"]["rojo"].lstrip("#").upper()
    assert rgb(resumen["G42"]) == config["colores"]["gris"].lstrip("#").upper()

    # El detalle 1ST ocupa su bloque y 2ST inicia en el bloque siguiente.
    assert lista["C8"].value == "1003"
    assert lista["C9"].value == "1002"
    assert lista["C10"].value == "1001"
    assert lista["C58"].value == "2001"
    assert resumen["D16"].hyperlink is not None
    assert "Versuchsmatrix" in resumen["D16"].hyperlink.target
    assert resumen["K17"].value == "=SUM(D17:J17)"


def test_tiempo_en_conflicto_se_muestra_gris(tmp_path):
    raiz = Path(__file__).resolve().parents[1]
    plantilla = raiz / "plantillas" / "reporte_bmg_1st_2st.xlsx"
    salida = tmp_path / "conflicto.xlsx"
    item = caso(3001, "1ST", "HT", "UGL", 5.5)
    item["campos"]["opening_time_ms"]["requiere_revision"] = True
    generar_reporte_bmg(plantilla, salida, [item], cargar_config(), cargar_reglas())
    libro = load_workbook(salida)
    celda = libro["Übersicht Standversuche"]["D16"]
    assert (celda.fill.fgColor.rgb or "")[-6:].upper() == cargar_config()["colores"]["gris"].lstrip("#").upper()
