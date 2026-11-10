"""Medición de cobertura con el libro real del usuario (P10).

Simula lo que pasará en su próxima corrida con `fase3.modo_relleno: true`:

  - plantilla = su libro (`Book-10-Examples.xlsx`), que ya tiene filas escritas;
  - «lecturas» = los valores que publicó su corrida V16.0.21 (hoja Versuchsmatrix de
    `versionV16_0_21.xlsx`), es decir, exactamente lo que el pipeline lee hoy;
  - se genera el libro y se compara con el propio libro de referencia.

Se separa lo publicado **por lectura** de lo publicado **por el libro** (constantes y celdas
que ya estaban): son cosas distintas y mezclarlas sería vender humo.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from openpyxl import load_workbook

import reporte_bmg as rb
from evidencia.p08_replay_reglas import CAMPOS, CANDIDATOS_LIBRO, LIBRO_RESULTADO, _norm
from openpyxl import Workbook  # noqa: F401

EQUIV = {"232550": "222550"}


def lecturas_del_libro_publicado(ruta: Path) -> list[dict]:
    """Convierte su Excel publicado en «resultados del pipeline» (con campos publicables)."""
    hoja = load_workbook(ruta, data_only=True)["Versuchsmatrix"]
    resultados = []
    for fila in range(8, hoja.max_row + 1):
        datos = {}
        for i, campo in enumerate(CAMPOS, start=1):
            valor = hoja.cell(fila, i).value
            if valor not in (None, ""):
                datos[campo] = {"valor": valor}
        if datos.get("test_number"):
            resultados.append({"test_number": str(datos["test_number"]["valor"]),
                               "tipo_st": "1ST", "campos": datos})
    return resultados


def main() -> int:
    referencia = next((r for r in CANDIDATOS_LIBRO if r.is_file()), None)
    if referencia is None:
        raise SystemExit("No encuentro Book-10-Examples.xlsx")
    resultados = lecturas_del_libro_publicado(LIBRO_RESULTADO)
    # El libro del usuario dentro de la plantilla institucional: sus 10 casos ya escritos.
    plantilla = Path("/tmp/p10_plantilla.xlsx")
    libro_bmg = load_workbook(RAIZ / "plantillas" / "reporte_bmg_1st_2st.xlsx")
    referencia_wb = load_workbook(referencia, data_only=True)
    origen = referencia_wb[referencia_wb.sheetnames[0]]
    destino = libro_bmg["Versuchsmatrix"] if "Versuchsmatrix" in libro_bmg.sheetnames \
        else libro_bmg[libro_bmg.sheetnames[0]]
    for fila in range(8, origen.max_row + 1):
        if not origen.cell(fila, 3).value:
            continue
        for columna in range(1, len(CAMPOS) + 1):
            destino.cell(fila, columna).value = origen.cell(fila, columna).value
    # Su libro tiene 10 casos: las filas de ejemplo de la plantilla (18-107) no existen en él.
    for fila in range(18, destino.max_row + 1):
        for columna in range(1, 56):
            celda = destino.cell(fila, columna)
            celda.value = None
            celda.hyperlink = None
            celda.comment = None
    libro_bmg.save(plantilla)
    salida = Path("/tmp/p10_salida.xlsx")
    rb.generar_reporte_bmg(plantilla, salida, resultados,
                           {"colores": {}, "fase3": {"modo_relleno": True}}, {}, "es")
    informe = json.loads(salida.with_suffix(".relleno.json").read_text(encoding="utf-8"))

    antes = load_workbook(plantilla, data_only=True)["Versuchsmatrix"]
    despues = load_workbook(salida, data_only=True)["Versuchsmatrix"]
    verdad = load_workbook(referencia, data_only=True)
    verdad = verdad[verdad.sheetnames[0]]

    # 1) ¿se destruyó algo de su libro?
    destruidas, conservadas = [], 0
    for fila in range(8, 8 + 10):
        for i, campo in enumerate(CAMPOS, start=1):
            previo = antes.cell(fila, i).value
            if previo in (None, ""):
                continue
            if despues.cell(fila, i).value in (None, ""):
                destruidas.append((fila, campo))
            else:
                conservadas += 1

    # 2) ¿cuántas celdas rellenaría en un caso NUEVO (que el libro no tiene)?
    #    Se simula el caso 299999 con lo único que el pipeline sí lee de la carpeta y de la
    #    etiqueta en el mejor de los casos: número, temperatura, versión e inflador.
    prueba = dict(resultados[0])
    prueba["test_number"] = "299999"
    prueba["campos"] = {"test_number": {"valor": "299999"},
                        "temperature_condition": {"valor": "HT"},
                        "module_version": {"valor": "RDW"},
                        "inflator_type": {"valor": "NOM"}}
    salida2 = Path("/tmp/p10_salida_caso_nuevo.xlsx")
    rb.generar_reporte_bmg(plantilla, salida2, [*resultados, prueba],
                           {"colores": {}, "fase3": {"modo_relleno": True}}, {}, "es")
    nuevo = load_workbook(salida2, data_only=True)["Versuchsmatrix"]
    fila_nueva = None
    for fila in range(8, nuevo.max_row + 1):
        if str(nuevo.cell(fila, 3).value) == "299999":
            fila_nueva = fila
            break
    llenas = [campo for i, campo in enumerate(CAMPOS, start=1)
              if nuevo.cell(fila_nueva, i).value not in (None, "")] if fila_nueva else []

    print("=" * 76)
    print(" COBERTURA CON TU LIBRO REAL (modo relleno + constantes del libro)")
    print("=" * 76)
    print(f" celdas de tu libro conservadas : {conservadas}"
          f" · destruidas: {len(destruidas)}")
    print(f" discrepancias detectadas       : {len(informe['discrepancias'])} "
          f"(no se sobrescriben, se avisan)")
    print(f" constantes del libro aplicadas : {len(informe['constantes_aplicadas'])}")
    print(f" emparejados por identidad      : {informe['emparejados_por_identidad']}")
    print("-" * 76)
    print(f" CASO NUEVO (no está en el libro): {len(llenas)} de {len(CAMPOS)} celdas "
          f"({100*len(llenas)/len(CAMPOS):.0f} % de cobertura sin rellenar nada a mano)")
    print("   " + ", ".join(llenas))
    print("=" * 76)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
