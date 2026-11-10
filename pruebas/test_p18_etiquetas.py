"""Pruebas de la lectura de etiquetas guiada por anclas (P18)."""
from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from openpyxl import Workbook, load_workbook

import rellenar_desde_referencia as R
from utilidades import lector_etiquetas as L
from utilidades import tablero_lectura as T

GUIA = Path("/home/user/evidencia_guia/etiquetas")
FOTO_AZUL = Path("/home/user/uploads/image-3.png")
FOTO_ROSA = Path("/home/user/uploads/image-4.png")
FOTO_CODIGO = Path("/home/user/uploads/image-5.png")


class PruebasFechas(unittest.TestCase):
    def test_formatos_de_fecha_de_las_etiquetas(self):
        self.assertEqual(L.interpretar_fecha("17/05/2025"), "2025-05-17")
        self.assertEqual(L.interpretar_fecha("17.05.25"), "2025-05-17")
        self.assertEqual(L.interpretar_fecha("17/MAY/2025"), "2025-05-17")
        self.assertEqual(L.interpretar_fecha("17 MAY 2025"), "2025-05-17")
        self.assertEqual(L.interpretar_fecha("1:51:23PM"), None)


class PruebasNivel(unittest.TestCase):
    def test_nivel_directo(self):
        self.assertEqual(L.interpretar_nivel("69K"), ("69K", False))
        self.assertEqual(L.interpretar_nivel("01S"), ("01S", False))

    def test_nivel_reparado_de_la_estampa(self):
        nivel, reparado = L.interpretar_nivel("D3S")      # el OCR lee D por 0
        self.assertEqual(nivel, "03S")
        self.assertTrue(reparado)

    def test_nivel_con_letra_delante(self):
        self.assertEqual(L.interpretar_nivel("S03")[0], "03S")

    def test_nivel_basura(self):
        self.assertEqual(L.interpretar_nivel("AUTOLIV")[0], "")


class PruebasParteYSerie(unittest.TestCase):
    def test_parte_compacto_y_con_puntos(self):
        self.assertEqual(L.interpretar_parte("2GJ880204J"), "2GJ.880.204.J")
        self.assertEqual(L.interpretar_parte("2GJ.857.003.G"), "2GJ.857.003.G")

    def test_serie_del_modulo(self):
        self.assertEqual(L.interpretar_serie("671ZRZ0539958G"), "671 ZRZ0539958G")

    def test_serie_del_tablero_y_su_duda(self):
        seguro = L.interpretar_serie_tablero("*052 3KVJ008R52V")
        self.assertEqual(seguro["valor"], "052 3KVJ008R52V")
        self.assertFalse(seguro["dudoso"])
        dudoso = L.interpretar_serie_tablero("*0523KVJ008R562")
        self.assertEqual(dudoso["valor"], "052 3KVJ008R562")
        self.assertTrue(dudoso["dudoso"])


class PruebasInterpretacion(unittest.TestCase):
    def test_varias_lineas_a_campos(self):
        lectura = L.Lectura(lineas=[("2GJ880204J", 0.9), ("69K", 0.7), ("11/04/2025", 0.8),
                                    ("Autoliv", 0.8)])
        campos = L.interpretar(lectura)
        self.assertEqual(campos["part_number"]["valor"], "2GJ.880.204.J")
        self.assertEqual(campos["engineering_level"]["valor"], "69K")
        self.assertEqual(campos["date"]["valor"], "2025-04-11")
        self.assertEqual(campos["supplier"]["valor"], "Autoliv")

    def test_corroboracion_modulo_tablero(self):
        modulo = {"part_number": {"valor": "2GJ.880.204.J"}}
        tablero = {"part_number": {"valor": "2GJ.857.003.G"}}
        resultado = L.corroborar(modulo, tablero)
        self.assertEqual(resultado["discrepancias"], ["part_number"])


class PruebasSemanaDelNumero(unittest.TestCase):
    def test_estructura_de_la_guia(self):
        self.assertEqual(R.desglose_del_numero("232541"),
                         {"semana": "23", "anio": 2025, "secuencia": "41", "numero": "232541"})

    def test_semana_del_numero_y_corroboracion(self):
        self.assertEqual(R.semana_del_numero(232541)[0], "23")
        self.assertEqual(R.semana_del_numero(252590, datetime(2025, 6, 19))[0], "25")

    def test_numero_que_no_cuadra_con_la_fecha_no_se_usa(self):
        semana, como = R.semana_del_numero(222550, datetime(2025, 6, 4))
        self.assertIsNone(semana)
        self.assertIn("conflicto", como)

    def test_numero_sin_estructura(self):
        self.assertIsNone(R.desglose_del_numero("12345"))


