"""R15.6 · F4 — Registro de inconsistencias fail-closed + recuperación explícita.

Auditoría independiente R15.5:

* ALTO-03: `_persistir_inconsistencias()` captura OSError y lo ignora
  (fail-open): si el registro durable no puede escribirse, el bloqueo vive
  sólo en memoria y un reinicio devuelve el sistema a modo normal en silencio.
  Un registro corrupto/ilegible al arrancar también se ignora. Corrección
  exigida: persistencia verificada (temporal + fsync + replace + relectura);
  si no se puede escribir ⇒ modo recuperación global persistente (centinela)
  o mutaciones impedidas; archivo ilegible al iniciar ⇒ modo recuperación.
* MEDIO-05: el mensaje de bloqueo pide al usuario borrar
  `estado_inconsistente.json` a mano, pero eso NO desbloquea el proceso en
  marcha y no existe flujo público de resolución. Corrección exigida: API
  explícita (listar + resolver con verificación confirmada + auditoría de
  quién/cuándo) y mensajes que no pidan borrado manual.
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

import dashboard.backend.app as backend
from test_v15_10_1_r153_cas_efectos import env  # noqa: F401 — fixture compartido


@pytest.fixture
def registro_aislado(env, monkeypatch):
    """Rutas del registro/centinela/auditoría redirigidas a tmp y estado limpio."""
    monkeypatch.setattr(backend, "RUTA_INCONSISTENCIAS",
                        env["tmp"] / "inconsistencias" / "estado_inconsistente.json",
                        raising=False)
    monkeypatch.setattr(backend, "RUTA_RECUPERACION",
                        env["tmp"] / "inconsistencias" / "recuperacion_requerida.json",
                        raising=False)
    monkeypatch.setattr(backend, "RUTA_AUDITORIA_RESOLUCIONES",
                        env["tmp"] / "inconsistencias" / "resoluciones.json",
                        raising=False)
    monkeypatch.setattr(backend, "_inconsistencias_activas", {}, raising=False)
    monkeypatch.setattr(backend, "_modo_recuperacion", None, raising=False)
    return env["tmp"] / "inconsistencias"


def _reiniciar():
    """Simula un reinicio del proceso: sólo queda lo durable."""
    backend._inconsistencias_activas.clear()
    backend._modo_recuperacion = None
    backend._cargar_inconsistencias()


# ---------------------------------------------------------------------------
# ALTO-03 — persistencia fail-closed
# ---------------------------------------------------------------------------


def test_registro_no_escribible_bloquea_tambien_tras_reinicio(
        env, monkeypatch, registro_aislado):
    """Repro del auditor: ruta no escribible + reinicio ⇒ el recurso NO puede
    quedar desbloqueado en silencio."""
    bloqueador = env["tmp"] / "bloqueado"
    bloqueador.write_text("soy un archivo, no un directorio")
    monkeypatch.setattr(backend, "RUTA_INCONSISTENCIAS",
                        bloqueador / "sub" / "estado_inconsistente.json",
                        raising=False)
    backend._registrar_inconsistencia("carpeta:X", "prueba", "doble fallo")
    # En el proceso actual, bloqueado.
    with pytest.raises(HTTPException):
        backend._assert_recurso_consistente("carpeta:X", "seguir")
    _reiniciar()
    with pytest.raises(HTTPException) as bloqueo:
        backend._assert_recurso_consistente("carpeta:X", "seguir")
    assert bloqueo.value.status_code == 503, (
        "ALTO-03: tras reiniciar con registro no escribible, el sistema debe "
        "seguir en modo recuperación (fail-closed), no volver a modo normal")


def test_registro_corrupto_al_iniciar_activa_modo_recuperacion(
        registro_aislado, monkeypatch):
    ruta = registro_aislado / "estado_inconsistente.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("{esto no es json válido", encoding="utf-8")
    _reiniciar()
    assert backend._modo_recuperacion is not None, (
        "ALTO-03: un registro ilegible al arrancar debe producir modo "
        "recuperación, no ignorarse")
    with pytest.raises(HTTPException) as bloqueo:
        backend._assert_documento_editable("editar")
    assert bloqueo.value.status_code == 503


def test_modo_recuperacion_bloquea_mutaciones_gobernadas(registro_aislado):
    backend._modo_recuperacion = {"motivo": "prueba", "fecha": "2026-10-16"}
    for invocar in (
            lambda: backend._assert_documento_editable("editar"),
            lambda: backend._assert_recurso_consistente("recurso:X", "mutar"),
            lambda: backend._assert_pipeline_inactivo("editar zonas")):
        with pytest.raises(HTTPException) as bloqueo:
            invocar()
        assert bloqueo.value.status_code == 503


def test_persistencia_normal_es_verificada_y_durable(registro_aislado):
    backend._registrar_inconsistencia("carpeta:Y", "op", "detalle")
    assert registro_aislado.joinpath("estado_inconsistente.json").is_file()
    _reiniciar()
    assert "carpeta:Y" in backend._inconsistencias_activas
    assert backend._modo_recuperacion is None


# ---------------------------------------------------------------------------
# MEDIO-05 — flujo explícito de recuperación
# ---------------------------------------------------------------------------


def test_mensaje_bloqueo_no_pide_borrado_manual(registro_aislado):
    backend._registrar_inconsistencia("carpeta:Z", "op", "detalle")
    with pytest.raises(HTTPException) as bloqueo:
        backend._assert_recurso_consistente("carpeta:Z", "mutar")
    detalle = str(bloqueo.value.detail).lower()
    assert "elimina el registro" not in detalle, (
        "MEDIO-05: el mensaje no debe pedir borrado manual del archivo")
    assert "/api/recuperacion" in detalle, (
        "MEDIO-05: el mensaje debe remitir al flujo explícito de recuperación")


def test_api_listar_inconsistencias(registro_aislado):
    backend._registrar_inconsistencia("carpeta:Z", "corrección", "doble fallo")
    estado = backend.listar_inconsistencias()
    assert estado["total"] == 1
    assert estado["inconsistencias"][0]["recurso"] == "carpeta:Z"
    assert estado["modo_recuperacion"] is None


def test_api_resolver_desbloquea_con_auditoria(registro_aislado):
    backend._registrar_inconsistencia("carpeta:Z", "corrección", "doble fallo")
    respuesta = backend.resolver_inconsistencia(
        "carpeta:Z",
        backend.SolicitudResolucionInconsistencia(
            usuario="revisor", confirmo_verificacion=True,
            nota="almacenes comprobados"))
    assert respuesta["resuelta"] is True
    # Recurso desbloqueado y registro durable actualizado.
    backend._assert_recurso_consistente("carpeta:Z", "mutar")
    _reiniciar()
    assert "carpeta:Z" not in backend._inconsistencias_activas
    # Auditoría: quién y cuándo.
    auditoria = json.loads(
        registro_aislado.joinpath("resoluciones.json").read_text(encoding="utf-8"))
    assert any(r["recurso"] == "carpeta:Z" and r["usuario"] == "revisor"
               for r in auditoria["resoluciones"])


def test_api_resolver_sin_confirmacion_no_desbloquea(registro_aislado):
    backend._registrar_inconsistencia("carpeta:Z", "corrección", "doble fallo")
    with pytest.raises(HTTPException) as rechazo:
        backend.resolver_inconsistencia(
            "carpeta:Z",
            backend.SolicitudResolucionInconsistencia(
                usuario="revisor", confirmo_verificacion=False))
    assert rechazo.value.status_code == 400
    with pytest.raises(HTTPException):
        backend._assert_recurso_consistente("carpeta:Z", "mutar")


def test_api_resolver_recurso_desconocido_404(registro_aislado):
    with pytest.raises(HTTPException) as rechazo:
        backend.resolver_inconsistencia(
            "carpeta:inexistente",
            backend.SolicitudResolucionInconsistencia(
                usuario="revisor", confirmo_verificacion=True))
    assert rechazo.value.status_code == 404


def test_api_resolver_modo_recuperacion_limpia_centinela(
        env, monkeypatch, registro_aislado):
    """Modo recuperación por registro no escribible: tras reparar la ruta y
    confirmar la verificación, el centinela desaparece y el sistema vuelve a
    modo normal."""
    bloqueador = env["tmp"] / "bloqueado2"
    bloqueador.write_text("archivo, no directorio")
    rota = bloqueador / "sub" / "estado_inconsistente.json"
    monkeypatch.setattr(backend, "RUTA_INCONSISTENCIAS", rota, raising=False)
    backend._registrar_inconsistencia("carpeta:W", "op", "detalle")
    assert backend._modo_recuperacion is not None
    _reiniciar()   # el centinela mantiene el modo activo
    assert backend._modo_recuperacion is not None
    # El usuario repara el almacenamiento; el registro vuelve a ser escribible.
    monkeypatch.setattr(backend, "RUTA_INCONSISTENCIAS",
                        registro_aislado / "estado_inconsistente.json",
                        raising=False)
    respuesta = backend.resolver_modo_recuperacion(
        backend.SolicitudResolucionInconsistencia(
            usuario="revisor", confirmo_verificacion=True,
            nota="almacén reparado y comprobado"))
    assert respuesta["modo_recuperacion"] is None
    assert not backend.RUTA_RECUPERACION.exists()
    backend._assert_documento_editable("editar")   # ya no lanza
    _reiniciar()
    assert backend._modo_recuperacion is None
