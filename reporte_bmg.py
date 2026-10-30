"""Generador del reporte BMG 1ST + 2ST basado en la plantilla de validación.

Mantiene el aspecto del libro de referencia (Resumen / Versuchsmatrix) y usa
los campos consolidados del flujo empresarial. La matriz del resumen muestra
el estado del tiempo de apertura con el MISMO motor de reglas que el dashboard
(``utilidades.matriz_apertura``): verde ≤ V, amarillo > V y ≤ A, rojo > A y
gris con motivo para valores no confiables o pendientes. V15.9 dibuja todas
las posiciones esperadas: las vacantes llevan relleno gris tenue y nunca se
inventan IDs ni tiempos.
"""

from __future__ import annotations

import copy
import json
import math
import os
import time
from pathlib import Path
from typing import Iterable

from openpyxl import load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from configuracion import evaluar_criterio
from flujo_empresarial import CLAVES_PLANTILLA
from utilidades.encabezados_institucionales import textos_institucionales
from utilidades.matriz_apertura import (
    COLUMNAS_MATRIZ,
    celda_caso,
    criterio_desde_limites,
    evaluar_apertura,
    limites_desde_criterio,
    validar_limites,
)

HOJA_RESUMEN = "Übersicht Standversuche"
HOJA_LISTA = "Versuchsmatrix"
HOJA_RANGOS = "Rangos"
FILA_1ST_INICIO = 8
FILA_1ST_FIN = 57
FILA_2ST_INICIO = 58
FILA_2ST_FIN = 107

# Orden de la lista detallada en el archivo de referencia.
ORDEN_LISTA = {
    ("NT", "NOM"): 0,
    ("NT", "OGL"): 1,
    ("NT", "UGL"): 2,
    ("HT", "NOM"): 3,
    ("HT", "OGL"): 4,
    ("HT", "UGL"): 5,
    ("RT", "NOM"): 6,
}

# Orden visual de la matriz resumen (izquierda -> derecha) y cantidades
# esperadas: definición única en utilidades.matriz_apertura (compartida con el
# dashboard). ``col`` conserva la letra de columna de la plantilla BMG.

# Gris tenue para posiciones esperadas SIN caso: se distingue del gris de
# "valor no confiable" (gris estándar de la paleta) por relleno y por comentario.
COLOR_VACANTE = "#D9D9D9"

MOTIVOS_GRIS = {
    "sin_tiempo": {"es": "Sin tiempo medido", "en": "No measured time",
                   "de": "Keine gemessene Zeit"},
    "pendiente_revision": {"es": "Pendiente de revisión", "en": "Pending review",
                           "de": "Prüfung ausstehend"},
    "conflicto": {"es": "Conflicto entre fuentes", "en": "Conflict between sources",
                  "de": "Widerspruch zwischen Quellen"},
    "valor_no_finito": {"es": "Valor no finito descartado", "en": "Non-finite value discarded",
                        "de": "Unendlicher Wert verworfen"},
    "valor_negativo": {"es": "Valor negativo descartado", "en": "Negative value discarded",
                       "de": "Negativer Wert verworfen"},
    "valor_no_positivo": {"es": "Tiempo final debe ser > 0", "en": "Final time must be > 0",
                           "de": "Endzeit muss > 0 sein"},
    "no_positivo": {"es": "Tiempo final debe ser > 0", "en": "Final time must be > 0",
                     "de": "Endzeit muss > 0 sein"},
    "no_finito": {"es": "Tiempo final no finito descartado", "en": "Non-finite final time discarded",
                  "de": "Nicht endliche Endzeit verworfen"},
    "no_interpretable": {"es": "Tiempo final no interpretable", "en": "Final time not interpretable",
                          "de": "Endzeit nicht interpretierbar"},
    "referencia_invalida": {"es": "Referencia temporal inválida", "en": "Invalid time reference",
                             "de": "Ungültige Zeitreferenz"},
    "sin_medicion": {"es": "Sin medición", "en": "No measurement", "de": "Keine Messung"},
    "sin_caso": {"es": "Posición esperada sin caso asignado",
                 "en": "Expected position without assigned case",
                 "de": "Erwartete Position ohne zugeordneten Fall"},
}


TEXTOS = {
    "es": {"overview":"Resumen de resultados","opening":"Tiempo de apertura","expected":"Cantidad esperada","found":"Encontrada","processed":"Procesada","unclassified":"Casos sin clasificación de matriz","unknown":"Desconocido / pendiente","state":"Estado","trace":"Trazabilidad","dictionary":"Diccionario de datos","project":"Proyecto","stage":"Etapa","case":"Caso","component":"Componente","field":"Campo","image":"Imagen","region":"Región original","original":"Texto OCR original","corrected":"Texto corregido","orientation":"Orientación","rule":"Regla","source":"Fuente","version":"Versión de procesamiento","header":"Encabezado","origin_rule":"Origen / regla","status":"Estado de fuente","pending":"Pendiente de fuente o confirmación manual","test_temperature":"Temperatura de prueba","generator_type":"Tipo de generador","ok_test":"OK Test","ma_test":"m.A. Test","nio_test":"N.i.O Test"},
    "en": {"overview":"Overview results","opening":"Opening time","expected":"Expected quantity","found":"Found","processed":"Processed","unclassified":"Cases outside matrix classification","unknown":"Unknown / pending","state":"State","trace":"Traceability","dictionary":"Data dictionary","project":"Project","stage":"Stage","case":"Case","component":"Component","field":"Field","image":"Image","region":"Original region","original":"Original OCR text","corrected":"Corrected text","orientation":"Orientation","rule":"Rule","source":"Source","version":"Processing version","header":"Header","origin_rule":"Origin / rule","status":"Source status","pending":"Pending source or manual confirmation","test_temperature":"Test temperature","generator_type":"Generator type","ok_test":"OK test","ma_test":"Conditional test","nio_test":"NOK test"},
    "de": {"overview":"Übersicht Ergebnisse","opening":"Öffnungszeit","expected":"Erwartete Anzahl","found":"Gefunden","processed":"Verarbeitet","unclassified":"Fälle außerhalb der Matrixklassifikation","unknown":"Unbekannt / ausstehend","state":"Status","trace":"Rückverfolgbarkeit","dictionary":"Datenwörterbuch","project":"Projekt","stage":"Stufe","case":"Fall","component":"Komponente","field":"Feld","image":"Bild","region":"Originalbereich","original":"Original OCR-Text","corrected":"Korrigierter Text","orientation":"Orientierung","rule":"Regel","source":"Quelle","version":"Verarbeitungsversion","header":"Überschrift","origin_rule":"Quelle / Regel","status":"Quellenstatus","pending":"Quelle oder manuelle Bestätigung ausstehend","test_temperature":"Prüftemperatur","generator_type":"Generatortyp","ok_test":"OK Test","ma_test":"m.A. Test","nio_test":"N.i.O Test"},
}
# V15.9: leyenda ampliada con la posición vacante y los motivos del gris.
for _idioma, _extra in (
    ("es", {"vacant": "Vacante (posición esperada sin caso)",
            "reason": "Motivo", "criteria_origin": "Origen del criterio",
            "cause": "Causa", "count": "Casos"}),
    ("en", {"vacant": "Vacant (expected position without case)",
            "reason": "Reason", "criteria_origin": "Criteria origin",
            "cause": "Cause", "count": "Cases"}),
    ("de", {"vacant": "Frei (erwartete Position ohne Fall)",
            "reason": "Grund", "criteria_origin": "Ursprung der Kriterien",
            "cause": "Ursache", "count": "Fälle"}),
):
    TEXTOS[_idioma].update(_extra)

HEADERS = {
    "week":{"es":"Semana","en":"Week","de":"Woche"},
    "test_reason":{"es":"Motivo de prueba","en":"Test reason","de":"Prüfgrund"},
    "test_number":{"es":"Número de prueba","en":"Test number","de":"Versuchsnummer"},
    "test_date":{"es":"Fecha de prueba","en":"Test date","de":"Testdatum"},
    "test_place":{"es":"Lugar de prueba","en":"Test location","de":"Prüfort"},
    "temperature_condition":{"es":"Temperatura","en":"Temperature","de":"Temperatur"},
    "module_part_number":{"es":"PAB · Número de parte","en":"PAB · Part number","de":"PAB · Teilnummer"},
    "module_version":{"es":"PAB · Variante","en":"PAB · Variant","de":"PAB · Variante"},
    "module_serial_number":{"es":"PAB · Serie","en":"PAB · Serial","de":"PAB · Seriennummer"},
    "module_date":{"es":"PAB · Fecha fabricación","en":"PAB · Manufacturing date","de":"PAB · Fertigungsdatum"},
    "engineering_level":{"es":"PAB · Nivel de ingeniería","en":"PAB · Engineering level","de":"PAB · Entwicklungsstand"},
    "delay_ms":{"es":"Delay ms","en":"Delay ms","de":"Delay ms"},
    "inflator_type":{"es":"Tipo de generador","en":"Inflator type","de":"Generatortyp"},
    "inflator_supplier":{"es":"Proveedor de generador","en":"Inflator supplier","de":"Generatorlieferant"},
    "dashboard_part_number":{"es":"Tablero · Número de parte","en":"Dashboard · Part number","de":"I-Tafel · Teilnummer"},
    "dashboard_serial_number":{"es":"Tablero · Serie","en":"Dashboard · Serial","de":"I-Tafel · Seriennummer"},
    "dashboard_date":{"es":"Tablero · Fecha fabricación","en":"Dashboard · Manufacturing date","de":"I-Tafel · Fertigungsdatum"},
    "dashboard_engineering_level":{"es":"Tablero · Nivel de ingeniería","en":"Dashboard · Engineering level","de":"I-Tafel · Entwicklungsstand"},
    "laser_opening":{"es":"Apertura láser","en":"Laser opening","de":"Laseröffnung"},
    "dashboard_supplier":{"es":"Proveedor de tablero","en":"Dashboard supplier","de":"I-Tafel-Lieferant"},
    "cushion_evaluation":{"es":"Evaluación cushion","en":"Cushion evaluation","de":"Cushion-Bewertung"},
    "housing_evaluation":{"es":"Evaluación housing","en":"Housing evaluation","de":"Housing-Bewertung"},
    "protective_cover_evaluation":{"es":"Evaluación cubierta protectora","en":"Protective cover evaluation","de":"Schutzabdeckungs-Bewertung"},
    "opening_time_ms":{"es":"Tiempo apertura ms","en":"Opening time ms","de":"Öffnungszeit ms"},
    "forvia_measurement_ms":{"es":"Medición FORVIA ms","en":"FORVIA measurement ms","de":"FORVIA-Messung ms"},
    "full_inflation_time_ms":{"es":"Inflado completo ms","en":"Full inflation time ms","de":"Aufblaszeit ms"},
    "second_review":{"es":"Segunda revisión","en":"Second review","de":"Zweite Prüfung"},
    "pab_comments":{"es":"Comentarios PAB","en":"PAB comments","de":"PAB-Kommentare"},
    "pab_zsb_evaluation":{"es":"Evaluación PAB ZSB","en":"PAB ZSB evaluation","de":"PAB-ZSB-Bewertung"},
    "dashboard_comments":{"es":"Comentarios tablero","en":"Dashboard comments","de":"I-Tafel-Kommentare"},
    "dashboard_zsb_evaluation":{"es":"Evaluación tablero ZSB","en":"Dashboard ZSB evaluation","de":"I-Tafel-ZSB-Bewertung"},
    "test_environment_comments":{"es":"Comentarios entorno de prueba","en":"Test environment comments","de":"Kommentare zur Prüfumgebung"},
    "overall_system_evaluation":{"es":"Evaluación general del sistema","en":"Overall system evaluation","de":"Gesamtbewertung System"},
    "reserved_ah":{"es":"Reservado AH","en":"Reserved AH","de":"Reserviert AH"},
    "housing_sidewall_stress_whitening":{"es":"Blanqueamiento lateral del housing","en":"Housing sidewall stress whitening","de":"Spannungsaufhellung Housing-Seitenwand"},
    "housing_inner_stress_whitening":{"es":"Blanqueamiento interior del housing","en":"Housing inner stress whitening","de":"Spannungsaufhellung Housing innen"},
}

