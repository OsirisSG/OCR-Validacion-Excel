"""R15.6 · F5 — Autoridad del documento externo (ALTO-04).

Auditoría independiente R15.5, ALTO-04: dos pestañas pueden perder cambios en
`pruebas_externas.json`. Las ramas externas usan `cargar()` (snapshot fuera de
lock) → modificar → `_guardar_json_atomico()` (documento completo desde el
snapshot viejo). La escritura atómica protege contra archivos parciales, pero
NO contra lost updates: la segunda escritura pisa el cambio de la primera
(repro del auditor: EXT1 «sin cambio», EXT2 «revisada_sin_datos»).

Corrección exigida: autoridad equivalente a `persistencia_documento` para el
documento externo — lock por ruta, lectura fresca dentro del lock,
`revision_documento` monotónica, `expected_revision` en writers humanos y
commit atómico verificado.
"""
from __future__ import annotations

import json
import threading

import pytest
from fastapi import HTTPException

import dashboard.backend.app as backend
import pruebas_externas
from test_v15_10_1_r153_cas_efectos import env  # noqa: F401 — fixture compartido


@pytest.fixture
def externas(env, monkeypatch):
    """Banco externo real sobre tmp: dos pruebas con imagen y documento JSON."""
    dir_ext = env["tmp"] / "banco"
    dir_ext.mkdir()
    img1 = dir_ext / "EXT1.png"
    img1.write_bytes(b"PNG1dummy")
    img2 = dir_ext / "EXT2.png"
    img2.write_bytes(b"PNG2dummy")
    salida = env["tmp"] / "externas_resultados.json"
    documento = {"generado_en": None, "revision_documento": 0, "resultados": [
        {"id": "EXT1", "ruta": str(img1), "imagen": "EXT1.png",
         "tipo": "codigo", "coincidencia_exacta": False, "cobertura": 0.5},
        {"id": "EXT2", "ruta": str(img2), "imagen": "EXT2.png",
         "tipo": "codigo", "coincidencia_exacta": False, "cobertura": 0.5}]}
    salida.write_text(json.dumps(documento), encoding="utf-8")
    monkeypatch.setattr(pruebas_externas, "rutas",
                        lambda config=None: (dir_ext, salida))
    return {"dir": dir_ext, "salida": salida, "img1": img1, "img2": img2}


def _leer_externo(salida) -> dict:
    return json.loads(salida.read_text(encoding="utf-8"))


def _marcar(pid: str, expected_revision=None):
    return backend.marcar_imagen_sin_datos(backend.SolicitudImagenSinDatos(
        tipo="externa", prueba_id=pid, imagen_id=None, motivo="sin datos",
        usuario="revisor", expected_revision=expected_revision))


# ---------------------------------------------------------------------------
# ALTO-04 — lost update entre dos pestañas
# ---------------------------------------------------------------------------


def test_dos_pestanas_preservan_ambos_cambios(env, externas, monkeypatch):
    """Repro del auditor: AMBOS cambios deben sobrevivir en el documento final.

    R15.7 (MEDIO-05): el writer externo es CAS ESTRICTO, así que una pestaña
    desactualizada recibe 409 y debe RECARGAR (patrón UI correcto) antes de
    reintentar; los dos cambios siguen sin perderse (la petición rechazada no
    produce efectos)."""
    salida = externas["salida"]
    cargar_real = pruebas_externas.cargar
    turno = {"n": 0}
    turno_lock = threading.Lock()
    leyo = {1: threading.Event(), 2: threading.Event()}

    def cargar_carrera(config=None):
        doc = cargar_real(config)
        with turno_lock:
            turno["n"] += 1
            mio = turno["n"]
        otro = 2 if mio == 1 else 1
        leyo.setdefault(mio, threading.Event()).set()
        # Espera acotada: hoy (sin lock) la otra pestaña lee el mismo
        # snapshot en milisegundos y la carrera se reproduce; tras la
        # corrección la otra pestaña espera el lock y el timeout expira sin
        # deadlock (lectura fresca garantizada por la autoridad).
        leyo.setdefault(otro, threading.Event()).wait(2.0)
        return doc

    monkeypatch.setattr(pruebas_externas, "cargar", cargar_carrera)
    errores = []

    def marcar(pid):
        try:
            _marcar(pid)
        except HTTPException as conflicto:  # noqa: PERF203 — recarga de UI
            if conflicto.status_code != 409:
                errores.append((pid, repr(conflicto)))
                return
            try:
                revision = int(_leer_externo(salida)["revision_documento"])
                _marcar(pid, expected_revision=revision)
            except BaseException as exc:  # noqa: BLE001 — se assertsiona abajo
                errores.append((pid, repr(exc)))
        except BaseException as exc:  # noqa: BLE001 — se assertsiona abajo
            errores.append((pid, repr(exc)))

    hilos = [threading.Thread(target=marcar, args=(pid,))
             for pid in ("EXT1", "EXT2")]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(20)
    assert not errores, f"ambas peticiones deben terminar sin error: {errores}"
    estados = {f["id"]: f.get("estado_imagen")
               for f in _leer_externo(salida)["resultados"]}
    assert estados == {"EXT1": "revisada_sin_datos",
                       "EXT2": "revisada_sin_datos"}, (
        "ALTO-04: lost update — una escritura pisó el cambio de la otra "
        f"pestaña: {estados}")


