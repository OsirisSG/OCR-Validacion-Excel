"""Matriz dinámica de apertura: sólo casos reales, sin vacantes inventadas.

Los cupos históricos 5/10 permanecen como metadatos ``esperados``; la UI y el
Excel sólo crean celdas para casos realmente existentes. Los tiempos finales
deben ser finitos y estrictamente positivos.
"""
from dashboard.backend.app import _fila_publica, _matriz_apertura
from utilidades.matriz_apertura import (
    COLUMNAS_MATRIZ,
    celda_caso,
    celda_vacante,
    criterio_desde_limites,
    evaluar_apertura,
    valor_confiable,
)


def fila(numero, tipo_st, temp, inflador, apertura, conflicto=False):
    return {
        "ruta": f"/tmp/{tipo_st}/{numero}", "nombre": str(numero), "identificador": str(numero),
        "test_number": str(numero), "tipo_st": tipo_st, "temperature_condition": temp,
        "inflator_type": inflador, "estado": "procesada", "estado_proceso": "procesada",
        "comparacion": {"resultado": "coincidencia_total"},
        "confianza_ocr_pct": 95.0, "campos": {
            "opening_time_ms": {
                "valor": apertura, "estado": "confirmado_manual",
                "confirmacion_manual": True, "requiere_revision": conflicto,
                "referencia_tiempo_valida": True, "estado_tiempo": "VALIDO",
            },
            "test_number": {"valor": str(numero)},
        },
    }


def _matriz(brutas):
    return _matriz_apertura([_fila_publica(f) for f in brutas])


def test_matriz_expone_siete_columnas_pero_solo_casos_existentes():
    matriz = _matriz([fila(1, "1ST", "HT", "UGL", 5.8)])
    etapa = next(e for e in matriz["etapas"] if e["tipo_st"] == "1ST")
    assert [c["id"] for c in etapa["columnas"]] == [c["id"] for c in COLUMNAS_MATRIZ]
    ht_ugl = next(c for c in etapa["columnas"] if c["id"] == "HT_UGL")
    assert ht_ugl["ocupados"] == 1
    assert ht_ugl["cupos"] == 1 and ht_ugl["esperados"] == 5
    assert len(ht_ugl["celdas"]) == 1
    caso = ht_ugl["celdas"][0]
    assert caso["tipo"] == "caso" and caso["test_number"] == "1"
    assert caso["estado"] == "verde"
    # Los 10 cupos históricos de NT_NOM siguen como metadata, pero no generan
    # casillas ficticias ni grises durante la ejecución.
    nt_nom = next(c for c in etapa["columnas"] if c["id"] == "NT_NOM")
    assert nt_nom["esperados"] == 10 and nt_nom["ocupados"] == 0
    assert nt_nom["cupos"] == 0 and nt_nom["celdas"] == []


def test_vacante_se_diferencia_del_gris_de_caso():
    vacante = celda_vacante(1)
    gris = celda_caso(_fila_publica(fila(4, "2ST", "RT", "NOM", None)),
                      criterio_desde_limites(6.0, 7.0))
    assert vacante["estado"] == "vacante" and gris["estado"] == "gris"
    assert vacante["id"] is None and gris["id"] is not None
    assert vacante["motivo_estado"] == "sin_caso"


