"""Busca en otro caso las fotos que más se parecen a una foto de referencia.

Las fotos del libro se toman siempre con la misma secuencia de vistas, así que la toma donde se ve
el número moldeado del 222504 (`VOR/IMG_1598.JPG`) tiene su equivalente en cada caso. Emparejar por
puntos ORB es barato (no llama al OCR) y ahorra barrer las 130 fotos de cada carpeta.

Uso: python3 fotos_parecidas.py --referencia "222504 RDW NOM NT/VOR/IMG_1598.JPG" --caso "222509 RDW NOM NT" --cuantas 6
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

EXTENSIONES = ("*.JPG", "*.jpg", "*.jpeg", "*.png")


def fotos_de(carpeta: Path) -> list[Path]:
    salida: list[Path] = []
    for sub in ("NACH", "VOR", ""):
        base = carpeta / sub if sub else carpeta
        if base.is_dir():
            for patron in EXTENSIONES:
                salida.extend(sorted(base.glob(patron)))
    return salida


def huellas(ruta: Path, detector) -> tuple:
    imagen = cv2.imread(str(ruta), cv2.IMREAD_GRAYSCALE)
    if imagen is None:
        return [], None
    escala = 900 / max(imagen.shape)
    vista = cv2.resize(imagen, None, fx=escala, fy=escala) if escala < 1 else imagen
    puntos, descriptores = detector.detectAndCompute(vista, None)
    return puntos, descriptores


def parecidas(referencia: Path, carpeta: Path, cuantas: int = 6) -> list[dict]:
    detector = cv2.ORB_create(nfeatures=900)
    _, referencia_descriptores = huellas(referencia, detector)
    if referencia_descriptores is None:
        return []
    emparejador = cv2.BFMatcher(cv2.NORM_HAMMING)
    filas = []
    for ruta in fotos_de(carpeta):
        _, descriptores = huellas(ruta, detector)
        if descriptores is None:
            continue
        parejas = emparejador.knnMatch(referencia_descriptores, descriptores, k=2)
        buenos = [a for a, b in (pareja for pareja in parejas if len(pareja) == 2)
                  if a.distance < 0.75 * b.distance]
        filas.append({"foto": f"{ruta.parent.name}/{ruta.name}", "ruta": str(ruta),
                      "parecido": len(buenos)})
    filas.sort(key=lambda f: -f["parecido"])
    return filas[:cuantas]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--referencia", required=True)
    ap.add_argument("--caso", required=True)
    ap.add_argument("--fotos", default="/var/tmp/fotos")
    ap.add_argument("--cuantas", type=int, default=6)
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    referencia = Path(args.fotos) / args.referencia
    if not referencia.exists():
        referencia = Path(args.referencia)
    lista = parecidas(referencia, Path(args.fotos) / args.caso, args.cuantas)
    print(json.dumps(lista, ensure_ascii=False, indent=1))
    if args.json:
        Path(args.json).write_text(json.dumps(lista, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
