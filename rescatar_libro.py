#!/usr/bin/env python3
"""Rellena un libro ya generado con lo que su propia Trazabilidad leyó (P12).

    python rescatar_libro.py --libro versionV16_0_24.xlsx --salida versionV16_0_25.xlsx

- Nunca sobrescribe una celda ocupada.
- Exige mayoría entre lecturas del mismo caso y forma válida del campo.
- Escribe un informe `.rescate.json` con el origen de cada celda y otro `.md` legible.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from openpyxl import load_workbook

from utilidades.protocolo_campos import (aprender_lexico, matriz_confusion, perfil_proyecto,
                                          sembrar_test_number)
from utilidades.rescate_columnas import (aplicar, fechas_por_contexto, leer_trazabilidad,
                                         planificar, resumen)

# encabezado del libro -> campo interno (las 20 primeras columnas de Versuchsmatrix)
ENCABEZADOS = {
    "semana": "week",
    "motivo de prueba": "test_reason",
    "número de prueba": "test_number",
    "fecha de prueba": "test_date",
    "lugar de prueba": "test_place",
    "temperatura": "temperature_condition",
    "pab · número de parte": "module_part_number",
    "pab · variante": "module_version",
    "pab · serie": "module_serial_number",
    "pab · fecha fabricación": "module_date",
    "pab · nivel de ingeniería": "engineering_level",
    "delay ms": "delay_ms",
    "tipo de generador": "inflator_type",
    "proveedor de generador": "inflator_supplier",
    "tablero · número de parte": "dashboard_part_number",
    "tablero · serie": "dashboard_serial_number",
    "tablero · fecha fabricación": "dashboard_date",
    "tablero · nivel de ingeniería": "dashboard_engineering_level",
    "apertura láser": "laser_opening",
    "proveedor de tablero": "dashboard_supplier",
}


def columnas_del_libro(hoja, fila_encabezado: int) -> dict[str, int]:
    mapa = {}
    for columna in range(1, hoja.max_column + 1):
        titulo = str(hoja.cell(fila_encabezado, columna).value or "").strip().lower()
        if titulo in ENCABEZADOS:
            mapa[ENCABEZADOS[titulo]] = columna
    return mapa


def contexto_del_libro(libro, hoja_trazabilidad: str):
    """Aprende de la propia Trazabilidad: léxico por familia, prefijo del proyecto y matriz de
    confusión (pares texto OCR → texto corregido a mano)."""
    from collections import Counter, defaultdict
    hoja = libro[hoja_trazabilidad]
    valores: dict[str, Counter] = defaultdict(Counter)
    pares, casos = [], set()
    for fila in range(2, hoja.max_row + 1):
        caso = hoja.cell(fila, 3).value
        campo = str(hoja.cell(fila, 5).value or "").strip().lower()
        original, corregido = hoja.cell(fila, 8).value, hoja.cell(fila, 9).value
        if caso and "|" in str(caso):
            casos.add(str(caso).split("|")[2])
        if campo and corregido:
            valores[campo][str(corregido).strip()] += 1
        if original and corregido:
            pares.append((str(original), str(corregido)))
    lexico = aprender_lexico(valores)
    sembrar_test_number(lexico, casos)
    return {"lexico": lexico, "perfil": perfil_proyecto(valores),
            "confusion": matriz_confusion(pares),
            "fechas": fechas_por_contexto(hoja)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Rescata en el libro lo ya leído en Trazabilidad")
    ap.add_argument("--libro", required=True)
    ap.add_argument("--salida", default=None)
    ap.add_argument("--hoja", default="Versuchsmatrix")
    ap.add_argument("--trazabilidad", default="Trazabilidad")
    ap.add_argument("--fila-encabezado", type=int, default=7)
    args = ap.parse_args(argv)

    ruta = Path(args.libro)
    salida = Path(args.salida or ruta.with_name(ruta.stem + "_rescatado.xlsx"))
    libro = load_workbook(ruta)
    hoja = libro[args.hoja]
    columnas = columnas_del_libro(hoja, args.fila_encabezado)
    trazabilidad = leer_trazabilidad(libro[args.trazabilidad])
    contexto = contexto_del_libro(libro, args.trazabilidad)
    plan = planificar(hoja, trazabilidad, columnas, args.fila_encabezado, contexto=contexto)
    escritas = aplicar(hoja, plan)
    libro.save(salida)

    datos = {"libro": str(ruta), "salida": str(salida), "celdas_escritas": escritas,
             "columnas_reconocidas": len(columnas), "plan": plan, **resumen(plan),
             "lexico": {k: sorted(v) for k, v in contexto["lexico"].items()},
             "perfil_proyecto": contexto["perfil"],
             "confusiones_aprendidas": len(contexto["confusion"])}
    (salida.with_suffix(".rescate.json")).write_text(
        json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")

    lineas = [f"# Rescate de columnas · {ruta.name}", "",
              f"- Columnas reconocidas: **{len(columnas)} de 20**",
              f"- Celdas escritas: **{escritas}** (sólo estaban vacías)", "",
              "| Columna | Celdas | Origen |", "|---|---|---|"]
    for campo, veces in sorted(datos["por_campo"].items(), key=lambda kv: -kv[1]):
        origenes = sorted({p["origen"] for p in plan if p["campo"] == campo})
        lineas.append(f"| {campo} | {veces} | {', '.join(origenes)} |")
    salida.with_suffix(".rescate.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(f"{salida}: {escritas} celdas escritas | {dict(datos['por_campo'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
