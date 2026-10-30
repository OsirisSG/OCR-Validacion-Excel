"""V15.9.2 · Pruebas que reproducen los defectos C1-C6 de la auditoría estricta.

Cada prueba de este archivo FALLA sobre el árbol V15.9.1 (reproduce el
defecto auditado) y PASA con la corrección aplicada:

- C1: consensos legados 2/4 volvían a validarse con la regla antigua; la
  migración debe reevaluarlos y conservarlos como evidencia pendiente.
- C2: una alerta ``requiere_revision`` sin causa catalogada se evaporaba en
  el consolidado confirmado; ahora distingue informativa vs. bloqueante.
- C3: ``_guardar_json`` ignoraba el fallo de escritura y declaraba éxito.
- C4: el endpoint de reversión persistía la ROI ANTES de reanalizar; un
  fallo posterior dejaba ROI cambiada con JSON/consenso viejos.
- C5: los ``.command`` de macOS perdieron el modo ejecutable (100755).
- C6: falta ``AGENTS.md`` en la raíz (Codex sólo leía ``.agents/AGENTS.md``).

Ejecutar: python -m pytest pruebas/test_v15_9_2_correcciones_c1_c7.py -q
"""
from __future__ import annotations

import importlib
import json
import pathlib
import sys
import types

import pytest
from fastapi import HTTPException

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "pruebas"))

import aprendizaje_video_airbag as ava
import video_airbag as va
from sintetico_airbag import generar_video


def _backend():
    return importlib.import_module("dashboard.backend.app")


def _reset_cache(backend) -> None:
    backend._cache.update({"mtime": None, "datos": None})


ROI_1 = [0.10, 0.10, 0.50, 0.50]
ROI_2 = [0.20, 0.15, 0.65, 0.60]

CAM_A = "09_DETAIL.AVI"
CAM_B = "09_FRONTAL.AVI"
CAM_C = "09_LATERAL.AVI"
CAM_D = "09_SCHEIBE.AVI"


def _item(nombre, tiempo, *, estado="candidato", revision=None, **extra):
    it = {
        "nombre": nombre, "estado": estado, "tiempo_ms": tiempo,
        "tiempo_fps_ms": tiempo, "resolucion_nativa_ms": 0.1,
        "precision_fuente_ms": 0.1, "fuente_tiempo": "fps_subframe",
    }
    if revision:
        it["revision_manual"] = revision
    it.update(extra)
    return it


# ---------------------------------------------------------------------------
# C1 · consensos legados 2/4: la regla antigua ya no los publica
# ---------------------------------------------------------------------------


def test_c1_consenso_legado_2_de_4_ya_no_es_valido():
    """Reproducción literal del caso de la auditoría (video_airbag.py)."""
    legado = {"estado": "primera_aparicion", "tiempo_ms": 6.0, "soporte": 2,
              "total_principales": 4, "requiere_revision": False}
    assert va.consenso_valido(legado) is False


def test_c1_consensos_legados_con_respaldo_suficiente_se_conservan():
    # 3 de 4 principales: la regla vigente también lo confirma.
    assert va.consenso_valido({"estado": "primera_aparicion", "tiempo_ms": 6.0,
                               "soporte": 3, "total_principales": 4,
                               "requiere_revision": False}) is True
    # V15.9.4 (ALTA-N4): política única — los legados automáticos 2/2 y 1/1
    # (aunque traigan metadata completa) NO se publican; el respaldo mínimo
    # automático son 3 cámaras comparables, igual que en la ruta vigente.
    assert va.consenso_valido({"estado": "primera_aparicion", "tiempo_ms": 6.0,
                               "soporte": 2, "total_principales": 2,
                               "requiere_revision": False}) is False
    assert va.consenso_valido({"estado": "primera_aparicion", "tiempo_ms": 6.0,
                               "soporte": 1, "total_principales": 1,
                               "requiere_revision": False}) is False
    # Confirmaciones manuales reales: siempre se preservan.
    assert va.consenso_valido({"estado": "confirmado_manual", "tiempo_ms": 6.0,
                               "soporte": 1, "total_principales": 4}) is True


