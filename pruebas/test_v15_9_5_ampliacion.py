"""V15.9.5 · Ampliación de pruebas exigida por la auditoría (N7-N9).

Complementa `test_v15_9_5_auditoria_regresiones.py` (los 3 casos literales)
con los escenarios de `CORRECCIONES_OBLIGATORIAS_V_MATRIX_V15_9_5.md`:

- N7: hojas visibles no declaradas en ``hojas_busqueda`` (incluida la hoja
  BMG real ``Rangos``), hojas ocultas, contrato de exención documentada,
  cabeceras/pies de página y celdas etiquetadas en hojas no mapeadas.
- N8: títulos legítimos con año/semana/versión/fecha en ES/EN/DE, nombres
  compuestos, ID distinto del nombre visible, nombres parecidos A/AB y
  referencias ambiguas (fail-closed con explicación).
- N9: tres estados distintos (verificada / pendiente sin asignar / bloqueada
  / no verificada), decisión de usuario confirmada y propagación al endpoint
  de exportación.

Todo sintético (tmp_path); no toca datos reales ni de red.
"""
from __future__ import annotations

import hashlib
import importlib
import pathlib
import sys

import pytest
from openpyxl import Workbook, load_workbook

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "pruebas"))

from test_plantilla_empresarial import _plantilla
from utilidades.identidad_excel import aplicar_identidad_a_salida

IDENTIDAD_A = {"nombre_proyecto": "Proyecto A", "project_id": "proyecto-a",
               "origen": "declarado_usuario", "sin_asignar": False,
               "pendiente": False, "ejecucion_id": "ej-a"}
IDENTIDAD_B = {"nombre_proyecto": "Proyecto B", "project_id": "proyecto-b",
               "origen": "declarado_usuario", "sin_asignar": False,
               "pendiente": False, "ejecucion_id": "ej-b"}
SIN_ASIGNAR = {"nombre_proyecto": None, "project_id": "sin-asignar",
               "origen": "sin_asignar_expreso", "sin_asignar": True,
               "pendiente": True}


def _backend():
    return importlib.import_module("dashboard.backend.app")


def _hash(ruta) -> str:
    return hashlib.sha256(pathlib.Path(ruta).read_bytes()).hexdigest()


def _resumen_texto(libro, hoja="Resumen"):
    return "\n".join(str(c.value) for fila in libro[hoja].iter_rows()
                     for c in fila if c.value)


def _libro_etiquetado(titulo=None):
    """Libro mínimo con hoja Resumen y celda de proyecto etiquetada A2/B2."""
    libro = Workbook()
    libro.active.title = "Resumen"
    hoja = libro["Resumen"]
    if titulo is not None:
        hoja["A1"] = titulo
    hoja["A2"] = "Proyecto:"
    hoja["B2"] = "Proyecto A"  # valor histórico que el mapeo sustituye
    return libro


def _plantilla_publicable(ruta, titulo="Reporte del Proyecto B"):
    """Fixture empresarial con título coherente y celda etiquetada."""
    _plantilla(ruta)
    libro = load_workbook(ruta)
    captura = libro["Captura_pruebas"]
    captura["A1"] = titulo
    captura["A2"] = "Proyecto:"
    captura["B2"] = "Proyecto A"
    libro.save(ruta)
    return ruta


# ---------------------------------------------------------------------------
# N7 · todas las hojas visibles del entregable se examinan
# ---------------------------------------------------------------------------


def test_n7_hoja_visible_no_declarada_bloquea_publicacion(tmp_path):
    from plantilla_empresarial import generar_desde_plantilla
    plantilla = _plantilla_publicable(tmp_path / "base.xlsx")
    libro = load_workbook(plantilla)
    libro.create_sheet("Indicadores")["A1"] = "Reporte del Proyecto A"
    libro.save(plantilla)
    hash_plantilla = _hash(plantilla)
    oficial = tmp_path / "salida.xlsx"
    resultado = pathlib.Path(generar_desde_plantilla(
        plantilla, oficial, [], identidad_proyecto=IDENTIDAD_B))
    assert not oficial.exists()
    assert "borrador_no_publicable" in resultado.name and resultado.is_file()
    salida = load_workbook(resultado)
    # El título ajeno NUNCA se reemplaza; la celda etiquetada sí se mapeó.
    assert salida["Indicadores"]["A1"].value == "Reporte del Proyecto A"
    assert salida["Captura_pruebas"]["B2"].value == "Proyecto B"
    resumen = _resumen_texto(salida)
    assert "REFERENCIA CONTRADICTORIA" in resumen
    assert "Indicadores" in resumen
    assert _hash(plantilla) == hash_plantilla  # plantilla original intacta


