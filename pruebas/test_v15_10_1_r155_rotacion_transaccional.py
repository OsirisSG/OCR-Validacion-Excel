"""R15.5 · F3 — `guardar_rotacion` en una sola transacción (HIGH-02).

Auditoría independiente R15.4 (`AUDITORIA_INDEPENDIENTE_R15_4_20261016.md`):

* HIGH-02: en `guardar_rotacion` (carpeta), `mutar_documento()` aplicaba el
  giro y confirmaba la revisión NUEVA del documento ANTES de llamar a
  `GestorAprendizaje.actualizar_rotacion()`. Con fallo inyectado en el almacén
  de rotaciones, la petición terminaba en error pero
  `validacion_resultados.json` quedaba con la geometría rotada y
  `rotacion_manual_aplicada_grados=90` mientras el almacén no recibió el
  cambio: geometría y aprendizaje desacoplados; el siguiente OCR no partiría
  de la orientación que refleja el documento.
* Corrección exigida: rotación + evidencias + documento en la MISMA
  transacción compensable — snapshot de rotación/evidencias, efectos
  externos, commit documental al final; si cualquier paso falla, restaurar
  todos los efectos previos (vía coordinador P0 de R15.5).

Cada prueba verifica también número de revisión y almacén de rotaciones,
como pide el plan P1 de la auditoría.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import dashboard.backend.app as backend
import utilidades.persistencia_documento as pdoc
from test_v15_10_1_r153_cas_efectos import (  # noqa: F401 — fixture compartido
    REV_INICIAL, env, _leer)
from test_v15_10_1_r15_1_documento_global import CLAVE


def _rotar(grados=90, usar_automatico=False, rev=REV_INICIAL):
    return backend.guardar_rotacion(backend.SolicitudRotacion(
        tipo="carpeta", prueba_id=CLAVE, imagen_id="IMG1", grados=grados,
        usar_automatico=usar_automatico, expected_revision=rev))


def _rotaciones(gestor, ruta) -> dict:
    """Fila del almacén de rotaciones para la imagen ( keyed por hash)."""
    return next(iter(gestor.listar_rotaciones([ruta]).values()), {})


def test_fallo_almacen_rotacion_no_toca_documento(env, monkeypatch):
    """Repro del auditor: el almacén de rotaciones falla ⇒ documento intacto."""
    def boom(*a, **kw):
        raise RuntimeError("sqlite bloqueado (simulado)")
    monkeypatch.setattr(env["gestor"], "actualizar_rotacion", boom)
    antes = env["validacion"].read_bytes()
    with pytest.raises(HTTPException) as fallo:
        _rotar()
    assert fallo.value.status_code >= 500
    assert env["validacion"].read_bytes() == antes, (
        "HIGH-02: el almacén de rotaciones falló pero el documento quedó "
        "confirmado con la geometría rotada")
    disco = _leer(env["validacion"])
    assert int(disco["revision_documento"]) == REV_INICIAL
    ocr = disco["resultados"][0]["imagenes"][0]["resultado_ocr"]
    assert not ocr.get("rotacion_manual_aplicada_grados"), (
        "HIGH-02: el documento refleja un giro que el almacén no registró")


def test_fallo_commit_restaura_rotacion_y_evidencias(env, monkeypatch):
    """Efectos aplicados + commit documental fallido ⇒ almacén restaurado."""
    monkeypatch.setattr(pdoc, "escribir_json_seguro", lambda *a, **kw: None)
    with pytest.raises(HTTPException) as fallo:
        _rotar()
    assert fallo.value.status_code == 503
    assert "no se pudo guardar" in str(fallo.value.detail).lower()
    assert not _rotaciones(env["gestor"], env["imagen"]), (
        "HIGH-02: el commit falló pero la rotación quedó en el almacén")
    disco = _leer(env["validacion"])
    assert int(disco["revision_documento"]) == REV_INICIAL


def test_doble_fallo_declara_inconsistente_y_bloquea(env, monkeypatch):
    """Commit fallido + restauración fallida ⇒ ATENCIÓN estado inconsistente
    (nunca «restaurados») y recurso bloqueado hasta resolución."""
    ruta_reg = env["tmp"] / "inconsistencias" / "estado_inconsistente.json"
    monkeypatch.setattr(backend, "RUTA_INCONSISTENCIAS", ruta_reg,
                        raising=False)
    monkeypatch.setattr(backend, "_inconsistencias_activas", {}, raising=False)
    escribir_real = pdoc.escribir_json_seguro
    monkeypatch.setattr(pdoc, "escribir_json_seguro", lambda *a, **kw: None)
    monkeypatch.setattr(env["gestor"], "restaurar_evidencias_imagen",
                        lambda snap: False)
    with pytest.raises(HTTPException) as fallo:
        _rotar()
    assert fallo.value.status_code == 503
    bajo = str(fallo.value.detail).lower()
    assert "inconsistente" in bajo and "restaurados" not in bajo, (
        f"MEDIUM-05 en rotación: mensaje debe declarar inconsistencia: "
        f"{fallo.value.detail}")
    assert ruta_reg.is_file(), "la inconsistencia debe registrarse durable"
    # Recurso bloqueado aunque la escritura del documento vuelva a sanar.
    monkeypatch.setattr(pdoc, "escribir_json_seguro", escribir_real)
    with pytest.raises(HTTPException) as bloqueo:
        _rotar()
    assert bloqueo.value.status_code == 503
    assert "inconsistente" in str(bloqueo.value.detail).lower()
    # Resolución manual ⇒ desbloqueo y operación sana.
    backend._resolver_inconsistencias(str(env["imagen"]))
    respuesta = _rotar()
    assert int(respuesta["revision_documento"]) == REV_INICIAL + 1


def test_exito_rota_documento_y_almacen_coherentes(env):
    """No regresión: con éxito, documento y almacén dicen lo mismo."""
    respuesta = _rotar(grados=90)
    assert int(respuesta["revision_documento"]) == REV_INICIAL + 1
    disco = _leer(env["validacion"])
    assert int(disco["revision_documento"]) == REV_INICIAL + 1
    ocr = disco["resultados"][0]["imagenes"][0]["resultado_ocr"]
    assert float(ocr.get("rotacion_manual_aplicada_grados") or 0) == 90.0
    guardada = _rotaciones(env["gestor"], env["imagen"])
    assert guardada and float(guardada.get("grados") or 0) == 90.0, (
        f"el almacén de rotaciones debe reflejar el giro: {guardada}")
