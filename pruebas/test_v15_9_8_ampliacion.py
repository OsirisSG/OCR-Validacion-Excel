"""V15.9.8 · Ampliación de la corrección CRIT-N15.

La ruta DECLARADA (`hojas_busqueda`) usa exactamente la misma política
estructural que la complementaria (`_clasificar_par`): una cabecera tabular
«Proyecto | Etapa [| Caso …]» nunca se mapea ni se sobrescribe; la
estructura ambigua con datos ajenos bloquea; el campo único desnudo y la
etiqueta explícita siguen actualizándose. Cobertura exigida por
`CORRECCIONES_OBLIGATORIAS_V_MATRIX_V15_9_8.md`: hoja declarada de dos
columnas, de tres o más, par explícito, campo único desnudo, hojas
ocultas/exentas, ES/EN/DE, propagación a borrador en empresarial y BMG
reales (copias temporales con hash de plantilla), celdas y formatos
verificados antes/después releyendo el Excel temporal.
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
from utilidades.identidad_excel import aplicar_identidad_a_salida

IDENTIDAD_B = {"nombre_proyecto": "Proyecto B", "project_id": "proyecto-b",
               "origen": "declarado_usuario", "sin_asignar": False,
               "pendiente": False, "ejecucion_id": "ej-v1598"}


def _libro_base():
    libro = Workbook()
    libro.active.title = "Resumen"
    return libro


def _aplicar(libro, idioma="es", **extra):
    return aplicar_identidad_a_salida(
        libro, IDENTIDAD_B, hojas_busqueda=["Resumen"], hoja_resumen="Resumen",
        idioma=idioma, **extra)


# ---------------------------------------------------------------------------
# Hoja declarada: cabeceras tabulares intactas, sin celdas mapeadas
# ---------------------------------------------------------------------------


def test_n15_cabecera_dos_columnas_declarada_no_verifica_y_no_publica():
    libro = _libro_base()
    resumen = libro["Resumen"]
    resumen["A2"], resumen["B2"] = "Proyecto", "Etapa"
    resumen["A3"], resumen["B3"] = "Proyecto B", "1ST"
    meta = _aplicar(libro)
    assert (resumen["A2"].value, resumen["B2"].value) == ("Proyecto", "Etapa")
    assert (resumen["A3"].value, resumen["B3"].value) == ("Proyecto B", "1ST")
    assert meta["celdas"] == []
    assert meta["identidad_verificada"] is False
    assert meta["publicable"] is False          # sin campo verificable (P08)
    assert meta["estado_identidad"] == "no_verificada"
    # Cabecera reconocible y columna coherente: no hay contradicción falsa.
    assert not [c for c in meta["contradicciones"] if c.get("estructural")]


def test_n15_cabecera_tres_columnas_declarada_datos_y_formato_intactos(tmp_path):
    libro = _libro_base()
    resumen = libro["Resumen"]
    resumen["A1"], resumen["B1"], resumen["C1"] = "Proyecto", "Etapa", "Caso"
    resumen["A2"], resumen["B2"], resumen["C2"] = "Proyecto B", "2ST", 1001
    temporal = tmp_path / "n15_3col.xlsx"
    libro.save(temporal)
    releido = load_workbook(temporal)           # releer el Excel temporal
    meta = _aplicar(releido)
    hoja = releido["Resumen"]
    assert [hoja[c].value for c in ("A1", "B1", "C1")] \
        == ["Proyecto", "Etapa", "Caso"]
    assert [hoja[c].value for c in ("A2", "B2", "C2")] \
        == ["Proyecto B", "2ST", 1001]
    assert hoja["C2"].data_type == "n"          # número intacto
    assert meta["celdas"] == []
    assert meta["publicable"] is False


def test_n15_ambigua_declarada_con_historicos_bloquea_sin_reemplazar():
    libro = _libro_base()
    resumen = libro["Resumen"]
    resumen["A1"], resumen["B1"] = "Proyecto", "Etapa"
    resumen["A2"], resumen["B2"] = "Proyecto A", "1ST"   # histórico ajeno
    meta = _aplicar(libro)
    assert (resumen["A2"].value, resumen["B2"].value) == ("Proyecto A", "1ST")
    assert resumen["B1"].value == "Etapa"
    assert meta["celdas"] == []
    assert meta["publicable"] is False
    bloqueos = [c for c in meta["contradicciones"] if c.get("estructural")]
    assert bloqueos and bloqueos[0]["hoja"] == "Resumen"
    assert "revisión requerida" in bloqueos[0]["detalle"]


def test_n15_cabecera_declarada_con_campo_explicito_valido_publica():
    """Cabecera tabular en fila 1 + par explícito editable ⇒ publicable."""
    libro = _libro_base()
    resumen = libro["Resumen"]
    resumen["A1"], resumen["B1"] = "Proyecto", "Etapa"
    resumen["A2"], resumen["B2"] = "Proyecto B", "1ST"   # registro coherente
    resumen["A4"], resumen["B4"] = "Proyecto:", "Proyecto A"
    meta = _aplicar(libro)
    assert (resumen["A1"].value, resumen["B1"].value) == ("Proyecto", "Etapa")
    assert (resumen["A2"].value, resumen["B2"].value) == ("Proyecto B", "1ST")
    assert resumen["B4"].value == "Proyecto B"           # campo válido mapeado
    assert [c["celda_valor"] for c in meta["celdas"]] == ["B4"]
    assert meta["publicable"] is True
    assert meta["identidad_verificada"] is True


def test_n15_fila_tabular_con_etiqueta_explicita_declarada_bloquea():
    """Política única: explícita en fila tabular con valor ajeno ⇒ bloqueo."""
    libro = _libro_base()
    resumen = libro["Resumen"]
    resumen["A2"], resumen["B2"], resumen["C2"] = "Proyecto:", "Otro", "x"
    meta = _aplicar(libro)
    assert (resumen["B2"].value, resumen["C2"].value) == ("Otro", "x")
    assert meta["celdas"] == []
    assert meta["publicable"] is False
    assert any(c.get("estructural") and "fila tabular" in c["detalle"]
               for c in meta["contradicciones"])


@pytest.mark.parametrize("idioma,etiquetas", [
    ("es", ("Proyecto", "Etapa", "Caso")),
    ("en", ("Project", "Stage", "Case")),
    ("de", ("Projekt", "Stufe", "Fall")),
])
def test_n15_cabeceras_declaradas_tres_idiomas_intactas(idioma, etiquetas):
    libro = _libro_base()
    resumen = libro["Resumen"]
    resumen["A1"], resumen["B1"], resumen["C1"] = etiquetas
    meta = _aplicar(libro, idioma=idioma)
    assert (resumen["A1"].value, resumen["B1"].value, resumen["C1"].value) \
        == etiquetas, idioma
    assert meta["celdas"] == []


def test_n15_ocultas_y_exentas_con_cabeceras_no_se_examinan():
    libro = _libro_base()
    libro["Resumen"]["A2"], libro["Resumen"]["B2"] = "Proyecto:", "Proyecto A"
    oculta = libro.create_sheet("Oculto")
    oculta["A1"], oculta["B1"] = "Proyecto", "Proyecto A"
    oculta["A2"], oculta["B2"] = "Proyecto A", "1ST"
    oculta.sheet_state = "hidden"
    historico = libro.create_sheet("Historico")
    historico["A1"], historico["B1"] = "Proyecto", "Proyecto A"
    historico["A2"], historico["B2"] = "Proyecto A", "1ST"
    meta = _aplicar(libro, hojas_exentas=["Historico"])
    assert oculta["B1"].value == "Proyecto A"        # intacta
    assert historico["A2"].value == "Proyecto A"     # intacta
    assert libro["Resumen"]["B2"].value == "Proyecto B"
    assert meta["publicable"] is True


# ---------------------------------------------------------------------------
# Propagación a los generadores reales (empresarial y BMG) en copias
# ---------------------------------------------------------------------------


def test_n15_empresarial_cabecera_declarada_genera_borrador_intacto(tmp_path):
    from plantilla_empresarial import generar_desde_plantilla
    plantilla = tmp_path / "base_n15.xlsx"
    _plantilla(plantilla)
    libro = load_workbook(plantilla)
    captura = libro["Captura_pruebas"]
    captura["A1"], captura["B1"], captura["C1"] = "Proyecto", "Etapa", "Caso"
    captura["A2"], captura["B2"], captura["C2"] = "Proyecto B", "1ST", 1001
    libro.save(plantilla)
    hash_plantilla = _hash(plantilla)
    oficial = tmp_path / "salida_n15.xlsx"
    resultado = pathlib.Path(generar_desde_plantilla(
        plantilla, oficial, [], identidad_proyecto=IDENTIDAD_B))
    assert not oficial.exists()
    assert "borrador_no_publicable" in resultado.name
    borrador = load_workbook(resultado)
    assert [borrador["Captura_pruebas"][c].value for c in
            ("A1", "B1", "C1")] == ["Proyecto", "Etapa", "Caso"]
    assert [borrador["Captura_pruebas"][c].value for c in
            ("A2", "B2", "C2")] == ["Proyecto B", "1ST", 1001]
    assert _hash(plantilla) == hash_plantilla    # plantilla original intacta


def test_n15_empresarial_cabecera_mas_campo_explicito_publica(tmp_path):
    from plantilla_empresarial import generar_desde_plantilla
    plantilla = _plantilla_publicable(tmp_path / "base_n15b.xlsx")
    libro = load_workbook(plantilla)
    extra = libro.create_sheet("Trazabilidad")
    extra["A1"], extra["B1"], extra["C1"] = "Proyecto", "Etapa", "Caso"
    extra["A2"], extra["B2"], extra["C2"] = "Proyecto B", "1ST", 1001
    libro.save(plantilla)
    hash_plantilla = _hash(plantilla)
    oficial = tmp_path / "salida_n15b.xlsx"
    resultado = pathlib.Path(generar_desde_plantilla(
        plantilla, oficial, [], identidad_proyecto=IDENTIDAD_B))
    assert resultado == oficial and oficial.is_file()
    salida = load_workbook(oficial)
    assert [salida["Trazabilidad"][c].value for c in
            ("A1", "B1", "C1")] == ["Proyecto", "Etapa", "Caso"]
    assert salida["Captura_pruebas"]["B2"].value == "Proyecto B"
    assert _hash(plantilla) == hash_plantilla


def test_n15_bmg_cabecera_tabular_coherente_publica_con_proyecto_explicito(tmp_path):
    from reporte_bmg import generar_reporte_bmg
    from configuracion import cargar_config, cargar_reglas
    from test_reporte_bmg_v7 import caso
    real = RAIZ / "plantillas" / "reporte_bmg_1st_2st.xlsx"
    hash_real = _hash(real)
    copia = tmp_path / "bmg_n15.xlsx"
    copia.write_bytes(real.read_bytes())
    libro = load_workbook(copia)
    # Cabecera tabular desnuda en la hoja DECLARADA del generador BMG.
    resumen = libro["Übersicht Standversuche"]
    resumen["A1"], resumen["B1"], resumen["C1"] = "Projekt", "Stufe", "Fall"
    resumen["A2"], resumen["B2"], resumen["C2"] = "Proyecto B", "1ST", 1001
    libro.save(copia)
    oficial = tmp_path / "bmg_oficial.xlsx"
    resultados = [caso(1001, "1ST", "HT", "UGL", 5.8)]
    salida = pathlib.Path(generar_reporte_bmg(
        copia, oficial, resultados, cargar_config(), cargar_reglas(),
        idioma="de", identidad_proyecto=IDENTIDAD_B))
    assert salida == oficial and oficial.exists()
    publicado = load_workbook(salida)
    hoja = publicado["Übersicht Standversuche"]
    # La identidad explícita gobierna A1; el resto de la cabecera tabular
    # coherente permanece intacta y no se interpreta como contradicción.
    assert hoja["A1"].value == "Proyecto B"
    assert (hoja["B1"].value, hoja["C1"].value) == ("Stufe", "Fall")
    assert _hash(real) == hash_real            # plantilla del repo intacta
