"""Pruebas del relleno del libro desde la barra de los vídeos (P16)."""
from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from openpyxl import load_workbook, Workbook

import rellenar_desde_videos as R

VIDEO = Path("/home/user/casos_video/252590/VIDEOS/det.AVI")
VIDEO_ALTERNO = Path("/tmp/p15v/det.AVI")
RUTA_VIDEO = VIDEO if VIDEO.is_file() else VIDEO_ALTERNO


def libro_falso(ruta: Path, filas: list[dict]) -> Path:
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Versuchsmatrix"
    cabecera = {1: "Semana", 3: "Número de prueba", 4: "Fecha de prueba", 5: "Lugar de prueba",
                6: "Temperatura", 12: "Delay ms", 13: "Tipo de generador"}
    for columna, nombre in cabecera.items():
        hoja.cell(7, columna).value = nombre
    for indice, datos in enumerate(filas, start=8):
        hoja.cell(indice, 3).value = datos.get("test_number")
        for columna, clave in ((4, "test_date"), (5, "test_place"), (6, "temperature_condition"),
                               (12, "delay_ms"), (13, "inflator_type")):
            if clave in datos:
                hoja.cell(indice, columna).value = datos[clave]
    libro.save(ruta)
    return ruta


def campos_de_prueba(acuerdo: float = 1.0, numero: str = "252590") -> dict:
    return {
        "test_number": {"valor": numero, "acuerdo": acuerdo, "acuerdo_interno": 1.0, "video": "v.AVI", "votos": 4, "videos": 4},
        "test_date": {"valor": "2025-06-19", "acuerdo": acuerdo, "acuerdo_interno": 1.0, "video": "v.AVI", "votos": 4, "videos": 4},
        "test_place": {"valor": "EDAG MEX", "acuerdo": acuerdo, "acuerdo_interno": 1.0, "video": "v.AVI", "votos": 4, "videos": 4},
        "delay_ms": {"valor": "0", "acuerdo": acuerdo, "acuerdo_interno": 1.0, "video": "v.AVI", "votos": 4, "videos": 4},
        "temperature_condition": {"valor": "RT", "acuerdo": acuerdo, "acuerdo_interno": 1.0, "video": "v.AVI", "votos": 4, "videos": 4},
    }


class PruebasMapa(unittest.TestCase):
    def test_numero_sale_de_la_carpeta_del_caso(self):
        with TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "1st" / "RT" / "252590 RDW NOM RT" / "VIDEOS").mkdir(parents=True)
            (raiz / "1st" / "RT" / "252590 RDW NOM RT" / "VIDEOS" / "090_FRONTAL.AVI").write_bytes(b"0")
            mapa = R.mapa_de_casos(raiz)
            self.assertEqual(list(mapa), ["252590"])
            self.assertEqual(len(mapa["252590"]), 1)

    def test_solo_cuentan_los_numeros_del_libro(self):
        with TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "999999 otro" / "VIDEOS").mkdir(parents=True)
            (raiz / "999999 otro" / "VIDEOS" / "a.AVI").write_bytes(b"0")
            self.assertEqual(R.mapa_de_casos(raiz, {"252590"}), {})

    def test_se_queda_el_numero_mas_cercano_al_video(self):
        with TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "252590 caso" / "VIDEOS").mkdir(parents=True)
            (raiz / "252590 caso" / "VIDEOS" / "a.AVI").write_bytes(b"0")
            (raiz / "252590 caso" / "20251102 copia" / "VIDEOS").mkdir(parents=True)
            (raiz / "252590 caso" / "20251102 copia" / "VIDEOS" / "b.AVI").write_bytes(b"0")
            mapa = R.mapa_de_casos(raiz, {"252590"})
            self.assertEqual(len(mapa["252590"]), 2)


class PruebasConversion(unittest.TestCase):
    def test_fecha_a_fecha_de_excel(self):
        self.assertEqual(R.a_valor_de_celda("test_date", "2025-06-19"), date(2025, 6, 19))

    def test_delay_a_numero(self):
        self.assertEqual(R.a_valor_de_celda("delay_ms", "0"), 0.0)
        self.assertEqual(R.a_valor_de_celda("delay_ms", "15"), 15.0)

    def test_lugar_queda_como_texto(self):
        self.assertEqual(R.a_valor_de_celda("test_place", "EDAG MEX"), "EDAG MEX")

    def test_fecha_imposible_no_se_convierte(self):
        self.assertIsNone(R.a_valor_de_celda("test_date", "2025-02-30"))
        self.assertIsNone(R.a_valor_de_celda("delay_ms", "cero"))


