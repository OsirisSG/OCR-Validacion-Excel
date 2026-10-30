"""V15.9.7 · Ampliación de las correcciones CRIT-N13 y ALTA-N14.

N13: política segura ÚNICA de escritura para TODAS las celdas mapeadas
(declaradas y complementarias): fórmulas (incluidas referencias externas),
valores no textuales y celdas combinadas nunca se sobrescriben; el campo
queda intacto, se registra contradicción estructural con hoja/celda/motivo y
la publicación se bloquea (borrador oficial en los generadores). Plantillas
reales (empresarial y BMG) en copias temporales con hash verificado.

N14: etiqueta «Proyecto» DESNUDA (sin separador) en hojas visibles fuera de
``hojas_busqueda``: sólo se mapea con evidencia estructural segura (campo
único); las cabeceras tabulares de trazabilidad (≥3 celdas) no se tocan; la
estructura ambigua con datos ajenos debajo bloquea; hojas ocultas/exentas no
se examinan; cobertura ES/EN/DE y valores abreviados («A», «PRJ-001»).
"""
from __future__ import annotations

import pathlib
import sys

import pytest
from openpyxl import Workbook, load_workbook

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "pruebas"))

from test_plantilla_empresarial import _plantilla
from test_v15_9_6_ampliacion import _hash, _plantilla_publicable
from utilidades.identidad_excel import (
    aplicar_identidad_a_salida,
    nombre_visible,
)

IDENTIDAD_B = {"nombre_proyecto": "Proyecto B", "project_id": "proyecto-b",
               "origen": "declarado_usuario", "sin_asignar": False,
               "pendiente": False, "ejecucion_id": "ej-v1597"}


def _libro_base(titulo=None):
    """Resumen con par declarado editable (Proyecto: → Proyecto A)."""
    libro = Workbook()
    resumen = libro.active
    resumen.title = "Resumen"
    if titulo is not None:
        resumen["A1"] = titulo
    resumen["A2"] = "Proyecto:"
    resumen["B2"] = "Proyecto A"
    return libro


def _aplicar(libro, idioma="es", **extra):
    return aplicar_identidad_a_salida(
        libro, IDENTIDAD_B, hojas_busqueda=["Resumen"], hoja_resumen="Resumen",
        idioma=idioma, **extra)


# ---------------------------------------------------------------------------
# N13 · celdas declaradas: fórmulas, números y combinadas nunca se tocan
# ---------------------------------------------------------------------------


def test_n13_formula_con_referencias_externas_queda_intacta_y_bloquea():
    libro = _libro_base()
    datos = libro.create_sheet("Datos")
    datos["A1"] = "Proyecto A"
    resumen = libro["Resumen"]
    formula = '=CONCATENAR(Datos!A1," — revisado")'
    resumen["B2"] = formula
    meta = _aplicar(libro)
    assert resumen["B2"].value == formula
    assert resumen["B2"].data_type == "f"
    assert datos["A1"].value == "Proyecto A"          # referencia intacta
    assert meta["publicable"] is False
    assert meta["identidad_verificada"] is False
    bloqueo = [c for c in meta["contradicciones"]
               if c.get("estructural") and c.get("celda") == "B2"]
    assert bloqueo and bloqueo[0]["hoja"] == "Resumen"
    assert "fórmula" in bloqueo[0]["detalle"]


def test_n13_celda_no_validada_no_cuenta_como_identidad_pero_las_demas_sí():
    libro = _libro_base()
    resumen = libro["Resumen"]
    resumen["A3"] = "Project:"        # segundo par declarado, editable
    resumen["B3"] = "Old"
    resumen["B2"] = 2025              # numérico ⇒ no editable
    meta = _aplicar(libro)
    assert resumen["B2"].value == 2025
    assert resumen["B3"].value == "Proyecto B"   # el editable sí se mapea
    assert [c["celda_valor"] for c in meta["celdas"]] == ["B3"]
    assert meta["identidad_verificada"] is False
    assert meta["publicable"] is False
    assert any(c.get("estructural") and c["celda"] == "B2"
               for c in meta["contradicciones"])


