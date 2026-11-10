"""Compara un libro GENERADO por el pipeline contra el libro de referencia (P08).

Es el medidor que faltaba: hasta ahora las cifras salían de reanalizar lecturas viejas. Este
script toma el `.xlsx` que produjo la corrida y lo compara, campo por campo, con el libro que
tú das por bueno. Lo que salga es lo único que se puede llamar «acertividad».

Uso en Windows:

    python comparar_resultado.py --resultado "resultado_maestro.xlsx" --libro "Book-10-Examples.xlsx"
    python comparar_resultado.py --resultado ... --libro ... --json > comparacion.json

Qué cuenta
----------
- **cobertura**: celdas publicadas / celdas comparables (20 campos del OCR × casos).
- **aciertos**: valores publicados que coinciden con el libro (ignorando puntos/espacios y
  mayúsculas, para no castigar `671ZRZ0539983E` frente a `671 ZRZ0539983E`).
- **errores**: publicados que no coinciden. Se listan con las dos versiones: son los que hay
  que mirar.
- Emparejamiento: por número de prueba; si un caso no aparece (p. ej. porque el propio número
  de prueba se leyó mal), se empareja por posición y se avisa, en vez de perder el caso.

No juzga los tiempos de apertura ni las evaluaciones: eso es el carril de vídeo.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from openpyxl import load_workbook

CAMPOS = ("week", "test_reason", "test_number", "test_date", "test_place",
          "temperature_condition", "module_part_number", "module_version",
          "module_serial_number", "module_date", "engineering_level", "delay_ms",
          "inflator_type", "inflator_supplier", "dashboard_part_number",
          "dashboard_serial_number", "dashboard_date", "dashboard_engineering_level",
          "laser_opening", "dashboard_supplier")


def _texto(valor) -> str:
    if valor is None:
        return ""
    if hasattr(valor, "date"):
        return valor.date().isoformat()
    return " ".join(str(valor).split())


def _clave(valor) -> str:
    return _texto(valor).upper().replace(".", "").replace(" ", "")


def leer(ruta: Path) -> list[dict]:
    """Filas de datos de la matriz, en el orden del libro (columnas 1-20 = CAMPOS)."""
    libro = load_workbook(ruta, data_only=True)
    hoja = libro["Versuchsmatrix"] if "Versuchsmatrix" in libro.sheetnames else libro[libro.sheetnames[0]]
    filas = []
    for fila in range(8, hoja.max_row + 1):
        datos = {campo: _texto(hoja.cell(fila, i).value) for i, campo in enumerate(CAMPOS, 1)}
        if any(datos.values()):
            filas.append({"fila": fila, "datos": datos})
    return filas


def emparejar(generado: list[dict], referencia: list[dict]) -> tuple[list[tuple], list[str]]:
    """Empareja por número de prueba y, lo que sobre, por posición (avisando)."""
    por_numero = {r["datos"]["test_number"]: r for r in referencia if r["datos"]["test_number"]}
    pares, avisos = [], []
    usados = set()
    sobrantes = []
    for fila in generado:
        numero = fila["datos"]["test_number"]
        if numero in por_numero and id(por_numero[numero]) not in usados:
            pares.append((fila, por_numero[numero]))
            usados.add(id(por_numero[numero]))
        else:
            sobrantes.append(fila)
    libres = [r for r in referencia if id(r) not in usados]
    for fila, ref in zip(sobrantes, libres):
        pares.append((fila, ref))
        avisos.append(f"caso emparejado por posición: generado «{fila['datos']['test_number']}» "
                      f"↔ libro «{ref['datos']['test_number']}»")
    return pares, avisos


def comparar(generado: list[dict], referencia: list[dict]) -> dict:
    pares, avisos = emparejar(generado, referencia)
    campos = {campo: {"publicados": 0, "aciertos": 0, "errores": []} for campo in CAMPOS}
    publicados = aciertos = 0
    errores = []
    for fila, ref in pares:
        for campo in CAMPOS:
            valor = fila["datos"].get(campo, "")
            esperado = ref["datos"].get(campo, "")
            if not valor:
                continue
            publicados += 1
            campos[campo]["publicados"] += 1
            coincide = bool(esperado) and _clave(valor) == _clave(esperado)
            if coincide:
                aciertos += 1
                campos[campo]["aciertos"] += 1
            else:
                error = {"caso": fila["datos"].get("test_number") or ref["datos"].get("test_number"),
                         "campo": campo, "publicado": valor, "libro": esperado}
                errores.append(error)
                campos[campo]["errores"].append(error)
    comparables = len(pares) * len(CAMPOS)
    return {
        "casos_emparejados": len(pares),
        "celdas_comparables": comparables,
        "publicados": publicados,
        "aciertos": aciertos,
        "errores": errores,
        "cobertura_pct": round(100 * publicados / comparables, 1) if comparables else 0.0,
        "precision_pct": round(100 * aciertos / publicados, 1) if publicados else 0.0,
        "por_campo": campos,
        "avisos": avisos,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compara el libro generado con el de referencia")
    parser.add_argument("--resultado", required=True, help="libro que generó el pipeline")
    parser.add_argument("--libro", required=True, help="libro que se da por bueno")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    for ruta in (args.resultado, args.libro):
        if not Path(ruta).is_file():
            raise SystemExit(f"no existe: {ruta}")
    informe = comparar(leer(Path(args.resultado)), leer(Path(args.libro)))

    if args.json:
        print(json.dumps(informe, ensure_ascii=False, indent=2))
        return 0

    print("=" * 72)
    print(" COMPARACIÓN CONTRA EL LIBRO DE REFERENCIA")
    print("=" * 72)
    print(f" casos emparejados : {informe['casos_emparejados']} "
          f"({informe['celdas_comparables']} celdas comparables)")
    print(f" cobertura         : {informe['publicados']} publicados "
          f"({informe['cobertura_pct']} %)")
    print(f" precisión         : {informe['aciertos']} de {informe['publicados']} "
          f"publicados = {informe['precision_pct']} %")
    print(f" errores           : {len(informe['errores'])}")
    print("-" * 72)
    for error in informe["errores"]:
        print(f"   {error['caso']} {error['campo']:<26} publicado {error['publicado'] or '—':<16}"
              f" libro {error['libro'] or '—'}")
    print("-" * 72)
    print(" por campo (publicados / aciertos):")
    for campo, dato in informe["por_campo"].items():
        if dato["publicados"]:
            print(f"   {campo:<28} {dato['aciertos']:3d} / {dato['publicados']:3d}")
    for aviso in informe["avisos"]:
        print(f"   aviso: {aviso}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