# Se amplía a la derecha del contrato histórico A:AJ, sin reutilizar la
# casilla FULL INFLATION para un evento visual distinto.
COLUMNAS_MAXIMO_VIDEO = ("maximum_visible_deployment_ms", "maximum_deployment_review")
HEADERS.update({
    "maximum_visible_deployment_ms": {
        "es": "Máximo despliegue visible de la bolsa ms",
        "en": "Maximum visible bag deployment ms",
        "de": "Maximale sichtbare Entfaltung des Airbags ms",
    },
    "maximum_deployment_review": {
        "es": "Revisión del máximo despliegue", "en": "Maximum deployment review",
        "de": "Prüfung der maximalen Entfaltung",
    },
})

TEXTOS_VIDEO = {
    "es": {
        "sheet": "Evidencia de tiempos de vídeo", "video": "Vídeo original", "camera": "Cámara",
        "fps": "FPS temporal utilizado", "fps_source": "Fuente de FPS", "zero": "Fotograma cero",
        "initial_ms": "Timestamp inicial ms", "opening_frame": "Fotograma de apertura",
        "opening_ms": "Apertura ms", "opening_review": "Revisión de apertura", "no_event": "Sin apertura (revisión manual)",
        "opening_source": "Fuente de tiempo de apertura", "opening_resolution": "Resolución de apertura ms",
        "maximum_frame": "Fotograma de máximo despliegue visible", "maximum_ms": "Máximo despliegue visible ms",
        "resolution": "Resolución temporal ms", "source": "Fuente de tiempo del máximo",
        "opening_roi": "Región de apertura", "maximum_roi": "Región de bolsa / máximo",
        "review": "Revisión del máximo", "pending": "Pendiente de revisión", "confirmed": "Confirmado",
        "conflict": "Conflicto entre vídeos", "no_data": "Sin dato", "invalid": "Evidencia no válida",
        "confirmed_by": "Confirmado por", "confirmed_at": "Confirmado en", "warnings": "Advertencias", "method": "Método del máximo",
        "opening_raw": "Tiempo crudo de apertura ms", "opening_time_state": "Estado del tiempo de apertura",
        "opening_rejection": "Motivo de rechazo de apertura",
        "maximum_rule": "Máximo despliegue visible confirmado manualmente. Entre vídeos confirmados se usa el mayor tiempo si coinciden dentro de un fotograma; si discrepan queda vacío. Separado de apertura e inflado completo.",
    },
    "en": {
        "sheet": "Video timing evidence", "video": "Original video", "camera": "Camera",
        "fps": "Timing FPS used", "fps_source": "FPS source", "zero": "Zero frame",
        "initial_ms": "Initial timestamp ms", "opening_frame": "Opening frame",
        "opening_ms": "Opening ms", "opening_review": "Opening review", "no_event": "No opening (manual review)",
        "opening_source": "Opening timing source", "opening_resolution": "Opening resolution ms",
        "maximum_frame": "Maximum visible deployment frame", "maximum_ms": "Maximum visible deployment ms",
        "resolution": "Temporal resolution ms", "source": "Maximum timing source",
        "opening_roi": "Opening region", "maximum_roi": "Bag / maximum region",
        "review": "Maximum review", "pending": "Pending review", "confirmed": "Confirmed",
        "conflict": "Conflict between videos", "no_data": "No data", "invalid": "Invalid evidence",
        "confirmed_by": "Confirmed by", "confirmed_at": "Confirmed at", "warnings": "Warnings", "method": "Maximum method",
        "opening_raw": "Raw opening time ms", "opening_time_state": "Opening time state",
        "opening_rejection": "Opening rejection reason",
        "maximum_rule": "Manually confirmed maximum visible deployment. Among confirmed videos, the latest time is used if times agree within one frame; disagreement leaves the field blank. Separate from opening and full inflation.",
    },
    "de": {
        "sheet": "Video-Zeitnachweise", "video": "Originalvideo", "camera": "Kamera",
        "fps": "Verwendete Zeitbasis-FPS", "fps_source": "FPS-Quelle", "zero": "Nullbild",
        "initial_ms": "Anfangszeitstempel ms", "opening_frame": "Öffnungsbild",
        "opening_ms": "Öffnung ms", "opening_review": "Öffnungsprüfung", "no_event": "Keine Öffnung (manuell geprüft)",
        "opening_source": "Zeitquelle der Öffnung", "opening_resolution": "Zeitauflösung der Öffnung ms",
        "maximum_frame": "Bild der maximalen sichtbaren Entfaltung", "maximum_ms": "Maximale sichtbare Entfaltung ms",
        "resolution": "Zeitauflösung ms", "source": "Zeitquelle des Maximums",
        "opening_roi": "Öffnungsbereich", "maximum_roi": "Airbag- / Maximalbereich",
        "review": "Prüfung des Maximums", "pending": "Prüfung ausstehend", "confirmed": "Bestätigt",
        "conflict": "Widerspruch zwischen Videos", "no_data": "Keine Angabe", "invalid": "Ungültiger Nachweis",
        "confirmed_by": "Bestätigt durch", "confirmed_at": "Bestätigt am", "warnings": "Hinweise", "method": "Methode des Maximums",
        "opening_raw": "Rohzeit der Öffnung ms", "opening_time_state": "Status der Öffnungszeit",
        "opening_rejection": "Ablehnungsgrund der Öffnung",
        "maximum_rule": "Manuell bestätigte maximale sichtbare Entfaltung. Unter bestätigten Videos wird die späteste Zeit übernommen, wenn sie innerhalb eines Bildes übereinstimmen; sonst bleibt das Feld leer. Getrennt von Öffnung und vollständiger Aufblasung.",
    },
}


def _tv(idioma: str, clave: str) -> str:
    return TEXTOS_VIDEO.get(idioma, TEXTOS_VIDEO["es"])[clave]

REGLAS_ORIGEN = {
    "week": "Sólo perfil EDAG: WW del número de prueba WWYYNN, corroborado con la fecha. No aplicar esa codificación a otros laboratorios.",
    "test_reason": "Proyecto o pizarra explícitos o confirmación manual; no inferir desde códigos de piezas.",
    "test_number": "Carpeta madre; contrastar con pizarra y overlay si existen. Corroborar todas las etiquetas, sin prioridad ciega.",
    "test_date": "Fecha de prueba explícita o confirmación manual; separada de fabricación.",
    "test_place": "EDAG Testlab explícito en overlay o laboratorio VW con prueba prefijada VW. El fabricante VW AG en una etiqueta no identifica el laboratorio.",
    "temperature_condition": "Catálogo HT/RT/NT en ruta, pizarra, etiqueta o confirmación manual.",
    "module_part_number": "Etiqueta de bolsa/QR/confirmación manual; no completar desde ejemplos.",
    "module_version": "RDW/NAR y alias explícitos; las letras finales siguen siendo significativas.",
    "module_serial_number": "Etiqueta de bolsa o confirmación manual; conservar letras, espacios, asteriscos y ceros iniciales.",
    "module_date": "Fecha de fabricación del módulo; conservar impreso e interpretación. DMY sólo con perfil indicado; distintas fechas entre etiquetas quedan en conflicto.",
    "dashboard_part_number": "Etiqueta del tablero/QR/confirmación manual; no completar desde ejemplos.",
    "dashboard_serial_number": "Etiqueta del tablero o confirmación manual; conservar letras, espacios, asteriscos y ceros iniciales.",
    "dashboard_date": "Fecha de fabricación del tablero; conservar impreso e interpretación. DMY sólo con perfil indicado; distintas fechas entre etiquetas quedan en conflicto.",
    "engineering_level": "Nivel del módulo o prototipo en etiqueta/pizarra con componente identificado; conservar letras. Los ejemplos 02S/69K no son predeterminados.",
    "dashboard_engineering_level": "Nivel del tablero en su etiqueta o confirmación manual. El ejemplo 03S no es predeterminado.",
    "delay_ms": "DELAY explícito con contexto de los pasos de disparo; no inferir desde otro tiempo.",
    "inflator_type": "Catálogo NOM/OGL/UGL por evidencia explícita o confirmación manual.",
    "inflator_supplier": "Proveedor explícito en la etiqueta del módulo, por ejemplo Autoliv; no completar desde ejemplos.",
    "laser_opening": "Apertura láser u homologación explícita; no inferir desde el número de parte.",
    "dashboard_supplier": "Proveedor explícito del tablero o confirmación manual; separado del proveedor del módulo.",
    "opening_time_ms": "Primera ruptura visible del tablero, no su abombamiento previo: fotograma y tiempo corroborados por vídeo o confirmación manual. Resolución física según FPS/timestamp; candidatos por revisar no se presentan como seguros.",
    "full_inflation_time_ms": "Campo histórico FULL INFLATION/AUFBLASZEIT o captura manual; no sustituir por apertura ni por máximo despliegue visible.",
    "forvia_measurement_ms": "Sólo medición FORVIA explícita o captura manual; no usar como apertura.",
}

