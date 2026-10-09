"""Máximo visible: feedback durable, identidad por contenido y API aislada."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

import maximos_video as maximos
from utilidades.persistencia import AdvertenciaPersistencia


@pytest.fixture
def feedback(tmp_path, monkeypatch):
    ruta = tmp_path / "aprendizaje" / "maximos_video.json"
    monkeypatch.setattr(maximos, "RUTA_MAXIMOS", ruta)
    monkeypatch.setattr(maximos, "_cache", {"marca": None, "datos": None})
    monkeypatch.setattr(maximos, "_firmas", {})
    return ruta


def guardar(ruta, frame=7, fps=10000.0, tiempo=None):
    return maximos.guardar_maximo(
        ruta, frame_index=frame, usuario="prueba", case_key="P|1ST|1",
        tiempo_resuelto={"tiempo_ms": frame / fps * 1000 if tiempo is None else tiempo,
                         "fps": fps, "fuente_tiempo": "fps_real", "overlay_valido": False})


def test_permiso_temporal_reintenta_y_conserva_historial(feedback, tmp_path, monkeypatch):
    video = tmp_path / "camara.avi"
    video.write_bytes(b"video para identidad")
    anterior = guardar(video, frame=5)
    reemplazo_real = os.replace
    llamadas = []

    def ocupado_temporal(origen, destino):
        llamadas.append(str(destino))
        if len(llamadas) < 3:
            raise PermissionError("ocupado temporalmente")
        return reemplazo_real(origen, destino)

    monkeypatch.setattr("utilidades.persistencia.os.replace", ocupado_temporal)
    monkeypatch.setattr("utilidades.persistencia.time.sleep", lambda _segundos: None)
    nueva = guardar(video, frame=7)
    assert len(llamadas) == 3
    assert maximos.revision_maximo(video)["frame_index"] == 7
    datos = json.loads(feedback.read_text(encoding="utf-8"))
    assert datos["historial"] == [anterior, nueva]
    assert not list(feedback.parent.glob("*.tmp"))


def test_permiso_permanente_conserva_json_y_revision_anterior(feedback, tmp_path, monkeypatch):
    video = tmp_path / "camara.avi"
    video.write_bytes(b"video previo")
    anterior = guardar(video, frame=5)
    bytes_anteriores = feedback.read_bytes()
    monkeypatch.setattr("utilidades.persistencia.os.replace",
                        lambda *_args: (_ for _ in ()).throw(PermissionError("ocupado")))
    monkeypatch.setattr("utilidades.persistencia.time.sleep", lambda _segundos: None)
    with pytest.warns(AdvertenciaPersistencia), pytest.raises(PermissionError):
        guardar(video, frame=8)
    assert feedback.read_bytes() == bytes_anteriores
    assert maximos.revision_maximo(video) == anterior
    assert not list(feedback.parent.glob("*.tmp"))


def test_sha_completo_reutiliza_video_movido_y_detecta_cambio_intermedio_grande(
        feedback, tmp_path):
    contenido = b"A" * (3 * 1024 * 1024)
    video = tmp_path / "camara.avi"
    video.write_bytes(contenido)
    revision = guardar(video)
    assert revision["firma"] == "sha256-" + hashlib.sha256(contenido).hexdigest()
    nueva_carpeta = tmp_path / "otro_equipo"
    nueva_carpeta.mkdir()
    copia = nueva_carpeta / "nombre_diferente.avi"
    shutil.copy2(video, copia)
    assert maximos.revision_maximo(copia) == revision
    stat_previo = copia.stat()
    modificado = bytearray(contenido)
    modificado[len(modificado) // 2] = ord("B")
    copia.write_bytes(modificado)
    os.utime(copia, ns=(stat_previo.st_atime_ns, stat_previo.st_mtime_ns))
    assert maximos.revision_maximo(copia) is None
    assert maximos.revision_maximo(video) == revision
    fila = {"videos": [{"ruta": str(copia), "despliegue_maximo": deepcopy(revision)}]}
    maximos.incorporar_maximos(fila)
    assert fila["videos"][0]["despliegue_maximo"]["estado"] == "archivo_modificado"


def test_feedback_sobrevive_reproceso_y_no_modifica_apertura_ni_inflado(feedback, tmp_path):
    video = tmp_path / "camara.avi"
    video.write_bytes(b"contenido inmutable")
    revision = guardar(video)
    campos = {"opening_time_ms": {"valor": "0.3", "estado": "confirmado_manual"},
              "full_inflation_time_ms": {"valor": "1.7", "estado": "confirmado_manual"}}
    apertura = {"estado": "confirmado", "frame_index": 3, "tiempo_ms": .3}
    # Simula un resultado completamente nuevo del analizador, sin el máximo.
    reproceso = {"campos": deepcopy(campos), "video_apertura": {"tiempo_ms": .3},
                 "videos": [{"ruta": str(video), "revision_manual": deepcopy(apertura)}]}
    maximos.incorporar_maximos(reproceso)
    assert reproceso["videos"][0]["despliegue_maximo"] == revision
    assert reproceso["campos"] == campos
    assert reproceso["video_apertura"] == {"tiempo_ms": .3}
    assert reproceso["videos"][0]["revision_manual"] == apertura
    reproceso["videos"][0]["revision_manual"]["frame_index"] = 9
    maximos.incorporar_maximos(reproceso)
    assert reproceso["videos"][0]["despliegue_maximo"]["estado"] == "revisar_orden_temporal"
    assert maximos.revision_maximo(video) == revision


@pytest.mark.parametrize("estado_apertura", ["sin_evento", "pendiente"])
def test_maximo_requiere_revision_si_apertura_pierde_confirmacion(feedback, tmp_path, estado_apertura):
    ruta = tmp_path / "camara.avi"
    ruta.write_bytes(b"mismo video")
    revision = guardar(ruta)
    campos = {"opening_time_ms": {"valor": ".3"}, "full_inflation_time_ms": {"valor": "1.2"}}
    apertura = {"estado": estado_apertura, "frame_index": 3}
    fila = {"campos": deepcopy(campos), "videos": [{"ruta": str(ruta),
        "revision_manual": deepcopy(apertura)}]}
    maximos.incorporar_maximos(fila)
    actual = fila["videos"][0]["despliegue_maximo"]
    assert actual["estado"] == "revisar_apertura"
    assert actual["requiere_revision"] is True
    assert actual["frame_index"] == revision["frame_index"]
    assert fila["campos"] == campos
    assert fila["videos"][0]["revision_manual"] == apertura
    assert maximos.revision_maximo(ruta) == revision


def test_maximo_requiere_revision_si_cambia_fps_grabacion(feedback, tmp_path):
    ruta = tmp_path / "camara.avi"
    ruta.write_bytes(b"mismo video")
    revision = guardar(ruta, frame=7, fps=1000)
    fila = {"videos": [{"ruta": str(ruta), "fps_grabacion": 2000, "fps": 2000,
        "fps_fuente": "config_forzado", "revision_manual": {"estado": "confirmado", "frame_index": 3}}]}
    maximos.incorporar_maximos(fila)
    actual = fila["videos"][0]["despliegue_maximo"]
    assert actual["estado"] == "revisar_origen_temporal"
    assert actual["requiere_revision"] is True
    assert actual["tiempo_ms"] == revision["tiempo_ms"]
    assert maximos.revision_maximo(ruta) == revision


def test_maximo_requiere_revision_si_cambia_offset_temporal(feedback, tmp_path):
    ruta = tmp_path / "camara.avi"
    ruta.write_bytes(b"mismo video")
    revision = maximos.guardar_maximo(ruta, frame_index=7, usuario="prueba",
        tiempo_resuelto={"tiempo_ms": 7, "fps": 1000, "timestamp_inicial_ms": 0,
                         "fuente_tiempo": "fps_real"})
    fila = {"videos": [{"ruta": str(ruta), "fps_grabacion": 1000, "fps": 1000,
        "fps_fuente": "config_forzado", "overlay_timestamp_inicial_ms": 10,
        "revision_manual": {"estado": "confirmado", "frame_index": 3}}]}
    maximos.incorporar_maximos(fila)
    actual = fila["videos"][0]["despliegue_maximo"]
    assert actual["estado"] == "revisar_origen_temporal"
    assert actual["requiere_revision"] is True
    assert actual["timestamp_inicial_ms"] == 0
    assert maximos.revision_maximo(ruta) == revision


@pytest.mark.parametrize("disponible", [True, False])
def test_fps_ausente_y_video_offline_conservan_evidencia_confirmada(feedback, tmp_path, disponible):
    ruta = tmp_path / "camara.avi"
    ruta.write_bytes(b"video que conserva evidencia portable")
    revision = guardar(ruta, fps=1000)
    if not disponible:
        ruta.rename(tmp_path / "video_movido.avi")
    fila = {"videos": [{"ruta": str(ruta), "despliegue_maximo": deepcopy(revision),
                        "revision_manual": {"estado": "confirmado", "frame_index": 3}}]}
    maximos.incorporar_maximos(fila)
    assert fila["videos"][0]["despliegue_maximo"] == revision


@pytest.mark.parametrize("metadatos,estado", [
    ({"revision_manual": {"estado": "sin_evento"}}, "revisar_apertura"),
    ({"revision_manual": {"estado": "pendiente"}}, "revisar_apertura"),
    ({"revision_manual": {"estado": "confirmado", "frame_index": 9}}, "revisar_orden_temporal"),
    ({"fps_grabacion": 2000, "fps": 2000, "fps_fuente": "config_forzado"}, "revisar_origen_temporal"),
    ({"overlay_timestamp_inicial_ms": 10}, "revisar_origen_temporal"),
])
def test_video_offline_no_ignora_contradicciones_explicitas(feedback, tmp_path, metadatos, estado):
    ruta = tmp_path / "camara.avi"
    ruta.write_bytes(b"video luego trasladado a otro equipo")
    revision = maximos.guardar_maximo(ruta, frame_index=7, usuario="prueba",
        tiempo_resuelto={"tiempo_ms": 7, "fps": 1000, "timestamp_inicial_ms": 0,
                         "fuente_tiempo": "fps_real"})
    ruta.rename(tmp_path / "video_en_otro_equipo.avi")
    fila = {"videos": [{"ruta": str(ruta), "despliegue_maximo": deepcopy(revision),
                        **deepcopy(metadatos)}]}
    maximos.incorporar_maximos(fila)
    actual = fila["videos"][0]["despliegue_maximo"]
    assert actual["estado"] == estado
    assert actual["requiere_revision"] is True
    assert actual["frame_index"] == revision["frame_index"]
    assert actual["tiempo_ms"] == revision["tiempo_ms"]
    assert json.loads(feedback.read_text(encoding="utf-8"))["revisiones"][revision["firma"]] == revision


@pytest.mark.parametrize("frame", [-1, True, 1.5, "2", None])
def test_frame_invalido_no_persiste(feedback, tmp_path, frame):
    video = tmp_path / "camara.avi"
    video.write_bytes(b"video")
    with pytest.raises(ValueError):
        guardar(video, frame=frame, tiempo=.5)
    assert not feedback.exists()


@pytest.mark.parametrize("fps", [0, -2, float("nan"), float("inf"), None])
def test_fps_invalido_no_persiste(feedback, tmp_path, fps):
    video = tmp_path / "camara.avi"
    video.write_bytes(b"video")
    with pytest.raises(ValueError):
        guardar(video, fps=fps, tiempo=.5)
    assert not feedback.exists()


@pytest.mark.parametrize("tiempo", [float("nan"), float("inf"), -1, True])
def test_tiempo_invalido_no_persiste(feedback, tmp_path, tiempo):
    video = tmp_path / "camara.avi"
    video.write_bytes(b"video")
    with pytest.raises(ValueError):
        guardar(video, tiempo=tiempo)
    assert not feedback.exists()


@pytest.fixture
def api(feedback, tmp_path, monkeypatch):
    import dashboard.backend.app as backend
    import video_airbag
    from aprendizaje import GestorAprendizaje

    raiz = tmp_path / "lote"
    raiz.mkdir()
    video = raiz / "camara.avi"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 25, (96, 64))
    assert writer.isOpened()
    for i in range(12):
        imagen = np.full((64, 96, 3), (i * 17, 40, 220 - i * 12), np.uint8)
        cv2.rectangle(imagen, (i + 5, 20), (i + 12, 30), (255, 255, 255), -1)
        writer.write(imagen)
    writer.release()
    fila = {"case_key": "P|1ST|1", "campos": {
                "opening_time_ms": {"valor": "0.2"}, "full_inflation_time_ms": {"valor": "1.2"}},
            "videos": [{"id": "camara", "ruta": str(video), "fps": 10000,
                        "revision_manual": {"estado": "confirmado", "frame_index": 2, "tiempo_ms": .2}}]}
    datos = {"raiz": str(raiz), "resultados": [fila]}
    config = {"aprendizaje": {"directorio": str(tmp_path / "db")},
              "dashboard": {"raiz_datos_permitida": str(raiz)}}
    gestor = GestorAprendizaje(config)
    ruta_resultados = tmp_path / "validacion_resultados.json"
    ruta_resultados.write_bytes(b"resultado primario que no debe reescribirse")
    monkeypatch.setattr(backend, "CONFIG", config)
    monkeypatch.setattr(backend, "RUTA_VALIDACION", ruta_resultados)
    monkeypatch.setattr(backend, "_cargar_datos", lambda: datos)
    monkeypatch.setattr(backend, "_resolver_raiz_datos", lambda _datos: raiz.resolve())
    monkeypatch.setattr(backend, "_fila_publica", lambda _fila: {"revision": {"estado": "por_revisar"}})
    monkeypatch.setattr(backend, "GestorAprendizaje", lambda _config: gestor)
    monkeypatch.setattr(backend, "_pipeline_estado", {"estado": "inactivo"})
    monkeypatch.setattr(backend, "_video_reanalisis_hilo", None)
    monkeypatch.setattr(backend, "_cache", {"mtime": None, "datos": None})
    monkeypatch.setattr(backend, "_cache_rutas_registradas", {"firma": None, "rutas": set()})
    # El cierre del TestClient ejecuta el lifespan del dashboard. Se aísla su
    # checkpoint general, además de la escritura primaria prohibida abajo.
    monkeypatch.setattr(backend, "_persistir_checkpoint_pipeline", lambda: True)
    monkeypatch.setattr(backend, "_cola_excel", SimpleNamespace(iniciar=lambda: None, detener=lambda: None))
    monkeypatch.setattr(video_airbag, "fps_real_item", lambda _item: 10000)
    monkeypatch.setattr(video_airbag, "resolver_tiempo_frame", lambda _ruta, frame, **_kw: {
        "tiempo_ms": frame / 10, "fps": 10000, "fuente_tiempo": "fps_real"})
    exportaciones = []
    monkeypatch.setattr(backend, "_regenerar_excel", lambda resultado: exportaciones.append(deepcopy(resultado)))
    monkeypatch.setattr(backend, "escribir_json_seguro", lambda *_a, **_kw: pytest.fail(
        "El endpoint de máximo no debe reescribir resultados primarios."))
    payload = {"prueba_id": backend._id_fila(fila), "video_id": "camara", "frame_index": 7}
    with TestClient(backend.app) as cliente:
        yield {"cliente": cliente, "backend": backend, "gestor": gestor, "fila": fila,
               "video": video, "payload": payload, "resultados": ruta_resultados,
               "exportaciones": exportaciones}


def test_api_maximo_exito_sin_escribir_cache_y_reutilizable(api):
    anterior = deepcopy(api["fila"])
    bytes_previos = api["resultados"].read_bytes()
    respuesta = api["cliente"].post("/api/video/maximo", json=api["payload"])
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["guardado"] is True
    assert respuesta.json()["despliegue_maximo"]["tiempo_ms"] == .7
    assert api["fila"] == anterior
    assert api["resultados"].read_bytes() == bytes_previos
    assert len(api["exportaciones"]) == 1
    nueva = deepcopy(anterior)
    maximos.incorporar_maximos(nueva)
    assert nueva["videos"][0]["despliegue_maximo"]["frame_index"] == 7
    assert nueva["campos"] == anterior["campos"]


def test_api_revision_completada_exige_reabrir(api, feedback):
    api["gestor"].actualizar_revision("carpeta", api["payload"]["prueba_id"], estado="completada")
    respuesta = api["cliente"].post("/api/video/maximo", json=api["payload"])
    assert respuesta.status_code == 409
    assert "Reabre" in respuesta.json()["detail"]
    assert not feedback.exists()


@pytest.mark.parametrize("estado", ["procesando", "pausando", "pausado", "cancelando", "reanudando"])
def test_api_procesamiento_activo_bloquea_confirmacion(api, feedback, estado):
    api["backend"]._pipeline_estado["estado"] = estado
    assert api["cliente"].post("/api/video/maximo", json=api["payload"]).status_code == 409
    assert not feedback.exists()


def test_api_exige_ruptura_confirmada_y_orden_temporal(api, feedback):
    payload = {**api["payload"], "frame_index": 1}
    assert api["cliente"].post("/api/video/maximo", json=payload).status_code == 422
    api["fila"]["videos"][0]["revision_manual"] = {"estado": "pendiente"}
    assert api["cliente"].post("/api/video/maximo", json=api["payload"]).status_code == 409
    assert not feedback.exists()


@pytest.mark.parametrize("frame,estado", [(12, 416), (-1, 422), (True, 422), (1.5, 422)])
def test_api_frame_fuera_de_rango_o_invalido(api, feedback, frame, estado):
    respuesta = api["cliente"].post("/api/video/maximo", json={**api["payload"], "frame_index": frame})
    assert respuesta.status_code == estado
    assert not feedback.exists()


def test_api_permiso_permanente_devuelve_503_y_conserva_maximo(api, monkeypatch):
    anterior = guardar(api["video"], frame=5)
    monkeypatch.setattr("utilidades.persistencia.os.replace",
                        lambda *_args: (_ for _ in ()).throw(PermissionError("ocupado")))
    monkeypatch.setattr("utilidades.persistencia.time.sleep", lambda _segundos: None)
    with pytest.warns(AdvertenciaPersistencia):
        respuesta = api["cliente"].post("/api/video/maximo", json=api["payload"])
    assert respuesta.status_code == 503
    assert maximos.revision_maximo(api["video"]) == anterior
    assert not api["exportaciones"]


def test_api_rechaza_fps_no_finito(api, feedback, monkeypatch):
    monkeypatch.setattr("video_airbag.resolver_tiempo_frame", lambda *_a, **_kw: {
        "tiempo_ms": .7, "fps": float("nan")})
    respuesta = api["cliente"].post("/api/video/maximo", json=api["payload"])
    assert respuesta.status_code == 422
    assert not feedback.exists()


def test_png_contiene_exactamente_el_cuadro_solicitado(api):
    cap = cv2.VideoCapture(str(api["video"]))
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, 8)
        ok, esperado = cap.read()
        assert ok
    finally:
        cap.release()
    respuesta = api["cliente"].get("/api/video/frame", params={"ruta": str(api["video"]), "frame": 8})
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"] == "image/png"
    assert respuesta.headers["cache-control"] == "no-store"
    recibido = cv2.imdecode(np.frombuffer(respuesta.content, np.uint8), cv2.IMREAD_COLOR)
    assert np.array_equal(recibido, esperado)
    assert api["cliente"].get("/api/video/frame", params={"ruta": str(api["video"]), "frame": 12}).status_code == 416
