#!/usr/bin/env python3
"""P42 · auditoría de cobertura: ¿tenemos todas las fotos? ¿las miramos todas?

    python3 auditar_cobertura.py --repo /var/tmp/fotos_repo --local /var/tmp/fotos \
        --parcial /tmp/lecturas_tablero.json [--informe cobertura.txt]

Tres preguntas, en este orden, porque cada una tapa un agujero distinto:

  1. ¿Está la foto en el repositorio?      → manifiesto: nombre, tamaño y huella por caso.
  2. ¿Está en la copia de trabajo?         → compara el manifiesto del repo con el disco local.
  3. ¿La miró el sistema?                  → compara con las lecturas del parcial (qué foto
                                             produjo qué dato) y con las de la segunda pasada.

La lección del 2026-10-29: la foto de la fecha de 232564 (`NACH/IMG_4408.JPG`) estaba en los
tres sitios menos en el tercero. No faltaba la foto: faltaba la respuesta a «¿la miraste?».
Por eso el informe separa **tenerla** de **haberla mirado**, y un caso con fotos sin mirar no
puede cerrarse como «sin dato».

Umbral: se avisa si queda más del 0 % de fotos sin mirar en un caso que tiene algún campo en
duda. Esa es la condición que, con 50 o 100 carpetas, deja de ser un aviso y pasa a ser un fallo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SUFIJOS = {".jpg", ".jpeg", ".png"}


def manifiesto(carpeta: Path, con_huella: bool = False) -> dict[str, dict]:
    """ruta relativa en minúsculas -> {bytes, huella}. Pura."""
    salida: dict[str, dict] = {}
    for ruta in sorted(carpeta.rglob("*")):
        if not ruta.is_file() or ruta.suffix.lower() not in SUFIJOS:
            continue
        clave = ruta.relative_to(carpeta).as_posix().lower()
        registro = {"bytes": ruta.stat().st_size}
        if con_huella:
            registro["sha1"] = hashlib.sha1(ruta.read_bytes()).hexdigest()[:12]
        salida[clave] = registro
    return salida


def por_caso(base: Path) -> dict[str, dict[str, dict]]:
    """Caso -> {foto: registro}. El nombre de la foto es lo que nos importa, no la carpeta."""
    casos: dict[str, dict[str, dict]] = {}
    # las carpetas de caso pueden estar a cualquier profundidad (`HT/<caso>/PHOTOS/NACH`, etc.)
    candidatas = [d for d in sorted(base.rglob("*")) if d.is_dir()
                  and d.name.split()[0].isdigit() and len(d.name.split()[0]) == 6]
    for carpeta in candidatas:
        caso = carpeta.name.split()[0]
        registro = casos.setdefault(caso, {})
        for ruta in sorted(carpeta.rglob("*")):
            if ruta.is_file() and ruta.suffix.lower() in SUFIJOS:
                registro.setdefault(ruta.name.lower(),
                                    {"bytes": ruta.stat().st_size,
                                     "ruta": str(ruta.relative_to(base))})
    return casos


def miradas(parcial: dict, caso: str) -> set[str]:
    """Nombres de foto que produjeron al menos una lectura en ese caso. Pura."""
    registro = parcial.get(caso) or {}
    vistas: set[str] = set()
    for lecturas in (registro.get("lecturas") or {}).values():
        for lectura in lecturas:
            if lectura.get("foto"):
                vistas.add(str(lectura["foto"]).lower())
    return vistas


def main() -> int:
    ap = argparse.ArgumentParser(description="Cobertura de fotos: tenerlas vs haberlas mirado")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--local", required=True)
    ap.add_argument("--parcial", default="")
    ap.add_argument("--segunda", action="append", default=[],
                    help="JSON de la segunda pasada (buscar_mas.py), repetible")
    ap.add_argument("--informe", default="")
    args = ap.parse_args()

    repo = por_caso(Path(args.repo))
    local = por_caso(Path(args.local))
    parcial = (json.loads(Path(args.parcial).read_text(encoding="utf-8"))
               if args.parcial and Path(args.parcial).exists() else {})
    extra: dict[str, set[str]] = {}
    for ruta in args.segunda:
        if not Path(ruta).exists():
            continue
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
        caso = str(datos.get("caso") or "")
        for lectura in datos.get("lecturas") or []:
            extra.setdefault(caso, set()).add(str(lectura.get("foto", "")).lower())

    lineas = []
    total_repo = total_local = total_miradas = total_fotos = 0
    faltan_en_local = {}
    sin_mirar = {}
    for caso in sorted(set(repo) | set(local)):
        en_repo = repo.get(caso, {})
        en_local = local.get(caso, {})
        vistas = miradas(parcial, caso) | extra.get(caso, set())
        total_repo += len(en_repo)
        total_local += len(en_local)
        total_miradas += len(vistas & set(en_local))
        total_fotos += len(en_local)
        ausentes = sorted(set(en_repo) - set(en_local))
        if ausentes:
            faltan_en_local[caso] = ausentes
        pendientes = sorted(set(en_local) - vistas)
        if pendientes:
            sin_mirar[caso] = pendientes
        marca = "OK " if not ausentes and not pendientes else ("~  " if not ausentes else "XX ")
        lineas.append(f"  {marca}{caso}  repo {len(en_repo):4d} · local {len(en_local):4d} · "
                      f"miradas {len(vistas & set(en_local)):4d} · "
                      f"sin mirar {len(pendientes):4d}"
                      + (f" · FALTAN {len(ausentes)}" if ausentes else ""))

    cabecera = [
        f"COBERTURA DE FOTOS · {Path(args.local)}",
        f"  fotos en el repositorio ......... {total_repo}",
        f"  fotos en la copia de trabajo .... {total_local}",
        f"  fotos que el sistema miró ....... {total_miradas} "
        f"({total_miradas / max(1, total_fotos) * 100:.1f} % de la copia)",
        "",
        "  caso      repositorio  copia  miradas  sin mirar",
    ]
    texto = "\n".join(cabecera + lineas)
    if faltan_en_local:
        texto += "\n\nFOTOS DEL REPO QUE NO ESTÁN EN LA COPIA (hay que volver a bajarlas):"
        for caso, nombres in faltan_en_local.items():
            texto += f"\n  {caso}: {', '.join(nombres[:8])}" + (" …" if len(nombres) > 8 else "")
    if sin_mirar:
        texto += ("\n\nFOTOS EN DISCO QUE NINGUNA PASADA MIRÓ (aquí estaba el fallo de 232564):")
        for caso, nombres in sin_mirar.items():
            texto += f"\n  {caso}: {len(nombres)} foto(s) · p. ej. {', '.join(nombres[:5])}"
        texto += ("\n  REGLA: un campo no se cierra como «sin dato» mientras este número no sea 0\n"
                  "  en un caso que tenga ese campo en duda.")
    print(texto)
    if args.informe:
        Path(args.informe).write_text(texto + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