REGLAS_ORIGEN_EN = {
    "week": "EDAG profile only: WW from the WWYYNN test number, corroborated with the date. Do not apply this encoding to other laboratories.",
    "test_reason": "Explicit project/slate or manual confirmation; do not infer from part codes.",
    "test_number": "Parent folder; cross-check with the slate and overlay when available. Corroborate all labels without blind priority.",
    "test_date": "Explicit test date or manual confirmation; separate from manufacturing dates.",
    "test_place": "Explicit EDAG Testlab overlay or VW laboratory with a VW-prefixed test. A VW AG manufacturer label does not identify the test laboratory.",
    "temperature_condition": "HT/RT/NT catalog from path, slate, label or manual confirmation.",
    "module_part_number": "Airbag label/QR/manual confirmation; never fill from examples.",
    "module_version": "Explicit RDW/NAR variant evidence; final letters remain significant.",
    "module_serial_number": "Airbag label or manual confirmation; preserve letters, spaces, asterisks and leading zeros.",
    "module_date": "Module manufacturing date; preserve print and interpretation. DMY only with an indicated profile; different label dates remain conflicting.",
    "dashboard_part_number": "Dashboard label/QR/manual confirmation; never fill from examples.",
    "dashboard_serial_number": "Dashboard label or manual confirmation; preserve letters, spaces, asterisks and leading zeros.",
    "dashboard_date": "Dashboard manufacturing date; preserve print and interpretation. DMY only with an indicated profile; different label dates remain conflicting.",
    "engineering_level": "Module/prototype engineering level from a component-identified label/slate; preserve letters. Examples 02S/69K are not defaults.",
    "dashboard_engineering_level": "Dashboard level from its label or manual confirmation. Example 03S is not a default.",
    "delay_ms": "Explicit DELAY with firing-step context; never infer from another timing value.",
    "inflator_type": "NOM/OGL/UGL catalog from explicit evidence or manual confirmation.",
    "inflator_supplier": "Explicit module-label supplier, such as Autoliv; never fill from examples.",
    "laser_opening": "Explicit laser-opening/homologation evidence; never infer from the part number.",
    "dashboard_supplier": "Explicit dashboard supplier or manual confirmation; separate from the module supplier.",
    "opening_time_ms": "First visible dashboard rupture, not prior bulging: video-corroborated frame/time or manual confirmation. Physical resolution depends on FPS/timestamp; pending candidates are not presented as certain.",
    "full_inflation_time_ms": "Historical FULL INFLATION/AUFBLASZEIT or manual entry; do not replace with opening or maximum visible deployment.",
    "forvia_measurement_ms": "Only explicit FORVIA measurement or manual entry; never use as opening time.",
}
REGLAS_ORIGEN_DE = {
    "week": "Nur EDAG-Profil: WW aus der Prüfnummer WWYYNN, mit dem Datum abgleichen. Diese Codierung nicht auf andere Labore übertragen.",
    "test_reason": "Explizites Projekt/Tafel oder manuelle Bestätigung; nicht aus Teilecodes ableiten.",
    "test_number": "Übergeordneter Ordner; mit Tafel und Einblendung abgleichen. Alle Etiketten ohne pauschalen Vorrang abgleichen.",
    "test_date": "Explizites Prüfdatum oder manuelle Bestätigung; getrennt vom Fertigungsdatum.",
    "test_place": "Explizite EDAG-Testlab-Einblendung oder VW-Labor mit VW-Prüfpräfix. Ein VW-AG-Herstelleretikett bezeichnet nicht das Prüflabor.",
    "temperature_condition": "HT/RT/NT aus Pfad, Tafel, Etikett oder manueller Bestätigung.",
    "module_part_number": "Airbag-Etikett/QR/manuelle Bestätigung; niemals aus Beispielen ergänzen.",
    "module_version": "Explizite RDW/NAR-Variante; Endbuchstaben bleiben bedeutend.",
    "module_serial_number": "Airbag-Etikett oder manuelle Bestätigung; Buchstaben, Leerzeichen, Sternchen und führende Nullen erhalten.",
    "module_date": "Fertigungsdatum des Moduls; Druckwert und Interpretation erhalten. DMY nur bei angegebenem Profil; unterschiedliche Etikettdaten bleiben widersprüchlich.",
    "dashboard_part_number": "I-Tafel-Etikett/QR/manuelle Bestätigung; niemals aus Beispielen ergänzen.",
    "dashboard_serial_number": "I-Tafel-Etikett oder manuelle Bestätigung; Buchstaben, Leerzeichen, Sternchen und führende Nullen erhalten.",
    "dashboard_date": "Fertigungsdatum der I-Tafel; Druckwert und Interpretation erhalten. DMY nur bei angegebenem Profil; unterschiedliche Etikettdaten bleiben widersprüchlich.",
    "engineering_level": "Modul-/Prototypstand aus eindeutig zugeordneter Tafel/Etikett; Buchstaben erhalten. Beispiele 02S/69K sind keine Standardwerte.",
    "dashboard_engineering_level": "I-Tafel-Stand aus deren Etikett oder manueller Bestätigung. Beispiel 03S ist kein Standardwert.",
    "delay_ms": "Explizites DELAY mit Kontext der Zündschritte; nicht aus einer anderen Zeit ableiten.",
    "inflator_type": "NOM/OGL/UGL aus explizitem Nachweis oder manueller Bestätigung.",
    "inflator_supplier": "Expliziter Lieferant auf dem Moduletikett, etwa Autoliv; nicht aus Beispielen ergänzen.",
    "laser_opening": "Expliziter Nachweis der Laseröffnung/Homologation; nicht aus der Teilnummer ableiten.",
    "dashboard_supplier": "Expliziter I-Tafel-Lieferant oder manuelle Bestätigung; getrennt vom Modullieferanten.",
    "opening_time_ms": "Erster sichtbarer Riss der I-Tafel, nicht die vorherige Wölbung: durch Video bestätigtes Bild/Zeit oder manuelle Bestätigung. Physikalische Auflösung nach FPS/Zeitstempel; ausstehende Kandidaten gelten nicht als sicher.",
    "full_inflation_time_ms": "Bisheriges FULL INFLATION/AUFBLASZEIT oder manuelle Eingabe; nicht durch Öffnung oder maximale sichtbare Entfaltung ersetzen.",
    "forvia_measurement_ms": "Nur explizite FORVIA-Messung oder manuelle Eingabe; nicht als Öffnungszeit verwenden.",
}

def _regla_origen(clave: str, idioma: str = "es") -> tuple[str, str]:
    mapas = {"es": REGLAS_ORIGEN, "en": REGLAS_ORIGEN_EN, "de": REGLAS_ORIGEN_DE}
    mapa = mapas.get(idioma, REGLAS_ORIGEN)
    if clave in mapa:
        estado = {"es":"definida","en":"defined","de":"definiert"}.get(idioma,"definida")
        return mapa[clave], estado
    pendientes = {
        "es": "Fuente por definir o confirmación manual; el sistema no inventa el valor.",
        "en": "Source still to be defined or manually confirmed; the system does not invent the value.",
        "de": "Quelle noch zu definieren oder manuell zu bestätigen; das System erfindet keinen Wert.",
    }
    estado = {"es":"pendiente","en":"pending","de":"ausstehend"}.get(idioma,"pendiente")
    return pendientes.get(idioma, pendientes["es"]), estado


def _t(idioma: str, clave: str) -> str:
    return TEXTOS.get(idioma, TEXTOS["es"]).get(clave, clave)

def _identidad(resultado: dict) -> str:
    return str(resultado.get("case_key") or resultado.get("id") or f"{resultado.get('project_id')}|{resultado.get('tipo_st')}|{_campo(resultado,'test_number')}")


def _campo(resultado: dict, clave: str):
    dato = (resultado.get("campos") or {}).get(clave)
    if isinstance(dato, dict):
        return dato.get("valor")
    if dato not in (None, ""):
        return dato
    if clave in resultado:
        return resultado.get(clave)
    return (resultado.get("metadata_ruta") or {}).get(clave)


def _campo_confiable(resultado: dict, clave: str):
    dato = (resultado.get("campos") or {}).get(clave)
    if isinstance(dato, dict):
        if dato.get("requiere_revision") or dato.get("estado") in {"conflicto", "pendiente_revision"}:
            return None
        return dato.get("valor")
    return dato


def _numero(valor):
    if isinstance(valor, bool) or valor in (None, "", "--", "-"):
        return None
    try:
        numero = float(str(valor).strip().replace(",", ".").replace(" ms", "").replace("ms", ""))
        return numero if math.isfinite(numero) else None
    except (TypeError, ValueError):
        return None


def _tiempo_ms(valor):
    numero = _numero(valor)
    return numero if numero is not None and numero >= 0 else None


def _tiempo_apertura_final(valor):
    numero = _numero(valor)
    return numero if numero is not None and numero > 0 else None


def _tiempo_crudo_finito(valor):
    """Tiempo de evidencia con signo; nunca usar como apertura publicable."""
    return _numero(valor)


def _raw_tiempo_excel(valor):
    """Raw de auditoría firmado; no finitos/ilegibles se guardan como texto."""
    numero = _tiempo_crudo_finito(valor)
    if numero is not None:
        return numero
    return None if valor is None else str(valor)


def _frame_valido(valor):
    numero = _tiempo_ms(valor)
    return int(numero) if numero is not None and numero.is_integer() else None


def _datos_maximo(video: dict) -> dict:
    dato = video.get("despliegue_maximo")
    return dato if isinstance(dato, dict) else {}


def _maximo_confirmado(dato: dict) -> bool:
    return (dato.get("estado") == "confirmado" and not dato.get("requiere_revision", True)
            and _tiempo_ms(dato.get("tiempo_ms")) is not None
            and _frame_valido(dato.get("frame_index")) is not None)


def _maximo_invalidado(dato: dict) -> bool:
    """Una confirmación caducada no puede desaparecer del consolidado."""
    estados_invalidacion = {
        "revisar_apertura", "revisar_orden_temporal", "revisar_origen_temporal", "archivo_modificado",
    }
    return (dato.get("estado") in estados_invalidacion
            or dato.get("estado") == "confirmado" and not _maximo_confirmado(dato))


def _resolucion_maximo(video: dict) -> float | None:
    dato = _datos_maximo(video)
    resolucion = _tiempo_ms(dato.get("resolucion_nativa_ms"))
    if resolucion is not None and resolucion > 0:
        return resolucion
    fps = _numero(dato.get("fps"))
    if fps is not None and fps > 0:
        return 1000.0 / fps
    resolucion = _tiempo_ms(video.get("resolucion_nativa_ms"))
    return resolucion if resolucion is not None and resolucion > 0 else None


def _resumen_maximo(resultado: dict) -> tuple[float | None, str]:
    """Sólo publica confirmaciones compatibles; conserva propuestas en evidencia."""
    videos = [v for v in (resultado.get("videos") or []) if isinstance(v, dict)]
    confirmados = [v for v in videos if _maximo_confirmado(_datos_maximo(v))]
    invalidos = [v for v in videos if _maximo_invalidado(_datos_maximo(v))]
    if invalidos:
        return None, "pending"
    if not confirmados:
        pendiente = any(_datos_maximo(v).get("estado") not in {None, "sin_datos"} for v in videos)
        return None, "pending" if pendiente else "no_data"
    for i, video in enumerate(confirmados):
        for otro in confirmados[i + 1:]:
            tiempo = _tiempo_ms(_datos_maximo(video).get("tiempo_ms"))
            tiempo_otro = _tiempo_ms(_datos_maximo(otro).get("tiempo_ms"))
            resoluciones = (_resolucion_maximo(video), _resolucion_maximo(otro))
            # Sin resolución para ambos, sólo la igualdad exacta está respaldada.
            tolerancia = max(resoluciones) if all(r is not None for r in resoluciones) else 0.0
            if abs(tiempo - tiempo_otro) > tolerancia + 1e-9:
                return None, "conflict"
    return max(_tiempo_ms(_datos_maximo(v).get("tiempo_ms")) for v in confirmados), "confirmed"


def _test_sort(resultado: dict):
    valor = resultado.get("test_number") or _campo(resultado, "test_number") or resultado.get("identificador")
    try:
        return (0, int(str(valor).strip()))
    except (TypeError, ValueError):
        return (1, str(valor or ""))


def _ordenar_etapa(resultados: Iterable[dict]) -> list[dict]:
    return sorted(
        resultados,
        key=lambda r: (
            ORDEN_LISTA.get((str(r.get("temperature_condition") or _campo(r, "temperature_condition") or "").upper(),
                             str(r.get("inflator_type") or _campo(r, "inflator_type") or "").upper()), 99),
            _test_sort(r),
        ),
    )


