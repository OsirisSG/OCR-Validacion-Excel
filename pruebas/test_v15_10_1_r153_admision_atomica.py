"""R15.3 · F1 — Admisión atómica pipeline/reanálisis + rollback de Thread.start().

Auditoría independiente R15.2 (`AUDITORIA_INDEPENDIENTE_R15_2_20261015.md`):

* CRÍTICO-01: ``reanalizar_videos`` comprueba el pipeline bajo
  ``_pipeline_lock``, lo LIBERA, y sólo después toma
  ``_video_reanalisis_lock`` para admitir. Entre ambas secciones
  ``iniciar_pipeline`` puede ser admitido ⇒ los dos procesos quedan activos a
  la vez. Corrección exigida: una ÚNICA región atómica con el mismo orden de
  locks que ``iniciar_pipeline`` (``_pipeline_lock → _video_reanalisis_lock``)
  que cubra validación, reserva de estado, creación del hilo, transición a
  «preparando» y arranque (o rollback si ``start()`` falla).
* MEDIO-05: si ``Thread.start()`` lanza, el reanálisis queda en estado
  fantasma («preparando» + ``_video_reanalisis_hilo`` apuntando a un hilo
  muerto). Corrección exigida: try/except con rollback (hilo=None, estado
  seguro, ``ultimo_error`` visible) — mismo criterio que el pipeline
  (``_rollback_admision_pipeline``, prueba obligatoria 4 de R15).

Prueba obligatoria del auditor: dos threads reales intentando simultáneamente
iniciar pipeline y reanálisis ⇒ EXACTAMENTE UNO aceptado (criterio 1: 100+
carreras).
"""
from __future__ import annotations

import copy
import hashlib
import json
import random
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


def _solicitud_reanalisis() -> backend.SolicitudReanalisisVideos:
    return backend.SolicitudReanalisisVideos(prueba_id=None, video_id=None)


class _GestorRecursosStub:
    def configurar(self, *_a, **_kw):
        return None

    def snapshot(self, forzar=False):
        return {}


@pytest.fixture
def entorno(monkeypatch, tmp_path):
    """Backend hermético con workers espía (mismo patrón que r15_concurrencia)."""
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
    reanalisis: list = []

    def worker_fondo(**kwargs):
        workers.append(kwargs.get("ejecucion_id") or "pipeline")
        time.sleep(0.05)

    def reanalisis_fondo(prueba_id, video_id):
        # Vivo el tiempo suficiente para que la admisión del otro extremo
        # lo observe (is_alive()) durante la carrera.
        reanalisis.append((prueba_id, video_id))
        time.sleep(0.4)

    monkeypatch.setattr(backend, "RUTA_VALIDACION", validacion)
    monkeypatch.setattr(backend, "RUTA_ESTRUCTURA", tmp_path / "no_existe.json")
    monkeypatch.setattr(backend, "_cache", {"mtime": None, "datos": None})
    monkeypatch.setattr(backend, "_cache_rutas_registradas",
                        {"firma": None, "rutas": set()})
    estado_inicial = copy.deepcopy(backend._pipeline_estado)
    estado_inicial.update({"estado": "inactivo", "ejecucion_id": None})
    monkeypatch.setattr(backend, "_pipeline_estado", estado_inicial)
    monkeypatch.setattr(backend, "_pipeline_hilo", None)
    monkeypatch.setattr(backend, "_pipeline_reserva", None, raising=False)
    monkeypatch.setattr(backend, "_video_reanalisis_hilo", None)
    estado_reanalisis_inicial = copy.deepcopy(backend._video_reanalisis_estado)
    estado_reanalisis_inicial.update({"estado": "inactivo", "ultimo_error": None})
    monkeypatch.setattr(backend, "_video_reanalisis_estado",
                        estado_reanalisis_inicial)
    monkeypatch.setattr(backend, "_capacidad_pipeline",
                        lambda: {"listo": True, "recursos": {}})
    monkeypatch.setattr(
        backend, "_resolver_instantanea_para_ejecucion",
        lambda ejecucion_id, rango: {"verde_max": 6.0, "amarillo_max": 7.0,
                                     "origen": "predeterminado"})
    monkeypatch.setattr(backend, "_persistir_checkpoint_pipeline", lambda: True)
    monkeypatch.setattr(backend, "_ejecutar_pipeline_fondo", worker_fondo)
    monkeypatch.setattr(backend, "_reanalizar_videos_fondo", reanalisis_fondo)
    monkeypatch.setattr(backend, "_regenerar_excel", lambda resultado: None)
    monkeypatch.setattr(backend, "obtener_gestor_recursos",
                        lambda perfil: _GestorRecursosStub())

    import utilidades.proyectos as proyectos_mod
    monkeypatch.setattr(proyectos_mod, "registrar_proyecto",
                        lambda *a, **kw: None)
    monkeypatch.setattr(proyectos_mod, "registrar_ejecucion",
                        lambda *a, **kw: None)

    yield {"lote": lote, "workers": workers, "reanalisis": reanalisis,
           "tmp": tmp_path}


