"""R15.9 — Durabilidad de la sonda, preservación byte a byte y soak con
identidad estricta (auditoría independiente R15.8,
`AUDITORIA_INDEPENDIENTE_R15_8_20261018.md`).

Hallazgos reproducidos por el auditor y cubiertos aquí (uno a uno):

* ALTO-03 — la sonda sustituía el registro real sin respaldo: un corte
  abrupto entre la sustitución y la restauración perdía las entradas
  (repro del auditor: ``SystemExit`` tras ``_escribir_json_verificado`` ⇒
  ``registro_igual=false``, ``quedo_sonda=true`` y SIN vía de recuperación).
  Ahora: copia de respaldo DURABLE (fsync+replace+relectura) ANTES de tocar
  el target y protocolo de recuperación al reinicio
  (``_leer_registro_o_respaldo``).
* MEDIO-04 — la restauración en modo TEXTO normalizaba CRLF→LF: un registro
  válido con CRLF salía con otro SHA-256 (``bytes_iguales=false``). Ahora
  toda la sonda opera a nivel de BYTES (CRLF/BOM/UTF-8 intactos).
* MEDIO-05 — el soak aceptaba como final un estado terminal AJENO tras
  observar cualquier activo (repro del auditor: activo ANTERIOR + terminal
  ANTERIOR con ejecución pedida NUEVA ⇒ devolvía ANTERIOR). Ahora la
  identidad es estricta cuando el POST devolvió ``ejecucion_id``.

Cada prueba reproduce el escenario del auditor o su corrección mínima, y
falla sobre el árbol R15.8 sin el endurecimiento R15.9.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest

import dashboard.backend.app as backend
from test_v15_10_1_r153_cas_efectos import env  # noqa: F401 — fixture compartida
from validacion_campo import soak_r157


@pytest.fixture
def registro(env, monkeypatch):
    """Registro/centinela/auditoría aislados en tmp (mismo aislamiento que la
    suite R15.6/R15.7/R15.8) + estado inicial limpio."""
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
    monkeypatch.setattr(backend, "_modo_recuperacion", None, raising=False)
    dir_reg.mkdir(parents=True, exist_ok=True)
    return dir_reg


REGISTRO_CRLF = (b'{\r\n  "inconsistencias": [\r\n'
                 b'    {"recurso": "carpeta:CASO1"}\r\n  ]\r\n}\r\n')
REGISTRO_BOM = ('﻿{"inconsistencias": [{"recurso": "carpeta:BOM1"}]}'
                .encode("utf-8"))
REGISTRO_UTF8 = '{"inconsistencias": [{"recurso": "carpeta:ÑÖ-ñeo"}]}'.encode(
    "utf-8")


# ---------------------------------------------------------------------------
# MEDIO-04 — preservación byte a byte (CRLF / BOM / UTF-8)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("original", [REGISTRO_CRLF, REGISTRO_BOM,
                                      REGISTRO_UTF8],
                         ids=["CRLF", "BOM-UTF-8", "UTF-8-acentos"])
def test_medio04_sonda_preserva_los_bytes_exactos(env, registro, original):
    """Repro del auditor: un registro JSON válido con CRLF debía salir con el
    MISMO SHA-256 tras la sonda (antes: normalización CRLF→LF)."""
    objetivo = registro / "estado_inconsistente.json"
    objetivo.write_bytes(original)
    sonda = backend._sonda_recuperacion()
    assert sonda["escribible"] is True, sonda
    assert objetivo.read_bytes() == original, (
        "MEDIO-04: la sonda alteró los bytes del registro "
        "(CRLF/BOM no preservados)")


def test_medio04_restauracion_usa_bytes_no_texto(env, registro):
    """El ayudante de restauración trabaja en binario: ni lectura ni escritura
    pasan por modo texto (universal newlines). El contraste demuestra que el
    camino en MODO TEXTO de R15.8 sí normalizaba CRLF→LF."""
    objetivo = registro / "estado_inconsistente.json"
    original = b"a\r\nb\r\n"
    backend._escribir_bytes_verificados(objetivo, original)
    assert objetivo.read_bytes() == original
    assert not list(registro.glob("*.tmp"))
    # Contraste: el camino TEXTO de R15.8 (read_text + newline="") cambiaba
    # los bytes — por eso el R15.9 exige el camino binario.
    temporal = objetivo.with_name(objetivo.name + ".texto.tmp")
    with open(temporal, "w", encoding="utf-8", newline="") as fh:
        fh.write(original.decode("utf-8").replace("\r\n", "\n"))
    temporal.replace(objetivo)
    assert objetivo.read_bytes() != original, (
        "el contraste exige que el modo texto altere CRLF")


# ---------------------------------------------------------------------------
# ALTO-03 — respaldo durable + protocolo de recuperación
# ---------------------------------------------------------------------------

def _matar_durante_la_sonda(objetivo: Path, original: bytes) -> None:
    """Repro literal del auditor: SystemExit justo después de que la sonda
    sustituyó el registro y antes de restaurarlo (muerte del proceso)."""
    escritura_real = backend._escribir_json_verificado

    def injection(ruta, payload):
        escritura_real(ruta, payload)
        raise SystemExit("simulated process loss")

    with patch.object(backend, "RUTA_INCONSISTENCIAS", objetivo), \
            patch.object(backend, "_escribir_json_verificado",
                         side_effect=injection):
        with pytest.raises(SystemExit):
            backend._sonda_recuperacion()


def test_alto03_interrupcion_deja_respaldo_y_el_arranque_recupera(env,
                                                                  registro):
    """Repro del auditor + corrección: tras la muerte abrupta el target
    contiene la sonda (inevitable), pero EXISTE un respaldo durable con los
    bytes originales y el siguiente arranque RECUPERA las entradas sin
    activar el modo recuperación."""
    objetivo = registro / "estado_inconsistente.json"
    original = REGISTRO_CRLF
    objetivo.write_bytes(original)
    _matar_durante_la_sonda(objetivo, original)
    respaldo = backend._ruta_respaldo_sonda()
    assert respaldo.is_file(), (
        "ALTO-03: la sonda dejó el único registro sustituido SIN backup")
    assert json.loads(objetivo.read_text()).get("sonda") is True, (
        "el repro exige que la muerte ocurrió con el target ya sustituido")
    assert respaldo.read_bytes() == original, (
        "ALTO-03: el respaldo no contiene los bytes originales")
    # Siguiente arranque (reinicio simulado: sólo queda lo durable).
    backend._inconsistencias_activas.clear()
    backend._modo_recuperacion = None
    backend._cargar_inconsistencias()
    assert "carpeta:CASO1" in backend._inconsistencias_activas, (
        "ALTO-03: las entradas originales se perdieron")
    assert backend._modo_recuperacion is None, (
        "ALTO-03: con respaldo utilizable no debe activarse modo recuperación")
    assert objetivo.read_bytes() == original, (
        "ALTO-03: la recuperación no restauró el registro byte a byte")
    assert not respaldo.exists(), (
        "ALTO-03: el respaldo debe retirarse tras recuperarlo")


def test_alto03_sonda_sana_retira_el_respaldo(env, registro):
    """Sin residuos: una sonda que termina bien no deja respaldo ni temporales."""
    objetivo = registro / "estado_inconsistente.json"
    objetivo.write_bytes(REGISTRO_UTF8)
    sonda = backend._sonda_recuperacion()
    assert sonda["escribible"] is True
    assert not backend._ruta_respaldo_sonda().exists()
    assert not list(registro.glob("*.tmp"))


def test_alto03_registro_danado_con_respaldo_se_recupera(env, registro):
    """Un registro corrupto (p. ej. escrito a medias por un corte) con
    respaldo válido se recupera en el arranque."""
    objetivo = registro / "estado_inconsistente.json"
    objetivo.write_bytes(b'{"inconsistencias": [ {"recurso": "carpeta:X"')  # truncado
    respaldo = backend._ruta_respaldo_sonda()
    respaldo.write_bytes(REGISTRO_CRLF)
    backend._inconsistencias_activas.clear()
    backend._modo_recuperacion = None
    backend._cargar_inconsistencias()
    assert "carpeta:CASO1" in backend._inconsistencias_activas
    assert backend._modo_recuperacion is None
    assert objetivo.read_bytes() == REGISTRO_CRLF


def test_alto03_registro_danado_sin_respaldo_sigue_fail_closed(env, registro):
    """Regresión R15.6 intacta: registro ilegible SIN respaldo ⇒ modo
    recuperación (el protocolo nuevo no afloja el fail-closed)."""
    objetivo = registro / "estado_inconsistente.json"
    objetivo.write_bytes(b"{ esto no es json")
    backend._inconsistencias_activas.clear()
    backend._modo_recuperacion = None
    backend._cargar_inconsistencias()
    assert backend._modo_recuperacion is not None


def test_alto03_registro_danado_con_respaldo_invalido_fail_closed(env,
                                                                  registro):
    objetivo = registro / "estado_inconsistente.json"
    objetivo.write_bytes(b"{ corrupto")
    backend._ruta_respaldo_sonda().write_bytes(b"{ respaldo corrupto")
    backend._inconsistencias_activas.clear()
    backend._modo_recuperacion = None
    backend._cargar_inconsistencias()
    assert backend._modo_recuperacion is not None


def test_alto03_registro_sano_limpia_respaldo_residual(env, registro):
    """Registro sano + respaldo residual (interrupción tras restaurar y antes
    de retirar el backup) ⇒ el arranque lo limpia y carga normal."""
    objetivo = registro / "estado_inconsistente.json"
    objetivo.write_bytes(REGISTRO_CRLF)
    backend._ruta_respaldo_sonda().write_bytes(REGISTRO_CRLF)
    backend._inconsistencias_activas.clear()
    backend._modo_recuperacion = None
    backend._cargar_inconsistencias()
    assert "carpeta:CASO1" in backend._inconsistencias_activas
    assert backend._modo_recuperacion is None
    assert not backend._ruta_respaldo_sonda().exists()


def test_alto03_sonda_falla_con_registro_ilegible_y_no_lo_toca(env, registro):
    """Un registro ILEGIBLE no se respalda ni se sustituye: fail-closed con
    el archivo intacto (el operador decide qué hacer con la evidencia)."""
    objetivo = registro / "estado_inconsistente.json"
    objetivo.write_bytes(b"{ no-json")
    sonda = backend._sonda_recuperacion()
    assert sonda["escribible"] is False
    assert "no es legible" in sonda["error"]
    assert objetivo.read_bytes() == b"{ no-json"
    assert not backend._ruta_respaldo_sonda().exists()


# ---------------------------------------------------------------------------
# MEDIO-05 — soak con identidad estricta por ejecucion_id
# ---------------------------------------------------------------------------

def test_medio05_soak_rechaza_activo_y_terminal_de_otra_ejecucion():
    """Repro EXACTO del auditor: activo ANTERIOR + terminal ANTERIOR con
    ejecución pedida NUEVA. R15.8 devolvía ANTERIOR (``acepto_terminacion_ajena
    = true``); R15.9 no acepta la ejecución ajena y sigue esperando (el
    generador se agota ⇒ IndexError, igual que en el script del auditor)."""
    estados = [{"estado": "procesando", "ejecucion_id": "ANTERIOR"},
               {"estado": "completado", "ejecucion_id": "ANTERIOR"}]

    def responder(*args, **kwargs):
        return estados.pop(0)

    with patch.object(soak_r157, "_pedir_json", side_effect=responder):
        with pytest.raises((IndexError, soak_r157.ErrorSoak)):
            soak_r157._esperar_pipeline("http://dummy", intervalo=0,
                                        arranque_max=.01, esperar_max=.1,
                                        ejecucion_objetivo="NUEVA")


def test_medio05_soak_id_ausente_es_inconcluso_cuando_se_espera_un_id():
    """Un terminal SIN id no equivale a la ejecución pedida (evidencia
    inconclusa): se sigue esperando hasta agotar la ventana de admisión."""
    estados = [{"estado": "procesando"}, {"estado": "completado"}]

    def responder(*args, **kwargs):
        return estados.pop(0) if estados else {"estado": "completado"}

    with patch.object(soak_r157, "_pedir_json", side_effect=responder):
        with pytest.raises(soak_r157.ErrorSoak) as fallo:
            soak_r157._esperar_pipeline("http://dummy", intervalo=0,
                                        arranque_max=.05, esperar_max=5,
                                        ejecucion_objetivo="NUEVA")
    assert "no arrancó" in str(fallo.value)


def test_medio05_soak_acepta_terminal_propio_antes_del_primer_sondeo():
    """MEDIO-07 (R15.8) se conserva: terminal de la MISMA ejecución aceptado
    aunque no se viera nunca un estado activo."""
    estados = [{"estado": "completado", "ejecucion_id": "NUEVA",
                "resumen": {}}]
    with patch.object(soak_r157, "_pedir_json", side_effect=lambda *a, **k: estados.pop(0)):
        final = soak_r157._esperar_pipeline("http://dummy", intervalo=0,
                                            arranque_max=.05, esperar_max=5,
                                            ejecucion_objetivo="NUEVA")
    assert final["ejecucion_id"] == "NUEVA"


def test_medio05_soak_sin_ids_conserva_criterio_heredado():
    """Servidor sin identidad por ejecución y POST sin id: activo→terminal
    sigue siendo la única evidencia disponible (comportamiento heredado)."""
    estados = [{"estado": "procesando"}, {"estado": "completado"}]
    with patch.object(soak_r157, "_pedir_json", side_effect=lambda *a, **k: estados.pop(0)):
        final = soak_r157._esperar_pipeline("http://dummy", intervalo=0,
                                            arranque_max=5, esperar_max=5,
                                            ejecucion_objetivo=None)
    assert final["estado"] == "completado"


def test_medio05_soak_terminal_propio_tras_activo_propio():
    """Camino feliz con identidad: activo NUEVA → terminal NUEVA aceptado."""
    estados = [{"estado": "procesando", "ejecucion_id": "NUEVA"},
               {"estado": "completado", "ejecucion_id": "NUEVA"}]
    with patch.object(soak_r157, "_pedir_json", side_effect=lambda *a, **k: estados.pop(0)):
        final = soak_r157._esperar_pipeline("http://dummy", intervalo=0,
                                            arranque_max=5, esperar_max=5,
                                            ejecucion_objetivo="NUEVA")
    assert final["estado"] == "completado"
    assert final["ejecucion_id"] == "NUEVA"


# ---------------------------------------------------------------------------
# Identidad del soak (constantes por defecto = árbol vigente)
# ---------------------------------------------------------------------------

def test_soak_identidad_por_defecto_es_la_del_arbol():
    raiz = Path(__file__).resolve().parents[1]
    build = (raiz / "VERSION.txt").read_text(encoding="utf-8").strip()
    assert soak_r157.PATCH_BUILD_R159 == build
    assert soak_r157.PATCH_BUILD_R158 == build, (
        "el alias histórico R15.8 debe apuntar a la identidad vigente")
    assert soak_r157.PATCH_BUILD_R157 == build, (
        "el alias histórico R15.7 debe apuntar a la identidad vigente")


# ---------------------------------------------------------------------------
# R15.9 REVISIÓN (auditoría del paquete entregado: bom_r158.log vs bom_r159.log)
# — loader y sonda con el MISMO criterio binario + motivo con detalle.
# ---------------------------------------------------------------------------

def test_revision_registro_con_bom_carga_y_sobrevive_a_la_sonda(env, registro):
    """Guion del auditor (bom_r159.log) con criterio unificado: un registro
    válido con BOM UTF-8 (re-guardado con un editor de Windows) CARGA sus
    entradas, la sonda lo preserva byte a byte y el arranque siguiente sigue
    leyéndolo sin modo de recuperación."""
    objetivo = registro / "estado_inconsistente.json"
    objetivo.write_bytes(REGISTRO_BOM)
    backend._cargar_inconsistencias()
    assert backend._modo_recuperacion is None, (
        "revisión: un registro válido con BOM no debe activar modo "
        "recuperación (la sonda ya lo aceptaba en bytes: criterios "
        "distintos para el mismo fichero)")
    assert "carpeta:BOM1" in backend._inconsistencias_activas
    resultado = backend._sonda_recuperacion()
    assert resultado["escribible"] is True and resultado["error"] is None
    assert objetivo.read_bytes() == REGISTRO_BOM, (
        "revisión: la sonda alteró los bytes de un registro con BOM")
    assert not backend._ruta_respaldo_sonda().exists(), (
        "revisión: la sonda dejó respaldo residual tras retirarlo")
    # Arranque siguiente: el mismo registro intacto sigue cargando.
    backend._inconsistencias_activas.clear()
    backend._modo_recuperacion = None
    backend._cargar_inconsistencias()
    assert backend._modo_recuperacion is None
    assert "carpeta:BOM1" in backend._inconsistencias_activas


def test_revision_registro_danado_reporta_el_detalle_en_el_motivo(env, registro):
    """R15.8 informaba la CAUSA exacta en el motivo («(JSONDecodeError: …)»);
    el corte R15.9 la había perdido. Un registro dañado sigue en fail-closed
    PERO el motivo vuelve a traer el detalle para diagnóstico de campo."""
    objetivo = registro / "estado_inconsistente.json"
    truncado = b'{"inconsistencias": [{"recurso": "carpeta:X"}'
    objetivo.write_bytes(truncado)
    backend._cargar_inconsistencias()
    motivo = str((backend._modo_recuperacion or {}).get("motivo") or "")
    assert motivo.startswith("registro de inconsistencias ilegible"), motivo
    assert "JSONDecodeError" in motivo, (
        "revisión: el motivo perdió el detalle del daño "
        "(diagnóstico de campo, comportamiento R15.8)")
    assert objetivo.read_bytes() == truncado, (
        "el fail-closed no debe tocar el fichero dañado")

@pytest.mark.parametrize("registro_malformado", [
    b'{"inconsistencias": [null]}',
    b'{"inconsistencias": [42]}',
    b'{"inconsistencias": [{"recurso": "carpeta:OK", "aliases": 42}]}',
    b'{"inconsistencias": [{"recurso": "carpeta:OK", "aliases": [42, "carpeta:XYZ"]}]}',
    b'{"inconsistencias": [{"recurso": 42}]}',
    b'{"inconsistencias": [{"recurso": "  "}]}',
], ids=["entrada-null", "entrada-numero", "aliases-no-lista",
       "aliases-mixtos", "recurso-no-texto", "recurso-vacio"])
def test_revision_esquema_invalido_falla_cerrado_sin_mutar_archivo(
        registro, registro_malformado):
    """Repro independiente 2026-10-19: JSON válido con esquema interno
    inválido no lanza excepciones, no migra parcialmente y conserva bytes."""
    objetivo = registro / "estado_inconsistente.json"
    objetivo.write_bytes(registro_malformado)

    backend._cargar_inconsistencias()

    assert backend._modo_recuperacion is not None
    assert not backend._inconsistencias_activas
    assert objetivo.read_bytes() == registro_malformado
    assert "estructura no reconocida" in backend._modo_recuperacion["motivo"]


def test_revision_respaldo_malformado_sin_target_no_se_toma_por_instalacion_fresca(
        registro):
    """Un respaldo residual inválido con target ausente también es fail-closed;
    su existencia demuestra que había un registro previo que no se pudo leer."""
    respaldo = registro / "estado_inconsistente.json.respaldo_sonda"
    original = b'{"inconsistencias": [null]}'
    respaldo.write_bytes(original)

    backend._cargar_inconsistencias()

    assert backend._modo_recuperacion is not None
    assert not backend._inconsistencias_activas
    assert not (registro / "estado_inconsistente.json").exists()
    assert respaldo.read_bytes() == original
