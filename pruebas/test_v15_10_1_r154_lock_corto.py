"""R15.4 · F2 — Lock documental corto + reserva de operación (MEDIUM-02).

Auditoría independiente R15.3 (`AUDITORIA_INDEPENDIENTE_R15_3_20261015.md`):

* MEDIUM-02: para eliminar la carrera TOCTOU, R15.3 dejó ``analizar_video()``
  DENTRO de ``_lock_documento()`` en ``aprender_zona_video``. Con un análisis
  de 2 s, cualquier otra mutación queda bloqueada los mismos 2 s (con videos
  reales, mucho más): otra pantalla parece congelada sin timeout visible.
* Recomendación del auditor: flujo de TRES etapas — (1) reserva corta +
  lectura/CAS, (2) análisis pesado FUERA del lock documental, (3) reentrada
  corta con CAS fresco + commit. Y ante otra edición incompatible sobre el
  mismo recurso, responder INMEDIATAMENTE 409/423 con mensaje visible en vez
  de dejar la solicitud esperando indefinidamente.

Diseño R15.4: reserva de operación por recurso (ruta de video) con respuesta
423 inmediata; el análisis corre fuera del lock; la fase 3 revalida CAS sobre
el documento fresco — si otra mutación entró durante el análisis, la petición
recibe 409 y la ROI se COMPENSA (consistencia ALTO-02/HIGH-01 preservada).
El contrato existente de 422 de análisis (la ROI explícita se conserva) no
cambia. ``revertir_zona_video`` (que ya analizaba fuera del lock) comparte la
misma reserva de recurso.
"""
from __future__ import annotations

import threading
import time

import pytest
from fastapi import HTTPException

import dashboard.backend.app as backend
import video_airbag
import aprendizaje_video_airbag
from test_v15_10_1_r153_cas_efectos import (  # noqa: F401 — fixture compartido
    REV_INICIAL, env, _leer)
from test_v15_10_1_r15_1_documento_global import CLAVE

DURACION_ANALISIS = 1.2


def _analizar_lento(monkeypatch, duracion=DURACION_ANALISIS):
    """Stub de analizar_video que marca el evento y duerme (fuera del lock)."""
    en_analisis = threading.Event()

    def stub(ruta, config, usar_cache=False):
        en_analisis.set()
        time.sleep(duracion)
        return {"frame_evento": 7, "tiempo_ms": 120.0,
                "algoritmo_video": "stub-lento", "desde_cache": False}

    monkeypatch.setattr(video_airbag, "analizar_video", stub)
    return en_analisis


def _solicitud_zona():
    return backend.SolicitudZonaVideo(
        prueba_id=CLAVE, video_id="V1", bbox_norm=[0.2, 0.2, 0.6, 0.6],
        usuario="t", expected_revision=REV_INICIAL)


def _arrancar(fn):
    caja = {"respuesta": None, "error": None}

    def correr():
        try:
            caja["respuesta"] = fn()
        except BaseException as exc:  # noqa: BLE001 — diagnóstico
            caja["error"] = exc

    hilo = threading.Thread(target=correr, daemon=True)
    hilo.start()
    return hilo, caja


def test_analisis_pesado_no_bloquea_el_lock_documento(env, monkeypatch):
    """MEDIUM-02: durante el análisis, el lock documental debe estar libre."""
    en_analisis = _analizar_lento(monkeypatch)
    hilo, caja = _arrancar(lambda: backend.aprender_zona_video(_solicitud_zona()))
    try:
        assert en_analisis.wait(timeout=10), "el análisis nunca empezó"
        espera = {}

        def probe():
            inicio = time.monotonic()
            with backend._lock_documento():
                pass
            espera["seg"] = time.monotonic() - inicio

        hilo_probe = threading.Thread(target=probe, daemon=True)
        hilo_probe.start()
        hilo_probe.join(timeout=10)
        assert "seg" in espera, "la sonda no pudo tomar el lock"
        assert espera["seg"] < 0.5, (
            f"MEDIUM-02: el lock documental estuvo tomado {espera['seg']:.2f}s "
            "durante el análisis pesado")
    finally:
        hilo.join(timeout=10)
    assert caja["error"] is None, f"la operación falló: {caja['error']}"
    assert caja["respuesta"]["guardado"] is True
    assert int(_leer(env["validacion"])["revision_documento"]) >= REV_INICIAL + 1
    assert not backend._operaciones_activas, "la reserva no se liberó"


