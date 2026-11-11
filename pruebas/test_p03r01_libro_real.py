"""P03-R01 · El catálogo se cierra contra el libro real entregado el 2026-10-30.

Fixture: las 54 cabeceras tal cual están escritas en la fila 7 de
`Book-10-Examples.xlsx` (hoja `Versuchsmatrix`), con los saltos de línea y las
erratas del original ("Versuche Begrundung", "evironment", "Sytem", "gerisst").
No se maquilla: si el libro dice así, la prueba dice así.
"""
import pytest


LIBRO_REAL = {
    "A": "Woche\nWeek",
    "B": "Versuche Begrundung  ",
    "C": "Nummer\n Number",
    "D": "Datum\nDate",
    "E": "Standort\nPlace",
    "F": "Temperatur °C Temperature °C",
    "G": "Teilnummer\nPart number",
    "H": "Version",
    "I": "Serial\nNo. series",
    "J": "Datum\nDate",
    "K": "Stand\nEng. Level",
    "L": "Delay\nms",
    "M": "Gasgenerator\nInflator",
    "N": "Lieferant\nSupplier",
    "O": "Teilnummer\nPart number",
    "P": "Serial\nSerie number",
    "Q": "Datum\nDate",
    "R": "Stand\nEng. Level",
    "S": "Laser",
    "T": "Lieferant\nSupplier",
    "U": "Luftsack\nCushion",
    "V": "Gehäuse\nHousing",
    "W": "Schutzhuelle\nProtective cover",
    "X": "Öffnungs zeit ms\nOpening time",
    "Y": "FORVIA",
    "Z": "Aufblaszeit ms\nFull inflation time",
    "AA": "2nd Review (Mario)",
    "AB": "Bemerkungen der BFAB\nComments of PAB",
    "AC": "Bewertung als ZSB BFAB\nEvaluation as ZSB BFAB",
    "AD": "Bemerkungen der Instrumententafel\nComments of dashboard",
    "AE": "Bewertung als ZSB I-Tafel\nEvaluation as ZSB I-Tafel",
    "AF": "Bemerkungen der Versuchsträger\nComments of evironment of test",
    "AG": "Gesamt bewertung als\nSicherheits Sytem IP+AB",
    "AH": None,
    "AI": "15) Weißbruch in Seitewand  der Gehäuse",
    "AJ": "16) Weißbruch in Innenbereich  der Gehäuse",
    "AK": "9) Luftsackspuren / Pinhole < 2 mm",
    "AL": "19) Stecker Auslösung",
    "AM": "17) Risse im Gehäuse des Airbagmoduls",
    "AN": "10) Tearing or Holes at frontal pannel (> 2 mm)",
    "AO": "14) Bremsen Rippen Trennung",
    "AP": "5) Weissbruch im Schusskanal Vorne Ecke",
    "AQ": "6) Weissbruch im Schusskanal Hintere Ecke",
    "AR": "7) Partikelflug im Fankorb (<0.115gr)",
    "AS": "11) Pin gebrochen -35°C",
    "AT": "8) Weissbruch im GK nach Deckel Schlag",
    "AU": "1) Cracking in Lid without detachement",
    "AV": "2) Riss in Upperpart (A_SVK)",
    "AW": "3) Cracking in Lid with detachement",
    "AX": "Schusskanal mit Weissbruch",
    "AY": "12) Auslösung des Dekoren",
    "AZ": "13) Speaker Auslösung",
    "BA": "18) TPO Lid gerisst",
    "BB": "4) Risse im Schusskanal ()",
    "BC": "Riss in Upperpart (in richtung Innsasen)",
}


@pytest.fixture()
def ce():
    from utilidades import cabeceras_excel
    return cabeceras_excel


def test_las_54_cabeceras_del_libro_real_se_reconocen(ce):
    """54 cabeceras = 33 escribibles + 21 evaluaciones de daño + 1 estructural."""
    informe = ce.resolver_cabeceras(LIBRO_REAL)
    assert len(informe.resueltos) == 33
    assert len([e for e in informe.encabezados if e.estado == "dano"]) == 21
    assert informe.estructurales == ["AH"]
    assert informe.ambiguas == []
    assert informe.no_resueltas == [] and informe.danos and len(informe.danos) == 21


