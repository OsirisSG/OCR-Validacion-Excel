"""P01-R01 · Vaciado de datos: alias reales del libro y puerta de publicación.

Contrato que se exige aquí (no relaja nada existente):

1. El encabezado REAL del libro (`Versuche Begrundung`) y sus alias bilingües
   producen `test_reason`. Hoy no se reconocen: el extractor solo conoce
   `PROYECTO|PROJECT|PROJEKT|MOTIVO|TEST REASON|PRÜFGRUND` seguidos de `:` o `=`.
2. Un valor cuyo estado es `pendiente_revision` o `conflicto` NUNCA se escribe
   en la plantilla del usuario como si estuviera confirmado.
3. Un valor limpio se sigue escribiendo igual que antes (no regresión).

Sin datos reales: todo son cadenas y libros en memoria.
"""
from __future__ import annotations

import pytest
from openpyxl import Workbook

import flujo_empresarial as fe
import reporte_bmg as rb

IMAGEN = {"confianza_ocr": 0.95}


def _hoja():
    return Workbook().active


def _valor_de(clave):
    return dict(zip(rb.CLAVES_PLANTILLA, range(1, len(rb.CLAVES_PLANTILLA) + 1)))[clave]


# ---------------------------------------------------------------------------
# 1 · Alias reales del libro para el motivo de la prueba
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("texto", [
    "Versuche Begrundung: IT BMG",
    "Versuche Begründung: IT BMG",
    "Versuchsbegründung: IT BMG",
    "Test reason: IT BMG",
    "Prüfgrund: IT BMG",
    "Motivo de prueba: IT BMG",
])
def test_alias_de_motivo_del_libro_producen_test_reason(texto):
    candidatos = fe.extraer_candidatos_texto(texto, IMAGEN, {})
    motivos = [c for c in candidatos if c["clave"] == "test_reason"]
    assert motivos, f"no se reconoció el motivo en {texto!r}"
    assert motivos[0]["valor_normalizado"].strip().upper() == "IT BMG"


def test_alias_de_motivo_conserva_el_original_y_la_regla():
    candidatos = fe.extraer_candidatos_texto("Versuche Begrundung: IT BMG", IMAGEN, {})
    motivo = [c for c in candidatos if c["clave"] == "test_reason"][0]
    assert motivo["valor_original"] == "IT BMG"
    assert motivo["regla_aplicada"]
    assert motivo["confianza_ocr"] == pytest.approx(0.95, abs=1e-6)


def test_alias_no_confunde_una_frase_cualquiera_con_el_motivo():
    """Sin dos puntos ni '=' no hay campo: no se inventa el motivo."""
    candidatos = fe.extraer_candidatos_texto("Versuche Begrundung IT BMG sin separador",
                                             IMAGEN, {})
    assert not [c for c in candidatos if c["clave"] == "test_reason"]


def test_motivo_explicito_previo_sigue_funcionando():
    """No regresión del alias que ya existía."""
    candidatos = fe.extraer_candidatos_texto("PROYECTO: IT BMG", IMAGEN, {})
    assert [c["valor_normalizado"] for c in candidatos if c["clave"] == "test_reason"] == ["IT BMG"]


# ---------------------------------------------------------------------------
# 2 · Puerta de publicación: lo que está en revisión no entra en la plantilla
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("clave", ["test_number", "test_place", "inflator_supplier"])
def test_valor_en_revision_no_se_escribe_en_la_plantilla(clave):
    hoja = _hoja()
    rb._escribir_fila(hoja, 8, {"campos": {
        clave: {"valor": "VALOR_SOSPECHOSO", "estado": "pendiente_revision",
                "requiere_revision": True}}})
    assert hoja.cell(8, _valor_de(clave)).value is None


@pytest.mark.parametrize("clave", ["test_number", "test_place", "inflator_supplier"])
def test_valor_en_conflicto_no_se_escribe_en_la_plantilla(clave):
    hoja = _hoja()
    rb._escribir_fila(hoja, 8, {"campos": {
        clave: {"valor": "VALOR_EN_CONFLICTO", "estado": "conflicto"}}})
    assert hoja.cell(8, _valor_de(clave)).value is None


def test_valor_limpio_si_se_escribe():
    """No regresión: un campo extraído y sin revisión se publica como siempre."""
    hoja = _hoja()
    rb._escribir_fila(hoja, 8, {"campos": {
        "test_number": {"valor": "232550", "estado": "extraido"},
        "test_place": {"valor": "EDAG", "estado": "extraido"},
        "inflator_supplier": {"valor": "Autoliv", "estado": "extraido"},
        "dashboard_supplier": {"valor": "FORVIA", "estado": "extraido"},
    }})
    # P08: en el libro el número de prueba es un número, no texto (la lectura sigue
    # siendo "232550"; lo que cambia es el tipo con el que se escribe la celda).
    assert hoja.cell(8, _valor_de("test_number")).value == 232550
    assert hoja.cell(8, _valor_de("test_place")).value == "EDAG"
    assert hoja.cell(8, _valor_de("inflator_supplier")).value == "Autoliv"
    assert hoja.cell(8, _valor_de("dashboard_supplier")).value == "FORVIA"


