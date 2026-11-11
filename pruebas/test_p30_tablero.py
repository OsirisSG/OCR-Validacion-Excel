#!/usr/bin/env python3
"""P30 · Las columnas del tablero: número de parte, serie, fecha y nivel.

Lo que pidió el usuario, tal cual:

1. El **número de tablero** va grabado en el plástico y «termina en una letra o número más grande»;
   se toma **la parte inferior del código**.
2. La **serie del tablero** sale de una etiqueta con QR «que se parece al PAB pero no es igual»:
   de los códigos se toma **el más largo**.
3. La **fecha del tablero** está en **otro tipo de etiqueta**, también con código, que lleva además
   una **pegatina de color** (y escribe el mes con letras: `17/MAY/2025`).
4. El **nivel de ingeniería** va en una **estampa**, en la sintaxis `##S`, sin descartar `##K`.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evidencia_tablero import consensuar
from utilidades.protocolo_campos import evaluar
from utilidades.tablero_campos import (_es_codigo_de_resina, _parece_numero_de_parte,
                                      _sintaxis_del_nivel, interpretar_fecha_de_tablero,
                                      interpretar_parte_grabada, interpretar_serie_tablero,
                                      leer_serie_de_etiqueta)


class NumeroDeParteGrabado(unittest.TestCase):
    """Punto 1: la banda de abajo y el remate en caja aparte."""

    def test_parte_con_espacios_y_puntos(self):
        self.assertEqual(interpretar_parte_grabada("2GJ.857.003.G"), "2GJ.857.003.G")
        self.assertEqual(interpretar_parte_grabada("2GJ857 003 G"), "2GJ.857.003.G")
        self.assertEqual(interpretar_parte_grabada("2 GJ 857 003 (G)"), "2GJ.857.003.G")

    def test_el_numero_de_molde_no_es_el_de_parte(self):
        # la banda de arriba es el molde (`4148399X`): no tiene la forma del número de parte
        self.assertIsNone(interpretar_parte_grabada("4148399X"))
        self.assertIsNone(interpretar_parte_grabada(""))


class SerieDelTablero(unittest.TestCase):
    """Punto 2: de los códigos de la etiqueta, el más largo; y el del PAB no se cuela."""

    def test_la_serie_lleva_el_espacio_del_libro(self):
        self.assertEqual(interpretar_serie_tablero("*0523KVJ008R6E")["valor"],
                         "052 3KVJ008R6E")
        self.assertEqual(interpretar_serie_tablero("*052 3KVJ008R6J6")["valor"],
                         "052 3KVJ008R6J6")

    def test_se_queda_con_el_codigo_mas_largo(self):
        lineas = [("540548031", 0.9), ("*0523KVJ008R6E", 0.8)]
        elegido = leer_serie_de_etiqueta(lineas)
        self.assertEqual(elegido["valor"], "052 3KVJ008R6E")
        self.assertEqual(elegido["largo"], 13)

    def test_la_etiqueta_del_modulo_no_es_la_del_tablero(self):
        # `671 ZRZ0539983E` es la serie del PAB: se descarta antes de elegir
        self.assertEqual(leer_serie_de_etiqueta([("671 ZRZ0539983E", 0.9)]), {})


class FechaDelTablero(unittest.TestCase):
    """Punto 3: la etiqueta con mes en letra (y la del módulo, con puntos, no vale)."""

    def test_mes_en_letra(self):
        self.assertEqual(interpretar_fecha_de_tablero("17/MAY0/2025"), "2025-05-17")
        self.assertEqual(interpretar_fecha_de_tablero("17/MAY/2025"), "2025-05-17")

    def test_forma_numerica(self):
        self.assertEqual(interpretar_fecha_de_tablero("17/05/2025"), "2025-05-17")

    def test_una_fecha_imposible_se_rechaza(self):
        # `1911-05-25` es lo que sale cuando el OCR engancha dos trozos: no es una fecha
        self.assertIsNone(interpretar_fecha_de_tablero("1911-05-25"))


class NivelDelTablero(unittest.TestCase):
    """Punto 4: la estampa, en la sintaxis `##S` (o `##K`)."""

    def test_la_sintaxis_que_indicó_el_usuario(self):
        self.assertTrue(_sintaxis_del_nivel("03S"))
        self.assertTrue(_sintaxis_del_nivel("66K"))
        self.assertFalse(_sintaxis_del_nivel("0S3"))
        self.assertFalse(_sintaxis_del_nivel(""))


class ElPlasticoNoEsElNumeroDeParte(unittest.TestCase):
    """El plástico lleva marcas de material y de molde: no pueden colarse como número de parte."""

    def test_los_codigos_de_resina_se_descartan(self):
        self.assertTrue(_es_codigo_de_resina("PA66"))
        self.assertTrue(_es_codigo_de_resina(">PBT-GF30<"))
        self.assertFalse(_es_codigo_de_resina("2GJ.857.003.G"))

    def test_para_aceptar_el_catalogo_tiene_que_parecerse_de_verdad(self):
        # `94994408852400PA66` no se parece a la parte del tablero: no vale como identificación
        self.assertFalse(_parece_numero_de_parte("2GJ.857.003.G", ["94994408852400PA66"]))
        self.assertTrue(_parece_numero_de_parte("2GJ.857.003.G", ["2GJ857 00 G"]))


class ElProtocoloAceptaLaSerieDelTablero(unittest.TestCase):
    """El protocolo del libro tenía la forma del módulo; la del tablero es otra."""

    def test_las_series_del_lote_pasan_el_protocolo(self):
        for valor in ("052 3KVJ008R6E", "052 3KVJ008R6J6", "052 3KVJ008R52V"):
            self.assertTrue(evaluar("dashboard_serial_number", valor).escribible, valor)

    def test_la_serie_del_modulo_no_se_acepta_como_serie_del_tablero(self):
        self.assertFalse(evaluar("dashboard_serial_number", "671 ZRZ0539983E").escribible)


class ConsensoEntreFotos(unittest.TestCase):
    """La cola de la serie cambia entre fotos: decide el voto, y si no hay acuerdo queda en duda."""

    def test_gana_la_lectura_repetida(self):
        lecturas = [{"valor": "052 3KVJ008R6E", "confianza": 0.8},
                    {"valor": "052 3KVJ008R6E", "confianza": 0.7},
                    {"valor": "052 3KVJ008R6E7", "confianza": 0.9}]
        resultado = consensuar(lecturas)
        self.assertEqual(resultado["valor"], "052 3KVJ008R6E")
        self.assertFalse(resultado["dudoso"])

    def test_la_cola_se_decide_contando_todas_las_lecturas(self):
        # tres fotos dicen 13 caracteres y una añade un `1`: manda la mayoría
        lecturas = [{"valor": "052 3KVJ008R6E", "confianza": 0.8},
                    {"valor": "052 3KVJ008R6E", "confianza": 0.75},
                    {"valor": "052 3KVJ008R6E1", "confianza": 0.5}]
        self.assertEqual(consensuar(lecturas)["valor"], "052 3KVJ008R6E")

    def test_el_caracter_que_imprime_la_etiqueta_se_respeta(self):
        # aquí la mitad de las lecturas ven el `1` final: se escribe, pero queda en duda
        lecturas = [{"valor": "052 3KVJ008R6E1", "confianza": 0.86},
                    {"valor": "052 3KVJ008R6E7", "confianza": 0.85},
                    {"valor": "052 3KVJ008R6E1", "confianza": 0.9}]
        resultado = consensuar(lecturas)
        self.assertEqual(resultado["valor"], "052 3KVJ008R6E1")
        self.assertTrue(resultado["dudoso"])

    def test_una_sola_lectura_es_dudosa(self):
        self.assertTrue(consensuar([{"valor": "052 3KVJ008R6E", "confianza": 0.8}])["dudoso"])

    def test_sin_lecturas_no_hay_valor(self):
        self.assertEqual(consensuar([]), {})


if __name__ == "__main__":
    unittest.main()
