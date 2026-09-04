"""Adaptador de la plantilla de captura; las claves estables son el contrato."""

from __future__ import annotations

import re
from copy import copy
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo


HOJA_CAPTURA = "Captura_pruebas"
HOJA_DICCIONARIO = "Diccionario_campos"
HOJA_CATALOGOS = "Catalogos"
HOJA_TRAZABILIDAD = "Trazabilidad_OCR"
FILA_CLAVES = 5
FILA_DATOS = 6

COLUMNAS_TRAZABILIDAD = [
    "test_number", "tipo_st", "temperature_condition", "module_version",
    "inflator_type", "fase", "tor", "ruta_absoluta", "ruta_relativa",
    "estado_imagen", "texto_crudo", "confianza_ocr", "coordenadas_roi",
    "zoom_aplicado", "modo_recorte", "dispositivo", "tiempo_deteccion",
    "tiempo_ocr", "campos_detectados", "requiere_revision", "mensaje_error",
    "qr_detectado", "payload_qr", "poligono_qr", "fuente_campo",
    "modelo_ocr", "correccion_confirmada", "dataset_entrenamiento", "estado_cache",
]


def cargar_contrato(ruta_plantilla: str | Path) -> dict:
    libro = load_workbook(ruta_plantilla, data_only=False)
    faltantes = {HOJA_CAPTURA, HOJA_DICCIONARIO, HOJA_CATALOGOS, "Resumen"} - set(libro.sheetnames)
    if faltantes:
        raise ValueError(f"La plantilla no contiene las hojas requeridas: {sorted(faltantes)}")
    captura = libro[HOJA_CAPTURA]
    claves = {}
    for celda in captura[FILA_CLAVES]:
        if celda.value:
            clave = str(celda.value).strip()
            if clave in claves:
                raise ValueError(f"Clave estable duplicada en la plantilla: {clave}")
            claves[clave] = celda.column

    diccionario = libro[HOJA_DICCIONARIO]
    encabezados = {str(c.value).strip(): c.column for c in diccionario[4] if c.value}
    esquema = {}
    for fila in range(5, diccionario.max_row + 1):
        registro = {nombre: diccionario.cell(fila, columna).value
                    for nombre, columna in encabezados.items()}
        clave = str(registro.get("clave_estable") or "").strip()
        if clave:
            esquema[clave] = registro

    catalogos = {}
    hoja_cat = libro[HOJA_CATALOGOS]
    for columna in range(1, hoja_cat.max_column + 1):
        nombre = hoja_cat.cell(1, columna).value
        if isinstance(nombre, str) and nombre.startswith("CAT_"):
            valores = []
            for fila in range(3, hoja_cat.max_row + 1):
                valor = hoja_cat.cell(fila, columna).value
                if valor not in (None, ""):
                    valores.append(str(valor))
            catalogos[nombre] = valores
    return {"claves": claves, "esquema": esquema, "catalogos": catalogos}


def _limites_y_regex(valor) -> tuple[float | None, str | None]:
    if valor in (None, ""):
        return None, None
    texto = str(valor).strip()
    # La celda combina máximo y regex con `` espacio|espacio ``. No dividir
    # alternancias legítimas como ``^(NT|RT|HT)$``.
    partes = [p.strip() for p in re.split(r"\s+\|\s+", texto, maxsplit=1)]
    maximo = None
    patron = None
    try:
        maximo = float(partes[0])
    except ValueError:
        patron = partes[0] if partes[0].startswith("^") else None
    if len(partes) == 2:
        patron = partes[1]
    return maximo, patron


def validar_valor(clave: str, valor, contrato: dict) -> dict:
    regla = contrato["esquema"].get(clave, {})
    if valor in (None, ""):
        return {"valido": str(regla.get("requerido") or "").lower() not in {"sí", "si"},
                "valor": None, "errores": ["campo requerido"] if
                str(regla.get("requerido") or "").lower() in {"sí", "si"} else []}
    tipo = str(regla.get("tipo_esperado") or "string").lower()
    errores = []
    convertido = valor
    try:
        if tipo == "integer":
            convertido = int(float(valor))
        elif tipo == "decimal":
            convertido = float(str(valor).replace(",", "."))
        elif tipo == "date" and isinstance(valor, str):
            convertido = datetime.strptime(valor, "%Y-%m-%d").date()
        elif tipo in {"identifier", "string", "enum"}:
            convertido = str(valor)
    except (TypeError, ValueError):
        errores.append(f"tipo inválido: se esperaba {tipo}")
    catalogo = str(regla.get("valores_o_catalogo") or "")
    if catalogo.startswith("CAT_") and str(convertido) not in contrato["catalogos"].get(catalogo, []):
        errores.append(f"fuera de catálogo {catalogo}")
    minimo = regla.get("minimo")
    maximo, patron = _limites_y_regex(regla.get("maximo_regex"))
    if isinstance(convertido, (int, float)):
        if minimo not in (None, "") and convertido < float(minimo):
            errores.append(f"menor que {minimo}")
        if maximo is not None and convertido > maximo:
            errores.append(f"mayor que {maximo:g}")
    if patron and not re.fullmatch(patron, str(valor)):
        errores.append("no cumple la expresión regular")
    return {"valido": not errores, "valor": convertido, "errores": errores}


