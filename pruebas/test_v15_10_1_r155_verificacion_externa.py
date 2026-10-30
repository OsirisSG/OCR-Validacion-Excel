"""R15.5 · F4 — verificar_imagen (HIGH-03) y externas sin-datos (MEDIUM-04).

Auditoría independiente R15.4:

* HIGH-03: `verificar_imagen` hace `mutar_documento()` primero y
  `gestor.actualizar_revision(...)` después. Si el almacén de revisiones
  falla, el documento queda confirmado como «verificada» (estado_imagen)
  pero el estado de revisión humano no se actualiza: la UI de revisión y el
  documento divergen. El estado de revisión es un efecto externo
  compensable que debe aplicarse ANTES del commit documental.
* MEDIUM-04: en `marcar_imagen_sin_datos` rama EXTERNA,
  `registrar_imagen_sin_datos()` escribe SQLite y sólo después se intenta
  `_guardar_json_atomico()`. Sin transacción sqlite abierta ni
  compensación: si la escritura JSON falla, la marca «sin datos» persiste
  en SQLite aunque el documento externo no la refleje.
* Criterio de liberación: rotación/verificación/sin-datos/externas deben
  compartir la MISMA política transaccional (coordinador P0 de R15.5), no
  compensación endpoint por endpoint.
"""
from __future__ import annotations

import copy
import json

import pytest
from fastapi import HTTPException

import dashboard.backend.app as backend
import pruebas_externas
import utilidades.persistencia_documento as pdoc
from test_v15_10_1_r153_cas_efectos import (  # noqa: F401 — fixture compartido
    REV_INICIAL, env, _leer)
from test_v15_10_1_r15_1_documento_global import CLAVE


def _verificar(rev=REV_INICIAL):
    return backend.verificar_imagen(backend.SolicitudImagenVerificada(
        prueba_id=CLAVE, imagen_id="IMG1", expected_revision=rev,
        usuario="revisor"))


def _marcar_carpeta(rev=REV_INICIAL):
    return backend.marcar_imagen_sin_datos(backend.SolicitudImagenSinDatos(
        tipo="carpeta", prueba_id=CLAVE, imagen_id="IMG1", motivo="ilegible",
        usuario="revisor", expected_revision=rev))


def _marcar_externa():
    return backend.marcar_imagen_sin_datos(backend.SolicitudImagenSinDatos(
        tipo="externa", prueba_id="EXT1", motivo="ilegible", usuario="revisor"))


def _restaurar_carpeta():
    return backend.restaurar_imagen_con_texto(backend.SolicitudImagenSinDatos(
        tipo="carpeta", prueba_id=CLAVE, imagen_id="IMG1", usuario="revisor"))


@pytest.fixture
def externa(env, monkeypatch):
    """Documento externo en memoria + salida JSON bajo tmp."""
    documento = {"resultados": [{"id": "EXT1", "ruta": str(env["imagen"]),
                                 "tokens": [{"texto": "41"}]}]}
    salida = env["tmp"] / "externas_resultados.json"
    monkeypatch.setattr(pruebas_externas, "cargar",
                        lambda config=None: copy.deepcopy(documento))
    monkeypatch.setattr(pruebas_externas, "rutas",
                        lambda config=None: (env["tmp"], salida))
    return documento, salida


# --- HIGH-03: verificar_imagen -------------------------------------------

def test_verificar_fallo_revision_no_toca_documento(env, monkeypatch):
    """Repro del auditor: el almacén de revisiones falla ⇒ documento intacto."""
    def boom(*a, **kw):
        raise RuntimeError("sqlite bloqueado (simulado)")
    monkeypatch.setattr(env["gestor"], "actualizar_revision", boom)
    antes = env["validacion"].read_bytes()
    with pytest.raises(HTTPException) as fallo:
        _verificar()
    assert fallo.value.status_code >= 500
    assert env["validacion"].read_bytes() == antes, (
        "HIGH-03: el almacén de revisiones falló pero el documento quedó "
        "confirmado como verificado")
    disco = _leer(env["validacion"])
    assert int(disco["revision_documento"]) == REV_INICIAL
    assert disco["resultados"][0]["imagenes"][0].get("estado_imagen") != "verificada"


