"""Pruebas de las anclas del tablero (P13): saber qué es cada foto antes de leerla."""
from __future__ import annotations

import numpy as np
import cv2
import pytest

from utilidades.tablero_anclas import (CAMPO_POR_ANCLA, desrotar_180, normalizar_giro,
                                       que_es, reordenar_nivel)
from utilidades.protocolo_campos import evaluar


def _lienzo(alto=600, ancho=900):
    return np.full((alto, ancho, 3), 40, np.uint8)          # plástico oscuro


def test_pestana_azul_es_fecha_de_tablero():
    img = _lienzo()
    cv2.rectangle(img, (600, 250), (660, 360), (200, 120, 40), -1)     # pestaña azul
    cv2.rectangle(img, (250, 245), (600, 365), (240, 240, 240), -1)    # etiqueta blanca
    r = que_es(img)
    assert r["tipo"] == "pestana_azul"
    assert r["campo"] == "dashboard_date"
    assert CAMPO_POR_ANCLA["pestana_azul"] == "dashboard_date"


def test_estampa_de_color_es_nivel_de_ingenieria():
    img = _lienzo()
    cv2.circle(img, (450, 300), 60, (150, 60, 200), -1)                # magenta
    r = que_es(img)
    assert r["tipo"] == "estampa_color"
    assert r["campo"] == "dashboard_engineering_level"


def test_codigo_cuadrado_es_numero_de_parte(tmp_path):
    img = _lienzo()
    cv2.rectangle(img, (200, 150), (700, 450), (245, 245, 245), -1)    # etiqueta blanca
    # DataMatrix simulado: borde en L (izquierda y abajo) + módulos alternos
    cv2.rectangle(img, (300, 220), (313, 373), (20, 20, 20), -1)
    cv2.rectangle(img, (300, 360), (468, 373), (20, 20, 20), -1)
    for i in range(8):
        for j in range(8):
            if (i + j) % 2 == 0:
                cv2.rectangle(img, (306 + j * 20, 226 + i * 20),
                              (321 + j * 20, 241 + i * 20), (20, 20, 20), -1)
    r = que_es(img)
    assert r["tipo"] == "codigo_cuadrado"
    assert r["campo"] == "dashboard_part_number"


def test_foto_sin_ancla_no_se_adivina():
    r = que_es(_lienzo())
    assert r["tipo"] == "desconocido" and r["campo"] == "" and r["confianza"] == 0.0


def test_giro_180_de_la_estampa():
    assert desrotar_180("E0S") == "S03"
    assert reordenar_nivel("S03") == "03S"
    valida = lambda campo, texto: evaluar(campo, texto).estado in ("valido", "reparado")
    assert normalizar_giro("03S", "dashboard_engineering_level", valida) == ("03S", "tal_cual")
    assert normalizar_giro("S03", "dashboard_engineering_level", valida) == ("03S", "letra_delante")
    assert normalizar_giro("E0S", "dashboard_engineering_level", valida)[0] == "03S"


def test_numero_de_parte_del_tablero_admite_las_dos_formas():
    assert evaluar("dashboard_part_number", "3KV0008R662").estado == "valido"
    assert evaluar("dashboard_part_number", "2GJ.880.204.J").estado == "valido"
    assert evaluar("dashboard_part_number", "01S2 3KV0008R662").estado == "invalido"


def test_pagina_de_dudas_muestra_la_imagen_y_el_boton_de_duda(tmp_path):
    import panel_dudas_html as pagina
    imagen = tmp_path / "evidencia.png"
    cv2.imwrite(str(imagen), _lienzo(80, 120))
    tarjeta = pagina._tarjeta_duda({
        "caso": "232550", "campo": "dashboard_engineering_level", "motivo": "fuentes_en_conflicto",
        "detalle": "estampa leída al revés", "opciones": [{"valor": "03S", "detalle": "estampa"}],
        "imagen": str(imagen)})
    assert "data:image/png;base64" in tarjeta
    assert "Tengo duda" in tarjeta
    assert "Caso 232550" in tarjeta


# ---------------------------------------------------------------------------------------------
# P14 · enganche al flujo: clasificar fotos de un caso y decidir campo/valor/duda
# ---------------------------------------------------------------------------------------------
def _foto_azul(directorio, nombre="fecha.jpg"):
    import cv2, numpy as np
    img = np.full((600, 900, 3), 40, np.uint8)
    cv2.rectangle(img, (250, 245), (600, 365), (240, 240, 240), -1)
    cv2.rectangle(img, (600, 250), (660, 360), (200, 120, 40), -1)
    ruta = directorio / nombre
    cv2.imwrite(str(ruta), img)
    return ruta


def _foto_estampa(directorio, nombre="nivel.jpg"):
    import cv2, numpy as np
    img = np.full((600, 900, 3), 40, np.uint8)
    cv2.circle(img, (450, 300), 60, (150, 60, 200), -1)
    ruta = directorio / nombre
    cv2.imwrite(str(ruta), img)
    return ruta


def test_pipeline_sin_ocr_manda_todo_a_dudas(tmp_path):
    from utilidades.tablero_pipeline import analizar_fotos, a_dudas
    rutas = [_foto_azul(tmp_path), _foto_estampa(tmp_path)]
    propuestas = analizar_fotos(rutas, caso="232550", carpeta_evidencia=tmp_path / "ev")
    assert propuestas["dashboard_date"].estado == "requiere_lectura"
    assert propuestas["dashboard_engineering_level"].estado == "requiere_lectura"
    dudas = a_dudas("232550", propuestas)
    assert {d["campo"] for d in dudas} == {"dashboard_date", "dashboard_engineering_level"}
    assert all(d["imagen"] for d in dudas)          # la imagen viaja con la duda


def test_pipeline_con_ocr_corrige_el_giro_y_valida(tmp_path):
    from utilidades.tablero_pipeline import analizar_fotos, a_dudas

    def motor(imagen):
        # devuelve lo que "leería" según el campo: aquí simulamos la estampa girada
        return "E0S"

    rutas = [_foto_estampa(tmp_path)]
    propuestas = analizar_fotos(rutas, motor_ocr=motor, caso="232550")
    nivel = propuestas["dashboard_engineering_level"]
    assert nivel.estado == "propuesto"
    assert nivel.valor == "03S"                      # E0S → S03 → 03S
    assert a_dudas("232550", propuestas) == []        # lo claro no se pregunta


def test_pipeline_descarta_fotos_sin_ancla(tmp_path):
    import cv2, numpy as np
    from utilidades.tablero_pipeline import analizar_fotos
    ruta = tmp_path / "ruido.jpg"
    cv2.imwrite(str(ruta), np.full((400, 600, 3), 40, np.uint8))
    assert analizar_fotos([ruta]) == {}
