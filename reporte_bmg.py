"""Generador del reporte BMG 1ST + 2ST basado en la plantilla de validación.

Mantiene el aspecto del libro de referencia (Resumen / Versuchsmatrix) y usa
los campos consolidados del flujo empresarial. La matriz del resumen muestra
el estado del tiempo de apertura:
  verde <= 6 ms; amarillo > 6 y <= 7 ms; rojo > 7 ms; gris desconocido.
"""

from __future__ import annotations

import copy
import os
import time
from pathlib import Path
from typing import Iterable

from openpyxl import load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

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


TEXTOS = {
    "es": {"overview":"Resumen de resultados","opening":"Tiempo de apertura","unknown":"Desconocido / pendiente","state":"Estado","trace":"Trazabilidad","dictionary":"Diccionario de datos","project":"Proyecto","stage":"Etapa","case":"Caso","component":"Componente","field":"Campo","image":"Imagen","region":"Región original","original":"Texto OCR original","corrected":"Texto corregido","orientation":"Orientación","rule":"Regla","source":"Fuente","version":"Versión de procesamiento","header":"Encabezado","origin_rule":"Origen / regla","status":"Estado de fuente","pending":"Pendiente de fuente o confirmación manual","test_temperature":"Temperatura de prueba","generator_type":"Tipo de generador","ok_test":"OK Test","ma_test":"m.A. Test","nio_test":"N.i.O Test"},
    "en": {"overview":"Overview results","opening":"Opening time","unknown":"Unknown / pending","state":"State","trace":"Traceability","dictionary":"Data dictionary","project":"Project","stage":"Stage","case":"Case","component":"Component","field":"Field","image":"Image","region":"Original region","original":"Original OCR text","corrected":"Corrected text","orientation":"Orientation","rule":"Rule","source":"Source","version":"Processing version","header":"Header","origin_rule":"Origin / rule","status":"Source status","pending":"Pending source or manual confirmation","test_temperature":"Test temperature","generator_type":"Generator type","ok_test":"OK test","ma_test":"Conditional test","nio_test":"NOK test"},
    "de": {"overview":"Übersicht Ergebnisse","opening":"Öffnungszeit","unknown":"Unbekannt / ausstehend","state":"Status","trace":"Rückverfolgbarkeit","dictionary":"Datenwörterbuch","project":"Projekt","stage":"Stufe","case":"Fall","component":"Komponente","field":"Feld","image":"Bild","region":"Originalbereich","original":"Original OCR-Text","corrected":"Korrigierter Text","orientation":"Orientierung","rule":"Regel","source":"Quelle","version":"Verarbeitungsversion","header":"Überschrift","origin_rule":"Quelle / Regel","status":"Quellenstatus","pending":"Quelle oder manuelle Bestätigung ausstehend","test_temperature":"Prüftemperatur","generator_type":"Generatortyp","ok_test":"OK Test","ma_test":"m.A. Test","nio_test":"N.i.O Test"},
}

HEADERS = {
    "test_number":{"es":"Número de prueba","en":"Test number","de":"Versuchsnummer"},
    "test_date":{"es":"Fecha de prueba","en":"Test date","de":"Testdatum"},
    "temperature_condition":{"es":"Temperatura","en":"Temperature","de":"Temperatur"},
    "module_part_number":{"es":"PAB · Número de parte","en":"PAB · Part number","de":"PAB · Teilnummer"},
    "module_serial_number":{"es":"PAB · Serie","en":"PAB · Serial","de":"PAB · Seriennummer"},
    "module_date":{"es":"PAB · Fecha fabricación","en":"PAB · Manufacturing date","de":"PAB · Fertigungsdatum"},
    "dashboard_part_number":{"es":"Tablero · Número de parte","en":"Dashboard · Part number","de":"I-Tafel · Teilnummer"},
    "dashboard_serial_number":{"es":"Tablero · Serie","en":"Dashboard · Serial","de":"I-Tafel · Seriennummer"},
    "dashboard_date":{"es":"Tablero · Fecha fabricación","en":"Dashboard · Manufacturing date","de":"I-Tafel · Fertigungsdatum"},
    "opening_time_ms":{"es":"Tiempo apertura ms","en":"Opening time ms","de":"Öffnungszeit ms"},
    "full_inflation_time_ms":{"es":"Inflado completo ms","en":"Full inflation time ms","de":"Aufblaszeit ms"},
}

