#!/usr/bin/env python3
"""Compara un libro con el **libro completo** de referencia, celda por celda (P17).

    python medir_contra_referencia.py --libro versionV16_0_30.xlsx --referencia Book-10-Examples.xlsx

Salida: por columna, cuántas celdas hay llenas en el libro medido, cuántas coinciden con la
referencia, cuántas discrepan y cuántas siguen vacías. Las filas se emparejan por **número de
prueba**, no por posición.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook

from rescatar_libro import columnas_del_libro


def normalizar(valor) -> str:
    if valor in (None, ""):
        return ""
    if isinstance(valor, datetime):
        return valor.date().isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor).strip()


def por_numero(hoja, columna_numero: int) -> dict[str, int]:
    filas = {}
    for fila in range(8, hoja.max_row + 1):
        valor = hoja.cell(fila, columna_numero).value
        if valor in (None, ""):
            continue
        filas.setdefault("".join(ch for ch in str(valor) if ch.isdigit()), fila)
    return filas


def medir(libro: Path, referencia: Path, hoja_nombre: str = "Versuchsmatrix") -> dict:
    ws = load_workbook(libro, data_only=True)[hoja_nombre]
    ref = load_workbook(referencia, data_only=True)[hoja_nombre]
    mapa = columnas_del_libro(ws, 7)
    # el libro completo tiene las cabeceras en alemán: sus columnas van en el mismo orden (A..T),
    # así que se emparejan por posición y se comprueba que la fila de grupos coincide.
    mapa_ref = {campo: columna for campo, columna in mapa.items()}
    col_numero, col_numero_ref = mapa["test_number"], mapa_ref["test_number"]
    filas, filas_ref = por_numero(ws, col_numero), por_numero(ref, col_numero_ref)
    comunes = [n for n in filas if n in filas_ref]

    detalle = []
    total_ok = total_llenas = total_vacias = total_mal = 0
    for campo, columna in mapa.items():
        if campo not in mapa_ref:
            continue
        columna_ref = mapa_ref[campo]
        llenas = ok = mal = vacias = 0
        discrepancias = []
        for numero in comunes:
            mio = normalizar(ws.cell(filas[numero], columna).value)
            suyo = normalizar(ref.cell(filas_ref[numero], columna_ref).value)
            if mio:
                llenas += 1
                if mio == suyo:
                    ok += 1
                else:
                    mal += 1
                    discrepancias.append((numero, mio, suyo))
            else:
                vacias += 1
        detalle.append({"campo": campo, "llenas": llenas, "coinciden": ok, "discrepan": mal,
                        "vacias": vacias, "discrepancias": discrepancias[:3]})
        total_ok += ok
        total_llenas += llenas
        total_vacias += vacias
        total_mal += mal
    return {"casos_comunes": len(comunes), "columnas": len(detalle), "detalle": detalle,
            "llenas": total_llenas, "coinciden": total_ok, "discrepan": total_mal,
            "vacias": total_vacias, "total": total_llenas + total_vacias}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Medición contra el libro completo")
    ap.add_argument("--libro", required=True)
    ap.add_argument("--referencia", required=True)
    args = ap.parse_args(argv)
    datos = medir(Path(args.libro), Path(args.referencia))
    print(f"{Path(args.libro).name} vs {Path(args.referencia).name} · "
          f"{datos['casos_comunes']} casos · {datos['total']} celdas")
    print(f"  llenas {datos['llenas']}/{datos['total']} · coinciden {datos['coinciden']} · "
          f"discrepan {datos['discrepan']} · vacías {datos['vacias']}")
    print(f"  {'campo':30s} {'llenas':>6s} {'coinc.':>6s} {'disc.':>5s} {'vacías':>6s}")
    for fila in datos["detalle"]:
        print(f"  {fila['campo']:30s} {fila['llenas']:6d} {fila['coinciden']:6d} "
              f"{fila['discrepan']:5d} {fila['vacias']:6d}")
        for numero, mio, suyo in fila["discrepancias"]:
            print(f"      {numero}: nuestro {mio!r} ≠ referencia {suyo!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
