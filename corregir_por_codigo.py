#!/usr/bin/env python3
"""P42 · corrige una celda del libro cuando el CÓDIGO demuestra que el libro se equivocó.

    python3 corregir_por_codigo.py --libro versionV16_0_50.xlsx \
        --correcciones codigo_vs_libro_correcciones.json \
        --aplicar 222530:module_date --salida versionV16_0_51.xlsx

Esto **sí** sobrescribe una celda ocupada, y por eso es un programa aparte, con tres seguros:

  1. Hay que nombrar la celda a mano (`--aplicar caso:campo`). No se aplica nada «que aparezca».
  2. El valor que hay ahora tiene que ser exactamente el que la verificación vio (`antes`). Si
     alguien tocó el libro entretanto, no se toca nada y se avisa.
  3. Queda renglón en `Trazabilidad`: valor anterior, valor nuevo, valor del código, foto del
     código y la regla `corregido_por_codigo`. Nada se corrige sin dejar rastro.

El valor nuevo es siempre el del código, nunca el de la referencia: si coinciden, bien; si no,
manda el código.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from openpyxl import load_workbook

COLUMNAS = {"module_part_number": 7, "module_version": 8, "module_serial_number": 9,
            "module_date": 10, "engineering_level": 11, "dashboard_part_number": 15,
            "dashboard_serial_number": 16, "dashboard_date": 17,
            "dashboard_engineering_level": 18}
HOJAS = ("Versuchsmatrix", "Rangos")


def filas_por_caso(hoja) -> dict[str, int]:
    filas = {}
    for fila in range(8, hoja.max_row + 1):
        valor = hoja.cell(fila, 3).value
        if valor in (None, ""):
            continue
        numero = str(valor).strip()
        if len(numero) == 6 and numero.isdigit():
            filas.setdefault(numero, fila)
    return filas


def main() -> int:
    ap = argparse.ArgumentParser(description="Corrige celdas probadas por el código")
    ap.add_argument("--libro", required=True)
    ap.add_argument("--correcciones", required=True)
    ap.add_argument("--aplicar", action="append", default=[],
                    help="caso:campo, repetible. Sin esto no se aplica nada.")
    ap.add_argument("--salida", required=True)
    args = ap.parse_args()

    correcciones = {f"{c['caso']}:{c['campo']}": c
                    for c in json.loads(Path(args.correcciones).read_text(encoding="utf-8"))}
    pedidas = [p for p in args.aplicar if p in correcciones]
    ignoradas = [p for p in args.aplicar if p not in correcciones]
    for clave in ignoradas:
        print(f"AVISO: {clave} no está en la lista de correcciones; no se toca")
    if not pedidas:
        print("nada que aplicar")
        return 1

    wb = load_workbook(args.libro)
    traza = wb["Trazabilidad"]
    aplicadas = 0
    for clave in pedidas:
        correccion = correcciones[clave]
        caso, campo = clave.split(":")
        columna = COLUMNAS.get(campo)
        if not columna:
            print(f"AVISO: no sé en qué columna va {campo}")
            continue
        for nombre_hoja in HOJAS:
            if nombre_hoja not in wb.sheetnames:
                continue
            hoja = wb[nombre_hoja]
            fila = filas_por_caso(hoja).get(caso)
            if fila is None:
                continue
            celda = hoja.cell(fila, columna)
            actual = "" if celda.value is None else str(celda.value).strip()
            if actual != str(correccion.get("antes") or "").strip():
                print(f"AVISO {caso}:{campo} en {nombre_hoja}: ahora dice {actual!r} y se esperaba "
                      f"{correccion.get('antes')!r}; no se toca")
                continue
            celda.value = correccion["despues"]
            aplicadas += 1
            traza.append(["jetta_gran_turismo", "1ST", caso, "módulo", campo,
                          correccion.get("foto", ""), "", actual, correccion["despues"], "",
                          "corregido_por_codigo", "dataMatrix", "v51",
                          "", str(correccion.get("codigo", ""))])
        print(f"{caso}:{campo}  {correccion.get('antes')!r} -> {correccion['despues']!r} "
              f"(código {correccion.get('codigo')!r})")

    destino = Path(args.salida)
    temporal = Path(tempfile.mkstemp(suffix=".xlsx", dir=str(destino.parent or Path(".")))[1])
    try:
        wb.save(temporal)
        os.replace(temporal, destino)
    except PermissionError:
        temporal.unlink(missing_ok=True)
        print(f"ERROR: no se pudo escribir {destino}. ¿Excel lo tiene abierto?")
        return 2
    print(f"{aplicadas} celda(s) corregidas · guardado {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
