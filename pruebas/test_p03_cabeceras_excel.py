"""P03 · Adaptador de cabeceras del libro real.

Las pruebas construyen libros en memoria: no hacen falta datos de la empresa.
"""
from __future__ import annotations

import pytest
from openpyxl import Workbook

from utilidades import cabeceras_excel as ce

# Encabezados tal como los escribe el libro (fila 7), en las columnas documentadas.
LIBRO_REAL = {
    'A': 'Woche\nWeek',
    'B': 'Versuche Begrundung  ',
    'C': 'Nummer\n Number',
    'D': 'Datum\nDate',
    'E': 'Standort\nPlace',
    'F': 'Temperatur °C Temperature °C',
    'G': 'Teilnummer\nPart number',
    'H': 'Version',
    'I': 'Serial\nNo. series',
    'J': 'Datum\nDate',
    'K': 'Stand\nEng. Level',
    'L': 'Delay\nms',
    'M': 'Gasgenerator\nInflator',
    'N': 'Lieferant\nSupplier',
    'O': 'Teilnummer\nPart number',
    'P': 'Serial\nSerie number',
    'Q': 'Datum\nDate',
    'R': 'Stand\nEng. Level',
    'S': 'Laser',
    'T': 'Lieferant\nSupplier',
    'U': 'Luftsack\nCushion',
    'V': 'Gehäuse\nHousing',
    'W': 'Schutzhuelle\nProtective cover',
    'X': 'Öffnungs zeit ms\nOpening time',
    'Y': 'FORVIA',
    'Z': 'Aufblaszeit ms\nFull inflation time',
    'AA': '2nd Review (Mario)',
    'AB': 'Bemerkungen der BFAB\nComments of PAB',
    'AC': 'Bewertung als ZSB BFAB\nEvaluation as ZSB BFAB',
    'AD': 'Bemerkungen der Instrumententafel\nComments of dashboard',
    'AE': 'Bewertung als ZSB I-Tafel\nEvaluation as ZSB I-Tafel',
    'AF': 'Bemerkungen der Versuchsträger\nComments of evironment of test',
    'AG': 'Gesamt bewertung als\nSicherheits Sytem IP+AB',
    'AH': '',
    'AI': '15) Weißbruch in Seitewand  der Gehäuse',
    'AJ': '16) Weißbruch in Innenbereich  der Gehäuse',
    'AK': '9) Luftsackspuren / Pinhole < 2 mm',
    'AL': '19) Stecker Auslösung',
    'AM': '17) Risse im Gehäuse des Airbagmoduls',
    'AN': '10) Tearing or Holes at frontal pannel (> 2 mm)',
    'AO': '14) Bremsen Rippen Trennung',
    'AP': '5) Weissbruch im Schusskanal Vorne Ecke',
    'AQ': '6) Weissbruch im Schusskanal Hintere Ecke',
    'AR': '7) Partikelflug im Fankorb (<0.115gr)',
    'AS': '11) Pin gebrochen -35°C',
    'AT': '8) Weissbruch im GK nach Deckel Schlag',
    'AU': '1) Cracking in Lid without detachement ',
    'AV': '2) Riss in Upperpart (A_SVK)',
    'AW': '3) Cracking in Lid with detachement ',
    'AX': 'Schusskanal mit Weissbruch',
    'AY': '12) Auslösung des Dekoren\xa0',
    'AZ': '13) Speaker Auslösung ',
    'BA': '18) TPO Lid gerisst ',
    'BB': '4) Risse im Schusskanal ()',
    'BC': 'Riss in Upperpart (in richtung Innsasen)',
}


def _libro(cabeceras=None, fila_encabezados: int = 7):
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Versuchsmatrix"
    for letra, texto in (cabeceras or LIBRO_REAL).items():
        hoja[f"{letra}{fila_encabezados}"] = texto
    return hoja


# --------------------------------------------------------------------------
# normalización y letras
# --------------------------------------------------------------------------
@pytest.mark.parametrize("entrada,esperado", [
    ("Versuche Begründung", "versuche begrundung"),
    ("Versuchsche Begruendung", "versuchsche begruendung"),
    ("Temperatur °C", "temperatur c"),
    ("  Standort  ", "standort"),
    ("PAB · Teilnummer", "pab teilnummer"),
    (None, ""),
])
def test_normaliza_encabezados(entrada, esperado):
    assert ce.normalizar_encabezado(entrada) == esperado


@pytest.mark.parametrize("letra,indice", [("A", 1), ("Z", 26), ("AA", 27), ("AH", 34), ("BC", 55)])
def test_letras_de_columna(letra, indice):
    assert ce.letra_a_indice(letra) == indice
    assert ce.indice_a_letra(indice) == letra


def test_letra_invalida_revienta():
    with pytest.raises(ValueError):
        ce.letra_a_indice("A1")


# --------------------------------------------------------------------------
# resolución
# --------------------------------------------------------------------------
def test_resuelve_las_cabeceras_reales_del_libro():
    """Las 54 cabeceras del Book-10-Examples.xlsx, tal cual están en la fila 7."""
    informe = ce.resolver_cabeceras(LIBRO_REAL)
    resueltos = informe.resueltos
    assert len(resueltos) == 33
    assert resueltos["week"] == "A"
    assert resueltos["test_reason"] == "B"
    assert resueltos["test_number"] == "C"
    assert resueltos["test_place"] == "E"
    assert resueltos["module_part_number"] == "G"
    assert resueltos["engineering_level"] == "K"
    assert resueltos["opening_time_ms"] == "X"


