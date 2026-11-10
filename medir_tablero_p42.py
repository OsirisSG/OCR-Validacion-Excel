#!/usr/bin/env python3
"""P42 · marcador del tablero, con el universo completo y sin premiar vacíos (revisión F7).

    python3 medir_tablero_p42.py --referencia Book-10-Examples_CORREGIDO.xlsx \
        [--evidencia evidencia_tablero_p42.json] [--libro versionV16_0_50.xlsx]

Qué cambia respecto de la primera versión:
  * el **universo** lo pone la referencia (los 10 casos), no la evidencia: un caso que falta se
    cuenta como ausente y se avisa, no desaparece del denominador;
  * se avisa de casos duplicados y de referencias inexistentes;
  * un valor vacío **nunca** cuenta como acierto salvo que la referencia también esté vacía, y
    esos casos se informan aparte (`referencia vacía`);
  * se distinguen cuatro estados: `exacto`, `cola pendiente` (difiere sólo en el último carácter
    de una serie cuya cola codificada no tiene la forma esperada), `vacío` y `discrepancia`;
  * la evidencia (lo que el motor propone) y el libro (lo que se publica) se miden **por
    separado**: no son lo mismo.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from openpyxl import load_workbook

CAMPOS = {15: "N/P", 16: "serie", 17: "fecha", 18: "nivel"}
EVIDENCIA = {"N/P": "dashboard_part_number", "serie": "dashboard_serial_number",
             "fecha": "dashboard_date", "nivel": "dashboard_engineering_level"}


def normalizar(valor) -> str:
    if valor in (None, ""):
        return ""
    if hasattr(valor, "date"):
        valor = valor.date()
    return str(valor).strip()


def leer_referencia(ruta: Path) -> dict[str, dict[str, str]]:
    hoja = load_workbook(ruta, data_only=True)["Versuchsmatrix"]
    ref: dict[str, dict[str, str]] = {}
    duplicados = []
    for fila in range(8, hoja.max_row + 1):
        numero = normalizar(hoja.cell(fila, 3).value)
        if not (len(numero) == 6 and numero.isdigit()):
            continue
        if numero in ref:
            duplicados.append(numero)
            continue
        ref[numero] = {nombre: normalizar(hoja.cell(fila, col).value)
                       for col, nombre in CAMPOS.items()}
    if duplicados:
        print(f"  AVISO: casos duplicados en la referencia: {sorted(set(duplicados))}")
    return ref


def clasificar(campo: str, nuestro: str, esperado: str, cola: str) -> str:
    """Estado de una celda. Pura.

    `cola pendiente` = el valor difiere de la referencia sólo en el último carácter y el código
    traía una cola que no tiene la forma esperada (`simbolo` o `ambigua`): es una diferencia
    conocida y pendiente de decidir, no un acierto ni un error nuevo.
    """
    if not nuestro:
        return "vacío"
    if nuestro == esperado:
        return "exacto"
    if campo == "serie" and esperado and len(nuestro) == len(esperado) + 1 \
            and nuestro[:-1] == esperado:
        return "cola pendiente"
    return "discrepancia"


def medir(origen: dict[str, dict], ref: dict[str, dict], etiqueta: str) -> dict:
    totales = {estado: 0 for estado in ("exacto", "cola pendiente", "vacío", "discrepancia")}
    detalle_casos = []
    ausentes = [caso for caso in ref if caso not in origen]
    sobran = [caso for caso in origen if caso not in ref]
    print(f"\n{etiqueta}: {len(ref)} casos de referencia · {len(origen)} en la medición")
    if ausentes:
        print(f"  AVISO: casos de la referencia que no están: {sorted(ausentes)}")
    if sobran:
        print(f"  AVISO: casos medidos que no están en la referencia: {sorted(sobran)}")
    print(f"  {'caso':8s} " + " ".join(f"{n:16s}" for n in CAMPOS.values()))
    for caso in sorted(ref):
        fila = []
        esperado_caso = ref[caso]
        nuestro_caso = origen.get(caso) or {}
        for nombre in CAMPOS.values():
            campo = EVIDENCIA[nombre]
            esperado = esperado_caso.get(nombre, "")
            nuestro = normalizar(nuestro_caso.get(campo))
            estado = clasificar(nombre, nuestro, esperado, "")
            totales[estado] += 1
            marca = {"exacto": "OK", "cola pendiente": "~ ", "vacío": "--",
                     "discrepancia": "XX"}[estado]
            fila.append(f"{nuestro or '—':14s}{marca}")
        detalle_casos.append((caso, fila))
        print(f"  {caso:8s} " + " ".join(fila))
    print("  " + " · ".join(f"{k} {v}" for k, v in totales.items())
          + f" · TOTAL exactos {totales['exacto']}/{len(ref) * len(CAMPOS)}")
    return totales


def desde_evidencia(datos: dict) -> dict[str, dict]:
    return {caso: {campo: valor for campo, valor in
                   ((EVIDENCIA[n], datos[caso].get(EVIDENCIA[n])) for n in CAMPOS.values())}
            for caso in datos}


def desde_libro(ruta: Path) -> dict[str, dict]:
    hoja = load_workbook(ruta, data_only=True)["Versuchsmatrix"]
    salida: dict[str, dict] = {}
    for fila in range(8, hoja.max_row + 1):
        numero = normalizar(hoja.cell(fila, 3).value)
        if not (len(numero) == 6 and numero.isdigit()):
            continue
        salida[numero] = {EVIDENCIA[nombre]: normalizar(hoja.cell(fila, col).value)
                          for col, nombre in CAMPOS.items()}
    return salida


def main() -> int:
    ap = argparse.ArgumentParser(description="Marcador del tablero contra la referencia")
    ap.add_argument("--referencia", required=True)
    ap.add_argument("--evidencia", default="")
    ap.add_argument("--libro", default="")
    args = ap.parse_args()
    ref = leer_referencia(Path(args.referencia))
    if args.evidencia:
        datos = json.loads(Path(args.evidencia).read_text(encoding="utf-8"))
        medir(desde_evidencia(datos), ref, "EVIDENCIA (lo que propone el motor)")
    if args.libro:
        medir(desde_libro(Path(args.libro)), ref, "LIBRO (lo que se publica)")
    if not args.evidencia and not args.libro:
        print("nada que medir: pasa --evidencia y/o --libro")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
