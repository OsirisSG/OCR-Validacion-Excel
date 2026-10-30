"""R15.6 · F2 — `corregir_lectura` y `editar_zona` bajo el coordinador común.

Auditoría independiente R15.5:

* ALTO-02: en `corregir_lectura`, si el commit/`actualizar_revision` falla y
  la restauración automática TAMBIÉN falla, los efectos SQLite quedan sin
  registro durable de inconsistencia (el doble fallo desaparece tras
  reiniciar). Las rutas `ilegible`/`no_es_campo` ni siquiera capturan
  snapshot: cualquier fallo posterior deja la muestra persistida.
* ALTO-11: `editar_zona` persiste la edición (ediciones_zona, muestras,
  estrategias) aunque `actualizar_revision` falle después: petición fallida
  con efectos durables.

Política exigida: petición fallida ⇒ cero efectos persistentes O
inconsistencia declarada + bloqueo durable del recurso.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import dashboard.backend.app as backend
import utilidades.persistencia_documento as pdoc
from test_v15_10_1_r153_cas_efectos import (  # noqa: F401 — fixture compartido
    REV_INICIAL, env, _leer)
from test_v15_10_1_r15_1_documento_global import CLAVE


@pytest.fixture
def inconsistencias(env, monkeypatch):
    """Registro de inconsistencias redirigido a tmp y vacío al iniciar."""
    ruta = env["tmp"] / "inconsistencias" / "estado_inconsistente.json"
    monkeypatch.setattr(backend, "RUTA_INCONSISTENCIAS", ruta, raising=False)
    monkeypatch.setattr(backend, "_inconsistencias_activas", {}, raising=False)
    return {"ruta": ruta}


def _reventar(*a, **kw):
    raise RuntimeError("almacén bloqueado (simulado)")


def _conteo(gestor, tabla):
    con = gestor._conectar()
    try:
        return int(con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0])
    except Exception:
        return 0
    finally:
        con.close()


def _llamar_corregir(accion="corregir", campo_destino="test_number"):
    return backend.corregir_lectura(backend.SolicitudCorreccion(
        prueba_id=CLAVE, imagen_id="IMG1", campo="etiqueta",
        texto_ocr="ABC", texto_correcto="A.1", bbox=[0, 0, 10, 10],
        accion=accion, usuario="t", campo_destino=campo_destino,
        expected_revision=REV_INICIAL))


# ---------------------------------------------------------------------------
# corregir_lectura — ALTO-02
# ---------------------------------------------------------------------------


def test_corregir_lectura_doble_fallo_registra_inconsistencia_durable(
        env, monkeypatch, inconsistencias):
    """Commit fallido + restauración fallida ⇒ registro durable + bloqueo.

    Repro del auditor: hoy se responde 503 pero NADA queda registrado; tras
    reiniciar el doble fallo desaparece y el recurso sigue editable con la
    corrección SQLite huérfana.
    """
    monkeypatch.setattr(pdoc, "escribir_json_seguro", lambda *a, **kw: None)
    monkeypatch.setattr(env["gestor"], "restaurar_evidencias_imagen",
                        lambda snap: False)
    with pytest.raises(HTTPException) as fallo:
        _llamar_corregir()
    assert fallo.value.status_code == 503
    recurso = f"carpeta:{CLAVE}"
    assert recurso in backend._inconsistencias_activas, (
        "ALTO-02: el doble fallo debe registrar la inconsistencia de forma "
        "durable; hoy no queda rastro y el recurso sigue editable")
    assert inconsistencias["ruta"].is_file(), (
        "ALTO-02: el registro debe persistir en disco (sobrevive reinicio)")
    # El recurso queda bloqueado para nuevas mutaciones.
    with pytest.raises(HTTPException) as bloqueo:
        _llamar_corregir()
    assert bloqueo.value.status_code == 503
    assert "inconsistente" in str(bloqueo.value.detail).lower()


def test_corregir_lectura_fallo_revision_cero_efectos(
        env, monkeypatch, inconsistencias):
    """Fallo del almacén de revisiones ⇒ 503 controlado y cero efectos."""
    correcciones_antes = _conteo(env["gestor"], "correcciones_texto")
    monkeypatch.setattr(env["gestor"], "actualizar_revision", _reventar)
    with pytest.raises(HTTPException) as fallo:
        _llamar_corregir()
    assert fallo.value.status_code == 503, (
        "ALTO-02: el fallo debe traducirse a 503 controlado, no propagar la "
        "excepción cruda")
    assert _conteo(env["gestor"], "correcciones_texto") == correcciones_antes, (
        "ALTO-02: la corrección SQLite quedó pese a la petición fallida")
    disco = _leer(env["validacion"])
    assert int(disco["revision_documento"]) == REV_INICIAL
    assert disco["resultados"][0]["campos"]["test_number"]["valor"] == "1001"
    assert not backend._inconsistencias_activas


def test_corregir_lectura_ilegible_fallo_revision_cero_efectos(
        env, monkeypatch, inconsistencias):
    """La ruta ilegifible/no_es_campo (sin commit documental) también debe
    compensar: hoy no captura snapshot y la muestra queda persistida."""
    # La imagen del fixture compartido es un dummy de bytes; la muestra
    # visual requiere un PNG decodifiable (cv2.imdecode).
    import cv2
    import numpy as np
    img = np.full((64, 96, 3), 200, np.uint8)
    env["imagen"].write_bytes(cv2.imencode(".png", img)[1].tobytes())
    muestras_antes = _conteo(env["gestor"], "muestras_visuales")
    monkeypatch.setattr(env["gestor"], "actualizar_revision", _reventar)
    with pytest.raises(HTTPException) as fallo:
        _llamar_corregir(accion="ilegible", campo_destino=None)
    assert fallo.value.status_code == 503
    assert _conteo(env["gestor"], "muestras_visuales") == muestras_antes, (
        "MEDIO-06: la muestra visual quedó persistida con la petición fallida")


def test_corregir_lectura_exito_conserva_efectos(env, inconsistencias):
    respuesta = _llamar_corregir()
    assert respuesta.get("registrada") or respuesta.get("campo_confirmado")
    disco = _leer(env["validacion"])
    assert int(disco["revision_documento"]) >= REV_INICIAL + 1
    assert env["gestor"].estado_revision("carpeta", CLAVE, "por_revisar")[
        "estado"] == "parcial"


# ---------------------------------------------------------------------------
# editar_zona — ALTO-11
# ---------------------------------------------------------------------------


def _previsualizar(env):
    return backend.editar_zona(backend.SolicitudZona(
        prueba_id=CLAVE, imagen_id="IMG1", bbox=[0, 0, 10, 10],
        accion="previsualizar", releer=False, exacta=True,
        firma="", texto=""))


def _guardar_zona(firma, texto="XYZ"):
    return backend.editar_zona(backend.SolicitudZona(
        prueba_id=CLAVE, imagen_id="IMG1", bbox=[0, 0, 10, 10],
        accion="guardar", releer=False, exacta=True,
        firma=firma, texto=texto))


def test_editar_zona_fallo_revision_cero_efectos(
        env, monkeypatch, inconsistencias):
    """ALTO-11: si `actualizar_revision` falla tras guardar la edición, la
    petición debe fallar SIN dejar la edición persistida (o declarar
    inconsistencia durable). Hoy la edición queda y revienta en crudo."""
    vista = _previsualizar(env)
    ediciones_antes = _conteo(env["gestor"], "ediciones_zona")
    monkeypatch.setattr(env["gestor"], "actualizar_revision", _reventar)
    with pytest.raises(HTTPException) as fallo:
        _guardar_zona(vista["firma"])
    assert fallo.value.status_code == 503, (
        "ALTO-11: el fallo debe traducirse a 503 controlado")
    assert _conteo(env["gestor"], "ediciones_zona") == ediciones_antes, (
        "ALTO-11: la edición de zona quedó persistida con petición fallida")
    assert not backend._inconsistencias_activas


def test_editar_zona_exito_revision_y_edicion(env, inconsistencias):
    vista = _previsualizar(env)
    respuesta = _guardar_zona(vista["firma"], texto="10.04.25")
    assert respuesta.get("guardado") is True
    assert _conteo(env["gestor"], "ediciones_zona") >= 1
    assert env["gestor"].estado_revision("carpeta", CLAVE, "por_revisar")[
        "estado"] == "parcial"
