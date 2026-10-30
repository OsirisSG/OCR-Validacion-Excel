from dashboard.backend.app import _fila_publica, _matriz_apertura


def fila(numero, tipo_st, temp, inflador, apertura, conflicto=False, manual=False):
    campo = {"valor": apertura, "estado": "confirmado", "requiere_revision": conflicto}
    if manual:
        # R15 (SUPERSEDE documentado): confirmación humana con referencia
        # temporal validada (VERIFICADO_HUMANO), único camino que colorea.
        campo["confirmacion_manual"] = True
        campo["referencia_tiempo_valida"] = True
    return {
        "ruta": f"/tmp/{tipo_st}/{numero}", "nombre": str(numero), "identificador": str(numero),
        "test_number": str(numero), "tipo_st": tipo_st, "temperature_condition": temp,
        "inflator_type": inflador, "comparacion": {"resultado": "coincidencia_total"},
        "confianza_ocr_pct": 95.0, "campos": {
            "opening_time_ms": campo,
            "test_number": {"valor": str(numero)},
        },
    }


def test_matriz_dashboard_apertura_y_gris_desconocido():
    """R15 (SUPERSEDE documentado del contrato V7).

    En V7 un campo ``opening_time_ms`` con ``estado: confirmado`` bastaba
    para colorear por umbral numérico. Desde V15.10 el semáforo es autónomo
    y basado en evidencia: sólo confirmaciones humanas (VERIFICADO_HUMANO) o
    resultados AUTO_VERIFICABLES con referencia temporal validada colorean;
    propuestas, conflictos y ausencias quedan GRISES sin borrar la evidencia
    (PLAN_CORRECCION_R10 reglas 8-9; PLAN_CORRECCION_R13 §Semáforo:
    «gris: caso ya evaluado pero sin tiempo defendible, en conflicto o con
    referencia temporal insuficiente»). Las filas 1-3 ejercitan ahora colores
    con confirmación humana explícita; 4 (sin dato) y 5 (conflicto) siguen
    en gris por abstención. La estructura de la matriz (etapas/columnas/
    celdas) se conserva intacta.
    """
    brutas = [
        fila(1, "1ST", "HT", "UGL", 6.0, manual=True),
        fila(2, "1ST", "HT", "OGL", 6.3, manual=True),
        fila(3, "1ST", "HT", "NOM", 7.1, manual=True),
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
