#!/usr/bin/env python3
"""Descarga las fotos de `OsirisSG79/Contexto-imagenes` (una carpeta por caso) para leer etiquetas.

    python descargar_fotos_repo.py --destino /var/tmp/fotos --token <pat> [--caso "232550"] [--limite 12]

Deja `<destino>/<caso>/<NACH|VOR>/<foto>.JPG`, que es la forma que espera `evidencia_modulo.py`.
"""
from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = "OsirisSG79/Contexto-imagenes"


def arbol(token: str) -> list[str]:
    url = f"https://api.github.com/repos/{REPO}/git/trees/main?recursive=1"
    peticion = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}",
                                                    "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(peticion, timeout=120) as respuesta:
        datos = json.load(respuesta)
    return [e["path"] for e in datos["tree"]
            if e["type"] == "blob" and e["path"].lower().endswith((".jpg", ".jpeg", ".png"))]


def destino_de(ruta: str, destino: Path) -> Path:
    """`HT/232550 RDW NOM HT/PHOTOS/NACH/IMG_4156.JPG` -> `<destino>/232550 RDW NOM HT/NACH/IMG_4156.JPG`."""
    partes = ruta.split("/")
    if len(partes) < 4:
        return destino / Path(*partes)
    caso, lado, nombre = partes[1], partes[-2], partes[-1]
    return destino / caso / lado / nombre


def descargar(ruta: str, destino: Path, token: str) -> str | None:
    salida = destino_de(ruta, destino)
    if salida.exists() and salida.stat().st_size > 0:
        return None
    salida.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://raw.githubusercontent.com/{REPO}/main/{urllib.parse.quote(ruta)}"
    peticion = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    for intento in range(3):
        try:
            with urllib.request.urlopen(peticion, timeout=180) as respuesta:
                datos = respuesta.read()
            salida.write_bytes(datos)
            return ruta
        except Exception as error:  # red intermitente: se reintenta
            if intento == 2:
                print(f"  fallo {ruta}: {error}", flush=True)
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Descarga las fotos del repositorio de contexto")
    ap.add_argument("--destino", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--caso", default=None, help="sólo un caso (número o parte del nombre)")
    ap.add_argument("--limite", type=int, default=None, help="máximo de fotos por caso")
    ap.add_argument("--hilos", type=int, default=8)
    args = ap.parse_args(argv)

    rutas = arbol(args.token)
    if args.caso:
        rutas = [r for r in rutas if args.caso in r]
    if args.limite:
        por_caso: dict[str, int] = {}
        elegidas = []
        for r in rutas:
            clave = r.split("/")[1] if r.count("/") >= 2 else r
            if por_caso.get(clave, 0) >= args.limite:
                continue
            por_caso[clave] = por_caso.get(clave, 0) + 1
            elegidas.append(r)
        rutas = elegidas
    destino = Path(args.destino)
    print(f"fotos a descargar: {len(rutas)} -> {destino}", flush=True)
    with ThreadPoolExecutor(max_workers=args.hilos) as pool:
        hechas = [r for r in pool.map(lambda r: descargar(r, destino, args.token), rutas) if r]
    print(f"descargadas: {len(hechas)} · casos: {len({r.split('/')[1] for r in rutas if r.count('/') > 1})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
