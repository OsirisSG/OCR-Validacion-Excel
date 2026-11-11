#!/usr/bin/env python3
"""P42 · mete el barrido del DataMatrix en el parcial del tablero antes de cerrar.

Lo que decodifica el DataMatrix **sustituye** a lo que el OCR leyó para esa columna: el código
lleva corrección de errores y el texto impreso no. Las columnas que toca son sólo dos:

  * `dashboard_serial_number` — la serie (`052 3KVJ008…`),
  * `dashboard_part_number`   — el número de parte, cuando viene en el mismo payload.

    python3 fundir_datamatrix.py --parcial /tmp/p42/lecturas.json --dm /tmp/p42/dm.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Funde el DataMatrix en el parcial del tablero")
    ap.add_argument("--parcial", required=True)
    ap.add_argument("--dm", required=True)
    ap.add_argument("--salida", default="")
    args = ap.parse_args()
    parcial = Path(args.parcial)
    datos = json.loads(parcial.read_text(encoding="utf-8"))
    dm = json.loads(Path(args.dm).read_text(encoding="utf-8"))

    fundidos = []
    for caso, lecturas in dm.items():
        if not lecturas:
            continue
        registro = None
        for clave, valor in datos.items():
            if clave == caso:
                registro = valor
                break
        if registro is None:
            print(f"{caso}: no está en el parcial, se omite")
            continue
        columnas = registro.setdefault("lecturas", {})
        columnas["dashboard_serial_number"] = [
            {"valor": l["valor"], "confianza": l.get("confianza", 0.9), "foto": l["foto"],
             "carpeta": l["carpeta"], "origen": "datamatrix", "ancla": "", "descartada": False}
            for l in lecturas]
        partes = [l for l in lecturas if l.get("parte")]
        if partes:
            columnas["dashboard_part_number"] = [
                {"valor": l["parte"], "confianza": 0.95, "foto": l["foto"], "carpeta": l["carpeta"],
                 "origen": "datamatrix", "ancla": "", "descartada": False}
                for l in partes]
        fundidos.append(f"{caso}:{lecturas[0]['valor']}"
                        f"{' + ' + partes[0]['parte'] if partes else ''}")
    destino = Path(args.salida) if args.salida else parcial
    destino.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    print(f"fundidos {len(fundidos)} caso(s) · escrito {destino}")
    for linea in fundidos:
        print("  ", linea)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