def _estado_apertura(resultado: dict, reglas: dict) -> tuple[str, float | None]:
    """(estado, valor) del semáforo de apertura.

    V15.9 comparte el evaluador con el dashboard (``utilidades.matriz_apertura``);
    el contrato numérico se conserva: sin valor confiable se reporta (\"gris\", None).
    """
    dato = _campo_confiable_dict(resultado, "opening_time_ms")
    criterio = (reglas.get("criterios") or {}).get("tiempo_apertura_ms") or {
        "verde": "<= 6", "amarillo": "6-7", "rojo": "> 7"
    }
    estado, valor, motivo = evaluar_apertura(dato, criterio)
    if motivo in {"sin_tiempo", "pendiente_revision", "conflicto",
                  "valor_no_finito", "valor_negativo", "valor_no_positivo"}:
        return "gris", None
    return estado, valor


def _campo_confiable_dict(resultado: dict, clave: str):
    """El ``dato`` completo de ``campos`` (para distinguir motivos del gris) o None.

    Misma fuente que ``_campo_confiable``: sólo ``campos[clave]``; un valor
    plano se envuelve como ``{"valor": ...}`` para el evaluador compartido.
    """
    dato = (resultado.get("campos") or {}).get(clave)
    if isinstance(dato, dict):
        return dato
    if dato in (None, ""):
        return None
    return {"valor": dato}


def _relleno(hex_color: str) -> PatternFill:
    return PatternFill("solid", fgColor=hex_color.lstrip("#"))


def _escribir_fila(hoja, fila: int, resultado: dict, idioma: str = "es") -> None:
    canonico = resultado.get("resultado_caso_canonico")
    if ("campos" in resultado or "videos" in resultado or "video_apertura" in resultado
            or not isinstance(canonico, dict)):
        from utilidades.resultado_caso import resolver_resultado_caso
        canonico = resolver_resultado_caso(resultado)
    apertura = (canonico.get("apertura") or {}) if isinstance(canonico, dict) else {}
    for indice, clave in enumerate(CLAVES_PLANTILLA, start=1):
        valor = _campo(resultado, clave)
        if clave == "opening_time_ms":
            # Sólo publica como dato de plantilla un tiempo confirmado por una
            # persona. Los consensos heurísticos quedan en «Apertura V15.10».
            valor = (apertura.get("tiempo_ms")
                     if apertura.get("estado") in {"VERIFICADO_HUMANO", "AUTO_VERIFICABLE"} else None)
        celda = hoja.cell(fila, indice)
        if clave in {"opening_time_ms", "forvia_measurement_ms", "full_inflation_time_ms", "delay_ms"}:
            valor = (_tiempo_apertura_final(valor) if clave == "opening_time_ms"
                     else _tiempo_ms(valor))
            celda.number_format = "0.000"
        celda.value = valor
    valor_maximo, estado = _resumen_maximo(resultado)
    columna = len(CLAVES_PLANTILLA) + 1
    hoja.cell(fila, columna).value = valor_maximo
    hoja.cell(fila, columna).number_format = "0.000"
    hoja.cell(fila, columna + 1).value = _tv(idioma, estado)
    if resultado.get("videos"):
        hoja.cell(fila, columna).comment = Comment(_tv(idioma, "maximum_rule"), "OCR vídeo")
    if estado in {"pending", "conflict"}:
        hoja.cell(fila, columna + 1).fill = _relleno("#FFD966")


def _limpiar_fila_datos(hoja, inicio: int = 8, fin: int = 107) -> None:
    for fila in range(inicio, fin + 1):
        for columna in range(1, 56):  # A:BC
            hoja.cell(fila, columna).value = None


def _copiar_estilo_fila(hoja, origen: int, destino: int, columnas: int = 55) -> None:
    hoja.row_dimensions[destino].height = hoja.row_dimensions[origen].height
    for c in range(1, columnas + 1):
        src, dst = hoja.cell(origen, c), hoja.cell(destino, c)
        if src.has_style:
            dst._style = copy.copy(src._style)
        dst.number_format = src.number_format
        dst.alignment = copy.copy(src.alignment)
        dst.protection = copy.copy(src.protection)


def _poblar_lista(hoja, resultados: list[dict], idioma: str = "es") -> dict[str, int]:
    """No recorta casos: conserva filas históricas y desplaza 2ST cuando hace falta."""
    estilo_1st = 8 if hoja.max_row >= 8 else 7
    estilo_2st = 58 if hoja.max_row >= 58 else estilo_1st
    for idx, clave in enumerate((*CLAVES_PLANTILLA, *COLUMNAS_MAXIMO_VIDEO), start=1):
        if idx > len(CLAVES_PLANTILLA):
            hoja.cell(7, idx)._style = copy.copy(hoja.cell(7, len(CLAVES_PLANTILLA))._style)
        hoja.cell(7, idx).value = HEADERS.get(clave, {}).get(idioma, clave)
        hoja.cell(7, idx).alignment = Alignment(wrap_text=True, vertical="center")
    g1 = _ordenar_etapa([r for r in resultados if str(r.get("tipo_st") or "").upper() == "1ST"])
    g2 = _ordenar_etapa([r for r in resultados if str(r.get("tipo_st") or "").upper() == "2ST"])
    gx = _ordenar_etapa([r for r in resultados if str(r.get("tipo_st") or "").upper() not in {"1ST","2ST"}])
    inicio1, inicio2 = 8, max(58, 8 + len(g1))
    iniciox = inicio2 + len(g2)
    ultimo = max(107, inicio1+len(g1)-1, inicio2+len(g2)-1, iniciox+len(gx)-1)
    for fila in range(8, max(hoja.max_row, ultimo)+1):
        for col in range(1, 56):
            celda=hoja.cell(fila,col); celda.value=None; celda.hyperlink=None; celda.comment=None
    mapa={}
    for grupo,inicio,estilo in ((g1,inicio1,estilo_1st),(g2,inicio2,estilo_2st),(gx,iniciox,estilo_1st)):
        for off, resultado in enumerate(grupo):
            fila=inicio+off; _copiar_estilo_fila(hoja, estilo, fila)
            _escribir_fila(hoja, fila, resultado, idioma)
            mapa[_identidad(resultado)] = fila
    hoja.freeze_panes="A8"
    hoja.auto_filter.ref=f"A7:{get_column_letter(len(CLAVES_PLANTILLA) + len(COLUMNAS_MAXIMO_VIDEO))}{max(7,ultimo)}"
    hoja.column_dimensions[get_column_letter(len(CLAVES_PLANTILLA) + 1)].width = 27
    hoja.column_dimensions[get_column_letter(len(CLAVES_PLANTILLA) + 2)].width = 26
    return mapa


def _copiar_lista_a_rangos(libro, resultados: list[dict], idioma: str = "es") -> None:
    if HOJA_RANGOS in libro.sheetnames:
        _poblar_lista(libro[HOJA_RANGOS], resultados, idioma)


def _limpiar_bloques_historicos_matriz(hoja) -> None:
    """Limpia IDs/colores de la matriz precargada de la plantilla institucional.

    La plantilla BMG trae ejemplos/histórico en D:J (1ST filas 7-16 y 2ST
    filas 33-42). Esos valores son formato de referencia, NO datos de la
    ejecución. Se limpian una sola vez antes de dibujar los casos actuales,
    conservando bordes, tamaños, merges y estilos estructurales.
    """
    for inicio, fin in ((7, 16), (33, 42)):
        for fila in range(inicio, fin + 1):
            for col in range(4, 11):
                celda = hoja.cell(fila, col)
                celda.value = None
                celda.hyperlink = None
                celda.comment = None
                celda.fill = PatternFill(fill_type=None)


def _aplicar_titulos_proyecto_institucionales(libro, identidad_proyecto: dict | None, idioma: str,
                                             resultados: list[dict] | None = None) -> None:
    """Proyecta identidad elegida + textos institucionales OCR/localizados.

    El proyecto sigue viniendo EXCLUSIVAMENTE de la selección del usuario. Los
    términos técnicos de cabecera se recuperan de OCR cuando existen y las
    palabras de presentación se localizan según ES/EN/DE.
    """
    if identidad_proyecto and not identidad_proyecto.get("sin_asignar"):
        from utilidades.identidad_excel import nombre_visible
        nombre = nombre_visible(identidad_proyecto, idioma)
        for hoja_nombre, coordenada in (
            (HOJA_RESUMEN, "A1"),
            (HOJA_LISTA, "A2"),
            (HOJA_RANGOS, "A2"),
        ):
            if hoja_nombre in libro.sheetnames:
                libro[hoja_nombre][coordenada].value = nombre

    info = textos_institucionales(resultados or [], idioma)
    if HOJA_RESUMEN in libro.sheetnames:
        ws = libro[HOJA_RESUMEN]
        ws["B3"] = info["linea_bmg"]
        ws["B4"] = info["linea_cop"]
        fuente_txt = (f"Fuente: {info.get('fuente')}; textos OCR: {info.get('fuentes_ocr', 0)}; "
                      f"programa VW: {info.get('programa_vw') or 'no observado'}; "
                      f"programa: {info.get('programa_x') or 'fallback'}")
        ws["B3"].comment = Comment(fuente_txt, "OCR encabezado")
        ws["B4"].comment = Comment(
            f"COP BFA observado en OCR: {'sí' if info.get('cop_bfa_observado') else 'no; texto institucional de fallback'}. "
            f"Idioma de presentación: {idioma}.", "OCR encabezado")
    # Fila de grupos de la tabla detallada: no dejar mezcla DE/EN/ES.
    grupos = info["grupos"]
    for hoja_nombre in (HOJA_LISTA, HOJA_RANGOS):
        if hoja_nombre not in libro.sheetnames:
            continue
        ws = libro[hoja_nombre]
        for celda, clave in (("C6","grupo_prueba"),("G6","grupo_pab"),
                             ("O6","grupo_panel_zsb"),("U6","grupo_sub"),
                             ("AI6","grupo_airbag"),("AO6","grupo_panel")):
            ws[celda] = grupos[clave]