def _reset_slots():
    backend._pipeline_hilo = None
    backend._pipeline_reserva = None
    backend._video_reanalisis_hilo = None
    backend._pipeline_estado.update({"estado": "inactivo", "ejecucion_id": None})


def _lanzar_en_paralelo(llamadas):
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
        h.join(timeout=20)
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
# CRÍTICO-01 — reproducción determinista del interleaving del auditor
# ---------------------------------------------------------------------------


def test_ventana_forzada_doble_admision_reanalisis_pipeline(entorno, monkeypatch):
    """Interleaving exacto del auditor:

    1. reanálisis comprueba que el pipeline está libre y LIBERA
       ``_pipeline_lock``;
    2. antes de que admita bajo ``_video_reanalisis_lock``, se inicia el
       pipeline y queda aceptado;
    3. el reanálisis continúa y también queda aceptado.

    Con la corrección (región única) el paso 2 es imposible: o el pipeline
    ve el reanálisis ya admitido, o el reanálisis ve la reserva del pipeline.
    """
    lote = entorno["lote"]
    hilo_reanalisis: list = []
    ventana = threading.Event()
    permiso = threading.Event()
    lock_real = backend._pipeline_lock
    estado_pausa = {"usada": False}

    class LockConPausa:
        """Proxy de ``_pipeline_lock``: la PRIMERA liberación hecha por el
        hilo de reanálisis abre la ventana de carrera (avisa y espera)."""

        def __enter__(self):
            return lock_real.__enter__()

        def __exit__(self, *args):
            resultado = lock_real.__exit__(*args)
            if (threading.current_thread() is hilo_reanalisis[0]
                    and not estado_pausa["usada"]):
                estado_pausa["usada"] = True
                ventana.set()
                if not permiso.wait(timeout=10):
                    raise RuntimeError("permiso no concedido (deadlock de prueba)")
            return resultado

        def __getattr__(self, nombre):
            return getattr(lock_real, nombre)

    def llamar_reanalisis():
        hilo_reanalisis.append(threading.current_thread())
        return backend.reanalizar_videos(_solicitud_reanalisis())

    monkeypatch.setattr(backend, "_pipeline_lock", LockConPausa())
    aceptados_pipeline: list = []
    errores_pipeline: list = []

    def llamar_pipeline():
        try:
            aceptados_pipeline.append(
                backend.iniciar_pipeline(_solicitud_pipeline(lote)))
        except BaseException as exc:  # noqa: BLE001
            errores_pipeline.append(exc)

    t1 = threading.Thread(target=lambda: _envolver_reanalisis(llamar_reanalisis))
    resultados_reanalisis: list = []
    errores_reanalisis: list = []

    def _envolver_reanalisis(fn):
        try:
            resultados_reanalisis.append(fn())
        except BaseException as exc:  # noqa: BLE001
            errores_reanalisis.append(exc)

    t1.start()
    assert ventana.wait(timeout=10), "el reanálisis nunca abrió la ventana"
    # Ventana abierta: el reanálisis ya comprobó y (en código R15.2) aún no
    # admitió. Intentamos colar el pipeline.
    t2 = threading.Thread(target=llamar_pipeline)
    t2.start()
    t2.join(timeout=20)
    permiso.set()
    t1.join(timeout=20)

    aceptados = len(resultados_reanalisis) + len(aceptados_pipeline)
    rechazados_409 = sum(
        1 for e in errores_reanalisis + errores_pipeline
        if isinstance(e, HTTPException) and e.status_code == 409)
    otros = [e for e in errores_reanalisis + errores_pipeline
             if not (isinstance(e, HTTPException) and e.status_code == 409)]
    assert not otros, f"errores inesperados: {otros}"
    assert aceptados == 1, (
        f"DOBLE ADMISIÓN: {aceptados} aceptados (pipeline="
        f"{len(aceptados_pipeline)}, reanálisis={len(resultados_reanalisis)}) "
        "— CRÍTICO-01: la ventana entre locks permite iniciar ambos")
    assert rechazados_409 == 1
    # Un solo worker real de cada tipo como máximo y coherente con el ganador.
    assert len(entorno["workers"]) + len(entorno["reanalisis"]) == 1


