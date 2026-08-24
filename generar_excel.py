"""
generar_excel.py — Fase 3: consolidación en Excel maestro + matriz de cumplimiento.

Propósito
---------
Lee `validacion_resultados.json` (Fase 2) y genera `resultado_maestro.xlsx`
con dos hojas:
  1. "Estructura completa": una fila por carpeta procesada con toda la evidencia.
  2. "Matriz de cumplimiento": el semáforo verde/amarillo/rojo.

El semáforo se construye DINÁMICAMENTE desde reglas_cumplimiento.yaml:
- criterios numéricos continuos (confianza_ocr) → ColorScaleRule con extremos
  en los umbrales del YAML;
- criterios categóricos (coincidencia_texto) → CellIsRule con relleno por valor;
- columna "Semáforo global" = el color más restrictivo entre criterios
  (evaluado con el mismo motor de reglas que usa el dashboard).

Ningún rango está fijo en el código: cambiar el YAML cambia Excel y dashboard.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from configuracion import (RAIZ_PROYECTO, cargar_config, cargar_reglas,
                           clasificar, estructura_regla)

COLUMNAS = [
    ("Ruta", 46), ("Identificador", 18), ("Variante", 9),
    ("Tipos de archivo", 30), ("Texto etiqueta (OCR)", 34),
    ("Texto referencia (OCR)", 34), ("Resultado comparación", 20),
    ("Confianza OCR (%)", 12), ("QR detectado", 11),
    ("Anomalías Fase 0", 22), ("Observaciones", 34),
]

COLUMNAS_MATRIZ = [
    ("Ruta", 46), ("Identificador", 18), ("Confianza OCR (%)", 12),
    ("Coincidencia texto", 22), ("Semáforo global", 16),
]


def _hex_a_fill(hex_color: str) -> PatternFill:
    """'#22c55e' -> PatternFill aRGB sólido (openpyxl exige canal alfa)."""
    return PatternFill(start_color="FF" + hex_color.lstrip("#"),
                       end_color="FF" + hex_color.lstrip("#"), fill_type="solid")


def _resumen_tipos(tipos: dict) -> str:
    partes = []
    for cat, archivos in sorted(tipos.items()):
        partes.append(f"{len(archivos)} {cat}")
    return ", ".join(partes) if partes else "—"


def _texto_fila(fila: dict) -> dict:
    """Convierte una fila de validacion_resultados en valores de celda."""
    et = fila.get("etiqueta") or {}
    ref = fila.get("referencia") or {}
    et_tokens = " | ".join(t["texto"] for t in (et.get("resultado_ocr") or {}).get("tokens", []))
    ref_tokens = " | ".join(t["texto"] for t in (ref.get("resultado_ocr") or {}).get("tokens", []))
    comparacion = fila["comparacion"]["resultado"]
    return {
        "Ruta": fila["ruta"],
        "Identificador": (f"{fila.get('prefijo_numerico')}_{fila.get('nomenclatura')}"
                          if fila.get("prefijo_numerico") and fila.get("nomenclatura")
                          else fila.get("identificador") or fila["nombre"]),
        "Variante": fila.get("variante") or "—",
        "Tipos de archivo": _resumen_tipos(fila.get("tipos_archivo", {})),
        "Texto etiqueta (OCR)": et_tokens or "—",
        "Texto referencia (OCR)": ref_tokens or "—",
        "Resultado comparación": comparacion,
        "Confianza OCR (%)": fila.get("confianza_ocr_pct"),
        "QR detectado": "Sí" if fila.get("qr_detectado") else "No",
        "Anomalías Fase 0": fila.get("anomalia_fase0") or "",
        "Observaciones": "; ".join(fila.get("observaciones", [])),
    }


def generar_excel(ruta_validacion: str | Path | None = None,
                  ruta_salida: str | Path | None = None,
                  config: dict | None = None,
                  reglas: dict | None = None) -> Path:
    """Genera resultado_maestro.xlsx. Retorna la ruta del archivo creado."""
    config = config or cargar_config()
    reglas = reglas or cargar_reglas()
    f3 = config.get("fase3", {})
    ruta_validacion = Path(ruta_validacion) if ruta_validacion else RAIZ_PROYECTO / "validacion_resultados.json"
    ruta_salida = Path(ruta_salida) if ruta_salida else RAIZ_PROYECTO / f3.get("archivo_salida", "resultado_maestro.xlsx")

    with open(ruta_validacion, "r", encoding="utf-8") as f:
        datos = json.load(f)

    colores = config.get("colores", {})
    c_verde, c_amarillo, c_rojo = (colores.get("verde", "#22c55e"),
                                   colores.get("amarillo", "#f59e0b"),
                                   colores.get("rojo", "#ef4444"))
    criterios = reglas.get("criterios", {})

    wb = Workbook()

    # ---------------------------------------------------------------- Hoja 1
    ws = wb.active
    ws.title = f3.get("hoja_estructura", "Estructura completa")
    estilo_encabezado = Font(bold=True, color="FFFFFF")
    fill_encabezado = PatternFill(start_color="FF1F2937", end_color="FF1F2937", fill_type="solid")
    for col, (titulo, ancho) in enumerate(COLUMNAS, start=1):
        celda = ws.cell(row=1, column=col, value=titulo)
        celda.font = estilo_encabezado
        celda.fill = fill_encabezado
        ws.column_dimensions[get_column_letter(col)].width = ancho
    ws.freeze_panes = "A2"
    for fila_datos in datos.get("resultados", []):
        ws.append([_texto_fila(fila_datos)[t] for t, _ in COLUMNAS])
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNAS))}{ws.max_row}"

    # ---------------------------------------------------------------- Hoja 2
    wm = wb.create_sheet(f3.get("hoja_matriz", "Matriz de cumplimiento"))
    for col, (titulo, ancho) in enumerate(COLUMNAS_MATRIZ, start=1):
        celda = wm.cell(row=1, column=col, value=titulo)
        celda.font = estilo_encabezado
        celda.fill = fill_encabezado
        wm.column_dimensions[get_column_letter(col)].width = ancho
    wm.freeze_panes = "A2"

    col_conf = next(i for i, (t, _) in enumerate(COLUMNAS_MATRIZ, start=1)
                    if "Confianza" in t)
    col_coinc = next(i for i, (t, _) in enumerate(COLUMNAS_MATRIZ, start=1)
                     if "Coincidencia" in t)
    col_semaforo = next(i for i, (t, _) in enumerate(COLUMNAS_MATRIZ, start=1)
                        if "Semáforo" in t)

    fila_excel = 2
    for fila_datos in datos.get("resultados", []):
        valores = _texto_fila(fila_datos)
        conf = valores["Confianza OCR (%)"]
        coinc = valores["Resultado comparación"]
        clasif = clasificar(conf, coinc, reglas)
        semaforo = clasif.get("semaforo_global") or "sin clasificar"

        wm.cell(row=fila_excel, column=1, value=valores["Ruta"])
        wm.cell(row=fila_excel, column=2, value=valores["Identificador"])
        wm.cell(row=fila_excel, column=col_conf, value=conf if conf is not None else "—")
        wm.cell(row=fila_excel, column=col_coinc, value=coinc)
        celda_semaforo = wm.cell(row=fila_excel, column=col_semaforo, value=semaforo)
        if semaforo in ("verde", "amarillo", "rojo"):
            celda_semaforo.fill = _hex_a_fill(colores[semaforo])
            celda_semaforo.font = Font(bold=True, color="FFFFFF")
        celda_semaforo.alignment = Alignment(horizontal="center")
        fila_excel += 1

    ultima = fila_excel - 1

    # --- Semáforo NUMÉRICO continuo (ColorScaleRule) desde el YAML ------------
    regla_conf = estructura_regla(criterios["confianza_ocr"]["amarillo"])
    if regla_conf["tipo"] == "rango":
        lim_inferior, lim_superior = regla_conf["min"], regla_conf["max"] + 1
    else:  # fallback defensivo si el YAML cambia a operadores
        verde = estructura_regla(criterios["confianza_ocr"]["verde"])
        rojo = estructura_regla(criterios["confianza_ocr"]["rojo"])
        lim_superior = verde.get("valor", 90)
        lim_inferior = rojo.get("valor", 70)
    rango_conf = f"{get_column_letter(col_conf)}2:{get_column_letter(col_conf)}{max(ultima, 3)}"
    wm.conditional_formatting.add(rango_conf, ColorScaleRule(
        start_type="num", start_value=lim_inferior, start_color=c_rojo.lstrip("#"),
        mid_type="num", mid_value=(lim_inferior + lim_superior) / 2, mid_color=c_amarillo.lstrip("#"),
        end_type="num", end_value=lim_superior, end_color=c_verde.lstrip("#"),
    ))

    # --- Semáforo CATEGÓRICO (CellIsRule) desde el YAML ------------------------
    rango_coinc = f"{get_column_letter(col_coinc)}2:{get_column_letter(col_coinc)}{max(ultima, 3)}"
    for color in ("verde", "amarillo", "rojo"):
        estruct = estructura_regla(criterios["coincidencia_texto"][color])
        if estruct["tipo"] != "categorico":
            continue
        for valor in estruct["valores"]:
            wm.conditional_formatting.add(rango_coinc, CellIsRule(
                operator="equal", formula=[f'"{valor}"'], fill=_hex_a_fill(colores[color])))

    wb.save(ruta_salida)
    return ruta_salida


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fase 3: generar Excel maestro.")
    parser.add_argument("--validacion", default=None, help="Ruta de validacion_resultados.json.")
    parser.add_argument("--salida", default=None, help="Ruta del xlsx de salida.")
    args = parser.parse_args()
    ruta = generar_excel(args.validacion, args.salida)
    print(f"Excel maestro generado en: {ruta}")
