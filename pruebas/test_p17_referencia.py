"""Pruebas del relleno por constantes del proyecto + semana ISO (P17)."""
from __future__ import annotations

import unittest
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from openpyxl import Workbook, load_workbook

import medir_contra_referencia as M
import rellenar_desde_referencia as R

CABECERAS = {1: "Semana", 2: "Motivo de prueba", 3: "Número de prueba", 4: "Fecha de prueba",
             5: "Lugar de prueba", 6: "Temperatura", 7: "PAB · Número de parte",
             8: "PAB · Variante", 9: "PAB · Serie", 10: "PAB · Fecha fabricación",
             11: "PAB · Nivel de ingeniería", 12: "Delay ms", 13: "Tipo de generador",
             14: "Proveedor de generador", 15: "Tablero · Número de parte",
             16: "Tablero · Serie", 17: "Tablero · Fecha fabricación",
             18: "Tablero · Nivel de ingeniería", 19: "Apertura láser", 20: "Proveedor de tablero"}


def libro(ruta: Path, filas: list[dict]) -> Path:
    hoja = Workbook().active
    hoja.title = "Versuchsmatrix"
    for columna, nombre in CABECERAS.items():
        hoja.cell(7, columna).value = nombre
    for indice, datos in enumerate(filas, start=8):
        for columna, nombre in CABECERAS.items():
            clave = {v: k for k, v in CABECERAS.items()}
            campo = [c for c, t in R.columnas(hoja).items() if t == columna]
            if campo and campo[0] in datos:
                hoja.cell(indice, columna).value = datos[campo[0]]
        hoja.cell(indice, 3).value = datos.get("test_number")
    hoja.parent.save(ruta)
    return ruta


class PruebasConstantes(unittest.TestCase):
    def test_detecta_columna_constante(self):
        with TemporaryDirectory() as tmp:
            ruta = libro(Path(tmp) / "ref.xlsx", [
                {"test_number": 1, "test_reason": "IT BMG"},
                {"test_number": 2, "test_reason": "IT BMG"},
                {"test_number": 3, "test_reason": "IT BMG"}])
            hoja = load_workbook(ruta)["Versuchsmatrix"]
            mapa = R.columnas(hoja)
            const = R.constantes(hoja, mapa, mapa["test_number"])
            self.assertIn("test_reason", const)
            self.assertEqual(const["test_reason"]["valor"], "IT BMG")
            self.assertEqual(const["test_reason"]["casos"], 3)

    def test_columna_variable_no_es_constante(self):
        with TemporaryDirectory() as tmp:
            ruta = libro(Path(tmp) / "ref.xlsx", [
                {"test_number": 1, "temperature_condition": "NT"},
                {"test_number": 2, "temperature_condition": "RT"},
                {"test_number": 3, "temperature_condition": "HT"}])
            hoja = load_workbook(ruta)["Versuchsmatrix"]
            mapa = R.columnas(hoja)
            self.assertNotIn("temperature_condition", R.constantes(hoja, mapa, mapa["test_number"]))

    def test_menos_de_tres_casos_no_hacen_constante(self):
        with TemporaryDirectory() as tmp:
            ruta = libro(Path(tmp) / "ref.xlsx", [
                {"test_number": 1, "test_reason": "IT BMG"},
                {"test_number": 2, "test_reason": "IT BMG"}])
            hoja = load_workbook(ruta)["Versuchsmatrix"]
            mapa = R.columnas(hoja)
            self.assertNotIn("test_reason", R.constantes(hoja, mapa, mapa["test_number"]))


class PruebasSemana(unittest.TestCase):
    def test_semana_iso_desde_fecha(self):
        self.assertEqual(R.semana_iso(date(2025, 6, 19)), "25")
        self.assertEqual(R.semana_iso(datetime(2025, 6, 19)), "25")
        self.assertEqual(R.semana_iso("2025-05-28"), "22")

    def test_semana_iso_con_texto_raro(self):
        self.assertIsNone(R.semana_iso("mucho tiempo"))
        self.assertIsNone(R.semana_iso(None))