def test_n13_combinada_inicial_declarada_bloquea_sin_excepcion():
    libro = _libro_base()
    resumen = libro["Resumen"]
    resumen["B2"] = "Proyecto A"
    resumen.merge_cells("B2:C2")      # B2 es la inicial del rango combinado
    meta = _aplicar(libro)
    assert resumen["B2"].value == "Proyecto A"   # intacta
    assert meta["publicable"] is False
    assert any(c.get("estructural") and "combinada" in c["detalle"]
               for c in meta["contradicciones"])


def test_n13_empresarial_real_con_formula_declarada_genera_borrador(tmp_path):
    """Generador empresarial: el bloqueo estructural se propaga a borrador."""
    from plantilla_empresarial import generar_desde_plantilla
    plantilla = _plantilla_publicable(tmp_path / "base_n13.xlsx")
    libro = load_workbook(plantilla)
    formula = '=CONCAT("Proyecto ","B")'
    libro["Captura_pruebas"]["B2"] = formula
    libro.save(plantilla)
    hash_plantilla = _hash(plantilla)
    oficial = tmp_path / "salida_n13.xlsx"
    resultado = pathlib.Path(generar_desde_plantilla(
        plantilla, oficial, [], identidad_proyecto=IDENTIDAD_B))
    assert not oficial.exists()
    assert "borrador_no_publicable" in resultado.name
    borrador = load_workbook(resultado)
    assert borrador["Captura_pruebas"]["B2"].value == formula  # intacta
    assert borrador["Captura_pruebas"]["B2"].data_type == "f"
    assert _hash(plantilla) == hash_plantilla     # plantilla original intacta


def test_n13_bmg_real_con_formula_complementaria_genera_borrador(tmp_path):
    """BMG auténtico en copia temporal: fórmula en par complementario."""
    from reporte_bmg import generar_reporte_bmg
    from configuracion import cargar_config, cargar_reglas
    from test_reporte_bmg_v7 import caso
    real = RAIZ / "plantillas" / "reporte_bmg_1st_2st.xlsx"
    hash_real = _hash(real)
    copia = tmp_path / "bmg_n13.xlsx"
    copia.write_bytes(real.read_bytes())
    libro = load_workbook(copia)
    formula = '=CONCAT("Projekt ","B")'
    libro["Rangos"]["A1"] = "Projekt:"
    libro["Rangos"]["B1"] = formula
    libro["Übersicht Standversuche"]["Z1"] = "Bericht Projekt B — Stufe 1ST"
    libro.save(copia)
    oficial = tmp_path / "bmg_oficial.xlsx"
    resultados = [caso(1001, "1ST", "HT", "UGL", 5.8)]
    salida = pathlib.Path(generar_reporte_bmg(
        copia, oficial, resultados, cargar_config(), cargar_reglas(),
        idioma="de", identidad_proyecto=IDENTIDAD_B))
    assert not oficial.exists()
    assert "borrador_no_publicable" in salida.name
    borrador = load_workbook(salida)
    assert borrador["Rangos"]["B1"].value == formula   # fórmula intacta
    assert borrador["Rangos"]["B1"].data_type == "f"
    assert borrador["Rangos"]["A1"].value == "Projekt:"
    assert _hash(real) == hash_real                    # plantilla repo intacta


# ---------------------------------------------------------------------------
# N14 · etiquetas desnudas: campo único sí, cabecera/ambigüedad no
# ---------------------------------------------------------------------------