def test_c1_consenso_nuevo_lleva_sello_de_algoritmo():
    items = [_item(CAM_A, 12.0), _item(CAM_B, 12.05), _item(CAM_C, 12.1)]
    consenso = va.consenso_videos(items, {})
    assert consenso.get("algoritmo_consenso") == va.CONSENSO_ALGORITMO_VERSION


def test_c1_migracion_reevalua_2_de_4_y_conserva_evidencia(tmp_path, monkeypatch):
    """El JSON persistido con consenso legado 2/4 se migra al cargar."""
    backend = _backend()
    videos = [_item(CAM_A, 12.0), _item(CAM_B, 12.05),
              _item(CAM_C, 40.0), _item(CAM_D, 40.0)]
    for v in videos:
        v["ruta"] = f"CASO1/{v['nombre']}"
    fila = {
        "nombre": "CASO1", "case_key": "CASO1", "campos": {
            "opening_time_ms": {"valor": "12.0", "estado": "extraido_video",
                                "fuente": "video_airbag_consenso",
                                "soporte_videos": 2}},
        "consolidado": {}, "videos": videos,
        # Consenso persistido por la regla ANTIGUA (V15.8.x): 2/4 publicado.
        "video_apertura": {"estado": "primera_aparicion", "tiempo_ms": 12.0,
                           "soporte": 2, "total_principales": 4,
                           "requiere_revision": False},
    }
    validacion = tmp_path / "validacion_resultados.json"
    validacion.write_text(json.dumps({"resultados": [fila]}), encoding="utf-8")
    monkeypatch.setattr(backend, "RUTA_VALIDACION", validacion)
    _reset_cache(backend)
    try:
        datos = backend._cargar_datos()
        f = datos["resultados"][0]
        # Evidencia anterior conservada, sello vigente en el nuevo consenso.
        assert f["video_apertura_anterior"]["soporte"] == 2
        assert f["video_apertura_anterior"].get("algoritmo_consenso") is None
        assert f["video_apertura"]["algoritmo_consenso"] == va.CONSENSO_ALGORITMO_VERSION
        # 2/4 reevaluado ⇒ ya no se publica: queda pendiente con su medida.
        assert va.consenso_valido(f["video_apertura"]) is False
        campo = f["campos"]["opening_time_ms"]
        assert campo["estado"] == "pendiente_revision"
        assert float(campo["valor"]) == pytest.approx(12.0)
        # La migración se persistió en disco (el Excel no revive el 2/4).
        disco = json.loads(validacion.read_text(encoding="utf-8"))
        assert disco["resultados"][0]["video_apertura"]["algoritmo_consenso"] \
            == va.CONSENSO_ALGORITMO_VERSION
        assert disco["resultados"][0]["campos"]["opening_time_ms"]["estado"] \
            == "pendiente_revision"
    finally:
        _reset_cache(backend)


def test_c1_migracion_preserva_confirmacion_manual_real(tmp_path, monkeypatch):
    backend = _backend()
    videos = [_item(CAM_A, 12.0, revision={"estado": "confirmado",
                                           "tiempo_ms": 11.5, "usuario": "ana"}),
              _item(CAM_B, 40.0), _item(CAM_C, 41.0), _item(CAM_D, 42.0)]
    fila = {"nombre": "CASO2", "case_key": "CASO2", "campos": {}, "videos": videos,
            "video_apertura": {"estado": "primera_aparicion", "tiempo_ms": 12.0,
                               "soporte": 2, "total_principales": 4,
                               "requiere_revision": False}}
    validacion = tmp_path / "validacion_resultados.json"
    validacion.write_text(json.dumps({"resultados": [fila]}), encoding="utf-8")
    monkeypatch.setattr(backend, "RUTA_VALIDACION", validacion)
    _reset_cache(backend)
    try:
        f = backend._cargar_datos()["resultados"][0]
        assert f["video_apertura"]["estado"] == "confirmado_manual"
        assert va.consenso_valido(f["video_apertura"]) is True
        campo = f["campos"]["opening_time_ms"]
        assert campo["estado"] == "extraido_video"
        assert float(campo["valor"]) == pytest.approx(11.5)
        assert f["video_apertura_anterior"]["soporte"] == 2
    finally:
        _reset_cache(backend)


