"""Orquesta la lectura del tablero en tramos, para que quepa en 2 GB de memoria.

Un solo proceso con 20 fotos revienta (cada OCR deja ~200 MB); en tramos de seis fotos cabe de
sobra. Este script hace los tres pasos de `evidencia_tablero.py`:

1. lista de candidatas por caso (filtro barato, sin OCR);
2. tramos de `--lote` fotos, cada uno en su propio proceso, acumulando en el archivo parcial;
3. consenso y `evidencia_tablero.json`.

Uso:
    python leer_tablero_lote.py --fotos "/var/tmp/fotos" --json evidencia_tablero.json \
        --salida evidencia_tablero --catalogo 2GJ.857.003.G --lote 6
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent


def correr(argumentos: list[str]) -> int:
    proceso = subprocess.run([sys.executable, str(AQUI / "evidencia_tablero.py"), *argumentos],
                             cwd=str(AQUI))
    return proceso.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description="Lee el tablero por tramos, sin agotar la memoria")
    ap.add_argument("--fotos", required=True)
    ap.add_argument("--json", default="evidencia_tablero.json")
    ap.add_argument("--salida", default="evidencia_tablero")
    ap.add_argument("--catalogo", default="2GJ.857.003.G")
    ap.add_argument("--lote", type=int, default=6)
    ap.add_argument("--casos", default="", help="lista de casos separada por comas (por defecto todos)")
    ap.add_argument("--lista", default="", help="reutilizar una lista ya calculada")
    args = ap.parse_args()

    lista_path = Path(args.lista) if args.lista else Path("/tmp/lista_tablero.json")
    if not args.lista or not lista_path.exists():
        if correr(["--fotos", args.fotos, "--lista", str(lista_path),
                   "--json", args.json, "--salida", args.salida]) != 0:
            return 1
    lista = json.loads(lista_path.read_text(encoding="utf-8"))
    casos = [c.strip() for c in args.casos.split(",") if c.strip()] or list(lista)

    parcial = Path("/tmp/lecturas_tablero.json")
    if parcial.exists():
        parcial.unlink()
    for clave in casos:
        caso = lista[clave]
        total = len(caso["elegidas"])
        for desde in range(0, total, args.lote):
            codigo = correr(["--fotos", args.fotos, "--json", args.json,
                             "--salida", args.salida, "--catalogo", args.catalogo,
                             "--lista", str(lista_path), "--parcial", str(parcial),
                             "--rango", f"{desde}:{desde + args.lote}", "--caso", clave])
            if codigo != 0:
                print(f"  aviso: el tramo {clave} {desde} terminó con código {codigo}",
                      flush=True)
    return correr(["--cerrar", "--json", args.json, "--salida", args.salida,
                   "--parcial", str(parcial)])


if __name__ == "__main__":
    raise SystemExit(main())
