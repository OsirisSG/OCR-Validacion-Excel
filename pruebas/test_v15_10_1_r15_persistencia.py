"""R15 · Persistencia verificada del registro durable de revisiones (ALTA-04).

Prueba obligatoria 9 de la auditoría R14: «Persistencia de revisiones
simulada en fallo ⇒ el endpoint debe reportar error, nunca éxito».

`video_airbag._guardar_json` llamaba a `escribir_json_seguro(..., lanzar=False)`
e IGNORABA el `ResultadoPersistencia`: `guardar_revision_video` devolvía la
revisión como persistida aunque el archivo durable no se hubiera guardado
(`RETURNED_SUCCESS confirmado 10 2.0` en la reproducción del auditor). La
política de `aprendizaje_video_airbag` (ErrorPersistenciaAprendizaje) y de
`maximos_video` (lanzar=True) sí era verificada; aquí se unifica.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

import dashboard.backend.app as backend
import video_airbag
from utilidades.persistencia import ResultadoPersistencia

CASE_KEY = "PROY|1ST|HT|NOM|1001"
CLAVE = hashlib.sha256(CASE_KEY.encode("utf-8")).hexdigest()[:16]


def _fallo(ruta, data, lanzar=False, compacto=False):
    return ResultadoPersistencia(guardado=False, destino=Path(ruta),
                                 intentos=3, error="disco lleno (fallo inyectado)")


class _GestorAprendizajeStub:
    def __init__(self, config=None):
        pass

    def estado_revision(self, ambito, item_id, inicial):
        return {"estado": "pendiente", "inicial": inicial}

    def listar_alertas_atendidas(self, *a, **kw):
        return set()


@pytest.fixture
def entorno(monkeypatch, tmp_path):
    lote = tmp_path / "Lote"
    (lote / "CASO1").mkdir(parents=True)
    video = lote / "CASO1" / "n_DETAIL.AVI"
    video.write_bytes(b"RIFFdummy")
    validacion = tmp_path / "validacion_resultados.json"
    validacion.write_text(json.dumps({
        "raiz": str(lote),
        "resultados": [{
            "nombre": "CASO1", "case_key": CASE_KEY,
            "ruta": str(lote / "CASO1"), "tipo_st": "1ST", "imagenes": [],
            "videos": [{"id": "V1", "nombre": "n_DETAIL.AVI", "ruta": str(video),
                        "ruta_relativa": "CASO1/n_DETAIL.AVI",
                        "carpeta_video": "CASO1"}],
        }],
    }), encoding="utf-8")
    revisiones = tmp_path / "revisiones_video.json"

    import maximos_video

    monkeypatch.setattr(video_airbag, "RUTA_REVISIONES", revisiones)
    monkeypatch.setattr(backend, "RUTA_VALIDACION", validacion)
    monkeypatch.setattr(backend, "RUTA_ESTRUCTURA", tmp_path / "no_existe.json")
    monkeypatch.setattr(backend, "_cache", {"mtime": None, "datos": None})
    monkeypatch.setattr(backend, "_pipeline_estado",
                        copy.deepcopy(backend._pipeline_estado))
    monkeypatch.setattr(backend, "_pipeline_hilo", None)
    monkeypatch.setattr(backend, "_pipeline_reserva", None, raising=False)
    monkeypatch.setattr(backend, "_video_reanalisis_hilo", None)
    monkeypatch.setattr(backend, "CONFIG", {})
    monkeypatch.setattr(backend, "GestorAprendizaje", _GestorAprendizajeStub)
    monkeypatch.setattr(backend, "_regenerar_excel", lambda resultado: None)
    monkeypatch.setattr(backend, "_resolver_raiz_datos", lambda datos: lote)
    monkeypatch.setattr(backend, "_resolver_imagen",
                        lambda ruta, datos, raiz: Path(ruta))
    monkeypatch.setattr(backend, "_aplicar_consenso_video_a_fila",
                        lambda fila, consenso: None)
    monkeypatch.setattr(backend, "_migrar_consensos_video", lambda datos: None)
    monkeypatch.setattr(backend, "_evento_censurado_video_api", lambda item: False)
    monkeypatch.setattr(video_airbag, "normalizar_videos_caso",
                        lambda videos, config: None)
    monkeypatch.setattr(video_airbag, "consenso_videos",
                        lambda videos, config: {"tiempo_ms": None, "soporte": 0,
                                                "estado": "pendiente"})
    monkeypatch.setattr(maximos_video, "incorporar_maximos", lambda fila: None)

    yield {"lote": lote, "video": video, "validacion": validacion,
           "revisiones": revisiones, "tmp": tmp_path}


def test_guardar_revision_video_lanza_si_la_escritura_falla(entorno, monkeypatch):
    """Unidad: el helper durable NUNCA devuelve éxito con guardado=False."""
    monkeypatch.setattr(video_airbag, "escribir_json_seguro", _fallo)
    with pytest.raises(video_airbag.ErrorPersistenciaRevisiones):
        video_airbag.guardar_revision_video(
            entorno["video"], case_key=CASE_KEY, frame_index=None,
            tiempo_ms=None, estado="pendiente", usuario="tester")


def test_endpoint_revision_reporta_error_y_no_exito_si_falla_el_durable(
        entorno, monkeypatch):
    """Prueba obligatoria 9: 503 explícito; ni el durable ni el documento cambian."""
    monkeypatch.setattr(video_airbag, "escribir_json_seguro", _fallo)
    antes = entorno["validacion"].read_bytes()
    with pytest.raises(HTTPException) as exc:
        backend.revisar_video(backend.SolicitudRevisionVideo(
            prueba_id=CLAVE, video_id="V1", estado="pendiente", usuario="tester"))
    assert exc.value.status_code == 503
    assert "no se guardó" in str(exc.value.detail).lower()
    # El documento de resultados no fue tocado (la revisión no se aplica).
    assert entorno["validacion"].read_bytes() == antes


def test_revision_valida_sigue_guardando_verificado(entorno):
    """Control: sin fallo inyectado, la revisión se persiste de verdad."""
    revision = video_airbag.guardar_revision_video(
        entorno["video"], case_key=CASE_KEY, frame_index=None,
        tiempo_ms=None, estado="pendiente", usuario="tester")
    assert revision["estado"] == "pendiente"
    assert entorno["revisiones"].is_file()
    datos = json.loads(entorno["revisiones"].read_text(encoding="utf-8"))
    assert len(datos["revisiones"]) == 1