class PruebasEtiquetasReales(unittest.TestCase):
    @unittest.skipUnless(GUIA.is_dir(), "hacen falta las imágenes de la guía")
    def test_modulo_de_la_guia(self):
        motor = L.motor_disponible()
        if motor is None:
            self.skipTest("no hay motor OCR en este equipo")
        resultado = T.leer_fotos([GUIA / "pag5_img1.jpeg", GUIA / "pag5_img3.jpeg"])
        self.assertEqual(resultado.campos["module_part_number"]["valor"], "2GJ.880.204.J")
        self.assertEqual(resultado.campos["engineering_level"]["valor"], "69K")

    @unittest.skipUnless(FOTO_AZUL.is_file(), "hacen falta las fotos del tablero")
    def test_pestana_azul_da_la_fecha(self):
        motor = L.motor_disponible()
        if motor is None:
            self.skipTest("no hay motor OCR en este equipo")
        resultado = T.leer_fotos([FOTO_AZUL])
        self.assertEqual(resultado.campos["dashboard_date"]["valor"], "2025-05-17")
        self.assertEqual(resultado.campos["dashboard_date"]["ancla"], "pestana_azul")

    @unittest.skipUnless(FOTO_ROSA.is_file(), "hacen falta las fotos del tablero")
    def test_estampa_rosa_da_el_nivel(self):
        motor = L.motor_disponible()
        if motor is None:
            self.skipTest("no hay motor OCR en este equipo")
        resultado = T.leer_fotos([FOTO_ROSA])
        self.assertEqual(resultado.campos["dashboard_engineering_level"]["valor"], "03S")

    @unittest.skipUnless(FOTO_CODIGO.is_file(), "hacen falta las fotos del tablero")
    def test_codigo_del_tablero_queda_en_duda_si_el_final_no_se_lee(self):
        motor = L.motor_disponible()
        if motor is None:
            self.skipTest("no hay motor OCR en este equipo")
        resultado = T.leer_fotos([FOTO_CODIGO])
        campo = resultado.campos.get("dashboard_serial_number")
        self.assertIsNotNone(campo)
        self.assertTrue(campo["dudoso"])
        motivos = [d["motivo"] for d in resultado.dudas]
        self.assertIn("etiqueta_dudosa", motivos)


CABECERAS = {1: "Semana", 2: "Motivo de prueba", 3: "Número de prueba", 4: "Fecha de prueba",
             5: "Lugar de prueba", 6: "Temperatura", 12: "Delay ms", 13: "Tipo de generador",
             17: "Tablero · Fecha fabricación", 18: "Tablero · Nivel de ingeniería"}


def libro_simple(ruta: Path, filas: list[dict]) -> Path:
    hoja = Workbook().active
    hoja.title = "Versuchsmatrix"
    for columna, nombre in CABECERAS.items():
        hoja.cell(7, columna).value = nombre
    for indice, datos in enumerate(filas, start=8):
        for columna, nombre in CABECERAS.items():
            campo = [c for c, col in R.columnas(hoja).items() if col == columna]
            if campo and campo[0] in datos:
                hoja.cell(indice, columna).value = datos[campo[0]]
        hoja.cell(indice, 3).value = datos["test_number"]
    hoja.parent.save(ruta)
    return ruta


class PruebasConstantesEstrictas(unittest.TestCase):
    def test_por_defecto_no_se_copian_las_columnas_de_etiqueta(self):
        with TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            referencia = libro_simple(raiz / "ref.xlsx", [
                {"test_number": n, "test_reason": "IT BMG",
                 "dashboard_date": datetime(2025, 5, 17)} for n in (1001, 1002, 1003)])
            destino = libro_simple(raiz / "libro.xlsx", [{"test_number": 1001}])
            salida = raiz / "salida.xlsx"
            R.main(["--libro", str(destino), "--referencia", str(referencia), "--salida", str(salida)])
            hoja = load_workbook(salida)["Versuchsmatrix"]
            self.assertEqual(hoja.cell(8, 2).value, "IT BMG")     # constante normal: sí
            self.assertIsNone(hoja.cell(8, 17).value)             # etiqueta: no se copia

    def test_con_constantes_completas_si_se_copian(self):
        with TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            referencia = libro_simple(raiz / "ref.xlsx", [
                {"test_number": n, "dashboard_date": datetime(2025, 5, 17)}
                for n in (1001, 1002, 1003)])
            destino = libro_simple(raiz / "libro.xlsx", [{"test_number": 1001}])
            salida = raiz / "salida.xlsx"
            R.main(["--libro", str(destino), "--referencia", str(referencia),
                    "--salida", str(salida), "--constantes-completas"])
            self.assertIsNotNone(load_workbook(salida)["Versuchsmatrix"].cell(8, 17).value)

    def test_la_semana_sale_del_numero_de_prueba(self):
        with TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            referencia = libro_simple(raiz / "ref.xlsx", [{"test_number": n} for n in (1, 2, 3)])
            destino = libro_simple(raiz / "libro.xlsx", [{"test_number": 252590}])
            salida = raiz / "salida.xlsx"
            R.main(["--libro", str(destino), "--referencia", str(referencia), "--salida", str(salida)])
            self.assertEqual(load_workbook(salida)["Versuchsmatrix"].cell(8, 1).value, "25")