def test_c1_normalizar_fila_reevalua_por_sello_obsoleto():
    """_normalizar_tiempos_video_fila también migra en caliente la vista."""
    backend = _backend()
    fila = {"campos": {"opening_time_ms": {"valor": "12.0", "estado": "extraido_video",
                                           "fuente": "video_airbag_consenso"}},
            "videos": [_item(CAM_A, 12.0), _item(CAM_B, 12.05),
                       _item(CAM_C, 40.0), _item(CAM_D, 40.0)],
            "video_apertura": {"estado": "primera_aparicion", "tiempo_ms": 12.0,
                               "soporte": 2, "total_principales": 4,
                               "requiere_revision": False}}
    cambiado = backend._normalizar_tiempos_video_fila(fila)
    assert cambiado is True
    assert fila["video_apertura"]["algoritmo_consenso"] == va.CONSENSO_ALGORITMO_VERSION
    assert fila["video_apertura_anterior"]["soporte"] == 2
    assert fila["campos"]["opening_time_ms"]["estado"] == "pendiente_revision"


# ---------------------------------------------------------------------------
# C2 · alertas sin clasificar: informativas vs. bloqueantes
# ---------------------------------------------------------------------------

ALERTA_NUEVA = "Alerta heurística experimental del sensor v3 (no documentada)"


def test_c2_alerta_sin_clasificar_bloquea_el_consolidado():
    """3 cámaras de acuerdo + 1 alerta no catalogada ⇒ NO se publica solo."""
    items = [_item(CAM_A, 12.0),
             _item(CAM_B, 12.05, requiere_revision=True, motivo=ALERTA_NUEVA),
             _item(CAM_C, 12.1)]
    consenso = va.consenso_videos(items, {})
    assert consenso["estado_consenso"] == "confirmado"  # el respaldo numérico existe
    assert consenso["revision_no_clasificada"] is True
    assert consenso["requiere_revision"] is True
    assert va.consenso_valido(consenso) is False
    assert any("SIN CLASIFICAR" in m for m in consenso["motivo_revision"])
    assert any(ALERTA_NUEVA in m for m in consenso["motivo_revision"])
    # La alerta queda expuesta por cámara para la UI.
    camara = next(p for p in consenso["primer_instante_por_camara"]
                  if p["video"] == CAM_B)
    assert camara["alerta_sin_clasificar"] is True
    assert camara["motivo_alerta"] == ALERTA_NUEVA


def test_c2_alerta_sin_clasificar_deja_la_fila_pendiente():
    backend = _backend()
    items = [_item(CAM_A, 12.0),
             _item(CAM_B, 12.05, requiere_revision=True, motivo=ALERTA_NUEVA),
             _item(CAM_C, 12.1)]
    fila = {"campos": {}, "videos": []}
    backend._aplicar_consenso_video_a_fila(fila, va.consenso_videos(items, {}))
    campo = fila["campos"]["opening_time_ms"]
    assert campo["estado"] == "pendiente_revision"
    assert any("SIN CLASIFICAR" in m for m in campo["motivos_revision"])


def test_c2_revision_informativa_no_bloquea_confirmacion_limpia():
    """La bandera genérica del detector (informativa) no impide confirmar."""
    items = [_item(CAM_A, 12.0, requiere_revision=True, revision_informativa=True),
             _item(CAM_B, 12.05, requiere_revision=True, revision_informativa=True),
             _item(CAM_C, 12.1, requiere_revision=True, revision_informativa=True)]
    consenso = va.consenso_videos(items, {})
    assert consenso["estado_consenso"] == "confirmado"
    assert consenso["revision_no_clasificada"] is False
    assert consenso["requiere_revision"] is False
    assert va.consenso_valido(consenso) is True