def test_n7_hoja_oculta_no_forma_parte_del_entregable_visible(tmp_path):
    from plantilla_empresarial import generar_desde_plantilla
    plantilla = _plantilla_publicable(tmp_path / "base.xlsx")
    libro = load_workbook(plantilla)
    historica = libro.create_sheet("Historico")
    historica["A1"] = "Reporte del Proyecto A"
    historica.sheet_state = "hidden"
    libro.save(plantilla)
    oficial = tmp_path / "salida.xlsx"
    resultado = pathlib.Path(generar_desde_plantilla(
        plantilla, oficial, [], identidad_proyecto=IDENTIDAD_B))
    # La hoja oculta se conserva intacta en el archivo, pero no es entregable
    # visible: no bloquea la publicación identificada.
    assert resultado == oficial and oficial.is_file()
    assert load_workbook(oficial)["Historico"]["A1"].value == "Reporte del Proyecto A"


def test_n7_exencion_documentada_para_hoja_de_historico():
    libro = _libro_etiquetado("Reporte del Proyecto B")
    libro.create_sheet("Historico")["A1"] = "Reporte del Proyecto A"
    meta = aplicar_identidad_a_salida(
        libro, IDENTIDAD_B, hojas_busqueda=["Resumen"], hoja_resumen="Resumen",
        hojas_exentas=["Historico"])
    assert meta["publicable"] is True
    assert meta["contradicciones"] == []
    assert meta["hojas_exentas"] == ["Historico"]
    # La exención queda DOCUMENTADA en el bloque de identidad.
    resumen = _resumen_texto(libro)
    assert "Hojas exentas" in resumen and "Historico" in resumen
    # Sin la exención, la misma hoja bloquea (fail-closed por defecto).
    libro2 = _libro_etiquetado("Reporte del Proyecto B")
    libro2.create_sheet("Historico")["A1"] = "Reporte del Proyecto A"
    meta2 = aplicar_identidad_a_salida(
        libro2, IDENTIDAD_B, hojas_busqueda=["Resumen"], hoja_resumen="Resumen")
    assert meta2["publicable"] is False


def test_n7_cabecera_de_pagina_con_otro_proyecto_bloquea():
    libro = _libro_etiquetado("Reporte del Proyecto B")
    libro["Resumen"].oddHeader.center.text = "Reporte del Proyecto A"
    libro["Resumen"].oddFooter.left.text = "Projekt A — internes Dokument"
    meta = aplicar_identidad_a_salida(
        libro, IDENTIDAD_B, hojas_busqueda=["Resumen"], hoja_resumen="Resumen")
    assert meta["publicable"] is False
    referencias = {(c["hoja"], c["celda"]) for c in meta["contradicciones"]}
    assert ("Resumen", "oddHeader.center") in referencias
    assert ("Resumen", "oddFooter.left") in referencias
    # Las cabeceras no se reemplazan nunca.
    assert libro["Resumen"].oddHeader.center.text == "Reporte del Proyecto A"


