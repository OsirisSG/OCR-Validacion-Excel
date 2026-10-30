"""R15.4 · F3 — Checkpoint histórico no puede presentarse como actual (MEDIUM-03).

Auditoría independiente R15.3 (`AUDITORIA_INDEPENDIENTE_R15_3_20261015.md`):

* MEDIUM-03: ``/api/pruebas`` recurre a ``resultados_parciales`` del
  checkpoint cuando ``validacion_resultados.json`` no existe. Si el checkpoint
  pertenece a una corrida FINALIZADA y falta el documento oficial, el endpoint
  devuelve resultados viejos como si fueran actuales (reproducido con el
  checkpoint histórico del ZIP de auditoría).
* Corrección pedida: permitir el fallback a parciales ÚNICAMENTE cuando el
  pipeline está realmente procesando, detenido de forma recuperable o en
  reanudación explícita; si no, devolver un estado claro de recuperación/error.
  Y devolver ``fuente=checkpoint_recuperacion`` para que el frontend lo
  comunique.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import dashboard.backend.app as backend
from test_v15_10_1_r153_cas_efectos import env, _leer  # noqa: F401 — fixture


def _llamar_listado():
    return backend.pruebas(q="", estado="", limit=200, offset=0,
                           incluir_ocultos=False)


def _sembrar_parciales(env, monkeypatch, estado_pipeline: str):
    """Documento oficial ausente + checkpoint con una fila parcial pública."""
    disco = _leer(env["validacion"])
    fila_publica = backend._fila_publica(disco["resultados"][0])
    fila_publica["origen"] = "carpeta"
    fila_publica["nombre"] = "PARCIAL-VIEJO"
    env["validacion"].unlink()  # el documento oficial desaparece
    backend._cache.update({"mtime": None, "datos": None})
    monkeypatch.setattr(backend, "_pipeline_hilo", None)
    monkeypatch.setattr(backend, "_pipeline_reserva", None, raising=False)
    backend._pipeline_estado.update({
        "estado": estado_pipeline,
        "ejecucion_id": "ckpt-20261014",
        "porcentaje": 100.0 if estado_pipeline == "completado" else 40.0,
        "reanudable": estado_pipeline == "detenido_con_avance",
        "resultados_parciales": [fila_publica],
    })


def test_checkpoint_completado_sin_documento_no_muestra_parciales(env, monkeypatch):
    """El escenario del auditor: corrida finalizada + documento ausente."""
    _sembrar_parciales(env, monkeypatch, "completado")
    with pytest.raises(HTTPException) as fallo:
        _llamar_listado()
    assert fallo.value.status_code == 503, (
        f"MEDIUM-03: se esperaba un estado claro de recuperación (503), llegó "
        f"{fallo.value.status_code}")
    detalle = str(fallo.value.detail).lower()
    assert "checkpoint" in detalle and "no se muestran" in detalle, (
        f"el mensaje debe explicar que los parciales no se muestran: {detalle}")


@pytest.mark.parametrize("estado", ["procesando", "pausado", "reanudando",
                                    "detenido_con_avance"])
def test_checkpoint_en_curso_permite_parciales_con_fuente(env, monkeypatch, estado):
    _sembrar_parciales(env, monkeypatch, estado)
    respuesta = _llamar_listado()
    assert respuesta["total"] == 1
    assert respuesta["fuente"] == "checkpoint_recuperacion", (
        "el frontend necesita la fuente explícita para comunicarlo")
    assert respuesta["items"][0].get("fuente") == "checkpoint_recuperacion"


def test_documento_presente_fuente_documento(env, monkeypatch):
    respuesta = _llamar_listado()
    assert respuesta["total"] >= 1
    assert respuesta["fuente"] == "documento"
    assert "revision_documento" in respuesta


def test_documento_presente_ignora_parciales_de_corrida_finalizada(env, monkeypatch):
    """Con documento oficial, un checkpoint 'completado' no pisa las filas."""
    disco = _leer(env["validacion"])
    fila_publica = backend._fila_publica(disco["resultados"][0])
    fila_publica["origen"] = "carpeta"
    fila_publica["nombre"] = "PARCIAL-VIEJO"
    backend._pipeline_estado.update({
        "estado": "completado", "ejecucion_id": "ckpt-viejo",
        "resultados_parciales": [fila_publica]})
    respuesta = _llamar_listado()
    assert respuesta["fuente"] == "documento"
    nombres = [i.get("nombre") for i in respuesta["items"]]
    assert "PARCIAL-VIEJO" not in nombres, (
        "MEDIUM-03: un parcial de corrida finalizada no debe tapar al documento")


def test_sin_documento_ni_parciales_404(env, monkeypatch):
    env["validacion"].unlink()
    backend._cache.update({"mtime": None, "datos": None})
    backend._pipeline_estado.update({"estado": "inactivo",
                                     "resultados_parciales": []})
    with pytest.raises(HTTPException) as fallo:
        _llamar_listado()
    assert fallo.value.status_code == 404
