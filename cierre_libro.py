#!/usr/bin/env python3
"""P42 · qué falta, exactamente, para llegar al 100% del libro contra la referencia.

    python3 cierre_libro.py --libro versionV16_0_50.xlsx \
        --referencia Book-10-Examples_CORREGIDO.xlsx

No hay una cifra sola. Hay cuatro cajas y cada una se cierra de una forma distinta:

  coinciden        el libro dice lo mismo que la referencia
  huecos          la referencia tiene un dato y el libro no
  discrepancias   los dos tienen dato y no es el mismo
  sin dato        la referencia dice `--`: no hay dato que buscar, no es un hueco

Y cada cosa que falta lleva pegada la acción que la desbloquea, porque un porcentaje sin
«qué hago para subirlo» no sirve para nada.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from openpyxl import load_workbook

COLUMNAS = {1: "week", 2: "test_reason", 3: "test_number", 4: "test_date", 5: "test_place",
            6: "temperature_condition", 7: "module_part_number", 8: "module_version",
            9: "module_serial_number", 10: "module_date", 11: "engineering_level",
            12: "delay_ms", 13: "inflator_type", 14: "inflator_supplier",
            15: "dashboard_part_number", 16: "dashboard_serial_number",
            17: "dashboard_date", 18: "dashboard_engineering_level", 19: "laser_opening",
            20: "dashboard_supplier"}

SIN_DATO = {"--", "-", "—", "n/a", ""}

# qué desbloquea cada hueco: se escribe aquí para que el informe sirva de algo
ACCION = {
    "dashboard_part_number": "A6 · autorizar el payload como fuente cuando el grabado no lee",
    "dashboard_serial_number": "revisar la etiqueta en la cola de confirmación",
    "dashboard_date": "fotos dirigidas del sticker de fecha (hacen falta 2 lecturas iguales)",
    "delay_ms": "tubería de tiempos de vídeo (no es tablero)",
    "module_date": "normalizar el criterio de fecha del módulo (o no normalizar ninguna)",
    "module_serial_number": "normalizar espacios (o no normalizar ninguno)",
}


def leer(ruta: Path) -> dict[str, dict[str, str]]:
    """Número de caso -> {campo: valor normalizado}. Pura."""
    hoja = load_workbook(ruta, data_only=True)["Versuchsmatrix"]
    filas: dict[str, dict[str, str]] = {}
    for fila in range(8, hoja.max_row + 1):
        valor = hoja.cell(fila, 3).value
        if valor in (None, ""):
            continue
        numero = str(valor).strip()
        if len(numero) != 6 or not numero.isdigit():
            continue
        registro = {}
        for columna, campo in COLUMNAS.items():
            dato = hoja.cell(fila, columna).value
            if dato is None:
                registro[campo] = ""
            elif hasattr(dato, "date"):
                registro[campo] = str(dato.date())
            else:
                registro[campo] = str(dato).strip()
        filas[numero] = registro
    return filas


def clasificar(libro: str, referencia: str) -> str:
    """En qué caja cae una celda. Pura."""
    if libro in SIN_DATO and referencia in SIN_DATO:
        return "sin dato"
    if libro in SIN_DATO and referencia not in SIN_DATO:
        return "hueco"
    if libro not in SIN_DATO and referencia in SIN_DATO:
        return "sobra"                       # el libro inventa donde la referencia no tiene
    if libro == referencia:
        return "coincide"
    return "discrepancia"


def main() -> int:
    ap = argparse.ArgumentParser(description="Cuadro de cierre contra la referencia")
    ap.add_argument("--libro", required=True)
    ap.add_argument("--referencia", required=True)
    args = ap.parse_args()
    libro = leer(Path(args.libro))
    referencia = leer(Path(args.referencia))

    cajas = {"coincide": [], "hueco": [], "discrepancia": [], "sobra": [], "sin dato": []}
    for caso in sorted(referencia):
        for campo in COLUMNAS.values():
            estado = clasificar(libro.get(caso, {}).get(campo, ""),
                                referencia[caso].get(campo, ""))
            cajas[estado].append((caso, campo, libro.get(caso, {}).get(campo, ""),
                                  referencia[caso].get(campo, "")))

    total = sum(len(v) for v in cajas.values())
    print(f"{Path(args.libro).name} vs {Path(args.referencia).name} · {total} celdas\n")
    for nombre in ("coincide", "hueco", "discrepancia", "sobra", "sin dato"):
        print(f"  {nombre:14s} {len(cajas[nombre]):3d}"
              + (f"   ({len(cajas[nombre]) / total * 100:4.1f} %)" if nombre == "coincide" else ""))
    cierre = len(cajas['coincide']) + len(cajas['sin dato'])
    print(f"\n  cerradas (coincide + sin dato) ... {cierre}/{total} = {cierre / total * 100:.1f} %")
    print(f"  techo si se resuelve todo lo pendiente ... {total}/{total} = 100 %")

    if cajas["hueco"]:
        print("\nHUECOS (la referencia tiene dato y el libro no):")
        for caso, campo, _, esperado in cajas["hueco"]:
            print(f"  {caso}  {campo:26s} falta {esperado!r:20s} -> {ACCION.get(campo, '?')}")
    if cajas["discrepancia"]:
        print("\nDISCREPANCIAS (los dos tienen dato y no coinciden):")
        for caso, campo, nuestro, esperado in cajas["discrepancia"]:
            print(f"  {caso}  {campo:26s} {nuestro!r} ≠ {esperado!r} -> {ACCION.get(campo, '?')}")
    if cajas["sobra"]:
        print("\nSOBRAN (el libro tiene dato donde la referencia no):")
        for caso, campo, nuestro, _ in cajas["sobra"]:
            print(f"  {caso}  {campo:26s} {nuestro!r} · revisar si se inventó")
    if cajas["sin dato"]:
        print(f"\nSIN DATO: {len(cajas['sin dato'])} celdas que la referencia marca `--`.")
        print("  No son un hueco, pero conviene escribirlas igual en todas las filas:",
              ", ".join(sorted({caso for caso, *_ in cajas['sin dato']})))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