def test_n7_bmg_hoja_rangos_con_titulo_ajeno_bloquea(tmp_path):
    from reporte_bmg import generar_reporte_bmg
    from configuracion import cargar_config, cargar_reglas
    from test_reporte_bmg_v7 import caso
    real = RAIZ / "plantillas" / "reporte_bmg_1st_2st.xlsx"
    hash_real = _hash(real)
    resultados = [caso(1001, "1ST", "HT", "UGL", 5.8)]
    sucia = tmp_path / "bmg_sucia.xlsx"
    sucia.write_bytes(real.read_bytes())
    libro = load_workbook(sucia)
    # «Rangos» es visible pero NO está en hojas_busqueda del generador BMG.
    libro["Rangos"]["A1"] = "Reporte del Proyecto A"
    libro.save(sucia)
    oficial = tmp_path / "bmg_oficial.xlsx"
    salida = pathlib.Path(generar_reporte_bmg(
        sucia, oficial, resultados, cargar_config(), cargar_reglas(),
        idioma="es", identidad_proyecto=IDENTIDAD_B))
    assert not oficial.exists()
    assert "borrador_no_publicable" in salida.name and salida.is_file()
    resumen = _resumen_texto(load_workbook(salida), "Übersicht Standversuche")
    assert "REFERENCIA CONTRADICTORIA" in resumen and "Rangos" in resumen
    # La plantilla real del repositorio permanece byte-intacta.
    assert _hash(real) == hash_real
    # Control: con la plantilla limpia, la hoja de diccionario (documentación
    # estática de campos, exenta por contrato) no produce falsos positivos y
    # la exención queda documentada en el bloque.
    limpia = tmp_path / "bmg_limpia.xlsx"
    limpia.write_bytes(real.read_bytes())
    salida2 = pathlib.Path(generar_reporte_bmg(
        limpia, tmp_path / "bmg_oficial2.xlsx", resultados, cargar_config(),
        cargar_reglas(), idioma="es", identidad_proyecto=IDENTIDAD_B))
    resumen2 = _resumen_texto(load_workbook(salida2), "Übersicht Standversuche")
    assert "REFERENCIA CONTRADICTORIA" not in resumen2
    assert "Hojas exentas" in resumen2


def test_n7_celda_mapeada_no_garantiza_las_demas_referencias():
    """Una etiqueta «Proyecto:» mapeada NO prueba que el resto sea correcto.

    V15.9.6 (CRIT-N10) SUPERSEDE el comportamiento V15.9.5 para pares
    etiqueta/valor en hojas elegibles: la verificación estructural los
    corrige de manera específica (celda de valor, registrada en
    ``celdas_complementarias``) en vez de bloquear; lo que NO se puede
    resolver sin riesgo bloquea. La garantía original se conserva: ninguna
    referencia contradictoria de texto libre se publica ni se reemplaza
    jamás, y un par no resoluble no se ignora.
    """
    libro = _libro_etiquetado("Reporte del Proyecto B")
    otra = libro.create_sheet("Indicadores")
    otra["A2"] = "Proyecto:"
    otra["B2"] = "Proyecto A"  # par etiqueta/valor en hoja NO mapeada
    meta = aplicar_identidad_a_salida(
        libro, IDENTIDAD_B, hojas_busqueda=["Resumen"], hoja_resumen="Resumen")
    # N10: el par complementario se corrige de manera específica y se registra.
    assert libro["Indicadores"]["B2"].value == "Proyecto B"
    assert any(c["hoja"] == "Indicadores" and c["celda_valor"] == "B2"
               and c["valor_anterior"] == "Proyecto A"
               for c in meta["celdas_complementarias"])
    assert meta["publicable"] is True
    # Un TÍTULO libre de otro proyecto en la misma hoja sigue bloqueando y no
    # se reemplaza (la revisión de textos complementa a la estructural).
    libro2 = _libro_etiquetado("Reporte del Proyecto B")
    extra = libro2.create_sheet("Indicadores")
    extra["A1"] = "Reporte del Proyecto A"
    meta2 = aplicar_identidad_a_salida(
        libro2, IDENTIDAD_B, hojas_busqueda=["Resumen"], hoja_resumen="Resumen")
    assert meta2["publicable"] is False
    assert libro2["Indicadores"]["A1"].value == "Reporte del Proyecto A"
    # Un par con fórmula en el valor NO se reemplaza: bloquea señalando celda.
    libro3 = _libro_etiquetado("Reporte del Proyecto B")
    formula = libro3.create_sheet("Indicadores")
    formula["A2"] = "Proyecto:"
    formula["B2"] = "=CONCATENAR(\"Proyecto \",\"A\")"
    meta3 = aplicar_identidad_a_salida(
        libro3, IDENTIDAD_B, hojas_busqueda=["Resumen"], hoja_resumen="Resumen")
    assert meta3["publicable"] is False
    assert libro3["Indicadores"]["B2"].value == "=CONCATENAR(\"Proyecto \",\"A\")"
    assert any(c.get("estructural") for c in meta3["contradicciones"])


