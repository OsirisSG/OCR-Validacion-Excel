"""Generador del reporte BMG 1ST + 2ST basado en la plantilla de validación.

Mantiene el aspecto del libro de referencia (Resumen / Versuchsmatrix) y usa
los campos consolidados del flujo empresarial. La matriz del resumen muestra
el estado del tiempo de apertura:
  verde <= 6 ms; amarillo > 6 y <= 7 ms; rojo > 7 ms; gris desconocido.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from openpyxl import load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import PatternFill

from configuracion import evaluar_criterio
from flujo_empresarial import CLAVES_PLANTILLA

HOJA_RESUMEN = "Übersicht Standversuche"
HOJA_LISTA = "Versuchsmatrix"
HOJA_RANGOS = "Rangos"
FILA_1ST_INICIO = 8
FILA_1ST_FIN = 57
FILA_2ST_INICIO = 58
FILA_2ST_FIN = 107

# Orden de la lista detallada en el archivo de referencia.
ORDEN_LISTA = {
    ("NT", "NOM"): 0,
    ("NT", "OGL"): 1,
    ("NT", "UGL"): 2,
    ("HT", "NOM"): 3,
    ("HT", "OGL"): 4,
    ("HT", "UGL"): 5,
    ("RT", "NOM"): 6,
}

# Orden visual de la matriz resumen (izquierda -> derecha).
COLUMNAS_MATRIZ = [
    {"col": "D", "temperature_condition": "HT", "inflator_type": "UGL", "esperados": 5},
    {"col": "E", "temperature_condition": "HT", "inflator_type": "OGL", "esperados": 5},
    {"col": "F", "temperature_condition": "HT", "inflator_type": "NOM", "esperados": 10},
    {"col": "G", "temperature_condition": "RT", "inflator_type": "NOM", "esperados": 10},
    {"col": "H", "temperature_condition": "NT", "inflator_type": "NOM", "esperados": 10},
    {"col": "I", "temperature_condition": "NT", "inflator_type": "OGL", "esperados": 5},
    {"col": "J", "temperature_condition": "NT", "inflator_type": "UGL", "esperados": 5},
]


def _campo(resultado: dict, clave: str):
    dato = (resultado.get("campos") or {}).get(clave)
    if isinstance(dato, dict):
        return dato.get("valor")
    if dato not in (None, ""):
        return dato
    if clave in resultado:
        return resultado.get(clave)
    return (resultado.get("metadata_ruta") or {}).get(clave)


def _campo_confiable(resultado: dict, clave: str):
    dato = (resultado.get("campos") or {}).get(clave)
    if isinstance(dato, dict):
        if dato.get("requiere_revision") or dato.get("estado") in {"conflicto", "pendiente_revision"}:
            return None
        return dato.get("valor")
    return dato


def _numero(valor):
    if isinstance(valor, bool) or valor in (None, "", "--", "-"):
        return None
    try:
        return float(str(valor).strip().replace(",", ".").replace(" ms", "").replace("ms", ""))
    except (TypeError, ValueError):
        return None


def _test_sort(resultado: dict):
    valor = resultado.get("test_number") or _campo(resultado, "test_number") or resultado.get("identificador")
    try:
        return (0, int(str(valor).strip()))
    except (TypeError, ValueError):
        return (1, str(valor or ""))


def _ordenar_etapa(resultados: Iterable[dict]) -> list[dict]:
    return sorted(
        resultados,
        key=lambda r: (
            ORDEN_LISTA.get((str(r.get("temperature_condition") or _campo(r, "temperature_condition") or "").upper(),
                             str(r.get("inflator_type") or _campo(r, "inflator_type") or "").upper()), 99),
            _test_sort(r),
        ),
    )


def _estado_apertura(resultado: dict, reglas: dict) -> tuple[str, float | None]:
    valor = _numero(_campo_confiable(resultado, "opening_time_ms"))
    if valor is None:
        return "gris", None
    criterio = (reglas.get("criterios") or {}).get("tiempo_apertura_ms") or {
        "verde": "<= 6", "amarillo": "6-7", "rojo": "> 7"
    }
    return evaluar_criterio(criterio, valor) or "gris", valor


def _relleno(hex_color: str) -> PatternFill:
    return PatternFill("solid", fgColor=hex_color.lstrip("#"))


def _escribir_fila(hoja, fila: int, resultado: dict) -> None:
    for indice, clave in enumerate(CLAVES_PLANTILLA, start=1):
        hoja.cell(fila, indice).value = _campo(resultado, clave)


def _limpiar_fila_datos(hoja, inicio: int = 8, fin: int = 107) -> None:
    for fila in range(inicio, fin + 1):
        for columna in range(1, 56):  # A:BC
            hoja.cell(fila, columna).value = None


def _poblar_lista(hoja, resultados: list[dict]) -> dict[str, int]:
    _limpiar_fila_datos(hoja)
    mapa_filas: dict[str, int] = {}
    por_st = {
        "1ST": _ordenar_etapa([r for r in resultados if str(r.get("tipo_st") or "").upper() == "1ST"]),
        "2ST": _ordenar_etapa([r for r in resultados if str(r.get("tipo_st") or "").upper() == "2ST"]),
    }
    bloques = {"1ST": (FILA_1ST_INICIO, FILA_1ST_FIN), "2ST": (FILA_2ST_INICIO, FILA_2ST_FIN)}
    for tipo_st, filas in por_st.items():
        inicio, fin = bloques[tipo_st]
        capacidad = fin - inicio + 1
        if len(filas) > capacidad:
            raise ValueError(f"El reporte BMG soporta hasta {capacidad} casos {tipo_st}; llegaron {len(filas)}.")
        for offset, resultado in enumerate(filas):
            fila = inicio + offset
            _escribir_fila(hoja, fila, resultado)
            mapa_filas[str(resultado.get("id") or resultado.get("case_key") or resultado.get("test_number") or fila)] = fila
            # Mapeo alterno por número de prueba para el resumen.
            test_number = resultado.get("test_number") or _campo(resultado, "test_number")
            if test_number not in (None, ""):
                mapa_filas[f"test:{test_number}"] = fila
    return mapa_filas


def _copiar_lista_a_rangos(libro, resultados: list[dict]) -> None:
    if HOJA_RANGOS not in libro.sheetnames:
        return
    hoja = libro[HOJA_RANGOS]
    _limpiar_fila_datos(hoja)
    por_st = {
        "1ST": _ordenar_etapa([r for r in resultados if str(r.get("tipo_st") or "").upper() == "1ST"]),
        "2ST": _ordenar_etapa([r for r in resultados if str(r.get("tipo_st") or "").upper() == "2ST"]),
    }
    for tipo_st, filas in por_st.items():
        inicio = FILA_1ST_INICIO if tipo_st == "1ST" else FILA_2ST_INICIO
        for offset, resultado in enumerate(filas[:50]):
            _escribir_fila(hoja, inicio + offset, resultado)


def _poblar_matriz(hoja, tipo_st: str, resultados: list[dict], fila_inicio: int,
                   mapa_filas: dict[str, int], colores: dict, reglas: dict) -> None:
    verde = colores.get("verde", "#00B050")
    amarillo = colores.get("amarillo", "#FFD966")
    rojo = colores.get("rojo", "#FF0000")
    gris = colores.get("gris", "#A6A6A6")
    mapa_color = {"verde": verde, "amarillo": amarillo, "rojo": rojo, "gris": gris}

    etapa = [r for r in resultados if str(r.get("tipo_st") or "").upper() == tipo_st]
    for spec in COLUMNAS_MATRIZ:
        grupo = [r for r in etapa
                 if str(r.get("temperature_condition") or _campo(r, "temperature_condition") or "").upper() == spec["temperature_condition"]
                 and str(r.get("inflator_type") or _campo(r, "inflator_type") or "").upper() == spec["inflator_type"]]
        grupo = sorted(grupo, key=_test_sort, reverse=True)
        # La referencia alinea grupos de 5 en la parte inferior de una matriz de 10 filas.
        alto = 10
        arranque = fila_inicio + max(0, alto - len(grupo))
        for r in range(fila_inicio, fila_inicio + alto):
            celda = hoja[f"{spec['col']}{r}"]
            celda.value = None
            celda.hyperlink = None
            celda.comment = None
            celda.fill = PatternFill(fill_type=None)
        for indice, resultado in enumerate(grupo[:alto]):
            fila = arranque + indice
            celda = hoja[f"{spec['col']}{fila}"]
            test_number = resultado.get("test_number") or _campo(resultado, "test_number") or resultado.get("identificador")
            celda.value = test_number
            estado, tiempo = _estado_apertura(resultado, reglas)
            celda.fill = _relleno(mapa_color[estado])
            detalle_fila = mapa_filas.get(f"test:{test_number}")
            if detalle_fila:
                celda.hyperlink = f"#'{HOJA_LISTA}'!C{detalle_fila}"
            descripcion = "Tiempo de apertura no disponible" if tiempo is None else f"Tiempo de apertura: {tiempo:g} ms"
            celda.comment = Comment(f"{descripcion}\nEstado: {estado}", "OCR")


def generar_reporte_bmg(ruta_plantilla: str | Path, ruta_salida: str | Path,
                        resultados: list[dict], config: dict, reglas: dict) -> Path:
    """Genera un único Excel con 1ST + 2ST y matriz de apertura clicable."""
    ruta_plantilla = Path(ruta_plantilla)
    libro = load_workbook(ruta_plantilla)
    faltantes = {HOJA_RESUMEN, HOJA_LISTA} - set(libro.sheetnames)
    if faltantes:
        raise ValueError(f"La plantilla BMG no contiene las hojas requeridas: {sorted(faltantes)}")

    hoja_lista = libro[HOJA_LISTA]
    mapa_filas = _poblar_lista(hoja_lista, resultados)
    _copiar_lista_a_rangos(libro, resultados)

    hoja_resumen = libro[HOJA_RESUMEN]
    _poblar_matriz(hoja_resumen, "1ST", resultados, 7, mapa_filas,
                   config.get("colores", {}), reglas)
    _poblar_matriz(hoja_resumen, "2ST", resultados, 33, mapa_filas,
                   config.get("colores", {}), reglas)

    # Leyenda: se conserva la original y se añade el estado desconocido.
    hoja_resumen["B25"].fill = _relleno(config.get("colores", {}).get("gris", "#A6A6A6"))
    hoja_resumen["C25"] = "Unknown / pending"

    # Recalcular fórmulas del libro al abrirlo.
    libro.calculation.fullCalcOnLoad = True
    libro.calculation.forceFullCalc = True
    libro.calculation.calcMode = "auto"

    destino = Path(ruta_salida)
    destino.parent.mkdir(parents=True, exist_ok=True)
    libro.save(destino)
    return destino
