"""Lee el **número de parte moldeado** del tablero (`2GJ.857.003.G`) en todas las fotos de un caso.

Dos pasos, a propósito:

1. `localizar_grabado_punteado()` recorre las fotos **sin OCR** (barato) y se queda con las que
   tienen pinta de llevar letra punteada en relieve.
2. De esas, cada foto se lee en un **subproceso aparte**: el OCR deja ~200 MB por llamada y la
   máquina tiene 2 GB, así que un proceso por foto es lo único que no muere por memoria.

Devuelve el consenso del caso: qué número se repitió y en qué fotos.

Uso: python3 leer_parte_de_tablero.py --caso "222504 RDW NOM NT" --salida /tmp/parte/222504.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utilidades.grabado_punteado import localizar_grabado_punteado  # noqa: E402

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
    ap.add_argument("--salida", required=True)
    ap.add_argument("--maximo", type=int, default=8, help="fotos a leer con OCR")
    args = ap.parse_args()

    carpeta = Path(args.fotos) / args.caso
    candidatas = []
    for ruta in fotos_de(carpeta):
        imagen = cv2.imread(str(ruta))
        if imagen is None:
            continue
        cajas = localizar_grabado_punteado(imagen, maximo=3)
        if cajas:
            candidatas.append({"foto": f"{ruta.parent.name}/{ruta.name}", "ruta": str(ruta),
                               "puntos": sum(c["puntos"] for c in cajas)})
        del imagen
    candidatas.sort(key=lambda c: -c["puntos"])
    elegidas = candidatas[:args.maximo]
    print(f"{args.caso}: {len(candidatas)} foto(s) con grabado punteado, se leen {len(elegidas)}",
          flush=True)

    lecturas = []
    for candidata in elegidas:
        proceso = subprocess.run([sys.executable, str(LECTOR), candidata["ruta"]],
                                 capture_output=True, text=True, timeout=600)
        try:
            lectura = json.loads(proceso.stdout.strip().splitlines()[-1])
        except Exception:
            lectura = {}
        if lectura.get("valor"):
            lectura["foto"] = candidata["foto"]
            lecturas.append(lectura)
            print(f"   {candidata['foto']} -> {lectura['valor']} "
                  f"({lectura['confianza']:.2f}) · «{lectura['texto'][:28]}»", flush=True)

    completos = [l["valor"] for l in lecturas if l.get("cola")]
    medios = [l["valor"] for l in lecturas]
    consenso = Counter(completos or medios).most_common(1)[0] if (completos or medios) else ("", 0)
    informe = {
        "caso": args.caso,
        "candidatas": len(candidatas),
        "leidas": lecturas,
        "valor": consenso[0],
        "votos": consenso[1],
        "fotos": [l["foto"] for l in lecturas if l["valor"] == consenso[0]],
        "completo": bool(completos),
    }
    salida = Path(args.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(informe, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{args.caso}: {informe['valor'] or 'sin lectura'} · {informe['votos']} foto(s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
