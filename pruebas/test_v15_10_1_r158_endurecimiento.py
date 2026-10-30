"""R15.8 — Cierre del perímetro de recuperación y herramental de campo
(revalidación independiente de R15.7, `AUDITORIA_REVALIDADA_R15_7_20261016.md`).

Hallazgos reproducidos por la revalidación y cubiertos aquí (uno a uno):

* ALTO-01 — la sonda de recuperación probaba un archivo HERMANO
  (``sonda_recuperacion.json``) y no el target real: con
  ``estado_inconsistente.json`` no reemplazable y el directorio escribible,
  el arranque creía durable un registro que no se podía escribir.
* ALTO-02 — la migración de rutas heredadas resolvía las rutas RELATIVAS
  contra el working directory del servidor y no contra ``datos['raiz']``: un
  bloqueo real creado antes del upgrade dejaba de bloquear al caso canónico.
* ALTO-03 — ``/api/externas/evaluar`` (y cualquier endpoint mutante) podía
  ejecutarse durante MODO RECUPERACIÓN; ahora existe un guard TRANSVERSAL
  declarado para todas las rutas POST/PUT/PATCH/DELETE (con el propio flujo
  de recuperación y pausar/cancelar como exenciones DECLARADAS).
* ALTO-04 — ``/api/revisiones`` modificaba un caso con inconsistencia activa.
* MEDIO-05 — ``/api/alertas/atender`` ignoraba el bloqueo de recuperación.
* MEDIO-06 — el listado de recuperación duplicaba alias (total inflado).
* MEDIO-07 — el soak informaba «el pipeline no arrancó» si el POST terminaba
  antes del primer sondeo (sólo aceptaba un terminal tras ver uno activo).
* MEDIO-08 — el soak heredaba el ``ejecucion_id`` de la iteración anterior
  (``locals().get('lanzado')`` sin reiniciar por iteración).

Cada prueba reproduce el escenario del auditor o su corrección mínima, y está
escrita para fallar sobre el árbol R15.7 sin el endurecimiento R15.8.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi import HTTPException, Request
from fastapi.routing import APIRoute

import dashboard.backend.app as backend
import pruebas_externas
from test_v15_10_1_r153_cas_efectos import (  # noqa: F401 — fixtures compartidas
    REV_INICIAL, env, _leer)
from test_v15_10_1_r15_1_documento_global import CLAVE


@pytest.fixture
def registro(env, monkeypatch):
    """Registro/centinela/auditoría aislados en tmp (mismo aislamiento que la
    suite R15.6/R15.7) + estado inicial limpio."""
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
    return dir_reg


def _invalidar_indice() -> None:
    """Fuerza la reconstrucción del índice de rutas (caché por firma)."""
    backend._indice_rutas_cache["firma"] = None


# ---------------------------------------------------------------------------
# ALTO-01 — la sonda prueba el TARGET REAL (estado_inconsistente.json)
# ---------------------------------------------------------------------------

def test_alto01_sonda_falla_si_el_target_no_es_un_archivo_regular(env, registro):
    """Repro del auditor: el padre es escribible pero el target NO es
    reemplazable. La sonda hermana devolvía ``escribible=True`` (bug); la
    sonda R15.8 prueba el target exacto y falla."""
    registro.mkdir(parents=True, exist_ok=True)
    (registro / "estado_inconsistente.json").mkdir()  # target: directorio
    backend._inconsistencias_activas.clear()
    backend._modo_recuperacion = None
    sonda = backend._sonda_recuperacion()
    assert sonda["escribible"] is False, (
        "ALTO-01: la sonda sigue probando un archivo hermano, no el target")
    backend.inicializar_recuperacion()  # arranque fail-closed
    assert backend._modo_recuperacion is not None, (
        "ALTO-01: el arranque no activó el modo recuperación con el target "
        "inservible")
    with pytest.raises(HTTPException) as bloqueo:
        backend._assert_sistema_recuperable("mutar")
    assert bloqueo.value.status_code == 503


def test_alto01_sonda_prueba_el_reemplazo_del_target_real(env, registro,
                                                          monkeypatch):
    """El target existe como archivo regular pero NO puede reemplazarse
    (repro literal del auditor): la sonda debe fallar y el registro previo
    debe quedar intacto."""
    registro.mkdir(parents=True, exist_ok=True)
    objetivo = registro / "estado_inconsistente.json"
    previo = {"inconsistencias": [{"recurso": "carpeta:LEGACY",
                                   "operacion": "op", "detalle": "d"}]}
    objetivo.write_text(json.dumps(previo), encoding="utf-8")

    def reemplazo_bloqueado(self, target):
        raise PermissionError(13, "reemplazo bloqueado (simulado)")

    monkeypatch.setattr(Path, "replace", reemplazo_bloqueado)
    sonda = backend._sonda_recuperacion()
    assert sonda["escribible"] is False, (
        "ALTO-01: la sonda no detectó que el target no es reemplazable")
    assert json.loads(objetivo.read_text(encoding="utf-8")) == previo, (
        "ALTO-01: la sonda dañó el registro previo")
    backend._inconsistencias_activas.clear()
    backend._modo_recuperacion = None
    backend.inicializar_recuperacion()
    assert backend._modo_recuperacion is not None


def test_alto01_sonda_preserva_el_registro_existente(env, registro):
    """Sin falsos positivos: almacén sano ⇒ sonda OK y el contenido previo del
    registro se restaura byte a byte (sin temporales residuales)."""
    registro.mkdir(parents=True, exist_ok=True)
    objetivo = registro / "estado_inconsistente.json"
    previo = {"inconsistencias": [{"recurso": "carpeta:X",
                                   "operacion": "op", "detalle": "d"}]}
    objetivo.write_text(json.dumps(previo), encoding="utf-8")
    sonda = backend._sonda_recuperacion()
    assert sonda["escribible"] is True and sonda["releido"] is True
    assert json.loads(objetivo.read_text(encoding="utf-8")) == previo
    assert backend._modo_recuperacion is None
    assert not list(registro.glob("*.tmp")), "la sonda dejó temporales"


# ---------------------------------------------------------------------------
# ALTO-02 — migración de rutas heredadas contra datos['raiz']
# ---------------------------------------------------------------------------

def _documento_con_ruta_relativa(env) -> None:
    """Reescribe el documento del ``env`` con la imagen en ruta RELATIVA y
    ``raiz`` absoluta (formato real del documento tras mover el lote)."""
    datos = _leer(env["validacion"])
    fila = datos["resultados"][0]
    fila["imagenes"][0]["ruta"] = "CASO1/img_0001.png"
    datos["raiz"] = str(env["lote"])
    env["validacion"].write_text(json.dumps(datos), encoding="utf-8")
    backend._cache["mtime"] = None
    backend._cache["datos"] = None
    _invalidar_indice()


def _escribir_registro_durable(registro: Path, entradas: list) -> None:
    registro.mkdir(parents=True, exist_ok=True)
    (registro / "estado_inconsistente.json").write_text(
        json.dumps({"inconsistencias": entradas}, ensure_ascii=False),
        encoding="utf-8")


def _reiniciar_y_cargar() -> None:
    backend._inconsistencias_activas.clear()
    backend._modo_recuperacion = None
    backend._cargar_inconsistencias()


def test_alto02_migracion_relativa_en_documento_bloquea(env, registro):
    """Repro del auditor: registro heredado con ruta ABSOLUTA de R15.6 y
    documento actual con ruta RELATIVA. La clave canónica del caso debe
    bloquear y la migración debe persistirse canónica."""
    _documento_con_ruta_relativa(env)
    legacy = str(env["imagen"])  # <lote real>/CASO1/img_0001.png (R15.6)
    _escribir_registro_durable(registro, [
        {"recurso": legacy, "operacion": "corrección heredada",
         "detalle": "doble fallo pre-upgrade"}])
    _reiniciar_y_cargar()
    canonico = backend._recurso_canonico(legacy)
    assert canonico == f"carpeta:{CLAVE}#imagen:IMG1", (
        "ALTO-02: la ruta heredada absoluta no migró al recurso canónico del "
        "caso cuando el documento usa rutas relativas")
    with pytest.raises(HTTPException) as bloqueo:
        backend._assert_recurso_consistente(f"carpeta:{CLAVE}", "mutar")
    assert bloqueo.value.status_code == 503
    durable = json.loads(
        (registro / "estado_inconsistente.json").read_text(encoding="utf-8"))
    assert durable["inconsistencias"][0]["recurso"] == canonico, (
        "ALTO-02: la migración canónica no se persistió en el registro durable")
    assert legacy in durable["inconsistencias"][0].get("aliases", [])


def test_alto02_registro_relativo_heredado_bloquea(env, registro):
    """Dirección inversa: registro heredado con ruta RELATIVA y documento con
    rutas absolutas. La resolución contra ``datos['raiz']`` debe encontrar el
    recurso canónico (antes se resolvía contra el working directory)."""
    relativa = "CASO1/img_0001.png"
    _escribir_registro_durable(registro, [
        {"recurso": relativa, "operacion": "corrección heredada",
         "detalle": "doble fallo pre-upgrade"}])
    _reiniciar_y_cargar()
    canonico = backend._recurso_canonico(relativa)
    assert canonico == f"carpeta:{CLAVE}#imagen:IMG1", (
        "ALTO-02: la ruta relativa heredada no se resolvió contra "
        "datos['raiz']")
    with pytest.raises(HTTPException) as bloqueo:
        backend._assert_recurso_consistente(f"carpeta:{CLAVE}", "mutar")
    assert bloqueo.value.status_code == 503


def test_alto02_ruta_relativa_fuera_de_la_raiz_no_mapea_al_caso(env, registro):
    """Confinamiento: una ruta relativa que ESCAPA de ``datos['raiz']`` no se
    mapea al recurso del caso (no puede bloquear por identidad ajena)."""
    escapada = "../FUERA/lote/img.png"
    _escribir_registro_durable(registro, [
        {"recurso": escapada, "operacion": "op", "detalle": "d"}])
    _reiniciar_y_cargar()
    assert backend._recurso_canonico(escapada) == escapada, (
        "ALTO-02: una ruta fuera de la raíz del lote se mapeó al caso")


# ---------------------------------------------------------------------------
# ALTO-03 — guard transversal de recuperación en endpoints mutantes
# ---------------------------------------------------------------------------

def test_alto03_evaluar_banco_externo_bloqueado_en_modo_recuperacion(
        env, registro, monkeypatch):
    """Repro del auditor: con ``_modo_recuperacion`` forzado,
    ``pruebas_externas.evaluar()`` llegaba a EJECUTARSE."""
    ejecutado: list = []
    monkeypatch.setattr(pruebas_externas, "evaluar",
                        lambda config: ejecutado.append(config))
    backend._modo_recuperacion = {"motivo": "prueba", "fecha": ""}
    with pytest.raises(HTTPException) as bloqueo:
        backend.evaluar_pruebas_externas()
    assert bloqueo.value.status_code == 503
    assert ejecutado == [], (
        "ALTO-03: el banco externo se recalculó durante MODO RECUPERACIÓN")


def test_alto03_toda_ruta_mutante_declara_politica_de_recuperacion():
    """Criterio P0-5: catálogo contractual de POST/PUT/PATCH/DELETE. Toda ruta
    mutante debe llevar el guard transversal o estar en la lista de exenciones
    DECLARADAS (flujo de recuperación y acciones de seguridad del pipeline)."""
    mutantes = [r for r in backend.app.routes if isinstance(r, APIRoute)
                and r.methods & {"POST", "PUT", "PATCH", "DELETE"}]
    assert len(mutantes) >= 40, "catálogo de endpoints mutantes vacío"
    rutas = {r.path for r in mutantes}
    for obligatoria in ("/api/externas/evaluar", "/api/revisiones",
                        "/api/alertas/atender", "/api/pipeline"):
        assert obligatoria in rutas
    for ruta in mutantes:
        declarada = any(ruta.path.startswith(prefijo) for prefijo in
                        backend._ENDPOINTS_SEGUROS_EN_RECUPERACION)
        lleva_guard = any(
            getattr(d.call, "__name__", "") == "_guard_recuperacion_transversal"
            for d in ruta.dependant.dependencies)
        if declarada:
            # Las exenciones son exactamente: resolver ambas rutas de
            # recuperación, pausar y cancelar. Nada más.
            assert ruta.path in (
                "/api/recuperacion/inconsistencias/{recurso:path}/resolver",
                "/api/recuperacion/modo-recuperacion/resolver",
                "/api/pipeline/pausar", "/api/pipeline/cancelar"), (
                f"exención NO declarada en el contrato: {ruta.path}")
        else:
            assert lleva_guard, (
                f"ALTO-03: {ruta.path} muta sin política de recuperación "
                "declarada")


def test_alto03_guard_transversal_bloquea_mutantes_y_permite_la_salida():
    """El guard bloquea cualquier mutante en modo recuperación; no toca GETs,
    permite el propio flujo de recuperación (la salida) y las dos acciones de
    seguridad (pausar/cancelar) para no dejar análisis desatendidos."""
    def peticion(metodo: str, ruta: str) -> Request:
        return Request({"type": "http", "scheme": "http",
                        "server": ("testserver", 80), "method": metodo,
                        "path": ruta, "headers": [], "query_string": b""})

    backend._modo_recuperacion = {"motivo": "prueba", "fecha": ""}
    try:
        with pytest.raises(HTTPException) as bloqueo:
            backend._guard_recuperacion_transversal(
                peticion("POST", "/api/revisiones"))
        assert bloqueo.value.status_code == 503
        with pytest.raises(HTTPException):
            backend._guard_recuperacion_transversal(
                peticion("DELETE", "/api/casos/x/campos/y"))
        # Lecturas y salidas declaradas: sin bloqueo.
        backend._guard_recuperacion_transversal(
            peticion("GET", "/api/revisiones"))
        backend._guard_recuperacion_transversal(peticion(
            "POST", "/api/recuperacion/inconsistencias/carpeta:x/resolver"))
        backend._guard_recuperacion_transversal(peticion(
            "POST", "/api/recuperacion/modo-recuperacion/resolver"))
        backend._guard_recuperacion_transversal(
            peticion("POST", "/api/pipeline/pausar"))
        backend._guard_recuperacion_transversal(
            peticion("POST", "/api/pipeline/cancelar"))
    finally:
        backend._modo_recuperacion = None


# ---------------------------------------------------------------------------
# ALTO-04 — /api/revisiones respeta el bloqueo del caso
# ---------------------------------------------------------------------------

def test_alto04_revision_carpeta_bloqueada_con_inconsistencia_activa(
        env, registro):
    """Repro del auditor: con inconsistencia activa para ``carpeta:<id>``,
    ``actualizar_revision()`` seguía ejecutándose."""
    backend._registrar_inconsistencia(f"carpeta:{CLAVE}", "corrección",
                                      "rollback fallido")
    with pytest.raises(HTTPException) as bloqueo:
        backend.actualizar_revision(backend.SolicitudRevision(
            tipo="carpeta", item_id=CLAVE, estado="casi_listo"))
    assert bloqueo.value.status_code == 503, (
        "ALTO-04: la revisión mutó un caso que el sistema considera "
        "inconsistente")


def test_alto04_revision_externa_bloqueada_con_inconsistencia_activa(
        env, registro):
    backend._registrar_inconsistencia("externa:EXT1", "corrección",
                                      "rollback fallido")
    with pytest.raises(HTTPException) as bloqueo:
        backend.actualizar_revision(backend.SolicitudRevision(
            tipo="externa", item_id="EXT1", estado="parcial"))
    assert bloqueo.value.status_code == 503


# ---------------------------------------------------------------------------
# MEDIO-05 — /api/alertas/atender respeta el bloqueo
# ---------------------------------------------------------------------------

def test_medio05_alertas_respetan_el_bloqueo_de_recuperacion(env, registro):
    backend._registrar_inconsistencia(f"carpeta:{CLAVE}", "corrección",
                                      "rollback fallido")
    with pytest.raises(HTTPException) as bloqueo:
        backend.atender_alerta(backend.SolicitudAlerta(
            tipo="carpeta", item_id=CLAVE, alerta_id="ALERTA12"))
    assert bloqueo.value.status_code == 503, (
        "MEDIO-05: una anomalía se marcó como atendida con el caso bloqueado")


# ---------------------------------------------------------------------------
# MEDIO-06 — el listado deduplica el mismo incidente
# ---------------------------------------------------------------------------

def test_medio06_listado_deduplica_el_mismo_incidente(env, registro):
    """Repro del auditor: el mismo incidente bajo ``carpeta:abc`` y su ruta
    heredada producía ``total = 2`` para UN incidente lógico."""
    backend._registrar_inconsistencia("carpeta:abc", "op", "detalle")
    entrada = backend._inconsistencias_activas["carpeta:abc"]
    backend._inconsistencias_activas["/legacy/abc/img.png"] = entrada
    estado = backend.listar_inconsistencias()
    assert estado["total"] == 1, (
        "MEDIO-06: el listado infla el total con aliases del mismo incidente")
    assert estado["inconsistencias"][0]["recurso"] == "carpeta:abc"
    assert set(estado["inconsistencias"][0]["claves"]) == {
        "carpeta:abc", "/legacy/abc/img.png"}


def test_medio06_resolucion_por_alias_sigue_funcionando(env, registro):
    """Regresión: la deduplicación del listado no rompe la resolución por
    identidad heredada (ALTO-02/R15.7)."""
    backend._registrar_inconsistencia("carpeta:abc", "op", "detalle")
    entrada = backend._inconsistencias_activas["carpeta:abc"]
    backend._inconsistencias_activas["/legacy/abc/img.png"] = entrada
    respuesta = backend.resolver_inconsistencia(
        "/legacy/abc/img.png",
        backend.SolicitudResolucionInconsistencia(usuario="t",
                                                  confirmo_verificacion=True))
    assert respuesta["resuelta"] is True
    assert respuesta["restantes"] == 0
    assert backend._inconsistencias_activas == {}


# ---------------------------------------------------------------------------
# MEDIO-07 / MEDIO-08 — soak ligado a ejecucion_id y reinicio por iteración
# ---------------------------------------------------------------------------

class _Estado:
    def __init__(self, patch_build="15.10.1-r15.8", inconsistencias=0,
                 modo_pipeline="normal", fallar_post_en=0):
        self.patch_build = patch_build
        self.inconsistencias = inconsistencias
        self.modo_pipeline = modo_pipeline  # normal | terminal_propio | terminal_ajeno
        self.fallar_post_en = fallar_post_en
        self.post = 0
        self.sondesos = 0


def _servidor(estado: _Estado):
    class Manejador(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silencio
            pass

        def _responder(self, payload: dict, codigo: int = 200):
            cuerpo = json.dumps(payload).encode("utf-8")
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        def do_POST(self):
            if self.path == "/api/pipeline":
                estado.post += 1
                if estado.fallar_post_en and estado.post >= estado.fallar_post_en:
                    self._responder({"detail": "hay algo en curso"}, 409)
                    return
                self._responder({"aceptado": True,
                                 "ejecucion_id": f"EXEC{estado.post}"})
                return
            self._responder({"detail": "no encontrado"}, 404)

        def do_GET(self):
            estado.sondesos += 1
            if self.path == "/api/estado":
                self._responder({"patch_build": estado.patch_build})
                return
            if self.path == "/api/pipeline/estado":
                if estado.modo_pipeline == "terminal_propio":
                    self._responder({"estado": "completado",
                                     "ejecucion_id": f"EXEC{estado.post}",
                                     "resumen": {}})
                    return
                if estado.modo_pipeline == "terminal_ajeno":
                    self._responder({"estado": "completado",
                                     "ejecucion_id": "VIEJA",
                                     "resumen": {}})
                    return
                if estado.sondesos % 2 == 1:
                    self._responder({"estado": "procesando",
                                     "ejecucion_id": f"EXEC{estado.post}",
                                     "resumen": {}})
                else:
                    self._responder({"estado": "completado",
                                     "ejecucion_id": f"EXEC{estado.post}",
                                     "resumen": {}})
                return
            if self.path == "/api/recuperacion/inconsistencias":
                self._responder({"modo_recuperacion": None,
                                 "total": estado.inconsistencias,
                                 "inconsistencias": []})
                return
            self._responder({"detail": "no encontrado"}, 404)

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    return servidor, hilo


def _ejecutar(estado: _Estado, iteraciones: int = 2, **kwargs):
    from validacion_campo import soak_r157
    servidor, hilo = _servidor(estado)
    base = f"http://127.0.0.1:{servidor.server_address[1]}"
    try:
        return soak_r157.ejecutar_soak(
            base=base, lote="/lote", iteraciones=iteraciones, perfil="alto",
            intervalo=0.01, arranque_max=kwargs.pop("arranque_max", 5),
            esperar_max=10, esperado="15.10.1-r15.8", validacion=None,
            cache_ocr=None, log=lambda *_a: None, **kwargs)
    finally:
        servidor.shutdown()
        hilo.join(timeout=5)
        servidor.server_close()


def test_medio07_soak_acepta_terminal_antes_del_primer_sondeo():
    """Repro del auditor: el pipeline termina antes del primer poll; el soak
    debe aceptar el terminal de ESA MISMA ejecución, no informar «no arrancó»."""
    reporte = _ejecutar(_Estado(modo_pipeline="terminal_propio"),
                        iteraciones=2, arranque_max=1.0)
    assert reporte["ok"] is True, reporte["fallos"]
    assert len(reporte["iteraciones"]) == 2
    for iteracion in reporte["iteraciones"]:
        assert iteracion["estado_final"] == "completado"
        assert iteracion["fallos"] == []


def test_medio07_soak_no_confunde_terminal_de_otra_ejecucion():
    """Un terminal de OTRA ejecución (más antigua) no se acepta como nuestro
    fin: el soak sigue esperando la admisión y falla por ventana, no por
    «terminal ajeno aceptado»."""
    reporte = _ejecutar(_Estado(modo_pipeline="terminal_ajeno"),
                        iteraciones=1, arranque_max=0.3)
    assert reporte["ok"] is False
    assert any("no arrancó" in fallo for fallo in reporte["fallos"])


def test_medio08_soak_no_hereda_ejecucion_id_entre_iteraciones():
    """Repro del auditor: iteración 1 = EXEC1; el lanzamiento de la iteración
    2 falla; el reporte de la iteración 2 debe mostrar ``ejecucion_id: None``
    (estado reiniciado por ciclo), nunca EXEC1."""
    reporte = _ejecutar(_Estado(fallar_post_en=2), iteraciones=2)
    assert reporte["ok"] is False
    assert len(reporte["iteraciones"]) == 2
    assert reporte["iteraciones"][0]["ejecucion_id"] == "EXEC1"
    assert reporte["iteraciones"][1]["ejecucion_id"] is None, (
        "MEDIO-08: el soak atribuye el fallo a la ejecución de la iteración "
        "anterior")
    assert any("409" in fallo or "lanzar" in fallo.lower()
               for fallo in reporte["iteraciones"][1]["fallos"])


def test_soak_identidad_por_defecto_version_aware():
    """R15.9 (SUPERSEDE): la identidad por defecto del soak sigue la fuente
    única (VERSION.txt) y los alias históricos apuntan a la identidad vigente;
    un árbol con otro build se detecta (no se relaja el criterio)."""
    from validacion_campo import soak_r157
    build = (Path(__file__).resolve().parents[1]
             / "VERSION.txt").read_text(encoding="utf-8").strip()
    assert soak_r157.PATCH_BUILD_R159 == build
    assert soak_r157.PATCH_BUILD_R158 == build
    assert soak_r157.PATCH_BUILD_R157 == build
    reporte = _ejecutar(_Estado(patch_build="15.10.1-r15.7"), iteraciones=1)
    assert reporte["ok"] is False
    assert any("patch_build" in fallo for fallo in reporte["fallos"])