def _poblar_matriz(hoja, tipo_st: str, resultados: list[dict], fila_inicio: int,
                   mapa_filas: dict[str, int], colores: dict, reglas: dict, idioma: str = "es") -> int:
    """Dibuja casos reales en la plantilla; la hoja aditiva lista cada caso sin cupos.

    V15.10 conserva el contrato visual BMG, pero ya no colorea ni etiqueta
    posiciones vacías como si fueran casos. El número esperado queda como
    metadato de referencia en el pie; sólo los IDs existentes ocupan celdas.
    """
    mapa_color={"verde":colores.get("verde","#00B050"),"amarillo":colores.get("amarillo","#FFD966"),"rojo":colores.get("rojo","#FF0000"),"gris":colores.get("gris","#A6A6A6")}
    criterio=(reglas.get("criterios") or {}).get("tiempo_apertura_ms") or {"verde":"<= 6","amarillo":"6-7","rojo":"> 7"}
    etapa=[r for r in resultados if str(r.get("tipo_st") or "").upper()==tipo_st]
    grupos=[]
    for spec in COLUMNAS_MATRIZ:
        grupo=[r for r in etapa if str(r.get("temperature_condition") or _campo(r,"temperature_condition") or "").upper()==spec["temperature_condition"] and str(r.get("inflator_type") or _campo(r,"inflator_type") or "").upper()==spec["inflator_type"]]
        grupos.append((spec,sorted(grupo,key=_test_sort,reverse=True)))
    # Altura por casos presentes, no por el cupo histórico de la plantilla.
    cupos={spec["id"]: len(grupo) for spec,grupo in grupos}
    alto=max(cupos.values(), default=0)

    # Replica estilos de la plantilla para filas añadidas dinámicamente.
    fuente_titulo = 6 if tipo_st == "1ST" else 32
    fuente_dato = 16 if tipo_st == "1ST" else 42
    fuente_pie = (17,18,19) if tipo_st == "1ST" else (43,44,45)
    if fila_inicio-1 != fuente_titulo:
        _copiar_estilo_fila(hoja, fuente_titulo, fila_inicio-1, columnas=10)
    hoja.cell(fila_inicio-1,2).value = f"{_t(idioma,'overview')} ({'1st' if tipo_st=='1ST' else '2st'})"
    for r in range(fila_inicio, fila_inicio+alto):
        if r not in range(7,17) and r not in range(33,43):
            _copiar_estilo_fila(hoja, fuente_dato, r, columnas=10)
        for col in range(2,11):
            c=hoja.cell(r,col); c.value=None; c.hyperlink=None; c.comment=None
            if col>=4: c.fill=PatternFill(fill_type=None)

    def _comentario_celda(celda):
        estado = celda.get("estado")
        tiempo = (celda.get("opening_time_ms") if estado != "gris"
                  else celda.get("tiempo_pendiente_ms"))
        motivo = celda.get("motivo_estado")
        razon = MOTIVOS_GRIS.get(motivo, MOTIVOS_GRIS["sin_tiempo"])[idioma if idioma in {"es","en","de"} else "es"]
        if celda.get("tiempo_es_estimado") and tiempo is not None:
            etiqueta_est = {
                "es": "Estimación automática de apertura (color calculado; publicación pendiente)",
                "en": "Automatic opening estimate (calculated color; publication pending)",
                "de": "Automatische Öffnungsschätzung (berechnete Farbe; Veröffentlichung ausstehend)",
            }.get(idioma, "Estimación automática de apertura")
            detalle = f"{etiqueta_est}: {tiempo:g} ms"
        else:
            detalle = (razon if tiempo is None else
                       f"{razon if estado == 'gris' else _t(idioma, 'opening')}: {tiempo:g} ms")
        lineas = [detalle, f"{_t(idioma, 'state')}: {estado}"]
        if estado == "gris" and celda.get("decision_apertura") in {"PROPUESTA", "CONFLICTO"}:
            pendiente_txt = {"es": "Pendiente de revisión", "en": "Pending review", "de": "Prüfung ausstehend"}.get(idioma, "Pendiente de revisión")
            if pendiente_txt not in lineas:
                lineas.append(pendiente_txt)
        if celda.get("decision_apertura"):
            lineas.append(f"Decisión: {celda['decision_apertura']}")
        if celda.get("estado_tiempo"):
            lineas.append(f"Estado temporal: {celda['estado_tiempo']}")
        if celda.get("motivo_rechazo"):
            lineas.append(f"Rechazo: {celda['motivo_rechazo']}")
        if celda.get("raw_time_ms") is not None:
            lineas.append(f"Tiempo crudo: {celda['raw_time_ms']} ms")
        if celda.get("fuente_evidencia"):
            lineas.append(f"Fuente: {celda['fuente_evidencia']}")
        if celda.get("color_fuente"):
            lineas.append(f"Fuente color: {celda['color_fuente']}")
        if celda.get("auto_color_soporte") is not None and celda.get("tiempo_es_estimado"):
            lineas.append(f"Soporte automático: {celda['auto_color_soporte']} video(s)")
        if celda.get("auto_color_score_max") is not None and celda.get("tiempo_es_estimado"):
            lineas.append(f"Evidencia visual máxima: {float(celda['auto_color_score_max']):.3f}")
        if celda.get("duracion_llenado_estimada_ms") is not None:
            etiqueta_llenado = {
                "es": "Duración de llenado visual estimada",
                "en": "Estimated visual filling duration",
                "de": "Geschätzte visuelle Fülldauer",
            }.get(idioma, "Duración de llenado visual estimada")
            lineas.append(f"{etiqueta_llenado}: {float(celda['duracion_llenado_estimada_ms']):.3f} ms")
        if celda.get("razones_apertura"):
            lineas.append("Evidencia: " + "; ".join(str(x) for x in celda["razones_apertura"]))
        return "\n".join(lineas)

    for spec,grupo in grupos:
        col_letra=spec["col"]
        arranque=fila_inicio
        for indice,resultado in enumerate(grupo):
            fila=arranque+indice; c=hoja[f"{col_letra}{fila}"]
            numero=resultado.get("test_number") or _campo(resultado,"test_number") or resultado.get("identificador")
            c.value=numero
            celda=celda_caso(resultado,criterio)
            estado=celda.get("estado","gris")
            c.fill=_relleno(mapa_color.get("gris","#A6A6A6") if estado=="gris" else mapa_color[estado])
            detalle=mapa_filas.get(_identidad(resultado))
            if detalle: c.hyperlink=f"#'{HOJA_LISTA}'!C{detalle}"
            c.comment=Comment(_comentario_celda(celda),"OCR Versuchsmatrix")

    pie=fila_inicio+alto
    # Conserva el pie visual de la plantilla y añade conteos reales separados de
    # la cantidad esperada para no presentar números predefinidos como resultados.
    for i,origen in enumerate(fuente_pie):
        destino=pie+i
        if destino != origen: _copiar_estilo_fila(hoja, origen, destino, columnas=10)
        for col in range(2,11): hoja.cell(destino,col).value=None
    hoja.cell(pie,2).value=_t(idioma,"expected")
    hoja.cell(pie+1,2).value=_t(idioma,"test_temperature")
    hoja.cell(pie+2,2).value=_t(idioma,"generator_type")
    fila_encontrada, fila_procesada = pie+3, pie+4
    _copiar_estilo_fila(hoja, fuente_pie[0], fila_encontrada, columnas=10)
    _copiar_estilo_fila(hoja, fuente_pie[0], fila_procesada, columnas=10)
    for col in range(2,11):
        hoja.cell(fila_encontrada,col).value=None
        hoja.cell(fila_procesada,col).value=None
    hoja.cell(fila_encontrada,2).value=_t(idioma,"found")
    hoja.cell(fila_procesada,2).value=_t(idioma,"processed")
    for spec, grupo in grupos:
        col=ord(spec["col"])-64
        hoja.cell(pie,col).value=spec["esperados"]
        temp={"HT":"+85°C","RT":"RT","NT":"-35°C"}.get(spec["temperature_condition"],spec["temperature_condition"])
        gen="nominal" if spec["inflator_type"]=="NOM" else spec["inflator_type"]
        hoja.cell(pie+1,col).value=temp
        hoja.cell(pie+2,col).value=gen
        hoja.cell(fila_encontrada,col).value=len(grupo)
        procesadas=sum(1 for r in grupo if str(r.get("estado") or r.get("estado_pipeline") or "").lower() not in {"error","fallido","pendiente"})
        hoja.cell(fila_procesada,col).value=procesadas

    # V15.9.1 (B3): los casos fuera de etapa/categorización ya no se dibujan
    # dentro de cada etapa; existe UN bloque único global («Sin clasificar»)
    # detrás del bloque 2ST, idéntico al del dashboard (paridad de IDs).
    return fila_procesada + 1


def _poblar_sin_clasificar(hoja, resultados: list[dict], fila_inicio: int,
                           mapa_filas: dict[str, int], colores: dict,
                           reglas: dict, idioma: str = "es") -> int:
    """V15.9.1 (B3): bloque único con TODOS los casos fuera de la matriz.

    Usa la MISMA agrupación que el dashboard (``agrupar_casos`` de
    ``utilidades.matriz_apertura``): etapas 3RD/LEGACY/sin etapa y
    combinaciones temperatura/generador fuera de columnas. Cada fila lleva el
    ID real (nunca inventado), causa trazable, semáforo y vínculo al Listado.
    Devuelve la siguiente fila libre (== ``fila_inicio`` si no hay casos).
    """
    from utilidades.matriz_apertura import agrupar_casos, causa_sin_clasificar
    _sin_columnas, fuera = agrupar_casos(resultados)
    if not fuera:
        return fila_inicio
    mapa_color={"verde":colores.get("verde","#00B050"),"amarillo":colores.get("amarillo","#FFD966"),
                "rojo":colores.get("rojo","#FF0000"),"gris":colores.get("gris","#A6A6A6")}
    criterio=(reglas.get("criterios") or {}).get("tiempo_apertura_ms") or {"verde":"<= 6","amarillo":"6-7","rojo":"> 7"}
    fila=fila_inicio
    hoja.cell(fila,2).value=_t(idioma,"unclassified")
    hoja.cell(fila,2).font=Font(bold=True)
    hoja.cell(fila,3).value=f"{_t(idioma,'count')}: {len(fuera)}"
    fila += 1
    for col, clave in ((2,"case"),(3,"stage"),(4,"test_temperature"),
                       (5,"generator_type"),(6,"cause"),(7,"opening"),(8,"state")):
        c=hoja.cell(fila,col); c.value=_t(idioma,clave); c.font=Font(bold=True)
    fila += 1
    for resultado in sorted(fuera, key=_test_sort):
        numero=resultado.get("test_number") or _campo(resultado,"test_number") or resultado.get("identificador")
        etapa=str(resultado.get("tipo_st") or _campo(resultado,"tipo_st") or "—")
        temp=str(resultado.get("temperature_condition") or _campo(resultado,"temperature_condition") or "—")
        gen=str(resultado.get("inflator_type") or _campo(resultado,"inflator_type") or "—")
        celda=celda_caso(resultado,criterio)
        estado=celda.get("estado","gris")
        tiempo=(celda.get("opening_time_ms") if estado!="gris"
                else celda.get("tiempo_pendiente_ms"))
        motivo=celda.get("motivo_estado")
        hoja.cell(fila,2).value=numero
        hoja.cell(fila,3).value=etapa
        hoja.cell(fila,4).value=temp
        hoja.cell(fila,5).value=gen
        hoja.cell(fila,6).value=causa_sin_clasificar({
            "tipo_st": resultado.get("tipo_st") or _campo(resultado,"tipo_st"),
            "temperature_condition": resultado.get("temperature_condition") or _campo(resultado,"temperature_condition"),
            "inflator_type": resultado.get("inflator_type") or _campo(resultado,"inflator_type")})
        hoja.cell(fila,7).value=None if tiempo is None else round(float(tiempo),1)
        celda_estado=hoja.cell(fila,8); celda_estado.value=estado
        celda_estado.fill=_relleno(mapa_color.get(estado,mapa_color["gris"]))
        lineas_comentario=[]
        if celda.get("tiempo_es_estimado") and tiempo is not None:
            lineas_comentario.append(f"Estimación automática de apertura: {float(tiempo):g} ms; color calculado, publicación pendiente")
        if estado=="gris":
            razon=MOTIVOS_GRIS.get(motivo,MOTIVOS_GRIS["sin_tiempo"])[idioma if idioma in {"es","en","de"} else "es"]
            lineas_comentario.append(razon)
        if celda.get("decision_apertura"):
            lineas_comentario.append(f"Decisión: {celda['decision_apertura']}")
        if celda.get("estado_tiempo"):
            lineas_comentario.append(f"Estado temporal: {celda['estado_tiempo']}")
        if celda.get("motivo_rechazo"):
            lineas_comentario.append(f"Rechazo: {celda['motivo_rechazo']}")
        if celda.get("raw_time_ms") is not None:
            lineas_comentario.append(f"Tiempo crudo: {celda['raw_time_ms']} ms")
        if celda.get("fuente_evidencia"):
            lineas_comentario.append(f"Fuente: {celda['fuente_evidencia']}")
        lineas_comentario.append(f"{_t(idioma,'state')}: {estado}")
        if lineas_comentario:
            celda_estado.comment=Comment("\n".join(lineas_comentario),"OCR Versuchsmatrix")
        detalle=mapa_filas.get(_identidad(resultado))
        if detalle: hoja.cell(fila,2).hyperlink=f"#'{HOJA_LISTA}'!C{detalle}"
        fila += 1
    return fila


