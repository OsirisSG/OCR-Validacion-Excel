"""R15.2 · P0 — Autoridad única de escritura del documento de resultados.

Auditoría independiente R15.1 (2026-10-15):

* CRÍTICO-01: ``_migrar_consensos_video`` recibe el snapshot cacheado, lo
  modifica FUERA del lock y luego escribe ese snapshot completo bajo lock:
  puede confirmar información vieja encima de un commit concurrente (el
  contador no retrocede, pero la actualización se pierde).
* CRÍTICO-02: ``pipeline.py::_persistir_validacion`` y los persistidores de
  ``validacion.py`` escriben el documento completo con
  ``escribir_json_seguro()`` sin lock, sin CAS y sin ``revision_documento``
  (la revisión llega a DESAPARECER del documento).

Corrección exigida (plan R15.2 del auditor):

1. Módulo compartido ``utilidades/persistencia_documento.py`` con el
   contrato: lock → leer fresco → validar revisión → aplicar patch →
   incrementar revisión → escritura atómica verificada. Backend, pipeline,
   validación y migraciones lo usan (UNA sola autoridad).
2. Prueba estática: ninguna escritura directa del documento fuera del
   módulo autorizado.
3. Protección temporal: mutaciones de UI rechazadas (409) mientras haya
   pipeline/reproceso activo (lecturas permitidas).
4. Prueba obligatoria: migración + mutación concurrente ⇒ ambos cambios
   existen y la revisión es monótona; pipeline + edición ⇒ preservación o
   rechazo explícito, nunca pérdida silenciosa.
"""
from __future__ import annotations

import importlib.util
import json
import re
import threading
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

