"""R15 · Validación de entradas (auditoría R14: MEDIA-10 + MEDIA-11).

Pruebas obligatorias 15 y 16:

15. ``NUL.data.xlsx``, ``CON.foo.xlsx``, ``COM1.log.xlsx``, espacio/punto
    final ⇒ rechazo temprano (en Windows los nombres reservados siguen
    reservados con extensiones múltiples, y el espacio final no debe
    «corregirse» en silencio).
16. Seleccionar una carpeta PADRE que contiene el árbol de V-Matrix ⇒
    rechazo con mensaje específico (el escaneo recursivo incluiría el
    programa dentro del lote).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from utilidades.validacion_entradas import (
    es_raiz_codigo_seleccionada,
    validar_nombre_excel,
)


@pytest.mark.parametrize("valor", [
    "CON.foo.xlsx", "AUX.backup.xlsx", "COM1.log.xlsx", "LPT9.test.xlsx",
    "NUL.data.xlsx", "con.foo.xlsx", "nul.DATA.XLSX",
    "COM¹.xlsx", "LPT².dat.xlsx", "COM³.xlsx",
])
def test_dispositivos_reservados_con_extensiones_adicionales(valor):
    with pytest.raises(ValueError):
        validar_nombre_excel(valor)


@pytest.mark.parametrize("valor", ["archivo ", "archivo  ", "salida.xlsx ", "x. "])
def test_espacio_final_crudo_se_rechaza(valor):
    """El valor crudo se valida ANTES del trim: nada de corrección silenciosa."""
    with pytest.raises(ValueError):
        validar_nombre_excel(valor)


@pytest.mark.parametrize("valor", ["archivo.", "salida.xlsx."])
def test_punto_final_se_rechaza(valor):
    with pytest.raises(ValueError):
        validar_nombre_excel(valor)


def test_nombres_validos_sigue_aceptados():
    assert validar_nombre_excel("resultado") == "resultado.xlsx"
    assert validar_nombre_excel("resultado.XLSX") == "resultado.XLSX"
    # Prefijos parecidos a dispositivos NO son dispositivos: sólo el primer
    # componente completo antes del primer punto.
    assert validar_nombre_excel("CONSOLE.xlsx") == "CONSOLE.xlsx"
    assert validar_nombre_excel("nulidades.xlsx") == "nulidades.xlsx"
    assert validar_nombre_excel("mi.CON.xlsx") == "mi.CON.xlsx"
    assert validar_nombre_excel(None) is None


def test_raiz_exacta_y_ancestros_del_programa_se_bloquean(tmp_path):
    programa = tmp_path / "Programas Base" / "OCR-Validacion-Excel"
    programa.mkdir(parents=True)
    (programa / "datos").mkdir()
    # Raíz exacta del programa (contrato R14, se conserva).
    assert es_raiz_codigo_seleccionada(programa, programa)
    # R15 (MEDIA-11): un ancestro que contiene el árbol también se bloquea;
    # el escaneo recursivo metería V-Matrix dentro del lote.
    assert es_raiz_codigo_seleccionada(tmp_path / "Programas Base", programa)
    assert es_raiz_codigo_seleccionada(tmp_path, programa)
    # Una subcarpeta del programa NO es la raíz del código (contrato R14).
    assert not es_raiz_codigo_seleccionada(programa / "datos", programa)
    # Carpetas ajenas, tampoco.
    assert not es_raiz_codigo_seleccionada(tmp_path / "LotePruebas", programa)


def test_mensaje_del_endpoint_cubre_ancestros():
    """Prueba 16: el rechazo debe indicar elegir la carpeta específica."""
    texto = Path(__file__).resolve().parents[1].joinpath(
        "dashboard/backend/app.py").read_text(encoding="utf-8")
    assert "es_raiz_codigo_seleccionada(ruta, RAIZ_PROYECTO)" in texto
    assert "que la contiene" in texto, (
        "el mensaje del 400 no explica el caso de carpeta padre")