def test_semaforo_compartido_y_gris_sin_falsos_ceros():
    brutas = [
        fila(1, "1ST", "HT", "UGL", 6.0),    # verde inclusive
        fila(2, "1ST", "HT", "OGL", 6.5),    # amarillo
        fila(3, "1ST", "HT", "NOM", 7.5),    # rojo
        fila(4, "2ST", "RT", "NOM", None),   # gris sin tiempo
        fila(5, "2ST", "NT", "NOM", 5.0, conflicto=True),  # gris conflicto
        fila(6, "2ST", "NT", "OGL", 0.0),    # 0 ms nunca es apertura final válida
    ]
    publicas = [_fila_publica(f) for f in brutas]
    assert [f["semaforo_apertura"] for f in publicas] == [
        "verde", "amarillo", "rojo", "gris", "gris", "gris"]
    criterio = criterio_desde_limites(6.0, 7.0)
    matriz = _matriz_apertura(publicas)
    celdas = {}
    for e in matriz["etapas"]:
        for col in e["columnas"]:
            for c in col["celdas"]:
                if c["tipo"] == "caso":
                    celdas[str(c["test_number"])] = c
    assert celdas["1"]["estado"] == "verde" and celdas["1"]["opening_time_ms"] == 6.0
    assert celdas["2"]["estado"] == "amarillo"
    assert celdas["3"]["estado"] == "rojo"
    # El gris nunca lleva 0 ni valor inventado: va a tiempo_pendiente_ms o queda vacío.
    assert celdas["4"]["estado"] == "gris"
    assert celdas["4"]["opening_time_ms"] is None
    assert celdas["4"]["motivo_estado"] == "sin_tiempo"
    assert celdas["5"]["estado"] == "gris"
    assert celdas["5"]["opening_time_ms"] is None
    assert celdas["5"]["tiempo_pendiente_ms"] == 5.0
    assert celdas["5"]["motivo_estado"] in {"pendiente_revision", "conflicto"}
    assert celdas["6"]["estado"] == "gris" and celdas["6"]["opening_time_ms"] is None
    assert celdas["6"]["motivo_estado"] == "no_positivo"
    # Contrato directo del evaluador compartido con el Excel.
    assert evaluar_apertura(0.0, criterio) == ("gris", None, "valor_no_positivo")
    assert evaluar_apertura(None, criterio)[2] == "sin_tiempo"
    assert evaluar_apertura(-1, criterio)[2] == "valor_negativo"
    assert valor_confiable({"valor": 5.0, "requiere_revision": True}) is None


def test_expansion_si_hay_mas_casos_que_esperados():
    matriz = _matriz([fila(i, "1ST", "HT", "UGL", 5.8) for i in range(1, 13)])
    ht_ugl = next(c for c in matriz["etapas"][0]["columnas"] if c["id"] == "HT_UGL")
    assert ht_ugl["ocupados"] == 12 and ht_ugl["cupos"] == 12
    assert all(c["tipo"] == "caso" for c in ht_ugl["celdas"])


def test_sin_clasificar_con_causa_y_sin_inventar_posicion():
    brutas = [
        fila(7, "3RD", "HT", "UGL", 5.8),      # etapa fuera de 1ST/2ST
        fila(8, "1ST", "XT", "UGL", 5.8),      # temperatura desconocida
        fila(9, "1ST", "HT", "XYZ", 5.8),      # generador desconocido
    ]
    matriz = _matriz(brutas)
    assert matriz["sin_clasificar"] and not any(
        e["tipo_st"] == "1ST" and any(c["tipo"] == "caso"
                                      for col in e["columnas"] for c in col["celdas"])
        for e in matriz["etapas"])
    fuera = {str(c["test_number"]): c for c in matriz["sin_clasificar"]}
    assert set(fuera) == {"7", "8", "9"}
    assert fuera["7"]["tipo_st"] == "3RD"          # causa a la vista, sin reclasificar
    assert fuera["8"]["temperature_condition"] == "XT"
    assert fuera["9"]["inflator_type"] == "XYZ"
    for c in matriz["sin_clasificar"]:
        assert c["tipo"] == "caso" and c["opening_time_ms"] == 5.8


def test_matriz_vacia_o_solo_fuera_de_casilla():
    assert _matriz_apertura([]) is None
    # Sin ninguna fila reclasificable el backend conserva el grupo «Sin clasificar».
    matriz = _matriz([fila(1, "3RD", "XT", "XYZ", 5.8)])
    assert matriz["etapas"] == []
    assert len(matriz["sin_clasificar"]) == 1
