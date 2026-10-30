"""R15.7 — Endurecimiento de recuperación, identidad de recursos y semántica
post-commit (auditoría independiente R15.6).

Fuente: `AUDITORIA_INDEPENDIENTE_R15_6_20261016.md` (secciones 5 y 8).

Hallazgos cubiertos:

* ALTO-01 — una transacción exitosa que ya estaba en vuelo borra la
  inconsistencia creada por otra operación concurrente
  (`TransaccionMultiAlmacen.exito()` llamaba a `_resolver_inconsistencias`).
* ALTO-02 — las claves de recurso no son canónicas (`carpeta:<id>` vs ruta
  absoluta de imagen/video): una inconsistencia del mismo caso no bloquea las
  demás pantallas.
* ALTO-03 — si el registro durable Y el centinela no pueden escribirse, el
  bloqueo sólo vive en memoria y un reinicio devuelve el sistema a modo normal
  (fail-open).
* MEDIO-04 — `verificar_imagen` responde error después de que el commit
  principal ya quedó guardado, porque una tarea OPCIONAL post-commit
  (`incorporar_uniones_guardadas`) escapa del endpoint.
* MEDIO-05 — el CAS del documento externo acepta `expected_revision=None` en
  writers humanos versionados.
* BAJO-07 — la resolución de recuperación ignora el fallo al borrar el
  centinela y afirma «resuelto» aunque el siguiente arranque vuelva a
  activarlo.

Cada prueba reproduce el escenario del auditor o su criterio de aceptación
(sección 9) y está escrita para pasar SÓLO con la corrección R15.7 aplicada.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

import dashboard.backend.app as backend
from test_v15_10_1_r153_cas_efectos import (  # noqa: F401 — fixtures compartidas
    REV_INICIAL, env, _leer)
from test_v15_10_1_r15_1_documento_global import CLAVE
from test_v15_10_1_r156_documento_externo import (  # noqa: F401
    externas, _leer_externo)


@pytest.fixture
def registro(env, monkeypatch):
    """Registro/centinela/auditoría aislados en tmp (mismo aislamiento que la
    suite R15.6 de recuperación) + estado inicial limpio."""
    dir_reg = env["tmp"] / "inconsistencias"
    monkeypatch.setattr(backend, "RUTA_INCONSISTENCIAS",
                        dir_reg / "estado_inconsistente.json", raising=False)
    monkeypatch.setattr(backend, "RUTA_RECUPERACION",
                        dir_reg / "recuperacion_requerida.json", raising=False)
    monkeypatch.setattr(backend, "RUTA_AUDITORIA_RESOLUCIONES",
                        dir_reg / "resoluciones.json", raising=False)
    monkeypatch.setattr(backend, "RUTA_RECUPERACION_ESPEJO",
                        dir_reg / "recuperacion_requerida_espejo.json",
                        raising=False)
    monkeypatch.setattr(backend, "_inconsistencias_activas", {}, raising=False)
    monkeypatch.setattr(backend, "_aliases_inconsistencias", {}, raising=False)
    monkeypatch.setattr(backend, "_modo_recuperacion", None, raising=False)
    return dir_reg


def _reiniciar() -> None:
    """Reinicio simulado: sólo queda lo durable + la sonda de arranque."""
    backend._inconsistencias_activas.clear()
    backend._modo_recuperacion = None
    backend.inicializar_recuperacion()


def _claves_durables(registro: Path) -> list[str]:
    ruta = registro / "estado_inconsistente.json"
    if not ruta.is_file():
        return []
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    return [str(e.get("recurso")) for e in datos.get("inconsistencias", [])]


def _verificar(prueba_id: str = CLAVE, expected_revision=None):
    return backend.verificar_imagen(backend.SolicitudImagenVerificada(
        prueba_id=prueba_id, imagen_id="IMG1", usuario="revisor",
        expected_revision=(REV_INICIAL if expected_revision is None
                           else expected_revision)))


def _boom(*_a, **_kw):
    raise RuntimeError("fallo simulado de tarea opcional post-commit")


# ---------------------------------------------------------------------------
# ALTO-01 — una transacción ajena no puede resolver inconsistencias
# ---------------------------------------------------------------------------

def test_alto01_exito_no_resuelve_inconsistencia_ajena(env, registro):
    """Repro del auditor: B ya está en vuelo cuando A registra la
    inconsistencia; el éxito de B NO debe borrarla."""
    tx = backend.TransaccionMultiAlmacen("verificación de imagen",
                                         recurso=f"carpeta:{CLAVE}")
    backend._registrar_inconsistencia(f"carpeta:{CLAVE}", "otra operación",
                                      "rollback fallido de A")
    assert f"carpeta:{CLAVE}" in backend._inconsistencias_activas
    tx.exito()  # B termina «correctamente»
    assert f"carpeta:{CLAVE}" in backend._inconsistencias_activas, (
        "ALTO-01: una transacción exitosa ajena resolvió la inconsistencia")
    assert _claves_durables(registro), (
        "ALTO-01: el registro durable quedó vacío tras el éxito ajeno")
    with pytest.raises(HTTPException) as bloqueo:
        backend._assert_recurso_consistente(f"carpeta:{CLAVE}", "mutar")
    assert bloqueo.value.status_code == 503


def test_alto01_peticion_en_vuelo_no_desbloquea_el_caso(env, registro,
                                                        monkeypatch):
    """Carrera real: otra operación falla mientras B ya superó su precheck."""
    real = env["gestor"].actualizar_revision
    disparo = {"hecho": False}

    def actualizar_con_fallo_ajeno(*args, **kwargs):
        if not disparo["hecho"]:
            disparo["hecho"] = True
            backend._registrar_inconsistencia(
                f"carpeta:{CLAVE}", "operación A",
                "restauración automática fallida (concurrente)")
        return real(*args, **kwargs)

    monkeypatch.setattr(env["gestor"], "actualizar_revision",
                        actualizar_con_fallo_ajeno)
    _verificar()  # B termina su operación con éxito
    assert disparo["hecho"], "el escenario de carrera no llegó a ejecutarse"
    assert f"carpeta:{CLAVE}" in backend._inconsistencias_activas, (
        "ALTO-01: la operación en vuelo desbloqueó el caso tras el fallo ajeno")
    with pytest.raises(HTTPException) as bloqueo:
        _verificar(expected_revision=REV_INICIAL + 1)
    assert bloqueo.value.status_code == 503


def test_alto01_solo_la_api_de_recuperacion_levanta_el_bloqueo(env, registro):
    backend._registrar_inconsistencia(f"carpeta:{CLAVE}", "op", "doble fallo")
    with pytest.raises(HTTPException) as bloqueo:
        _verificar()
    assert bloqueo.value.status_code == 503
    respuesta = backend.resolver_inconsistencia(
        f"carpeta:{CLAVE}",
        backend.SolicitudResolucionInconsistencia(
            usuario="auditor", confirmo_verificacion=True, nota="verificado"))
    assert respuesta["resuelta"] is True
    assert f"carpeta:{CLAVE}" not in backend._inconsistencias_activas
    assert _verificar()["verificada"] is True  # ya desbloqueado


# ---------------------------------------------------------------------------
# ALTO-02 — identidad canónica de recursos
# ---------------------------------------------------------------------------

def test_alto02_inconsistencia_de_carpeta_bloquea_verificar_imagen(env,
                                                                  registro):
    """Repro del auditor: la inconsistencia se registró para `carpeta:<id>` y
    `verificar_imagen` usaba la ruta absoluta de la imagen."""
    backend._registrar_inconsistencia(f"carpeta:{CLAVE}", "prueba",
                                      "bloqueo del caso completo")
    with pytest.raises(HTTPException) as bloqueo:
        _verificar()
    assert bloqueo.value.status_code == 503, (
        "ALTO-02: la verificación avanzó pese al bloqueo activo del caso")
    disco = _leer(env["validacion"])
    assert int(disco["revision_documento"]) == REV_INICIAL
    assert disco["resultados"][0]["imagenes"][0].get("estado_imagen") != "verificada"


def test_alto02_inconsistencia_de_imagen_bloquea_operacion_de_carpeta(env,
                                                                     registro):
    """Polaridad inversa: una inconsistencia de la imagen (registrada por el
    formato heredado) bloquea las operaciones de la carpeta del mismo caso."""
    backend._registrar_inconsistencia(str(env["imagen"]), "prueba",
                                      "bloqueo registrado por ruta")
    with pytest.raises(HTTPException) as bloqueo:
        backend.corregir_lectura(backend.SolicitudCorreccion(
            prueba_id=CLAVE, campo="etiqueta", imagen_id="IMG1",
            texto_ocr="ABC", texto_correcto="ABD", tipo_unidad="token",
            accion="guardar_sin_entrenar", usuario="t",
            expected_revision=REV_INICIAL))
    assert bloqueo.value.status_code == 503, (
        "ALTO-02: la carpeta siguió admitiendo mutaciones con la imagen bloqueada")
    claves = _claves_durables(registro)
    assert any(c.startswith(f"carpeta:{CLAVE}") for c in claves), (
        "ALTO-02: el registro durable no quedó en la identidad canónica")


def test_alto02_inconsistencia_de_carpeta_bloquea_revision_de_video(env,
                                                                   registro):
    backend._registrar_inconsistencia(f"carpeta:{CLAVE}", "prueba",
                                      "bloqueo del caso completo")
    with pytest.raises(HTTPException) as bloqueo:
        backend.revisar_video(backend.SolicitudRevisionVideo(
            prueba_id=CLAVE, video_id="V1", estado="pendiente", usuario="t",
            expected_revision=REV_INICIAL))
    assert bloqueo.value.status_code == 503, (
        "ALTO-02: el video del caso bloqueado siguió admitiendo mutaciones")


def test_alto02_inconsistencia_de_carpeta_bloquea_rotacion(env, registro):
    backend._registrar_inconsistencia(f"carpeta:{CLAVE}", "prueba",
                                      "bloqueo del caso completo")
    with pytest.raises(HTTPException) as bloqueo:
        backend.guardar_rotacion(backend.SolicitudRotacion(
            tipo="carpeta", prueba_id=CLAVE, imagen_id="IMG1", grados=90,
            expected_revision=REV_INICIAL))
    assert bloqueo.value.status_code == 503, (
        "ALTO-02: la rotación de la imagen siguió admitiendo mutaciones")


def test_alto02_identidad_canonica_de_recursos(env, registro):
    """Contrato de identidad: carpeta / imagen / video / externa."""
    canon = backend._recurso_canonico
    assert canon(f"carpeta:{CLAVE}") == f"carpeta:{CLAVE}"
    assert canon(f"externa:{CLAVE}") == f"externa:{CLAVE}"
    img = canon(str(env["imagen"]))
    vid = canon(str(env["video"]))
    assert img == f"carpeta:{CLAVE}#imagen:IMG1", img
    assert vid == f"carpeta:{CLAVE}#video:V1", vid
    assert backend._recursos_relacionados(f"carpeta:{CLAVE}") >= {
        f"carpeta:{CLAVE}", img, vid}
    assert backend._recursos_relacionados(img) >= {img, f"carpeta:{CLAVE}"}
    # El subrecurso declara explícitamente a su padre.
    assert backend._padre_recurso(vid) == f"carpeta:{CLAVE}"


def test_alto02_entradas_heredadas_se_migran_al_cargar(env, registro,
                                                       monkeypatch):
    """Un registro escrito por R15.6 con la ruta cruda debe seguir bloqueando
    tras el upgrade (aliases al cargar desde disco)."""
    ruta = registro / "estado_inconsistente.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps({"inconsistencias": [
        {"recurso": str(env["imagen"]), "operacion": "R15.6",
         "detalle": "clave heredada por ruta", "fecha": "2026-10-15T10:00:00"}]}),
        encoding="utf-8")
    _reiniciar()
    assert f"carpeta:{CLAVE}" in backend._inconsistencias_activas or \
        str(env["imagen"]) in backend._inconsistencias_activas
    with pytest.raises(HTTPException) as bloqueo:
        backend.corregir_lectura(backend.SolicitudCorreccion(
            prueba_id=CLAVE, imagen_id="IMG1", campo="etiqueta",
            texto_ocr="ABC", texto_correcto="ABD", tipo_unidad="token",
            usuario="t", expected_revision=REV_INICIAL))
    assert bloqueo.value.status_code == 503, (
        "ALTO-02: una inconsistencia heredada dejó de bloquear tras migrar")


# ---------------------------------------------------------------------------
# ALTO-03 — sonda de arranque fail-closed
# ---------------------------------------------------------------------------

def _almacen_no_escribible(tmp: Path):
    bloqueador = tmp / "bloqueador"
    bloqueador.write_text("soy un archivo, no un directorio", encoding="utf-8")
    return (bloqueador / "sub" / "estado_inconsistente.json",
            bloqueador / "sub2" / "recuperacion_requerida.json")


def test_alto03_arranque_fail_closed_sin_registro_ni_centinela(env, registro,
                                                               monkeypatch):
    """Repro del auditor: registro + centinela no escribibles ⇒ tras reiniciar
    el guard permitía continuar (`after restart guard: ALLOWED`)."""
    ruta_reg, ruta_cent = _almacen_no_escribible(env["tmp"])
    monkeypatch.setattr(backend, "RUTA_INCONSISTENCIAS", ruta_reg)
    monkeypatch.setattr(backend, "RUTA_RECUPERACION", ruta_cent)
    backend._inconsistencias_activas.clear()
    backend._modo_recuperacion = None
    backend.inicializar_recuperacion()  # sonda obligatoria de arranque
    with pytest.raises(HTTPException) as bloqueo:
        backend._assert_recurso_consistente(f"carpeta:{CLAVE}", "seguir")
    assert bloqueo.value.status_code == 503, (
        "ALTO-03: sin registro ni centinela durables el sistema volvió a "
        "modo normal (fail-open)")
    with pytest.raises(HTTPException) as bloqueo_edit:
        backend._assert_documento_editable("editar el documento")
    assert bloqueo_edit.value.status_code == 503


def test_alto03_sonda_ok_no_bloquea(env, registro):
    """Sin falsos positivos: un almacén sano no activa modo recuperación."""
    backend.inicializar_recuperacion()
    assert backend._modo_recuperacion is None
    sonda = backend._sonda_recuperacion()
    assert sonda["escribible"] is True
    assert sonda["releido"] is True
    # Un almacén sano no bloquea: el guard no lanza por modo recuperación.
    backend._assert_recurso_consistente(f"carpeta:{CLAVE}", "mutar")


def test_alto03_doble_ubicacion_del_centinela(env, registro, monkeypatch):
    """El centinela se replica en una segunda ubicación independiente: si la
    primera no puede escribirse, el arranque sigue detectando recuperación."""
    ruta_reg, ruta_cent = _almacen_no_escribible(env["tmp"])
    espejo = env["tmp"] / "espejo_estado" / "recuperacion_requerida.json"
    monkeypatch.setattr(backend, "RUTA_INCONSISTENCIAS", ruta_reg)
    monkeypatch.setattr(backend, "RUTA_RECUPERACION", ruta_cent)
    monkeypatch.setattr(backend, "RUTA_RECUPERACION_ESPEJO", espejo)
    backend._inconsistencias_activas.clear()
    backend._modo_recuperacion = None
    backend._activar_modo_recuperacion("doble fallo simulado")
    assert espejo.is_file(), (
        "ALTO-03: el centinela no se replicó en la ubicación secundaria")
    backend._inconsistencias_activas.clear()
    backend._modo_recuperacion = None
    backend.inicializar_recuperacion()
    with pytest.raises(HTTPException) as bloqueo:
        backend._assert_recurso_consistente(f"carpeta:{CLAVE}", "mutar")
    assert bloqueo.value.status_code == 503


# ---------------------------------------------------------------------------
# MEDIO-04 — post-commit best-effort
# ---------------------------------------------------------------------------

def test_medio04_fallo_incorporar_uniones_no_convierte_en_error(env, registro,
                                                               monkeypatch):
    """Repro del auditor: RuntimeError en `incorporar_uniones_guardadas`
    escapaba del endpoint con el commit ya guardado."""
    monkeypatch.setattr(env["gestor"], "incorporar_uniones_guardadas", _boom)
    resultado = _verificar()
    assert resultado["verificada"] is True
    assert resultado.get("advertencia_aprendizaje"), (
        "MEDIO-04: el fallo de la tarea opcional no quedó como advertencia")
    disco = _leer(env["validacion"])
    assert int(disco["revision_documento"]) == REV_INICIAL + 1
    assert disco["resultados"][0]["imagenes"][0]["estado_imagen"] == "verificada"


def test_medio04_fallo_entrenamiento_visual_no_convierte_en_error(env, registro,
                                                                 monkeypatch):
    monkeypatch.setattr(backend, "_programar_entrenamiento_visual_auto", _boom)
    resultado = _verificar()
    assert resultado["verificada"] is True
    assert resultado.get("advertencia_aprendizaje")
    disco = _leer(env["validacion"])
    assert int(disco["revision_documento"]) == REV_INICIAL + 1


def test_medio04_error_inesperado_del_aprendizaje_tampoco_es_fatal(env, registro,
                                                                  monkeypatch):
    """Cualquier excepción (no sólo OSError/ValueError) es no fatal."""
    monkeypatch.setattr(env["gestor"], "incorporar_uniones_guardadas",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            KeyError("clave ausente en el dataset")))
    resultado = _verificar()
    assert resultado["verificada"] is True
    assert "KeyError" in json.dumps(resultado.get("advertencia_aprendizaje", ""),
                                    ensure_ascii=False)


# ---------------------------------------------------------------------------
# MEDIO-05 — CAS estricto en writers externos versionados
# ---------------------------------------------------------------------------

def _documento_externo_con_revision(externas, revision: int = 5) -> None:
    documento = _leer_externo(externas["salida"])
    documento["revision_documento"] = revision
    externas["salida"].write_text(json.dumps(documento), encoding="utf-8")


def test_medio05_marca_externa_sin_expected_revision_409(env, externas, registro):
    _documento_externo_con_revision(externas, 5)
    with pytest.raises(HTTPException) as conflicto:
        backend.marcar_imagen_sin_datos(backend.SolicitudImagenSinDatos(
            tipo="externa", prueba_id="EXT1", imagen_id=None,
            motivo="sin datos", usuario="revisor", expected_revision=None))
    assert conflicto.value.status_code == 409, (
        "MEDIO-05: la rama externa aceptó expected_revision=None con "
        "revision_documento>0")
    assert int(_leer_externo(externas["salida"])["revision_documento"]) == 5


def test_medio05_restaurar_externa_sin_expected_revision_409(env, externas,
                                                             registro):
    _documento_externo_con_revision(externas, 4)
    with pytest.raises(HTTPException) as conflicto:
        backend.restaurar_imagen_con_texto(backend.SolicitudImagenSinDatos(
            tipo="externa", prueba_id="EXT1", imagen_id=None,
            expected_revision=None, usuario="t"))
    assert conflicto.value.status_code == 409, (
        "MEDIO-05: restaurar en rama externa aceptó expected_revision=None")


def test_medio05_rotacion_externa_sin_expected_revision_409(env, externas,
                                                            registro):
    _documento_externo_con_revision(externas, 7)
    with pytest.raises(HTTPException) as conflicto:
        backend.guardar_rotacion(backend.SolicitudRotacion(
            tipo="externa", prueba_id="EXT1", imagen_id=None, grados=90,
            expected_revision=None))
    assert conflicto.value.status_code == 409, (
        "MEDIO-05: la rotación externa aceptó expected_revision=None")


def test_medio05_escritor_externo_con_revision_correcta_funciona(env, externas,
                                                                 registro):
    """Control: con la revisión correcta el writer externo sigue operando."""
    _documento_externo_con_revision(externas, 5)
    resultado = backend.marcar_imagen_sin_datos(backend.SolicitudImagenSinDatos(
        tipo="externa", prueba_id="EXT1", imagen_id=None, motivo="sin datos",
        usuario="revisor", expected_revision=5))
    assert resultado
    documento = _leer_externo(externas["salida"])
    assert int(documento["revision_documento"]) == 6


# ---------------------------------------------------------------------------
# BAJO-07 — la resolución verifica el borrado del centinela
# ---------------------------------------------------------------------------

def test_bajo07_resolucion_reporta_centinela_no_eliminado(env, registro,
                                                          monkeypatch):
    """Si el centinela no puede eliminarse, la sesión no debe declarar
    «resolución completa»: el próximo arranque volvería a recuperarse."""
    centinela = registro / "recuperacion_requerida.json"
    centinela.mkdir(parents=True, exist_ok=True)  # unlink() fallará
    backend._modo_recuperacion = {"motivo": "simulado", "fecha": "2026-10-16"}
    respuesta = backend.resolver_modo_recuperacion(
        backend.SolicitudResolucionInconsistencia(
            usuario="auditor", confirmo_verificacion=True))
    assert respuesta["modo_recuperacion"] is None
    assert respuesta.get("centinela_eliminado") is False, (
        "BAJO-07: se declaró resuelto con el centinela todavía presente")
    assert respuesta.get("advertencia_centinela")


def test_bajo07_resolucion_normal_elimina_el_centinela(env, registro):
    centinela = registro / "recuperacion_requerida.json"
    centinela.parent.mkdir(parents=True, exist_ok=True)
    centinela.write_text(json.dumps({"motivo": "x", "fecha": "y"}),
                         encoding="utf-8")
    backend._modo_recuperacion = {"motivo": "simulado", "fecha": "2026-10-16"}
    respuesta = backend.resolver_modo_recuperacion(
        backend.SolicitudResolucionInconsistencia(
            usuario="auditor", confirmo_verificacion=True))
    assert respuesta.get("centinela_eliminado") is True
    assert not centinela.exists()


# ---------------------------------------------------------------------------
# P2 — evidencia del árbol destino (inventario posterior al upgrade)
# ---------------------------------------------------------------------------

def test_p2_inventario_del_arbol_destino(env, tmp_path):
    """El inventario del árbol destino reporta identidad, conteos y extras
    heredados (BAJO-06: staging 39 vs base histórica 40 `.cjs`)."""
    from utilidades.inventario_destino import inventariar_destino

    destino = tmp_path / "destino"
    (destino / "pruebas").mkdir(parents=True)
    (destino / "VERSION.txt").write_text("15.10.1-r15.7", encoding="utf-8")
    (destino / "dashboard" / "backend").mkdir(parents=True)
    (destino / "dashboard" / "backend" / "app.py").write_text(
        'PATCH_BUILD = "15.10.1-r15.7"\n', encoding="utf-8")
    for nombre in ("a.cjs", "b.cjs", "legado.cjs"):
        (destino / "pruebas" / nombre).write_text("// test\n", encoding="utf-8")
    (destino / "pruebas" / "test_x.py").write_text("# test\n", encoding="utf-8")

    staging = tmp_path / "staging"
    (staging / "pruebas").mkdir(parents=True)
    for nombre in ("a.cjs", "b.cjs"):
        (staging / "pruebas" / nombre).write_text("// test\n", encoding="utf-8")

    informe = inventariar_destino(destino, staging=staging)
    assert informe["identidad"]["version"] == "15.10.1-r15.7"
    assert informe["identidad"]["patch_build"] == "15.10.1-r15.7"
    assert informe["pruebas"]["cjs"] == 3
    assert informe["pruebas"]["py"] == 1
    assert informe["pruebas"]["extras_heredados"] == ["legado.cjs"]
    assert informe["pruebas"]["staging"] == {"cjs": 2, "py": 0}
    assert informe["coherente"] is True