def _crear_leyenda_matriz(hoja, fila: int, colores: dict, idioma: str, reglas: dict | None = None) -> None:
    """Leyenda explícita del MISMO criterio usado para pintar las celdas."""
    criterio=((reglas or {}).get("criterios") or {}).get("tiempo_apertura_ms") or {"verde":"<= 6","amarillo":"6-7","rojo":"> 7"}
    try:
        verde_max, amarillo_max = limites_desde_criterio(criterio)
    except (TypeError, ValueError):
        verde_max, amarillo_max = 6.0, 7.0
    if idioma == "en":
        textos={
            "verde": f"Green ≤ {verde_max:g} ms",
            "amarillo": f"Yellow > {verde_max:g} and ≤ {amarillo_max:g} ms",
            "rojo": f"Red > {amarillo_max:g} ms",
            "gris": "Grey: pending / conflict / no reliable time",
        }
    elif idioma == "de":
        textos={
            "verde": f"Grün ≤ {verde_max:g} ms",
            "amarillo": f"Gelb > {verde_max:g} und ≤ {amarillo_max:g} ms",
            "rojo": f"Rot > {amarillo_max:g} ms",
            "gris": "Grau: ausstehend / Konflikt / keine zuverlässige Zeit",
        }
    else:
        textos={
            "verde": f"Verde ≤ {verde_max:g} ms",
            "amarillo": f"Amarillo > {verde_max:g} y ≤ {amarillo_max:g} ms",
            "rojo": f"Rojo > {amarillo_max:g} ms",
            "gris": "Gris: pendiente / conflicto / sin tiempo confiable",
        }
    for off,estado in enumerate(("verde","amarillo","rojo","gris")):
        c=hoja.cell(fila+off,2); c.value=textos[estado]
        c.fill=_relleno(colores.get(estado, {"verde":"#00B050","amarillo":"#FFD966","rojo":"#FF0000","gris":"#A6A6A6"}[estado]))
        c.font=Font(color="000000",bold=(estado=="gris"))



def _crear_trazabilidad(libro, resultados: list[dict], idioma: str) -> None:
    nombre=_t(idioma,"trace")[:31]
    if nombre in libro.sheetnames: del libro[nombre]
    ws=libro.create_sheet(nombre)
    keys=("project","stage","case","component","field","image","region","original","corrected","orientation","rule","source","version")
    ws.append([_t(idioma,k) for k in keys])
    for c in ws[1]: c.font=Font(bold=True,color="FFFFFF"); c.fill=_relleno("#1D4ED8")
    for r in resultados:
        cands=r.get("candidatos") or (r.get("consolidado") or {}).get("candidatos") or []
        for cand in cands:
            ws.append([r.get("project_id") or cand.get("proyecto") or "",r.get("tipo_st") or cand.get("etapa") or "",_identidad(r),cand.get("componente") or "por_identificar",cand.get("clave") or "",cand.get("imagen") or "",str(cand.get("bbox_original") or ""),cand.get("valor_original") or "",cand.get("texto_correcto") or cand.get("valor_normalizado") or "",cand.get("orientacion_grados") or 0,cand.get("regla_aplicada") or "",cand.get("fuente") or "",cand.get("version_procesamiento") or ""])
            ruta_abs=str(cand.get("imagen_absoluta") or "").strip()
            if ruta_abs:
                celda=ws.cell(ws.max_row,6)
                try:
                    # Excel acepta rutas de archivo locales; no depende de internet.
                    celda.hyperlink=ruta_abs
                    celda.style="Hyperlink"
                except Exception:
                    pass
    ws.freeze_panes="A2"; ws.auto_filter.ref=ws.dimensions
    for col,width in {1:18,2:10,3:38,4:20,5:28,6:42,7:24,8:32,9:32,10:12,11:26,12:20,13:20}.items(): ws.column_dimensions[get_column_letter(col)].width=width


def _crear_diccionario(libro, idioma: str) -> None:
    nombre=_t(idioma,"dictionary")[:31]
    if nombre in libro.sheetnames: del libro[nombre]
    ws=libro.create_sheet(nombre)
    ws.append([_t(idioma,"field"),_t(idioma,"header"),_t(idioma,"origin_rule"),_t(idioma,"status")])
    for c in ws[1]: c.font=Font(bold=True,color="FFFFFF"); c.fill=_relleno("#1D4ED8")
    for clave in CLAVES_PLANTILLA:
        regla,estado=_regla_origen(clave, idioma)
        ws.append([clave,HEADERS.get(clave,{}).get(idioma,clave),regla,estado])
    ws.append([COLUMNAS_MAXIMO_VIDEO[0], HEADERS[COLUMNAS_MAXIMO_VIDEO[0]][idioma],
               _tv(idioma, "maximum_rule"), _tv(idioma, "review")])
    ws.append([COLUMNAS_MAXIMO_VIDEO[1], HEADERS[COLUMNAS_MAXIMO_VIDEO[1]][idioma],
               " / ".join(_tv(idioma, estado) for estado in ("confirmed", "pending", "conflict", "no_data")),
               _tv(idioma, "review")])
    ws.freeze_panes="A2"; ws.auto_filter.ref=ws.dimensions
    for col,width in {1:32,2:34,3:92,4:18}.items(): ws.column_dimensions[get_column_letter(col)].width=width
    for row in ws.iter_rows(min_row=2,max_col=4):
        row[2].alignment=Alignment(wrap_text=True,vertical="top")


def _texto_evidencia(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, (dict, list, tuple)):
        return json.dumps(valor, ensure_ascii=False, default=str)
    return str(valor)


def _crear_evidencia_video(libro, resultados: list[dict], idioma: str) -> None:
    nombre = _tv(idioma, "sheet")[:31]
    if nombre in libro.sheetnames:
        del libro[nombre]
    ws = libro.create_sheet(nombre)
    claves = ("video", "camera", "fps", "fps_source", "zero", "initial_ms", "opening_frame",
              "opening_ms", "opening_review", "maximum_frame", "maximum_ms", "resolution",
              "source", "opening_roi", "maximum_roi", "review", "confirmed_by", "confirmed_at",
              "method", "warnings", "opening_source", "opening_resolution", "opening_raw",
              "opening_time_state", "opening_rejection")
    ws.append([_t(idioma, "project"), _t(idioma, "stage"), _t(idioma, "case"),
               *[_tv(idioma, clave) for clave in claves]])
    for celda in ws[1]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = _relleno("#1D4ED8")
        celda.alignment = Alignment(wrap_text=True, vertical="center")
    for resultado in resultados:
        for video in (resultado.get("videos") or []):
            if not isinstance(video, dict):
                continue
            dato = _datos_maximo(video)
            revision = video.get("revision_manual") or {}
            revision_confirmada = revision.get("estado") == "confirmado"
            sin_apertura = revision.get("estado") == "sin_evento"
            try:
                frame_revision_valido = (revision.get("frame_index") is not None
                                         and int(revision.get("frame_index")) >= 0)
            except (TypeError, ValueError, OverflowError):
                frame_revision_valido = False
            tiempo_revision_crudo = _tiempo_crudo_finito(
                revision.get("raw_time_ms", revision.get("tiempo_ms")))
            referencia_revision_valida = (revision.get("referencia_tiempo_valida") is True
                                          if "referencia_tiempo_valida" in revision
                                          else revision.get("estado_tiempo") == "VALIDO")
            evento_censurado = bool(
                video.get("evento_al_inicio") or video.get("censurado_por_izquierda")
                or str(video.get("estado") or "").casefold() == "evento_al_inicio"
                or str(video.get("estado_evento") or "").casefold() == "evento_al_inicio")
            apertura_confirmada = bool(
                not evento_censurado
                and revision_confirmada and tiempo_revision_crudo is not None
                and tiempo_revision_crudo > 0 and frame_revision_valido
                and referencia_revision_valida
                and revision.get("estado_tiempo") not in {
                    "NO_FINITO", "NO_POSITIVO", "REFERENCIA_INVALIDA", "PENDIENTE"})
            apertura_invalida = evento_censurado or (revision_confirmada and not apertura_confirmada)
            apertura_frame = None if sin_apertura else _frame_valido(
                revision.get("frame_index") if revision_confirmada else video.get("frame_evento"))
            if revision_confirmada:
                apertura_raw = revision.get("raw_time_ms")
                if apertura_raw is None:
                    apertura_raw = revision.get("tiempo_ms")
            else:
                apertura_raw = video.get("tiempo_crudo_ms")
                if apertura_raw is None:
                    apertura_raw = video.get("tiempo_ms")
                if apertura_raw is None:
                    apertura_raw = video.get("tiempo_ms_sospechoso")
            apertura_estado_tiempo = "SIN_EVENTO" if sin_apertura else "PENDIENTE"
            apertura_rechazo = ""
            apertura_raw_num = _tiempo_crudo_finito(apertura_raw)
            video_referencia_valida = (video.get("referencia_tiempo_valida") is True
                                       if "referencia_tiempo_valida" in video
                                       else video.get("estado_tiempo") == "VALIDO")
            if evento_censurado:
                apertura_estado_tiempo = "CENSURADO"
                apertura_rechazo = (revision.get("motivo_rechazo") or video.get("motivo_rechazo")
                                    or "El evento está censurado al inicio del clip; falta evidencia previa del nacimiento.")
            elif revision_confirmada:
                if apertura_raw_num is None:
                    try:
                        valor_raw = float(str(apertura_raw).strip().casefold().replace(",", "."))
                        apertura_estado_tiempo = "NO_FINITO" if not math.isfinite(valor_raw) else "NO_INTERPRETABLE"
                    except (TypeError, ValueError, OverflowError):
                        apertura_estado_tiempo = "NO_INTERPRETABLE"
                elif apertura_raw_num <= 0:
                    apertura_estado_tiempo = "NO_POSITIVO"
                elif not frame_revision_valido or not referencia_revision_valida or revision.get("estado_tiempo") in {
                        "NO_FINITO", "NO_POSITIVO", "NO_INTERPRETABLE", "REFERENCIA_INVALIDA", "PENDIENTE"}:
                    apertura_estado_tiempo = "REFERENCIA_INVALIDA"
                else:
                    apertura_estado_tiempo = "VALIDO"
                if not apertura_confirmada:
                    apertura_rechazo = revision.get("motivo_rechazo") or {
                        "NO_POSITIVO": "El tiempo final de apertura debe ser estrictamente mayor que cero.",
                        "NO_FINITO": "El tiempo final de apertura debe ser finito.",
                        "NO_INTERPRETABLE": "El tiempo crudo no se interpreta como milisegundos.",
                        "REFERENCIA_INVALIDA": "La referencia temporal no está validada; no se publica.",
                    }.get(apertura_estado_tiempo, "La revisión de apertura está pendiente.")
            elif apertura_raw is not None:
                if apertura_raw_num is None:
                    try:
                        valor_raw = float(str(apertura_raw).strip().casefold().replace(",", "."))
                        apertura_estado_tiempo = "NO_FINITO" if not math.isfinite(valor_raw) else "NO_INTERPRETABLE"
                    except (TypeError, ValueError, OverflowError):
                        apertura_estado_tiempo = "NO_INTERPRETABLE"
                elif apertura_raw_num <= 0:
                    apertura_estado_tiempo = "NO_POSITIVO"
                elif not video_referencia_valida:
                    apertura_estado_tiempo = "REFERENCIA_INVALIDA"
                    apertura_rechazo = video.get("motivo_rechazo") or "La referencia temporal del candidato no está validada."
            if apertura_estado_tiempo in {"NO_POSITIVO", "NO_FINITO", "NO_INTERPRETABLE"} and not apertura_rechazo:
                apertura_rechazo = (video.get("motivo_rechazo") or
                                    revision.get("motivo_rechazo") or {
                                        "NO_POSITIVO": "El tiempo final de apertura debe ser estrictamente mayor que cero.",
                                        "NO_FINITO": "El tiempo final de apertura debe ser finito.",
                                        "NO_INTERPRETABLE": "El tiempo crudo no se interpreta como milisegundos.",
                                    }.get(apertura_estado_tiempo, "Tiempo no publicable."))
            apertura_ms = apertura_raw_num if apertura_confirmada else None
            ruta = str(video.get("ruta") or video.get("nombre") or "").strip()
            fps = _numero(dato.get("fps") or video.get("fps_grabacion") or video.get("fps"))
            if fps is not None and fps <= 0:
                fps = None
            if _maximo_confirmado(dato):
                estado_maximo = "confirmed"
            elif _maximo_invalidado(dato):
                estado_maximo = "invalid"
            elif dato and dato.get("estado") != "sin_datos":
                estado_maximo = "pending"
            else:
                estado_maximo = "no_data"
            avisos = []
            for valor in (video.get("advertencia_fps"), video.get("advertencia_tiempo"),
                          video.get("advertencia_deteccion"), revision.get("motivo_rechazo"),
                          dato.get("advertencias")):
                if valor:
                    avisos.append(_texto_evidencia(valor))
            if estado_maximo == "invalid":
                avisos.append(_tv(idioma, "invalid"))
            zona_apertura = video.get("zona_deteccion") or {}
            timestamp_inicial = video.get("overlay_timestamp_inicial_ms")
            if timestamp_inicial is None:
                timestamp_inicial = dato.get("timestamp_inicial_ms")
            ws.append([
                resultado.get("project_id") or "", resultado.get("tipo_st") or "", _identidad(resultado),
                ruta, video.get("tipo_camara") or zona_apertura.get("tipo_camara") or "",
                fps, video.get("fps_fuente") or "", _frame_valido(video.get("frame_cero")),
                _numero(timestamp_inicial), apertura_frame, apertura_ms,
                _tv(idioma, "no_event" if sin_apertura else "invalid" if apertura_invalida
                    else "confirmed" if apertura_confirmada else "pending" if apertura_frame is not None else "no_data"),
                _frame_valido(dato.get("frame_index")), _tiempo_ms(dato.get("tiempo_ms")), _resolucion_maximo(video),
                dato.get("fuente_tiempo") or "", _texto_evidencia(zona_apertura.get("bbox_norm")),
                _texto_evidencia(dato.get("bbox_norm")), _tv(idioma, estado_maximo),
                dato.get("usuario") or "", dato.get("confirmado_en") or "", dato.get("metodo") or "", "\n".join(avisos),
                "revision_manual" if apertura_confirmada or sin_apertura else video.get("fuente_tiempo") or "",
                _tiempo_ms(video.get("resolucion_nativa_ms")),
                _raw_tiempo_excel(apertura_raw), apertura_estado_tiempo, apertura_rechazo,
            ])
            fila = ws.max_row
            if ruta:
                ws.cell(fila, 4).hyperlink = ruta
                ws.cell(fila, 4).style = "Hyperlink"
            for columna in (6, 9, 11, 14, 15, 25, 26):
                ws.cell(fila, columna).number_format = "0.000"
            for columna in (8, 10, 13):
                ws.cell(fila, columna).number_format = "0"
            for columna in (17, 18, 23, 28):
                ws.cell(fila, columna).alignment = Alignment(wrap_text=True, vertical="top")
            if estado_maximo in {"pending", "invalid"}:
                ws.cell(fila, 19).fill = _relleno("#FFD966")
            if apertura_invalida:
                ws.cell(fila, 27).fill = _relleno("#FFD966")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for columna in range(1, 29):
        ws.column_dimensions[get_column_letter(columna)].width = {
            3: 38, 4: 55, 17: 30, 18: 30, 21: 28, 23: 65,
            26: 22, 27: 24, 28: 64,
        }.get(columna, 22)



