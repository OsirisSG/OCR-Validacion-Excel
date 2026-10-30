"""R15.5 · F2 — Coordinador único de mutaciones multi-almacén (P0 + MEDIUM-05).

Auditoría independiente R15.4 (`AUDITORIA_INDEPENDIENTE_R15_4_20261016.md`):

* MEDIUM-05: en `aprender_zona_video`, si el commit documental fallaba Y la
  compensación (`eliminar_zona_aprendida`) también fallaba, la ROI nueva
  permanecía persistida pero la respuesta 503 afirmaba «La ROI aprendida fue
  revertida; la solicitud no produjo efectos persistentes» — falso bajo doble
  fallo (condiciones comunes a ambos almacenes: disco lleno, antivirus,
  permisos). Corrección exigida: registrar explícitamente el resultado del
  rollback; si falla ⇒ mensaje de `ATENCIÓN: estado potencialmente
  inconsistente` con ruta afectada y acción manual recomendada; no ignorar la
  excepción de compensación.
* Plan P0: capa común de transacción (no compensación endpoint por endpoint) —
  snapshot → efectos → commit → restaurar TODOS en orden inverso → VERIFICAR;
  restauración fallida ⇒ estado_inconsistente explícito.
* Criterio de liberación: «si un rollback falla, el sistema lo declara
  explícitamente y bloquea acciones incompatibles hasta resolverlo».
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

import dashboard.backend.app as backend
import video_airbag
import aprendizaje_video_airbag
import utilidades.persistencia_documento as pdoc
from test_v15_10_1_r153_cas_efectos import (  # noqa: F401 — fixture compartido
    REV_INICIAL, env, _leer)
from test_v15_10_1_r15_1_documento_global import CLAVE


def _reventar(*a, **kw):
    raise RuntimeError("almacén bloqueado (simulado)")


@pytest.fixture
def inconsistencias(env, monkeypatch):
    """Registro de inconsistencias redirigido a tmp y vacío al iniciar."""
    ruta = env["tmp"] / "inconsistencias" / "estado_inconsistente.json"
    monkeypatch.setattr(backend, "RUTA_INCONSISTENCIAS", ruta, raising=False)
    monkeypatch.setattr(backend, "_inconsistencias_activas", {}, raising=False)
    return {"ruta": ruta}


def _aprender(bbox=(0.2, 0.2, 0.6, 0.6)):
    return backend.aprender_zona_video(backend.SolicitudZonaVideo(
        prueba_id=CLAVE, video_id="V1", bbox_norm=list(bbox),
        usuario="t", expected_revision=REV_INICIAL))


def _revisar_pendiente():
    return backend.revisar_video(backend.SolicitudRevisionVideo(
        prueba_id=CLAVE, video_id="V1", estado="pendiente",
        usuario="t", expected_revision=REV_INICIAL))


def _revertir():
    return backend.revertir_zona_video(backend.SolicitudZonaRevertir(
        prueba_id=CLAVE, video_id="V1", usuario="t",
        expected_revision=REV_INICIAL))


def _dos_rois(env):
    aprendizaje_video_airbag.guardar_zona_aprendida(
        env["video"], [0.1, 0.1, 0.5, 0.5], tipo_camara=None,
        frame_index=None, usuario="t")
    aprendizaje_video_airbag.guardar_zona_aprendida(
        env["video"], [0.2, 0.2, 0.6, 0.6], tipo_camara=None,
        frame_index=None, usuario="t")


# ---------------------------------------------------------------------------
# MEDIUM-05 — doble fallo: el mensaje nunca afirma «revertido»
# ---------------------------------------------------------------------------


def test_aprender_doble_fallo_no_afirma_revertido(env, inconsistencias,
                                                  monkeypatch):
    monkeypatch.setattr(pdoc, "escribir_json_seguro", lambda *a, **kw: None)
    monkeypatch.setattr(aprendizaje_video_airbag, "eliminar_zona_aprendida",
                        _reventar)
    with pytest.raises(HTTPException) as fallo:
        _aprender()
    assert fallo.value.status_code == 503
    detalle = str(fallo.value.detail)
    bajo = detalle.lower()
    assert "revertida" not in bajo and "no produjo efectos" not in bajo, (
        f"MEDIUM-05: con la compensación fallida el mensaje afirma algo "
        f"falso: {detalle}")
    assert "inconsistente" in bajo, (
        f"MEDIUM-05: debe declarar estado potencialmente inconsistente: "
        f"{detalle}")
    # R15.7 (ALTO-02): el recurso afectado se identifica con la identidad
    # CANÓNICA del caso (carpeta:<id>#video:<id>), estable entre pantallas.
    assert CLAVE in detalle and "V1" in detalle, (
        f"el mensaje debe incluir el recurso afectado: {detalle}")


def test_revisar_video_doble_fallo_declara_inconsistente(env, inconsistencias,
                                                         monkeypatch):
    monkeypatch.setattr(pdoc, "escribir_json_seguro", lambda *a, **kw: None)
    monkeypatch.setattr(video_airbag, "restaurar_revisiones", _reventar)
    with pytest.raises(HTTPException) as fallo:
        _revisar_pendiente()
    assert fallo.value.status_code == 503
    bajo = str(fallo.value.detail).lower()
    assert "inconsistente" in bajo, (
        f"el doble fallo en revisar_video debe declararse: {fallo.value.detail}")
    assert "fue restaurada" not in bajo


def test_revertir_doble_fallo_declara_inconsistente(env, inconsistencias,
                                                    monkeypatch):
    _dos_rois(env)
    monkeypatch.setattr(pdoc, "escribir_json_seguro", lambda *a, **kw: None)
    monkeypatch.setattr(aprendizaje_video_airbag, "restaurar_perfil_zona",
                        _reventar)
    with pytest.raises(HTTPException) as fallo:
        _revertir()
    assert fallo.value.status_code == 503
    bajo = str(fallo.value.detail).lower()
    assert "inconsistente" in bajo, (
        f"el doble fallo en revertir debe declararse: {fallo.value.detail}")
    assert "se deshizo" not in bajo


# ---------------------------------------------------------------------------
# Criterio de liberación — bloqueo del recurso hasta resolución explícita
# ---------------------------------------------------------------------------


def test_doble_fallo_bloquea_recurso_hasta_resolucion(env, inconsistencias,
                                                      monkeypatch):
    escribir_real = pdoc.escribir_json_seguro
    monkeypatch.setattr(pdoc, "escribir_json_seguro", lambda *a, **kw: None)
    monkeypatch.setattr(aprendizaje_video_airbag, "eliminar_zona_aprendida",
                        _reventar)
    with pytest.raises(HTTPException):
        _aprender()
    # Registro persistente de la inconsistencia.
    ruta_reg = inconsistencias["ruta"]
    assert ruta_reg.is_file(), "la inconsistencia debe registrarse de forma durable"
    entradas = json.loads(ruta_reg.read_text(encoding="utf-8"))["inconsistencias"]
    # R15.7 (ALTO-02): identidad canónica del caso (no la ruta absoluta).
    assert any(str(e.get("recurso")) == f"carpeta:{CLAVE}#video:V1"
               for e in entradas), entradas
    # Con la escritura del documento ya sana, la operación incompatible queda
    # BLOQUEADA de todos modos hasta la resolución explícita.
    monkeypatch.setattr(pdoc, "escribir_json_seguro", escribir_real)
    with pytest.raises(HTTPException) as bloqueo:
        _aprender()
    assert bloqueo.value.status_code == 503
    assert "inconsistente" in str(bloqueo.value.detail).lower(), (
        f"el bloqueo debe explicar la causa: {bloqueo.value.detail}")
    # Resolución manual recomendada: revisar almacenes y retirar el registro.
    ruta_reg.unlink()
    backend._cargar_inconsistencias()
    respuesta = _aprender()
    assert respuesta["guardado"] is True, (
        "tras la resolución explícita la operación debe volver a funcionar")


# ---------------------------------------------------------------------------
# Fallo simple (compensación exitosa): mensaje unificado y SIN bloqueo
# ---------------------------------------------------------------------------


def test_fallo_simple_compensado_no_bloquea(env, inconsistencias, monkeypatch):
    monkeypatch.setattr(pdoc, "escribir_json_seguro", lambda *a, **kw: None)
    with pytest.raises(HTTPException) as fallo:
        _aprender()
    assert fallo.value.status_code == 503
    bajo = str(fallo.value.detail).lower()
    assert "restaurados" in bajo and "no produjo efectos persistentes" in bajo, (
        f"mensaje unificado de compensación exitosa: {fallo.value.detail}")
    assert "inconsistente" not in bajo
    assert not inconsistencias["ruta"].exists(), (
        "una compensación exitosa no debe registrar inconsistencia")
    assert aprendizaje_video_airbag.perfil_zona_aprendida(env["video"]) is None
    assert int(_leer(env["validacion"])["revision_documento"]) == REV_INICIAL


def test_registro_inconsistencia_persiste_y_se_resuelve(env, inconsistencias):
    """El registro es durable (sobrevive recarga) y la resolución explícita
    lo retira de la memoria y del archivo."""
    backend._registrar_inconsistencia(str(env["video"]), "operación-x",
                                      "detalle-y")
    ruta_reg = inconsistencias["ruta"]
    assert ruta_reg.is_file(), "el registro debe persistirse"
    # Simula reinicio del proceso: memoria vacía + recarga desde disco.
    backend._inconsistencias_activas.clear()
    backend._cargar_inconsistencias()
    # R15.7 (ALTO-02): tras el reinicio el bloqueo vive en identidad canónica.
    assert f"carpeta:{CLAVE}#video:V1" in backend._inconsistencias_activas, (
        "el bloqueo debe sobrevivir reinicios (registro durable)")
    # Mientras exista el registro, la operación incompatible está bloqueada.
    with pytest.raises(HTTPException) as bloqueo:
        _aprender()
    assert bloqueo.value.status_code == 503
    # Resolución explícita ⇒ desbloqueo inmediato.
    backend._resolver_inconsistencias(str(env["video"]))  # acepta alias heredado
    assert f"carpeta:{CLAVE}#video:V1" not in backend._inconsistencias_activas
    respuesta = _aprender()
    assert respuesta["guardado"] is True
