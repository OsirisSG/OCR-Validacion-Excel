#!/usr/bin/env python3
"""P25 · la barra del vídeo se repara contra lo que ya sabemos del caso.

El banco de glifos confunde parecidos: `22250A` por `222504`, `0A JDN 25` por `04 JUN 25`. Como el
número de la carpeta y los doce meses son conjuntos cerrados, se reparan en vez de descartar la lectura.

Se comprueba:
1. `A`→4, `S`→5, `B`→8… en números y en días;
2. un mes mal leído se reconoce (`JDN` → `JUN`, `MAf` → `MAY`/`MAR`);
3. cuando dos meses encajan, decide la **semana del número de la carpeta**;
4. `NOM` (tipo de generador) nunca se toma por un mes;
5. el número de la barra **no se inventa**: si no coincide exacto con la carpeta, no se da por leído.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utilidades import barra_estado as B

BARRA_RT = "VW316/5 252590 RdW RT NOM 0ms EDAG Mex BMG 19 JUN 25 Rec5000 fps"
BARRA_NT = "9TM815x5 22250A R5MM NT NOM 0ms EDAG Mex BMG 28 MAf 25 Rec5000 fps"
BARRA_HT = "9TM815x5 282550 RJMM NT NOM 0ms EDAG Mex 0A JDN 25 Rec5000 fps"


class TestReparaciones:
    def test_numero_con_letra(self):
        assert B.reparar_numero("22250A") == "222504"

    def test_numero_de_verdad_no_se_toca(self):
        assert B.reparar_numero("252590") == "252590"

    def test_token_con_pocos_digitos_no_es_numero(self):
        assert B.reparar_numero("R5MM") == ""

    def test_dia_con_letra(self):
        assert B.reparar_dia("0A") == "04"

    def test_dia_imposible(self):
        assert B.reparar_dia("99") == ""

    def test_mes_mal_leido(self):
        # `JDN` está a una letra de JUN y de JAN: reparar_mes devuelve uno; la desambiguación la
        # hace el intérprete con la semana del número
        assert B.reparar_mes("JDN") in ("JUN", "JAN")

    def test_mes_exacto(self):
        assert B.reparar_mes("JUN") == "JUN"


class TestInterpretacionReparada:
    def test_barra_buena_no_cambia(self):
        datos = B.interpretar_barra_reparada(BARRA_RT, numero_esperado="252590")
        assert datos["test_date"] == "2025-06-19"
        assert datos["test_number"] == "252590"

    def test_numero_y_fecha_reparados(self):
        datos = B.interpretar_barra_reparada(BARRA_NT, numero_esperado="222504")
        assert datos["test_number"] == "222504"
        assert datos["test_date"] == "2025-05-28"

    def test_dia_reparado(self):
        datos = B.interpretar_barra_reparada(BARRA_HT, numero_esperado="232550")
        assert datos["test_date"] == "2025-06-04"

    def test_desempate_de_mes_por_semana(self):
        # `MAf` puede ser MAR o MAY: con la semana 22 gana MAY; con la 13, MAR
        mayo = B.interpretar_barra_reparada(BARRA_NT, numero_esperado="222504")
        marzo = B.interpretar_barra_reparada(BARRA_NT, numero_esperado="132504")
        assert mayo["test_date"] == "2025-05-28"
        assert marzo["test_date"] == "2025-03-28"

    def test_nom_no_es_un_mes(self):
        datos = B.interpretar_barra_reparada("252590 RdW RT NOM 0ms EDAG Mex NOM 19 JUN 25")
        assert datos.get("inflator_type") == "NOM"
        assert datos.get("test_date") == "2025-06-19"

    def test_numero_no_coincidente_no_se_da_por_leido(self):
        datos = B.interpretar_barra_reparada(BARRA_NT, numero_esperado="232550")
        assert datos["test_number"] == ""
        assert datos["numero_barra_leido"]

    def test_sin_numero_esperado_no_inventa(self):
        datos = B.interpretar_barra_reparada("RdW RT NOM 0ms EDAG Mex 19 JUN 25")
        assert datos["test_date"] == "2025-06-19"
        assert not datos.get("test_number")