if __name__ == "__main__":
    unittest.main()


class PruebasGrabado(unittest.TestCase):
    def test_bandas_de_texto_claro(self):
        import cv2
        import numpy as np
        imagen = np.full((160, 420, 3), 40, np.uint8)
        cv2.putText(imagen, "2GJ.857.003.G", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (200, 200, 200), 2)
        cv2.putText(imagen, "4148399X", (30, 130), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (200, 200, 200), 2)
        bandas = L.bandas_grabadas(imagen)
        self.assertGreaterEqual(len(bandas), 2)

    def test_identificar_parte_con_fragmentos_del_ocr(self):
        identificado = L.identificar_parte(["1857."], ["2GJ.857.003.G"])
        self.assertEqual(identificado["valor"], "2GJ.857.003.G")
        self.assertGreaterEqual(identificado["nucleo"], 3)

    def test_no_identifica_si_no_comparte_el_nucleo(self):
        self.assertIsNone(L.identificar_parte(["9999"], ["2GJ.857.003.G"]))

    def test_catalogo_filtra_lo_que_no_es_numero_de_parte(self):
        self.assertTrue(R.PATRON_PARTE_CATALOGO.match("2GJ.857.003.G"))
        self.assertFalse(R.PATRON_PARTE_CATALOGO.match("Promedio"))
        self.assertFalse(R.PATRON_PARTE_CATALOGO.match("#REF!"))

    @unittest.skipUnless(Path("/home/user/uploads/image-7.png").is_file(), "falta la foto del grabado")
    def test_grabado_ilegible_pide_confirmacion_con_el_catalogo(self):
        motor = L.motor_disponible()
        if motor is None:
            self.skipTest("no hay motor OCR en este equipo")
        resultado = T.leer_fotos([Path("/home/user/uploads/image-7.png")],
                                 catalogo=["2GJ.857.003.G"])
        dudas = [d for d in resultado.dudas if d["campo"] == "dashboard_part_number"]
        self.assertEqual(len(dudas), 1)
        self.assertEqual(dudas[0]["motivo"], "grabado_no_legible")
        valores = [o["valor"] for o in dudas[0]["opciones"]]
        self.assertIn("2GJ.857.003.G", valores)


class PruebasGirosYCatalogo(unittest.TestCase):
    def test_nivel_exige_letra_final(self):
        self.assertEqual(L.interpretar_nivel("002")[0], "")
        self.assertEqual(L.interpretar_nivel("01S")[0], "01S")

    def test_reparacion_contra_catalogo(self):
        reparado = L.reparar_con_catalogo("2GJ 880204 3", ["2GJ.880.204.J"])
        self.assertEqual(reparado["valor"], "2GJ.880.204.J")
        self.assertLessEqual(reparado["distancia"], 2)

    def test_reparacion_no_inventa(self):
        self.assertIsNone(L.reparar_con_catalogo("ZZZ999999Z", ["2GJ.880.204.J"]))

    def test_fecha_del_datamatrix_gana_a_la_impresa(self):
        lectura = L.Lectura(lineas=[("11/04/2025", 0.9), ("10.04.25", 0.8)])
        self.assertEqual(L.interpretar(lectura)["date"]["valor"], "2025-04-10")

    def test_serie_a_medias_queda_en_duda(self):
        lectura = L.Lectura(lineas=[("7JZRZ0539991", 0.78)])
        campos = L.interpretar(lectura)
        self.assertTrue(campos["serial_number"]["dudoso"])

    @unittest.skipUnless(Path("/home/user/uploads/image-8.png").is_file(),
                         "falta la foto del DataMatrix del tablero")
    def test_el_datamatrix_girado_se_lee(self):
        import cv2
        motor = L.motor_disponible()
        if motor is None:
            self.skipTest("no hay motor OCR en este equipo")
        imagen = cv2.imread("/home/user/uploads/image-8.png")[380:720, 590:840]
        _, campos = L.leer_con_giros(imagen, motor, catalogo=["2GJ.857.003.G", "2GJ.880.204.J"])
        serie = campos.get("dashboard_serial_number") or campos.get("serial_number")
        self.assertIsNotNone(serie)
        self.assertTrue(serie["valor"].startswith("052"))
