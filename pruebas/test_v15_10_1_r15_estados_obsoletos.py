"""R15 · Limpieza de estados obsoletos tras cambio/reversión de ROI (ALTA-06).

Prueba obligatoria 10 de la auditoría R14: «ROI candidato→sin_evento ⇒ no
sobreviven frame_evento/tiempo_ms viejos».

R14 hacía ``video_item.update(nuevo)`` sin ``clear()``: las claves que el
nuevo análisis ya no incluye (p. ej. ``frame_evento``/``tiempo_ms`` de una
detección anterior) seguían dentro del objeto, y el frontend abría el video
``sin_evento`` situado en el breakout viejo. El reanálisis global ya usaba el
patrón correcto (conservar metadatos → clear → nuevo → reponer). Los
endpoints de ROI deben hacer lo mismo, conservando ADEMÁS los datos humanos
(revision_manual, ultima_zona_nacimiento): cero pérdida de trabajo manual.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import dashboard.backend.app as backend

CASE_KEY = "PROY|1ST|HT|NOM|1001"
CLAVE = hashlib.sha256(CASE_KEY.encode("utf-8")).hexdigest()[:16]

CAMPOS_HUMANOS = {
    "revision_manual": {"estado": "confirmado", "frame_index": 12,
                        "tiempo_ms": 2.4, "usuario": "humano"},
    "ultima_zona_nacimiento": {"bbox_norm": [0.2, 0.2, 0.4, 0.4],
                               "frame_index": 12, "metodo": "manual_dashboard"},
}
CAMPOS_OBSOLETOS = {
    "estado": "candidato", "frame_evento": 30, "tiempo_ms": 6.0,
    "algoritmo_video": "viejo", "desde_cache": True,
    "tiempo_overlay_ms": 5.0, "fuente_tiempo": "overlay_rec",
}


class _GestorAprendizajeStub:
    def __init__(self, config=None):
        pass

    def estado_revision(self, ambito, item_id, inicial):
        return {"estado": "pendiente", "inicial": inicial}

    def listar_alertas_atendidas(self, *a, **kw):
        return set()


class _CapturaStub:
    """cv2.VideoCapture stub: primer cuadro decodificable."""

    def __init__(self, ruta):
        self.ruta = ruta

    def read(self):
        return True, object()

    def release(self):
        pass


@pytest.fixture
def entorno_roi(monkeypatch, tmp_path):
    lote = tmp_path / "Lote"
    (lote / "CASO1").mkdir(parents=True)
    video = lote / "CASO1" / "n_DETAIL.AVI"
    video.write_bytes(b"RIFFdummy")
    item = {"id": "V1", "nombre": "n_DETAIL.AVI", "ruta": str(video),
            "ruta_relativa": "CASO1/n_DETAIL.AVI", "carpeta_video": "CASO1"}
    item.update(copy.deepcopy(CAMPOS_OBSOLETOS))
    item.update(copy.deepcopy(CAMPOS_HUMANOS))
    validacion = tmp_path / "validacion_resultados.json"
    validacion.write_text(json.dumps({
        "raiz": str(lote),
        "resultados": [{
            "nombre": "CASO1", "case_key": CASE_KEY,
            "ruta": str(lote / "CASO1"), "tipo_st": "1ST", "imagenes": [],
            "videos": [item],
        }],
    }), encoding="utf-8")

    import aprendizaje_video_airbag
    import cv2
    import maximos_video
    import video_airbag

    def analizar_sin_evento(ruta, config, usar_cache=False):
        # El nuevo análisis NO incluye frame_evento/tiempo_ms (sin evento).
        return {"estado": "sin_evento", "algoritmo_video": "nuevo",
                "zona_deteccion": {"bbox_norm": [0.1, 0.1, 0.5, 0.5]}}

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
    monkeypatch.setattr(video_airbag, "analizar_video", analizar_sin_evento)
    monkeypatch.setattr(video_airbag, "consenso_videos",
                        lambda videos, config: {"tiempo_ms": None, "soporte": 0,
                                                "estado": "pendiente"})
    monkeypatch.setattr(maximos_video, "incorporar_maximos", lambda fila: None)
    monkeypatch.setattr(cv2, "VideoCapture", _CapturaStub)
    monkeypatch.setattr(aprendizaje_video_airbag, "guardar_zona_aprendida",
                        lambda ruta, bbox, **kw: {"zona": "stub", "bbox": bbox})
    monkeypatch.setattr(aprendizaje_video_airbag, "resumen_aprendizajes",
                        lambda *a, **kw: {})
    monkeypatch.setattr(aprendizaje_video_airbag, "revertir_zona_aprendida",
                        lambda ruta, **kw: {"zona": "revertida"})
    monkeypatch.setattr(aprendizaje_video_airbag, "perfil_zona_aprendida",
                        lambda ruta: {"bbox_norm": [0.1, 0.1, 0.5, 0.5]})
    monkeypatch.setattr(aprendizaje_video_airbag, "historial_zona_aprendida",
                        lambda ruta: [])
    monkeypatch.setattr(aprendizaje_video_airbag, "restaurar_perfil_zona",
                        lambda ruta, perfil: None)

    yield {"validacion": validacion, "tmp": tmp_path}


def _video_persistido(validacion: Path) -> dict:
    datos = json.loads(validacion.read_text(encoding="utf-8"))
    return datos["resultados"][0]["videos"][0]


def _assert_sin_obsoletos_con_humanos(video: dict):
    assert video["estado"] == "sin_evento"
    assert video["algoritmo_video"] == "nuevo"
    # Campos obsoletos de la detección anterior: AUSENTES.
    for campo in ("frame_evento", "tiempo_ms", "tiempo_overlay_ms",
                  "fuente_tiempo", "desde_cache"):
        assert campo not in video, f"campo obsoleto sobrevivió: {campo}={video[campo]}"
    # Metadatos de inventario: conservados.
    assert video["id"] == "V1"
    assert video["ruta_relativa"] == "CASO1/n_DETAIL.AVI"
    assert video["carpeta_video"] == "CASO1"
    # Datos humanos: INTACTOS (cero pérdida de trabajo manual). El
    # normalizador legacy puede ENRIQUECER revision_manual con campos
    # doctrinales adicionales; se verifica que ningún valor humano se perdió.
    revision = video["revision_manual"]
    for clave, valor in CAMPOS_HUMANOS["revision_manual"].items():
        assert revision[clave] == valor, f"datos humanos perdidos: {clave}"
    zona = video["ultima_zona_nacimiento"]
    for clave, valor in CAMPOS_HUMANOS["ultima_zona_nacimiento"].items():
        assert zona[clave] == valor, f"datos humanos perdidos: {clave}"


def test_zona_aprendizaje_limpia_estados_obsoletos(entorno_roi):
    backend.aprender_zona_video(backend.SolicitudZonaVideo(
        prueba_id=CLAVE, video_id="V1", bbox_norm=[0.1, 0.1, 0.5, 0.5],
        usuario="tester"))
    _assert_sin_obsoletos_con_humanos(_video_persistido(entorno_roi["validacion"]))


def test_zona_revertir_limpia_estados_obsoletos(entorno_roi):
    backend.revertir_zona_video(backend.SolicitudZonaRevertir(
        prueba_id=CLAVE, video_id="V1", indice=0, usuario="tester"))
    _assert_sin_obsoletos_con_humanos(_video_persistido(entorno_roi["validacion"]))