def _crear_matriz_apertura_dinamica(libro, resultados: list[dict], mapa_filas: dict[str, int],
                                      reglas: dict, idioma: str = "es",
                                      identidad_proyecto: dict | None = None) -> None:
    """Hoja aditiva de apertura con una fila por caso existente, sin cupos/vacantes."""
    from utilidades.resultado_caso import resolver_resultado_caso

    nombre = "Apertura V15.10"
    if nombre in libro.sheetnames:
        del libro[nombre]
    ws = libro.create_sheet(nombre)
    encabezados = {
        "es": ["Proyecto", "Etapa", "Case key", "Número de prueba", "Temperatura",
               "Generador", "Decisión V15.10", "Apertura confirmada ms", "Tiempo propuesto ms",
               "Intervalo ms", "Resolución ms", "Incertidumbre ms", "Fuente", "Estado tiempo",
               "Tiempo crudo ms", "Motivo rechazo", "Soporte cámaras", "Motivo / evidencia", "Ir al detalle",
               "Máximo inflado estimado ms", "Duración breakout→máximo ms",
               "Soporte máximo", "Anomalías máximo",
               # R15.1 (MEDIO-09): columnas NUEVAS al final — el contrato de
               # posiciones legacy (1-23) no se mueve.
               "Estado máximo inflado", "Máximo visible NO CONFIRMADO ms"],
        "en": ["Project", "Stage", "Case key", "Test number", "Temperature", "Inflator",
               "V15.10 decision", "Confirmed opening ms", "Proposed time ms", "Interval ms",
               "Resolution ms", "Uncertainty ms", "Source", "Time status", "Raw time ms",
               "Rejection reason", "Camera support", "Reason / evidence", "Open detail",
               "Estimated maximum inflation ms", "Breakout→maximum duration ms",
               "Maximum support", "Maximum anomalies",
               "Maximum inflation status", "Visible maximum NOT CONFIRMED ms"],
        "de": ["Projekt", "Stufe", "Case key", "Versuchsnummer", "Temperatur", "Generator",
               "V15.10-Entscheidung", "Bestätigte Öffnung ms", "Vorgeschlagene Zeit ms",
               "Intervall ms", "Auflösung ms", "Unsicherheit ms", "Quelle", "Zeitstatus",
               "Rohzeit ms", "Ablehnungsgrund", "Kameraunterstützung", "Grund / Evidenz", "Details öffnen",
               "Geschätzte maximale Entfaltung ms", "Dauer Breakout→Maximum ms",
               "Maximum-Unterstützung", "Maximum-Anomalien",
               "Status maximale Entfaltung", "Sichtbares Maximum NICHT BESTÄTIGT ms"],
    }
    # R15.1 (MEDIO-09): etiqueta de estado explícita del máximo agregado.
    etiquetas_estado_max = {
        "es": {"maximo_inflado_estimado": "Confirmado (estimado defendible)",
               "maximo_visible_observado_no_confirmado": "NO CONFIRMADO (máximo visible observado)",
               "sin_maximo_defendible": "Sin máximo defendible"},
        "en": {"maximo_inflado_estimado": "Confirmed (defensible estimate)",
               "maximo_visible_observado_no_confirmado": "NOT CONFIRMED (observed visible maximum)",
               "sin_maximo_defendible": "No defensible maximum"},
        "de": {"maximo_inflado_estimado": "Bestätigt (vertretbare Schätzung)",
               "maximo_visible_observado_no_confirmado": "NICHT BESTÄTIGT (beobachtetes sichtbares Maximum)",
               "sin_maximo_defendible": "Kein vertretbares Maximum"},
    }.get(idioma, {"maximo_inflado_estimado": "Confirmado (estimado defendible)",
                   "maximo_visible_observado_no_confirmado": "NO CONFIRMADO (máximo visible observado)",
                   "sin_maximo_defendible": "Sin máximo defendible"})
    ws.append(encabezados.get(idioma, encabezados["es"][:]))
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = _relleno("#1D4ED8")
        cell.alignment = Alignment(wrap_text=True, vertical="center")

    criterios = (reglas.get("criterios") or {}).get("tiempo_apertura_ms") or {
        "verde": "<= 6", "amarillo": "6-7", "rojo": "> 7"}
    colores = {"verde": "#00B050", "amarillo": "#FFD966", "rojo": "#FF0000", "gris": "#A6A6A6"}
    orden = {"1ST": 0, "2ST": 1}
    filas = sorted(resultados, key=lambda r: (
        orden.get(str(r.get("tipo_st") or "").upper(), 2),
        str(r.get("temperature_condition") or _campo(r, "temperature_condition") or ""),
        str(r.get("inflator_type") or _campo(r, "inflator_type") or ""),
        str(_campo(r, "test_number") or r.get("identificador") or _identidad(r))))
    for resultado in filas:
        canonico = resultado.get("resultado_caso_canonico")
        if ("campos" in resultado or "videos" in resultado or "video_apertura" in resultado
                or not isinstance(canonico, dict)):
            canonico = resolver_resultado_caso(resultado)
        apertura = canonico.get("apertura") if isinstance(canonico.get("apertura"), dict) else {}
        decision = str(apertura.get("estado") or "NO_OBSERVADO")
        confirmado = (_tiempo_apertura_final(apertura.get("tiempo_ms"))
                      if decision in {"VERIFICADO_HUMANO", "AUTO_VERIFICABLE"} else None)
        propuesto = (_tiempo_apertura_final(apertura.get("tiempo_propuesto_ms"))
                     if decision in {"PROPUESTA", "CONFLICTO"} else None)
        intervalo = apertura.get("intervalo_tiempo_ms")
        motivos = list(apertura.get("motivos") or [])
        revisiones_invalidas = apertura.get("revisiones_temporales_invalidas")
        revisiones_invalidas = revisiones_invalidas if isinstance(revisiones_invalidas, list) else []
        revision_invalida = next((x for x in revisiones_invalidas if isinstance(x, dict)), {})
        campos_resultado = resultado.get("campos") if isinstance(resultado.get("campos"), dict) else {}
        campo_tiempo = campos_resultado.get("opening_time_ms") if isinstance(campos_resultado.get("opening_time_ms"), dict) else {}
        estado_tiempo = revision_invalida.get("estado_tiempo") or apertura.get("estado_tiempo") or (
            "VALIDO" if decision in {"VERIFICADO_HUMANO", "AUTO_VERIFICABLE"} else
            "CONFLICTO" if decision == "CONFLICTO" else
            "PENDIENTE" if decision == "PROPUESTA" else "SIN_MEDICION")
        raw_time_ms = revision_invalida.get("raw_time_ms")
        if raw_time_ms is None:
            raw_time_ms = apertura.get("tiempo_crudo_ms")
        if raw_time_ms is None:
            raw_time_ms = campo_tiempo.get("raw_time_ms")
        if raw_time_ms is not None:
            try:
                if not math.isfinite(float(raw_time_ms)):
                    raw_time_ms = str(raw_time_ms)
            except (TypeError, ValueError, OverflowError):
                raw_time_ms = str(raw_time_ms)
        motivo_rechazo = revision_invalida.get("motivo") or campo_tiempo.get("motivo_rechazo") or ""
        if apertura.get("estado_operativo") == "sin_apertura_confirmada_manual":
            motivos.append("sin_apertura_confirmada_manualmente")
        soporte = apertura.get("soporte_independiente")
        proyecto = (resultado.get("project_id") or resultado.get("proyecto")
                    or (identidad_proyecto or {}).get("project_id")
                    or (identidad_proyecto or {}).get("nombre_proyecto") or "")
        etapa = resultado.get("tipo_st") or ""
        numero = _campo(resultado, "test_number") or resultado.get("identificador") or ""
        temp = resultado.get("temperature_condition") or _campo(resultado, "temperature_condition") or ""
        gen = resultado.get("inflator_type") or _campo(resultado, "inflator_type") or ""
        case_key = _identidad(resultado)
        fuente = (apertura.get("fuente") or campo_tiempo.get("fuente_preferida")
                  or campo_tiempo.get("fuente") or revision_invalida.get("fuente")
                  or revision_invalida.get("video") or "")
        fila = ws.max_row + 1
        ws.append([
            proyecto, etapa, case_key, numero, temp, gen, decision,
            _tiempo_apertura_final(confirmado), _tiempo_apertura_final(propuesto),
            json.dumps(intervalo, ensure_ascii=False) if intervalo is not None else "",
            _numero(apertura.get("resolucion_ms")), _numero(apertura.get("incertidumbre_ms")),
            fuente, estado_tiempo, raw_time_ms if raw_time_ms is not None else "",
            motivo_rechazo, soporte if soporte is not None else "",
            "; ".join(str(x) for x in dict.fromkeys(motivos)), "Abrir caso",
            _numero(apertura.get("tiempo_max_inflado_estimado_ms")),
            _numero(apertura.get("duracion_hasta_max_inflado_ms")),
            apertura.get("max_inflado_soporte") if apertura.get("max_inflado_soporte") is not None else "",
            "; ".join(str(x) for x in (apertura.get("max_inflado_anomalias") or [])),
            etiquetas_estado_max.get(str(apertura.get("max_inflado_estado") or ""), ""),
            _numero(apertura.get("tiempo_max_inflado_no_confirmado_ms")),
        ])
        if decision in {"VERIFICADO_HUMANO", "AUTO_VERIFICABLE"} and confirmado is not None:
            color, valor, _motivo = evaluar_apertura(confirmado, criterios)
            ws.cell(fila, 7).fill = _relleno(colores.get(color, colores["gris"]))
            ws.cell(fila, 8).fill = _relleno(colores.get(color, colores["gris"]))
        else:
            ws.cell(fila, 7).fill = _relleno(colores["gris"])
            ws.cell(fila, 9).fill = _relleno(colores["gris"])
        detalle = mapa_filas.get(_identidad(resultado))
        if detalle:
            ws.cell(fila, 19).hyperlink = f"#'{HOJA_LISTA}'!C{detalle}"
            ws.cell(fila, 19).style = "Hyperlink"
        comentario = "\n".join(str(x) for x in motivos) or "Sin evidencia suficiente; no se declara tiempo confirmado."
        comentario_traza = [f"Decisión: {decision}", f"Estado temporal: {estado_tiempo}"]
        if motivo_rechazo:
            comentario_traza.append(f"Rechazo: {motivo_rechazo}")
        if raw_time_ms is not None:
            comentario_traza.append(f"Tiempo crudo: {raw_time_ms} ms")
        if fuente:
            comentario_traza.append(f"Fuente: {fuente}")
        comentario_traza.extend((comentario, "score/probabilidad calibrada: no disponible"))
        ws.cell(fila, 7).comment = Comment("\n".join(comentario_traza), "V-Matrix")
        for col in (8, 9, 11, 12, 15, 20, 21):
            ws.cell(fila, col).number_format = "0.000"
        for col in range(1, 24):
            ws.cell(fila, col).alignment = Alignment(vertical="top", wrap_text=(col in {10, 15, 16, 18, 23}))
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for col, width in enumerate((22, 10, 38, 20, 16, 16, 28, 21, 20, 27, 16, 18, 24, 18, 18, 46, 17, 68, 18, 24, 28, 16, 48), 1):
        ws.column_dimensions[get_column_letter(col)].width = width