def test_c2_items_legados_sin_motivo_bloquean_v15_9_3():
    """V15.9.3 (CRIT-02): la AUSENCIA de motivo no implica revisión informativa.

    En V15.9.2 esta bandera genérica se trataba como informativa y publicaba
    el consenso confirmado; la auditoría exige que sólo una marca explícita
    y auditable ``revision_informativa=True`` excepcione el bloqueo. Un
    integrante con ``requiere_revision=True`` sin motivo se conserva pendiente
    hasta revisión humana.
    """
    items = [_item(CAM_A, 12.0, requiere_revision=True),
             _item(CAM_B, 12.05, requiere_revision=True),
             _item(CAM_C, 12.1, requiere_revision=True)]
    consenso = va.consenso_videos(items, {})
    assert consenso["revision_no_clasificada"] is True
    assert consenso["requiere_revision"] is True
    assert va.consenso_valido(consenso) is False
    # La marca informativa explícita (sello del detector actual) sí excepciona.
    informativos = [_item(CAM_A, 12.0, requiere_revision=True, revision_informativa=True),
                    _item(CAM_B, 12.05, requiere_revision=True, revision_informativa=True),
                    _item(CAM_C, 12.1, requiere_revision=True, revision_informativa=True)]
    assert va.consenso_valido(va.consenso_videos(informativos, {})) is True


def test_c2_confirmacion_manual_manda_sobre_alerta_sin_clasificar():
    items = [_item(CAM_A, 11.5, revision={"estado": "confirmado", "tiempo_ms": 11.5}),
             _item(CAM_B, 12.05, requiere_revision=True, motivo=ALERTA_NUEVA),
             _item(CAM_C, 12.1)]
    consenso = va.consenso_videos(items, {})
    assert consenso["estado"] == "confirmado_manual"
    assert va.consenso_valido(consenso) is True


def test_c2_causa_grave_sigue_bloqueando_regresion_b2():
    items = [_item(CAM_A, 12.0, advertencia_fps="12 fps declarados"),
             _item(CAM_B, 12.05), _item(CAM_C, 12.1)]
    consenso = va.consenso_videos(items, {})
    assert consenso["requiere_revision"] is True
    assert va.consenso_valido(consenso) is False
    assert consenso["revision_no_clasificada"] is False


def test_c2_detector_marca_su_bandera_como_informativa(tmp_path):
    ruta = tmp_path / "09_DETAIL.AVI"
    generar_video(ruta, total=24, ancho=320, alto=240)
    resultado = va.analizar_video(ruta, {}, usar_cache=False)
    if resultado.get("estado") != "candidato":
        pytest.skip("el video sintético no produjo detección en este entorno")
    assert resultado.get("requiere_revision") is True
    assert resultado.get("revision_informativa") is True


# ---------------------------------------------------------------------------
# C3 · persistencia verificada del aprendizaje
# ---------------------------------------------------------------------------


@pytest.fixture
def video_y_almacen(tmp_path, monkeypatch):
    monkeypatch.setattr(ava, "RUTA_APRENDIZAJE", tmp_path / "zonas.json")
    monkeypatch.setattr(ava, "RUTA_REFERENCIAS", tmp_path / "referencias")
    ruta = tmp_path / "09_DETAIL.AVI"
    generar_video(ruta, total=16, ancho=320, alto=240)
    return ruta


def test_c3_guardar_zona_con_escritura_fallida_no_declara_exito(video_y_almacen, monkeypatch):
    """Reproducción del defecto: fallo de escritura simulado ⇒ error, no éxito."""
    ruta = video_y_almacen
    monkeypatch.setattr(ava, "escribir_json_seguro", lambda *a, **k: False)
    with pytest.raises(ava.ErrorPersistenciaAprendizaje):
        ava.guardar_zona_aprendida(ruta, ROI_1, usuario="qa")
    # No quedó ningún perfil persistido que no exista realmente.
    disco = json.loads((ava.RUTA_APRENDIZAJE).read_text(encoding="utf-8")) \
        if pathlib.Path(ava.RUTA_APRENDIZAJE).exists() else {"perfiles": []}
    assert disco["perfiles"] == []


def test_c3_revertir_con_escritura_fallida_deja_el_json_intacto(video_y_almacen, monkeypatch):
    ruta = video_y_almacen
    ava.guardar_zona_aprendida(ruta, ROI_1, usuario="qa")
    ava.guardar_zona_aprendida(ruta, ROI_2, usuario="qa")
    antes = pathlib.Path(ava.RUTA_APRENDIZAJE).read_bytes()
    monkeypatch.setattr(ava, "escribir_json_seguro", lambda *a, **k: False)
    with pytest.raises(ava.ErrorPersistenciaAprendizaje):
        ava.revertir_zona_aprendida(ruta, usuario="qa")
    # El JSON guardado conserva la ROI_2 activa: nada de «éxito» fantasma.
    assert pathlib.Path(ava.RUTA_APRENDIZAJE).read_bytes() == antes
    perfil = ava.perfil_zona_aprendida(ruta)
    assert perfil["bbox_norm"] == ROI_2