class PruebasConvenciones(unittest.TestCase):
    def test_lugar_edag_mex_es_edag(self):
        self.assertEqual(R.aplicar_convencion("test_place", "EDAG MEX"), "EDAG")
        self.assertEqual(R.aplicar_convencion("test_place", "EDAG"), "EDAG")

    def test_delay_cero_es_guiones(self):
        self.assertEqual(R.aplicar_convencion("delay_ms", "0"), "--")
        self.assertEqual(R.aplicar_convencion("delay_ms", "15"), "15")


class PruebasRelleno(unittest.TestCase):
    def test_rellena_constantes_y_semana_sin_tocar_lo_ocupado(self):
        with TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            referencia = libro(raiz / "ref.xlsx", [
                {"test_number": n, "test_reason": "IT BMG", "test_date": datetime(2025, 6, 19),
                 "temperature_condition": "RT"} for n in (1001, 1002, 1003)])
            destino = libro(raiz / "libro.xlsx", [
                {"test_number": 1001, "temperature_condition": "RT"},
                {"test_number": 1002, "temperature_condition": "NT"}])
            salida = raiz / "salida.xlsx"
            R.main(["--libro", str(destino), "--referencia", str(referencia),
                    "--salida", str(salida)])
            hoja = load_workbook(salida)["Versuchsmatrix"]
            self.assertEqual(hoja.cell(8, 2).value, "IT BMG")     # constante escrita
            self.assertEqual(hoja.cell(9, 2).value, "IT BMG")
            self.assertEqual(hoja.cell(8, 6).value, "RT")
            self.assertEqual(hoja.cell(9, 6).value, "NT")         # ocupada: no se toca

    def test_semana_se_calcula_de_la_fecha_existente(self):
        with TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            referencia = libro(raiz / "ref.xlsx", [{"test_number": n} for n in (1, 2, 3)])
            destino = libro(raiz / "libro.xlsx", [
                {"test_number": 2001, "test_date": datetime(2025, 5, 28)}])
            salida = raiz / "salida.xlsx"
            R.main(["--libro", str(destino), "--referencia", str(referencia),
                    "--salida", str(salida)])
            self.assertEqual(load_workbook(salida)["Versuchsmatrix"].cell(8, 1).value, "22")

    def test_simular_no_escribe(self):
        with TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            referencia = libro(raiz / "ref.xlsx", [{"test_number": n, "test_reason": "IT BMG"}
                                                   for n in (1, 2, 3)])
            destino = libro(raiz / "libro.xlsx", [{"test_number": 3001}])
            salida = raiz / "salida.xlsx"
            R.main(["--libro", str(destino), "--referencia", str(referencia),
                    "--salida", str(salida), "--simular"])
            self.assertFalse(salida.exists())


class PruebasMedicion(unittest.TestCase):
    def test_cuenta_coincidencias_y_vacias(self):
        with TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            referencia = libro(raiz / "ref.xlsx", [
                {"test_number": 1001, "test_reason": "IT BMG", "test_place": "EDAG"},
                {"test_number": 1002, "test_reason": "IT BMG", "test_place": "EDAG"}])
            medido = libro(raiz / "mia.xlsx", [
                {"test_number": 1001, "test_reason": "IT BMG", "test_place": "EDAG"},
                {"test_number": 1002, "test_reason": "OTRA"}])
            datos = M.medir(medido, referencia)
            self.assertEqual(datos["casos_comunes"], 2)
            por_campo = {f["campo"]: f for f in datos["detalle"]}
            self.assertEqual(por_campo["test_reason"]["coinciden"], 1)
            self.assertEqual(por_campo["test_reason"]["discrepan"], 1)
            self.assertEqual(por_campo["test_date"]["vacias"], 2)

    def test_fechas_y_numeros_se_comparan_normalizados(self):
        with TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            referencia = libro(raiz / "ref.xlsx", [{"test_number": 1001,
                                                    "test_date": datetime(2025, 6, 19)}])
            medido = libro(raiz / "mia.xlsx", [{"test_number": 1001, "test_date": date(2025, 6, 19)}])
            datos = M.medir(medido, referencia)
            por_campo = {f["campo"]: f for f in datos["detalle"]}
            self.assertEqual(por_campo["test_date"]["coinciden"], 1)


if __name__ == "__main__":
    unittest.main()