REGLAS_ORIGEN = {
    "test_number": "Carpeta madre; contrastar con pizarra si existe.",
    "test_date": "Fecha de prueba explícita o confirmación manual; separada de fabricación.",
    "temperature_condition": "Catálogo HT/RT/NT en ruta, pizarra, etiqueta o confirmación manual.",
    "module_part_number": "Etiqueta de bolsa/QR/confirmación manual; no completar desde ejemplos.",
    "module_version": "RDW/NAR y alias explícitos; las letras finales siguen siendo significativas.",
    "module_serial_number": "Etiqueta de bolsa o confirmación manual; conservar letras, espacios, asteriscos y ceros iniciales.",
    "module_date": "Fecha de fabricación de la bolsa; conservar impreso e interpretación.",
    "dashboard_part_number": "Etiqueta del tablero/QR/confirmación manual; no completar desde ejemplos.",
    "dashboard_serial_number": "Etiqueta del tablero o confirmación manual; conservar letras, espacios, asteriscos y ceros iniciales.",
    "dashboard_date": "Fecha de fabricación del tablero; conservar impreso e interpretación.",
    "engineering_level": "Etiqueta, pizarra sólo si el componente está identificado, o confirmación manual.",
    "dashboard_engineering_level": "Etiqueta del tablero o confirmación manual.",
    "inflator_type": "Catálogo NOM/OGL/UGL por evidencia explícita o confirmación manual.",
    "opening_time_ms": "Sólo valor etiquetado OPENING/ÖFFNUNGSZEIT o captura manual. Extracción automática general aún pendiente.",
    "full_inflation_time_ms": "Sólo FULL INFLATION/AUFBLASZEIT o captura manual; no confundir con apertura.",
    "forvia_measurement_ms": "Sólo medición FORVIA explícita o captura manual; no usar como apertura.",
}

def _regla_origen(clave: str) -> tuple[str, str]:
    if clave in REGLAS_ORIGEN:
        return REGLAS_ORIGEN[clave], "definida"
    return "Fuente por definir o confirmación manual; el sistema no inventa el valor.", "pendiente"


def _t(idioma: str, clave: str) -> str:
    return TEXTOS.get(idioma, TEXTOS["es"]).get(clave, clave)

def _identidad(resultado: dict) -> str:
    return str(resultado.get("case_key") or resultado.get("id") or f"{resultado.get('project_id')}|{resultado.get('tipo_st')}|{_campo(resultado,'test_number')}")


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


def _copiar_estilo_fila(hoja, origen: int, destino: int, columnas: int = 55) -> None:
    hoja.row_dimensions[destino].height = hoja.row_dimensions[origen].height
    for c in range(1, columnas + 1):
        src, dst = hoja.cell(origen, c), hoja.cell(destino, c)
        if src.has_style:
            dst._style = copy.copy(src._style)
        dst.number_format = src.number_format
        dst.alignment = copy.copy(src.alignment)
        dst.protection = copy.copy(src.protection)


