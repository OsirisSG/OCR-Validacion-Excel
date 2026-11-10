"""Busca el número moldeado en un caso, sin barrer las 130 fotos.

En el 222504 se barrió la carpeta entera y el número se leyó en **una** foto: `VOR/IMG_1598.JPG`.
Esa foto es la toma de la cara inferior junto al módulo, y esa toma se repite en los demás casos.
Aquí se ordenan las fotos del caso por parecido con esa referencia (ORB, sin OCR), se leen las
primeras y se corta en cuanto hay dos lecturas iguales.

Uso: python3 leer_parte_por_parecido.py --caso "222509 RDW NOM NT" --jsonl /tmp/parte/222509.jsonl
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fotos_parecidas import parecidas  # noqa: E402

LECTOR = Path(__file__).resolve().with_name("leer_parte_foto.py")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--caso", required=True)
    ap.add_argument("--fotos", default="/var/tmp/fotos")
    ap.add_argument("--referencia", default="222504 RDW NOM NT/VOR/IMG_1598.JPG")
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--maximo", type=int, default=8)
    ap.add_argument("--hasta", type=int, default=2, help="corta al juntar estas lecturas iguales")
    args = ap.parse_args()

    carpeta = Path(args.fotos) / args.caso
    referencia = Path(args.fotos) / args.referencia
    lista = parecidas(referencia, carpeta, args.maximo)
    jsonl = Path(args.jsonl)
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    print(f"{args.caso}: se leen {len(lista)} foto(s) de las más parecidas", flush=True)
    conteo: Counter = Counter()
    with jsonl.open("a", encoding="utf-8") as flujo:
        for candidata in lista:
            proceso = subprocess.run([sys.executable, str(LECTOR), candidata["ruta"]],
                                     capture_output=True, text=True, timeout=900)
            try:
                lectura = json.loads(proceso.stdout.strip().splitlines()[-1])
            except Exception:
                lectura = {}
            registro = {"caso": args.caso, "foto": candidata["foto"],
                        "valor": lectura.get("valor", ""), "texto": lectura.get("texto", ""),
                        "confianza": lectura.get("confianza", 0.0),
                        "region": lectura.get("region"), "parecido": candidata["parecido"],
                        "cola": bool(lectura.get("cola"))}
            flujo.write(json.dumps(registro, ensure_ascii=False) + "\n")
            flujo.flush()
            if registro["valor"]:
                conteo[registro["valor"]] += 1
                print(f"   {candidata['foto']} (parecido {candidata['parecido']}) -> "
                      f"{registro['valor']} «{registro['texto'][:24]}»", flush=True)
                if conteo[registro["valor"]] >= args.hasta:
                    break
            else:
                print(f"   {candidata['foto']} (parecido {candidata['parecido']}) -> sin lectura",
                      flush=True)
    print(f"{args.caso}: {conteo.most_common(2) or 'sin lectura'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
