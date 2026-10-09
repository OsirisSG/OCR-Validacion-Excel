"""Generador del reporte BMG 1ST + 2ST basado en la plantilla de validación.

Mantiene el aspecto del libro de referencia (Resumen / Versuchsmatrix) y usa
los campos consolidados del flujo empresarial. La matriz del resumen muestra
el estado del tiempo de apertura:
  verde <= 6 ms; amarillo > 6 y <= 7 ms; rojo > 7 ms; gris desconocido.
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

# Orden visual de la matriz resumen (izquierda -> derecha).
COLUMNAS_MATRIZ = [
    {"col": "D", "temperature_condition": "HT", "inflator_type": "UGL", "esperados": 5},
    {"col": "E", "temperature_condition": "HT", "inflator_type": "OGL", "esperados": 5},
    {"col": "F", "temperature_condition": "HT", "inflator_type": "NOM", "esperados": 10},
    {"col": "G", "temperature_condition": "RT", "inflator_type": "NOM", "esperados": 10},
    {"col": "H", "temperature_condition": "NT", "inflator_type": "NOM", "esperados": 10},
    {"col": "I", "temperature_condition": "NT", "inflator_type": "OGL", "esperados": 5},
    {"col": "J", "temperature_condition": "NT", "inflator_type": "UGL", "esperados": 5},
]


TEXTOS = {
    "es": {"overview":"Resumen de resultados","opening":"Tiempo de apertura","expected":"Cantidad esperada","found":"Encontrada","processed":"Procesada","unclassified":"Casos sin clasificación de matriz","unknown":"Desconocido / pendiente","state":"Estado","trace":"Trazabilidad","dictionary":"Diccionario de datos","project":"Proyecto","stage":"Etapa","case":"Caso","component":"Componente","field":"Campo","image":"Imagen","region":"Región original","original":"Texto OCR original","corrected":"Texto corregido","orientation":"Orientación","rule":"Regla","source":"Fuente","version":"Versión de procesamiento","header":"Encabezado","origin_rule":"Origen / regla","status":"Estado de fuente","pending":"Pendiente de fuente o confirmación manual","test_temperature":"Temperatura de prueba","generator_type":"Tipo de generador","ok_test":"OK Test","ma_test":"m.A. Test","nio_test":"N.i.O Test"},
    "en": {"overview":"Overview results","opening":"Opening time","expected":"Expected quantity","found":"Found","processed":"Processed","unclassified":"Cases outside matrix classification","unknown":"Unknown / pending","state":"State","trace":"Traceability","dictionary":"Data dictionary","project":"Project","stage":"Stage","case":"Case","component":"Component","field":"Field","image":"Image","region":"Original region","original":"Original OCR text","corrected":"Corrected text","orientation":"Orientation","rule":"Rule","source":"Source","version":"Processing version","header":"Header","origin_rule":"Origin / rule","status":"Source status","pending":"Pending source or manual confirmation","test_temperature":"Test temperature","generator_type":"Generator type","ok_test":"OK test","ma_test":"Conditional test","nio_test":"NOK test"},
    "de": {"overview":"Übersicht Ergebnisse","opening":"Öffnungszeit","expected":"Erwartete Anzahl","found":"Gefunden","processed":"Verarbeitet","unclassified":"Fälle außerhalb der Matrixklassifikation","unknown":"Unbekannt / ausstehend","state":"Status","trace":"Rückverfolgbarkeit","dictionary":"Datenwörterbuch","project":"Projekt","stage":"Stufe","case":"Fall","component":"Komponente","field":"Feld","image":"Bild","region":"Originalbereich","original":"Original OCR-Text","corrected":"Korrigierter Text","orientation":"Orientierung","rule":"Regel","source":"Quelle","version":"Verarbeitungsversion","header":"Überschrift","origin_rule":"Quelle / Regel","status":"Quellenstatus","pending":"Quelle oder manuelle Bestätigung ausstehend","test_temperature":"Prüftemperatur","generator_type":"Generatortyp","ok_test":"OK Test","ma_test":"m.A. Test","nio_test":"N.i.O Test"},
}

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
    valor = _tiempo_ms(_campo_confiable(resultado, "opening_time_ms"))
    if valor is None:
        return "gris", None
    criterio = (reglas.get("criterios") or {}).get("tiempo_apertura_ms") or {
        "verde": "<= 6", "amarillo": "6-7", "rojo": "> 7"
    }
    return evaluar_criterio(criterio, valor) or "gris", valor


def _relleno(hex_color: str) -> PatternFill:
    return PatternFill("solid", fgColor=hex_color.lstrip("#"))


def _escribir_fila(hoja, fila: int, resultado: dict, idioma: str = "es") -> None:
    for indice, clave in enumerate(CLAVES_PLANTILLA, start=1):
        valor = _campo(resultado, clave)
        celda = hoja.cell(fila, indice)
        if clave in {"opening_time_ms", "forvia_measurement_ms", "full_inflation_time_ms", "delay_ms"}:
            valor = _tiempo_ms(valor)
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


def _poblar_matriz(hoja, tipo_st: str, resultados: list[dict], fila_inicio: int,
                   mapa_filas: dict[str, int], colores: dict, reglas: dict, idioma: str = "es") -> int:
    """Dibuja un bloque de matriz completo; crece sin truncar y mueve 2ST si hace falta."""
    mapa_color={"verde":colores.get("verde","#00B050"),"amarillo":colores.get("amarillo","#FFD966"),"rojo":colores.get("rojo","#FF0000"),"gris":colores.get("gris","#A6A6A6")}
    etapa=[r for r in resultados if str(r.get("tipo_st") or "").upper()==tipo_st]
    grupos=[]
    for spec in COLUMNAS_MATRIZ:
        grupo=[r for r in etapa if str(r.get("temperature_condition") or _campo(r,"temperature_condition") or "").upper()==spec["temperature_condition"] and str(r.get("inflator_type") or _campo(r,"inflator_type") or "").upper()==spec["inflator_type"]]
        grupos.append((spec,sorted(grupo,key=_test_sort,reverse=True)))
    alto=max([10,*[len(g) for _,g in grupos]])

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

    for spec,grupo in grupos:
        arranque=fila_inicio+max(0,alto-len(grupo))
        for indice,resultado in enumerate(grupo):
            fila=arranque+indice; c=hoja[f"{spec['col']}{fila}"]
            numero=resultado.get("test_number") or _campo(resultado,"test_number") or resultado.get("identificador")
            c.value=numero; estado,tiempo=_estado_apertura(resultado,reglas); c.fill=_relleno(mapa_color[estado])
            detalle=mapa_filas.get(_identidad(resultado))
            if detalle: c.hyperlink=f"#'{HOJA_LISTA}'!C{detalle}"
            desc=_t(idioma,"unknown") if tiempo is None else f"{_t(idioma,'opening')}: {tiempo:g} ms"
            c.comment=Comment(f"{desc}\n{_t(idioma,'state')}: {estado}","OCR Versuchsmatrix")

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

    # Ningún caso desaparece del resumen: los grupos nuevos, incompletos o no
    # reconocidos se muestran en gris con vínculo al detalle.
    combinaciones={(s["temperature_condition"],s["inflator_type"]) for s in COLUMNAS_MATRIZ}
    fuera=[r for r in etapa if (
        str(r.get("temperature_condition") or _campo(r,"temperature_condition") or "").upper(),
        str(r.get("inflator_type") or _campo(r,"inflator_type") or "").upper()) not in combinaciones]
    fin=fila_procesada+1
    if fuera:
        hoja.cell(fin,2).value=_t(idioma,"unclassified")
        hoja.cell(fin,2).font=Font(bold=True)
        fin += 1
        for resultado in sorted(fuera,key=_test_sort):
            numero=resultado.get("test_number") or _campo(resultado,"test_number") or resultado.get("identificador")
            temp=str(resultado.get("temperature_condition") or _campo(resultado,"temperature_condition") or "—")
            gen=str(resultado.get("inflator_type") or _campo(resultado,"inflator_type") or "—")
            hoja.cell(fin,2).value=numero
            hoja.cell(fin,3).value=temp
            hoja.cell(fin,4).value=gen
            hoja.cell(fin,2).fill=_relleno(mapa_color["gris"])
            detalle=mapa_filas.get(_identidad(resultado))
            if detalle: hoja.cell(fin,2).hyperlink=f"#'{HOJA_LISTA}'!C{detalle}"
            fin += 1
    return fin


def _crear_leyenda_matriz(hoja, fila: int, colores: dict, idioma: str) -> None:
    items=[("verde",_t(idioma,"ok_test")),("amarillo",_t(idioma,"ma_test")),("rojo",_t(idioma,"nio_test")),("gris",_t(idioma,"unknown"))]
    for off,(estado,texto) in enumerate(items):
        c=hoja.cell(fila+off,2); c.value=texto
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
              "method", "warnings", "opening_source", "opening_resolution")
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
            apertura_confirmada = revision.get("estado") == "confirmado"
            sin_apertura = revision.get("estado") == "sin_evento"
            apertura_frame = None if sin_apertura else _frame_valido(
                revision.get("frame_index") if apertura_confirmada else video.get("frame_evento"))
            apertura_ms = None if sin_apertura else _tiempo_ms(
                revision.get("tiempo_ms") if apertura_confirmada else video.get("tiempo_ms"))
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
                          video.get("advertencia_deteccion"), dato.get("advertencias")):
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
                _tv(idioma, "no_event" if sin_apertura else "confirmed" if apertura_confirmada else "pending" if apertura_frame is not None else "no_data"),
                _frame_valido(dato.get("frame_index")), _tiempo_ms(dato.get("tiempo_ms")), _resolucion_maximo(video),
                dato.get("fuente_tiempo") or "", _texto_evidencia(zona_apertura.get("bbox_norm")),
                _texto_evidencia(dato.get("bbox_norm")), _tv(idioma, estado_maximo),
                dato.get("usuario") or "", dato.get("confirmado_en") or "", dato.get("metodo") or "", "\n".join(avisos),
                "revision_manual" if apertura_confirmada or sin_apertura else video.get("fuente_tiempo") or "",
                _tiempo_ms(video.get("resolucion_nativa_ms")),
            ])
            fila = ws.max_row
            if ruta:
                ws.cell(fila, 4).hyperlink = ruta
                ws.cell(fila, 4).style = "Hyperlink"
            for columna in (6, 9, 11, 14, 15, 25):
                ws.cell(fila, columna).number_format = "0.000"
            for columna in (8, 10, 13):
                ws.cell(fila, columna).number_format = "0"
            for columna in (17, 18, 23):
                ws.cell(fila, columna).alignment = Alignment(wrap_text=True, vertical="top")
            if estado_maximo in {"pending", "invalid"}:
                ws.cell(fila, 19).fill = _relleno("#FFD966")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for columna in range(1, 26):
        ws.column_dimensions[get_column_letter(columna)].width = {
            3: 38, 4: 55, 17: 30, 18: 30, 21: 28, 23: 65,
        }.get(columna, 22)



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
                        resultados: list[dict], config: dict, reglas: dict, idioma: str="es") -> Path:
    """Genera un único Excel 1ST+2ST, dinámico, traducido y trazable."""
    idioma=(idioma or "es").lower()
    if idioma not in {"es","en","de"}: raise ValueError("Idioma de exportación no válido: es, en o de.")
    # Las revisiones se incorporan a una copia: exportar nunca muta resultados
    # compartidos con el reanálisis o el escritor de validación.
    from maximos_video import incorporar_maximos
    resultados = copy.deepcopy(resultados)
    for resultado in resultados:
        incorporar_maximos(resultado)
    libro=load_workbook(Path(ruta_plantilla))
    faltantes={HOJA_RESUMEN,HOJA_LISTA}-set(libro.sheetnames)
    if faltantes: raise ValueError(f"La plantilla BMG no contiene las hojas requeridas: {sorted(faltantes)}")
    mapa=_poblar_lista(libro[HOJA_LISTA],resultados,idioma)
    _copiar_lista_a_rangos(libro,resultados,idioma)
    resumen=libro[HOJA_RESUMEN]
    fin1=_poblar_matriz(resumen,"1ST",resultados,7,mapa,config.get("colores",{}),reglas,idioma)
    inicio2=max(33,fin1+4)
    fin2=_poblar_matriz(resumen,"2ST",resultados,inicio2,mapa,config.get("colores",{}),reglas,idioma)
    _crear_leyenda_matriz(resumen,fin2+1,config.get("colores",{}),idioma)
    _crear_trazabilidad(libro,resultados,idioma)
    _crear_diccionario(libro,idioma)
    _crear_evidencia_video(libro,resultados,idioma)
    libro.calculation.fullCalcOnLoad=True; libro.calculation.forceFullCalc=True; libro.calculation.calcMode="auto"
    destino=Path(ruta_salida); _guardar_atomico(libro,destino); return destino
