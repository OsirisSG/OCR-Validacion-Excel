"""R15.3 · F2 — Atomicidad CAS+efectos (ALTO-02) y guarda uniforme de reserva (ALTO-03).

Auditoría independiente R15.2 (`AUDITORIA_INDEPENDIENTE_R15_2_20261015.md`):

* ALTO-02 (TOCTOU CAS): varias rutas hacen prechequeo de ``expected_revision``,
  LIBERAN el lock, ejecutan un efecto secundario durable (SQLite, registro de
  revisión, ROI aprendida) y sólo entonces hacen el commit CAS final. Una
  mutación concurrente entre el prechequeo y el commit produce 409 CON el
  efecto ya persistido: «la petición fue rechazada» no equivale a «la petición
  no produjo efectos». Rutas: ``corregir_lectura``, ``marcar_imagen_sin_datos``,
  ``revisar_video``, ``aprender_zona_video``.
  Corrección (opción mínima R15.3 del auditor): la autoridad de mutación va
  desde «lectura fresca + CAS» hasta «efecto coordinado → actualización del
  documento» en la MISMA región de exclusión; un 409 no puede emitirse después
  de un efecto irreversible sin compensación.
* ALTO-03: ``restaurar_imagen_con_texto`` sólo comprueba ``_pipeline_hilo``
  vivo e ignora ``_pipeline_reserva``: durante la ventana entre admisión y
  arranque del hilo acepta mutaciones que el pipeline está a punto de
  procesar. Corrección: ``_assert_documento_editable`` uniforme.

Pruebas obligatorias: inyectar una mutación concurrente exactamente entre
validación y commit ⇒ respuesta 409 Y CERO efectos secundarios persistentes;
con ``_pipeline_reserva`` ocupada y sin hilo vivo, TODAS las mutaciones
incompatibles responden 409.
"""
from __future__ import annotations

import copy
import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

import dashboard.backend.app as backend
import aprendizaje_video_airbag
import video_airbag
from aprendizaje import GestorAprendizaje
from test_v15_10_1_r15_1_documento_global import CASE_KEY, CLAVE

REV_INICIAL = 3


def _ocr() -> dict:
    return {"dimensiones": [100, 100], "texto_completo": "ABC",
            "tokens": [{"texto": "ABC", "bbox": [0, 0, 10, 10]}],
            "lineas_texto": [{"texto": "ABC", "bbox": [0, 0, 10, 10]}]}


def _video_sintetico(ruta: Path) -> None:
    import cv2
    import numpy as np
    writer = cv2.VideoWriter(str(ruta), cv2.VideoWriter_fourcc(*"MJPG"), 25,
                             (96, 64))
    assert writer.isOpened(), "cv2 no pudo crear el video sintético"
    for i in range(12):
        imagen = np.full((64, 96, 3), (i * 17, 40, 220 - i * 12), np.uint8)
        cv2.rectangle(imagen, (i + 5, 20), (i + 12, 30), (255, 255, 255), -1)
        writer.write(imagen)
    writer.release()