def test_proveedores_no_se_arrastran_entre_columnas():
    """Regresión obligatoria del diagnóstico P00 (C1/C1b)."""
    hoja = _hoja()
    rb._escribir_fila(hoja, 8, {"campos": {
        "inflator_supplier": {"valor": "Autoliv", "estado": "extraido"}}})
    assert hoja.cell(8, _valor_de("inflator_supplier")).value == "Autoliv"
    assert hoja.cell(8, _valor_de("dashboard_supplier")).value is None


def test_valor_confirmado_por_humano_siempre_se_publica():
    """Una confirmación humana manda sobre la marca de revisión."""
    hoja = _hoja()
    rb._escribir_fila(hoja, 8, {"campos": {
        "test_place": {"valor": "EDAG", "estado": "confirmado_manual",
                       "requiere_revision": False}}})
    assert hoja.cell(8, _valor_de("test_place")).value == "EDAG"


# ---------------------------------------------------------------------------
# 3 · Etiquetas reales del libro que el extractor no leía
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("texto,laboratorio,manual", [
    ("Standort: EDAG", "EDAG", False),
    ("Standort: EDAG Testlab", "EDAG", False),
    ("Standort: VW AG", "VW", True),          # VW AG puede ser fabricante
    ("Place: XYZ Lab", "XYZ Lab", True),      # laboratorio no catalogado
])
def test_standort_produce_test_place(texto, laboratorio, manual):
    candidatos = fe.extraer_candidatos_texto(texto, IMAGEN, {})
    lugares = [c for c in candidatos if c["clave"] == "test_place"]
    assert lugares and lugares[0]["valor_normalizado"] == laboratorio
    assert lugares[0]["requiere_confirmacion_manual"] is manual


def test_standort_sin_valor_no_inventa_laboratorio():
    assert not [c for c in fe.extraer_candidatos_texto("Standort:", IMAGEN, {})
                if c["clave"] == "test_place"]


@pytest.mark.parametrize("texto,esperado", [
    ("Nummer: 232550", "232550"),
    ("Number: 222550", "222550"),
    ("Test number: 232541", "232541"),
])
def test_nummer_produce_test_number_preservando_el_texto(texto, esperado):
    numeros = [c for c in fe.extraer_candidatos_texto(texto, IMAGEN, {})
               if c["clave"] == "test_number"]
    assert numeros and numeros[0]["valor_normalizado"] == esperado
    assert numeros[0]["requiere_confirmacion_manual"] is True


def test_nummer_sin_digitos_no_emite_candidato():
    assert not [c for c in fe.extraer_candidatos_texto("Nummer: ABCDEF", IMAGEN, {})
                if c["clave"] == "test_number"]


def test_serial_con_la_forma_del_libro_se_lee():
    """'Serial No.' es el rótulo real; antes no producía ninguna serie."""
    candidatos = fe.extraer_candidatos_texto("MODUL AIRBAG\nSerial No.: 671 ZRZ0540005Y",
                                             IMAGEN, {})
    seriales = [c for c in candidatos if "serial" in c["clave"]]
    assert seriales and seriales[0]["valor_normalizado"] == "671 ZRZ0540005Y"


def test_woche_valida_y_descarta_fuera_de_rango():
    ok = [c for c in fe.extraer_candidatos_texto("Woche: 23", IMAGEN, {}) if c["clave"] == "week"]
    assert ok and ok[0]["valor_normalizado"] == "23"
    malo = [c for c in fe.extraer_candidatos_texto("Woche: 78", IMAGEN, {}) if c["clave"] == "week"]
    assert not malo


@pytest.mark.parametrize("texto,clave", [
    ("MODUL AIRBAG\nStand Eng. Level: 01S", "engineering_level"),
    ("TABLERO\nStand Eng. Level: 69K", "dashboard_engineering_level"),
    ("Stand Eng. Level: 44K", "_nivel_por_identificar"),
])
def test_nivel_de_ingenieria_etiquetado(texto, clave):
    niveles = [c for c in fe.extraer_candidatos_texto(texto, IMAGEN, {})
               if "engineering_level" in c["clave"] or c["clave"].startswith("_nivel")]
    assert niveles and niveles[0]["clave"] == clave


# ---------------------------------------------------------------------------
# 4 · Temperatura contradictoria y duplicados
# ---------------------------------------------------------------------------
def test_temperatura_contradictoria_se_marca_para_revision():
    candidatos = fe.extraer_candidatos_texto("HT 85 C / RT 23 C", IMAGEN, {})
    temperatura = [c for c in candidatos if c["clave"] == "temperature_condition"]
    assert temperatura
    assert temperatura[0]["requiere_confirmacion_manual"] is True
    assert "HT" in temperatura[0]["observacion"] and "RT" in temperatura[0]["observacion"]


def test_temperatura_unica_no_pide_confirmacion():
    candidatos = fe.extraer_candidatos_texto("NT -35 C", IMAGEN, {})
    temperatura = [c for c in candidatos if c["clave"] == "temperature_condition"]
    assert temperatura and temperatura[0]["requiere_confirmacion_manual"] is False


