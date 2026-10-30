"""V15.7.1: firma por contenido, caché de video y control de Rec…fps con el reloj."""
import json
import shutil
from pathlib import Path
from unittest import mock

import aprendizaje_video_airbag as ava
import video_airbag as va
from sintetico_airbag import generar_video, overlay_falso
from utilidades import firma_video


def _video(tmp_path, nombre="081_LATERAL.AVI", carpeta="252581 RDW NOM RT/VIDEOS", **kw):
    destino = tmp_path / carpeta
    destino.mkdir(parents=True, exist_ok=True)
    ruta = destino / nombre
    generar_video(ruta, frame_hinchado=None, frame_bolsa=10, total=30, **kw)
    return ruta


# --- Identidad del video -------------------------------------------------------

def test_revision_sobrevive_a_copiar_la_carpeta(tmp_path):
    original = _video(tmp_path / "lote")
    va.guardar_revision_video(original, case_key="c", frame_index=10, tiempo_ms=2.0,
                              referencia_tiempo_valida=True, fuente_tiempo="fps_adquisicion")
    copia = tmp_path / "copia" / "RT" / "252581 RDW NOM RT" / "VIDEOS" / original.name
    copia.parent.mkdir(parents=True)
    shutil.copy2(original, copia)
    rev = va.revision_video(copia)
    assert rev and rev["frame_index"] == 10 and rev["tiempo_ms"] == 2.0


def test_revision_antigua_se_reconoce_por_id_y_nombre(tmp_path):
    # Revisión guardada por V15.6 en Windows con la firma ruta|tamaño|mtime.
    ruta = _video(tmp_path / "otra_ubicacion")
    va.RUTA_REVISIONES.write_text(json.dumps({"version": 1, "revisiones": {
        "firma-antigua": {"firma": "firma-antigua", "frame_index": 10, "tiempo_ms": 2.0,
                          "estado": "confirmado",
                          "ruta_video": r"C:\Users\x\copia\RT\252581 RDW NOM RT\VIDEOS\081_LATERAL.AVI"}}}),
        encoding="utf-8")
    assert va.revision_video(ruta)["frame_index"] == 10
    # Otro ID con el mismo nombre de archivo NO hereda esa revisión.
    ajeno = _video(tmp_path / "x", carpeta="999999 OTRO/VIDEOS")
    assert va.revision_video(ajeno) is None


def test_volver_a_confirmar_no_duplica_revisiones(tmp_path):
    ruta = _video(tmp_path)
    va.guardar_revision_video(ruta, case_key="c", frame_index=10, tiempo_ms=2.0,
                              referencia_tiempo_valida=True, fuente_tiempo="fps_adquisicion")
    va.guardar_revision_video(ruta, case_key="c", frame_index=11, tiempo_ms=2.2,
                              referencia_tiempo_valida=True, fuente_tiempo="fps_adquisicion")
    data = va.cargar_revisiones()["revisiones"]
    assert len(data) == 1
    assert next(iter(data.values()))["frame_index"] == 11


def test_zona_bloqueada_sigue_al_video_copiado(tmp_path):
    original = _video(tmp_path / "lote")
    ava.guardar_zona_aprendida(original, [0.2, 0.3, 0.6, 0.7], frame_index=10)
    copia = tmp_path / "copia" / original.name
    copia.parent.mkdir(parents=True)
    shutil.copy2(original, copia)
    import cv2
    ok, primer = cv2.VideoCapture(str(copia)).read()
    zona = ava.seleccionar_zona_aprendida(copia, primer, {"video_airbag": {}})
    assert zona["activa"] and zona["bbox_norm"] == [0.2, 0.3, 0.6, 0.7]


# --- Caché ---------------------------------------------------------------------

def test_cache_conserva_un_resultado_por_video(tmp_path):
    ruta = _video(tmp_path)
    with mock.patch.object(va, "_leer_overlay", overlay_falso(5000.0)):
        va.analizar_video(ruta, {"video_airbag": {"umbral_diff_min": 6.0}}, usar_cache=False)
        va.analizar_video(ruta, {"video_airbag": {"umbral_diff_min": 7.0}}, usar_cache=False)
    cache = json.loads(va.RUTA_CACHE.read_text(encoding="utf-8"))
    assert len(cache["items"]) == 1


def test_cache_descarta_algoritmos_anteriores(tmp_path):
    va.RUTA_CACHE.write_text(json.dumps({"version": 6, "items": {
        "vieja": {"firma": "otra", "algoritmo_video": "v15.6-fps-overlay-autorreparado-ui-estable"}}}),
        encoding="utf-8")
    ruta = _video(tmp_path)
    with mock.patch.object(va, "_leer_overlay", overlay_falso(5000.0)):
        va.analizar_video(ruta, {"video_airbag": {}}, usar_cache=False)
    cache = json.loads(va.RUTA_CACHE.read_text(encoding="utf-8"))
    assert "vieja" not in cache["items"]