def test_c3_endpoint_revertir_reporta_fallo_de_persistencia(env_revertir, monkeypatch):
    env = env_revertir
    monkeypatch.setattr(env.ava, "escribir_json_seguro", lambda *a, **k: False)
    with pytest.raises(HTTPException) as err:
        env.backend.revertir_zona_video(env.solicitud(usuario="qa"))
    assert err.value.status_code == 503
    assert "no cambió" in str(err.value.detail)
    # La ROI activa en disco sigue siendo la previa a la operación.
    assert env.ava.perfil_zona_aprendida(env.video)["bbox_norm"] == ROI_2


# ---------------------------------------------------------------------------
# C4 · reversión transaccional del endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def env_revertir(tmp_path, monkeypatch):
    backend = _backend()
    raiz = tmp_path / "lote"
    (raiz / "CASO1").mkdir(parents=True)
    video = raiz / "CASO1" / "09_DETAIL.AVI"
    generar_video(video, total=16, ancho=320, alto=240)
    datos = {"resultados": [{
        "nombre": "CASO1", "case_key": "CASO1", "campos": {}, "consolidado": {},
        "videos": [{"id": "v1", "ruta": str(video),
                    "ruta_relativa": "CASO1/09_DETAIL.AVI",
                    "carpeta_video": "CASO1", "nombre": video.name,
                    "estado": "candidato", "tiempo_ms": 12.0,
                    "resolucion_nativa_ms": 0.1, "fuente_tiempo": "fps_subframe"}],
    }]}
    validacion = tmp_path / "validacion_resultados.json"
    validacion.write_text(json.dumps(datos), encoding="utf-8")
    monkeypatch.setattr(backend, "RUTA_VALIDACION", validacion)
    monkeypatch.setattr(backend, "_resolver_raiz_datos", lambda d: raiz)
    monkeypatch.setattr(backend, "_resolver_imagen", lambda ruta, d, r: pathlib.Path(ruta))
    llamadas_excel = []
    monkeypatch.setattr(backend, "_regenerar_excel", lambda resultado: llamadas_excel.append(resultado))
    _reset_cache(backend)
    # ROI aprendida con historial: revertir debe restaurar ROI_1.
    monkeypatch.setattr(ava, "RUTA_APRENDIZAJE", tmp_path / "zonas.json")
    monkeypatch.setattr(ava, "RUTA_REFERENCIAS", tmp_path / "referencias")
    ava.guardar_zona_aprendida(video, ROI_1, usuario="qa")
    ava.guardar_zona_aprendida(video, ROI_2, usuario="qa")
    prueba_id = backend._id_fila(datos["resultados"][0])
    solicitud_cls = backend.SolicitudZonaRevertir
    env = types.SimpleNamespace(
        backend=backend, ava=ava, va=va, video=video, raiz=raiz,
        validacion=validacion, llamadas_excel=llamadas_excel,
        solicitud=lambda **kw: solicitud_cls(prueba_id=prueba_id, video_id="v1", **kw),
    )
    yield env
    _reset_cache(backend)


def test_c4_fallo_de_analisis_restaura_la_roi(env_revertir, monkeypatch):
    """Reproducción del defecto: analizar_video falla DESPUÉS de persistir la ROI."""
    env = env_revertir

    def boom(*args, **kwargs):
        raise RuntimeError("fallo inyectado de análisis")

    monkeypatch.setattr(env.va, "analizar_video", boom)
    json_antes = env.validacion.read_bytes()
    with pytest.raises(HTTPException) as err:
        env.backend.revertir_zona_video(env.solicitud(usuario="qa"))
    assert err.value.status_code == 500
    assert "DESHIZO" in str(err.value.detail)
    # Rollback: la ROI activa vuelve a ser la previa (ROI_2) en disco.
    assert env.ava.perfil_zona_aprendida(env.video)["bbox_norm"] == ROI_2
    # El JSON de resultados no quedó a medias.
    assert env.validacion.read_bytes() == json_antes
    # No se declaró éxito ni se encoló Excel.
    assert env.llamadas_excel == []


