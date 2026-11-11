#!/usr/bin/env python3
"""P23 · el relleno llega a **todas** las hojas espejo y las fechas se ven como fechas.

El libro tiene dos hojas con las mismas cabeceras en la fila 7 (`Versuchsmatrix` y `Rangos`).
Antes sólo se rellenaba la primera y la segunda se quedaba vacía. Además, una fecha escrita en una
celda con formato `General` se veía como `45827` (número de serie de Excel).

Se comprueba:
1. la réplica escribe en la hoja espejo los mismos campos;
2. **no** sobrescribe una celda ocupada;
3. las fechas llevan el formato de la columna (nunca `General`);
4. una hoja con otra estructura (diccionario, trazabilidad) **no** se toca.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rellenar_desde_referencia import (firma_de_cabeceras, formato_de_fecha,
                                       replicar_en_otras_hojas)

CABECERAS = ["Semana", "Motivo de prueba", "Número de prueba", "Fecha de prueba", "Lugar de prueba",
             "Temperatura"]


def libro_de_prueba(ocupada: bool = False) -> Workbook:
    libro = Workbook()
    principal = libro.active
    principal.title = "Versuchsmatrix"
    espejo = libro.create_sheet("Rangos")
    otra = libro.create_sheet("Diccionario de datos")
    for hoja in (principal, espejo):
        for columna, nombre in enumerate(CABECERAS, 1):
            hoja.cell(7, columna, nombre)
        hoja.cell(8, 3, 232541)
        hoja.cell(9, 3, 252590)
        hoja.cell(8, 4).number_format = "mm-dd-yy"
        if ocupada:
            espejo.cell(8, 2, "YA ESCRITO")
    otra.cell(1, 1, "Campo")
    otra.cell(1, 2, "Encabezado")
    return libro


class TestReplicaEnHojasEspejo:
    def test_escribe_en_la_hoja_espejo(self):
        libro = libro_de_prueba()
        aplicados = [{"numero": "232541", "campo": "test_reason", "valor": "IT BMG"}]
        replicadas, hojas = replicar_en_otras_hojas(libro, libro["Versuchsmatrix"], aplicados)
        assert replicadas == 1
        assert libro["Rangos"].cell(8, 2).value == "IT BMG"
        assert any("Rangos" in h for h in hojas)

    def test_no_sobrescribe_lo_ocupado(self):
        libro = libro_de_prueba(ocupada=True)
        aplicados = [{"numero": "232541", "campo": "test_reason", "valor": "IT BMG"}]
        replicar_en_otras_hojas(libro, libro["Versuchsmatrix"], aplicados)
        assert libro["Rangos"].cell(8, 2).value == "YA ESCRITO"

    def test_no_toca_hojas_con_otra_estructura(self):
        libro = libro_de_prueba()
        aplicados = [{"numero": "232541", "campo": "test_reason", "valor": "IT BMG"}]
        replicar_en_otras_hojas(libro, libro["Versuchsmatrix"], aplicados)
        otra = libro["Diccionario de datos"]
        assert otra.cell(1, 1).value == "Campo"
        # leer las cabeceras crea celdas vacías, así que se miran los valores, no `max_row`
        assert [(c.row, c.column) for fila in otra.iter_rows() for c in fila
                if c.value not in (None, "")] == [(1, 1), (1, 2)]

    def test_busca_la_fila_por_numero_no_por_posicion(self):
        libro = libro_de_prueba()
        aplicados = [{"numero": "252590", "campo": "test_reason", "valor": "IT BMG"}]
        replicar_en_otras_hojas(libro, libro["Versuchsmatrix"], aplicados)
        assert libro["Rangos"].cell(9, 2).value == "IT BMG"
        assert libro["Rangos"].cell(8, 2).value is None


class TestFormatoDeFecha:
    def test_hereda_el_formato_de_la_columna(self):
        libro = libro_de_prueba()
        assert formato_de_fecha(libro["Rangos"], 4) == "mm-dd-yy"

    def test_la_fecha_no_queda_en_general(self):
        libro = libro_de_prueba()
        principal = libro["Versuchsmatrix"]
        espejo = libro["Rangos"]
        principal.cell(9, 4).number_format = "General"
        aplicados = [{"numero": "252590", "campo": "test_date", "valor": date(2025, 6, 19)}]
        replicar_en_otras_hojas(libro, principal, aplicados)
        assert espejo.cell(9, 4).value == date(2025, 6, 19)
        assert espejo.cell(9, 4).number_format not in ("General", "")

    def test_la_firma_distingue_hojas(self):
        libro = libro_de_prueba()
        assert firma_de_cabeceras(libro["Rangos"]) == firma_de_cabeceras(libro["Versuchsmatrix"])
        assert firma_de_cabeceras(libro["Diccionario de datos"]) != firma_de_cabeceras(libro["Rangos"])