def test_cache_desde_otra_carpeta_actualiza_la_ruta(tmp_path):
    original = _video(tmp_path / "lote")
    with mock.patch.object(va, "_leer_overlay", overlay_falso(5000.0)):
        va.analizar_video(original, {"video_airbag": {}}, usar_cache=False)
        copia = tmp_path / "copia" / original.name
        copia.parent.mkdir(parents=True)
        shutil.copy2(original, copia)
        r = va.analizar_video(copia, {"video_airbag": {}})
    assert r["desde_cache"] is True
    assert r["ruta"] == str(copia.resolve())


def test_zona_de_otra_camara_no_invalida_el_cache(tmp_path):
    detail = _video(tmp_path, nombre="081_DETAIL.AVI")
    lateral = _video(tmp_path, nombre="081_LATERAL.AVI", semilla=9)
    antes = ava.version_aprendizajes(detail)
    ava.guardar_zona_aprendida(lateral, [0.1, 0.1, 0.5, 0.5])
    assert ava.version_aprendizajes(detail) == antes
    assert ava.version_aprendizajes(lateral) != antes


# --- Reloj por cuadro -----------------------------------------------------------

def test_reloj_del_mismo_cuadro_no_repite_ocr(tmp_path):
    ruta = _video(tmp_path)
    llamadas = []

    def lector(r, f, c=None):
        llamadas.append(f)
        return {"timestamp_ms": f * 0.2, "precision_ms": 0.1, "texto": "", "error": None}

    with mock.patch.object(va, "_leer_timestamp_esquina_frame_sin_cache", lector):
        assert va.leer_timestamp_esquina_frame(ruta, 11)["timestamp_ms"] == 2.2
        assert va.leer_timestamp_esquina_frame(ruta, 11)["timestamp_ms"] == 2.2
    assert llamadas == [11]


# --- Rec…fps contra el reloj ----------------------------------------------------

def test_rec_mal_leido_se_corrige_si_otro_cuadro_confirma_el_reloj():
    r = va.validar_fps_con_reloj(500.0, 11, 2.2, 0.0, leer_reloj=lambda f: f * 0.2)
    assert r["corregido"] and r["fps"] == 5000.0
    assert "500" in r["advertencia"]


def test_reloj_mal_leido_no_cambia_rec_correcto():
    # OCR leyó 22.0 en el cuadro del evento; otro cuadro confirma Rec5000.
    r = va.validar_fps_con_reloj(5000.0, 11, 22.0, 0.0, leer_reloj=lambda f: f * 0.2)
    assert not r["corregido"] and r["fps"] == 5000.0
    assert r["advertencia"]


def test_sin_tercer_cuadro_solo_avisa():
    r = va.validar_fps_con_reloj(500.0, 11, 2.2, 0.0)
    assert not r["corregido"] and r["fps"] == 500.0 and r["advertencia"]


def test_rec_y_reloj_coinciden_sin_aviso():
    r = va.validar_fps_con_reloj(5000.0, 11, 2.2, 0.0, leer_reloj=lambda f: 999.0)
    assert not r["corregido"] and r["advertencia"] is None


def test_tasa_validada_manda_sobre_texto_rec_mal_leido():
    item = {"overlay_texto": "EDAG Rec500 fps", "fps_validado_reloj": 5000.0}
    assert va.fps_grabacion_desde_item(item) == 5000.0


def test_firma_contenido_estable_y_distinta(tmp_path):
    a = _video(tmp_path / "a")
    b = _video(tmp_path / "b", semilla=3)
    c = tmp_path / "c.avi"
    shutil.copy2(a, c)
    assert firma_video.firma_contenido(a) == firma_video.firma_contenido(c)
    assert firma_video.firma_contenido(a) != firma_video.firma_contenido(b)


def test_analisis_corrige_rec_mal_leido_con_el_reloj(tmp_path):
    ruta = _video(tmp_path)  # bolsa en el cuadro 10 = 2.0 ms a 5000 fps
    lecturas = iter([0.0, 2.0])  # cuadro 0 y cuadro del evento

    def overlay(frame, config=None):
        return {"texto": "Rec500 fps", "tiempos_ms": [], "fps_grabacion": [500.0],
                "timestamp_esquina_ms": next(lecturas), "precision_timestamp_esquina_ms": 0.1,
                "timestamp_origen": "esquina_crop", "texto_esquina": "", "error": None}

    reloj = lambda r, f, c=None: {"timestamp_ms": round(f * 0.2, 1), "precision_ms": 0.1,
                                   "texto": "", "error": None}
    with mock.patch.object(va, "_leer_overlay", overlay), \
            mock.patch.object(va, "leer_timestamp_esquina_frame", reloj):
        r = va.analizar_video(ruta, {"video_airbag": {}}, usar_cache=False)
    assert r["frame_evento"] == 10
    assert r["fps"] == 5000.0 and r["fps_fuente"] == "reloj_overlay"
    assert r["tiempo_ms"] == 2.0
    assert r["advertencia_fps"]
    # La normalización posterior no vuelve a los 500 fps del texto.
    va.normalizar_item_temporal_video(r, {"video_airbag": {}})
    assert r["fps"] == 5000.0 and r["tiempo_ms"] == 2.0
