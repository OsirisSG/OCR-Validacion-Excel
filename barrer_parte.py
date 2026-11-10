"""Barre **todas** las fotos de un caso buscando el número moldeado del tablero, una por subproceso.

`leer_parte_de_tablero.py` se apoya en el detector de letra punteada para elegir 8 fotos; el
detector no distingue bien (en el 222504 la foto buena quedaba en el puesto 110 de 118), así que
para el número de parte se barren todas y se guarda cada lectura. Es lento (~10 s por foto) y por
eso corre en segundo plano, con `--jsonl` para poder reanudar.

Uso: python3 barrer_parte.py --caso "222504 RDW NOM NT" --jsonl /tmp/parte/222504.jsonl
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

EXTENSIONES = ("*.JPG", "*.jpg", "*.jpeg", "*.png")
LECTOR = Path(__file__).resolve().with_name("leer_parte_foto.py")


def fotos_de(carpeta: Path) -> list[Path]:
    salida: list[Path] = []
    for sub in ("NACH", "VOR", ""):
        base = carpeta / sub if sub else carpeta
        if base.is_dir():
            for patron in EXTENSIONES:
                salida.extend(sorted(base.glob(patron)))
    return salida


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--caso", required=True)
    ap.add_argument("--fotos", default="/var/tmp/fotos")
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--empezar", type=int, default=0)
    args = ap.parse_args()

    carpeta = Path(args.fotos) / args.caso
    jsonl = Path(args.jsonl)
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    hechas = set()
    if jsonl.exists():
        for linea in jsonl.read_text(encoding="utf-8").splitlines():
            try:
                hechas.add(json.loads(linea)["foto"])
            except Exception:
                pass

    pendientes = [f for f in fotos_de(carpeta) if f"{f.parent.name}/{f.name}" not in hechas]
    print(f"{args.caso}: {len(pendientes)} foto(s) por leer · {len(hechas)} ya hechas", flush=True)
    with jsonl.open("a", encoding="utf-8") as flujo:
        for i, ruta in enumerate(pendientes, 1):
            proceso = subprocess.run([sys.executable, str(LECTOR), str(ruta)],
                                     capture_output=True, text=True, timeout=900)
            try:
                lectura = json.loads(proceso.stdout.strip().splitlines()[-1])
            except Exception:
                lectura = {}
            registro = {"caso": args.caso, "foto": f"{ruta.parent.name}/{ruta.name}",
                        "valor": lectura.get("valor", ""), "texto": lectura.get("texto", ""),
                        "confianza": lectura.get("confianza", 0.0),
                        "region": lectura.get("region")}
            flujo.write(json.dumps(registro, ensure_ascii=False) + "\n")
            flujo.flush()
            if registro["valor"]:
                print(f"  [{i}/{len(pendientes)}] {registro['foto']} -> {registro['valor']} "
                      f"({registro['confianza']:.2f}) «{registro['texto'][:26]}»", flush=True)
            elif i % 10 == 0:
                print(f"  ... {i}/{len(pendientes)}", flush=True)

    valores = Counter(json.loads(l)["valor"] for l in jsonl.read_text(encoding="utf-8").splitlines()
                      if json.loads(l).get("valor"))
    print(f"{args.caso}: consenso {valores.most_common(3)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
