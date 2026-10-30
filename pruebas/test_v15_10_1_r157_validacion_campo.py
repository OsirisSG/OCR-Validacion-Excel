"""R15.7 · P2 — Herramental de validación de campo (criterios §9-6…§9-8).

Cubre las dos herramientas nuevas:

* ``validacion_campo/validar_tmax_semaforo.py`` — compara Tmax publicado contra
  ground truth humano y clasifica ambos con el MISMO motor de reglas del
  dashboard (semáforo verde ≤ 6 ms / amarillo ≤ 7 ms por defecto).
* ``validacion_campo/soak_r157.py`` — soak de análisis con verificación de
  invariantes R15 después de cada iteración (patch_build, registro de
  recuperación vacío, revisión monótona, temporales huérfanos).

El soak se prueba contra un servidor HTTP de prueba (stdlib) que emula
``/api/pipeline``, ``/api/pipeline/estado``, ``/api/estado`` y
``/api/recuperacion/inconsistencias``: así queda demostrado, en hermético, que
la herramienta (a) completa el soak y (b) DETECTA un bloqueo sobreviviente.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from validacion_campo import soak_r157, validar_tmax_semaforo


# ---------------------------------------------------------------------------
# validar_tmax_semaforo
# ---------------------------------------------------------------------------

def _fila(case_key: str, nombre: str, canonico: dict) -> dict:
    return {"case_key": case_key, "nombre": nombre, "ruta": f"/lote/{nombre}",
            "resultado_caso_canonico": {"apertura": canonico}}


def _documento() -> dict:
    return {"revision_documento": 3, "resultados": [
        _fila("PROY|1ST|1001", "1001",
              {"estado": "VERIFICADO_HUMANO", "tiempo_ms": 5.8}),
        _fila("PROY|1ST|A1", "A1_variante3",
              {"estado": "PROPUESTA", "tiempo_propuesto_ms": 6.4}),
        _fila("PROY|1ST|C2", "C2_variante1", {"estado": "NO_OBSERVADO"}),
    ]}


def test_validador_tmax_clasifica_y_reporta(tmp_path):
    ground_truth = tmp_path / "gt.csv"
    ground_truth.write_text(
        "caso,tiempo_ms_humano,nota\n"
        "1001,5.9,lectura cuadro a cuadro\n"
        "A1_variante3,6.4,\n"
        "C2_variante1,6.0,confirmado por 2 personas\n"
        "CASO_INEXISTENTE,7.5,\n", encoding="utf-8")

    reporte = validar_tmax_semaforo.validar(
        _documento(), validar_tmax_semaforo._leer_ground_truth(ground_truth),
        tolerancia_ms=0.5)

    resumen = reporte["resumen"]
    assert resumen["casos"] == 4
    assert resumen["encontrados"] == 3
    assert resumen["sin_caso"] == 1
    assert resumen["con_valor_detectado"] == 2      # C2 no tiene valor publicado
    assert resumen["sin_valor"] == 1
    # 5.8 vs 5.9 ⇒ Δ 0.1 (dentro de 0.5 ms); 6.4 vs 6.4 ⇒ Δ 0
    assert resumen["mae_ms"] == pytest.approx(0.05, abs=1e-6)
    assert resumen["dentro_tolerancia"] == 2
    # Semáforos: 1001 verde/verde, A1 amarillo/amarillo, C2 gris/verde
    assert resumen["acuerdo_semaforo"] == 2
    assert reporte["discrepancias"] == ["C2_variante1"]
    assert reporte["criterios_limites"]["verde_max"] == 6.0
    assert reporte["criterios_limites"]["amarillo_max"] == 7.0
    assert reporte["criterio_apertura"]["verde"] == "<= 6"
    assert reporte["criterio_apertura"]["amarillo"] == "6-7"

    # El caso sin valor publicado queda marcado, nunca inventado.
    c2 = next(c for c in reporte["casos"] if c["caso"] == "C2_variante1")
    assert c2["estado_deteccion"] == "sin_tiempo"
    assert c2["tiempo_ms_detectado"] is None
    assert c2["semaforo_detectado"] == "gris"


def test_validador_tmax_acepta_legacy_y_empareja_por_id_corto(tmp_path):
    documento = {"resultados": [
        {"case_key": "PROY|2ST|L1", "nombre": "L1", "ruta": "/lote/L1",
         "opening_time_ms": 7.4},
    ]}
    id_corto = validar_tmax_semaforo._id_corto(documento["resultados"][0])
    ground_truth = tmp_path / "gt.csv"
    ground_truth.write_text(
        f"caso,tiempo_ms_humano\n{id_corto},7.3\n", encoding="utf-8")
    reporte = validar_tmax_semaforo.validar(
        documento, validar_tmax_semaforo._leer_ground_truth(ground_truth),
        tolerancia_ms=0.2)
    caso = reporte["casos"][0]
    assert caso["estado_deteccion"] == "legacy"
    assert caso["tiempo_ms_detectado"] == 7.4
    assert caso["semaforo_humano"] == "rojo"       # 7.3 > 7 ms
    assert caso["semaforo_detectado"] == "rojo"
    assert caso["acuerdo_semaforo"] is True


def test_validador_tmax_ground_truth_invalido(tmp_path):
    ruta = tmp_path / "gt.csv"
    ruta.write_text("caso,tiempo_ms_humano\n1001,cero\n", encoding="utf-8")
    with pytest.raises(ValueError):
        validar_tmax_semaforo._leer_ground_truth(ruta)
    vacio = tmp_path / "vacio.csv"
    vacio.write_text("caso,tiempo_ms_humano\n", encoding="utf-8")
    with pytest.raises(ValueError):
        validar_tmax_semaforo._leer_ground_truth(vacio)


# ---------------------------------------------------------------------------
# soak_r157 contra un servidor de prueba
# ---------------------------------------------------------------------------

class _Estado:
    def __init__(self, inconsistencias: int = 0, patch_build: str = "15.10.1-r15.7"):
        self.inconsistencias = inconsistencias
        self.patch_build = patch_build
        self.sondeos = 0
        self.analisis_lanzados = 0


def _servidor(estado: _Estado, puerto: int = 0) -> tuple:
    class Manejador(BaseHTTPRequestHandler):
        def log_message(self, *_a):  # silencioso
            return

        def _responder(self, payload: dict, code: int = 200) -> None:
            cuerpo = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        def do_POST(self):  # noqa: N802 — API de BaseHTTPRequestHandler
            largo = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(largo)
            if self.path == "/api/pipeline":
                estado.analisis_lanzados += 1
                estado.sondeos = 0
                self._responder({"aceptado": True, "ejecucion_id": "e-1"})
                return
            self._responder({"detail": "no encontrado"}, 404)

        def do_GET(self):  # noqa: N802 — API de BaseHTTPRequestHandler
            if self.path == "/api/estado":
                self._responder({"hay_datos": True, "total": 3,
                                 "patch_build": estado.patch_build})
                return
            if self.path == "/api/pipeline/estado":
                # R15.9: el stub alinea su contrato con la API real, que
                # expone ``ejecucion_id`` en /api/pipeline/estado (el soak
                # con identidad estricta lo exige para aceptar el fin).
                estado.sondeos += 1
                if estado.sondeos < 2:
                    self._responder({"estado": "procesando", "porcentaje": 50,
                                     "ejecucion_id": "e-1"})
                else:
                    self._responder({"estado": "inactivo", "ejecucion_id": "e-1",
                                     "resumen": {"casos": 3},
                                     "metricas_recursos": {"perfil": "alto"}})
                return
            if self.path == "/api/recuperacion/inconsistencias":
                self._responder({
                    "modo_recuperacion": None, "total": estado.inconsistencias,
                    "inconsistencias": [{"recurso": "carpeta:x"}] * estado.inconsistencias})
                return
            self._responder({"detail": "no encontrado"}, 404)

    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    return servidor, hilo


def _ejecutar(estado, **kwargs):
    servidor, hilo = _servidor(estado)
    base = f"http://127.0.0.1:{servidor.server_address[1]}"
    try:
        return soak_r157.ejecutar_soak(
            base=base, lote="/lote", iteraciones=2, perfil="alto",
            intervalo=0.01, arranque_max=5, esperar_max=10,
            esperado="15.10.1-r15.7", validacion=None, cache_ocr=None,
            log=lambda *_a: None, **kwargs)
    finally:
        servidor.shutdown()
        hilo.join(timeout=5)
        servidor.server_close()


def test_soak_completa_iteraciones_sin_fallos():
    estado = _Estado()
    reporte = _ejecutar(estado)
    assert reporte["ok"] is True, reporte["fallos"]
    assert len(reporte["iteraciones"]) == 2
    assert estado.analisis_lanzados == 2
    for iteracion in reporte["iteraciones"]:
        assert iteracion["estado_final"] == "inactivo"
        assert iteracion["invariantes"]["patch_build"] == "15.10.1-r15.7"
        assert iteracion["invariantes"]["recuperacion"]["total"] == 0
        assert iteracion["fallos"] == []


def test_soak_detecta_inconsistencia_sobreviviente():
    estado = _Estado(inconsistencias=1)
    reporte = _ejecutar(estado)
    assert reporte["ok"] is False
    assert len(reporte["iteraciones"]) == 1, (
        "el soak debe detenerse en el primer fallo para no contaminar evidencia")
    fallos = " ".join(reporte["fallos"])
    assert "inconsistencia" in fallos.lower()
    assert "MODO RECUPERACIÓN" not in fallos  # modo limpio, sólo el registro


def test_soak_detecta_build_equivocado():
    estado = _Estado(patch_build="15.10.1-r15.6")
    reporte = _ejecutar(estado)
    assert reporte["ok"] is False
    assert any("patch_build" in fallo for fallo in reporte["fallos"])


def test_soak_simular_no_lanza_analisis():
    estado = _Estado()
    servidor, hilo = _servidor(estado)
    base = f"http://127.0.0.1:{servidor.server_address[1]}"
    try:
        reporte = soak_r157.ejecutar_soak(
            base=base, lote="", iteraciones=1, perfil="alto", intervalo=0.01,
            arranque_max=5, esperar_max=10, esperado="15.10.1-r15.7",
            validacion=None, cache_ocr=None, simular=True, log=lambda *_a: None)
    finally:
        servidor.shutdown()
        hilo.join(timeout=5)
        servidor.server_close()
    assert reporte["ok"] is True
    assert estado.analisis_lanzados == 0
    assert reporte["iteraciones"][0]["simulada"] is True


def test_soak_revisa_temporales_huerfanos_y_revision(tmp_path):
    cache = tmp_path / ".cache_ocr"
    cache.mkdir()
    (cache / "estado_inconsistente.json.tmp").write_text("{}", encoding="utf-8")
    validacion = tmp_path / "validacion_resultados.json"
    validacion.write_text(json.dumps({"revision_documento": 9}), encoding="utf-8")
    estado = _Estado()
    servidor, hilo = _servidor(estado)
    base = f"http://127.0.0.1:{servidor.server_address[1]}"
    try:
        reporte = soak_r157.ejecutar_soak(
            base=base, lote="/lote", iteraciones=1, perfil="alto", intervalo=0.01,
            arranque_max=5, esperar_max=10, esperado="15.10.1-r15.7",
            validacion=validacion, cache_ocr=cache, log=lambda *_a: None)
    finally:
        servidor.shutdown()
        hilo.join(timeout=5)
        servidor.server_close()
    assert reporte["ok"] is False
    fallos = " ".join(reporte["fallos"])
    assert "temporales huérfanos" in fallos
    assert reporte["iteraciones"][0]["invariantes"]["revision"] == 9
