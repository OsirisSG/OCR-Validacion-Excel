#!/usr/bin/env python3
"""P42 · vuelca la evidencia del tablero en el libro: sin pisar celdas y sin publicar dudas.

    python3 rellenar_tablero_p42.py --libro versionV16_0_48.xlsx \
        --evidencia evidencia_tablero_p42.json --salida versionV16_0_50.xlsx \
        [--decisiones decisiones_p42.json]

Reglas, después de la revisión técnica de P42 (F3 y F5):

1. **No se escribe nada que el motor marque dudoso.** Antes había una excepción amplia para la
   serie que venía del DataMatrix, y por ahí se colaba un valor dudoso. Ya no existe.
2. La única forma de escribir un valor dudoso es que haya una **decisión explícita** para esa
   celda: mismo caso, mismo campo y mismo valor, en el archivo `--decisiones`. Esa decisión se
   registra en `Trazabilidad` con su origen y su estado (`manual_validada` o
   `pendiente_de_confirmar`), y **no se aplica a ninguna otra etiqueta**.
3. **Nunca** se sobrescribe una celda ocupada.
4. Cada valor escrito deja su renglón en `Trazabilidad` con el valor **codificado** (lo que traía
   el código, sin tocar), el valor publicado, la regla y la fuente de la decisión.
5. Se escribe en un archivo temporal y luego se cambia: si el libro está abierto en Excel, no se
   destruye nada.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

from openpyxl import load_workbook

HOJAS = ("Versuchsmatrix", "Rangos")      # el libro tiene las dobles en espejo
COL_NUMERO = 3
COLUMNAS = {                              # campo de la evidencia -> columna del libro
    "dashboard_part_number": 15,
    "dashboard_serial_number": 16,
    "dashboard_date": 17,
    "dashboard_engineering_level": 18,
}
CABECERAS = {15: ("número de parte", "numero de parte", "teilnummer"),
             16: ("serie", "serial"),
             17: ("fecha", "datum"),
             18: ("nivel", "stand")}
ETAPA = "1ST"
VERSION = "v50"


def filas_por_caso(hoja) -> dict[str, int]:
    """Número de prueba -> fila. Pura."""
    filas = {}
    for fila in range(8, hoja.max_row + 1):
        valor = hoja.cell(fila, COL_NUMERO).value
        if valor in (None, ""):
            continue
        digitos = "".join(ch for ch in str(valor) if ch.isdigit())
        if digitos:
            filas.setdefault(digitos, fila)
    return filas


def cargar_decisiones(ruta: str) -> dict[tuple[str, str], dict]:
    """`(caso, campo) -> decisión`. Cada decisión autoriza **un valor concreto**. Pura."""
    if not ruta:
        return {}
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    salida = {}
    for entrada in datos:
        clave = (str(entrada.get("caso", "")), str(entrada.get("campo", "")))
        if clave[0] and clave[1]:
            salida[clave] = entrada
    return salida


def autoriza(decision: dict | None, valor) -> bool:
    """¿La decisión cubre exactamente este valor? Pura."""
    if not decision:
        return False
    return str(decision.get("publicada", "")).strip() == str(valor).strip()


def comprobar_hojas(wb) -> list[str]:
    """Devuelve la lista de problemas de estructura; vacía = todo bien. Pura."""
    problemas = []
    for nombre in HOJAS:
        if nombre not in wb.sheetnames:
            problemas.append(f"falta la hoja {nombre}")
            continue
        hoja = wb[nombre]
        for columna, palabras in CABECERAS.items():
            textos = []
            for fila in (6, 7):
                valor = hoja.cell(fila, columna).value
                if valor:
                    textos.append(str(valor).lower())
            if textos and not any(p in " ".join(textos) for p in palabras):
                problemas.append(f"{nombre}: la columna {columna} no parece la de "
                                 f"{palabras[0]} ({textos[0][:40]})")
    if "Trazabilidad" not in wb.sheetnames:
        problemas.append("falta la hoja Trazabilidad")
    return problemas


def main() -> int:
    ap = argparse.ArgumentParser(description="Vuelca la evidencia del tablero en el libro")
    ap.add_argument("--libro", required=True)
    ap.add_argument("--evidencia", required=True)
    ap.add_argument("--salida", required=True)
    ap.add_argument("--decisiones", default="", help="decisiones explícitas por celda (JSON)")
    args = ap.parse_args()

    wb = load_workbook(args.libro)
    problemas = comprobar_hojas(wb)
    if problemas:
        print("ERROR de estructura en el libro; no se escribe nada:")
        for problema in problemas:
            print("  -", problema)
        return 1

    traza = wb["Trazabilidad"]
    # F5: la trazabilidad del tablero necesita dos columnas más (payload y valor codificado).
    # Se añaden con su cabecera; el resto de columnas no se toca.
    for columna, titulo in ((14, "Payload (hex)"), (15, "Valor codificado")):
        if not traza.cell(1, columna).value:
            traza.cell(1, columna).value = titulo
    evidencia = json.loads(Path(args.evidencia).read_text(encoding="utf-8"))
    decisiones = cargar_decisiones(args.decisiones)
    hojas = [(wb[nombre], filas_por_caso(wb[nombre])) for nombre in HOJAS if nombre in wb.sheetnames]

    escritos = saltados_ocupado = saltados_dudoso = 0
    for caso, datos in sorted(evidencia.items()):
        dudosos = datos.get("dudoso") or {}
        for hoja, filas in hojas:
            fila = filas.get(caso)
            if fila is None:
                print(f"{caso}: no está en {hoja.title}, se omite")
                continue
            for campo, columna in COLUMNAS.items():
                valor = datos.get(campo)
                if valor in (None, ""):
                    continue
                celda = hoja.cell(fila, columna)
                if celda.value not in (None, ""):
                    saltados_ocupado += 1
                    continue
                decision = decisiones.get((caso, campo))
                fuente = (datos.get("fuente") or {}).get(campo) or {}
                codificada = str(fuente.get("valor_codificado", ""))
                # Una decisión sólo vale para el valor codificado que se vio al decidir. Si el
                # código dice hoy otra cosa, la decisión está caducada y no se aplica.
                cubre = bool(decision) and (
                    str(decision.get("codificada", "")).strip() == codificada.strip()
                    or autoriza(decision, valor))
                if str((decision or {}).get("estado") or "") == "dejar_en_blanco":
                    # el usuario miró esta celda y decidió que no se publica nada: ni el valor
                    # automático ni una sugerencia. Se respeta aunque el motor no tenga dudas.
                    saltados_dudoso += 1
                    continue
                if cubre:
                    valor = decision.get("publicada", valor)
                elif dudosos.get(campo):
                    saltados_dudoso += 1
                    continue
                if decision and not cubre:
                    print(f"  AVISO {caso} {campo}: hay decisión pero el código dice "
                          f"{codificada!r}; no se aplica")
                celda.value = valor
                escritos += 1
                traza.append([
                    "jetta_gran_turismo", ETAPA, datos.get("caso", caso), "tablero", campo,
                    f"{fuente.get('carpeta', '')}/{fuente.get('foto', '')}", "",
                    str(fuente.get("texto", "") or fuente.get("origen", ""))[:200],
                    valor, str(fuente.get("giro", "")),
                    "datamatrix_sin_transformar" if campo == "dashboard_serial_number" else "tablero",
                    (f"decision_manual:{decision.get('estado', 'manual_validada')}"
                     if decision else "automatica"),
                    VERSION,
                    str(fuente.get("payload_hex", ""))[:200],
                    codificada,
                ])

    # se guarda al lado y luego se cambia: si Excel tiene el libro abierto, no se destruye nada
    destino = Path(args.salida)
    temporal = Path(tempfile.mkstemp(suffix=".xlsx", dir=str(destino.parent or Path(".")))[1])
    try:
        wb.save(temporal)
        os.replace(temporal, destino)
    except PermissionError:
        temporal.unlink(missing_ok=True)
        print(f"ERROR: no se pudo escribir {destino}. ¿Está abierto en Excel? Ciérralo y repite.")
        return 2
    print(f"escritas {escritos} celdas · {saltados_ocupado} ya tenían valor · "
          f"{saltados_dudoso} no se escribieron por dudosas (sin decisión explícita)")
    print(f"guardado {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