def _copiar_fila_modelo(hoja, origen: int, destino: int) -> None:
    hoja.row_dimensions[destino].height = hoja.row_dimensions[origen].height
    for columna in range(1, hoja.max_column + 1):
        src, dst = hoja.cell(origen, columna), hoja.cell(destino, columna)
        if src.has_style:
            dst._style = copy(src._style)
        dst.number_format = src.number_format
        dst.alignment = copy(src.alignment)
        dst.protection = copy(src.protection)


def _extender_validaciones(hoja, ultima_fila: int) -> None:
    for validacion in hoja.data_validations.dataValidation:
        nuevos = []
        for rango in validacion.ranges.ranges:
            if rango.min_row <= FILA_DATOS and rango.max_row >= FILA_DATOS:
                nuevos.append(f"{get_column_letter(rango.min_col)}{rango.min_row}:"
                              f"{get_column_letter(rango.max_col)}{max(rango.max_row, ultima_fila)}")
            else:
                nuevos.append(str(rango))
        validacion.sqref = " ".join(nuevos)


def _actualizar_resumen(libro, ultima_fila: int) -> None:
    hoja = libro["Resumen"]
    for fila in hoja.iter_rows():
        for celda in fila:
            if isinstance(celda.value, str) and celda.value.startswith("="):
                celda.value = re.sub(
                    r"(Captura_pruebas!\$[A-Z]+\$6:\$[A-Z]+\$)\d+\b",
                    rf"\g<1>{ultima_fila}", celda.value)


def generar_desde_plantilla(ruta_plantilla: str | Path, ruta_salida: str | Path,
                            resultados: list[dict]) -> Path:
    contrato = cargar_contrato(ruta_plantilla)
    libro = load_workbook(ruta_plantilla)
    hoja = libro[HOJA_CAPTURA]
    ultima = max(FILA_DATOS, FILA_DATOS + len(resultados) - 1)
    if ultima > hoja.max_row:
        for fila in range(hoja.max_row + 1, ultima + 1):
            _copiar_fila_modelo(hoja, FILA_DATOS, fila)
    # La salida corresponde a esta ejecución; se conservan estilos, no datos anteriores.
    for fila in range(FILA_DATOS, max(hoja.max_row, ultima) + 1):
        for columna in contrato["claves"].values():
            hoja.cell(fila, columna).value = None

    for numero, resultado in enumerate(resultados, start=FILA_DATOS):
        campos = resultado.get("campos") or resultado.get("consolidado", {}).get("campos", {})
        for clave, columna in contrato["claves"].items():
            valor = campos.get(clave, {})
            valor = valor.get("valor") if isinstance(valor, dict) else valor
            validacion = validar_valor(clave, valor, contrato)
            # Se conserva vacío cuando un candidato viola el contrato; la evidencia queda en trazabilidad.
            celda = hoja.cell(numero, columna)
            celda.value = validacion["valor"] if validacion["valido"] else None
            tipo = str(contrato["esquema"].get(clave, {}).get("tipo_esperado") or "")
            if tipo in {"identifier", "string", "enum"}:
                celda.number_format = "@"
            elif tipo == "date":
                celda.number_format = "yyyy-mm-dd"

    _extender_validaciones(hoja, ultima)
    ultima_columna = get_column_letter(max(contrato["claves"].values()))
    for tabla in hoja.tables.values():
        inicio = tabla.ref.split(":")[0]
        tabla.ref = f"{inicio}:{ultima_columna}{ultima}"
    _actualizar_resumen(libro, ultima)

    if HOJA_TRAZABILIDAD in libro.sheetnames:
        del libro[HOJA_TRAZABILIDAD]
    traza = libro.create_sheet(HOJA_TRAZABILIDAD)
    fill = PatternFill("solid", fgColor="1F4E78")
    for columna, nombre in enumerate(COLUMNAS_TRAZABILIDAD, start=1):
        celda = traza.cell(1, columna, nombre)
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = fill
        traza.column_dimensions[get_column_letter(columna)].width = (
            46 if "ruta" in nombre else 50 if nombre == "texto_crudo" else 20)
    for resultado in resultados:
        for evidencia in resultado.get("trazabilidad", []):
            traza.append([
                ", ".join(evidencia.get(nombre, [])) if isinstance(evidencia.get(nombre), list)
                else str(evidencia.get(nombre)) if isinstance(evidencia.get(nombre), tuple)
                else evidencia.get(nombre)
                for nombre in COLUMNAS_TRAZABILIDAD
            ])
    traza.freeze_panes = "A2"
    ultima_traza = get_column_letter(len(COLUMNAS_TRAZABILIDAD))
    traza.auto_filter.ref = f"A1:{ultima_traza}{max(traza.max_row, 1)}"
    if traza.max_row >= 2:
        tabla = Table(displayName="TablaTrazabilidadOCR", ref=f"A1:{ultima_traza}{traza.max_row}")
        tabla.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        traza.add_table(tabla)
    for fila in traza.iter_rows(min_row=2):
        for celda in fila:
            celda.alignment = Alignment(vertical="top", wrap_text=True)

    # Excel/LibreOffice deben recalcular el resumen al abrir la salida.
    libro.calculation.fullCalcOnLoad = True
    libro.calculation.forceFullCalc = True
    libro.calculation.calcMode = "auto"

    ruta_salida = Path(ruta_salida)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    libro.save(ruta_salida)
    return ruta_salida