import dashboard.backend.app as backend

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture
def entorno_documento(monkeypatch, tmp_path):
    """Documento versionado (rev 5) con una fila de consenso legacy."""
    doc = tmp_path / "validacion_resultados.json"
    doc.write_text(json.dumps({
        "raiz": str(tmp_path),
        "revision_documento": 5,
        "resultados": [
            {"nombre": "CASO1", "case_key": "P|1ST|HT|N|1", "tipo_st": "1ST",
             "imagenes": [], "videos": [],
             "video_apertura": {"algoritmo_consenso": "v0-legacy",
                                "estado": "primera_aparicion",
                                "tiempo_ms": 5.4, "soporte": 1}},
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(backend, "RUTA_VALIDACION", doc)
    monkeypatch.setattr(backend, "_cache", {"mtime": None, "datos": None})
    monkeypatch.setattr(backend, "_advertencia_migracion_consensos", None,
                        raising=False)
    monkeypatch.setattr(backend, "_pipeline_hilo", None)
    monkeypatch.setattr(backend, "_pipeline_reserva", None, raising=False)
    return {"doc": doc, "tmp": tmp_path}


def _leer(doc: Path) -> dict:
    return json.loads(doc.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# CRÍTICO-01 — migración de consensos vs commit concurrente
# ---------------------------------------------------------------------------

def test_migracion_consensos_no_pierde_commit_concurrente(entorno_documento,
                                                           monkeypatch):
    """Reproducción del auditor: rev 5 + migración lenta + commit rev 6.

    La migración debe releer el documento FRESCO dentro del lock: al final
    existen CAMBIO_NUEVO (commit concurrente) y la fila legacy migrada, con
    revisión monótona.
    """
    doc = entorno_documento["doc"]
    llego = threading.Event()
    liberar = threading.Event()
    original = backend._degradar_campos_consenso_legacy
    llamadas = []

    def degradar_pausado(fila):
        # Pausa la migración con el snapshot ya mutado pero ANTES de escribir.
        if not llamadas:
            llamadas.append(fila)
            llego.set()
            assert liberar.wait(10)
        return original(fila)

    monkeypatch.setattr(backend, "_degradar_campos_consenso_legacy",
                        degradar_pausado)
    resultado: dict = {}

    def cargar():
        try:
            resultado["datos"] = backend._cargar_datos()  # dispara migración
        except BaseException as exc:  # noqa: BLE001
            resultado["exc"] = exc

    hilo = threading.Thread(target=cargar)
    hilo.start()
    try:
        assert llego.wait(10), "la migración no pasó por el punto de pausa"
        rev_nueva = backend.mutar_documento(
            lambda frescos: frescos.update(CAMBIO_NUEVO="preservar"))[0]
        assert rev_nueva == 6
    finally:
        liberar.set()
    hilo.join(15)
    assert "exc" not in resultado, resultado.get("exc")

    disco = _leer(doc)
    assert disco.get("CAMBIO_NUEVO") == "preservar", (
        "lost update: la migración confirmó un snapshot viejo encima del "
        "commit concurrente")
    fila = disco["resultados"][0]
    assert fila["video_apertura"].get("requiere_revision") is True, (
        "la migración legacy no quedó aplicada en el documento fresco")
    assert int(disco.get("revision_documento") or 0) >= rev_nueva + 1


# ---------------------------------------------------------------------------
# CRÍTICO-02 — pipeline/validación por la autoridad compartida
# ---------------------------------------------------------------------------

def test_autoridad_compartida_existe_y_backend_delega():
    assert importlib.util.find_spec("utilidades.persistencia_documento"), (
        "falta el módulo compartido utilidades/persistencia_documento.py")
    fuente = (RAIZ / "dashboard" / "backend" / "app.py").read_text(encoding="utf-8")
    assert "persistencia_documento" in fuente, (
        "el backend no delega en la autoridad compartida")


def test_pipeline_preserva_revision_documento(entorno_documento):
    """Reproducción B del auditor: _persistir_validacion sobre rev 5.

    Antes: revision_documento DESAPARECÍA del documento. Ahora: la escritura
    del pipeline pasa por la primitiva y la revisión es monótona.
    """
    import pipeline
    doc = entorno_documento["doc"]
    validacion = {"archivo_salida": str(doc), "perfil": "legacy",
                  "resultados": [{"nombre": "SALIDA_PIPELINE"}]}
    assert pipeline._persistir_validacion(validacion) is True
    disco = _leer(doc)
    assert "revision_documento" in disco, (
        "la escritura del pipeline borró revision_documento")
    assert int(disco["revision_documento"]) >= 6
    assert disco["resultados"][0]["nombre"] == "SALIDA_PIPELINE"


def test_pipeline_escribe_bajo_lock_compartido(entorno_documento):
    """El escritor del pipeline participa del MISMO lock que el backend."""
    import pipeline
    from utilidades import persistencia_documento as pd
    doc = entorno_documento["doc"]
    llego = threading.Event()

    def escribir():
        pipeline._persistir_validacion(
            {"archivo_salida": str(doc), "resultados": [{"nombre": "PIPE"}]})
        llego.set()

    with pd.lock_documento(doc):
        hilo = threading.Thread(target=escribir)
        hilo.start()
        time.sleep(0.3)
        assert not llego.is_set(), (
            "el pipeline escribió SIN adquirir el lock compartido del documento")
    hilo.join(10)
    assert llego.is_set()


def test_guard_estatico_escritura_unica_del_documento():
    """Ninguna escritura directa del documento fuera del módulo autorizado."""
    app = (RAIZ / "dashboard" / "backend" / "app.py").read_text(encoding="utf-8")
    assert "escribir_json_seguro(RUTA_VALIDACION" not in app
    assert "_guardar_json_atomico(RUTA_VALIDACION" not in app
    for nombre in ("pipeline.py", "validacion.py"):
        fuente = (RAIZ / nombre).read_text(encoding="utf-8")
        assert "persistencia_documento" in fuente, (
            f"{nombre} no usa la autoridad compartida")
        assert not re.search(r"escribir_json_seguro\(\s*\n?\s*destino", fuente), (
            f"{nombre} todavía escribe el documento directo (destino)")


# ---------------------------------------------------------------------------
# P0 temporal — mutaciones de UI bloqueadas con pipeline activo
# ---------------------------------------------------------------------------

class _HiloVivo:
    def is_alive(self):
        return True


@pytest.mark.parametrize("llamada", [
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
])
def test_mutaciones_rechazadas_durante_pipeline(entorno_documento, monkeypatch,
                                                llamada):
    """Rechazo explícito ANTES de cualquier efecto (opción 2 del auditor)."""
    nombre, invocar = llamada
    monkeypatch.setattr(backend, "_pipeline_hilo", _HiloVivo())
    with pytest.raises(HTTPException) as rechazo:
        invocar()
    assert rechazo.value.status_code == 409, (
        f"{nombre}: se esperaba 409 por pipeline activo, "
        f"llegó {rechazo.value.status_code}")
