#!/usr/bin/env python3
"""P26 · las fechas se pueden escribir como texto ISO para que se lean en cualquier visor.

Excel guarda una fecha como número de días (`45805` = 2025-05-28). Los visores que no aplican formatos
enseñan ese número. Con `--fechas-texto` se escribe `2025-05-28`, que se lee igual en todos y sigue
siendo ordenable.

Se comprueba:
1. la conversión afecta a las tres columnas de fecha, en **todas** las hojas espejo;
2. no toca otras columnas ni otras hojas;
3. una celda que no es fecha se queda como está;
4. el formato de la celda pasa a texto (`@`) para que el visor no la reconvierta.
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rellenar_desde_referencia import fechas_a_texto

CABECERAS = ["Semana", "Motivo de prueba", "Número de prueba", "Fecha de prueba", "Lugar de prueba",
             "Temperatura"]


def libro() -> Workbook:
    wb = Workbook()
    principal = wb.active
    principal.title = "Versuchsmatrix"
    espejo = wb.create_sheet("Rangos")
    otra = wb.create_sheet("Diccionario de datos")
    for hoja in (principal, espejo):
        for columna, nombre in enumerate(CABECERAS, 1):
            hoja.cell(7, columna, nombre)
        hoja.cell(8, 3, 232541)
        hoja.cell(8, 4, datetime(2025, 5, 28))
        hoja.cell(9, 4, date(2025, 6, 19))
        hoja.cell(10, 4, "sin fecha")
        hoja.cell(11, 2, "IT BMG")
    otra.cell(1, 1, "Campo")
    return wb


class TestFechasATexto:
    def test_convierte_en_las_dos_hojas(self):
        wb = libro()
        convertidas = fechas_a_texto(wb, wb["Versuchsmatrix"], {})
        assert convertidas == 4                       # 2 fechas × 2 hojas
        for nombre in ("Versuchsmatrix", "Rangos"):
            assert wb[nombre].cell(8, 4).value == "2025-05-28"
            assert wb[nombre].cell(9, 4).value == "2025-06-19"

    def test_formato_de_texto(self):
        wb = libro()
        fechas_a_texto(wb, wb["Versuchsmatrix"], {})
        assert wb["Versuchsmatrix"].cell(8, 4).number_format == "@"

    def test_no_toca_lo_que_no_es_fecha(self):
        wb = libro()
        fechas_a_texto(wb, wb["Versuchsmatrix"], {})
        assert wb["Versuchsmatrix"].cell(10, 4).value == "sin fecha"
        assert wb["Versuchsmatrix"].cell(11, 2).value == "IT BMG"

    def test_no_toca_hojas_ajenas(self):
        wb = libro()
        fechas_a_texto(wb, wb["Versuchsmatrix"], {})
        assert wb["Diccionario de datos"].cell(1, 1).value == "Campo"
