"""Orquesta la lectura del tablero en tramos, para que quepa en 2 GB de memoria.

Un solo proceso con 20 fotos revienta (cada OCR deja ~200 MB); en tramos de seis fotos cabe de
sobra. Este script hace los tres pasos de `evidencia_tablero.py`:

1. lista de candidatas por caso (filtro barato, sin OCR);
2. tramos de `--lote` fotos, cada uno en su propio proceso, acumulando en el archivo parcial;
3. consenso y `evidencia_tablero.json`.

P43 · cambios de aislamiento (sin tocar ninguna regla de lectura ni de consenso):
- los archivos intermedios (lista y parcial) viven en un directorio ÚNICO por corrida creado con
  `tempfile.mkdtemp` (antes `/tmp/lista_tablero.json` y `/tmp/lecturas_tablero.json` fijos, que
  en Windows ni siquiera existen y entre corridas se pisaban);
- un tramo que falla ya no se convierte en «sin lectura»: la corrida termina con código 2 y
  lista los tramos fallidos (el JSON se escribe igual, para revisar lo que sí se leyó);
- `--json` existente NO se funde en silencio con la corrida nueva: hace falta `--fundir`
  (comportamiento P42) o elegir otro destino.

Uso:
    python leer_tablero_lote.py --fotos "C:\\fotos lote" --json evidencia_tablero.json \
        --salida evidencia_tablero --catalogo 2GJ.857.003.G --lote 6
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent


def correr(argumentos: list[str]) -> int:
    proceso = subprocess.run([sys.executable, str(AQUI / "evidencia_tablero.py"), *argumentos],
                             cwd=str(AQUI))
    return proceso.returncode


def directorio_de_trabajo(base: str | None) -> Path:
    """Directorio único para esta corrida (nunca reutiliza el de otra)."""
    padre = Path(base) if base else None
    if padre is not None:
        padre.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="tablero_p42_", dir=str(padre) if padre else None))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lee el tablero por tramos, sin agotar la memoria")
    ap.add_argument("--fotos", required=True)
    ap.add_argument("--json", default="evidencia_tablero.json")
    ap.add_argument("--salida", default="evidencia_tablero")
    ap.add_argument("--catalogo", default="2GJ.857.003.G")
    ap.add_argument("--lote", type=int, default=6)
    ap.add_argument("--casos", default="", help="lista de casos separada por comas (por defecto todos)")
    ap.add_argument("--lista", default="", help="reutilizar EXPLÍCITAMENTE una lista ya calculada")
    ap.add_argument("--trabajo", default="",
                    help="carpeta donde crear el directorio único de la corrida (por defecto el temporal del sistema)")
    ap.add_argument("--conservar-trabajo", action="store_true",
                    help="no borrar el directorio de la corrida al terminar")
    ap.add_argument("--fundir", action="store_true",
                    help="fundir con un --json existente (comportamiento P42); sin esto se rechaza")
    args = ap.parse_args(argv)

    destino = Path(args.json)
    if destino.exists() and not args.fundir:
        print(f"ERROR: {destino} ya existe. Use otro --json o --fundir si de verdad quiere fundir "
              "con la evidencia anterior.", file=sys.stderr)
        return 2
    trabajo = directorio_de_trabajo(args.trabajo or None)
    print(f"directorio de la corrida: {trabajo}", flush=True)
    lista_path = Path(args.lista) if args.lista else trabajo / "lista_tablero.json"
    parcial = trabajo / "lecturas_tablero.json"
    fallidos: list[str] = []
    try:
        if not args.lista:
            if correr(["--fotos", args.fotos, "--lista", str(lista_path),
                       "--json", str(destino), "--salida", args.salida]) != 0:
                return 1
        elif not lista_path.exists():
            print(f"ERROR: la lista indicada no existe: {lista_path}", file=sys.stderr)
            return 2
        lista = json.loads(lista_path.read_text(encoding="utf-8"))
        casos = [c.strip() for c in args.casos.split(",") if c.strip()] or list(lista)
        for clave in casos:
            if clave not in lista:
                fallidos.append(f"{clave}: no está en la lista")
                continue
            caso = lista[clave]
            total = len(caso["elegidas"])
            for desde in range(0, total, args.lote):
                codigo = correr(["--fotos", args.fotos, "--json", str(destino),
                                 "--salida", args.salida, "--catalogo", args.catalogo,
                                 "--lista", str(lista_path), "--parcial", str(parcial),
                                 "--rango", f"{desde}:{desde + args.lote}", "--caso", clave])
                if codigo != 0:
                    fallidos.append(f"{clave} {desde}:{desde + args.lote} (código {codigo})")
                    print(f"  ERROR: el tramo {clave} {desde} terminó con código {codigo}",
                          flush=True)
        if not parcial.exists():
            print("ninguna foto leída: no hay parcial que cerrar", file=sys.stderr)
            return 2 if fallidos else 0
        codigo = correr(["--cerrar", "--json", str(destino), "--salida", args.salida,
                         "--parcial", str(parcial)])
        if fallidos:
            (trabajo / "tramos_fallidos.json").write_text(
                json.dumps(fallidos, ensure_ascii=False, indent=1), encoding="utf-8")
            print("TRAMOS FALLIDOS (sus fotos NO cuentan como examinadas):\n  "
                  + "\n  ".join(fallidos), file=sys.stderr)
            return 2
        return codigo
    finally:
        if fallidos or args.conservar_trabajo:
            print(f"se conserva {trabajo}", flush=True)
        else:
            shutil.rmtree(trabajo, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
