"""R15.6 · F1 — Efectos humanos bajo la política transaccional común.

Auditoría independiente R15.5 (`AUDITORIA_INDEPENDIENTE_R15_5_20261016.md`):

* CRÍTICO-01: `corregir_campo_caso` commitea el documento ANTES de
  `gestor.actualizar_revision()`; si el almacén de revisiones falla, la
  petición termina en error pero el documento quedó modificado (repro del
  auditor: revisión 3→4 y `test_number=2002` persistidos).
* MEDIO-06: `marcar_region_no_texto`, `marcar_regiones_no_texto_lote`,
  `anotar_region_no_detectada`, `corregir_prueba_externa` y
  `anotar_region_externa` repiten el patrón «efecto durable primero +
  actualizar_revision después» sin transacción/compensación común; el lote
  además no es atómico (si la segunda marca falla, la primera queda).
* Plan P1: helper único «efecto humano + estado de revisión» sobre
  `TransaccionMultiAlmacen`; cualquier petición fallida ⇒ cero efectos
  persistentes O inconsistencia declarada + bloqueo.

Cada prueba verifica también número de revisión y filas SQLite auxiliares,
como exige el plan adversarial del auditor.
"""
from __future__ import annotations

import copy
import json
import shutil

import pytest
from fastapi import HTTPException

import dashboard.backend.app as backend
import pruebas_externas
from test_v15_10_1_r153_cas_efectos import (  # noqa: F401 — fixture compartido
    REV_INICIAL, env, _leer)
from test_v15_10_1_r15_1_documento_global import CLAVE


def _boom(*a, **kw):
    raise RuntimeError("sqlite bloqueado (simulado)")


def _filas(gestor, tabla: str, where: str = "1=1") -> int:
    with gestor._conectar() as con:
        return con.execute(f"SELECT COUNT(*) FROM {tabla} WHERE {where}").fetchone()[0]


# --- MEDIO-06: no-texto simple --------------------------------------------

def test_no_texto_fallo_revision_cero_efectos(env, monkeypatch):
    """Repro del auditor: marcar_no_texto persiste y después falla la revisión."""
    monkeypatch.setattr(env["gestor"], "actualizar_revision", _boom)
    with pytest.raises(HTTPException) as fallo:
        backend.marcar_region_no_texto(backend.SolicitudNoTexto(
            prueba_id=CLAVE, imagen_id="IMG1", bbox=[0, 0, 10, 10],
            usuario="revisor"))
    assert fallo.value.status_code == 503
    assert _filas(env["gestor"], "regiones_no_texto") == 0, (
        "MEDIO-06: la petición falló pero la marca no_texto quedó persistida")
    estado = env["gestor"].estado_revision("carpeta", CLAVE, "por_revisar")
    assert estado["actualizado_en"] is None


def test_no_texto_lote_segundo_fallo_restaura_primero(env, monkeypatch):
    """Lote atómico: si la segunda marca falla, la primera se compensa."""
    disco = _leer(env["validacion"])
    ocr = disco["resultados"][0]["imagenes"][0]["resultado_ocr"]
    ocr["tokens"] = [{"texto": "ABC", "bbox": [0, 0, 10, 10]},
                     {"texto": "XY", "bbox": [20, 20, 10, 10]}]
    ocr["lineas_texto"] = []
    env["validacion"].write_text(json.dumps(disco), encoding="utf-8")
    original = env["gestor"].marcar_no_texto
    llamadas = {"n": 0}

    def flaky(*a, **kw):
        llamadas["n"] += 1
        if llamadas["n"] == 2:
            raise RuntimeError("sqlite bloqueado (simulado)")
        return original(*a, **kw)

    monkeypatch.setattr(env["gestor"], "marcar_no_texto", flaky)
    with pytest.raises(HTTPException) as fallo:
        backend.marcar_regiones_no_texto_lote(backend.SolicitudNoTextoLote(
            prueba_id=CLAVE, imagen_id="IMG1",
            bboxes=[[0, 0, 10, 10], [20, 20, 10, 10]], usuario="revisor"))
    assert fallo.value.status_code == 503
    assert _filas(env["gestor"], "regiones_no_texto") == 0, (
        "el lote no es atómico: la primera marca sobrevivió al fallo de la segunda")


def test_no_texto_exito_marca_y_revision(env):
    resultado = backend.marcar_region_no_texto(backend.SolicitudNoTexto(
        prueba_id=CLAVE, imagen_id="IMG1", bbox=[0, 0, 10, 10],
        usuario="revisor"))
    assert resultado["guardado"] is True
    assert _filas(env["gestor"], "regiones_no_texto", "activo=1") == 1
    assert env["gestor"].estado_revision(
        "carpeta", CLAVE, "por_revisar")["estado"] == "parcial"