def test_operacion_concurrente_mismo_video_423_inmediato(env, monkeypatch):
    """Reserva de operación: la segunda solicitud incompatible recibe 423 ya."""
    en_analisis = _analizar_lento(monkeypatch)
    hilo, caja = _arrancar(lambda: backend.aprender_zona_video(_solicitud_zona()))
    try:
        assert en_analisis.wait(timeout=10)
        inicio = time.monotonic()
        with pytest.raises(HTTPException) as rechazo:
            backend.aprender_zona_video(_solicitud_zona())
        assert rechazo.value.status_code == 423, (
            f"se esperaba 423 (operación en curso), llegó "
            f"{rechazo.value.status_code}")
        assert "en curso" in str(rechazo.value.detail).lower()
        assert time.monotonic() - inicio < 0.5, (
            "el 423 debe ser inmediato, no tras esperar el lock")
        # revertir sobre el mismo recurso también queda reservado
        with pytest.raises(HTTPException) as rechazo2:
            backend.revertir_zona_video(backend.SolicitudZonaRevertir(
                prueba_id=CLAVE, video_id="V1", usuario="t",
                expected_revision=REV_INICIAL))
        assert rechazo2.value.status_code == 423
    finally:
        hilo.join(timeout=10)
    assert caja["error"] is None
    assert not backend._operaciones_activas


def test_cas_durante_analisis_409_y_roi_compensada(env, monkeypatch):
    """Fase 3 con CAS fresco: mutación concurrente durante el análisis ⇒ 409
    y CERO efectos persistentes (la ROI se compensa)."""
    en_analisis = _analizar_lento(monkeypatch)
    hilo, caja = _arrancar(lambda: backend.aprender_zona_video(_solicitud_zona()))
    assert en_analisis.wait(timeout=10)
    backend.mutar_documento(lambda fresco: None, None)  # bump concurrente
    hilo.join(timeout=10)
    assert isinstance(caja["error"], HTTPException), (
        f"se esperaba 409 del CAS fresco, llegó {caja['error'] or caja['respuesta']}")
    assert caja["error"].status_code == 409
    assert aprendizaje_video_airbag.perfil_zona_aprendida(env["video"]) is None, (
        "409 en fase 3 debe compensar la ROI guardada en fase 1")
    disco = _leer(env["validacion"])
    assert int(disco["revision_documento"]) == REV_INICIAL + 1  # sólo el bump
    assert not backend._operaciones_activas


def test_analisis_422_conserva_roi_y_libera_reserva(env, monkeypatch):
    """Contrato existente: 422 de análisis conserva la ROI explícita."""
    def stub(ruta, config, usar_cache=False):
        raise ValueError("sin evento defendible")

    monkeypatch.setattr(video_airbag, "analizar_video", stub)
    with pytest.raises(HTTPException) as fallo:
        backend.aprender_zona_video(_solicitud_zona())
    assert fallo.value.status_code == 422
    assert aprendizaje_video_airbag.perfil_zona_aprendida(env["video"]) is not None, (
        "el contrato de 422 conserva la ROI explícita del usuario")
    assert not backend._operaciones_activas, "la reserva debe liberarse ante error"
    assert int(_leer(env["validacion"])["revision_documento"]) == REV_INICIAL


def test_revertir_tambien_reserva_el_recurso(env, monkeypatch):
    """revertir_zona_video comparte la reserva por recurso con aprender."""
    # ROI previa + una segunda para que exista historial que revertir.
    aprendizaje_video_airbag.guardar_zona_aprendida(
        env["video"], [0.1, 0.1, 0.5, 0.5], tipo_camara=None,
        frame_index=None, usuario="t")
    aprendizaje_video_airbag.guardar_zona_aprendida(
        env["video"], [0.2, 0.2, 0.6, 0.6], tipo_camara=None,
        frame_index=None, usuario="t")
    en_analisis = _analizar_lento(monkeypatch)
    hilo, caja = _arrancar(lambda: backend.revertir_zona_video(
        backend.SolicitudZonaRevertir(prueba_id=CLAVE, video_id="V1",
                                      usuario="t",
                                      expected_revision=REV_INICIAL)))
    try:
        assert en_analisis.wait(timeout=10)
        with pytest.raises(HTTPException) as rechazo:
            backend.aprender_zona_video(_solicitud_zona())
        assert rechazo.value.status_code == 423
    finally:
        hilo.join(timeout=10)
    assert caja["error"] is None, f"revertir falló: {caja['error']}"
    assert not backend._operaciones_activas
