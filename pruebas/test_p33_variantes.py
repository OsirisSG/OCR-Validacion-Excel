"""Pruebas de variantes (P33): ¿siguen funcionando las reglas si el dato es otro?

El usuario preguntó por dos campos concretos: **motivo de prueba** (`test_reason`) y **número de
parte del PAB** (`module_part_number`). La respuesta tiene que ser sí, y la prueba es esta batería:
las variantes reales se aceptan (y se normalizan), la basura se sigue rechazando.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utilidades.protocolo_campos import evaluar, normalizar_por_campo  # noqa: E402


class TestVariantesMotivoDePrueba:
    """El motivo lo escribe a mano quien monta la prueba: no hay catálogo cerrado."""

    @pytest.mark.parametrize("leido,esperado", [
        ("BMG", "BMG"),
        ("BMX", "BMX"),
        ("bmg", "BMG"),
        ("BMG (NOM)", "BMG (NOM)"),
        ("Certificación NOM", "CERTIFICACION NOM"),
        ("PRUEBA BMG RT", "PRUEBA BMG RT"),
        ("BMG/A", "BMG/A"),
        ("BMG-A", "BMG-A"),
        ("BMG 2", "BMG 2"),
    ])
    def test_acepta_variantes(self, leido, esperado):
        veredicto = evaluar("test_reason", leido)
        assert veredicto.escribible, veredicto.motivo
        assert veredicto.valor == esperado

    @pytest.mark.parametrize("basura", ["BMG_1", "-35°C \"BMG\"", "X" * 45, "A", ""])
    def test_rechaza_lo_que_no_es_un_motivo(self, basura):
        assert not evaluar("test_reason", basura).escribible


class TestVariantesNumeroDePartePAB:
    """El número de parte es estructural: cambia el prefijo y el sufijo, no la forma."""

    @pytest.mark.parametrize("leido,esperado", [
        ("2GJ.880.204.J", "2GJ.880.204.J"),      # el del proyecto
        ("2gj 880 204 j", "2GJ.880.204.J"),      # como lo imprime la etiqueta (espacios)
        ("2GJ880204J", "2GJ.880.204.J"),         # todo seguido
        ("2GJ.880.204.AB", "2GJ.880.204.AB"),    # variante de dos caracteres
        ("4M0.880.204.AG", "4M0.880.204.AG"),    # otro prefijo y otra variante
        ("1EA.880.204.AB", "1EA.880.204.AB"),    # otro proyecto
        ("2GJ.880.204.0", "2GJ.880.204.0"),      # sufijo que es un cero
    ])
    def test_acepta_variantes(self, leido, esperado):
        veredicto = evaluar("module_part_number", leido)
        assert veredicto.escribible, veredicto.motivo
        assert veredicto.valor == esperado

    @pytest.mark.parametrize("basura", ["2GJ.880.204", "2GJ.880.20", "880204J", "2GJ.880.204.JJJ"])
    def test_rechaza_lo_que_no_es_un_numero_de_parte(self, basura):
        assert not evaluar("module_part_number", basura).escribible

    def test_el_del_tablero_admite_las_mismas_variantes(self):
        for leido in ("2GJ.857.003.G", "2GJ 857 003 G", "2GJ.857.003.AB", "5QF.857.003.AB"):
            assert evaluar("dashboard_part_number", leido).escribible, leido


class TestNormalizacion:
    def test_los_puntos_se_reconstruyen(self):
        assert normalizar_por_campo("module_part_number", "2GJ 880 204 AB") == "2GJ.880.204.AB"
        assert normalizar_por_campo("dashboard_part_number", "2GJ857003G") == "2GJ.857.003.G"

    def test_lo_que_no_encaja_se_deja_como_vino(self):
        assert normalizar_por_campo("module_part_number", "sin numero") == "SIN NUMERO"

    def test_el_motivo_pierde_acentos_y_pasa_a_mayusculas(self):
        assert normalizar_por_campo("test_reason", "Prueba  de Humedad") == "PRUEBA DE HUMEDAD"
