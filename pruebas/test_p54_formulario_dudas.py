"""P54 · El formulario de dudas enlazado desde el dashboard y sus mejoras: vista «una a una»,
giro y zoom de las fotos, «Otro texto» a la vista y regreso al programa. Datos sintéticos."""
from __future__ import annotations

import re

import pytest

import panel_confirmacion as pc


def test_la_pagina_trae_la_vista_guiada_el_giro_y_otro_texto():
    html = pc.PAGINA
    for pieza in ("Una a una", 'id="v-lista"', "Otro texto", "Girar a la derecha", "Girar a la izquierda",
                  "Acercar", "Alejar", 'id="volver"', "function aplicarGiro", "setPointerCapture"):
        assert pieza in html, pieza
    assert "try { v.setPointerCapture(e.pointerId); } catch" in html      # protegido, como pide la guía
    assert not re.search(r"https?://(?!127)|@import|<link", html)         # sin recursos de red


def test_el_regreso_al_programa_solo_acepta_direcciones_de_este_equipo():
    html = pc.PAGINA
    patron = re.search(r"if \(!/(\^http.*?)/\.test\(destino\)\) return;", html).group(1)
    patron = patron.replace("[/]", "/").replace("[.]", r"\.")
    assert re.match(patron, "http://127.0.0.1:8000/#/inicio")
    assert re.match(patron, "http://localhost:8000/")
    for malo in ("https://ejemplo.com/", "http://127.0.0.1.ejemplo.com/", "javascript:alert(1)", "//ejemplo.com"):
        assert not re.match(patron, malo), malo


@pytest.fixture
def backend(monkeypatch, tmp_path):
    fastapi = pytest.importorskip("fastapi")                    # noqa: F841
    import dashboard.backend.app as backend
    libro = tmp_path / "libro con espacios.xlsx"
    libro.write_bytes(b"x")
    datos = {"panel_dudas": {"abierto": True, "url": "http://127.0.0.1:8099", "libro": str(libro)}}
    monkeypatch.setattr(backend, "_cargar_datos", lambda: datos)
    monkeypatch.setattr(backend, "_formulario_dudas_relanzado", {})
    return backend, datos, libro


def test_estado_dice_donde_esta_el_formulario_si_sigue_abierto(backend, monkeypatch):
    backend, _, _ = backend
    monkeypatch.setattr(backend, "_formulario_dudas_responde", lambda url: url == "http://127.0.0.1:8099")
    assert backend.estado_formulario_dudas() == {
        "disponible": True, "vivo": True, "url": "http://127.0.0.1:8099", "motivo": None}
    assert backend.abrir_formulario_dudas()["vivo"] is True          # ya abierto: no se lanza otro


def test_si_se_cerro_se_vuelve_a_lanzar_con_el_mismo_libro(backend, monkeypatch):
    backend, _, libro = backend
    monkeypatch.setattr(backend, "_formulario_dudas_responde", lambda url: False)
    llamadas = []

    def falso(libro_, validacion, config, **extra):
        llamadas.append((str(libro_), str(validacion), extra))
        return {"abierto": True, "url": "http://127.0.0.1:8100", "libro": str(libro_), "puerto": 8100}
    import utilidades.abrir_panel as ap
    monkeypatch.setattr(ap, "abrir_panel_dudas", falso)
    assert backend.estado_formulario_dudas()["vivo"] is False
    salida = backend.abrir_formulario_dudas()
    assert salida["url"] == "http://127.0.0.1:8100" and salida["iniciando"] is True
    assert llamadas[0][0] == str(libro) and llamadas[0][1] == str(backend.RUTA_VALIDACION)
    assert "abrir_navegador" in llamadas[0][2]                        # el dashboard lleva al usuario


def test_sin_excel_de_la_ultima_corrida_no_se_ofrece_ni_se_lanza(backend, monkeypatch):
    from fastapi import HTTPException
    backend, datos, libro = backend
    libro.unlink()
    monkeypatch.setattr(backend, "_formulario_dudas_responde", lambda url: False)
    estado = backend.estado_formulario_dudas()
    assert estado["disponible"] is False and estado["motivo"]
    with pytest.raises(HTTPException) as error:
        backend.abrir_formulario_dudas()
    assert error.value.status_code == 409


def test_solo_se_reconoce_el_formulario_en_este_equipo():
    import dashboard.backend.app as backend
    for url in (None, "", "http://ejemplo.com:8099", "https://127.0.0.1:8099", "http://127.0.0.1.ejemplo.com"):
        assert backend._formulario_dudas_responde(url) is False
