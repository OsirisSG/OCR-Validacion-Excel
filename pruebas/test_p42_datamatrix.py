"""P42 · el DataMatrix del tablero, **sin transformar el dato** (revisión de Astra).

Contrato que fijan estas pruebas, después de la revisión técnica:

  * lo que decodifica el código se devuelve tal cual: no se cambia `$` por `S`, no se borra
    un carácter y no se convierte `O` en cero. Clasificar (`clasificar_cola`) no es transformar;
  * sólo se aceptan símbolos **DataMatrix** válidos: un QR con el mismo texto no vale;
  * si en la misma foto hay dos códigos con valores distintos, se conserva el conflicto;
  * la duda del lector viaja hasta el cierre (`motivos_de_duda`);
  * la fecha se consensúa por valor completo, nunca por posiciones.
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import evidencia_tablero as E  # noqa: E402
from utilidades import tablero_campos as T  # noqa: E402

# cola cruda que trae el código en los 10 casos del lote, y lo que el libro tiene en su lugar
COLAS_DEL_LOTE = {
    "R6E1": ("052 3KVJ008R6E1", "052 3KVJ008R6E", "limpia"),
    "R6J6": ("052 3KVJ008R6J6", "052 3KVJ008R6J6", "limpia"),
    "R69$": ("052 3KVJ008R69$", "052 3KVJ008R69S", "simbolo"),
    "R6RE": ("052 3KVJ008R6RE", "052 3KVJ008R6R", "limpia"),
    "R56Z": ("052 3KVJ008R56Z", "052 3KVJ008R56Z", "limpia"),
    "R4O9": ("052 3KVJ008R4O9", "052 3KVJ008R40S", "ambigua"),
    "R4I3": ("052 3KVJ008R4I3", "052 3KVJ008R4I3", "limpia"),
    "R6YL": ("052 3KVJ008R6YL", "052 3KVJ008R6YI", "limpia"),
    "R5D%": ("052 3KVJ008R5D%", "052 3KVJ008R5D", "simbolo"),
    "R52V": ("052 3KVJ008R52V", "052 3KVJ008R52V", "limpia"),
}

PAYLOAD = "052# 2GJ 857 003 G#       #812506467#19052500*052 3KVJ008R6E1*="


def _imagen_del_codigo(texto: str, formato: str = "DataMatrix", lado: int = 320):
    """Una imagen con un código de verdad, generado al vuelo. Sin fotos ni red.

    El símbolo puede no ser cuadrado, así que se escala conservando la proporción y se centra.
    """
    zxingcpp = pytest.importorskip("zxingcpp")
    barcode = zxingcpp.create_barcode(texto, getattr(zxingcpp.BarcodeFormat, formato))
    codigo = np.where(np.asarray(barcode.to_image()) > 127, 255, 0).astype(np.uint8)
    alto, ancho = codigo.shape[:2]
    escala = min(lado * 0.8 / alto, lado * 0.8 / ancho)
    nuevo = (max(1, int(ancho * escala)), max(1, int(alto * escala)))
    codigo = cv2.resize(codigo, nuevo, interpolation=cv2.INTER_NEAREST)
    gris = np.full((lado, lado), 255, dtype=np.uint8)
    y0, x0 = (lado - codigo.shape[0]) // 2, (lado - codigo.shape[1]) // 2
    gris[y0:y0 + codigo.shape[0], x0:x0 + codigo.shape[1]] = codigo
    return cv2.cvtColor(gris, cv2.COLOR_GRAY2BGR)


# --- el dato no se toca --------------------------------------------------------------
@pytest.mark.parametrize("cola", sorted(COLAS_DEL_LOTE))
def test_la_serie_sale_tal_cual_sin_transformar(cola):
    """El valor devuelto es el del payload, incluidos `$`, `%`, `1` y `E`."""
    esperado, _, _ = COLAS_DEL_LOTE[cola]
    leido = T.leer_serie_de_datamatrix(_imagen_del_codigo(PAYLOAD.replace("R6E1", cola)))
    assert leido["valor"] == esperado
    assert leido["cola_cruda"] == cola


@pytest.mark.parametrize("cola", sorted(COLAS_DEL_LOTE))
def test_clasificar_cola(cola):
    """Clasificar la cola no cambia la cola: sólo dice si es publicable tal cual."""
    _, _, clase = COLAS_DEL_LOTE[cola]
    assert T.clasificar_cola(cola) == clase


@pytest.mark.parametrize("cola", ["R6E1", "R6J6", "R56Z", "R52V", "R69$", "R5D%"])
def test_la_duda_depende_de_la_forma_de_la_cola(cola):
    leido = T.leer_serie_de_datamatrix(_imagen_del_codigo(PAYLOAD.replace("R6E1", cola)))
    esperado_dudoso = T.clasificar_cola(cola) != "limpia"
    assert leido["dudoso"] is esperado_dudoso


def test_la_cola_con_simbolo_queda_en_duda():
    """`$` no se convierte en `S`: se marca y se revisa."""
    leido_limpio = T.leer_serie_de_datamatrix(_imagen_del_codigo(PAYLOAD.replace("R6E1", "R56Z")))
    assert leido_limpio["dudoso"] is False
    leido = T.leer_serie_de_datamatrix(_imagen_del_codigo(PAYLOAD.replace("R6E1", "R69$")))
    assert leido["valor"].endswith("R69$")
    assert leido["dudoso"] is True
    assert leido["clase_cola"] == "simbolo"


# --- simbología y conflicto ----------------------------------------------------------
def test_un_qr_con_el_mismo_texto_no_vale():
    """Revisión de Astra (F4): antes un QR con el mismo payload se aceptaba."""
    assert T.leer_serie_de_datamatrix(_imagen_del_codigo(PAYLOAD, formato="QRCode")) == {}


def test_dos_codigos_distintos_en_la_misma_foto_son_un_conflicto():
    """No se elige por orden: se conservan los dos valores y el campo queda en duda."""
    uno = _imagen_del_codigo(PAYLOAD.replace("R6E1", "R6J6"), lado=260)
    otro = _imagen_del_codigo(PAYLOAD.replace("R6E1", "R52V"), lado=260)
    lienzo = cv2.hconcat([uno, np.full((uno.shape[0], 60, 3), 255, dtype=np.uint8), otro])
    leido = T.leer_serie_de_datamatrix(lienzo)
    assert leido["dudoso"] is True
    assert leido["origen"] == "datamatrix_conflicto"
    assert len(leido["conflicto"]) == 2


def test_el_codigo_del_modulo_no_es_la_serie():
    payload = "052# 2GJ 880 204 J#       #812506467#19052500*671 ZRZ0539991D*="
    assert T.leer_serie_de_datamatrix(_imagen_del_codigo(payload)) == {}


def test_sin_libreria_no_revienta(monkeypatch):
    monkeypatch.setattr(T, "zxingcpp", None)
    assert T.leer_serie_de_datamatrix(np.zeros((40, 40, 3), dtype=np.uint8)) == {}


def test_imagen_vacia_devuelve_vacio():
    assert T.leer_serie_de_datamatrix(np.zeros((0, 0, 3), dtype=np.uint8)) == {}


# --- lo que se conserva para trazar ---------------------------------------------------
def test_se_conserva_el_payload_completo_y_la_version():
    leido = T.leer_serie_de_datamatrix(_imagen_del_codigo(PAYLOAD))
    assert leido["payload_text"] == PAYLOAD
    assert leido["payload_hex"].startswith("303532")      # "052"
    assert "DataMatrix" in leido["formato"]
    assert leido["parte"] == "2GJ.857.003.G"


# --- la duda y el consenso -----------------------------------------------------------
def test_la_duda_del_lector_llega_al_cierre():
    lectura = {"valor": "052 3KVJ008R69$", "confianza": 0.6, "origen": "datamatrix",
               "dudoso": True, "clase_cola": "simbolo", "cola_cruda": "R69$", "conflicto": []}
    consenso = {"valor": "052 3KVJ008R69$", "votos": 2, "dudoso": True, "posiciones_dudosas": []}
    motivos = E.motivos_de_duda("dashboard_serial_number", consenso, [lectura, lectura])
    assert motivos and any("no tiene la forma esperada" in m for m in motivos)


def test_una_lectura_del_datamatrix_sin_conflicto_basta():
    lectura = {"valor": "052 3KVJ008R6J6", "confianza": 0.95, "origen": "datamatrix",
               "dudoso": False, "clase_cola": "limpia", "conflicto": []}
    consenso = {"valor": "052 3KVJ008R6J6", "votos": 1, "dudoso": False, "posiciones_dudosas": []}
    assert E.motivos_de_duda("dashboard_serial_number", consenso, [lectura]) == []


def test_con_conflicto_no_basta_una_lectura():
    lectura = {"valor": "052 3KVJ008R6J6", "confianza": 0.5, "origen": "datamatrix_conflicto",
               "dudoso": True, "conflicto": ["052 3KVJ008R6J6", "052 3KVJ008R52V"]}
    consenso = {"valor": "052 3KVJ008R6J6", "votos": 1, "dudoso": True, "posiciones_dudosas": []}
    motivos = E.motivos_de_duda("dashboard_serial_number", consenso, [lectura])
    assert any("dos códigos distintos" in m for m in motivos)


def test_la_fecha_no_se_inventa_por_posiciones():
    """Revisión de Astra (F6): 11/04 + 06/05 + 17/05 daba 11/05, que nadie leyó."""
    lecturas = [{"valor": "2025-04-11", "confianza": 0.9},
                {"valor": "2025-05-06", "confianza": 0.89},
                {"valor": "2025-05-17", "confianza": 0.83}]
    consenso = E.consensuar_completo(lecturas)
    assert consenso["valor"] in {l["valor"] for l in lecturas}
    assert consenso["dudoso"] is True
    assert consenso["votos"] == 1


def test_la_fecha_con_dos_lecturas_iguales_si_se_publica():
    lecturas = [{"valor": "2025-05-17", "confianza": 0.9}, {"valor": "2025-05-17", "confianza": 0.8},
                {"valor": "2025-04-11", "confianza": 0.7}]
    consenso = E.consensuar_completo(lecturas)
    assert consenso["valor"] == "2025-05-17"
    assert consenso["votos"] == 2
