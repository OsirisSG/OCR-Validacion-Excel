"""P02 · Lectura de la etiqueta del módulo en fotos reales.

Cubre el módulo `utilidades/etiqueta_roi` (recorte, orientación, renglones) y
las dos reglas nuevas del extractor que nacen del mismo material: número de
parte con el espacio perdido por el OCR y serial impreso sin la palabra SERIAL.
"""
from __future__ import annotations

import numpy as np
import pytest

import flujo_empresarial as fe
from utilidades import etiqueta_roi as roi

IMAGEN = {"confianza_ocr": 0.9}


# --------------------------------------------------------------------------
# localización del recorte
# --------------------------------------------------------------------------
def _foto_con_etiqueta():
    """Pieza oscura con una etiqueta blanca en una esquina."""
    img = np.full((600, 800, 3), 30, dtype=np.uint8)
    img[80:280, 460:760] = 245
    return img


def test_detecta_la_etiqueta_blanca_sobre_pieza_oscura():
    cajas = roi.detectar_regiones_etiqueta(_foto_con_etiqueta())
    assert cajas, "debería proponer al menos un recorte"
    x, y, w, h = cajas[0]
    assert x <= 460 and y <= 80 and x + w >= 760 and y + h >= 280


def test_sin_etiqueta_no_inventa_recortes():
    assert roi.detectar_regiones_etiqueta(np.full((400, 400, 3), 20, dtype=np.uint8)) == []


def test_imagen_vacia_no_revienta():
    assert roi.detectar_regiones_etiqueta(None) == []
    assert roi.detectar_regiones_etiqueta(np.zeros((0, 0, 3), dtype=np.uint8)) == []


# --------------------------------------------------------------------------
# puntuación: palabras frente a caracteres sueltos
# --------------------------------------------------------------------------
def _caja(x, y, w, h, texto, confianza=0.9):
    return ([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], texto, confianza)


def test_las_palabras_puntuan_mas_que_los_caracteres_sueltos():
    palabras = [_caja(i * 60, 0, 50, 20, "2GJ880", 0.9) for i in range(6)]
    sueltos = [_caja(i * 20, 0, 15, 20, "8", 0.99) for i in range(6)]
    assert roi.puntuar_tokens(palabras) > 3 * roi.puntuar_tokens(sueltos)


def test_lista_vacia_puntua_cero():
    assert roi.puntuar_tokens([]) == 0.0
    assert roi.puntuar_tokens(None) == 0.0


# --------------------------------------------------------------------------
# reconstrucción de renglones
# --------------------------------------------------------------------------
def test_une_las_cajas_del_mismo_renglon():
    """Es el caso real: el OCR parte '2GJ 880 204 J' en dos cajas."""
    cajas = [_caja(0, 100, 120, 22, "2GJ 880 204"), _caja(130, 102, 12, 22, "J"),
             _caja(0, 140, 60, 22, "10.04.25")]
    assert roi.reconstruir_lineas(cajas) == ["2GJ 880 204 J", "10.04.25"]


def test_ordena_de_arriba_abajo_y_de_izquierda_a_derecha():
    cajas = [_caja(200, 0, 40, 20, "B"), _caja(0, 0, 40, 20, "A"), _caja(0, 40, 40, 20, "C")]
    assert roi.reconstruir_lineas(cajas) == ["A B", "C"]


def test_acepta_diccionarios_y_cajas_de_easyocr():
    como_dict = [{"texto": "VW", "confianza": 0.9, "bbox": (0, 0, 30, 20)},
                 {"texto": "AG", "confianza": 0.9, "bbox": (35, 0, 30, 20)}]
    assert roi.reconstruir_lineas(como_dict) == ["VW AG"]
    assert roi.reconstruir_lineas([_caja(0, 0, 30, 20, "VW")]) == ["VW"]


# --------------------------------------------------------------------------
# orientación
# --------------------------------------------------------------------------
def test_elige_la_orientacion_que_produce_palabras():
    """Lector simulado: sólo lee bien cuando la imagen es más alta que ancha."""
    llamadas = []

    def lector(img):
        llamadas.append(img.shape)
        if img.shape[0] > img.shape[1]:
            return [_caja(i * 60, 10, 50, 20, "2GJ880") for i in range(5)]
        return [_caja(i * 15, 10, 10, 20, "8") for i in range(5)]

    # etiqueta realista: ocupa una parte pequeña del encuadre (3,7 %)
    img = np.full((600, 800, 3), 30, dtype=np.uint8)
    img[80:230, 480:680] = 245
    lectura = roi.leer_etiqueta(img, lector, escalas=(1.0,), regiones=1)
    assert lectura.orientacion in (90, 270)
    assert "2GJ880" in lectura.texto
    assert len(llamadas) >= 4  # probó las cuatro orientaciones


def test_un_lector_que_falla_no_rompe_la_lectura():
    def lector(_img):
        raise RuntimeError("memoria agotada")

    img = np.full((200, 200, 3), 30, dtype=np.uint8)
    img[20:120, 20:180] = 245
    lectura = roi.leer_etiqueta(img, lector, escalas=(1.0,), regiones=1)
    assert lectura.texto == ""
    assert all(i.get("error") == "RuntimeError" for i in lectura.intentos)


def test_sin_lector_o_sin_imagen_devuelve_vacio():
    assert roi.leer_etiqueta(None, lambda _i: []).texto == ""
    img = np.full((100, 100, 3), 30, dtype=np.uint8)
    assert roi.leer_etiqueta(img, None).texto == ""


# --------------------------------------------------------------------------
# reglas del extractor que nacen de la etiqueta real
# --------------------------------------------------------------------------
@pytest.mark.parametrize("texto", ["2GJ 880 204 J", "2GJ.880.204.J", "2GJ880/204 J",
                                   "PIN Cust: 2GJ880/204 J"])
def test_numero_de_parte_aunque_el_ocr_pierda_el_espacio(texto):
    partes = [c["valor_normalizado"] for c in fe.extraer_candidatos_texto(texto, IMAGEN, {})
              if c["clave"] == "module_part_number"]
    assert partes == ["2GJ.880.204.J"]


@pytest.mark.parametrize("texto", ["651538300", "0589-P1-000678", "1234567890",
                                   "ABCD123456789", "2GJ880204J"])
def test_no_se_confunde_un_numero_cualquiera_con_numero_de_parte(texto):
    partes = [c for c in fe.extraer_candidatos_texto(texto, IMAGEN, {})
              if c["clave"] == "module_part_number"]
    assert partes == []


@pytest.mark.parametrize("texto", ["*671  ZRZ0539991D*", "671 ZRZ0539991D",
                                   "671  ZRZ0539991D"])
def test_serial_impreso_en_la_etiqueta_se_propone(texto):
    seriales = [c for c in fe.extraer_candidatos_texto(texto, IMAGEN, {})
                if c["clave"] == "module_serial_number"]
    assert [s["valor_normalizado"] for s in seriales] == ["671 ZRZ0539991D"]
    assert seriales[0]["requiere_confirmacion_manual"] is True
    assert seriales[0]["regla_aplicada"] == "serial_impreso_en_etiqueta"


@pytest.mark.parametrize("texto", ["651538300", "0589-P1-000678", "85221 Dachau"])
def test_no_se_inventa_un_serial(texto):
    assert [c for c in fe.extraer_candidatos_texto(texto, IMAGEN, {})
            if c["clave"] == "module_serial_number"] == []