# ---------------------------------------------------------------------------
# Criterio 1 — 100+ carreras concurrentes: un solo ganador siempre
# ---------------------------------------------------------------------------


def test_carrera_admision_100_iteraciones_un_solo_ganador(entorno):
    lote = entorno["lote"]
    rng = random.Random(153)
    ganadores = {"pipeline": 0, "reanalisis": 0}
    for i in range(100):
        _reset_slots()
        jitter_a = rng.uniform(0.0, 0.002)
        jitter_b = rng.uniform(0.0, 0.002)

        def pedir_pipeline():
            time.sleep(jitter_a)
            return backend.iniciar_pipeline(_solicitud_pipeline(lote))

        def pedir_reanalisis():
            time.sleep(jitter_b)
            return backend.reanalizar_videos(_solicitud_reanalisis())

        resultados, errores = _lanzar_en_paralelo([pedir_pipeline,
                                                   pedir_reanalisis])
        aceptados, rechazados, otros = _clasificar(resultados, errores)
        assert not otros, f"carrera {i}: errores inesperados {otros}"
        assert len(aceptados) == 1, (
            f"carrera {i}: {len(aceptados)} admitidos — CRÍTICO-01")
        assert len(rechazados) == 1
        if resultados[0] is not None:
            ganadores["pipeline"] += 1
        else:
            ganadores["reanalisis"] += 1
    # El azar debe permitir ganar a ambos lados en 100 carreras.
    assert ganadores["pipeline"] > 0 and ganadores["reanalisis"] > 0, ganadores


# ---------------------------------------------------------------------------
# MEDIO-05 — fallo de Thread.start() en reanálisis: nunca estado fantasma
# ---------------------------------------------------------------------------


def test_fallo_thread_start_reanalisis_estado_seguro(entorno, monkeypatch):
    hilo_real = threading.Thread

    class ThreadFalla(hilo_real):
        def start(self):
            raise RuntimeError("arranque simulado fallido")

    monkeypatch.setattr(backend.threading, "Thread", ThreadFalla)
    try:
        with pytest.raises(HTTPException) as falla:
            backend.reanalizar_videos(_solicitud_reanalisis())
    finally:
        monkeypatch.setattr(backend.threading, "Thread", hilo_real)

    assert falla.value.status_code == 500, (
        "el fallo de start() debe responder 500 explícito, no filtrar el "
        "RuntimeError crudo")
    # Estado seguro: sin «preparando fantasma» ni hilo muerto referenciado.
    assert backend._video_reanalisis_hilo is None, (
        "MEDIO-05: _video_reanalisis_hilo apunta a un hilo no iniciado")
    estado = backend._video_reanalisis_estado
    assert estado.get("estado") != "preparando", (
        "MEDIO-05: estado fantasma «preparando» sin hilo vivo")
    assert "arranque simulado fallido" in str(estado.get("ultimo_error") or ""), (
        "el fallo debe quedar visible en ultimo_error")

    # El slot de reanálisis queda libre: un reintento real se acepta.
    respuesta = backend.reanalizar_videos(_solicitud_reanalisis())
    assert respuesta["aceptado"] is True
    assert backend._video_reanalisis_hilo is not None
    time.sleep(0.05)
    assert len(entorno["reanalisis"]) == 1
