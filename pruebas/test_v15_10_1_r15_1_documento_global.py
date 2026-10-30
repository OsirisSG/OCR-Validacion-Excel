"""R15.1 · Consistencia global del documento (auditoría independiente R15).

CRÍTICO-01: varios endpoints legacy siguen haciendo
``_cargar_datos() → modificar snapshot → _guardar_json_atomico(RUTA_VALIDACION)``
sin lock, sin CAS y sin ``_commit_documento``. Una escritura lenta basada en un
snapshot viejo PIERDE los commits concurrentes y hace retroceder
``revision_documento`` (reproducción del auditor: revisión 6 → 5 con
``VIDEO_NUEVO`` perdido).

ALTO-02: ``expected_revision=None`` desactiva el CAS en endpoints R15; una
pestaña vieja puede mutar un documento ya versionado sin control.

Corrección exigida: una única primitiva ``mutar_documento()`` (lock → lectura
fresca de disco → CAS → patch → revisión monotónica → escritura verificada →
invalidación de caché) usada por TODA ruta que modifique el documento, y CAS
estricto en los endpoints R15 cuando el documento ya está versionado.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

import dashboard.backend.app as backend

CASE_KEY = "PROY|1ST|HT|NOM|1001"
CLAVE = hashlib.sha256(CASE_KEY.encode("utf-8")).hexdigest()[:16]


class _GestorStub:
    """Gestor de aprendizaje mínimo; ``hook_estado_revision`` permite pausar."""
    hook_estado_revision = None
    llamadas: list = []

    def __init__(self, config=None):
        pass

    def estado_revision(self, ambito, item_id, inicial):
        if type(self).hook_estado_revision is not None:
            type(self).hook_estado_revision()
        return {"estado": "pendiente", "inicial": inicial}

    def actualizar_revision(self, ambito, item_id, estado):
        type(self).llamadas.append((ambito, item_id, estado))

    def registrar_imagen_sin_datos(self, ruta, prueba_id, motivo, usuario):
        return {"estado": "revisada_sin_datos", "motivo": motivo,
                "usuario": usuario, "guardado": True}

    # R15.4 (HIGH-01): primitivas de compensación multi-almacén. El stub no
    # tiene efectos SQLite reales que compensar: snapshot nulo y restauración
    # trivialmente exitosa (la ruta bajo prueba aquí es la serialización del
    # documento, no los almacenes externos).
    def imagen_sin_datos(self, ruta):
        return None

    def snapshot_evidencias_imagen(self, ruta_imagen, caso_id=None):
        return None

    def restaurar_evidencias_imagen(self, snap):
        return True

    # R15.6 (Causa A): el helper común captura/restaura el estado de revisión;
    # sin fila previa la restauración es un DELETE sobre sqlite. El stub usa
    # una base efímera en memoria: sin efectos reales y trivialmente exitosa
    # (la ruta bajo prueba aquí sigue siendo la serialización del documento).
    def _conectar(self):
        import sqlite3
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE IF NOT EXISTS revisiones "
                    "(tipo TEXT, item_id TEXT)")
        return con

    def incorporar_uniones_guardadas(self, *a, **kw):
        return None

    def listar_anotaciones(self, *a, **kw):
        return []

    def listar_correcciones_texto(self, *a, **kw):
        return []

    def listar_rotaciones(self, *a, **kw):
        return []

    def listar_alertas_atendidas(self, *a, **kw):
        return set()


def _documento(lote: Path, video: Path, imagen: Path) -> dict:
    return {
        "raiz": str(lote),
        "resultados": [{
            "nombre": "CASO1", "case_key": CASE_KEY,
            "ruta": str(lote / "CASO1"), "tipo_st": "1ST",
            "perfil": "empresarial",
            "comparacion": {"resultado": "coincidencia_total"},
            "confianza_ocr_pct": 99.0,
            "campos": {"test_number": {"valor": "1001", "estado": "confirmado"}},
            "imagenes": [{"id": "IMG1", "ruta": str(imagen), "resultado_ocr": None}],
            "trazabilidad": [],
            "videos": [{
                "id": "V1", "nombre": "n_DETAIL.AVI", "ruta": str(video),
                "ruta_relativa": "CASO1/n_DETAIL.AVI", "carpeta_video": "CASO1",
                "marca_video": "old_video",
            }],
        }],
    }


@pytest.fixture
def entorno(monkeypatch, tmp_path):
    lote = tmp_path / "Lote"
    (lote / "CASO1").mkdir(parents=True)
    video = lote / "CASO1" / "n_DETAIL.AVI"
    video.write_bytes(b"RIFFdummy")
    imagen = lote / "CASO1" / "img_0001.png"
    imagen.write_bytes(b"PNGdummy")
    validacion = tmp_path / "validacion_resultados.json"
    validacion.write_text(json.dumps(_documento(lote, video, imagen)),
                          encoding="utf-8")

    _GestorStub.hook_estado_revision = None
    _GestorStub.llamadas = []

    import aprendizaje_video_airbag
    import maximos_video
    import video_airbag

    monkeypatch.setattr(backend, "RUTA_VALIDACION", validacion)
    monkeypatch.setattr(backend, "RUTA_ESTRUCTURA", tmp_path / "no_existe.json")
    monkeypatch.setattr(backend, "_cache", {"mtime": None, "datos": None})
    monkeypatch.setattr(backend, "_pipeline_estado",
                        copy.deepcopy(backend._pipeline_estado))
    monkeypatch.setattr(backend, "_pipeline_hilo", None)
    monkeypatch.setattr(backend, "_pipeline_reserva", None, raising=False)
    monkeypatch.setattr(backend, "_video_reanalisis_hilo", None)
    monkeypatch.setattr(backend, "CONFIG", {})
    monkeypatch.setattr(backend, "GestorAprendizaje", _GestorStub)
    monkeypatch.setattr(backend, "_regenerar_excel", lambda resultado: None)
    monkeypatch.setattr(backend, "_resolver_raiz_datos", lambda datos: lote)
    monkeypatch.setattr(backend, "_resolver_imagen",
                        lambda ruta, datos, raiz: Path(ruta))
    monkeypatch.setattr(backend, "_reubicar_ruta",
                        lambda ruta, datos, raiz: Path(ruta))
    monkeypatch.setattr(backend, "_aplicar_consenso_video_a_fila",
                        lambda fila, consenso: None)
    monkeypatch.setattr(backend, "_evento_censurado_video_api", lambda item: False)
    monkeypatch.setattr(video_airbag, "normalizar_videos_caso",
                        lambda videos, config: None)
    monkeypatch.setattr(video_airbag, "consenso_videos",
                        lambda videos, config: {"tiempo_ms": None, "soporte": 0,
                                                "estado": "pendiente"})
    monkeypatch.setattr(video_airbag, "guardar_revision_video",
                        lambda ruta, **kw: {"estado": kw.get("estado"),
                                            "guardado": True, **kw})
    monkeypatch.setattr(maximos_video, "incorporar_maximos", lambda fila: None)
    monkeypatch.setattr(aprendizaje_video_airbag, "guardar_zona_aprendida",
                        lambda ruta, bbox, **kw: {"zona": "stub", "bbox": bbox})
    monkeypatch.setattr(aprendizaje_video_airbag, "resumen_aprendizajes",
                        lambda *a, **kw: {})
    monkeypatch.setattr(aprendizaje_video_airbag, "revertir_zona_aprendida",
                        lambda ruta, **kw: {"zona": "revertida"})
    monkeypatch.setattr(aprendizaje_video_airbag, "perfil_zona_aprendida",
                        lambda ruta: None)
    monkeypatch.setattr(aprendizaje_video_airbag, "historial_zona_aprendida",
                        lambda ruta: [])
    monkeypatch.setattr(aprendizaje_video_airbag, "restaurar_perfil_zona",
                        lambda ruta, perfil: None)

    yield {"lote": lote, "video": video, "imagen": imagen,
           "validacion": validacion, "tmp": tmp_path}


def _leer(validacion: Path) -> dict:
    return json.loads(validacion.read_text(encoding="utf-8"))


def _commit_video(validacion: Path, marca: str) -> int:
    """Commit de video por la vía R15 (lock + fresco + revisión).

    R15.2: el lock es el de la autoridad compartida (``_lock_documento``).
    """
    with backend._lock_documento():
        frescos = backend._leer_documento_disco()
        frescos["resultados"][0]["videos"][0]["marca_video"] = marca
        return backend._commit_documento(frescos)


def _solicitud_revision(**kw) -> backend.SolicitudRevisionVideo:
    base = {"prueba_id": CLAVE, "video_id": "V1", "estado": "pendiente",
            "usuario": "tester"}
    base.update(kw)
    return backend.SolicitudRevisionVideo(**base)


# ---------------------------------------------------------------------------
# CRÍTICO-01 — reproducción de la pérdida de actualización
# ---------------------------------------------------------------------------

def test_escritura_legacy_lenta_no_pierde_commit_de_video(entorno):
    """Reproducción del auditor: corrección manual lenta + commit de video.

    La escritura legacy (campos manuales) toma un snapshot, se pausa antes de
    persistir, y mientras tanto un commit R15 de video avanza la revisión.

    R15.2 (ALTO-04, volteo documentado): con CAS estricto, al reanudar la
    escritura legacy recibe 409 (rechazo explícito) en vez de fusionar: el
    commit de video sobrevive intacto y la revisión no avanza con la
    escritura rechazada. «0 pérdida o rechazo explícito previo» — criterio 2.
    """
    llego = threading.Event()
    liberar = threading.Event()

    def hook():
        if not llego.is_set():
            llego.set()
            assert liberar.wait(10)

    _GestorStub.hook_estado_revision = hook
    resultado: dict = {}

    def llamar():
        try:
            resultado["resp"] = backend.corregir_campo_caso(
                CLAVE, "pab_comments",
                backend.SolicitudCampoManual(valor="CORRECCION_X", usuario="tester"))
        except BaseException as exc:  # noqa: BLE001 — se inspecciona abajo
            resultado["exc"] = exc

    hilo = threading.Thread(target=llamar)
    hilo.start()
    try:
        assert llego.wait(10), "el endpoint no llegó al punto de pausa"
        rev_video = _commit_video(entorno["validacion"], "VIDEO_NUEVO")
    finally:
        liberar.set()
    hilo.join(15)
    # R15.2: la pantalla que cargó rev 0 recibe 409 al reanudar (documento ya
    # versionado por el commit de video + expected_revision ausente).
    exc = resultado.get("exc")
    assert isinstance(exc, HTTPException) and exc.status_code == 409, resultado

    disco = _leer(entorno["validacion"])
    fila = disco["resultados"][0]
    # 1) El commit de video NO se pierde.
    assert fila["videos"][0]["marca_video"] == "VIDEO_NUEVO", (
        "la escritura legacy reescribió el snapshot viejo y perdió el video")
    # 2) La escritura rechazada NO dejó medio commit en el documento.
    assert "pab_comments" not in fila["campos"]
    # 3) La revisión quedó exactamente en el commit de video (sin inflar).
    assert int(disco.get("revision_documento") or 0) == rev_video


def test_sin_datos_concurrente_no_pierde_commit_de_video(entorno):
    """Misma garantía para /api/imagenes/sin-datos (otro writer legacy).

    R15.3 (ALTO-02, volteo documentado): en R15.2 esta prueba pausaba el
    writer legacy ENTRE el pre-chequeo CAS y el commit mientras un commit de
    video versionaba el documento ⇒ 409 explícito. Desde R15.3 el efecto
    durable y el CAS comparten la MISMA región de lock que el commit de video,
    así que esa interleaving es imposible por diseño (pausar dentro del lock
    sólo bloquearía al otro writer). La garantía «0 pérdida O rechazo
    explícito previo» se verifica con el orden que sí es alcanzable: el video
    versiona primero y sin-datos (sin expected_revision) recibe 409 ANTES de
    cualquier efecto.
    """
    registros: list = []
    original = _GestorStub.registrar_imagen_sin_datos

    def registrar_espia(self, ruta, prueba_id, motivo, usuario):
        registros.append((prueba_id, motivo))
        return original(self, ruta, prueba_id, motivo, usuario)

    _GestorStub.registrar_imagen_sin_datos = registrar_espia
    try:
        rev_video = _commit_video(entorno["validacion"], "VIDEO_NUEVO")
        with pytest.raises(HTTPException) as rechazo:
            backend.marcar_imagen_sin_datos(backend.SolicitudImagenSinDatos(
                tipo="carpeta", prueba_id=CLAVE, imagen_id="IMG1",
                motivo="sin datos visibles", usuario="tester"))
    finally:
        _GestorStub.registrar_imagen_sin_datos = original

    assert rechazo.value.status_code == 409
    assert registros == [], (
        "R15.3 (ALTO-02): un 409 no debe dejar efectos persistentes")

    disco = _leer(entorno["validacion"])
    fila = disco["resultados"][0]
    assert fila["videos"][0]["marca_video"] == "VIDEO_NUEVO"
    assert fila["imagenes"][0].get("estado_imagen") != "revisada_sin_datos", (
        "una escritura rechazada por CAS no debe dejar medio commit")
    assert int(disco.get("revision_documento") or 0) == rev_video


def test_sin_datos_y_video_serializados_cero_perdida(entorno):
    """R15.3: el orden complementario — sin-datos commitea primero (documento
    aún sin versionar) y el commit de video posterior no pierde la marca:
    ambos cambios sobreviven y la revisión es monotónica."""
    respuesta = backend.marcar_imagen_sin_datos(backend.SolicitudImagenSinDatos(
        tipo="carpeta", prueba_id=CLAVE, imagen_id="IMG1",
        motivo="sin datos visibles", usuario="tester"))
    rev_marca = int(respuesta["revision_documento"])
    rev_video = _commit_video(entorno["validacion"], "VIDEO_NUEVO")

    disco = _leer(entorno["validacion"])
    fila = disco["resultados"][0]
    assert fila["imagenes"][0].get("estado_imagen") == "revisada_sin_datos"
    assert fila["videos"][0]["marca_video"] == "VIDEO_NUEVO"
    assert rev_video == rev_marca + 1
    assert int(disco.get("revision_documento") or 0) == rev_video


def test_consolidar_fusiona_documento_fresco_no_snapshot_viejo(entorno, monkeypatch):
    """``/api/resultados/consolidar`` consolida sobre el documento FRESCO.

    Con la primitiva ``mutar_documento`` las escrituras se serializan bajo
    lock, así que en vez de pausar dentro del lock (que bloquearía al commit
    concurrente por diseño) se reproduce la pérdida real del auditor: una
    caché «válida» pero vieja (mtime coincide, datos anteriores al commit
    ``VIDEO_NUEVO``). El código legacy consolidaba ``_cargar_datos()`` y
    reescribía el documento completo, perdiendo ``VIDEO_NUEVO``; R15.1 lee
    el documento fresco de disco dentro del lock y lo preserva.
    """
    import utilidades.consolidacion as uc

    externa = entorno["tmp"] / "ejecucion_2st.json"
    externa.write_text(json.dumps({"resultados": []}), encoding="utf-8")

    llamado = threading.Event()

    def consolidar_espia(documentos):
        llamado.set()
        base = documentos[0]
        return {"resultados": base.get("resultados", []),
                "tipos_st": base.get("tipos_st", [])}

    monkeypatch.setattr(uc, "consolidar_documentos", consolidar_espia)

    snapshot_viejo = copy.deepcopy(backend._cargar_datos())  # rev N, sin VIDEO_NUEVO
    rev_video = _commit_video(entorno["validacion"], "VIDEO_NUEVO")  # disco rev N+1
    # Pestaña con caché vieja PERO VÁLIDA: mtime del archivo actual + datos de
    # antes del commit. ``_cargar_datos()`` devolvería el snapshot viejo.
    backend._cache.update({"datos": snapshot_viejo,
                           "mtime": entorno["validacion"].stat().st_mtime})

    # R15.2 (ALTO-04): consolidación es mutación humana ⇒ CAS estricto; la
    # pantalla envía la revisión vigente leída del disco (si enviara la del
    # snapshot viejo recibiría 409 «recarga antes de guardar»).
    backend.consolidar_resultados(backend.SolicitudConsolidacion(
        archivos=[str(externa)], regenerar_excel=False,
        expected_revision=rev_video))
    assert llamado.is_set()

    disco = _leer(entorno["validacion"])
    assert disco["resultados"][0]["videos"][0]["marca_video"] == "VIDEO_NUEVO"
    assert int(disco.get("revision_documento") or 0) >= rev_video + 1

def test_mutaciones_heterogeneas_concurrentes_sin_perdidas(entorno):
    """3 mutaciones concurrentes (campo + imagen + video) → 0 pérdidas.

    Versión reducida de la prueba de estrés del plan del auditor
    (2/5/10 mutaciones heterogéneas): todas las modificaciones sobreviven y
    la revisión final es inicial + número de commits.

    R15.2 (ALTO-04, volteo documentado): las mutaciones humanas usan CAS
    estricto; la UI correcta lee la revisión vigente, la envía y, ante 409,
    recarga y reintenta. Eso se simula aquí con ``_con_reintento``.
    """
    barrera = threading.Barrier(3, timeout=15)
    resultados: dict = {}

    def _con_reintento(fn):
        for _ in range(10):
            rev = int(_leer(entorno["validacion"]).get("revision_documento") or 0)
            try:
                return fn(rev)
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
                time.sleep(0.01)
        raise AssertionError("demasiados conflictos 409 sin resolución")

    def campo():
        barrera.wait()
        resultados["campo"] = _con_reintento(lambda rev: backend.corregir_campo_caso(
            CLAVE, "pab_comments",
            backend.SolicitudCampoManual(valor="X1", usuario="t1",
                                         expected_revision=rev)))

    def imagen():
        barrera.wait()
        resultados["imagen"] = _con_reintento(lambda rev: backend.marcar_imagen_sin_datos(
            backend.SolicitudImagenSinDatos(
                tipo="carpeta", prueba_id=CLAVE, imagen_id="IMG1",
                motivo="m", usuario="t2", expected_revision=rev)))

    def video():
        barrera.wait()
        resultados["video_rev"] = _commit_video(entorno["validacion"], "VIDEO_NUEVO")

    hilos = [threading.Thread(target=campo), threading.Thread(target=imagen),
             threading.Thread(target=video)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(20)
    assert len(resultados) == 3, f"faltó alguna mutación: {sorted(resultados)}"

    disco = _leer(entorno["validacion"])
    fila = disco["resultados"][0]
    assert fila["videos"][0]["marca_video"] == "VIDEO_NUEVO"
    assert fila["imagenes"][0]["estado_imagen"] == "revisada_sin_datos"
    assert fila["campos"]["pab_comments"]["valor"] == "X1"
    # 3 commits (inicial sin versionar): revisión final exactamente 3.
    assert int(disco.get("revision_documento") or 0) == 3


# ---------------------------------------------------------------------------
# ALTO-02 — CAS estricto en endpoints R15 con documento versionado
# ---------------------------------------------------------------------------

def test_endpoint_r15_sin_expected_revision_con_documento_versionado_409(entorno):
    """Pestaña vieja (R14) no puede bypasear el CAS con expected_revision=None."""
    rev = _commit_video(entorno["validacion"], "old_video")  # documento versionado
    with pytest.raises(HTTPException) as exc:
        backend.revisar_video(_solicitud_revision())
    assert exc.value.status_code == 409
    assert "recarga" in str(exc.value.detail).lower()
    # Sin efectos laterales: el documento no cambia.
    disco = _leer(entorno["validacion"])
    assert int(disco["revision_documento"]) == rev
    assert disco["resultados"][0]["videos"][0].get("revision_manual") is None


def test_endpoint_r15_con_expected_revision_correcta_sigue_funcionando(entorno):
    rev = _commit_video(entorno["validacion"], "old_video")
    resp = backend.revisar_video(_solicitud_revision(expected_revision=rev))
    assert resp["revision_documento"] == rev + 1
    disco = _leer(entorno["validacion"])
    assert disco["resultados"][0]["videos"][0]["revision_manual"]["estado"] == "pendiente"


def test_documento_sin_versionar_acepta_primera_mutacion_sin_cas(entorno):
    """Compatibilidad: la primera mutación de un documento legacy lo versiona."""
    resp = backend.revisar_video(_solicitud_revision())
    assert resp["revision_documento"] == 1


# ---------------------------------------------------------------------------
# Endpoints legacy con expected_revision opcional (CAS cuando se envía)
# ---------------------------------------------------------------------------

def test_endpoint_legacy_honra_expected_revision_cuando_se_envia(entorno):
    rev = _commit_video(entorno["validacion"], "old_video")
    with pytest.raises(HTTPException) as exc:
        backend.corregir_campo_caso(
            CLAVE, "pab_comments",
            backend.SolicitudCampoManual(valor="X", usuario="t",
                                         expected_revision=rev - 1 if rev else 0))
    assert exc.value.status_code == 409


def test_primitiva_mutar_documento_existe_y_es_unica(monkeypatch):
    """Toda escritura de RUTA_VALIDACION en app.py pasa por la primitiva.

    Guard estático: ningún endpoint vuelve a llamar directamente a
    ``_guardar_json_atomico(RUTA_VALIDACION, …)`` fuera de la primitiva y de
    la migración de carga (que también debe tomar el lock).
    """
    fuente = Path(backend.__file__).read_text(encoding="utf-8")
    assert "def mutar_documento(" in fuente
    directos = [ln for ln in fuente.splitlines()
                if "_guardar_json_atomico(RUTA_VALIDACION" in ln
                and not ln.strip().startswith("#")]
    assert directos == [], (
        "quedan escrituras directas del documento fuera de la primitiva: "
        f"{directos}")
