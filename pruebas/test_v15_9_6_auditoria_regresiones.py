"""Pruebas independientes N10–N12: solo usan Excel en memoria y datos sintéticos."""
import pytest
from openpyxl import Workbook
from utilidades.identidad_excel import aplicar_identidad_a_salida

IDENTIDAD_B = {"nombre_proyecto":"Proyecto B", "project_id":"proyecto-b", "origen":"declarado_usuario", "sin_asignar":False}


def _plantilla_extra():
    wb = Workbook()
    wb.active.title = "Resumen"
    wb["Resumen"]["A2"] = "Proyecto:"
    wb["Resumen"]["B2"] = "Proyecto A"
    return wb


def test_n10_hoja_adicional_con_etiqueta_y_valor_historico_debe_bloquearse():
    """N7 ampliado: 'Proyecto:' y nombre 'A' separado en celdas de otra hoja."""
    wb = _plantilla_extra()
    hoja = wb.create_sheet("Indicadores")
    hoja["A1"] = "Proyecto:"
    hoja["B1"] = "A"
    meta = aplicar_identidad_a_salida(wb, IDENTIDAD_B, hojas_busqueda=["Resumen"], hoja_resumen="Resumen")
    assert meta["publicable"] is False or hoja["B1"].value == "Proyecto B", (
        "No puede publicarse un Excel con Proyecto B en Resumen y A como proyecto visible en Indicadores"
    )


def test_n11_titulo_que_solo_coincide_parcialmente_con_nombre_compuesto_no_debe_validarse():
    """N8 ampliado: compartir una palabra no demuestra identidad completa del proyecto."""
    wb = _plantilla_extra()
    wb["Resumen"]["A1"] = "Reporte del Proyecto Beta"
    actual = dict(IDENTIDAD_B, nombre_proyecto="Proyecto Beta Sur", project_id="proyecto-beta-sur")
    meta = aplicar_identidad_a_salida(wb, actual, hojas_busqueda=["Resumen"], hoja_resumen="Resumen")
    assert meta["publicable"] is False, "'Proyecto Beta' no identifica a 'Proyecto Beta Sur'"


@pytest.mark.parametrize("nombre", ["Reporte del Proyecto B — Etapa 1ST", "Reporte del Proyecto B — Etapa 2ST", "Reporte del Proyecto B — Fase NACH"])
def test_n12_titulo_valido_con_etapa_o_fase_del_proyecto_no_debe_bloquearse(nombre):
    """N8 ampliado: etapas 1ST/2ST y fase NACH son etiquetas técnicas, no otros proyectos."""
    wb = _plantilla_extra()
    wb["Resumen"]["A1"] = nombre
    meta = aplicar_identidad_a_salida(wb, IDENTIDAD_B, hojas_busqueda=["Resumen"], hoja_resumen="Resumen")
    assert meta["publicable"] is True, f"No debió bloquear la etapa/fase en {nombre}: {meta['contradicciones']}"
