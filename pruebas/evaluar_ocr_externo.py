"""Evalúa fotografías externas de placas grabadas sin redistribuirlas.

Uso después de obtener y descomprimir ``Data.zip`` de Embossed-Text-Reader:

    python pruebas/evaluar_ocr_externo.py /ruta/a/Data/images

La fuente no declara una licencia de redistribución, por lo que las imágenes no
se copian al repositorio. Este script conserva únicamente el ground truth leído
visualmente y métricas reproducibles.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ocr_engine import extraer_texto


CASOS = {
    "test4.jpg": "IBC20",
    "test5.jpg": "GCC10",
    "test18.jpg": "123456789",
    "test2.jpg": "96819216",
}


def normalizar(texto: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", texto.upper())


def distancia_edicion(a: str, b: str) -> int:
    anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        actual = [i]
        for j, cb in enumerate(b, 1):
            actual.append(min(actual[-1] + 1, anterior[j] + 1,
                              anterior[j - 1] + (ca != cb)))
        anterior = actual
    return anterior[-1]


def evaluar(directorio: Path) -> dict:
    resultados = []
    for nombre, esperado in CASOS.items():
        ruta = directorio / nombre
        inicio = time.perf_counter()
        ocr = extraer_texto(str(ruta))
        tokens = [t["texto"] for t in ocr["tokens"]]
        candidatos = [normalizar(t) for t in tokens] or [""]
        mejor = min(candidatos, key=lambda t: distancia_edicion(esperado, t))
        distancia = distancia_edicion(esperado, mejor)
        similitud = 1.0 - distancia / max(len(esperado), len(mejor), 1)
        resultados.append({
            "imagen": nombre,
            "esperado": esperado,
            "mejor_candidato": mejor,
            "coincidencia_exacta": mejor == esperado,
            "similitud_caracteres": round(similitud, 4),
            "tokens": tokens,
            "orientacion_grados": ocr["orientacion_corregida_grados"],
            "variante": ocr["variante_preprocesamiento"],
            "intentos": len(ocr["intentos_ocr"]),
            "segundos": round(time.perf_counter() - inicio, 2),
        })
    exactos = sum(r["coincidencia_exacta"] for r in resultados)
    return {
        "casos": len(resultados),
        "exactos": exactos,
        "exactitud": round(exactos / len(resultados), 4),
        "similitud_media_caracteres": round(
            sum(r["similitud_caracteres"] for r in resultados) / len(resultados), 4),
        "resultados": resultados,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark externo de placas grabadas.")
    parser.add_argument("directorio", type=Path, help="Carpeta Data/images del benchmark.")
    args = parser.parse_args()
    faltantes = [n for n in CASOS if not (args.directorio / n).is_file()]
    if faltantes:
        parser.error(f"faltan imágenes: {', '.join(faltantes)}")
    print(json.dumps(evaluar(args.directorio), ensure_ascii=False, indent=2))