def test_verificar_fallo_commit_restaura_estado_revision(env, monkeypatch):
    """Efecto aplicado + commit fallido ⇒ estado de revisión restaurado."""
    monkeypatch.setattr(pdoc, "escribir_json_seguro", lambda *a, **kw: None)
    with pytest.raises(HTTPException) as fallo:
        _verificar()
    assert fallo.value.status_code == 503
    assert "no se pudo guardar" in str(fallo.value.detail).lower()
    estado = env["gestor"].estado_revision("carpeta", CLAVE, "por_revisar")
    assert estado["estado"] == "por_revisar" and estado["actualizado_en"] is None, (
        f"HIGH-03: el commit falló pero el estado de revisión quedó aplicado: {estado}")
    assert int(_leer(env["validacion"])["revision_documento"]) == REV_INICIAL


def test_verificar_exito_documento_y_revision_coherentes(env):
    respuesta = _verificar()
    assert int(respuesta["revision_documento"]) == REV_INICIAL + 1
    disco = _leer(env["validacion"])
    assert int(disco["revision_documento"]) == REV_INICIAL + 1
    assert disco["resultados"][0]["imagenes"][0]["estado_imagen"] == "verificada"
    assert env["gestor"].estado_revision("carpeta", CLAVE, "por_revisar")["estado"] == "parcial"


# --- MEDIUM-04: externas sin-datos ----------------------------------------

def test_externa_sin_datos_fallo_json_restaura_sqlite(env, externa, monkeypatch):
    """Repro del auditor: escritura JSON externa falla ⇒ marca SQLite deshecha."""
    _, salida = externa
    def boom(*a, **kw):
        raise pdoc.EscrituraFallida("disco lleno (simulado)")
    # El commit externo pasa por _guardar_json_atomico del backend (que usa
    # utilidades.persistencia, no el atributo de pdoc que parchean otros tests).
    monkeypatch.setattr(backend, "_guardar_json_atomico", boom)
    with pytest.raises(HTTPException) as fallo:
        _marcar_externa()
    assert fallo.value.status_code == 503
    assert not salida.exists(), "el JSON externo no debe crearse si la escritura falla"
    assert env["gestor"].imagen_sin_datos(env["imagen"]) is None, (
        "MEDIUM-04: la escritura JSON falló pero la marca 'sin datos' quedó "
        "persistida en SQLite")


def test_externa_sin_datos_exito_json_y_sqlite_coherentes(env, externa):
    _, salida = externa
    resultado = _marcar_externa()
    assert resultado["estado_imagen"] == "revisada_sin_datos"
    escrito = json.loads(salida.read_text(encoding="utf-8"))
    fila = escrito["resultados"][0]
    assert fila["estado_imagen"] == "revisada_sin_datos"
    assert fila["revision_sin_datos"]["imagen_hash"]
    assert env["gestor"].imagen_sin_datos(env["imagen"]) is not None
    assert env["gestor"].estado_revision("externa", "EXT1", "por_revisar")["estado"] == "parcial"


def test_restaurar_con_texto_fallo_revision_no_toca_documento(env, monkeypatch):
    """Política uniforme: restaurar con-texto también compensa su efecto."""
    _marcar_carpeta()  # marca sin datos con éxito (rev +1)
    def boom(*a, **kw):
        raise RuntimeError("sqlite bloqueado (simulado)")
    monkeypatch.setattr(env["gestor"], "actualizar_revision", boom)
    antes = env["validacion"].read_bytes()
    with pytest.raises(HTTPException) as fallo:
        _restaurar_carpeta()
    assert fallo.value.status_code >= 500
    assert env["validacion"].read_bytes() == antes, (
        "el estado de revisión falló pero el documento quedó restaurado")
    assert env["gestor"].imagen_sin_datos(env["imagen"]) is not None, (
        "la marca 'sin datos' no debe eliminarse si la operación falla")