def _poblar_lista(hoja, resultados: list[dict], idioma: str = "es") -> dict[str, int]:
    """No recorta casos: conserva filas históricas y desplaza 2ST cuando hace falta."""
    estilo_1st = 8 if hoja.max_row >= 8 else 7
    estilo_2st = 58 if hoja.max_row >= 58 else estilo_1st
    for idx, clave in enumerate(CLAVES_PLANTILLA, start=1):
        hoja.cell(7, idx).value = HEADERS.get(clave, {}).get(idioma, clave)
        hoja.cell(7, idx).alignment = Alignment(wrap_text=True, vertical="center")
    g1 = _ordenar_etapa([r for r in resultados if str(r.get("tipo_st") or "").upper() == "1ST"])
    g2 = _ordenar_etapa([r for r in resultados if str(r.get("tipo_st") or "").upper() == "2ST"])
    gx = _ordenar_etapa([r for r in resultados if str(r.get("tipo_st") or "").upper() not in {"1ST","2ST"}])
    inicio1, inicio2 = 8, max(58, 8 + len(g1))
    iniciox = inicio2 + len(g2)
    ultimo = max(107, inicio1+len(g1)-1, inicio2+len(g2)-1, iniciox+len(gx)-1)
    for fila in range(8, max(hoja.max_row, ultimo)+1):
        for col in range(1, 56):
            celda=hoja.cell(fila,col); celda.value=None; celda.hyperlink=None; celda.comment=None
    mapa={}
    for grupo,inicio,estilo in ((g1,inicio1,estilo_1st),(g2,inicio2,estilo_2st),(gx,iniciox,estilo_1st)):
        for off, resultado in enumerate(grupo):
            fila=inicio+off; _copiar_estilo_fila(hoja, estilo, fila)
            _escribir_fila(hoja, fila, resultado)
            mapa[_identidad(resultado)] = fila
    hoja.freeze_panes="A8"
    hoja.auto_filter.ref=f"A7:{get_column_letter(len(CLAVES_PLANTILLA))}{max(7,ultimo)}"
    return mapa


def _copiar_lista_a_rangos(libro, resultados: list[dict], idioma: str = "es") -> None:
    if HOJA_RANGOS in libro.sheetnames:
        _poblar_lista(libro[HOJA_RANGOS], resultados, idioma)


def _poblar_matriz(hoja, tipo_st: str, resultados: list[dict], fila_inicio: int,
                   mapa_filas: dict[str, int], colores: dict, reglas: dict, idioma: str = "es") -> int:
    """Dibuja un bloque de matriz completo; crece sin truncar y mueve 2ST si hace falta."""
    mapa_color={"verde":colores.get("verde","#00B050"),"amarillo":colores.get("amarillo","#FFD966"),"rojo":colores.get("rojo","#FF0000"),"gris":colores.get("gris","#A6A6A6")}
    etapa=[r for r in resultados if str(r.get("tipo_st") or "").upper()==tipo_st]
    grupos=[]
    for spec in COLUMNAS_MATRIZ:
        grupo=[r for r in etapa if str(r.get("temperature_condition") or _campo(r,"temperature_condition") or "").upper()==spec["temperature_condition"] and str(r.get("inflator_type") or _campo(r,"inflator_type") or "").upper()==spec["inflator_type"]]
        grupos.append((spec,sorted(grupo,key=_test_sort,reverse=True)))
    alto=max([10,*[len(g) for _,g in grupos]])

    # Replica estilos de la plantilla para filas añadidas dinámicamente.
    fuente_titulo = 6 if tipo_st == "1ST" else 32
    fuente_dato = 16 if tipo_st == "1ST" else 42
    fuente_pie = (17,18,19) if tipo_st == "1ST" else (43,44,45)
    if fila_inicio-1 != fuente_titulo:
        _copiar_estilo_fila(hoja, fuente_titulo, fila_inicio-1, columnas=10)
    hoja.cell(fila_inicio-1,2).value = f"{_t(idioma,'overview')} ({'1st' if tipo_st=='1ST' else '2st'})"
    for r in range(fila_inicio, fila_inicio+alto):
        if r not in range(7,17) and r not in range(33,43):
            _copiar_estilo_fila(hoja, fuente_dato, r, columnas=10)
        for col in range(2,11):
            c=hoja.cell(r,col); c.value=None; c.hyperlink=None; c.comment=None
            if col>=4: c.fill=PatternFill(fill_type=None)

    for spec,grupo in grupos:
        arranque=fila_inicio+max(0,alto-len(grupo))
        for indice,resultado in enumerate(grupo):
            fila=arranque+indice; c=hoja[f"{spec['col']}{fila}"]
            numero=resultado.get("test_number") or _campo(resultado,"test_number") or resultado.get("identificador")
            c.value=numero; estado,tiempo=_estado_apertura(resultado,reglas); c.fill=_relleno(mapa_color[estado])
            detalle=mapa_filas.get(_identidad(resultado))
            if detalle: c.hyperlink=f"#'{HOJA_LISTA}'!C{detalle}"
            desc=_t(idioma,"unknown") if tiempo is None else f"{_t(idioma,'opening')}: {tiempo:g} ms"
            c.comment=Comment(f"{desc}\n{_t(idioma,'state')}: {estado}","OCR Versuchsmatrix")

    pie=fila_inicio+alto
    for i,origen in enumerate(fuente_pie):
        destino=pie+i
        if destino != origen: _copiar_estilo_fila(hoja, origen, destino, columnas=10)
        for col in range(2,11): hoja.cell(destino,col).value=None
    hoja.cell(pie+1,2).value=_t(idioma,"test_temperature")
    hoja.cell(pie+2,2).value=_t(idioma,"generator_type")
    for spec in COLUMNAS_MATRIZ:
        col=ord(spec["col"])-64
        hoja.cell(pie,col).value=spec["esperados"]
        temp={"HT":"+85°C","RT":"RT","NT":"-35°C"}.get(spec["temperature_condition"],spec["temperature_condition"])
        gen="nominal" if spec["inflator_type"]=="NOM" else spec["inflator_type"]
        hoja.cell(pie+1,col).value=temp
        hoja.cell(pie+2,col).value=gen
    return pie+3


