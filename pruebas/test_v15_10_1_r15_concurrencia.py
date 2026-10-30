"""R15 · Concurrencia y admisión atómica (auditoría R14: CRIT-01, ALTA-02, MEDIA-15).

Pruebas obligatorias 1-4 y 8 de `AUDITORIA_EXHAUSTIVA_V_MATRIX_R14_20261015.md`:

1. Dos ``/api/pipeline`` simultáneos ⇒ 1 aceptado + 1 rechazado (409) + UN
   solo worker.
2. ``/api/pipeline`` simultáneo con ``/api/casos/.../reprocesar`` ⇒ un solo
   worker total.
3. Dos reprocesos simultáneos ⇒ un solo worker.
4. Fallo de ``Thread.start()`` ⇒ estado vuelve a seguro, sin checkpoint
   «procesando fantasma» y el slot queda libre.
8. Pipeline activo (o reservado) + revisión/reanálisis ⇒ 409 sin efectos
   laterales; ROI y registro de proyecto sólo se persisten DESPUÉS de la
   admisión (MEDIA-15/ALTA-02).

Estas pruebas se llaman al nivel de la función endpoint (mismo camino que
recorre TestClient) para poder ensanchar la ventana de carrera con un
checkpoint lento, igual que hizo el auditor.
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

RAIZ = Path(__file__).resolve().parents[1]

CASE_KEY = "PROY|1ST|HT|NOM|1001"
CLAVE = hashlib.sha256(CASE_KEY.encode("utf-8")).hexdigest()[:16]


def _solicitud_pipeline(ruta: Path) -> backend.SolicitudPipeline:
    return backend.SolicitudPipeline(ruta=str(ruta), nombre_excel="salida.xlsx")


def _solicitud_reproceso(**kw) -> backend.SolicitudReproceso:
    return backend.SolicitudReproceso(**kw)


class _GestorRecursosStub:
    def configurar(self, *_a, **_kw):
        return None

    def snapshot(self, forzar=False):
        return {}


@pytest.fixture
def entorno(monkeypatch, tmp_path):
    """Backend hermético: datos mínimos, worker espía y checkpoint lento."""
    lote = tmp_path / "Lote"
    (lote / "CASO1").mkdir(parents=True)
    validacion = tmp_path / "validacion_resultados.json"
    validacion.write_text(json.dumps({
        "raiz": str(lote),
        "resultados": [{
            "nombre": "CASO1", "case_key": CASE_KEY,
            "ruta": str(lote / "CASO1"), "tipo_st": "1ST",
            "imagenes": [{"ruta": str(lote / "CASO1" / "a.png"),
                          "fase": "ETIQUETA"}],
            "videos": [],
        }],
    }), encoding="utf-8")

    workers: list = []
    persistidos: list = []
    retraso = [0.2]

    def worker_fondo(**kwargs):
        workers.append(kwargs.get("ejecucion_id") or "reproceso")
        time.sleep(0.3)

    def persistir_checkpoint():
        # Ensancha deliberadamente la ventana entre el lock y el arranque
        # del hilo (el auditor reprodujo CRIT-01 exactamente así) y registra
        # el estado visible en cada persistencia.
        time.sleep(retraso[0])
        persistidos.append(backend._pipeline_estado.get("estado"))
        return True

    monkeypatch.setattr(backend, "RUTA_VALIDACION", validacion)
    monkeypatch.setattr(backend, "RUTA_ESTRUCTURA", tmp_path / "no_existe.json")
    monkeypatch.setattr(backend, "_cache", {"mtime": None, "datos": None})
    monkeypatch.setattr(backend, "_cache_rutas_registradas",
                        {"firma": None, "rutas": set()})
    # R15.1 (BAJO-11): hermeticidad — no se copia el estado global tal cual.
    # En una instalación usada el checkpoint .cache_ocr/estado_pipeline.json
    # puede dejar estado="completado" al importar el backend, y la prueba de
    # fallo de Thread.start() daba falso rojo al exigir "inactivo". Se fija
    # un estado inicial SEGURO conocido, conservando la estructura de claves.
    _estado_inicial = copy.deepcopy(backend._pipeline_estado)
    _estado_inicial.update({"estado": "inactivo", "ejecucion_id": None})
    monkeypatch.setattr(backend, "_pipeline_estado", _estado_inicial)
    monkeypatch.setattr(backend, "_pipeline_hilo", None)
    monkeypatch.setattr(backend, "_pipeline_reserva", None, raising=False)
    monkeypatch.setattr(backend, "_video_reanalisis_hilo", None)
    monkeypatch.setattr(backend, "_capacidad_pipeline",
                        lambda: {"listo": True, "recursos": {}})
    monkeypatch.setattr(
        backend, "_resolver_instantanea_para_ejecucion",
        lambda ejecucion_id, rango: {"verde_max": 6.0, "amarillo_max": 7.0,
                                     "origen": "predeterminado"})
    monkeypatch.setattr(backend, "_persistir_checkpoint_pipeline",
                        persistir_checkpoint)
    monkeypatch.setattr(backend, "_ejecutar_pipeline_fondo", worker_fondo)
    monkeypatch.setattr(backend, "_regenerar_excel", lambda resultado: None)
    monkeypatch.setattr(backend, "obtener_gestor_recursos",
                        lambda perfil: _GestorRecursosStub())

    import utilidades.proyectos as proyectos_mod
    registros: list = []
    ejecuciones: list = []
    monkeypatch.setattr(
        proyectos_mod, "registrar_proyecto",
        lambda *a, **kw: registros.append((a, kw)))
    monkeypatch.setattr(
        proyectos_mod, "registrar_ejecucion",
        lambda *a, **kw: ejecuciones.append((a, kw)))

    yield {"lote": lote, "workers": workers, "persistidos": persistidos,
           "retraso": retraso, "registros": registros,
           "ejecuciones": ejecuciones, "tmp": tmp_path}


def _lanzar_en_paralelo(llamadas):
    """Ejecuta funciones en hilos y devuelve (resultados, excepciones)."""
    resultados: list = [None] * len(llamadas)
    errores: list = [None] * len(llamadas)
    barrera = threading.Barrier(len(llamadas))

    def envolver(i, fn):
        def _run():
            try:
                barrera.wait(timeout=5)
                resultados[i] = fn()
            except BaseException as exc:  # noqa: BLE001 — se clasifica abajo
                errores[i] = exc
        return _run

    hilos = [threading.Thread(target=envolver(i, fn))
             for i, fn in enumerate(llamadas)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=15)
    return resultados, errores


def _clasificar(resultados, errores):
    aceptados = [r for r, e in zip(resultados, errores) if e is None]
    rechazados = [e for e in errores
                  if isinstance(e, HTTPException) and e.status_code == 409]
    otros = [e for e in errores
             if e is not None and not (isinstance(e, HTTPException)
                                       and e.status_code == 409)]
    return aceptados, rechazados, otros


# ---------------------------------------------------------------------------
# Prueba obligatoria 1 (y variante con 10 solicitudes)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [2, 5, 10])
def test_pipelines_simultaneos_un_solo_worker(entorno, n):
    lote = entorno["lote"]
    resultados, errores = _lanzar_en_paralelo(
        [lambda: backend.iniciar_pipeline(_solicitud_pipeline(lote))] * n)
    aceptados, rechazados, otros = _clasificar(resultados, errores)
    time.sleep(0.05)
    assert not otros, f"errores inesperados: {otros}"
    assert len(aceptados) == 1, f"{len(aceptados)} solicitudes aceptadas"
    assert len(rechazados) == n - 1
    assert len(entorno["workers"]) == 1, (
        f"WORKERS_STARTED {len(entorno['workers'])} — pipeline doble (CRIT-01)")


# ---------------------------------------------------------------------------
# Pruebas obligatorias 2 y 3
# ---------------------------------------------------------------------------


def test_pipeline_y_reproceso_simultaneos_un_solo_worker(entorno):
    lote = entorno["lote"]
    resultados, errores = _lanzar_en_paralelo([
        lambda: backend.iniciar_pipeline(_solicitud_pipeline(lote)),
        lambda: backend.reprocesar_caso(CLAVE, _solicitud_reproceso()),
    ])
    aceptados, rechazados, otros = _clasificar(resultados, errores)
    assert not otros, otros
    assert len(aceptados) == 1
    assert len(rechazados) == 1
    assert len(entorno["workers"]) == 1


def test_dos_reprocesos_simultaneos_un_solo_worker(entorno):
    resultados, errores = _lanzar_en_paralelo(
        [lambda: backend.reprocesar_caso(CLAVE, _solicitud_reproceso())] * 2)
    aceptados, rechazados, otros = _clasificar(resultados, errores)
    assert not otros, otros
    assert len(aceptados) == 1
    assert len(rechazados) == 1
    assert len(entorno["workers"]) == 1


# ---------------------------------------------------------------------------
# Prueba obligatoria 4 — fallo de Thread.start()
# ---------------------------------------------------------------------------


def test_fallo_thread_start_deja_estado_seguro_y_slot_libre(entorno, monkeypatch):
    lote = entorno["lote"]
    entorno["retraso"][0] = 0.0
    hilo_real = threading.Thread

    class ThreadFalla(hilo_real):
        def start(self):
            raise RuntimeError("arranque simulado fallido")

    monkeypatch.setattr(backend.threading, "Thread", ThreadFalla)
    with pytest.raises(HTTPException) as falla:
        backend.iniciar_pipeline(_solicitud_pipeline(lote))
    monkeypatch.setattr(backend.threading, "Thread", hilo_real)
    assert falla.value.status_code == 500

    # Estado seguro: sin «procesando fantasma» ni reserva colgada.
    assert backend._pipeline_estado.get("estado") == "inactivo"
    assert getattr(backend, "_pipeline_reserva", None) is None
    assert backend._pipeline_hilo is None
    if entorno["persistidos"]:
        assert entorno["persistidos"][-1] != "procesando", (
            "el último checkpoint persistido quedó en procesando fantasma")

    # El slot queda libre: una solicitud posterior válida se acepta.
    respuesta = backend.iniciar_pipeline(_solicitud_pipeline(lote))
    assert respuesta["aceptado"] is True
    time.sleep(0.05)
    assert len(entorno["workers"]) == 1


# ---------------------------------------------------------------------------
# Prueba obligatoria 8 / MEDIA-15 / ALTA-02 — efectos laterales TRAS admisión
# ---------------------------------------------------------------------------


def test_reproceso_rechazado_no_guarda_roi(entorno, monkeypatch):
    """ALTA-02: la preferencia ROI no puede persistir si la solicitud acaba
    en 409."""
    import aprendizaje
    guardadas: list = []
    monkeypatch.setattr(
        aprendizaje.GestorAprendizaje, "guardar_roi_preferida",
        lambda self, *a, **kw: guardadas.append((a, kw)))
    # Slot ocupado por una reserva ajena.
    backend._pipeline_reserva = {"ejecucion_id": "otra-ejecucion"}
    try:
        with pytest.raises(HTTPException) as rechazo:
            backend.reprocesar_caso(CLAVE, _solicitud_reproceso(
                modo_recorte="manual",
                roi_manual={"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}))
        assert rechazo.value.status_code == 409
        assert guardadas == [], "ROI persistida por una solicitud rechazada"
    finally:
        backend._pipeline_reserva = None


def test_inicio_rechazado_no_registra_proyecto(entorno):
    """MEDIA-15: registrar/crear identidad de proyecto es un efecto
    persistente y debe ocurrir sólo después de adquirir el slot."""
    proyecto = backend.ProyectoSolicitud(nombre_proyecto="Proyecto R15")
    backend._pipeline_reserva = {"ejecucion_id": "otra-ejecucion"}
    try:
        with pytest.raises(HTTPException) as rechazo:
            backend.iniciar_pipeline(backend.SolicitudPipeline(
                ruta=str(entorno["lote"]), nombre_excel="salida.xlsx",
                proyecto=proyecto))
        assert rechazo.value.status_code == 409
        assert entorno["registros"] == [], (
            "proyecto registrado por una solicitud rechazada")
    finally:
        backend._pipeline_reserva = None


def test_reanalisis_activo_bloquea_inicio_de_pipeline(entorno):
    """Plan R15 #2: procesamiento y reanálisis simultáneos ⇒ imposibles."""
    ocupado = threading.Thread(target=time.sleep, args=(0.6,), daemon=True)
    ocupado.start()
    backend._video_reanalisis_hilo = ocupado
    try:
        with pytest.raises(HTTPException) as rechazo:
            backend.iniciar_pipeline(_solicitud_pipeline(entorno["lote"]))
        assert rechazo.value.status_code == 409
        assert entorno["workers"] == []
    finally:
        backend._video_reanalisis_hilo = None
        ocupado.join(timeout=5)


def test_pipeline_reservado_bloquea_reanalisis(entorno):
    """La reserva atómica también cierra la puerta al reanálisis de vídeos."""
    backend._pipeline_reserva = {"ejecucion_id": "admision-en-curso"}
    try:
        with pytest.raises(HTTPException) as rechazo:
            backend.reanalizar_videos(backend.SolicitudReanalisisVideos())
        assert rechazo.value.status_code == 409
    finally:
        backend._pipeline_reserva = None
