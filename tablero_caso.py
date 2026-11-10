#!/usr/bin/env python3
"""Escanea las fotos de UN caso y saca los campos del tablero (Fase 3, P14).

    python tablero_caso.py --carpeta "caso_232550" --caso 232550
    python tablero_caso.py --carpeta "caso_232550" --caso 232550 --dudas dudas.json --pagina dudas.html

- clasifica TODAS las fotos de la carpeta (están mezcladas con las del módulo) por ancla visual;
- deja los recortes de evidencia y un JSON con lo encontrado;
- opcionalmente escribe la página de dudas con la imagen al lado.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from utilidades.tablero_pipeline import EXTENSIONES, a_dudas, analizar_fotos
from utilidades.video_campos import a_dudas as dudas_de_video
from utilidades.video_campos import analizar_videos, congruencia_con_caso, videos


def fotos(carpeta: Path) -> list[Path]:
    return sorted(p for p in carpeta.rglob("*") if p.suffix in EXTENSIONES and p.is_file())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Campos del tablero de un caso")
    ap.add_argument("--carpeta", required=True)
    ap.add_argument("--caso", default="")
    ap.add_argument("--evidencia", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--dudas", default=None)
    ap.add_argument("--pagina", default=None)
    ap.add_argument("--sin-video", action="store_true", help="no leer la barra de los vídeos")
    args = ap.parse_args(argv)

    carpeta = Path(args.carpeta)
    caso = args.caso or carpeta.name
    evidencia = Path(args.evidencia) if args.evidencia else carpeta / "_tablero_evidencia"
    rutas = fotos(carpeta)
    propuestas = analizar_fotos(rutas, caso=caso, carpeta_evidencia=evidencia)
    dudas = a_dudas(caso, propuestas)

    # la fecha, el número y el lugar de prueba vienen de la barra del vídeo, no de las fotos
    rutas_video = videos(carpeta) if not args.sin_video else []
    del_video = congruencia_con_caso(analizar_videos(rutas_video), caso)
    if del_video:
        dudas += dudas_de_video(caso, del_video)

    print(f"{carpeta}: {len(rutas)} fotos · {len(propuestas)} campo(s) del tablero detectado(s)"
          f" · {len(rutas_video)} vídeo(s)")
    resumen_video = del_video.get("__resumen__") if del_video else None
    if resumen_video:
        print(f"  barra del vídeo: {resumen_video['videos_con_barra']}/{resumen_video['videos']} vídeo(s) "
              f"con lectura · {resumen_video['texto'][:70]!r}")
    for campo, propuesta in del_video.items():
        if campo.startswith("__"):
            continue
        print(f"  {campo:32s} {propuesta['estado']:16s} {propuesta['valor']!r} "
              f"(acuerdo {propuesta['acuerdo']:.0%} de {propuesta['videos']} vídeo/s, vídeo)")
    for campo, propuesta in propuestas.items():
        print(f"  {campo:32s} {propuesta.estado:16s} {propuesta.valor!r} "
              f"({len(propuesta.evidencias)} foto/s)")
    if args.json:
        Path(args.json).write_text(json.dumps({"caso": caso,
                                              "propuestas": {k: v.as_dict() for k, v in propuestas.items()},
                                              "propuestas_video": del_video,
                                              "dudas": dudas}, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    if args.dudas:
        Path(args.dudas).write_text(json.dumps(dudas, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.pagina:
        import panel_dudas_html as pagina
        pagina.generar_desde_dudas(dudas, Path(args.pagina), titulo=f"Dudas del tablero · caso {caso}",
                                   subtitulo=f"{len(rutas)} fotos y {len(rutas_video)} vídeos revisados")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