# ---------------------------------------------------------------------------
# Revisión monotónica + CAS en writers humanos
# ---------------------------------------------------------------------------


def test_commit_externo_versiona_revision(env, externas):
    salida = externas["salida"]
    _marcar("EXT1")
    assert int(_leer_externo(salida)["revision_documento"]) == 1, (
        "ALTO-04: el commit externo debe versionar el documento (revisión "
        "monotónica)")
    # R15.7 (MEDIO-05): el segundo writer envía la revisión vigente (CAS).
    _marcar("EXT2", expected_revision=1)
    assert int(_leer_externo(salida)["revision_documento"]) == 2


def test_expected_revision_desfasada_409_sin_efectos(env, externas, monkeypatch):
    salida = externas["salida"]
    doc = _leer_externo(salida)
    doc["revision_documento"] = 5
    salida.write_text(json.dumps(doc), encoding="utf-8")
    antes = salida.read_bytes()
    with pytest.raises(HTTPException) as rechazo:
        _marcar("EXT1", expected_revision=3)
    assert rechazo.value.status_code == 409
    assert salida.read_bytes() == antes, "el 409 no debe tocar el documento"
    assert env["gestor"].imagen_sin_datos(externas["img1"]) is None, (
        "el 409 no debe dejar efectos SQLite")


def test_expected_revision_correcta_confirma(env, externas):
    salida = externas["salida"]
    doc = _leer_externo(salida)
    doc["revision_documento"] = 5
    salida.write_text(json.dumps(doc), encoding="utf-8")
    resultado = _marcar("EXT1", expected_revision=5)
    assert resultado.get("estado_imagen") == "revisada_sin_datos"
    assert int(_leer_externo(salida)["revision_documento"]) == 6


def test_restaurar_con_texto_versiona_y_cas(env, externas):
    salida = externas["salida"]
    _marcar("EXT1")
    respuesta = backend.restaurar_imagen_con_texto(
        backend.SolicitudImagenSinDatos(
            tipo="externa", prueba_id="EXT1", imagen_id=None,
            usuario="revisor", expected_revision=1))
    assert respuesta.get("restaurada") is True
    disco = _leer_externo(salida)
    assert int(disco["revision_documento"]) == 2
    fila = next(f for f in disco["resultados"] if f["id"] == "EXT1")
    assert fila.get("estado_imagen") == "pendiente"


# ---------------------------------------------------------------------------
# Regeneración completa (evaluar) bajo la misma autoridad
# ---------------------------------------------------------------------------


def test_commit_completo_monotonico(env, externas):
    salida = externas["salida"]
    doc = _leer_externo(salida)
    doc["revision_documento"] = 7
    salida.write_text(json.dumps(doc), encoding="utf-8")
    pruebas_externas._commit_documento_completo(
        salida, {"generado_en": None, "resultados": []})
    assert int(_leer_externo(salida)["revision_documento"]) == 8, (
        "la regeneración completa no puede hacer retroceder la revisión")


def test_commit_completo_sin_documento_previo(env, externas):
    nueva = externas["salida"].with_name("nueva.json")
    pruebas_externas._commit_documento_completo(
        nueva, {"generado_en": None, "resultados": []})
    assert int(_leer_externo(nueva)["revision_documento"]) == 1