# ---------------------------------------------------------------------------
# N8 · nombre del proyecto separado de metadatos (año/semana/versión/fecha)
# ---------------------------------------------------------------------------


TITULOS_ANIO = {
    "es": "Reporte del Proyecto B — Año 2026",
    "en": "Report of Project B — Year 2026",
    "de": "Bericht Projekt B — Jahr 2026",
}


@pytest.mark.parametrize("idioma", ["es", "en", "de"])
def test_n8_titulo_correcto_con_anio_publica_en_los_tres_idiomas(idioma, tmp_path):
    from plantilla_empresarial import generar_desde_plantilla
    plantilla = _plantilla_publicable(tmp_path / f"base_{idioma}.xlsx",
                                      titulo=TITULOS_ANIO[idioma])
    oficial = tmp_path / f"salida_{idioma}.xlsx"
    resultado = pathlib.Path(generar_desde_plantilla(
        plantilla, oficial, [], identidad_proyecto=IDENTIDAD_B, idioma=idioma))
    assert resultado == oficial and oficial.is_file(), idioma
    assert load_workbook(oficial)["Captura_pruebas"]["B2"].value == "Proyecto B"


@pytest.mark.parametrize("titulo", [
    "Proyecto B - Semana 12",
    "Project B — Week 12",
    "Projekt B — Woche 12",
    "Proyecto B (v1.3)",
    "Proyecto B, 12.10.2026",
    "Reporte del Proyecto B — Año 2026, revisión 3",
])
def test_n8_metadatos_de_prueba_no_generan_falsa_contradiccion(titulo):
    libro = _libro_etiquetado(titulo)
    meta = aplicar_identidad_a_salida(
        libro, IDENTIDAD_B, hojas_busqueda=["Resumen"], hoja_resumen="Resumen")
    assert meta["contradicciones"] == [], titulo
    assert meta["publicable"] is True


def test_n8_nombre_compuesto_e_id_distinto_al_nombre_visible():
    identidad = {"nombre_proyecto": "Proyecto Beta Sur",
                 "project_id": "PRJ-2026-07", "origen": "declarado_usuario",
                 "sin_asignar": False}
    for titulo in ("Reporte del Proyecto Beta Sur — Año 2026",
                   "Reporte del Proyecto PRJ-2026-07",
                   "Reporte del Proyecto Beta Sur (Semana 12)"):
        libro = _libro_etiquetado(titulo)
        meta = aplicar_identidad_a_salida(
            libro, identidad, hojas_busqueda=["Resumen"], hoja_resumen="Resumen")
        assert meta["contradicciones"] == [], titulo
        assert meta["publicable"] is True


@pytest.mark.parametrize("identidad,titulo", [
    (IDENTIDAD_A, "Reporte del Proyecto AB"),   # parecido: A vs AB
    ({"nombre_proyecto": "Proyecto AB", "project_id": "proyecto-ab",
      "origen": "declarado_usuario", "sin_asignar": False},
     "Reporte del Proyecto A"),                 # parecido: AB vs A
])
def test_n8_nombres_parecidos_sigue_bloqueando(identidad, titulo):
    libro = _libro_etiquetado(titulo)
    meta = aplicar_identidad_a_salida(
        libro, identidad, hojas_busqueda=["Resumen"], hoja_resumen="Resumen")
    assert meta["publicable"] is False
    assert meta["contradicciones"]


def test_n8_referencia_ambigua_sin_nombre_resoluble_bloquea_con_explicacion():
    libro = _libro_etiquetado("Reporte del Proyecto 2026")
    meta = aplicar_identidad_a_salida(
        libro, IDENTIDAD_B, hojas_busqueda=["Resumen"], hoja_resumen="Resumen")
    # Fail-closed: sólo un número no permite verificar con certeza.
    assert meta["publicable"] is False
    assert meta["contradicciones"]
    assert "resoluble" in meta["contradicciones"][0]["detalle"]
    # El bloque explica exactamente qué referencia no se pudo verificar.
    assert "resoluble" in _resumen_texto(libro)


# ---------------------------------------------------------------------------
# N9 · decisión confirmada ≠ identidad verificada; tres estados distintos
# ---------------------------------------------------------------------------


