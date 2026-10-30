"""R15.2 · ALTO-04: CAS estricto en TODA mutación humana del documento.

Hallazgo del auditor: el CAS estricto (R15.1) sólo cubría los endpoints de
video; las 7 mutaciones UI legacy (corrección OCR, rotación, sin-datos,
con-texto, verificar, consolidar y campo manual) aceptaban
``expected_revision=None`` contra un documento YA versionado, y además
``sin-datos`` registraba la evidencia en la base de aprendizaje ANTES de
validar el CAS (efecto lateral irreversible con petición rechazable).

Exigido (criterios 5 y 6 de R15.2):

* documento versionado (revisión > 0) + mutación UI sin ``expected_revision``
  ⇒ 409 ANTES de cualquier efecto lateral (pestaña desactualizada);
* ``expected_revision`` desfasada ⇒ 409 «recarga antes de guardar»;
* ``expected_revision`` correcta ⇒ commit y revisión +1 en la respuesta;
* la lista /api/pruebas expone ``revision_documento`` para que el frontend
  pueda enviarla (las pantallas mantienen la revisión actual).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

import dashboard.backend.app as backend
from aprendizaje import GestorAprendizaje
from test_v15_10_1_r15_1_documento_global import CASE_KEY, CLAVE

REV_INICIAL = 3


def _ocr() -> dict:
    return {"dimensiones": [100, 100], "texto_completo": "ABC",
            "tokens": [{"texto": "ABC", "bbox": [0, 0, 10, 10]}],
            "lineas_texto": [{"texto": "ABC", "bbox": [0, 0, 10, 10]}]}


def _documento(lote: Path, imagen: Path) -> dict:
    return {
        "raiz": str(lote), "revision_documento": REV_INICIAL,
        "resultados": [{
            "nombre": "CASO1", "case_key": CASE_KEY, "ruta": str(lote / "CASO1"),
            "tipo_st": "1ST", "perfil": "empresarial",
            "comparacion": {"resultado": "coincidencia_total"},
            "campos": {"test_number": {"valor": "1001", "estado": "confirmado"}},
            "imagenes": [{"id": "IMG1", "ruta": str(imagen),
                          "resultado_ocr": _ocr()}],
            "trazabilidad": [], "videos": [],
        }],
    }


@pytest.fixture
def env_cas(monkeypatch, tmp_path):
    lote = tmp_path / "Lote"
    (lote / "CASO1").mkdir(parents=True)
    imagen = lote / "CASO1" / "img_0001.png"
    imagen.write_bytes(b"PNGdummy")
    validacion = tmp_path / "validacion_resultados.json"
    validacion.write_text(json.dumps(_documento(lote, imagen)), encoding="utf-8")
    entrada = tmp_path / "ejecucion_2st.json"
    entrada.write_text(json.dumps({"resultados": []}), encoding="utf-8")
    gestor = GestorAprendizaje({"aprendizaje": {}}, directorio=str(tmp_path))

    monkeypatch.setattr(backend, "RUTA_VALIDACION", validacion)
    monkeypatch.setattr(backend, "_cache", {"mtime": None, "datos": None})
    monkeypatch.setattr(backend, "_pipeline_estado",
                        copy.deepcopy(backend._pipeline_estado))
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
    # Stub de harness: la decodificación real no es la ruta bajo prueba.
    monkeypatch.setattr(backend, "_dimensiones_ocr_desde_archivo",
                        lambda ruta, ocr: (100, 100))
    yield {"gestor": gestor, "validacion": validacion, "imagen": imagen,
           "entrada": entrada, "tmp": tmp_path}


def _leer(validacion: Path) -> dict:
    return json.loads(validacion.read_text(encoding="utf-8"))


def _cargar(endpoint: str, env: dict, expected):
    if endpoint == "ocr":
        return backend.corregir_lectura(backend.SolicitudCorreccion(
            prueba_id=CLAVE, imagen_id="IMG1", campo="etiqueta",
            texto_ocr="ABC", texto_correcto="A.1", bbox=[0, 0, 10, 10],
            accion="corregir", usuario="t", campo_destino="test_number",
            expected_revision=expected))
    if endpoint == "rotacion":
        return backend.guardar_rotacion(backend.SolicitudRotacion(
            tipo="carpeta", prueba_id=CLAVE, imagen_id="IMG1", grados=90,
            expected_revision=expected))
    if endpoint == "sin_datos":
        return backend.marcar_imagen_sin_datos(backend.SolicitudImagenSinDatos(
            tipo="carpeta", prueba_id=CLAVE, imagen_id="IMG1",
            motivo="sin texto útil", usuario="t", expected_revision=expected))
    if endpoint == "con_texto":
        return backend.restaurar_imagen_con_texto(backend.SolicitudImagenSinDatos(
            tipo="carpeta", prueba_id=CLAVE, imagen_id="IMG1",
            usuario="t", expected_revision=expected))
    if endpoint == "verificar":
        return backend.verificar_imagen(backend.SolicitudImagenVerificada(
            prueba_id=CLAVE, imagen_id="IMG1", usuario="t",
            expected_revision=expected))
    if endpoint == "consolidar":
        return backend.consolidar_resultados(backend.SolicitudConsolidacion(
            archivos=[str(env["entrada"])], regenerar_excel=False,
            expected_revision=expected))
    if endpoint == "campo":
        return backend.corregir_campo_caso(
            CLAVE, "test_number",
            backend.SolicitudCampoManual(valor="1002", usuario="t",
                                         expected_revision=expected))
    raise AssertionError(endpoint)


MUTACIONES = ["ocr", "rotacion", "sin_datos", "verificar", "consolidar",
              "campo"]


@pytest.mark.parametrize("endpoint", MUTACIONES)
def test_documento_versionado_exige_expected_revision(env_cas, endpoint):
    """Criterio 6: pestaña desactualizada (sin expected) ⇒ 409, no sobrescribe."""
    with pytest.raises(HTTPException) as err:
        _cargar(endpoint, env_cas, None)
    assert err.value.status_code == 409, (endpoint, err.value.detail)
    assert "versionado" in str(err.value.detail)
    assert _leer(env_cas["validacion"])["revision_documento"] == REV_INICIAL


@pytest.mark.parametrize("endpoint", MUTACIONES + ["con_texto"])
def test_revision_desfasada_recarga_antes_de_guardar(env_cas, endpoint):
    if endpoint == "con_texto":
        _preparar_con_texto(env_cas)
    with pytest.raises(HTTPException) as err:
        _cargar(endpoint, env_cas, REV_INICIAL - 1)
    assert err.value.status_code == 409, (endpoint, err.value.detail)
    assert "recarga" in str(err.value.detail)
    assert _leer(env_cas["validacion"])["revision_documento"] == REV_INICIAL


def _preparar_con_texto(env: dict) -> None:
    """Marca sin-datos previa (sqlite + documento) para ejercer con-texto."""
    env["gestor"].registrar_imagen_sin_datos(env["imagen"], CLAVE, "m", "t")
    disco = _leer(env["validacion"])
    item = disco["resultados"][0]["imagenes"][0]
    item["estado_imagen"] = "revisada_sin_datos"
    item["revision_sin_datos"] = {"estado": "revisada_sin_datos", "motivo": "m"}
    item["resultado_ocr"]["estado_imagen"] = "revisada_sin_datos"
    env["validacion"].write_text(json.dumps(disco), encoding="utf-8")
    backend._cache.update({"mtime": None, "datos": None})


def test_expected_correcto_confirma_y_versiona(env_cas):
    resultado = _cargar("verificar", env_cas, REV_INICIAL)
    assert resultado["revision_documento"] == REV_INICIAL + 1
    disco = _leer(env_cas["validacion"])
    assert disco["revision_documento"] == REV_INICIAL + 1
    assert disco["resultados"][0]["imagenes"][0]["estado_imagen"] == "verificada"


def test_campo_manual_con_expected_correcto_confirma(env_cas):
    resultado = _cargar("campo", env_cas, REV_INICIAL)
    assert resultado["revision_documento"] == REV_INICIAL + 1
    disco = _leer(env_cas["validacion"])
    assert disco["resultados"][0]["campos"]["test_number"]["valor"] == "1002"


def test_con_texto_con_expected_correcto_restaura(env_cas):
    _preparar_con_texto(env_cas)
    resultado = _cargar("con_texto", env_cas, REV_INICIAL)
    assert resultado["revision_documento"] == REV_INICIAL + 1
    assert env_cas["gestor"].imagen_sin_datos(env_cas["imagen"]) is None


# ---------------------------------------------------------------------------
# Efectos laterales SÓLO después de validar el CAS
# ---------------------------------------------------------------------------

def test_sin_datos_rechazado_no_registra_evidencia(env_cas):
    """ALTO-04: el registro sqlite no puede preceder al CAS."""
    with pytest.raises(HTTPException) as err:
        _cargar("sin_datos", env_cas, None)
    assert err.value.status_code == 409
    assert env_cas["gestor"].imagen_sin_datos(env_cas["imagen"]) is None, (
        "se registró la marca sin-datos pese al rechazo por CAS")


def test_ocr_rechazado_no_registra_correccion(env_cas):
    with pytest.raises(HTTPException) as err:
        _cargar("ocr", env_cas, None)
    assert err.value.status_code == 409
    assert env_cas["gestor"].listar_correcciones_texto([env_cas["imagen"]]) == [], (
        "se registró la corrección pese al rechazo por CAS")


def test_con_texto_rechazado_conserva_la_marca(env_cas):
    _preparar_con_texto(env_cas)
    with pytest.raises(HTTPException) as err:
        _cargar("con_texto", env_cas, None)
    assert err.value.status_code == 409
    assert env_cas["gestor"].imagen_sin_datos(env_cas["imagen"]) is not None


# ---------------------------------------------------------------------------
# /api/pruebas expone la revisión para que la UI la reenvíe (criterio 5)
# ---------------------------------------------------------------------------

def test_api_pruebas_expone_revision_documento(env_cas):
    respuesta = backend.pruebas(q="", estado="", limit=200, offset=0)
    assert respuesta["revision_documento"] == REV_INICIAL


def test_documento_ausente_no_inventa_revision(monkeypatch, tmp_path):
    """Sin documento no hay revisión que exponer (no se inventa 0 como dato)."""
    monkeypatch.setattr(backend, "RUTA_VALIDACION", tmp_path / "no_existe.json")
    monkeypatch.setattr(backend, "_cache", {"mtime": None, "datos": None})
    estado = copy.deepcopy(backend._pipeline_estado)
    # R15.4 (MEDIUM-03, contrato reemplazado documentado): si el entorno trae
    # un checkpoint con parciales (instalación usada), la ausencia del
    # documento oficial responde 503 con estado de recuperación — ése es el
    # contrato nuevo y lo cubre test_v15_10_1_r154_checkpoint_seguro.py.
    # Esta prueba aísla el caso SIN checkpoint: 404 sin inventar revisión.
    estado["estado"] = "inactivo"
    estado["resultados_parciales"] = []
    monkeypatch.setattr(backend, "_pipeline_estado", estado)
    with pytest.raises(HTTPException) as err:
        backend.pruebas(q="", estado="", limit=200, offset=0)
    assert err.value.status_code == 404