def test_no_se_duplican_candidatos_identicos():
    """Dos coincidencias del mismo valor no son dos votos: no inflan el consenso."""
    candidatos = fe.extraer_candidatos_texto("MODUL AIRBAG\nStand Eng. Level: 01S",
                                             IMAGEN, {})
    firmas = [(c["clave"], c["valor_normalizado"], c["componente"]) for c in candidatos]
    assert len(firmas) == len(set(firmas))


def test_dos_proveedores_distintos_no_se_deduplican_entre_si():
    """Mismo valor en claves distintas se conserva: son campos distintos."""
    texto = "MODUL AIRBAG\nLieferant: Autoliv\nTABLERO\nLieferant: Autoliv"
    candidatos = fe.extraer_candidatos_texto(texto, IMAGEN, {})
    claves = {c["clave"] for c in candidatos if "supplier" in c["clave"]}
    assert "inflator_supplier" in claves


# ---------------------------------------------------------------------------
# 5 · P01-R02 · Número de prueba visible, proyecto y nivel, con OCR real
# ---------------------------------------------------------------------------
def test_designacion_de_proyecto_no_es_numero_de_prueba():
    """'VW316/5' está en el título de TODOS los diagramas: es el proyecto."""
    candidatos = fe.extraer_candidatos_texto("VW316/5 232550 RdW HT NOM", IMAGEN, {})
    numeros = [c["valor_normalizado"] for c in candidatos if c["clave"] == "test_number"]
    assert "VW316/5" not in numeros
    assert "232550" in numeros
    proyecto = [c for c in candidatos if c["clave"] == "_proyecto_designacion"]
    assert proyecto and proyecto[0]["valor_normalizado"] == "VW316/5"


def test_designacion_de_proyecto_no_declara_laboratorio_vw():
    candidatos = fe.extraer_candidatos_texto("VW316/5 232550 RdW HT NOM", IMAGEN, {})
    assert not [c for c in candidatos if c["clave"] == "test_place"]


@pytest.mark.parametrize("texto,esperado", [
    ("VW316/5 232550 RdW HT NOM", "232550"),
    ("222521\nVW 316/5\nIt 03s\nBMG\nOGL", "222521"),
    ("252581\n15t Nom\n03s\n+23*C", "252581"),
])
def test_numero_impreso_de_seis_digitos_se_propone(texto, esperado):
    numeros = [c for c in fe.extraer_candidatos_texto(texto, IMAGEN, {})
               if c["clave"] == "test_number"]
    assert any(n["valor_normalizado"] == esperado for n in numeros)
    assert all(n["requiere_confirmacion_manual"] for n in numeros
               if n["valor_normalizado"] == esperado)


@pytest.mark.parametrize("texto", ["895544", "235599", "100425", "671 ZRZ0539991D"])
def test_no_se_inventa_numero_de_prueba(texto):
    """Semana inválida, año inválido, fecha o serial no son número de prueba."""
    numeros = [c for c in fe.extraer_candidatos_texto(texto, IMAGEN, {})
               if c["clave"] == "test_number"]
    assert numeros == []


def test_nivel_de_ingenieria_en_etiqueta_real_no_se_descarta():
    """Las fotos reales no dicen 'MODUL': el nivel debe conservarse igual."""
    niveles = [c for c in fe.extraer_candidatos_texto("222521\nIt 03s\n66k", IMAGEN, {})
               if "nivel" in c["clave"] or "engineering_level" in c["clave"]]
    assert {n["valor_normalizado"] for n in niveles} == {"03S", "66K"}
    assert all(n["requiere_confirmacion_manual"] for n in niveles)


def test_temperatura_impresa_se_lee_y_se_propone_categoria():
    candidatos = fe.extraer_candidatos_texto("+23*C\nBMG", IMAGEN, {})
    impresa = [c for c in candidatos if c["clave"] == "_temperatura_impresa"]
    assert impresa and impresa[0]["valor_normalizado"] == "+23"
    assert impresa[0]["temperatura_sugerida"] == "RT"
    assert impresa[0]["requiere_confirmacion_manual"] is True


def test_categoria_por_catalogo_no_se_publica_como_confirmada():
    """Sin código HT/RT/NT impreso, la categoría es una deducción: va a revisión."""
    temperatura = [c for c in fe.extraer_candidatos_texto("+23*C\nBMG", IMAGEN, {})
                   if c["clave"] == "temperature_condition"]
    assert temperatura
    assert temperatura[0]["requiere_confirmacion_manual"] is True
    assert temperatura[0]["regla_aplicada"] == "temperatura_por_catalogo_nominal"


def test_codigo_de_temperatura_impreso_sigue_siendo_confirmable():
    temperatura = [c for c in fe.extraer_candidatos_texto("HT 85 C", IMAGEN, {})
                   if c["clave"] == "temperature_condition"]
    assert temperatura and temperatura[0]["regla_aplicada"] == "temperatura_contextual"
    assert temperatura[0]["requiere_confirmacion_manual"] is False