class PruebasRelleno(unittest.TestCase):
    def _correr(self, filas, campos, simular=False):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        raiz = Path(tmp.name)
        libro = libro_falso(raiz / "libro.xlsx", filas)
        casos = raiz / "casos" / "252590 caso" / "VIDEOS"
        casos.mkdir(parents=True)
        (casos / "a.AVI").write_bytes(b"0")
        salida = raiz / "salida.xlsx"
        with mock.patch.object(R, "leer_caso", return_value=campos), \
             mock.patch.object(R, "cargar_banco", return_value={}):
            R.main(["--libro", str(libro), "--casos", str(raiz / "casos"),
                    "--salida", str(salida)] + (["--simular"] if simular else []))
        hoja = load_workbook(salida if salida.exists() else libro)["Versuchsmatrix"]
        return hoja, salida

    def test_escribe_las_celdas_vacias(self):
        hoja, _ = self._correr([{"test_number": 252590, "temperature_condition": "RT"}], campos_de_prueba())
        self.assertEqual(hoja.cell(8, 4).value.date(), date(2025, 6, 19))
        self.assertEqual(hoja.cell(8, 5).value, "EDAG MEX")
        self.assertEqual(hoja.cell(8, 12).value, 0)

    def test_no_sobrescribe_celda_ocupada(self):
        hoja, _ = self._correr([{"test_number": 252590, "temperature_condition": "NT"}], campos_de_prueba())
        self.assertEqual(hoja.cell(8, 6).value, "NT")

    def test_acuerdo_bajo_no_se_escribe(self):
        hoja, _ = self._correr([{"test_number": 252590}], campos_de_prueba(acuerdo=0.2))
        self.assertIsNone(hoja.cell(8, 5).value)
        self.assertIsNone(hoja.cell(8, 12).value)

    def test_barra_de_otro_ensayo_no_se_escribe(self):
        hoja, _ = self._correr([{"test_number": 252590}], campos_de_prueba(numero="222504"))
        self.assertIsNone(hoja.cell(8, 4).value)

    def test_simular_no_crea_el_libro_de_salida(self):
        with TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            libro = libro_falso(raiz / "libro.xlsx", [{"test_number": 252590}])
            casos = raiz / "casos" / "252590 caso"
            casos.mkdir(parents=True)
            (casos / "a.AVI").write_bytes(b"0")
            salida = raiz / "salida.xlsx"
            with mock.patch.object(R, "leer_caso", return_value=campos_de_prueba()), \
                 mock.patch.object(R, "cargar_banco", return_value={}):
                R.main(["--libro", str(libro), "--casos", str(raiz / "casos"),
                        "--salida", str(salida), "--simular"])
            self.assertFalse(salida.exists())

    def test_caso_sin_video_se_salta(self):
        hoja, _ = self._correr([{"test_number": 222504}], campos_de_prueba())
        self.assertIsNone(hoja.cell(8, 4).value)

    @unittest.skipUnless(VIDEO.is_file() or VIDEO_ALTERNO.is_file(), "hace falta un vídeo de eDAG")
    def test_punta_a_punta_con_un_video_de_verdad(self):
        with TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            libro = libro_falso(raiz / "libro.xlsx", [{"test_number": 252590}])
            casos = raiz / "casos" / "252590 RDW NOM RT" / "VIDEOS"
            casos.mkdir(parents=True)
            (casos / "det.AVI").write_bytes(RUTA_VIDEO.read_bytes())
            salida = raiz / "salida.xlsx"
            R.main(["--libro", str(libro), "--casos", str(raiz / "casos"), "--salida", str(salida)])
            hoja = load_workbook(salida)["Versuchsmatrix"]
            self.assertEqual(hoja.cell(8, 4).value.date(), date(2025, 6, 19))
            self.assertEqual(hoja.cell(8, 5).value, "EDAG MEX")
            self.assertEqual(hoja.cell(8, 12).value, 0)


if __name__ == "__main__":
    unittest.main()
