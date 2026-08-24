"""
pipeline.py — Orquestador de las Fases 0 a 3 en una sola ejecución.

Uso:
    python pipeline.py <ruta_raiz>

Ejecuta: mapeo de estructura → validación cruzada → Excel maestro, usando los
artefactos y rutas de config.yaml. Retorna/imprime un resumen por fase (doc §11).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Callable

from configuracion import RAIZ_PROYECTO, cargar_config
from estructura import carpetas_hoja, guardar_estructura, mapear_estructura
from generar_excel import generar_excel
from validacion import validar_lote


def ejecutar_pipeline(ruta_raiz: str | Path, config: dict | None = None,
                      al_progreso: Callable[[str, str], None] | None = None) -> dict:
    """Corre las Fases 0-3 y retorna un dict con artefactos y resumen por fase."""
    config = config or cargar_config()
    resumen: dict = {"raiz": str(ruta_raiz), "fases": {}}

    def progreso(fase: str, mensaje: str) -> None:
        if al_progreso:
            al_progreso(fase, mensaje)

    t0 = time.time()
    progreso("fase0", "Analizando la estructura de carpetas")
    estructura = mapear_estructura(ruta_raiz, config)
    ruta_estructura = guardar_estructura(estructura)
    resumen["fases"]["fase0"] = {
        "artifacto": str(ruta_estructura),
        "total_carpetas": estructura["total_carpetas"],
        "patron_dominante": estructura["patron_dominante"],
        "anomalias": len(estructura["anomalias"]),
        "hojas": len(carpetas_hoja(estructura)),
    }

    progreso("fase2", "Ejecutando OCR y validación cruzada")
    validacion = validar_lote(ruta_estructura, config)
    conteo: dict[str, int] = {}
    for fila in validacion["resultados"]:
        conteo[fila["comparacion"]["resultado"]] = conteo.get(fila["comparacion"]["resultado"], 0) + 1
    resumen["fases"]["fase2"] = {
        "artifacto": validacion["archivo_salida"],
        "carpetas_procesadas": validacion["carpetas_procesadas"],
        "resultados": conteo,
    }

    progreso("fase3", "Generando el Excel maestro")
    ruta_excel = generar_excel(
        None, RAIZ_PROYECTO / config.get("fase3", {}).get(
            "archivo_salida", "resultado_maestro.xlsx"), config)
    resumen["fases"]["fase3"] = {"artifacto": str(ruta_excel)}
    resumen["duracion_segundos"] = round(time.time() - t0, 1)
    progreso("completado", "Resultados y Excel actualizados")
    return resumen


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline completo Fases 0-3.")
    parser.add_argument("ruta_raiz", help="Carpeta raíz del lote a procesar.")
    args = parser.parse_args()
    resumen = ejecutar_pipeline(args.ruta_raiz)
    print(json.dumps(resumen, ensure_ascii=False, indent=2))
