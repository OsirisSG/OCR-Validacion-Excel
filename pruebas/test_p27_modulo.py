#!/usr/bin/env python3
"""P27 · la etiqueta del módulo PAB: dos códigos, estampa del nivel y excepción del prototipo.

Lo que se comprueba —y es lo que pidió el usuario:

1. **Doble lectura**: un dato que aparece dos veces y separado en la etiqueta es firme
   (`confirmado_por_dos`); si los dos códigos dicen cosas distintas, **no se elige** y va a dudas.
2. **El nivel no se copia del texto grabado**: `ZRZ 02S 2GJ 880 204 J` es constante en todas las
   carpetas y **no** es el nivel de ingeniería; tampoco se toma de la línea del número de parte.
3. **La estampa amarilla manda**: el nivel (`66K`, `69K`) va en la pegatina redonda amarilla, girada
   en cualquier sentido; se localiza por color y se lee en los cuatro giros.
4. **Sin pegatina** el nivel es el de partida (`01S`) y se marca como tal (`nivel_sin_estampa`).
5. **Consenso entre carpetas** para un dígito confundido: `56K` leído donde las demás dicen `66K`
   se queda en `66K`, dejando anotada la lectura original.
6. **Prototipo**: si la etiqueta viene en inglés (`PROTOTYPE`) se marca y no se apoya en las demás.
7. **PAB Variante**: sale de la etiqueta (`T 2GJ 204`, `Farbe`, código de proveedor) y del nombre de la
   carpeta (`RDW`).
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evidencia_modulo import aplicar_nivel_de_partida, datos_de_la_carpeta, resolver_niveles
from utilidades import codigos_modulo as CM
from utilidades.protocolo_campos import evaluar


def linea(texto, x, y, w=200, h=24):
    return {"texto": texto, "confianza": 0.9, "caja": {"x": x, "y": y, "w": w, "h": h}}


# 1 · doble lectura ------------------------------------------------------------------------------
def test_dos_apariciones_separadas_confirman_el_dato():
    lineas = [linea("2GJ 880 204 J", 100, 100),
              linea("2GJ 880 204 J", 900, 600)]       # el segundo código, al otro lado de la etiqueta
    campos = CM.consenso_de_lineas(lineas)
    assert campos["part_number"] == "2GJ.880.204.J"
    assert campos["fuerza"]["part_number"] == "confirmado_por_dos"


def test_dos_codigos_que_discrepan_no_eligen_valor():
    lineas = [linea("671ZRZ0539983E", 100, 100),
              linea("671ZRZ0539963E", 900, 600)]
    campos = CM.consenso_de_lineas(lineas)
    assert "serial_number" not in campos, "con dos lecturas distintas no se escribe nada"
    assert any(d["campo"] == "serial_number" for d in campos["discrepancias"])


def test_una_sola_aparicion_se_marca():
    campos = CM.consenso_de_lineas([linea("2GJ 880 204 J", 100, 100),
                                    linea("10.04.25", 100, 140)])
    assert campos["date"] == "2025-04-10"
    assert campos["fuerza"]["date"] == "una_sola_lectura"


def test_la_fecha_de_modificacion_del_dibujo_no_es_la_de_fabricacion():
    """`06/05/2025` (con barras) es la fecha de modificación; la de fabricación va con puntos."""
    campos = CM.consenso_de_lineas([linea("2GJ 880 204 J", 100, 100),
                                    linea("10.04.25", 120, 160),
                                    linea("10.04.25", 700, 500),
                                    linea("MEK/DZ/W71/E/C***/N/W316PA/06/05/2025", 120, 640)])
    assert campos["date"] == "2025-04-10", f"se coló la fecha de modificación: {campos.get('date')}"
    assert campos["fuerza"]["date"] == "confirmado_por_dos"


def test_fecha_con_barras_suelta_si_vale():
    """`11/04/2025` impresa sola es la fecha de fabricación de esa etiqueta; dentro del texto de
    modificación, no."""
    suelta = CM.consenso_de_lineas([linea("2GJ 880 204 J", 100, 100),
                                    linea("11/04/2025", 700, 300)])
    assert suelta["date"] == "2025-04-11"
    dentro = CM.consenso_de_lineas([linea("2GJ 880 204 J", 100, 100),
                                    linea("MEK/DZ/W71/E/C***/N/W316PA/07/05/2025", 120, 700)])
    assert "date" not in dentro, f"se coló la fecha de modificación: {dentro.get('date')}"


def test_la_fecha_de_cambio_manda_aunque_el_ocr_la_separe():
    """Si la etiqueta trae `Änderungs-Dat:`, su fecha (con barras) no es la de fabricación."""
    campos = CM.consenso_de_lineas([linea("2GJ 880 204 J", 100, 100),
                                    linea("06/05/2025", 700, 640),          # el OCR la separó
                                    linea("Änderungs-Dat:", 700, 600)])
    assert "date" not in campos, f"se coló la fecha de cambio: {campos.get('date')}"


# 2 · el nivel no sale del texto grabado --------------------------------------------------------
def test_el_grabado_zrz_no_es_el_nivel():
    campos = CM.consenso_de_lineas([linea("ZRZ 02S 2GJ 880 204 J", 100, 400),
                                    linea("2GJ 880 204 J", 100, 100)])
    assert "engineering_level" not in campos, "«02S» del grabado es constante, no es el nivel"


def test_el_nivel_nunca_sale_del_texto_suelto():
    """Un `##K` leído en el texto no se escribe: sólo se apunta como candidato."""
    campos = CM.consenso_de_lineas([linea("2GJ 880 204 J", 100, 100),
                                    linea("60K", 800, 900)])
    assert "engineering_level" not in campos
    assert campos["nivel_texto_candidato"] == {"60K": 1}


def test_la_linea_del_numero_de_parte_tampoco_da_nivel():
    assert CM._valores_de_linea("2GJ 880 204 J 69K", "engineering_level") == []


def test_nivel_normalizado_con_confusiones_del_ocr():
    assert CM.normalizar_nivel("69K") == "69K"
    assert CM.normalizar_nivel("O1S") == "01S"
    assert CM.normalizar_nivel("0lS") == "01S"
    assert CM.normalizar_nivel("DIE") is None          # palabra, no nivel
    assert CM.normalizar_nivel("204") is None


# 3 · la estampa amarilla -----------------------------------------------------------------------
def _foto_con_estampa(texto: str, ancho: int = 1200, alto: int = 900):
    """Foto sintética: fondo oscuro con una pegatina amarilla redonda y un texto negro encima."""
    imagen = np.full((alto, ancho, 3), 40, np.uint8)
    cv2.circle(imagen, (600, 450), 90, (0, 230, 255), -1)
    cv2.putText(imagen, texto, (545, 480), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 5, cv2.LINE_AA)
    return imagen


def test_la_pegatina_amarilla_se_localiza_y_no_se_confunde_con_la_etiqueta_de_aviso():
    imagen = _foto_con_estampa("69K")
    candidatos = CM.recortes_amarillos(imagen)
    assert candidatos, "la pegatina redonda tiene que aparecer"
    grande = np.full((900, 1200, 3), 40, np.uint8)
    cv2.rectangle(grande, (100, 100), (1100, 800), (0, 230, 255), -1)     # etiqueta de aviso entera
    assert CM.recortes_amarillos(grande) == [], "la etiqueta grande no es la estampa del nivel"


def test_la_estampa_se_lee_en_cualquier_giro():
    for giro in (None, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE):
        imagen = _foto_con_estampa("69K")
        if giro is not None:
            imagen = cv2.rotate(imagen, giro)
        estampa = CM.leer_estampa_nivel(imagen)
        assert estampa.get("nivel") == "69K", f"giro {giro}: {estampa}"


# 4 · sin pegatina -------------------------------------------------------------------------------
def test_sin_pegatina_el_nivel_es_el_de_partida_y_se_marca():
    resultados = {"222504": {"fotos_con_modulo": 13, "part_number": "2GJ.880.204.J"}}
    aplicar_nivel_de_partida(resultados)
    assert resultados["222504"]["engineering_level"] == "01S"
    assert resultados["222504"]["nivel_sin_estampa"] is True
    assert "sin pegatina" in resultados["222504"]["fuente_nivel"]["engineering_level"]


def test_el_prototipo_no_recibe_nivel_de_partida():
    resultados = {"232599": {"fotos_con_modulo": 4, "prototipo": True}}
    aplicar_nivel_de_partida(resultados)
    assert "engineering_level" not in resultados["232599"]


# 5 · consenso entre carpetas -------------------------------------------------------------------
def test_un_digito_confundido_se_resuelve_por_consenso():
    resultados = {"232561": {"engineering_level": "56K"},
                  "232564": {"engineering_level": "66K"},
                  "232566": {"engineering_level": "69K"}}
    resolver_niveles(resultados)
    assert resultados["232561"]["engineering_level"] == "66K"
    assert resultados["232561"]["engineering_level_lectura"] == "56K"
    assert resultados["232566"]["engineering_level"] == "69K", "69K es otro nivel, no se toca"


# 6 · prototipo ----------------------------------------------------------------------------------
def test_prototipo_por_etiqueta_en_ingles():
    """La etiqueta de prototipo **sustituye** a la normal: `PROTOTYPE` junto a los datos."""
    campos = CM.consenso_de_lineas([linea("PROTOTYPE", 120, 60),
                                    linea("2GJ 880 204 J", 100, 100)])
    assert campos["prototipo"] is True
    assert campos["es_modulo"] is True


def test_la_pegatina_de_prototipo_de_otro_componente_no_cuenta():
    """`PROTOTYPE AQW` en la pegatina amarilla de un componente (lejos, sin datos del módulo)
    no convierte la carpeta en prototipo: así no salen las diez carpetas marcadas."""
    campos = CM.consenso_de_lineas([linea("2GJ 880 204 J", 100, 100),
                                    linea("PROTOTYPE AQW", 2400, 1600),
                                    linea("651538300C", 2400, 1640)])
    assert not campos.get("prototipo")
    solo_pegatina = CM.consenso_de_lineas([linea("PROTOTYPE AQW", 100, 100),
                                           linea("651538300C", 100, 140)])
    assert not solo_pegatina.get("prototipo")


# 7 · PAB variante -------------------------------------------------------------------------------
def test_datos_de_la_variante_en_la_etiqueta():
    campos = CM.consenso_de_lineas([linea("2GJ 880 204 J", 100, 100),
                                    linea("T 2GJ 204", 700, 200),
                                    linea("0589-P1-000678", 700, 260),
                                    linea("651538300", 700, 300)])
    assert campos["variante"] == "2GJ204"
    assert campos["codigo_proveedor"] == "0589-P1-000678"
    assert campos["generador"] == "651538300"


def test_datos_de_la_carpeta():
    assert datos_de_la_carpeta("232561 RDW OGL HT") == {
        "caso_numero": "232561", "module_version": "RDW",
        "inflator_type": "OGL", "temperature_condition": "HT"}


# 8 · el protocolo de campos acepta lo que se va a escribir --------------------------------------
def test_el_protocolo_acepta_la_variante_y_la_serie():
    assert evaluar("module_version", "RDW").escribible
    assert evaluar("module_serial_number", "671 ZRZ0539983E").escribible
    assert evaluar("module_serial_number", "671 ZRZ05399609").escribible   # como en el libro real
    assert evaluar("engineering_level", "69K").escribible
    assert not evaluar("module_serial_number", "671ZRZ0539983E").escribible  # sin el espacio
