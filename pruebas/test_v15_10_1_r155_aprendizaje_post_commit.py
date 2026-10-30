"""R15.5 · F1 — El aprendizaje es un efecto OPCIONAL posterior al commit (HIGH-01).

Auditoría independiente R15.4 (`AUDITORIA_INDEPENDIENTE_R15_4_20261016.md`):

* HIGH-01: `revisar_video` con estado `confirmado`, escritura real del dataset
  de eventos y fallo inyectado sólo en el commit final devolvía 503 y
  restauraba la revisión durable, PERO el ejemplo de `guardar_ejemplo_evento`
  permanecía en el dataset de aprendizaje junto con sus frames. Una petición
  que el usuario ve como fallida podía modificar el perfil aprendido y afectar
  decisiones automáticas futuras — viola «petición fallida = almacenes
  coherentes».
* Corrección preferida del auditor: tratar el aprendizaje como efecto opcional
  POSTERIOR al commit principal — (1) validar + CAS, (2) revisión durable,
  (3) commit del documento, (4) sólo si el commit fue exitoso, generar/guardar
  el ejemplo, (5) si el aprendizaje falla, devolver éxito de la revisión con
  `advertencia_aprendizaje`, sin revertir la confirmación humana.

Cada prueba verifica también el número de revisión del documento y los
archivos auxiliares (dataset JSON + directorio de frames), como pide el plan
P1 de la auditoría.
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


@pytest.fixture
def dataset(env, monkeypatch):
    """Rutas del dataset de eventos redirigidas a tmp (efecto real observable)."""
    ruta_json = env["tmp"] / "dataset" / "video_airbag_dataset.json"
    ruta_frames = env["tmp"] / "dataset" / "video_airbag_dataset"
    monkeypatch.setattr(aprendizaje_video_airbag, "RUTA_DATASET", ruta_json)
    monkeypatch.setattr(aprendizaje_video_airbag, "RUTA_DATASET_FRAMES",
                        ruta_frames)
    # Tiempo resuelto válido y estable: la resolución temporal no es la ruta
    # bajo prueba (tiene sus propias pruebas desde V15.7/R15).
    monkeypatch.setattr(video_airbag, "resolver_tiempo_frame",
                        lambda *a, **kw: {
                            "tiempo_ms": 120.0, "fps": 25.0,
                            "fps_fuente": "archivo", "overlay_valido": False,
                            "advertencia": None})
    return {"json": ruta_json, "frames": ruta_frames}


def _estado_dataset(dataset) -> tuple[int, int]:
    """(n_ejemplos en el JSON, n_archivos en el directorio de frames)."""
    ejemplos = 0
    if dataset["json"].is_file():
        ejemplos = len(json.loads(
            dataset["json"].read_text(encoding="utf-8")).get("ejemplos") or [])
    frames = (sum(1 for _ in dataset["frames"].rglob("*") if _.is_file())
              if dataset["frames"].is_dir() else 0)
    return ejemplos, frames


def _confirmar(frame_index: int = 7):
    return backend.revisar_video(backend.SolicitudRevisionVideo(
        prueba_id=CLAVE, video_id="V1", estado="confirmado",
        frame_index=frame_index, bbox_evento_norm=[0.3, 0.3, 0.5, 0.5],
        usuario="t", expected_revision=REV_INICIAL))


def test_confirmado_fallo_commit_no_entrena(env, dataset, monkeypatch):
    """Repro del auditor: commit fallido ⇒ dataset de eventos SIN cambios."""
    assert _estado_dataset(dataset) == (0, 0)
    monkeypatch.setattr(pdoc, "escribir_json_seguro", lambda *a, **kw: None)
    with pytest.raises(HTTPException) as fallo:
        _confirmar()
    assert fallo.value.status_code == 503
    ejemplos, frames = _estado_dataset(dataset)
    assert ejemplos == 0 and frames == 0, (
        f"HIGH-01: el commit falló pero el aprendizaje entrenó igual "
        f"({ejemplos} ejemplo(s), {frames} frame(s))")
    # La revisión durable tampoco sobrevive (garantía R15.4, no regresada).
    durables = video_airbag.cargar_revisiones().get("revisiones") or {}
    assert not durables, "la revisión durable sobrevivió al commit fallido"
    disco = _leer(env["validacion"])
    assert int(disco["revision_documento"]) == REV_INICIAL
    assert not disco["resultados"][0]["videos"][0].get("revision_manual")


def test_fallo_aprendizaje_devuelve_exito_con_advertencia(env, dataset,
                                                          monkeypatch):
    """Punto 5 del auditor: aprendizaje fallido ⇒ éxito de la revisión +
    `advertencia_aprendizaje`, sin revertir la confirmación humana."""
    def _reventar(*a, **kw):
        raise RuntimeError("disco lleno (simulado)")
    monkeypatch.setattr(aprendizaje_video_airbag, "guardar_ejemplo_evento",
                        _reventar)
    respuesta = _confirmar()
    assert respuesta["guardado"] is True, (
        "el fallo del dataset NO debe hacer perder la revisión manual")
    assert "disco lleno" in (respuesta.get("advertencia_aprendizaje") or ""), (
        f"debe informar la advertencia de aprendizaje: {respuesta}")
    assert respuesta.get("ejemplo_aprendido") is None
    disco = _leer(env["validacion"])
    assert int(disco["revision_documento"]) == REV_INICIAL + 1, (
        "la confirmación humana debe quedar commiteada")
    assert disco["resultados"][0]["videos"][0].get("revision_manual")
    durables = video_airbag.cargar_revisiones().get("revisiones") or {}
    assert durables, "la revisión durable debe conservarse"


def test_exito_entrena_tras_commit(env, dataset):
    """No regresión: con commit exitoso el ejemplo SÍ se entrena y la
    respuesta lo reporta; el documento y la revisión durable quedan coherentes."""
    respuesta = _confirmar()
    assert respuesta["guardado"] is True
    assert respuesta.get("advertencia_aprendizaje") is None
    assert respuesta.get("ejemplo_aprendido") is not None, (
        "el ejemplo aprendido debe reportarse en la respuesta")
    ejemplos, frames = _estado_dataset(dataset)
    assert ejemplos == 1, f"el dataset debe tener 1 ejemplo, tiene {ejemplos}"
    assert frames >= 1, "los frames derivados del ejemplo deben existir"
    disco = _leer(env["validacion"])
    assert int(disco["revision_documento"]) == REV_INICIAL + 1
    video_doc = disco["resultados"][0]["videos"][0]
    assert video_doc.get("revision_manual")
    assert video_doc.get("ultima_zona_nacimiento"), (
        "la localización de nacimiento sigue siendo parte del commit (no es "
        "efecto opcional)")


def test_pendiente_no_entrena_nunca(env, dataset):
    """Estado distinto de `confirmado` no toca el dataset (contrato previo)."""
    respuesta = backend.revisar_video(backend.SolicitudRevisionVideo(
        prueba_id=CLAVE, video_id="V1", estado="pendiente",
        usuario="t", expected_revision=REV_INICIAL))
    assert respuesta["guardado"] is True
    assert _estado_dataset(dataset) == (0, 0)