def test_ninguna_columna_del_libro_queda_fuera_del_catalogo(ce):
    informe = ce.resolver_cabeceras(LIBRO_REAL)
    cubiertas = set()
    for e in informe.encabezados:
        assert e.estado in {"resuelta", "dano", "estructural"}, e
        if e.estado != "estructural":
            cubiertas.add(e.columna)
    assert cubiertas == {k for k in LIBRO_REAL if k != "AH"}


def test_los_campos_van_a_su_columna_real(ce):
    """Los cuatro textos repetidos se resuelven por columna, no por orden de aparición."""
    r = ce.resolver_cabeceras(LIBRO_REAL).resueltos
    assert r["test_date"] == "D" and r["module_date"] == "J" and r["dashboard_date"] == "Q"
    assert r["module_part_number"] == "G" and r["dashboard_part_number"] == "O"
    assert r["engineering_level"] == "K" and r["dashboard_engineering_level"] == "R"
    assert r["inflator_supplier"] == "N" and r["dashboard_supplier"] == "T"
    assert r["module_serial_number"] == "I" and r["dashboard_serial_number"] == "P"


def test_los_tiempos_se_nombran_sin_afirmar_de_mas(ce):
    """X es el tiempo de apertura (cuando se ve el cambio en el tablero) y Z el inflado
    total, según el usuario. Y se titula 'FORVIA' y **no se sabe qué mide**: las
    fórmulas de las filas 20-31 la promedian, pero eso no dice qué es. Se deja con un
    nombre neutro y no se rellena (carril de tiempos, diferido).

    Corrección de P03-R01: allí se afirmó que Y era el tiempo de apertura. No hay
    evidencia de eso. Se retira la afirmación."""
    r = ce.resolver_cabeceras(LIBRO_REAL).resueltos
    assert r["forvia_measurement_ms"] == "Y"      # nombre neutro: no afirma qué mide
    assert r["opening_time_ms"] == "X"            # apertura: cambio visible en el tablero
    assert r["full_inflation_time_ms"] == "Z"     # inflado total


def test_el_bloque_de_danos_se_reconoce_y_no_se_escribe(ce):
    informe = ce.resolver_cabeceras(LIBRO_REAL)
    danos = {e.columna: e.clave for e in informe.encabezados if e.estado == "dano"}
    assert len(danos) == 21
    assert danos["AI"] == "housing_sidewall_stress_whitening"
    assert danos["AJ"] == "housing_inner_stress_whitening"
    assert danos["AX"] == "dano_ax"       # sin número, pero es del bloque
    assert danos["BC"] == "dano_bc"
    from openpyxl import Workbook
    hoja = Workbook().active
    for letra, texto in LIBRO_REAL.items():
        hoja[f"{letra}7"] = texto
    hoja["C8"] = "222504"
    resultado = ce.escribir_valores(hoja, 8, {"housing_sidewall_stress_whitening": "x"}, informe)
    assert hoja["AI8"].value is None
    assert resultado["escritos"] == []


def test_la_ss_alema_no_se_pierde_al_normalizar(ce):
    """'Weißbruch' se normaliza a 'weissbruch'; sin esto, la ß desaparece y el
    encabezado del libro no coincide con el catálogo."""
    assert "weissbruch" in ce.normalizar_encabezado("15) Weißbruch in Seitewand der Gehäuse")
    assert ce.normalizar_encabezado("Weiß") == "weiss"


def test_inflador_se_corrige_solo_si_el_catalogo_cerrado_no_deja_duda(ce):
    """El diagrama real del caso 222521 se leyó 'OGE'; el libro dice OGL."""
    import flujo_empresarial as fe

    def inflador(texto):
        return [c for c in fe.extraer_candidatos_texto(texto, {"confianza_ocr": 0.9}, {})
                if c["clave"] == "inflator_type"]

    corregido = inflador("VW316/5 222521 RdW NT OGE")
    assert [(c["valor_normalizado"], c["requiere_confirmacion_manual"]) for c in corregido] == [("OGL", True)]
    assert "OGE" in corregido[0]["observacion"]

    # a una letra de DOS valores del catálogo -> no se propone nada
    assert inflador("0GL") == []
    # palabras que no son del catálogo no se tocan
    assert inflador("BMG") == [] and inflador("VWU") == []
    # el valor exacto nunca se marca para confirmación
    assert [(c["valor_normalizado"], c["requiere_confirmacion_manual"]) for c in inflador("RdW HT OGL")] == [("OGL", False)]
    # el propio número de caso no se confunde con un inflador
    assert inflador("222521") == []