def test_n9_sin_asignar_es_decision_pendiente_no_identidad_verificada():
    libro = Workbook()
    libro.active.title = "Resumen"
    libro["Resumen"]["A1"] = "Reporte de ensayos"
    meta = aplicar_identidad_a_salida(
        libro, dict(SIN_ASIGNAR), hojas_busqueda=["Resumen"], hoja_resumen="Resumen")
    assert meta["identidad_verificada"] is False
    assert meta["decision_usuario_confirmada"] is True
    assert meta["estado_identidad"] == "pendiente_sin_asignar"
    # Plantilla limpia: se entrega como PENDIENTE (P02), estado diferenciado.
    assert meta["publicable"] is True
    resumen = _resumen_texto(libro)
    assert "Identidad del proyecto verificada" in resumen
    assert "Sin asignar" in resumen


def test_n9_proyecto_declarado_con_celda_mapeada_es_verificado():
    libro = _libro_etiquetado("Reporte del Proyecto B")
    meta = aplicar_identidad_a_salida(
        libro, IDENTIDAD_B, hojas_busqueda=["Resumen"], hoja_resumen="Resumen")
    assert meta["identidad_verificada"] is True
    assert meta["decision_usuario_confirmada"] is True
    assert meta["estado_identidad"] == "verificada"
    assert meta["publicable"] is True


def test_n9_sin_asignar_con_titulo_historico_queda_bloqueado():
    libro = _libro_etiquetado("Reporte del Proyecto A")
    meta = aplicar_identidad_a_salida(
        libro, dict(SIN_ASIGNAR), hojas_busqueda=["Resumen"], hoja_resumen="Resumen")
    assert meta["identidad_verificada"] is False
    assert meta["decision_usuario_confirmada"] is True
    assert meta["estado_identidad"] == "bloqueada_contradiccion"
    assert meta["publicable"] is False
    # El título histórico no se reemplaza ni se autoriza.
    assert libro["Resumen"]["A1"].value == "Reporte del Proyecto A"


def test_n9_plantilla_sin_celda_identificable_no_esta_verificada():
    libro = Workbook()
    libro.active.title = "Resumen"
    libro["Resumen"]["A1"] = "Reporte de ensayos"
    meta = aplicar_identidad_a_salida(
        libro, IDENTIDAD_B, hojas_busqueda=["Resumen"], hoja_resumen="Resumen")
    assert meta["identidad_verificada"] is False
    assert meta["decision_usuario_confirmada"] is True
    assert meta["estado_identidad"] == "no_verificada"
    assert meta["publicable"] is False


def test_n9_export_api_distingue_pendiente_de_verificado(tmp_path, monkeypatch):
    backend = _backend()
    oficial = tmp_path / "resultado_ES.xlsx"
    Workbook().save(oficial)
    datos = {"resultados": [{"nombre": "caso"}],
             "nombre_excel_base": str(tmp_path / "resultado.xlsx")}
    monkeypatch.setattr(backend, "_cargar_datos", lambda: dict(datos))
    monkeypatch.setattr(backend, "_limites_apertura_efectivos",
                        lambda: (6, 7, "predeterminado", None))
    monkeypatch.setattr(backend, "_generar_excel_serializado",
                        lambda *a, **k: oficial)
    solicitud = backend.SolicitudExportacion(idiomas=["es"])
    # Identidad verificada: publicada normal.
    datos["proyecto_ejecucion"] = dict(IDENTIDAD_B)
    confirmada = backend.exportar_resultados(solicitud)
    assert confirmada["estado_publicacion"] == "publicada"
    assert confirmada["identidad_verificada"] is True
    assert confirmada["generados"][0]["estado_identidad"] == "verificada"
    # Decisión «Sin asignar»: PENDIENTE diferenciado, jamás verificada.
    datos["proyecto_ejecucion"] = dict(SIN_ASIGNAR)
    pendiente = backend.exportar_resultados(solicitud)
    assert pendiente["estado_publicacion"] == "pendiente_publicada"
    assert pendiente["identidad_verificada"] is False
    assert pendiente["pendiente_sin_asignar"] is True
    assert pendiente["generados"][0]["estado_identidad"] == "pendiente_sin_asignar"
    assert pendiente["publicable"] is True  # entregable como pendiente (P02)
    assert pendiente["bloqueados"] == []