def _crear_leyenda_matriz(hoja, fila: int, colores: dict, idioma: str) -> None:
    items=[("verde",_t(idioma,"ok_test")),("amarillo",_t(idioma,"ma_test")),("rojo",_t(idioma,"nio_test")),("gris",_t(idioma,"unknown"))]
    for off,(estado,texto) in enumerate(items):
        c=hoja.cell(fila+off,2); c.value=texto
        c.fill=_relleno(colores.get(estado, {"verde":"#00B050","amarillo":"#FFD966","rojo":"#FF0000","gris":"#A6A6A6"}[estado]))
        c.font=Font(color="000000",bold=(estado=="gris"))



def _crear_trazabilidad(libro, resultados: list[dict], idioma: str) -> None:
    nombre=_t(idioma,"trace")[:31]
    if nombre in libro.sheetnames: del libro[nombre]
    ws=libro.create_sheet(nombre)
    keys=("project","stage","case","component","field","image","region","original","corrected","orientation","rule","source","version")
    ws.append([_t(idioma,k) for k in keys])
    for c in ws[1]: c.font=Font(bold=True,color="FFFFFF"); c.fill=_relleno("#1D4ED8")
    for r in resultados:
        cands=r.get("candidatos") or (r.get("consolidado") or {}).get("candidatos") or []
        for cand in cands:
            ws.append([r.get("project_id") or cand.get("proyecto") or "",r.get("tipo_st") or cand.get("etapa") or "",_identidad(r),cand.get("componente") or "por_identificar",cand.get("clave") or "",cand.get("imagen") or "",str(cand.get("bbox_original") or ""),cand.get("valor_original") or "",cand.get("texto_correcto") or cand.get("valor_normalizado") or "",cand.get("orientacion_grados") or 0,cand.get("regla_aplicada") or "",cand.get("fuente") or "",cand.get("version_procesamiento") or ""])
            ruta_abs=str(cand.get("imagen_absoluta") or "").strip()
            if ruta_abs:
                celda=ws.cell(ws.max_row,6)
                try:
                    # Excel acepta rutas de archivo locales; no depende de internet.
                    celda.hyperlink=ruta_abs
                    celda.style="Hyperlink"
                except Exception:
                    pass
    ws.freeze_panes="A2"; ws.auto_filter.ref=ws.dimensions
    for col,width in {1:18,2:10,3:38,4:20,5:28,6:42,7:24,8:32,9:32,10:12,11:26,12:20,13:20}.items(): ws.column_dimensions[get_column_letter(col)].width=width


