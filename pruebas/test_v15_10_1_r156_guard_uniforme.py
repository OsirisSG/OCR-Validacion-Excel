"""R15.6 · F3 — Guard uniforme de pipeline (Causa B: ALTO-08/09/10).

Auditoría independiente R15.5:

* ALTO-08: `editar_zona` sólo comprueba `_pipeline_hilo.is_alive()` e ignora
  la reserva atómica del slot ⇒ ventana TOCTOU: acepta mutaciones entre la
  admisión del pipeline y el arranque del hilo.
* ALTO-09: `guardar_orientacion_region` tiene el mismo check local pese a su
  comentario «No cambiar preferencias mientras el pipeline está utilizando
  el modelo».
* ALTO-10: `POST /api/revisiones` acepta `estado="completada"` con el
  pipeline procesando/reservado o con reanálisis de videos en curso: la
  revisión humana queda cerrada sobre un estado que todavía no es final.
* Plan P1 (ítem 9): prueba automática que detecte writers de
  `actualizar_revision` fuera del coordinador transaccional.

Política exigida: un único guard común (hilo + reserva + estado + reanálisis)
sustituye los checks locales; `completada` se bloquea mientras el caso pueda
estar siendo modificado por el pipeline.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import HTTPException

import dashboard.backend.app as backend
from test_v15_10_1_r153_cas_efectos import (  # noqa: F401 — fixture compartido
    REV_INICIAL, env, _leer)
from test_v15_10_1_r15_1_documento_global import CLAVE
from test_v15_10_1_r156_lectura_zona import (
    _conteo, _previsualizar, _guardar_zona)

MARCO = "a" * 64
RESERVA = {"ejecucion_id": "reservado", "origen": "pipeline",
           "reservado_en": "2026-10-16T00:00:00.000"}


class _HiloVivo:
    def is_alive(self):
        return True


def _reservar(monkeypatch):
    """Ventana TOCTOU del auditor: slot reservado SIN hilo vivo todavía."""
    monkeypatch.setattr(backend, "_pipeline_hilo", None)
    monkeypatch.setattr(backend, "_pipeline_reserva", dict(RESERVA),
                        raising=False)


# ---------------------------------------------------------------------------
# ALTO-08 — edición de zonas durante la reserva
# ---------------------------------------------------------------------------


def test_editar_zona_reserva_bloquea(env, monkeypatch):
    vista = _previsualizar(env)          # con pipeline inactivo: permitida
    ediciones_antes = _conteo(env["gestor"], "ediciones_zona")
    _reservar(monkeypatch)
    with pytest.raises(HTTPException) as rechazo:
        _guardar_zona(vista["firma"])
    assert rechazo.value.status_code == 409, (
        "ALTO-08: la reserva del slot debe bloquear la edición de zonas")
    assert "procesamiento" in str(rechazo.value.detail).lower()
    assert _conteo(env["gestor"], "ediciones_zona") == ediciones_antes


def test_editar_zona_hilo_vivo_sigue_bloqueando(env, monkeypatch):
    """No-regresión: el hilo vivo (comportamiento previo) también bloquea."""
    monkeypatch.setattr(backend, "_pipeline_hilo", _HiloVivo())
    monkeypatch.setattr(backend, "_pipeline_reserva", None, raising=False)
    with pytest.raises(HTTPException) as rechazo:
        backend.editar_zona(backend.SolicitudZona(
            prueba_id=CLAVE, imagen_id="IMG1", bbox=[0, 0, 10, 10],
            accion="estado", releer=False, firma="", texto=""))
    assert rechazo.value.status_code == 409


# ---------------------------------------------------------------------------
# ALTO-09 — orientación regional durante la reserva
# ---------------------------------------------------------------------------


def _orientacion(env, monkeypatch, grados=90):
    datos = _leer(env["validacion"])
    fila = datos["resultados"][0]
    item = fila["imagenes"][0]
    monkeypatch.setattr(
        backend, "_resolver_region_orientacion",
        lambda p, i, m: (fila, item, {"bbox": [0, 0, 10, 10]}, env["imagen"]))
    return backend.guardar_orientacion_region(
        backend.SolicitudOrientacionRegional(
            prueba_id=CLAVE, imagen_id="IMG1", marco=MARCO, grados=grados))


def test_orientacion_regional_reserva_bloquea(env, monkeypatch):
    _reservar(monkeypatch)
    with pytest.raises(HTTPException) as rechazo:
        _orientacion(env, monkeypatch)
    assert rechazo.value.status_code == 409, (
        "ALTO-09: la reserva del slot debe bloquear la orientación regional")
    assert _conteo(env["gestor"], "orientaciones_region") == 0, (
        "ALTO-09: la preferencia quedó persistida durante la reserva")


def test_orientacion_regional_inactiva_guarda(env, monkeypatch):
    """No-regresión: sin pipeline, la orientación se guarda."""
    resultado = _orientacion(env, monkeypatch)
    assert resultado["guardada"] is True
    assert _conteo(env["gestor"], "orientaciones_region") == 1


# ---------------------------------------------------------------------------
# ALTO-10 — cierre de revisión como completada con pipeline activo
# ---------------------------------------------------------------------------


def _cerrar_completada():
    return backend.actualizar_revision(backend.SolicitudRevision(
        tipo="carpeta", item_id=CLAVE, estado="completada"))


def test_revision_completada_reserva_bloquea(env, monkeypatch):
    _reservar(monkeypatch)
    with pytest.raises(HTTPException) as rechazo:
        _cerrar_completada()
    assert rechazo.value.status_code == 409, (
        "ALTO-10: no se puede cerrar la revisión con el slot reservado")
    assert env["gestor"].estado_revision(
        "carpeta", CLAVE, "por_revisar")["estado"] != "completada"


def test_revision_completada_procesando_bloquea(env, monkeypatch):
    monkeypatch.setattr(backend, "_pipeline_hilo", None)
    monkeypatch.setattr(backend, "_pipeline_reserva", None, raising=False)
    backend._pipeline_estado.update({"estado": "procesando"})
    with pytest.raises(HTTPException) as rechazo:
        _cerrar_completada()
    assert rechazo.value.status_code == 409


def test_revision_completada_reanalisis_bloquea(env, monkeypatch):
    """Un reanálisis de videos en curso también impide cerrar la revisión:
    el pipeline puede estar modificando el caso (ALTO-10, reproceso)."""
    monkeypatch.setattr(backend, "_video_reanalisis_hilo", _HiloVivo())
    with pytest.raises(HTTPException) as rechazo:
        _cerrar_completada()
    assert rechazo.value.status_code == 409


def test_revision_parcial_con_reserva_no_bloquea(env, monkeypatch):
    """No-regresión: sólo el cierre «completada» exige pipeline inactivo;
    marcar avance parcial sigue permitido (comportamiento heredado)."""
    _reservar(monkeypatch)
    resultado = backend.actualizar_revision(backend.SolicitudRevision(
        tipo="carpeta", item_id=CLAVE, estado="parcial"))
    assert resultado["estado"] == "parcial"


# ---------------------------------------------------------------------------
# Plan P1 ítem 9 — inventario automático de writers bajo el coordinador
# ---------------------------------------------------------------------------


_WHITELIST_REVISION = {
    # El endpoint de revisión ES el writer de un único almacén (revisiones);
    # su atomicidad la cubre el propio gestor.
    "actualizar_revision",
    # Primitiva de compensación del coordinador (restaura, no escribe nuevo).
    "_restaurar_revision_estado",
}


def test_inventario_writers_revision_bajo_coordinador():
    """Toda función de backend que llame ``gestor.actualizar_revision`` debe
    usar el coordinador común (helper R15.6 o TransaccionMultiAlmacen), salvo
    whitelist documentada.Detecta regresiones de la Causa A del auditor."""
    raiz = Path(__file__).resolve().parents[1]
    tree = ast.parse((raiz / "dashboard" / "backend" / "app.py")
                     .read_text(encoding="utf-8"))
    infractores = []
    for fn in tree.body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        llama_revision = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "actualizar_revision"
            for n in ast.walk(fn))
        if not llama_revision or fn.name in _WHITELIST_REVISION:
            continue
        usa_tx = any(
            isinstance(n, ast.Name) and n.id in
            ("_transaccion_efecto_humano", "TransaccionMultiAlmacen")
            for n in ast.walk(fn))
        if not usa_tx:
            infractores.append(fn.name)
    assert not infractores, (
        "writers de actualización de revisión fuera del coordinador "
        f"transaccional (Causa A): {infractores}")
