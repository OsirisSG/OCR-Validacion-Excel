from dashboard.backend.app import _fila_publica, _matriz_apertura


def fila(numero, tipo_st, temp, inflador, apertura, conflicto=False):
    return {
        "ruta": f"/tmp/{tipo_st}/{numero}", "nombre": str(numero), "identificador": str(numero),
        "test_number": str(numero), "tipo_st": tipo_st, "temperature_condition": temp,
        "inflator_type": inflador, "comparacion": {"resultado": "coincidencia_total"},
        "confianza_ocr_pct": 95.0, "campos": {
            "opening_time_ms": {"valor": apertura, "estado": "confirmado",
                                "requiere_revision": conflicto},
            "test_number": {"valor": str(numero)},
        },
    }


def test_matriz_dashboard_apertura_y_gris_desconocido():
    brutas = [
        fila(1, "1ST", "HT", "UGL", 6.0),
        fila(2, "1ST", "HT", "OGL", 6.3),
        fila(3, "1ST", "HT", "NOM", 7.1),
        fila(4, "2ST", "RT", "NOM", None),
        fila(5, "2ST", "NT", "NOM", 5.0, conflicto=True),
    ]
    publicas = [_fila_publica(f) for f in brutas]
    assert [f["semaforo_apertura"] for f in publicas] == ["verde", "amarillo", "rojo", "gris", "gris"]
    matriz = _matriz_apertura(publicas)
    assert {e["tipo_st"] for e in matriz["etapas"]} == {"1ST", "2ST"}
    primera = matriz["etapas"][0]["columnas"][0]["celdas"][-1]
    assert primera["test_number"] == "1"
    assert primera["estado"] == "verde"
