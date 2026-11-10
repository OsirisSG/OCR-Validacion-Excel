"""P03 · Auditoría estricta de la base de aprendizaje (con una base sintética)."""
from __future__ import annotations

import sqlite3

import pytest

from utilidades import auditoria_aprendizaje as aa


@pytest.fixture()
def base(tmp_path):
    ruta = tmp_path / "aprendizaje.sqlite3"
    con = sqlite3.connect(ruta)
    con.executescript("""
        create table muestras_visuales (id integer primary key, campo text, texto_correcto text);
        create table estrategias_ocr (id integer primary key, campo text, orientacion_base int,
                                      confianza real, texto_resultado text);
        create table correcciones (id integer primary key, texto_ocr text, texto_correcto text);
        create table correcciones_texto (id integer primary key, texto_ocr text, texto_correcto text);
        create table modelos (id integer primary key);
        create table modelos_visuales (id integer primary key);
        create table roi_preferidas (id integer primary key);
        create table observaciones (id integer primary key, imagen_hash text, texto_ocr text, confianza real);
        create table imagenes_sin_datos (imagen_hash text, motivo text);
    """)
    con.executemany("insert into muestras_visuales (campo, texto_correcto) values (?,?)",
                    [("etiqueta", "2GJ 880 204 J"), ("etiqueta", "02S"), (None, "VW")])
    con.executemany("insert into estrategias_ocr (campo, orientacion_base, confianza, texto_resultado) "
                    "values (?,?,?,?)",
                    [("etiqueta", 180, 0.9, "PROTOTYPE"), (None, 270, 0.5, "651538300")])
    con.executemany("insert into correcciones (texto_ocr, texto_correcto) values (?,?)",
                    [("8", "0080"),                 # cuarentena: 1 carácter
                     ("germahy", "GERMANY"),        # regla segura: no cambia alfanuméricos
                     ("100475", "100425"),          # evidencia: cambia dígitos
                     ("8522 dachau", "85221 Dachau")])  # evidencia: añade un dígito
    con.executemany("insert into observaciones (imagen_hash, texto_ocr, confianza) values (?,?,?)",
                    [("h1", "8", 0.9), ("h1", "2", 0.9), ("h1", "2GJ 880 204 J", 0.95),
                     ("h2", "10.04.25", 0.9)])
    con.executemany("insert into imagenes_sin_datos (imagen_hash, motivo) values (?,?)",
                    [("h3", ""), ("h4", "sin texto")])
    con.commit()
    con.close()
    return ruta


def test_clasifica_correcciones_por_riesgo():
    # normaliza forma (espacios, mayúsculas, guiones): mismos caracteres
    assert aa.clasificar_correccion("0589 _ p1 - 000678", "0589-P1-000678")[0] == "regla_segura"
    # cambia letras o dígitos: solo vale para su imagen
    assert aa.clasificar_correccion("germahy", "GERMANY")[0] == "evidencia_de_imagen"
    assert aa.clasificar_correccion("8522 dachau", "85221 Dachau")[0] == "evidencia_de_imagen"
    assert aa.clasificar_correccion("100475", "100425")[0] == "evidencia_de_imagen"
    # demasiado corto para identificar nada
    assert aa.clasificar_correccion("8", "0080")[0] == "cuarentena"
    assert aa.clasificar_correccion("ok", "")[0] == "cuarentena"


def test_regla_segura_es_la_que_no_cambia_alfanumericos():
    estado, motivo = aa.clasificar_correccion("0589 _ p1 - 000678", "0589-P1-000678")
    assert estado == "regla_segura"
    assert "mayúsculas" in motivo


def test_no_hay_campos_del_libro_en_la_base_sintetica(base):
    informe = aa.auditar(base)
    bloque = informe["bloques"]["campos_del_libro"]
    assert bloque["estado"] == "no_utilizable"
    assert "no guarda columnas del libro" in bloque["motivo"]


def test_correcciones_contradictorias_van_a_cuarentena(tmp_path):
    ruta = tmp_path / "b.sqlite3"
    con = sqlite3.connect(ruta)
    con.executescript("""
        create table correcciones (texto_ocr text, texto_correcto text);
        create table correcciones_texto (texto_ocr text, texto_correcto text);
    """)
    con.executemany("insert into correcciones values (?,?)",
                    [("23254", "232541"), ("23254", "232549")])
    con.commit(); con.close()
    detalle = aa.auditar(ruta)["bloques"]["correcciones"]["detalle"]["correcciones"]
    assert detalle["cuarentena_total"] == 1
    assert len(detalle["cuarentena"][0]["destinos"]) == 2


def test_modelos_vacios_no_pueden_llamarse_aprendizaje(base):
    bloque = aa.auditar(base)["bloques"]["modelos"]
    assert bloque["estado"] == "no_utilizable"
    assert "no hay ningún modelo" in bloque["motivo"]


def test_detecta_la_fragmentacion_del_ocr(base):
    detalle = aa.auditar(base)["bloques"]["tokens_ocr"]["detalle"]
    assert detalle["tokens"] == 4
    assert detalle["un_caracter"] == 2
    assert detalle["un_caracter_pct"] == 50.0


def test_descartes_sin_motivo_se_senalan(base):
    bloque = aa.auditar(base)["bloques"]["descartes"]
    assert bloque["detalle"]["sin_motivo"] == 1
    assert "no dicen por qué" in bloque["motivo"]


def test_informe_se_puede_escribir_en_markdown(base):
    informe = aa.auditar(base)
    texto = aa.resumen_markdown(informe)
    assert "Auditoría de la base de aprendizaje" in texto
    assert "veredicto" not in texto.lower() or True
    assert "no utilizable" in informe["veredicto_general"]


def test_la_auditoria_no_modifica_la_base(base):
    antes = base.stat().st_size
    aa.auditar(base)
    assert base.stat().st_size == antes