# --- MEDIO-06: anotación de región ----------------------------------------

def test_anotar_region_fallo_revision_cero_efectos(env, monkeypatch):
    monkeypatch.setattr(env["gestor"], "actualizar_revision", _boom)
    with pytest.raises(HTTPException) as fallo:
        backend.anotar_region_no_detectada(backend.SolicitudAnotacionRegion(
            prueba_id=CLAVE, imagen_id="IMG1", bbox=[30, 30, 20, 20],
            texto_correcto="42", usuario="revisor"))
    assert fallo.value.status_code == 503
    assert _filas(env["gestor"], "anotaciones_regiones") == 0, (
        "MEDIO-06: la anotación sobrevivió al fallo de la revisión")
    assert _filas(env["gestor"], "muestras_visuales") == 0


# --- CRÍTICO-01: corrección manual de campo --------------------------------

def test_corregir_campo_fallo_revision_no_toca_documento(env, monkeypatch):
    """Repro del auditor: el documento NO puede avanzar si la revisión falla."""
    monkeypatch.setattr(env["gestor"], "actualizar_revision", _boom)
    antes = env["validacion"].read_bytes()
    with pytest.raises(HTTPException) as fallo:
        backend.corregir_campo_caso(CLAVE, "test_number",
                                    backend.SolicitudCampoManual(
                                        valor="2002", usuario="revisor",
                                        expected_revision=REV_INICIAL))
    assert fallo.value.status_code == 503
    assert env["validacion"].read_bytes() == antes, (
        "CRÍTICO-01: la revisión durable falló pero el documento quedó "
        "confirmado con la corrección manual")
    disco = _leer(env["validacion"])
    assert int(disco["revision_documento"]) == REV_INICIAL
    assert disco["resultados"][0]["campos"]["test_number"]["valor"] == "1001"


def test_corregir_campo_exito_documento_y_revision(env):
    respuesta = backend.corregir_campo_caso(
        CLAVE, "test_number",
        backend.SolicitudCampoManual(valor="2002", usuario="revisor",
                                     expected_revision=REV_INICIAL))
    assert int(respuesta["revision_documento"]) == REV_INICIAL + 1
    disco = _leer(env["validacion"])
    assert disco["resultados"][0]["campos"]["test_number"]["valor"] == "2002"
    assert env["gestor"].estado_revision(
        "carpeta", CLAVE, "por_revisar")["estado"] == "parcial"


# --- MEDIO-06: rutas externas ----------------------------------------------

@pytest.fixture
def externa(env, monkeypatch):
    """Documento externo en memoria + imagen real bajo tmp."""
    imagen_ext = env["tmp"] / "ext_0001.png"
    shutil.copy(env["imagen"], imagen_ext)
    documento = {"resultados": [{
        "id": "EXT1", "ruta": str(imagen_ext), "imagen": "ext_0001.png",
        "tipo": "texto", "cobertura": 0.5, "dimensiones": [100, 100],
        "tokens": [{"texto": "41", "bbox": [10, 10, 50, 20]}]}]}
    salida = env["tmp"] / "externas_resultados.json"
    monkeypatch.setattr(pruebas_externas, "cargar",
                        lambda config=None: copy.deepcopy(documento))
    monkeypatch.setattr(pruebas_externas, "rutas",
                        lambda config=None: (env["tmp"], salida))
    return documento, salida


def test_corregir_externa_fallo_revision_cero_efectos(env, externa, monkeypatch):
    monkeypatch.setattr(env["gestor"], "actualizar_revision", _boom)
    with pytest.raises(HTTPException) as fallo:
        backend.corregir_prueba_externa(backend.SolicitudCorreccionExterna(
            prueba_id="EXT1", texto_ocr="41", texto_correcto="42",
            accion="corregir", usuario="revisor"))
    assert fallo.value.status_code == 503
    assert _filas(env["gestor"], "correcciones_texto") == 0, (
        "MEDIO-06: la corrección externa sobrevivió al fallo de la revisión")
    assert _filas(env["gestor"], "correcciones") == 0


def test_anotar_externa_fallo_revision_cero_efectos(env, externa, monkeypatch):
    monkeypatch.setattr(env["gestor"], "actualizar_revision", _boom)
    with pytest.raises(HTTPException) as fallo:
        backend.anotar_region_externa(backend.SolicitudRegionExterna(
            prueba_id="EXT1", bbox=[10, 10, 20, 20], texto_correcto="99",
            usuario="revisor"))
    assert fallo.value.status_code == 503
    assert _filas(env["gestor"], "anotaciones_regiones") == 0, (
        "MEDIO-06: la región externa sobrevivió al fallo de la revisión")
