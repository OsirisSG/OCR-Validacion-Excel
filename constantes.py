#!/usr/bin/env python3
"""Constantes del proyecto: proponer, confirmar, aplicar y revocar (Fase 1 del plan).

    python constantes.py proponer --libro versionV16_0_26.xlsx
    python constantes.py confirmar --campo test_place --valor "Dachau" --autor "J. Osiris"
    python constantes.py aplicar --libro versionV16_0_26.xlsx --salida versionV16_0_27.xlsx
    python constantes.py listar
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from openpyxl import load_workbook

from rescatar_libro import columnas_del_libro, contexto_del_libro
from utilidades import constantes_aprendidas as ca
from utilidades.rescate_columnas import leer_trazabilidad


def _lecturas_carpeta(hoja_trazabilidad, lexico) -> dict[str, dict]:
    """Reconstruye, desde Trazabilidad, la lectura «de carpeta» por caso y campo (la más fiable)."""
    traz = leer_trazabilidad(hoja_trazabilidad)
    salida = {}
    for caso, campos in traz.items():
        salida[caso] = {"carpeta": {campo: (votos.most_common(1)[0][0] if votos else None)
                                    for campo, votos in campos.items()}}
    return salida


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Constantes confirmadas del proyecto")
    ap.add_argument("accion", choices=["proponer", "confirmar", "aplicar", "listar", "revocar"])
    ap.add_argument("--libro")
    ap.add_argument("--salida")
    ap.add_argument("--campo")
    ap.add_argument("--valor")
    ap.add_argument("--autor", default="operador")
    ap.add_argument("--forzar", action="store_true")
    a = ap.parse_args(argv)

    if a.accion == "listar":
        datos = ca.cargar().get("constantes", {})
        if not datos:
            print("No hay constantes confirmadas todavía.")
        for campo, d in datos.items():
            print(f"  {campo} = {d['valor']!r} · {d['autor']} · {d['fecha']}")
        return 0
    if a.accion == "confirmar":
        if not (a.campo and a.valor):
            raise SystemExit("confirmar necesita --campo y --valor")
        print("confirmada:", ca.confirmar(a.campo, a.valor, a.autor, forzar=a.forzar))
        return 0
    if a.accion == "revocar":
        print("revocada" if ca.revocar(a.campo) else "no existía")
        return 0

    libro = load_workbook(a.libro)
    hoja = libro["Versuchsmatrix"]
    columnas = columnas_del_libro(hoja, 7)
    if a.accion == "proponer":
        lecturas = _lecturas_carpeta(libro["Trazabilidad"], None)
        for p in ca.proponer(lecturas, tuple(columnas)):
            print(f"  {p['campo']:24s} = {p['valor']!r:22s} en {p['coincidencias']}/{p['casos']} "
                  f"casos ({p['confianza']}) · protocolo: {p['protocolo']}")
        return 0

    resultado = ca.aplicar(hoja, columnas, lecturas=_lecturas_carpeta(libro["Trazabilidad"], None))
    salida = Path(a.salida or "libro_con_constantes.xlsx")
    libro.save(salida)
    salida.with_suffix(".constantes.json").write_text(json.dumps(resultado, ensure_ascii=False,
                                                                indent=1), encoding="utf-8")
    print(f"{salida}: {len(resultado['escritas'])} celdas escritas · "
          f"{len(resultado['excepciones'])} excepciones (caso con lectura propia distinta)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