def test_n14_pares_desnudos_abreviados_en_varias_hojas_se_mapean():
    """V15.9.10 (CRIT-N17) SUPERSEDE: un par desnudo cuyo contiguo no tiene
    evidencia POSITIVA de ser nombre de proyecto («A», «PRJ-001»: ni tabla
    registrada, ni cabecera reconocible, ni mención, ni coincidencia con la
    identidad) ya NO se sobrescribe por suposición: fail-closed, se bloquea
    la publicación señalando hoja/celda. La garantía original de N14 (nunca
    publicar en silencio con un valor ajeno visible) se conserva reforzada:
    antes se corregía el valor, ahora además no se escribe nada sin
    evidencia. El par EXPLÍCITO declarado sigue mapeándose.
    """
    libro = _libro_base()
    ficha = libro.create_sheet("Ficha")
    ficha["A1"] = "Proyecto"          # desnuda, contiguo sin evidencia
    ficha["B1"] = "A"
    detalle = libro.create_sheet("Detalle")
    detalle["A1"] = "Project"         # EN desnuda, contiguo sin evidencia
    detalle["B1"] = "PRJ-001"
    meta = _aplicar(libro)
    assert ficha["B1"].value == "A"               # intacto (fail-closed)
    assert detalle["B1"].value == "PRJ-001"       # intacto (fail-closed)
    assert libro["Resumen"]["B2"].value == "Proyecto B"   # explícito sí
    assert meta["publicable"] is False
    bloqueos = {(c["hoja"], c["celda"]) for c in meta["contradicciones"]
                if c.get("estructural")}
    assert ("Ficha", "B1") in bloqueos
    assert ("Detalle", "B1") in bloqueos
    assert not [c for c in meta["celdas_complementarias"]
                if c["hoja"] in ("Ficha", "Detalle")]


def test_n14_cabecera_tabular_desnuda_no_se_toca_y_publica():
    libro = _libro_base(titulo="Reporte del Proyecto B")
    traz = libro.create_sheet("Trazabilidad")
    traz["A1"], traz["B1"], traz["C1"], traz["D1"] = \
        "Proyecto", "Etapa", "Caso", "Valor"
    traz["A2"], traz["B2"], traz["C2"], traz["D2"] = "Proyecto B", "1ST", 1001, 5.8
    meta = _aplicar(libro)
    assert (traz["A1"].value, traz["B1"].value, traz["C1"].value) \
        == ("Proyecto", "Etapa", "Caso")          # cabeceras intactas
    assert (traz["A2"].value, traz["C2"].value, traz["D2"].value) \
        == ("Proyecto B", 1001, 5.8)              # datos intactos
    assert meta["publicable"] is True
    assert not [c for c in meta["celdas_complementarias"]
                if c["hoja"] == "Trazabilidad"]


def test_n14_estructura_ambigua_con_datos_ajenos_bloquea_sin_reemplazar():
    libro = _libro_base(titulo="Reporte del Proyecto B")
    hoja = libro.create_sheet("Indicadores")
    hoja["A1"], hoja["B1"] = "Proyecto", "A"
    hoja["A2"], hoja["B2"] = "Proyecto A", "1ST"   # datos históricos ajenos
    meta = _aplicar(libro)
    assert hoja["B1"].value == "A"                 # nada reemplazado
    assert hoja["A2"].value == "Proyecto A"
    assert meta["publicable"] is False
    bloqueos = [c for c in meta["contradicciones"] if c.get("estructural")]
    assert bloqueos and bloqueos[0]["hoja"] == "Indicadores"


def test_n14_tabla_dos_columnas_cabecera_reconocible_coherente_no_se_toca():
    libro = _libro_base(titulo="Reporte del Proyecto B")
    hoja = libro.create_sheet("Etapas")
    hoja["A1"], hoja["B1"] = "Proyecto", "Etapa"   # cabecera de 2 columnas
    hoja["A2"], hoja["B2"] = "Proyecto B", "1ST"   # columna coherente
    meta = _aplicar(libro)
    assert (hoja["A1"].value, hoja["B1"].value) == ("Proyecto", "Etapa")
    assert (hoja["A2"].value, hoja["B2"].value) == ("Proyecto B", "1ST")
    assert meta["publicable"] is True
    assert not [c for c in meta["celdas_complementarias"]
                if c["hoja"] == "Etapas"]


