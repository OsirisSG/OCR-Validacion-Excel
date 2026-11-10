"""Pruebas de la lectura de la barra de estado del vídeo (P15)."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import cv2
import numpy as np

from utilidades import barra_estado as B
from utilidades import video_campos as V

RAIZ = Path(__file__).resolve().parent.parent
BANCO = RAIZ / "aprendizaje" / "barra_estado.json"
TEXTO_REAL = ("VW316/5 252590 RdW RT NOM 0ms EDAG Mex BMG 19 JUN 25 Rec5000 fps, Schutter 80us")
VIDEO = Path("/home/user/casos_video/252590/VIDEOS/det.AVI")
VIDEO_ALTERNO = Path("/tmp/det.AVI")
RUTA_VIDEO = VIDEO if VIDEO.is_file() else VIDEO_ALTERNO


def barra_sintetica(texto: str, paso: int = 11, alto: int = 772, ancho: int = 960) -> np.ndarray:
    imagen = np.zeros((alto, ancho, 3), np.uint8)
    for i, caracter in enumerate(texto):
        x = 3 + i * paso
        if x + paso > ancho:
            break
        if caracter == " ":
            continue
        cv2.putText(imagen, caracter, (x, alto - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1)
    return imagen


class PruebasBarra(unittest.TestCase):
    def test_franja_es_el_3_por_ciento_inferior(self):
        imagen = np.zeros((772, 960, 3), np.uint8)
        trozo = B.franja(imagen)
        self.assertGreaterEqual(trozo.shape[0], 18)
        self.assertLessEqual(trozo.shape[0], int(772 * 0.05))
        self.assertEqual(trozo.shape[0], imagen.shape[0] - (772 - trozo.shape[0]))

    def test_binarizar_deja_texto_blanco(self):
        imagen = np.zeros((40, 200, 3), np.uint8)
        cv2.putText(imagen, "abc", (5, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        binaria = B.binarizar(imagen)
        self.assertEqual(int(binaria.max()), 255)
        self.assertGreater(int((binaria > 0).sum()), 20)

    def test_avance_mide_el_paso_monoespaciado(self):
        imagen = barra_sintetica("HHHHHHHHHHHH")
        binaria = B.binarizar(B.franja(imagen))
        self.assertEqual(B.avance(binaria), 11)

    def test_segmentar_devuelve_espacios_entre_palabras(self):
        imagen = barra_sintetica("AB CD")
        binaria = B.binarizar(B.franja(imagen))
        celdas = B.segmentar(binaria, B.avance(binaria))
        self.assertTrue(any(glifo is None for _, glifo in celdas))

    def test_interpretar_barra_saca_los_ocho_campos(self):
        campos = B.interpretar_barra(TEXTO_REAL)
        self.assertEqual(campos["test_date"], "2025-06-19")
        self.assertEqual(campos["test_number"], "252590")
        self.assertEqual(campos["test_place"], "EDAG MEX")
        self.assertEqual(campos["delay_ms"], "0")
        self.assertEqual(campos["temperature_condition"], "RT")
        self.assertEqual(campos["inflator_type"], "NOM")
        self.assertEqual(campos["proyecto"], "VW316/5")

    def test_interpretar_barra_aguanta_espacios_de_mas(self):
        campos = B.interpretar_barra("  VW316/5   252590   RdW  RT  NOM  0ms  EDAG Mex  BMG  19 JUN 25 ")
        self.assertEqual(campos["test_number"], "252590")
        self.assertEqual(campos["test_date"], "2025-06-19")

    def test_interpretar_barra_sin_fecha_no_inventa(self):
        campos = B.interpretar_barra("VW316/5 252590 RdW RT NOM 0ms EDAG Mex")
        self.assertNotIn("test_date", campos)

    def test_ajustar_a_lexico_solo_arregla_cerca(self):
        self.assertEqual(B.ajustar_a_lexico("RDW", ["RDW"]), "RDW")
        self.assertEqual(B.ajustar_a_lexico("rdw", ["RDW"]), "RDW")
        self.assertIsNone(B.ajustar_a_lexico("R5MM", ["RDW"]))
        self.assertIsNone(B.ajustar_a_lexico("ZZZZZZ", ["RDW"]))

    def test_distancia_de_edicion(self):
        self.assertEqual(B._distancia("RDW", "RDW"), 0)
        self.assertEqual(B._distancia("RT", "NT"), 1)
        self.assertEqual(B._distancia("", "AB"), 2)

    def test_leer_imagen_en_negro_devuelve_vacio(self):
        lectura = B.leer(np.zeros((772, 960, 3), np.uint8))
        self.assertEqual(lectura["texto"].strip(), "")

    def test_leer_video_con_archivo_inexistente(self):
        lectura = B.leer_video("/tmp/no_existe_12345.AVI")
        self.assertEqual(lectura["muestras"], 0)
        self.assertEqual(lectura["campos"], {})

    def test_banco_guarda_el_alineamiento(self):
        self.assertTrue(BANCO.is_file())
        datos = json.loads(BANCO.read_text(encoding="utf-8"))
        self.assertIn("paso", datos)
        self.assertGreaterEqual(datos["paso"], 8)
        banco = B.cargar_banco(BANCO)
        self.assertGreaterEqual(len(banco), 20)
        self.assertEqual(banco.paso, datos["paso"])

    def test_campos_de_video_no_incluyen_los_descartados(self):
        for campo in ("module_version", "proyecto"):
            self.assertNotIn(campo, V.campos_disponibles())
        self.assertIn("test_date", V.campos_disponibles())

    def test_videos_de_carpeta_encuentra_avi_y_mp4(self):
        carpeta = Path("/tmp/p15_carpeta")
        (carpeta / "PHOTOS").mkdir(parents=True, exist_ok=True)
        (carpeta / "PHOTOS" / "a.MP4").write_bytes(b"0")
        (carpeta / "foto.jpg").write_bytes(b"0")
        encontrados = [p.name for p in V.videos(carpeta)]
        self.assertEqual(encontrados, ["a.MP4"])

    def test_duda_de_video_cuando_el_acuerdo_es_bajo(self):
        propuestas = {"test_date": {"campo": "test_date", "valor": "2025-06-19", "estado": "dudoso",
                                    "acuerdo": 0.4, "votos": 1, "videos": 2}}
        dudas = V.a_dudas("252590", propuestas)
        self.assertEqual(len(dudas), 1)
        self.assertEqual(dudas[0]["motivo"], "video_barra_dudoso")

    @unittest.skipUnless(VIDEO.is_file() or VIDEO_ALTERNO.is_file(), "hace falta un vídeo de eDAG")
    def test_video_real_da_los_campos_del_ensayo(self):
        lectura = B.leer_video(RUTA_VIDEO, muestras=3, banco=B.cargar_banco(BANCO), lexico=V.LEXICO)
        campos = lectura["campos"]
        self.assertEqual(campos.get("test_number"), "252590")
        self.assertEqual(campos.get("test_place"), "EDAG MEX")
        self.assertEqual(campos.get("temperature_condition"), "RT")
        self.assertEqual(campos.get("delay_ms"), "0")


if __name__ == "__main__":
    unittest.main()


class PruebasCongruencia(unittest.TestCase):
    def _propuestas(self, numero="252590"):
        return {"test_number": {"campo": "test_number", "valor": numero, "estado": "propuesto",
                                "acuerdo": 1.0, "votos": 4, "videos": 4},
                "test_date": {"campo": "test_date", "valor": "2025-06-19", "estado": "propuesto",
                              "acuerdo": 1.0, "votos": 4, "videos": 4}}

    def test_numero_igual_al_caso_se_mantiene(self):
        propuestas = V.congruencia_con_caso(self._propuestas("252590"), "252590")
        self.assertEqual(propuestas["test_number"]["estado"], "propuesto")

    def test_video_de_otro_ensayo_pasa_a_conflicto(self):
        propuestas = V.congruencia_con_caso(self._propuestas("252590"), "222504")
        self.assertEqual(propuestas["test_number"]["estado"], "conflicto")
        dudas = V.a_dudas("222504", propuestas)
        motivos = {d["campo"]: d["motivo"] for d in dudas}
        self.assertEqual(motivos.get("test_number"), "video_no_coincide_con_caso")

    def test_caso_con_texto_alrededor_del_numero(self):
        propuestas = V.congruencia_con_caso(self._propuestas("252590"), "caso_252590")
        self.assertEqual(propuestas["test_number"]["estado"], "propuesto")
