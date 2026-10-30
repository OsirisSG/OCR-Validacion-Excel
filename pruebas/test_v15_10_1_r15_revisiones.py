"""R15 · Mutaciones de video: guards, revisión completada y versionado CAS.

Auditoría R14 — Fase 2 (ALTA-03 + ALTA-07 + MEDIA-14). Pruebas obligatorias:

5. Reanálisis en curso + corrección manual ⇒ la corrección NO se pierde
   (el reanálisis aplica un merge por video sobre el documento más reciente,
   nunca reescribe el snapshot completo).
6. Reanálisis en curso + revisión/ROI ⇒ 409.
7. Revisión completada + request desde pestaña vieja ⇒ 409 en
   ``/api/video/revision``, ``zona-aprendizaje`` y ``zona-revertir``.
8. Pipeline activo (o slot reservado) + revisión/ROI video ⇒ 409 sin ningún
   efecto lateral.
18. Detalle/mutación con ``expected_revision`` antigua ⇒ 409 y recarga.

Se llama al nivel de la función endpoint (mismo camino que TestClient).
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

import dashboard.backend.app as backend

CASE_KEY = "PROY|1ST|HT|NOM|1001"
CLAVE = hashlib.sha256(CASE_KEY.encode("utf-8")).hexdigest()[:16]


class _HiloVivo:
    def is_alive(self):
        return True

    def start(self):
        pass

    def join(self, timeout=None):
        time.sleep(0.01)


class _GestorAprendizajeStub:
    """Sustituto de GestorAprendizaje; el estado de revisión es configurable."""
    estado = "pendiente"

    def __init__(self, config=None):
        pass

    def estado_revision(self, ambito, item_id, inicial):
        return {"estado": type(self).estado, "inicial": inicial}

    def listar_anotaciones(self, *a, **kw):
        return []

    def listar_correcciones_texto(self, *a, **kw):
        return []

    def listar_rotaciones(self, *a, **kw):
        return []

    def listar_alertas_atendidas(self, *a, **kw):
        return set()


def _documento(lote: Path, video: Path) -> dict:
    return {
        "raiz": str(lote),
        "resultados": [{
            "nombre": "CASO1", "case_key": CASE_KEY,
            "ruta": str(lote / "CASO1"), "tipo_st": "1ST",
            "imagenes": [],
            "videos": [{
                "id": "V1", "nombre": "n_DETAIL.AVI", "ruta": str(video),
                "ruta_relativa": "CASO1/n_DETAIL.AVI",
                "carpeta_video": "CASO1",
            }],
        }],
    }


@pytest.fixture
def entorno_video(monkeypatch, tmp_path):
    """Backend hermético con un caso y un video real (contenido dummy)."""
    lote = tmp_path / "Lote"
    (lote / "CASO1").mkdir(parents=True)
    video = lote / "CASO1" / "n_DETAIL.AVI"
    video.write_bytes(b"RIFFdummy")
    validacion = tmp_path / "validacion_resultados.json"
    validacion.write_text(json.dumps(_documento(lote, video)), encoding="utf-8")

    _GestorAprendizajeStub.estado = "pendiente"
    revisiones_guardadas: list = []

    def guardar_revision_video_stub(ruta, **kw):
        revisiones_guardadas.append((ruta, kw))
        return {"estado": kw.get("estado"), "frame_index": kw.get("frame_index"),
                "tiempo_ms": kw.get("tiempo_ms"), "usuario": kw.get("usuario"),
                "guardado": True}

    analizar_llamadas: list = []
    retraso_analizar = [0.0]

    def analizar_video_stub(ruta, config, usar_cache=False):
        analizar_llamadas.append(str(ruta))
        if retraso_analizar[0]:
            time.sleep(retraso_analizar[0])
        return {"frame_evento": 7, "tiempo_ms": 120.0,
                "algoritmo_video": "stub", "desde_cache": False}

    import aprendizaje_video_airbag
    import maximos_video
    import video_airbag

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
    monkeypatch.setattr(backend, "_reubicar_ruta",
                        lambda ruta, datos, raiz: Path(ruta))
    monkeypatch.setattr(backend, "_aplicar_consenso_video_a_fila",
                        lambda fila, consenso: fila.update(
                            {"video_apertura": {"estado": "pendiente",
                                                "tiempo_ms": None, "soporte": 0}}))
    monkeypatch.setattr(backend, "_migrar_consensos_video", lambda datos: None)
    monkeypatch.setattr(backend, "_evento_censurado_video_api", lambda item: False)
    monkeypatch.setattr(video_airbag, "normalizar_videos_caso",
                        lambda videos, config: None)
    monkeypatch.setattr(video_airbag, "consenso_videos",
                        lambda videos, config: {"tiempo_ms": None, "soporte": 0,
                                                "estado": "pendiente"})
    monkeypatch.setattr(video_airbag, "guardar_revision_video",
                        guardar_revision_video_stub)
    monkeypatch.setattr(video_airbag, "analizar_video", analizar_video_stub)
    monkeypatch.setattr(maximos_video, "incorporar_maximos", lambda fila: None)
    monkeypatch.setattr(aprendizaje_video_airbag, "guardar_zona_aprendida",
                        lambda ruta, bbox, **kw: {"zona": "stub", "bbox": bbox})
    monkeypatch.setattr(aprendizaje_video_airbag, "resumen_aprendizajes",
                        lambda *a, **kw: {})
    monkeypatch.setattr(aprendizaje_video_airbag, "revertir_zona_aprendida",
                        lambda ruta, **kw: {"zona": "revertida"})
    monkeypatch.setattr(aprendizaje_video_airbag, "perfil_zona_aprendida",
                        lambda ruta: None)
    monkeypatch.setattr(aprendizaje_video_airbag, "historial_zona_aprendida",
                        lambda ruta: [])
    monkeypatch.setattr(aprendizaje_video_airbag, "restaurar_perfil_zona",
                        lambda ruta, perfil: None)

    yield {"lote": lote, "video": video, "validacion": validacion,
           "revisiones": revisiones_guardadas, "analizar": analizar_llamadas,
           "retraso_analizar": retraso_analizar, "tmp": tmp_path}


def _leer(validacion: Path) -> dict:
    return json.loads(validacion.read_text(encoding="utf-8"))


def _solicitud_revision(**kw) -> backend.SolicitudRevisionVideo:
    base = {"prueba_id": CLAVE, "video_id": "V1", "estado": "pendiente",
            "usuario": "tester"}
    base.update(kw)
    return backend.SolicitudRevisionVideo(**base)


def _solicitud_zona(**kw) -> backend.SolicitudZonaVideo:
    base = {"prueba_id": CLAVE, "video_id": "V1",
            "bbox_norm": [0.1, 0.1, 0.5, 0.5], "usuario": "tester"}
    base.update(kw)
    return backend.SolicitudZonaVideo(**base)


# ---------------------------------------------------------------------------
# Prueba obligatoria 8 — pipeline activo/reservado + revisión/ROI ⇒ 409
# ---------------------------------------------------------------------------

def test_revision_bloqueada_con_pipeline_activo(entorno_video, monkeypatch):
    monkeypatch.setattr(backend, "_pipeline_hilo", _HiloVivo())
    antes = entorno_video["validacion"].read_bytes()
    with pytest.raises(HTTPException) as exc:
        backend.revisar_video(_solicitud_revision())
    assert exc.value.status_code == 409
    assert entorno_video["validacion"].read_bytes() == antes
    assert entorno_video["revisiones"] == []


def test_zonas_bloqueadas_con_reserva_de_pipeline(entorno_video, monkeypatch):
    monkeypatch.setattr(backend, "_pipeline_reserva",
                        {"ejecucion_id": "e1", "origen": "pipeline"})
    with pytest.raises(HTTPException) as exc:
        backend.aprender_zona_video(_solicitud_zona())
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        backend.revertir_zona_video(
            backend.SolicitudZonaRevertir(prueba_id=CLAVE, video_id="V1"))
    assert exc.value.status_code == 409
    assert entorno_video["revisiones"] == []


# ---------------------------------------------------------------------------
# Prueba obligatoria 6 — reanálisis en curso + revisión/ROI ⇒ 409
# ---------------------------------------------------------------------------

def test_revision_bloqueada_con_reanalisis_activo(entorno_video, monkeypatch):
    monkeypatch.setattr(backend, "_video_reanalisis_hilo", _HiloVivo())
    with pytest.raises(HTTPException) as exc:
        backend.revisar_video(_solicitud_revision())
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        backend.aprender_zona_video(_solicitud_zona())
    assert exc.value.status_code == 409
    assert entorno_video["revisiones"] == []


# ---------------------------------------------------------------------------
# Prueba obligatoria 7 — revisión completada + pestaña vieja ⇒ 409 (ALTA-07)
# ---------------------------------------------------------------------------

def test_revision_completada_bloquea_ediciones_de_video(entorno_video):
    _GestorAprendizajeStub.estado = "completada"
    with pytest.raises(HTTPException) as exc:
        backend.revisar_video(_solicitud_revision())
    assert exc.value.status_code == 409
    assert "reabre" in str(exc.value.detail).lower()
    with pytest.raises(HTTPException) as exc:
        backend.aprender_zona_video(_solicitud_zona())
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        backend.revertir_zona_video(
            backend.SolicitudZonaRevertir(prueba_id=CLAVE, video_id="V1"))
    assert exc.value.status_code == 409
    assert entorno_video["revisiones"] == []


# ---------------------------------------------------------------------------
# Prueba obligatoria 18 — expected_revision antigua ⇒ 409 (MEDIA-14)
# ---------------------------------------------------------------------------

def test_expected_revision_antigua_devuelve_409(entorno_video):
    r1 = backend.revisar_video(_solicitud_revision())
    assert "revision_documento" in r1
    revision_inicial = r1["revision_documento"]

    r2 = backend.revisar_video(
        _solicitud_revision(expected_revision=revision_inicial))
    assert r2["revision_documento"] > revision_inicial

    with pytest.raises(HTTPException) as exc:
        backend.revisar_video(
            _solicitud_revision(expected_revision=revision_inicial))
    assert exc.value.status_code == 409
    assert "recarga" in str(exc.value.detail).lower()

    # Zona-aprendizaje participa del mismo versionado.
    with pytest.raises(HTTPException) as exc:
        backend.aprender_zona_video(
            _solicitud_zona(expected_revision=revision_inicial))
    assert exc.value.status_code == 409


def test_detalle_expone_revision_documento(entorno_video):
    r1 = backend.revisar_video(_solicitud_revision())
    detalle_json = backend.detalle(CLAVE)
    assert detalle_json["revision_documento"] == r1["revision_documento"]


# ---------------------------------------------------------------------------
# Prueba obligatoria 5 — merge del reanálisis: la edición manual sobrevive
# (ALTA-03)
# ---------------------------------------------------------------------------

def test_edicion_manual_durante_reanalisis_sobrevive(entorno_video, monkeypatch):
    entorno_video["retraso_analizar"][0] = 0.5
    validacion = entorno_video["validacion"]

    fallo: list = []

    def worker():
        try:
            backend._reanalizar_videos_fondo(prueba_id=CLAVE, video_id="V1")
        except BaseException as exc:  # noqa: BLE001
            fallo.append(exc)

    hilo = threading.Thread(target=worker, daemon=True)
    hilo.start()
    # Espera a que el reanálisis esté dentro de analizar_video (durmiendo).
    for _ in range(200):
        if entorno_video["analizar"]:
            break
        time.sleep(0.01)
    assert entorno_video["analizar"], "el reanálisis no llegó a analizar el video"

    # Edición manual concurrente (simula un endpoint de corrección que
    # reescribe el documento): debe sobrevivir al commit del reanálisis.
    with backend._lock_documento():  # R15.2: autoridad compartida
        datos = backend._leer_documento_disco()
        datos["resultados"][0]["campo_corregido_manual"] = "valor_humano"
        revision = backend._commit_documento(datos)
    assert revision >= 1

    hilo.join(timeout=15)
    assert not fallo, f"el worker falló: {fallo}"

    final = _leer(validacion)
    fila = final["resultados"][0]
    video = fila["videos"][0]
    # Merge: la edición manual NO fue arrasada por el snapshot viejo...
    assert fila.get("campo_corregido_manual") == "valor_humano"
    # ...y el reanálisis SÍ aplicó su patch por video.
    assert video.get("frame_evento") == 7
    assert video.get("reanalizado_en")
    assert final.get("video_reanalizado_en")
    assert int(final.get("revision_documento") or 0) > revision
