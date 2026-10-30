"""R15.4 · F1 — Compensación multi-almacén cuando falla el commit (HIGH-01).

Auditoría independiente R15.3 (`AUDITORIA_INDEPENDIENTE_R15_3_20261015.md`):

* HIGH-01: R15.3 resolvió «409 ⇒ cero efectos», pero queda otra ventana:
  el CAS pasa, el efecto durable (SQLite / revisión de video) se guarda, y el
  commit final de ``validacion_resultados.json`` FALLA (disco, permisos,
  antivirus, archivo bloqueado). La petición termina en error pero el efecto
  externo sobrevive ⇒ los dos almacenes internos se contradicen.
  Reproducciones del auditor: ``marcar_imagen_sin_datos`` (fila SQLite queda),
  ``corregir_lectura`` (corrección queda), ``revisar_video`` (revisión durable
  queda).
* Corrección exigida: transacción compensable — capturar el estado anterior
  del efecto externo, aplicar, intentar el commit y, si falla, RESTAURAR el
  estado anterior. Además ``EscrituraFallida`` debe traducirse a un error
  HTTP controlado (503) con mensaje claro: nunca afirmar que se guardó.

Inyección de fallo: ``pdoc.escribir_json_seguro`` devolviendo None sólo
rompe la escritura verificada del DOCUMENTO (la autoridad compartida); los
almacenes durables (``video_airbag`` / SQLite) usan sus propias rutas y NO se
ven afectados — reproducción fiel del escenario del auditor.
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import HTTPException

import dashboard.backend.app as backend
import video_airbag
import aprendizaje_video_airbag
import utilidades.persistencia_documento as pdoc
from test_v15_10_1_r153_cas_efectos import (  # noqa: F401 — fixture compartido
    REV_INICIAL, env, _leer, _conteo_correcciones)
from test_v15_10_1_r15_1_documento_global import CLAVE


def _inyectar_fallo_commit(monkeypatch):
    """La escritura verificada del documento falla; el resto de almacenes no."""
    monkeypatch.setattr(pdoc, "escribir_json_seguro", lambda *a, **kw: None)


def _conteo_muestras(gestor) -> int:
    try:
        con = gestor._conectar()
    except sqlite3.Error:
        return 0
    try:
        return int(con.execute("SELECT COUNT(*) FROM muestras_visuales").fetchone()[0])
    except sqlite3.OperationalError:
        return 0
    finally:
        con.close()


def _assert_503_sin_exito(exc: HTTPException):
    assert exc.status_code == 503, (
        f"HIGH-01: EscrituraFallida debe traducirse a 503 controlado, llegó "
        f"{exc.status_code}")
    detalle = str(exc.detail).lower()
    assert "no se pudo guardar" in detalle, (
        f"el mensaje debe decir que NO se guardó; dijo: {exc.detail}")


# ---------------------------------------------------------------------------
# marcar_imagen_sin_datos
# ---------------------------------------------------------------------------


def test_sin_datos_fallo_commit_restaura_sqlite_y_503(env, monkeypatch):
    _inyectar_fallo_commit(monkeypatch)
    with pytest.raises(HTTPException) as fallo:
        backend.marcar_imagen_sin_datos(backend.SolicitudImagenSinDatos(
            tipo="carpeta", prueba_id=CLAVE, imagen_id="IMG1",
            motivo="sin texto útil", usuario="t",
            expected_revision=REV_INICIAL))
    _assert_503_sin_exito(fallo.value)
    assert env["gestor"].imagen_sin_datos(env["imagen"]) is None, (
        "HIGH-01: el commit falló pero la marca sin-datos sobrevivió en SQLite")
    disco = _leer(env["validacion"])
    assert int(disco["revision_documento"]) == REV_INICIAL
    assert disco["resultados"][0]["imagenes"][0].get("estado_imagen") != (
        "revisada_sin_datos")


def test_sin_datos_fallo_commit_restaura_marca_previa(env, monkeypatch):
    # La imagen YA tenía una marca previa válida (motivo anterior).
    env["gestor"].registrar_imagen_sin_datos(
        env["imagen"], CLAVE, "motivo-anterior", "otro-usuario")
    _inyectar_fallo_commit(monkeypatch)
    with pytest.raises(HTTPException) as fallo:
        backend.marcar_imagen_sin_datos(backend.SolicitudImagenSinDatos(
            tipo="carpeta", prueba_id=CLAVE, imagen_id="IMG1",
            motivo="motivo-nuevo", usuario="t",
            expected_revision=REV_INICIAL))
    _assert_503_sin_exito(fallo.value)
    marca = env["gestor"].imagen_sin_datos(env["imagen"])
    assert marca is not None and marca["motivo"] == "motivo-anterior", (
        "HIGH-01: la compensación debe restaurar la marca PREVIA, no dejar la "
        "nueva ni borrar la anterior")


# ---------------------------------------------------------------------------
# corregir_lectura
# ---------------------------------------------------------------------------


def _llamar_corregir():
    return backend.corregir_lectura(backend.SolicitudCorreccion(
        prueba_id=CLAVE, imagen_id="IMG1", campo="etiqueta",
        texto_ocr="ABC", texto_correcto="A.1", bbox=[0, 0, 10, 10],
        accion="corregir", usuario="t", campo_destino="test_number",
        expected_revision=REV_INICIAL))


def test_ocr_fallo_commit_no_deja_correcciones_ni_muestras(env, monkeypatch):
    correcciones_antes = _conteo_correcciones(env["gestor"])
    muestras_antes = _conteo_muestras(env["gestor"])
    revision_antes = env["gestor"].estado_revision("carpeta", CLAVE, "por_revisar")
    _inyectar_fallo_commit(monkeypatch)
    with pytest.raises(HTTPException) as fallo:
        _llamar_corregir()
    _assert_503_sin_exito(fallo.value)
    assert _conteo_correcciones(env["gestor"]) == correcciones_antes, (
        "HIGH-01: el commit falló pero la corrección quedó registrada en SQLite")
    assert _conteo_muestras(env["gestor"]) == muestras_antes, (
        "HIGH-01: el commit falló pero la muestra visual quedó en SQLite")
    revision_ahora = env["gestor"].estado_revision("carpeta", CLAVE, "por_revisar")
    assert revision_ahora["estado"] == revision_antes["estado"], (
        "HIGH-01: el estado de revisión quedó en 'parcial' tras el commit fallido")
    disco = _leer(env["validacion"])
    assert int(disco["revision_documento"]) == REV_INICIAL
    assert disco["resultados"][0]["campos"]["test_number"]["valor"] == "1001"


# ---------------------------------------------------------------------------
# revisar_video
# ---------------------------------------------------------------------------


def test_video_fallo_commit_restaura_revision_durable(env, monkeypatch):
    _inyectar_fallo_commit(monkeypatch)
    with pytest.raises(HTTPException) as fallo:
        backend.revisar_video(backend.SolicitudRevisionVideo(
            prueba_id=CLAVE, video_id="V1", estado="pendiente",
            usuario="t", expected_revision=REV_INICIAL))
    _assert_503_sin_exito(fallo.value)
    durables = video_airbag.cargar_revisiones().get("revisiones") or {}
    assert not durables, (
        "HIGH-01: el commit falló pero la revisión durable del video sobrevivió")
    disco = _leer(env["validacion"])
    assert int(disco["revision_documento"]) == REV_INICIAL
    assert not disco["resultados"][0]["videos"][0].get("revision_manual")


def test_video_fallo_commit_restaura_revision_previa(env, monkeypatch):
    # Revisión durable previa válida para el mismo video.
    video_airbag.guardar_revision_video(
        env["video"], case_key=None, frame_index=None, tiempo_ms=None,
        estado="pendiente", usuario="previo", comentario="revision-previa")
    _inyectar_fallo_commit(monkeypatch)
    with pytest.raises(HTTPException) as fallo:
        backend.revisar_video(backend.SolicitudRevisionVideo(
            prueba_id=CLAVE, video_id="V1", estado="pendiente",
            usuario="t", comentario="revision-nueva",
            expected_revision=REV_INICIAL))
    _assert_503_sin_exito(fallo.value)
    durables = video_airbag.cargar_revisiones().get("revisiones") or {}
    activos = [v for v in durables.values()]
    assert len(activos) == 1 and activos[0].get("comentario") == "revision-previa", (
        "HIGH-01: la compensación debe restaurar la revisión durable PREVIA")


# ---------------------------------------------------------------------------
# aprender_zona_video — la compensación de ROI ya existe (R15.3); falta el
# error HTTP controlado
# ---------------------------------------------------------------------------


def test_aprender_zona_fallo_commit_devuelve_503(env, monkeypatch):
    _inyectar_fallo_commit(monkeypatch)
    with pytest.raises(HTTPException) as fallo:
        backend.aprender_zona_video(backend.SolicitudZonaVideo(
            prueba_id=CLAVE, video_id="V1", bbox_norm=[0.2, 0.2, 0.6, 0.6],
            usuario="t", expected_revision=REV_INICIAL))
    _assert_503_sin_exito(fallo.value)
    assert aprendizaje_video_airbag.perfil_zona_aprendida(env["video"]) is None
    assert int(_leer(env["validacion"])["revision_documento"]) == REV_INICIAL


# ---------------------------------------------------------------------------
# Rutas de sólo documento: EscrituraFallida ⇒ 503 controlado (traducción en
# el envoltorio de mutar_documento)
# ---------------------------------------------------------------------------


def test_campo_manual_fallo_commit_503(env, monkeypatch):
    _inyectar_fallo_commit(monkeypatch)
    with pytest.raises(HTTPException) as fallo:
        backend.corregir_campo_caso(CLAVE, "opening_time_ms",
                                    backend.SolicitudCampoManual(
                                        valor="1.0", usuario="t",
                                        expected_revision=REV_INICIAL))
    _assert_503_sin_exito(fallo.value)
    disco = _leer(env["validacion"])
    assert int(disco["revision_documento"]) == REV_INICIAL


# ---------------------------------------------------------------------------
# No-regresión: sin fallo inyectado, el éxito conserva efectos y documento
# ---------------------------------------------------------------------------


def test_video_exito_conserva_revision_y_documento(env):
    respuesta = backend.revisar_video(backend.SolicitudRevisionVideo(
        prueba_id=CLAVE, video_id="V1", estado="pendiente",
        usuario="t", expected_revision=REV_INICIAL))
    assert respuesta["guardado"] is True
    durables = video_airbag.cargar_revisiones().get("revisiones") or {}
    assert durables, "el éxito debe dejar la revisión durable"
    disco = _leer(env["validacion"])
    assert int(disco["revision_documento"]) >= REV_INICIAL + 1
    assert disco["resultados"][0]["videos"][0].get("revision_manual")
