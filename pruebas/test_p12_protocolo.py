"""Pruebas del protocolo de campos y de las constantes confirmadas (P12)."""
from __future__ import annotations

import pytest

from utilidades import constantes_aprendidas as ca
from utilidades.protocolo_campos import (aprender_lexico, coherencia, evaluar, elegir_mejor,
                                         normalizar_fecha, perfil_proyecto)
from collections import Counter

LEXICO = {"parte": {"2GJ.880.204.J"}, "serie": set(), "nivel": {"02S", "03S"},
          "test_number": {"222504", "232550"}, "inflator_type": {"NOM", "OGL", "UGL"}}
PERFIL = {"serie": "671 ZRZ"}


def test_numero_de_parte_valido():
    v = evaluar("module_part_number", "2GJ.880.204.J", LEXICO)
    assert v.estado == "valido" and v.escribible


def test_numero_de_parte_recupera_el_caracter_que_falta():
    v = evaluar("module_part_number", "GJ.880.204.J", LEXICO)
    assert v.estado == "reparado" and v.valor == "2GJ.880.204.J" and v.escribible


def test_numero_de_parte_confusion_6_por_G():
    # el 6 se confunde con la G: con el léxico del proyecto, la lectura se corrige sola
    v = evaluar("module_part_number", "26J.880.204.J", LEXICO)
    assert v.estado == "reparado" and v.valor == "2GJ.880.204.J" and v.escribible


def test_numero_de_parte_basura():
    v = evaluar("module_part_number", "880.204", LEXICO)
    assert v.estado == "invalido" and not v.escribible


def test_serie_valida_por_estructura_y_prefijo():
    v = evaluar("module_serial_number", "671 ZRZ0539991D", LEXICO, 3, 4, None, PERFIL)
    assert v.estado == "valido" and v.escribible


def test_serie_con_O_por_0():
    v = evaluar("module_serial_number", "671 ZRZO539999L", LEXICO, 3, 4, None, PERFIL)
    assert v.estado == "reparado" and v.valor == "671 ZRZ0539999L"


def test_serie_basura_no_pasa():
    for basura in ("XZ JUEAZNOD", "DJABUEP", "I 0"):
        assert evaluar("module_serial_number", basura, LEXICO, 1, 1, None, PERFIL).estado == "invalido"


def test_serie_de_otro_proyecto_queda_dudosa():
    v = evaluar("module_serial_number", "999 ABC1234567X", LEXICO, 1, 1, None, PERFIL)
    assert v.estado == "dudoso" and "999 ABC" in v.motivo


def test_nivel_fuera_del_catalogo_es_dudoso():
    assert evaluar("engineering_level", "02S", LEXICO).estado == "valido"
    assert evaluar("engineering_level", "88X", LEXICO).estado == "dudoso"
    assert evaluar("engineering_level", "O2S", LEXICO).valor == "02S"


def test_numero_de_prueba():
    assert evaluar("test_number", "232550", LEXICO).estado == "valido"
    assert evaluar("test_number", "142025", LEXICO).estado == "dudoso"
    assert evaluar("test_number", "042025", LEXICO).estado == "invalido"


def test_fechas_de_etiqueta():
    assert normalizar_fecha("10.04.25") == "2025-04-10"
    assert normalizar_fecha("11/04/2025") == "2025-04-11"
    assert normalizar_fecha("2025-04-10") == "2025-04-10"
    assert normalizar_fecha("61-90-92") is None
    assert normalizar_fecha("12.38.17") is None


def test_semana_coherente_con_la_fecha():
    malo = coherencia("week", "2025-W02", {"test_date": "2025-04-10"})
    assert malo is not None and malo.estado == "invalido"
    assert coherencia("week", "2025-W15", {"test_date": "2025-04-10"}) is None


def test_lexico_no_aprende_basura():
    votos = {"module_part_number": Counter({"2GJ.880.204.J": 13, "26J.880.204.J": 2,
                                            "GJ.880.204.J": 2, "basura!!!": 1})}
    lexico = aprender_lexico(votos)
    assert lexico["parte"] == {"2GJ.880.204.J"}
    assert perfil_proyecto({"module_serial_number": Counter({"671 ZRZ0539991D": 4,
                                                             "671 ZRZ0539973D": 2})})["serie"] == "671 ZRZ"


def test_eleccion_entre_lecturas():
    votos = Counter({"2GJ.880.204.J": 5, "26J.880.204.J": 2, "ruido": 1})
    mejor = elegir_mejor("module_part_number", votos, LEXICO)
    assert mejor.valor == "2GJ.880.204.J" and mejor.escribible


def test_constante_rechaza_valor_invalido(tmp_path):
    with pytest.raises(ValueError):
        ca.confirmar("test_number", "042025", base=tmp_path)


def test_constante_se_guarda_y_se_revoca(tmp_path):
    ca.confirmar("test_place", "DACHAU", autor="prueba", base=tmp_path)
    assert ca.cargar(tmp_path)["constantes"]["test_place"]["valor"] == "DACHAU"
    assert ca.revocar("test_place", base=tmp_path) is True
    assert "test_place" not in ca.cargar(tmp_path)["constantes"]


class HojaFalsa:
    def __init__(self, celdas):
        self.celdas = celdas
        self.max_row = max(f for f, _ in celdas)
    def cell(self, fila, columna):
        class C:
            def __init__(self, v): self.value = v
        return C(self.celdas.get((fila, columna)))


def test_constante_no_sobrescribe_y_respeta_excepciones(tmp_path):
    ca.confirmar("test_place", "DACHAU", base=tmp_path)
    hoja = HojaFalsa({(8, 3): "222504", (8, 5): None, (9, 3): "222509", (9, 5): "INGOLSTADT",
                      (10, 3): "222521", (10, 5): None})
    resultado = ca.aplicar(hoja, {"test_number": 3, "test_place": 5}, base=tmp_path)
    assert {e["caso"] for e in resultado["escritas"]} == {"222504", "222521"}
    assert resultado["excepciones"][0]["caso"] == "222509"
    assert hoja.cell(9, 5).value == "INGOLSTADT"      # no se tocó
