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
    """Caso -> {ruta relativa al caso en minúsculas: registro}.

    P43 · antes la clave era sólo el nombre de la foto: `NACH/IMG_0001.JPG` y `VOR/IMG_0001.JPG`
    colapsaban en una y la segunda desaparecía del recuento (ni presente ni pendiente).
    """
    casos: dict[str, dict[str, dict]] = {}
    # las carpetas de caso pueden estar a cualquier profundidad (`HT/<caso>/PHOTOS/NACH`, etc.)
    candidatas = [d for d in sorted(base.rglob("*")) if d.is_dir()
                  and d.name.split()[0].isdigit() and len(d.name.split()[0]) == 6]
    for carpeta in candidatas:
        caso = carpeta.name.split()[0]
        registro = casos.setdefault(caso, {})
        for ruta in sorted(carpeta.rglob("*")):
            if ruta.is_file() and ruta.suffix.lower() in SUFIJOS:
                registro.setdefault(ruta.relative_to(carpeta).as_posix().lower(),
                                    {"bytes": ruta.stat().st_size,
                                     "ruta": str(ruta.relative_to(base)),
                                     "nombre": ruta.name.lower(),
                                     "carpeta": ruta.parent.name.lower()})
    return casos


def _clave_lectura(lectura: dict, presentes: dict[str, dict]) -> str | None:
    """Ruta relativa de la foto de una lectura, o None si no se puede saber sin adivinar. Pura.

    Las lecturas nuevas traen `ruta_relativa`. Las antiguas sólo `carpeta` (padre) + `foto`: se
    aceptan si identifican UNA sola foto presente; si hay dos candidatas, no se da por mirada.
    """
    if lectura.get("ruta_relativa"):
        return str(lectura["ruta_relativa"]).replace("\\", "/").lower()
    if not lectura.get("foto"):
        return None
    nombre = str(lectura["foto"]).lower()
    carpeta = str(lectura.get("carpeta") or "").lower()
    posibles = [clave for clave, reg in presentes.items()
                if reg.get("nombre") == nombre and (not carpeta or reg.get("carpeta") == carpeta)]
    return posibles[0] if len(posibles) == 1 else None


def miradas(parcial: dict, caso: str, presentes: dict[str, dict] | None = None) -> set[str]:
    """Fotos que produjeron al menos una lectura en ese caso (claves relativas). Pura."""
    registro = parcial.get(caso) or {}
    vistas: set[str] = set()
    for lecturas in (registro.get("lecturas") or {}).values():
        for lectura in lecturas:
            clave = _clave_lectura(lectura, presentes or {})
            if clave:
                vistas.add(clave)
    return vistas


def examinadas_de_parcial(parcial: dict, caso: str) -> set[str]:
    """P43 · fotos que la primera pasada pasó por OCR, con o sin lectura. Pura."""
    return {str(r).lower() for r in ((parcial.get(caso) or {}).get("examinadas") or [])}


def examinadas_de_segunda(datos: dict, presentes: dict[str, dict]) -> tuple[set[str], set[str]]:
    """(examinadas, con_lectura) de un JSON de `buscar_mas.py`. Pura.

    P43 · `examinadas_rutas` lista también las fotos examinadas que NO dieron fecha; los JSON
    antiguos no la traen y entonces sólo cuentan las que produjeron lectura.
    """
    con_lectura = {c for c in (_clave_lectura(l, presentes) for l in datos.get("lecturas") or [])
                   if c}
    examinadas = {str(r).lower() for r in datos.get("examinadas_rutas") or []} | con_lectura
    return examinadas, con_lectura


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
    segundas = []
    for ruta in args.segunda:
        if Path(ruta).exists():
            segundas.append(json.loads(Path(ruta).read_text(encoding="utf-8")))

    lineas = []
    total_repo = total_local = total_miradas = total_fotos = 0
    faltan_en_local = {}
    sin_mirar = {}
    sin_lectura = {}
    for caso in sorted(set(repo) | set(local)):
        en_repo = repo.get(caso, {})
        en_local = local.get(caso, {})
        con_lectura = miradas(parcial, caso, en_local)
        examinadas = set(con_lectura) | examinadas_de_parcial(parcial, caso)
        for datos in segundas:
            if str(datos.get("caso") or "") != caso:
                continue
            ex, cl = examinadas_de_segunda(datos, en_local)
            examinadas |= ex
            con_lectura |= cl
        vistas = examinadas
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
        vacias = sorted((vistas - con_lectura) & set(en_local))
        if vacias:
            sin_lectura[caso] = vacias
        marca = "OK " if not ausentes and not pendientes else ("~  " if not ausentes else "XX ")
        lineas.append(f"  {marca}{caso}  repo {len(en_repo):4d} · local {len(en_local):4d} · "
                      f"miradas {len(vistas & set(en_local)):4d} "
                      f"(sin lectura {len(vacias):4d}) · sin mirar {len(pendientes):4d}"
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
        if sin_lectura:
            texto += "\n\nFOTOS EXAMINADAS SIN LECTURA (miradas; no confundir con «sin mirar»):"
            for caso, nombres in sin_lectura.items():
                texto += f"\n  {caso}: {len(nombres)} foto(s) · p. ej. {', '.join(nombres[:5])}"
        texto += ("\n  REGLA: un campo no se cierra como «sin dato» mientras este número no sea 0\n"
                  "  en un caso que tenga ese campo en duda.")
    print(texto)
    if args.informe:
        Path(args.informe).write_text(texto + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