def _documento(lote: Path, imagen: Path, video: Path) -> dict:
    return {
        "raiz": str(lote), "revision_documento": REV_INICIAL,
        "resultados": [{
            "nombre": "CASO1", "case_key": CASE_KEY, "ruta": str(lote / "CASO1"),
            "tipo_st": "1ST", "perfil": "empresarial",
            "comparacion": {"resultado": "coincidencia_total"},
            "campos": {"test_number": {"valor": "1001", "estado": "confirmado"}},
            "imagenes": [{"id": "IMG1", "ruta": str(imagen),
                          "resultado_ocr": _ocr()}],
            "trazabilidad": [],
            "videos": [{"id": "V1", "nombre": "n_DETAIL.AVI", "ruta": str(video),
                        "ruta_relativa": "CASO1/n_DETAIL.AVI",
                        "carpeta_video": "CASO1"}],
        }],
    }


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Backend hermético: documento rev 3, gestor real en tmp, efectos durables
    reales (SQLite, revisiones_video.json, aprendizajes) redirigidos a tmp."""
    lote = tmp_path / "Lote"
    (lote / "CASO1").mkdir(parents=True)
    imagen = lote / "CASO1" / "img_0001.png"
    imagen.write_bytes(b"PNGdummy")
    video = lote / "CASO1" / "n_DETAIL.AVI"
    _video_sintetico(video)
    validacion = tmp_path / "validacion_resultados.json"
    validacion.write_text(json.dumps(_documento(lote, imagen, video)),
                          encoding="utf-8")
    gestor = GestorAprendizaje({"aprendizaje": {}}, directorio=str(tmp_path))

    monkeypatch.setattr(backend, "RUTA_VALIDACION", validacion)
    monkeypatch.setattr(backend, "_cache", {"mtime": None, "datos": None})
    monkeypatch.setattr(backend, "_cache_rutas_registradas",
                        {"firma": None, "rutas": set()}, raising=False)
    monkeypatch.setattr(backend, "_pipeline_estado",
                        copy.deepcopy(backend._pipeline_estado))
    backend._pipeline_estado.update({"estado": "inactivo", "ejecucion_id": None})
    monkeypatch.setattr(backend, "_pipeline_hilo", None)
    monkeypatch.setattr(backend, "_pipeline_reserva", None, raising=False)
    monkeypatch.setattr(backend, "_video_reanalisis_hilo", None)
    monkeypatch.setattr(backend, "CONFIG", {"aprendizaje": {}})
    monkeypatch.setattr(backend, "GestorAprendizaje", lambda c: gestor)
    monkeypatch.setattr(backend, "_regenerar_excel", lambda resultado: None)
    monkeypatch.setattr(backend, "_resolver_raiz_datos", lambda datos: lote)
    monkeypatch.setattr(backend, "_resolver_imagen",
                        lambda ruta, datos, raiz: Path(ruta))
    monkeypatch.setattr(backend, "_reubicar_ruta",
                        lambda ruta, datos, raiz: Path(ruta))
    monkeypatch.setattr(backend, "_dimensiones_ocr_desde_archivo",
                        lambda ruta, ocr: (100, 100))
    # Consenso/normalización: no son la ruta bajo prueba (mismo criterio que
    # test_v15_10_1_r15_revisiones.py).
    monkeypatch.setattr(video_airbag, "consenso_videos",
                        lambda videos, config: {})
    monkeypatch.setattr(backend, "_aplicar_consenso_video_a_fila",
                        lambda fila, consenso: None)
    monkeypatch.setattr(video_airbag, "analizar_video",
                        lambda ruta, config, usar_cache=False: {
                            "frame_evento": 7, "tiempo_ms": 120.0,
                            "algoritmo_video": "stub", "desde_cache": False})
    import maximos_video
    monkeypatch.setattr(maximos_video, "incorporar_maximos",
                        lambda fila: None, raising=False)
    # Efectos durables reales, redirigidos a tmp.
    monkeypatch.setattr(video_airbag, "RUTA_REVISIONES",
                        tmp_path / "revisiones_video.json")
    monkeypatch.setattr(aprendizaje_video_airbag, "RUTA_APRENDIZAJE",
                        tmp_path / "aprendizajes" / "zonas.json")
    monkeypatch.setattr(aprendizaje_video_airbag, "RUTA_REFERENCIAS",
                        tmp_path / "aprendizajes" / "referencias")

    yield {"gestor": gestor, "validacion": validacion, "imagen": imagen,
           "video": video, "tmp": tmp_path, "lote": lote}


def _leer(validacion: Path) -> dict:
    return json.loads(validacion.read_text(encoding="utf-8"))


def _instalar_carrera(monkeypatch, portador, nombre):
    """Envuelve el efecto durable y lanza la mutación concurrente justo cuando
    la ruta lo alcanza (reproducción del interleaving del auditor).

    * Código R15.2 (buggy): el lock NO está tomado ⇒ el bump completa de
      inmediato ⇒ el efecto persiste y el CAS final responde 409.
    * Código corregido: la ruta mantiene el lock del documento ⇒ el bump se
      bloquea hasta que el commit libera; la ruta responde éxito coherente.
    """
    real = getattr(portador, nombre)
    efecto_alcanzado = threading.Event()
    bump_listo = threading.Event()
    llamadas: list = []
    estado = {"rev": None, "error": None, "bloqueada": None}

    def wrapper(*args, **kwargs):
        llamadas.append((args, kwargs))
        efecto_alcanzado.set()
        bump_listo.wait(timeout=2.0)
        return real(*args, **kwargs)

    monkeypatch.setattr(portador, nombre, wrapper)

    def bump():
        if not efecto_alcanzado.wait(timeout=15):
            estado["error"] = "la ruta nunca alcanzó el efecto durable"
            bump_listo.set()
            return
        inicio = time.monotonic()
        try:
            estado["rev"], _ = backend.mutar_documento(lambda fresco: None,
                                                       None)
        except BaseException as exc:  # noqa: BLE001 — diagnóstico
            estado["error"] = exc
        finally:
            estado["bloqueada"] = (time.monotonic() - inicio) >= 1.0
            bump_listo.set()

    hilo = threading.Thread(target=bump, daemon=True)
    hilo.start()
    return {"hilo": hilo, "estado": estado, "llamadas": llamadas}


def _ejecutar_con_carrera(env, monkeypatch, portador, nombre, llamar):
    carrera = _instalar_carrera(monkeypatch, portador, nombre)
    respuesta, rechazo = None, None
    try:
        respuesta = llamar()
    except HTTPException as exc:
        rechazo = exc
    finally:
        carrera["hilo"].join(timeout=15)
    assert carrera["estado"]["error"] is None or carrera["estado"]["rev"], (
        f"el bump concurrente falló: {carrera['estado']['error']}")
    return respuesta, rechazo, carrera


def _invariante_409(respuesta, rechazo, efectos_persistidos, efecto_nombre):
    """Nunca 409 con efectos persistentes; nunca éxito sin efecto."""
    if rechazo is not None:
        assert rechazo.status_code == 409, (
            f"se esperaba 409 del CAS, llegó {rechazo.status_code}")
        assert not efectos_persistidos, (
            f"ALTO-02: la petición fue rechazada (409) pero {efecto_nombre} "
            "quedó PERSISTIDO — el prechequeo CAS no es garantía transaccional")
    else:
        assert respuesta is not None
        assert efectos_persistidos, (
            f"éxito declarado sin {efecto_nombre} persistente")


# ---------------------------------------------------------------------------
# ALTO-02 — ruta por ruta
# ---------------------------------------------------------------------------


def test_sin_datos_rechazado_no_deja_fila_sqlite(env, monkeypatch):
    def llamar():
        return backend.marcar_imagen_sin_datos(backend.SolicitudImagenSinDatos(
            tipo="carpeta", prueba_id=CLAVE, imagen_id="IMG1",
            motivo="sin texto útil", usuario="t",
            expected_revision=REV_INICIAL))

    respuesta, rechazo, _ = _ejecutar_con_carrera(
        env, monkeypatch, env["gestor"], "registrar_imagen_sin_datos", llamar)
    marca = env["gestor"].imagen_sin_datos(env["imagen"])
    _invariante_409(respuesta, rechazo, marca is not None,
                    "la marca sin-datos en SQLite")
    if rechazo is None:
        disco = _leer(env["validacion"])
        assert int(disco["revision_documento"]) >= REV_INICIAL + 1
        assert disco["resultados"][0]["imagenes"][0]["estado_imagen"] == (
            "revisada_sin_datos")


def _conteo_correcciones(gestor) -> int:
    try:
        con = gestor._conectar()
    except sqlite3.Error:
        return 0
    try:
        filas = con.execute("SELECT COUNT(*) FROM correcciones_texto").fetchone()
        return int(filas[0])
    except sqlite3.OperationalError:
        return 0  # tabla aún no creada ⇒ cero efectos
    finally:
        con.close()


def test_ocr_rechazado_no_deja_correcciones(env, monkeypatch):
    def llamar():
        return backend.corregir_lectura(backend.SolicitudCorreccion(
            prueba_id=CLAVE, imagen_id="IMG1", campo="etiqueta",
            texto_ocr="ABC", texto_correcto="A.1", bbox=[0, 0, 10, 10],
            accion="corregir", usuario="t", campo_destino="test_number",
            expected_revision=REV_INICIAL))

    respuesta, rechazo, _ = _ejecutar_con_carrera(
        env, monkeypatch, env["gestor"], "registrar_correccion", llamar)
    _invariante_409(respuesta, rechazo,
                    _conteo_correcciones(env["gestor"]) > 0,
                    "la corrección OCR en SQLite")
    if rechazo is None:
        disco = _leer(env["validacion"])
        assert int(disco["revision_documento"]) >= REV_INICIAL + 1
        fila = disco["resultados"][0]
        assert fila["campos"]["test_number"]["valor"] == "A.1"
        assert fila["imagenes"][0].get("confirmaciones_extraccion") or \
            fila.get("confirmaciones_extraccion")


def test_revisar_video_rechazado_no_deja_revision_durable(env, monkeypatch):
    def llamar():
        return backend.revisar_video(backend.SolicitudRevisionVideo(
            prueba_id=CLAVE, video_id="V1", estado="pendiente",
            usuario="t", expected_revision=REV_INICIAL))

    respuesta, rechazo, _ = _ejecutar_con_carrera(
        env, monkeypatch, video_airbag, "guardar_revision_video", llamar)
    durables = video_airbag.cargar_revisiones().get("revisiones") or {}
    _invariante_409(respuesta, rechazo, bool(durables),
                    "la revisión durable (revisiones_video.json)")
    if rechazo is None:
        disco = _leer(env["validacion"])
        assert int(disco["revision_documento"]) >= REV_INICIAL + 1
        assert disco["resultados"][0]["videos"][0].get("revision_manual")


def test_aprender_zona_rechazado_no_deja_roi(env, monkeypatch):
    def llamar():
        return backend.aprender_zona_video(backend.SolicitudZonaVideo(
            prueba_id=CLAVE, video_id="V1", bbox_norm=[0.2, 0.2, 0.6, 0.6],
            usuario="t", expected_revision=REV_INICIAL))

    respuesta, rechazo, _ = _ejecutar_con_carrera(
        env, monkeypatch, aprendizaje_video_airbag, "guardar_zona_aprendida",
        llamar)
    perfil = aprendizaje_video_airbag.perfil_zona_aprendida(env["video"])
    _invariante_409(respuesta, rechazo, perfil is not None,
                    "la ROI aprendida (aprendizajes)")
    if rechazo is None:
        disco = _leer(env["validacion"])
        assert int(disco["revision_documento"]) >= REV_INICIAL + 1


def test_aprender_zona_fallo_commit_compensa_roi(env, monkeypatch):
    """Si el commit del documento falla, la ROI ya guardada se COMPENSA
    (opción mínima del auditor: efecto coordinado o compensación)."""
    import utilidades.persistencia_documento as pdoc

    def llamar():
        return backend.aprender_zona_video(backend.SolicitudZonaVideo(
            prueba_id=CLAVE, video_id="V1", bbox_norm=[0.2, 0.2, 0.6, 0.6],
            usuario="t", expected_revision=REV_INICIAL))

    # Inyección de fallo de escritura en la autoridad compartida (contrato
    # R15.2): el guardado de la ROI usa otra ruta y NO debe verse afectado.
    monkeypatch.setattr(pdoc, "escribir_json_seguro",
                        lambda *a, **kw: None)
    with pytest.raises(Exception) as fallo:  # noqa: B017 — 500/503/EscrituraFallida
        llamar()
    exc = fallo.value
    if isinstance(exc, HTTPException):
        assert exc.status_code >= 500
    perfil = aprendizaje_video_airbag.perfil_zona_aprendida(env["video"])
    assert perfil is None, (
        "ALTO-02: el commit del documento falló pero la ROI aprendida quedó "
        "persistida sin compensación")
    # El documento no se tocó.
    disco = _leer(env["validacion"])
    assert int(disco.get("revision_documento") or 0) == REV_INICIAL


# ---------------------------------------------------------------------------
# ALTO-03 (y criterio 3) — reserva de pipeline bloquea TODAS las mutaciones
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("nombre,invocar", [
    ("campo", lambda: backend.corregir_campo_caso(
        "CLAVE", "opening_time_ms",
        backend.SolicitudCampoManual(valor="1.0", usuario="t"))),
    ("consolidar", lambda: backend.consolidar_resultados(
        backend.SolicitudConsolidacion(archivos=["/no/existe.json"],
                                       regenerar_excel=False))),
    ("ocr", lambda: backend.corregir_lectura(
        backend.SolicitudCorreccion(prueba_id="X", texto_ocr="A", usuario="t"))),
    ("rotacion", lambda: backend.guardar_rotacion(
        backend.SolicitudRotacion(tipo="carpeta", prueba_id="X",
                                  imagen_id="i", grados=90))),
    ("sin_datos", lambda: backend.marcar_imagen_sin_datos(
        backend.SolicitudImagenSinDatos(tipo="carpeta", prueba_id="X",
                                        imagen_id="i", usuario="t"))),
    ("con_texto", lambda: backend.restaurar_imagen_con_texto(
        backend.SolicitudImagenSinDatos(tipo="carpeta", prueba_id="X",
                                        imagen_id="i", usuario="t"))),
    ("verificar", lambda: backend.verificar_imagen(
        backend.SolicitudImagenVerificada(prueba_id="X", imagen_id="i",
                                          usuario="t"))),
    ("video_revision", lambda: backend.revisar_video(
        backend.SolicitudRevisionVideo(prueba_id="X", video_id="v",
                                       frame_index=1, tiempo_ms=1.0))),
    ("video_maximo", lambda: backend.confirmar_maximo_video(
        backend.SolicitudMaximoVideo(prueba_id="X", video_id="v",
                                     frame_index=1))),
    ("video_zona", lambda: backend.aprender_zona_video(
        backend.SolicitudZonaVideo(prueba_id="X", video_id="v",
                                   bbox_norm=[0.1, 0.1, 0.5, 0.5]))),
    ("video_zona_revertir", lambda: backend.revertir_zona_video(
        backend.SolicitudZonaRevertir(prueba_id="X", video_id="v"))),
    ("reanalizar", lambda: backend.reanalizar_videos(
        backend.SolicitudReanalisisVideos())),
])
def test_reserva_pipeline_bloquea_todas_las_mutaciones(env, monkeypatch,
                                                       nombre, invocar):
    """Con la reserva tomada y SIN hilo vivo (ventana entre admisión y
    arranque), ninguna mutación incompatible puede pasar (ALTO-03:
    restaurar_imagen_con_texto era la excepción en R15.2)."""
    monkeypatch.setattr(backend, "_pipeline_hilo", None)
    monkeypatch.setattr(backend, "_pipeline_reserva",
                        {"ejecucion_id": "reservado", "origen": "pipeline",
                         "reservado_en": "2026-10-15T00:00:00.000"},
                        raising=False)
    with pytest.raises(HTTPException) as rechazo:
        invocar()
    assert rechazo.value.status_code == 409, (
        f"{nombre}: se esperaba 409 por reserva de pipeline, llegó "
        f"{rechazo.value.status_code} — {rechazo.value.detail}")
