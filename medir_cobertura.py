#!/usr/bin/env python3
"""Medidor único de cobertura: el mismo número antes y después de cada fase (P12).

    python medir_cobertura.py --libro tu_libro.xlsx [--salida informe]

Cuenta, sobre las 20 primeras columnas de Versuchsmatrix y sólo las filas con número de prueba:
- celdas llenas / vacías por columna y en total (la cifra que manda),
- si existe hoja Trazabilidad, cuántas de las vacías tienen lectura disponible (rescatables),
de modo que «vacía» y «vacía pero recuperable» no se confundan nunca.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook

from rescatar_libro import columnas_del_libro
from utilidades.rescate_columnas import FUENTES, leer_trazabilidad


def medir(ruta: Path, hoja="Versuchsmatrix", fila_encabezado=7) -> dict:
    libro = load_workbook(ruta, data_only=True)
    ws = libro[hoja]
    columnas = columnas_del_libro(ws, fila_encabezado)
    casos, llenas, vacias = [], Counter(), Counter()
    for fila in range(fila_encabezado + 1, ws.max_row + 1):
        numero = ws.cell(fila, columnas["test_number"]).value
        if numero in (None, ""):
            continue
        casos.append(str(numero))
        for campo, col in columnas.items():
            if ws.cell(fila, col).value in (None, ""):
                vacias[campo] += 1
            else:
                llenas[campo] += 1
    total = len(casos) * len(columnas)
    recuperables = Counter()
    if "Trazabilidad" in libro.sheetnames:
        traz = leer_trazabilidad(libro["Trazabilidad"])
        for fila in range(fila_encabezado + 1, ws.max_row + 1):
            numero = ws.cell(fila, columnas["test_number"]).value
            if numero in (None, ""):
                continue
            fuentes = traz.get(str(numero)) or {}
            for campo, col in columnas.items():
                if ws.cell(fila, col).value not in (None, ""):
                    continue
                if campo in FUENTES and any(fuentes.get(f) for f in FUENTES[campo]):
                    recuperables[campo] += 1
    return {"libro": str(ruta), "casos": casos, "columnas": len(columnas), "celdas": total,
            "llenas": sum(llenas.values()), "vacias": sum(vacias.values()),
            "por_columna": {c: {"llenas": llenas[c], "vacias": vacias[c],
                                "recuperables": recuperables[c],
                                "casos": len(casos)} for c in columnas},
            "cobertura": round(100 * sum(llenas.values()) / total, 1) if total else 0.0}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--libro", required=True)
    ap.add_argument("--salida", default=None)
    a = ap.parse_args(argv)
    r = medir(Path(a.libro))
    print(f"{Path(a.libro).name}: {r['llenas']}/{r['celdas']} = {r['cobertura']} % "
          f"({r['casos'].__len__()} casos × {r['columnas']} columnas)")
    for campo, d in sorted(r["por_columna"].items(), key=lambda kv: kv[1]["llenas"]):
        extra = f" (+{d['recuperables']} recuperables)" if d["recuperables"] else ""
        print(f"  {campo:26s} {d['llenas']}/{d['casos']}{extra}")
    if a.salida:
        Path(a.salida).with_suffix(".json").write_text(json.dumps(r, ensure_ascii=False, indent=1),
                                                      encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
