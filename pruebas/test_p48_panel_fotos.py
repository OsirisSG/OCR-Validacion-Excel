"""P48 · Panel de dudas con la foto de cada opción (recuadro en el área leída), la pieza y la
casilla «otro valor». Imagen y valores sintéticos (2031, número 993101); el libro es una copia
de la plantilla de la rama con la fila del caso vaciada."""
from __future__ import annotations

import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest

from utilidades.dudas_y_opciones import lecturas_desde_validacion

RAIZ = Path(__file__).resolve().parent.parent
PLANTILLA = RAIZ / "plantillas" / "reporte_bmg_1st_2st.xlsx"
pytestmark = pytest.mark.skipif(not PLANTILLA.is_file(), reason="falta la plantilla BMG")


def _foto(ruta: Path) -> None:
    imagen = np.full((600, 800, 3), 235, np.uint8)
    cv2.putText(imagen, "10.04.31", (300, 330), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (20, 20, 20), 3)
    ok, datos = cv2.imencode(".jpg", imagen)
    datos.tofile(str(ruta))


def _validacion(tmp: Path) -> dict:
    carpeta = tmp / "caso con espacios" / "PHOTOS" / "NACH"
    carpeta.mkdir(parents=True)
    _foto(carpeta / "IMG_1.JPG")
    recorte = tmp / "recorte serie.jpg"
    _foto(recorte)
    return {"resultados": [{
        "case_key": "P|1ST|993101", "test_number": "993101",
        "imagenes": [{"ruta_relativa": "PHOTOS/NACH/IMG_1.JPG", "ruta": str(carpeta / "IMG_1.JPG"),
                      "resultado_ocr": {"rotacion_manual_aplicada_grados": 0, "lineas_texto": [
                          {"texto": "Airbag Module", "bbox": [280, 200, 200, 30]},
                          {"texto": "10.04.31", "bbox": [298, 296, 214, 44]}]}}],
        "candidatos": [{"clave": "module_date", "valor_normalizado": "2031-04-10",
                        "valor_original": "10.04.31", "fuente": "ocr",
                        "imagen": "PHOTOS/NACH/IMG_1.JPG"}],
        "tablero_p42": {"campos": {"dashboard_serial_number": {
            "votos": {"052 3KVJ0000AB1": 1}, "variantes": ["052 3KVJ0000AB1", "052 3KVJ0000AB"]}},
            "lecturas": {"dashboard_serial_number": [{
                "valor": "052 3KVJ0000AB1", "ruta_relativa": "PHOTOS/NACH/IMG_1.JPG",
                "recorte": str(recorte), "texto": "052 3KVJ0000AB1"}]}}}]}


def test_evidencia_con_recuadro_y_recorte(tmp_path):
    lecturas, ambiguos = lecturas_desde_validacion(_validacion(tmp_path))
    assert not ambiguos
    ev = lecturas["993101"]["evidencia"]
    fecha = ev["module_date"]["20310410"][0]
    assert fecha["caja"] == [298, 296, 214, 44] and fecha["foto"] == "PHOTOS/NACH/IMG_1.JPG"
    serie = ev["dashboard_serial_number"]["0523KVJ0000AB1"][0]
    assert serie["recorte"].endswith("recorte serie.jpg")


@pytest.fixture
def panel(tmp_path):
    """Se llaman las funciones del panel directamente: no hace falta httpx (TestClient)."""
    pytest.importorskip("fastapi")
    from openpyxl import load_workbook

    import panel_confirmacion as pc

    libro = tmp_path / "libro.xlsx"
    shutil.copy2(PLANTILLA, libro)
    wb = load_workbook(libro)
    ws = wb["Versuchsmatrix"]
    ws.cell(8, 3).value = 993101
    for columna in range(4, 21):
        ws.cell(8, columna).value = None
    wb.save(libro)
    lecturas, _ = lecturas_desde_validacion(_validacion(tmp_path))
    anterior = pc.ESTADO
    pc.ESTADO = pc.Estado(libro, lecturas, "Versuchsmatrix")
    try:
        yield pc
    finally:
        pc.ESTADO = anterior


def test_panel_muestra_foto_pieza_y_no_expone_rutas(panel):
    pc = panel
    respuesta = pc.api_dudas()
    dudas = {d["campo"]: d for d in respuesta["dudas"] if d["caso"] == "993101"}
    fecha = dudas["module_date"]
    assert fecha["pieza"].startswith("Módulo de bolsa de aire")
    opcion = next(o for o in fecha["opciones"] if o["valor"] == "2031-04-10")
    foto = opcion["fotos"][0]
    assert foto["con_caja"] and "token" in foto and "ruta" not in foto
    assert "caso con espacios" not in str(respuesta)                 # sin rutas de disco
    for tam in ("mini", "grande"):
        r = pc.api_foto(foto["token"], tam)
        assert r.media_type == "image/jpeg"
        imagen = cv2.imdecode(np.frombuffer(r.body, np.uint8), cv2.IMREAD_COLOR)
        naranja = (imagen[:, :, 2] > 200) & (imagen[:, :, 1] > 100) & (imagen[:, :, 1] < 180) & (imagen[:, :, 0] < 60)
        assert naranja.sum() > 50, "el recuadro del área leída se dibuja"
    serie = dudas["dashboard_serial_number"]
    variante = next(o for o in serie["opciones"] if o["valor"] == "052 3KVJ0000AB")
    assert variante["fotos"] and "token_recorte" in variante["fotos"][0]


def test_foto_fuera_de_la_lista_no_se_sirve(panel):
    from fastapi import HTTPException
    for token in ("0123456789abcdef", "../../config.yaml"):
        with pytest.raises(HTTPException) as error:
            panel.api_foto(token, "mini")
        assert error.value.status_code == 404


def test_otro_valor_avisa_la_forma_y_se_puede_usar(panel):
    pc = panel
    assert pc.api_revisar(pc.Revision(campo="module_date", valor="no es fecha"))["valido"] is False
    r = pc.api_revisar(pc.Revision(campo="module_date", valor="12.04.31"))
    assert r["valido"] and r["valor"] == "2031-04-12"
    assert pc.api_revisar(pc.Revision(campo="dashboard_engineering_level", valor="3S"))["valido"] is False
    duda = next(d for d in pc.ESTADO.dudas if d["caso"] == "993101" and d["campo"] == "module_date")
    decision = pc.api_decidir(pc.Decision(id=duda["id"], valor="2031-04-12"))
    assert decision["valor"] == "2031-04-12" and decision["fuente"] == "manual"


def test_la_pagina_trae_la_casilla_sutil_y_el_visor(panel):
    html = panel.inicio().body.decode("utf-8")
    assert "Otro texto" in html and 'id="visor"' in html and "Pieza:" in html


def test_el_panel_solo_escucha_en_esta_computadora():
    texto = (RAIZ / "panel_confirmacion.py").read_text(encoding="utf-8")
    assert 'host="127.0.0.1"' in texto and 'host="0.0.0.0"' not in texto
