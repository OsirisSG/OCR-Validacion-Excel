#!/usr/bin/env python3
"""P42 · barrido del **DataMatrix** del tablero en todas las fotos de todos los casos.

Es el paso más barato del sistema: ~10 ms por foto y ni un solo OCR. Lo que decodifica lleva
corrección de errores, así que sirve como fuente de la serie (`dashboard_serial_number`) sin
depender de que la foto esté entre las candidatas que elige el paso 1.

    python3 barrer_datamatrix.py --fotos /var/tmp/fotos --json /tmp/p42/datamatrix.json
    python3 barrer_datamatrix.py --fotos /var/tmp/fotos --jsonl /tmp/p42/dm.jsonl

`--json` escribe `{caso: [lectura, …]}` y `--jsonl` una lectura por línea (para acumular).
Cada lectura lleva el texto crudo del código y los ajustes aplicados al último glifo, para que
se pueda auditar una por una.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import cv2

from utilidades import tablero_campos as T

SUFIJOS = {".jpg", ".jpeg", ".png"}


def fotos_del_caso(carpeta: Path) -> list[Path]:
    """Todas las fotos del caso, **una vez cada una**. Pura.

    Antes se juntaban varios patrones (`*.JPG`, `*.jpg`, …) y en Windows, donde el glob no
    distingue mayúsculas, cada foto se leía dos veces: coste y votos duplicados. Ahora se filtra
    por sufijo en minúsculas y se quita el duplicado por ruta resuelta.
    """
    vistas: dict[str, Path] = {}
    for ruta in sorted(carpeta.rglob("*")):
        if ruta.is_file() and ruta.suffix.lower() in SUFIJOS:
            vistas.setdefault(str(ruta.resolve()).lower(), ruta)
    return list(vistas.values())


def barrer(fotos: Path, casos: list[str] | None, largo: int) -> dict:
    salida: dict[str, list[dict]] = {}
    for carpeta in sorted(p for p in fotos.iterdir() if p.is_dir()):
        if casos and carpeta.name.split()[0] not in casos:
            continue
        lecturas: list[dict] = []
        inicio = time.time()
        revisadas = 0
        for ruta in fotos_del_caso(carpeta):
            imagen = cv2.imread(str(ruta))
            if imagen is None:
                continue
            revisadas += 1
            alto, ancho = imagen.shape[:2]
            if max(alto, ancho) > largo:
                factor = largo / max(alto, ancho)
                imagen = cv2.resize(imagen, None, fx=factor, fy=factor,
                                    interpolation=cv2.INTER_AREA)
            dato = T.leer_serie_de_datamatrix_resistente(imagen)
            del imagen
            if not dato.get("valor"):
                continue
            lecturas.append({"valor": dato["valor"], "confianza": dato["confianza"],
                             "foto": ruta.name, "carpeta": ruta.parent.name,
                             "origen": dato.get("origen", "datamatrix"),
                             "texto": dato.get("payload_text", ""),
                             "parte": dato.get("parte", ""),
                             "cola_cruda": dato["cola_cruda"],
                             "clase_cola": dato.get("clase_cola", ""),
                             "dudoso": bool(dato.get("dudoso")),
                             "conflicto": list(dato.get("conflicto") or []),
                             "payload_hex": dato.get("payload_hex", ""),
                             "formato": dato.get("formato", ""),
                             "version_decode": dato.get("version_decode", "")})
        salida[carpeta.name.split()[0]] = lecturas
        print(f"{carpeta.name.split()[0]}: {revisadas} fotos, {len(lecturas)} lectura(s) "
              f"en {time.time() - inicio:.1f} s", flush=True)
    return salida


def main() -> int:
    ap = argparse.ArgumentParser(description="Barrido del DataMatrix del tablero")
    ap.add_argument("--fotos", required=True)
    ap.add_argument("--json", default="")
    ap.add_argument("--jsonl", default="")
    ap.add_argument("--casos", default="")
    ap.add_argument("--largo", type=int, default=2000)
    args = ap.parse_args()
    casos = [c.strip() for c in args.casos.split(",") if c.strip()]
    datos = barrer(Path(args.fotos), casos, args.largo)
    if args.json:
        Path(args.json).write_text(json.dumps(datos, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    if args.jsonl:
        with open(args.jsonl, "a", encoding="utf-8") as f:
            for caso, lecturas in datos.items():
                for lectura in lecturas:
                    f.write(json.dumps({"caso": caso, **lectura}, ensure_ascii=False) + "\n")
    total = sum(len(v) for v in datos.values())
    con = sum(1 for v in datos.values() if v)
    print(f"total: {total} lectura(s) en {con} caso(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