def _guardar_atomico(libro, destino: Path, intentos: int=6) -> None:
    destino.parent.mkdir(parents=True,exist_ok=True)
    tmp=destino.with_name(f".{destino.name}.{os.getpid()}.{time.time_ns()}.tmp.xlsx")
    libro.save(tmp); ultimo=None
    try:
        for i in range(intentos):
            try: os.replace(tmp,destino); return
            except PermissionError as exc: ultimo=exc; time.sleep(.08*(i+1))
        raise PermissionError(f"No se pudo reemplazar {destino.name}; probablemente está abierto en Excel. Cierra el archivo y reintenta.") from ultimo
    finally:
        try:
            if tmp.exists(): tmp.unlink()
        except OSError: pass


def generar_reporte_bmg(ruta_plantilla: str | Path, ruta_salida: str | Path,
                        resultados: list[dict], config: dict, reglas: dict, idioma: str="es",
                        criterios_apertura: dict | None = None,
                        identidad_proyecto: dict | None = None) -> Path:
    """Genera un único Excel 1ST+2ST, dinámico, traducido y trazable.

    ``criterios_apertura`` (V15.9) es la instantánea de la ejecución
    ``{"verde_max": …, "amarillo_max": …, "origen": …}``: cuando se pasa, el
    semáforo de ESTE Excel usa esos límites y no una preferencia posterior,
    de modo que pantalla y libro no divergen. Sin instantánea se usan las
    reglas vigentes (compatibilidad).
    """
    idioma=(idioma or "es").lower()
    if idioma not in {"es","en","de"}: raise ValueError("Idioma de exportación no válido: es, en o de.")
    if criterios_apertura is not None:
        try:
            verde, amarillo = validar_limites(criterios_apertura.get("verde_max"),
                                              criterios_apertura.get("amarillo_max"))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Los límites de apertura de la ejecución no son válidos: {exc}") from exc
        reglas = {**reglas,
                  "criterios": {**(reglas.get("criterios") or {}),
                                "tiempo_apertura_ms": criterio_desde_limites(verde, amarillo)}}
    # Las revisiones se incorporan a una copia: exportar nunca muta resultados
    # compartidos con el reanálisis o el escritor de validación.
    from maximos_video import incorporar_maximos
    resultados = copy.deepcopy(resultados)
    for resultado in resultados:
        incorporar_maximos(resultado)
        # R7: compatibilidad con resultados previos que perdieron project_id
        # al construir la fila final de validación. La identidad elegida por el
        # usuario es la fuente autoritativa de esta ejecución.
        if identidad_proyecto:
            if not resultado.get("project_id"):
                resultado["project_id"] = identidad_proyecto.get("project_id")
            if not resultado.get("nombre_proyecto"):
                resultado["nombre_proyecto"] = identidad_proyecto.get("nombre_proyecto")
    libro=load_workbook(Path(ruta_plantilla))
    faltantes={HOJA_RESUMEN,HOJA_LISTA}-set(libro.sheetnames)
    if faltantes: raise ValueError(f"La plantilla BMG no contiene las hojas requeridas: {sorted(faltantes)}")
    mapa=_poblar_lista(libro[HOJA_LISTA],resultados,idioma)
    _copiar_lista_a_rangos(libro,resultados,idioma)
    resumen=libro[HOJA_RESUMEN]
    # R7: eliminar datos históricos precargados ANTES de dibujar cualquier
    # etapa, para que una corrida de 1-2 filas no deje IDs de la plantilla.
    _limpiar_bloques_historicos_matriz(resumen)
    _aplicar_titulos_proyecto_institucionales(libro, identidad_proyecto, idioma, resultados)
    fin1=_poblar_matriz(resumen,"1ST",resultados,7,mapa,config.get("colores",{}),reglas,idioma)
    inicio2=max(33,fin1+4)
    fin2=_poblar_matriz(resumen,"2ST",resultados,inicio2,mapa,config.get("colores",{}),reglas,idioma)
    # V15.9.1 (B3): bloque único global de casos fuera de etapa/categorización
    # (3RD, LEGACY, sin etapa, combinaciones fuera de columnas) con paridad de
    # IDs respecto al dashboard y al Listado.
    inicio_sc=fin2+2
    fin_sc=_poblar_sin_clasificar(resumen,resultados,inicio_sc,mapa,config.get("colores",{}),reglas,idioma)
    fila_leyenda=fin_sc+1 if fin_sc>inicio_sc else fin2+1
    _crear_leyenda_matriz(resumen,fila_leyenda,config.get("colores",{}),idioma,reglas)
    _crear_trazabilidad(libro,resultados,idioma)
    _crear_diccionario(libro,idioma)
    _crear_evidencia_video(libro,resultados,idioma)
    _crear_matriz_apertura_dinamica(libro,resultados,mapa,reglas,idioma,identidad_proyecto)
    # V15.10: fuente de consulta aditiva; cada fila es un caso existente,
    # mientras la plantilla y sus hojas institucionales permanecen intactas.
    # V15.9.2 (C7): identidad autoritativa del proyecto en la SALIDA (la
    # plantilla BMG permanece intacta; sólo celdas identificadas).
    # V15.9.5 (CRIT-N7): se examinan TODAS las hojas visibles del entregable
    # (resumen, matriz, rangos, trazabilidad, evidencia…), no sólo las
    # mapeadas. Única exención documentada: la hoja de diccionario de datos,
    # documentación ESTATICA de campos generada por esta misma función (sus
    # textos describen reglas OCR, p. ej. «Proyecto o pizarra explícitos…», y
    # no son identidad del reporte). La exención queda escrita en el bloque
    # de identidad.
    # V15.10.1 R3: la plantilla no es la fuente de identidad. Si el usuario
    # eligió explícitamente el proyecto y la plantilla simplemente carece de
    # una celda de proyecto mapeable, se publica con trazabilidad. Las
    # contradicciones reales/estructurales siguen bloqueando.
    from utilidades.identidad_excel_publicacion import aplicar_identidad_a_salida_publicable
    meta_identidad = aplicar_identidad_a_salida_publicable(
        libro, identidad_proyecto, idioma=idioma,
        hojas_busqueda=[HOJA_RESUMEN, HOJA_LISTA], hoja_resumen=HOJA_RESUMEN,
        hojas_exentas=[_t(idioma, "dictionary")[:31]])
    libro.calculation.fullCalcOnLoad=True; libro.calculation.forceFullCalc=True; libro.calculation.calcMode="auto"
    # V15.9.3 (CRIT-03): identidad no verificada ⇒ BORRADOR NO PUBLICABLE en
    # ubicación diferenciada; el destino oficial no se crea ni se reemplaza.
    # Se devuelve la ruta del borrador (sin excepción: abortar la fase 3 del
    # pipeline perdería la persistencia de los resultados OCR de la corrida).
    destino = Path(ruta_salida)
    if identidad_proyecto and meta_identidad.get("publicable") is False:
        destino = destino.with_name(f"{destino.stem}.borrador_no_publicable{destino.suffix or '.xlsx'}")
    _guardar_atomico(libro,destino); return destino