def test_ah_sin_encabezado_es_estructural_y_no_es_campo():
    informe = ce.resolver_cabeceras(LIBRO_REAL)
    assert "AH" in informe.estructurales
    assert "AH" not in informe.resueltos.values()


def test_lieferant_repetido_se_resuelve_por_columna_documentada():
    informe = ce.resolver_cabeceras(LIBRO_REAL)
    assert informe.resueltos["inflator_supplier"] == "N"
    assert informe.resueltos["dashboard_supplier"] == "T"
    assert not informe.colisiones


def test_lieferant_adicional_en_columna_no_documentada_queda_ambiguo():
    """Si aparece un 'Lieferant' de más, ese queda ambiguo; los documentados siguen."""
    cabeceras = dict(LIBRO_REAL)
    cabeceras["M"] = "Lieferant"      # columna documentada como tipo de generador
    informe = ce.resolver_cabeceras(cabeceras)
    ambiguas = {e.columna for e in informe.ambiguas}
    assert "M" in ambiguas
    assert informe.resueltos["inflator_supplier"] == "N"
    assert informe.resueltos["dashboard_supplier"] == "T"


def test_texto_que_contradice_la_columna_documentada_no_se_resuelve():
    """'Woche' en la columna del número de prueba: el libro cambió, no se adivina."""
    informe = ce.resolver_cabeceras({"A": "Woche", "C": "Woche"})
    ambiguas = {e.columna for e in informe.ambiguas}
    assert "C" in ambiguas
    assert informe.resueltos["week"] == "A"


def test_encabezado_desconocido_no_se_resuelve():
    informe = ce.resolver_cabeceras({"A": "Woche", "B": "Campo rarísimo sin documentar"})
    assert [e.columna for e in informe.no_resueltas] == ["B"]
    puede, motivo = informe.puede_escribir("test_reason")
    assert puede is False and "no resuelta" in motivo


def test_dos_columnas_con_el_mismo_campo_es_colision():
    """Fuera de las columnas documentadas, dos 'Woche' son una colisión: no se escribe."""
    informe = ce.resolver_cabeceras({"BD": "Woche", "BE": "Woche"})
    assert informe.colisiones.get("week") == ["BD", "BE"]
    assert informe.puede_escribir("week")[0] is False
    assert "colisión" in informe.puede_escribir("week")[1]


def test_texto_valido_en_columna_no_documentada_se_resuelve_y_lo_declara():
    informe = ce.resolver_cabeceras({"BD": "Nummer"})   # BD no está documentada
    assert informe.resueltos["test_number"] == "BD"
    entrada = next(e for e in informe.encabezados if e.columna == "BD")
    assert "no es la documentada" in entrada.motivo


# --------------------------------------------------------------------------
# escritura
# --------------------------------------------------------------------------
def test_escribe_solo_en_las_columnas_resueltas():
    hoja = _libro()
    informe = ce.resolver_cabeceras(ce.leer_cabeceras(hoja))
    salida = ce.escribir_valores(hoja, 8, {"test_number": "232550", "test_place": "EDAG"}, informe)
    assert hoja["C8"].value == "232550"
    assert hoja["E8"].value == "EDAG"
    assert {e["clave"] for e in salida["escritos"]} == {"test_number", "test_place"}


def test_no_reescribe_la_fila_de_encabezados():
    hoja = _libro()
    antes = {c: hoja[f"{c}7"].value for c in LIBRO_REAL}
    informe = ce.resolver_cabeceras(ce.leer_cabeceras(hoja))
    ce.escribir_valores(hoja, 8, {"week": "23"}, informe)
    despues = {c: hoja[f"{c}7"].value for c in LIBRO_REAL}
    assert antes == despues


def test_se_niega_a_escribir_en_la_fila_de_encabezados():
    hoja = _libro()
    informe = ce.resolver_cabeceras(ce.leer_cabeceras(hoja))
    with pytest.raises(ValueError):
        ce.escribir_valores(hoja, 7, {"week": "23"}, informe)


def test_no_pisa_una_formula():
    hoja = _libro()
    hoja["G9"] = '=K9&""'
    informe = ce.resolver_cabeceras(ce.leer_cabeceras(hoja))
    salida = ce.escribir_valores(hoja, 9, {"module_part_number": "2GJ 880 204 J"}, informe)
    assert hoja["G9"].value == '=K9&""'
    assert salida["omitidos"][0]["motivo"] == "la celda contiene una fórmula"


def test_no_limpia_ninguna_otra_celda():
    hoja = _libro()
    hoja["B8"] = "IT BMG"
    hoja["C8"] = "232550"
    informe = ce.resolver_cabeceras(ce.leer_cabeceras(hoja))
    ce.escribir_valores(hoja, 8, {"test_place": "EDAG"}, informe)
    assert hoja["B8"].value == "IT BMG"
    assert hoja["C8"].value == "232550"


def test_lo_que_no_se_escribe_se_informa_con_motivo():
    hoja = _libro({"A": "Woche", "B": "Campo desconocido"})
    informe = ce.resolver_cabeceras(ce.leer_cabeceras(hoja))
    salida = ce.escribir_valores(hoja, 8, {"test_reason": "IT BMG", "week": None}, informe)
    motivos = {o["clave"]: o["motivo"] for o in salida["omitidos"]}
    assert "no resuelta" in motivos["test_reason"]
    assert motivos["week"] == "sin valor"
    assert salida["escritos"] == []


def test_lee_cabeceras_de_la_hoja():
    hoja = _libro()
    cabeceras = ce.leer_cabeceras(hoja)
    assert cabeceras["A"] == "Woche\nWeek"
    assert cabeceras["AH"] == ""
    assert len(cabeceras) == 55  # A:BC