def test_c4_fallo_al_guardar_resultados_restaura_la_roi(env_revertir, monkeypatch):
    env = env_revertir
    # R15.2 (CRÍTICO-02): la escritura del documento vive en la autoridad
    # compartida; el fallo se inyecta allí.
    from utilidades import persistencia_documento
    real = persistencia_documento.escribir_json_seguro

    def fallida(destino, contenido, **kwargs):
        if pathlib.Path(destino) == env.validacion:
            raise RuntimeError("disco lleno (fallo inyectado)")
        return real(destino, contenido, **kwargs)

    monkeypatch.setattr(persistencia_documento, "escribir_json_seguro", fallida)
    json_antes = env.validacion.read_bytes()
    with pytest.raises(HTTPException) as err:
        env.backend.revertir_zona_video(env.solicitud(usuario="qa"))
    assert err.value.status_code == 500
    assert "DESHIZO" in str(err.value.detail)
    assert env.ava.perfil_zona_aprendida(env.video)["bbox_norm"] == ROI_2
    assert env.validacion.read_bytes() == json_antes


def test_c4_video_ilegible_no_inicia_la_reversion(env_revertir, monkeypatch, tmp_path):
    env = env_revertir
    roto = tmp_path / "roto.avi"
    roto.write_bytes(b"esto no es un video")
    monkeypatch.setattr(env.backend, "_resolver_imagen", lambda *a: roto)
    with pytest.raises(HTTPException) as err:
        env.backend.revertir_zona_video(env.solicitud(usuario="qa"))
    assert err.value.status_code == 422
    assert "no iniciada" in str(err.value.detail).lower()
    # Nada se movió: la ROI activa sigue siendo ROI_2 y el historial intacto.
    assert env.ava.perfil_zona_aprendida(env.video)["bbox_norm"] == ROI_2
    assert env.ava.historial_zona_aprendida(env.video)[0]["bbox_norm"] == ROI_1


def test_c4_reversion_exitosa_verifica_escritura(env_revertir, monkeypatch):
    """Camino feliz: la reversión completa sólo tras escritura verificada."""
    env = env_revertir
    nuevo = {"estado": "candidato", "tiempo_ms": 12.0, "nombre": env.video.name,
             "resolucion_nativa_ms": 0.1, "fuente_tiempo": "fps_subframe",
             "requiere_revision": True, "revision_informativa": True}
    monkeypatch.setattr(env.va, "analizar_video", lambda *a, **k: dict(nuevo))
    resultado = env.backend.revertir_zona_video(env.solicitud(usuario="qa"))
    assert resultado["revertido"] is True
    assert resultado["escritura_verificada"] is True
    assert resultado["perfil"]["bbox_norm"] == ROI_1
    assert env.ava.perfil_zona_aprendida(env.video)["bbox_norm"] == ROI_1
    assert env.llamadas_excel and resultado["video"]["id"] == "v1"
    disco = json.loads(env.validacion.read_text(encoding="utf-8"))
    assert disco["resultados"][0]["videos"][0]["tiempo_ms"] == 12.0


# ---------------------------------------------------------------------------
# C5 · modo ejecutable de los .command (macOS)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Windows no expone bits de modo POSIX en stat()")
def test_c5_comandos_mac_conservan_modo_ejecutable():
    for nombre in ("iniciar.command", "instalar.command"):
        ruta = RAIZ / nombre
        assert ruta.is_file(), f"falta {nombre}"
        modo = ruta.stat().st_mode & 0o777
        assert modo & 0o111, f"{nombre} perdió el bit ejecutable (modo {oct(modo)})"


# ---------------------------------------------------------------------------
# C6 · AGENTS.md en la raíz del repositorio
# ---------------------------------------------------------------------------


def test_c6_agents_md_en_la_raiz():
    ruta = RAIZ / "AGENTS.md"
    assert ruta.is_file(), "Codex sólo descubre AGENTS.md en la raíz"
    texto = ruta.read_text(encoding="utf-8")
    assert "skills" in texto.lower()
    # El archivo interno de la organización sigue existiendo.
    assert (RAIZ / ".agents" / "AGENTS.md").is_file()
