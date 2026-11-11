#!/usr/bin/env python3
"""Evidencia de vídeo por caso: **fecha**, **lugar**, **número** y **semana**, con captura.

Se ejecuta aparte del relleno porque así se puede procesar carpeta a carpeta sin cargar el libro ni
las fotos en el mismo proceso (con muchas cámaras eso agota la memoria):

    python evidencia_video.py --casos "C:\\Programas Base\\Resumen-1-Step" --salida evidencia_video

Deja, por caso:

* `evidencia_video/<caso>.png` — captura con la **cabecera** (lugar) y la **barra** (fecha/número)
  ampliadas y lo leído escrito debajo;
* `evidencia_video.json` — lo leído, campo por campo, con votos y ruta de la captura.

Después `rellenar_desde_referencia.py --video-json evidencia_video.json` usa ese JSON y no vuelve a
abrir los vídeos.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from rellenar_desde_videos import leer_caso, mapa_de_casos
from utilidades import lector_etiquetas as L
from utilidades import video_cabecera as VC
from utilidades.barra_estado import cargar_banco
from utilidades.video_campos import videos


def semana_iso(fecha) -> str:
    from datetime import datetime
    if not fecha:
        return ""
    try:
        return f"{datetime.strptime(str(fecha)[:10], '%Y-%m-%d').date().isocalendar().week:02d}"
    except ValueError:
        return ""


def procesar_caso(numero: str, rutas, motor, banco, carpeta_capturas: Path) -> dict:
    barra = leer_caso(rutas, banco)
    texto_barra = (barra.get("__resumen__") or {}).get("texto", "")
    fecha = (barra.get("test_date") or {}).get("valor", "")
    lectura_cabecera, captura = {}, ""
    mejor_fotograma, mejor_lectura = None, {}
    for ruta in rutas:
        lectura = VC.leer_cabecera_de_video(ruta, motor, muestras=2)
        if not lectura.get("lugar"):
            continue
        lectura_cabecera = lectura
        if lectura.get("fotograma") is not None:
            mejor_fotograma, mejor_lectura = lectura["fotograma"], lectura.get("lectura") or {}
            captura = str(carpeta_capturas / f"{numero}_{Path(ruta).stem}.png")
            VC.captura_de_evidencia(mejor_fotograma, mejor_lectura,
                                    {"numero": (barra.get("test_number") or {}).get("valor", numero),
                                     "fecha": fecha, "semana": semana_iso(fecha), "texto": texto_barra},
                                    Path(captura))
        break
    return {
        "caso": numero,
        "numero_barra": ((barra.get("test_number") or {}).get("valor", "")
                         if (barra.get("test_number") or {}).get("valor", "") == numero else ""),
        "fecha": fecha,
        "semana": semana_iso(fecha),
        "lugar": lectura_cabecera.get("lugar", ""),
        "lugar_leido": lectura_cabecera.get("lugar_leido", ""),
        "lugar_barra": (barra.get("test_place") or {}).get("valor", ""),
        "texto_barra": texto_barra,
        "votos_barra": {campo: (dato or {}).get("acuerdo") for campo, dato in barra.items()
                        if campo != "__resumen__"},
        "captura": captura,
        "videos": [Path(r).name for r in rutas],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Evidencia de vídeo (fecha, lugar, número, semana)")
    ap.add_argument("--casos", required=True, help="árbol con una carpeta por caso y sus VIDEOS")
    ap.add_argument("--salida", default="evidencia_video", help="carpeta de capturas")
    ap.add_argument("--json", default="evidencia_video.json")
    ap.add_argument("--casos-concretos", default=None,
                    help="lista separada por comas; por defecto todas las carpetas con vídeos")
    args = ap.parse_args(argv)

    raiz = Path(args.casos)
    if not raiz.is_dir():
        print(f"no existe la carpeta de casos: {raiz}")
        return 1
    queridos = {c.strip() for c in (args.casos_concretos or "").split(",") if c.strip()}
    encontrados = mapa_de_casos(raiz, queridos or None)
    if not encontrados:
        print(f"no hay carpetas con vídeos en {raiz}")
        return 1
    motor = L.motor_disponible()
    banco = cargar_banco(Path(__file__).resolve().parent / "aprendizaje" / "barra_estado.json")
    capturas = Path(args.salida)
    capturas.mkdir(parents=True, exist_ok=True)
    resultados = {}
    for numero, rutas in sorted(encontrados.items()):
        if not videos(rutas[0].parent):
            continue
        datos = procesar_caso(numero, rutas, motor, banco, capturas)
        resultados[numero] = datos
        print(f"  {numero}: numero={datos['numero_barra'] or '?':6s} fecha={datos['fecha'] or '?':10s} "
              f"semana={datos['semana'] or '?':2s} lugar={datos['lugar'] or '?'} "
              f"«{datos['lugar_leido'] or 'sin leer'}»")
    Path(args.json).write_text(json.dumps(resultados, ensure_ascii=False, indent=1), encoding="utf-8")
    con_fecha = sum(1 for d in resultados.values() if d["fecha"])
    con_lugar = sum(1 for d in resultados.values() if d["lugar"])
    print(f"casos: {len(resultados)} · con fecha {con_fecha} · con lugar {con_lugar} · "
          f"json {args.json} · capturas {capturas}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