def test_n14_hojas_ocultas_y_exentas_no_se_examinan():
    libro = _libro_base(titulo="Reporte del Proyecto B")
    oculta = libro.create_sheet("Oculto")
    oculta["A1"], oculta["B1"] = "Proyecto", "Proyecto A"
    oculta.sheet_state = "hidden"
    historico = libro.create_sheet("Historico")
    historico["A1"], historico["B1"] = "Proyecto", "Proyecto A"
    meta = _aplicar(libro, hojas_exentas=["Historico"])
    assert oculta["B1"].value == "Proyecto A"      # oculta: intacta
    assert historico["B1"].value == "Proyecto A"   # exenta declarada: intacta
    assert "Oculto" not in meta["hojas_examinadas"]
    assert "Historico" not in meta["hojas_examinadas"]
    assert meta["publicable"] is True


def test_n14_campo_desnudo_con_formula_o_combinada_bloquea_intacto():
    # (a) fórmula en el valor del campo único desnudo
    libro = _libro_base(titulo="Reporte del Proyecto B")
    hoja = libro.create_sheet("Ficha")
    hoja["A1"], hoja["B1"] = "Proyecto", '=CONCAT("A","B")'
    meta = _aplicar(libro)
    assert hoja["B1"].value == '=CONCAT("A","B")'
    assert hoja["B1"].data_type == "f"
    assert meta["publicable"] is False
    # (b) celda combinada como destino del campo único desnudo
    libro2 = _libro_base(titulo="Reporte del Proyecto B")
    hoja2 = libro2.create_sheet("Ficha")
    hoja2["A1"] = "Proyecto"
    hoja2.merge_cells("B1:C1")
    meta2 = _aplicar(libro2)                       # sin excepción de bajo nivel
    assert meta2["publicable"] is False
    assert any("combinada" in c["detalle"]
               for c in meta2["contradicciones"] if c.get("estructural"))


@pytest.mark.parametrize("idioma,etiqueta", [
    ("es", "Proyecto"), ("en", "Project"), ("de", "Projekt"),
])
def test_n14_campo_desnudo_en_tres_idiomas_se_mapea(idioma, etiqueta):
    """V15.9.10 (CRIT-N17) SUPERSEDE: el contiguo «Old» no tiene evidencia
    positiva de ser nombre de proyecto (no empieza por mención ni coincide
    con la identidad): el par desnudo se trata fail-closed y bloquea, en los
    tres idiomas. La cobertura POSITIVA de los tres idiomas se conserva en
    ``test_n14_campo_explicito_en_tres_idiomas_se_mapea`` (V15.9.10) y en el
    control de campo único con mención («Proyecto | Proyecto A»).
    """
    libro = _libro_base(titulo=None)
    hoja = libro.create_sheet("Ficha")
    hoja["A1"], hoja["B1"] = etiqueta, "Old"
    meta = _aplicar(libro, idioma=idioma)
    assert hoja["B1"].value == "Old"            # intacto (fail-closed)
    assert meta["publicable"] is False, idioma
    assert any(c.get("estructural") and c["hoja"] == "Ficha"
               for c in meta["contradicciones"]), idioma


def test_n14_migracion_a_b_incluido_campo_historico_desnudo():
    """Plantilla del proyecto A → usuario declara B: campos y par desnudo."""
    libro = _libro_base(titulo="Reporte del Proyecto A")
    hoja = libro.create_sheet("Indicadores")
    hoja["A1"], hoja["B1"] = "Proyecto", "Proyecto A"
    meta = _aplicar(libro)
    assert libro["Resumen"]["B2"].value == "Proyecto B"
    assert hoja["B1"].value == "Proyecto B"        # migración del campo único
    # El título histórico NO se reemplaza: contradicción visible registrada.
    assert libro["Resumen"]["A1"].value == "Reporte del Proyecto A"
    assert meta["publicable"] is False