def _crear_diccionario(libro, idioma: str) -> None:
    nombre=_t(idioma,"dictionary")[:31]
    if nombre in libro.sheetnames: del libro[nombre]
    ws=libro.create_sheet(nombre)
    ws.append([_t(idioma,"field"),_t(idioma,"header"),_t(idioma,"origin_rule"),_t(idioma,"status")])
    for c in ws[1]: c.font=Font(bold=True,color="FFFFFF"); c.fill=_relleno("#1D4ED8")
    for clave in CLAVES_PLANTILLA:
        regla,estado=_regla_origen(clave)
        ws.append([clave,HEADERS.get(clave,{}).get(idioma,clave),regla,estado])
    ws.freeze_panes="A2"; ws.auto_filter.ref=ws.dimensions
    for col,width in {1:32,2:34,3:92,4:18}.items(): ws.column_dimensions[get_column_letter(col)].width=width
    for row in ws.iter_rows(min_row=2,max_col=4):
        row[2].alignment=Alignment(wrap_text=True,vertical="top")



def _guardar_atomico(libro, destino: Path, intentos: int=6) -> None:
    destino.parent.mkdir(parents=True,exist_ok=True)
    tmp=destino.with_name(f".{destino.name}.{os.getpid()}.{time.time_ns()}.tmp.xlsx")
    libro.save(tmp); ultimo=None
    try:
        for i in range(intentos):
            try: os.replace(tmp,destino); return
            except PermissionError as exc: ultimo=exc; time.sleep(.08*(i+1))
        raise PermissionError(f"No se pudo reemplazar {destino.name}; probablemente está abierto en Excel. Cierra el archivo y reintenta.") from ultimo
    finally:
        try:
            if tmp.exists(): tmp.unlink()
        except OSError: pass


def generar_reporte_bmg(ruta_plantilla: str | Path, ruta_salida: str | Path,
                        resultados: list[dict], config: dict, reglas: dict, idioma: str="es") -> Path:
    """Genera un único Excel 1ST+2ST, dinámico, traducido y trazable."""
    idioma=(idioma or "es").lower()
    if idioma not in {"es","en","de"}: raise ValueError("Idioma de exportación no válido: es, en o de.")
    libro=load_workbook(Path(ruta_plantilla))
    faltantes={HOJA_RESUMEN,HOJA_LISTA}-set(libro.sheetnames)
    if faltantes: raise ValueError(f"La plantilla BMG no contiene las hojas requeridas: {sorted(faltantes)}")
    mapa=_poblar_lista(libro[HOJA_LISTA],resultados,idioma)
    _copiar_lista_a_rangos(libro,resultados,idioma)
    resumen=libro[HOJA_RESUMEN]
    fin1=_poblar_matriz(resumen,"1ST",resultados,7,mapa,config.get("colores",{}),reglas,idioma)
    inicio2=max(33,fin1+4)
    fin2=_poblar_matriz(resumen,"2ST",resultados,inicio2,mapa,config.get("colores",{}),reglas,idioma)
    _crear_leyenda_matriz(resumen,fin2+1,config.get("colores",{}),idioma)
    _crear_trazabilidad(libro,resultados,idioma)
    _crear_diccionario(libro,idioma)
    libro.calculation.fullCalcOnLoad=True; libro.calculation.forceFullCalc=True; libro.calculation.calcMode="auto"
    destino=Path(ruta_salida); _guardar_atomico(libro,destino); return destino

