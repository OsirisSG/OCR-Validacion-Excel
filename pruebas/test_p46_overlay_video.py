"""P46 · Overlay de vídeo EDAG en la corrida normal. Textos con la FORMA medida en los vídeos del
usuario (pie pegado por el OCR) y valores sintéticos (2031, número 993101)."""
from __future__ import annotations

import video_overlay as VO

PIE = "VW316/5 993101 RdW RT NOM 0msEDAG MexBMG19 JUN31Rec5000 fps, Schutter 80us"


def test_pie_pegado_por_el_ocr_se_interpreta():
    datos = VO.interpretar_pie(PIE)
    assert datos["test_date"] == "2031-06-19" and datos["test_number"] == "993101"
    assert (datos["temperature_condition"], datos["inflator_type"], datos["module_version"]) == ("RT", "NOM", "RDW")
    assert datos["test_reason"] == "BMG"
    assert datos["delay_ms"] == "--"                    # P50 · «0ms» es el delay: el libro escribe «--»


def test_candidatos_por_mayoria_y_motivo_solo_propuesto():
    caso = {"case_key": "P|1ST|993101", "project_id": "P", "tipo_st": "1ST"}
    lectura = {"fotogramas": 3, "textos": [PIE], "votos": {
        "test_date": {"2031-06-19": 3}, "test_reason": {"BMG": 3}, "test_place_cabecera": {"EDAG": 3},
        "test_number": {"993101": 1, "993107": 1, "993108": 1}}}
    cands = {c["clave"]: c for c in VO.candidatos_overlay(caso, {"ruta": "/v/A.AVI", "ruta_relativa": "VIDEOS/A.AVI"}, lectura)}
    assert cands["test_date"]["fuente"] == "barra_video" and not cands["test_date"]["requiere_confirmacion_manual"]
    assert cands["test_reason"]["requiere_confirmacion_manual"] is True
    assert cands["test_place"]["regla_aplicada"] == "laboratorio_edag_explicito"
    assert "test_number" not in cands                   # sin mayoría dentro del vídeo


def test_overlay_en_la_ruta_normal_da_fecha_lugar_y_semana_edag(tmp_path, monkeypatch):
    import validacion
    from estructura import guardar_estructura, mapear_estructura
    raiz = tmp_path / "Lote_1ST"
    caso = raiz / "RT" / "253101 RDW NOM RT"
    (caso / "PHOTOS" / "NACH").mkdir(parents=True)
    (caso / "PHOTOS" / "VOR").mkdir()
    (caso / "VIDEOS").mkdir()
    for nombre in ("A_FRONTAL.AVI", "A_LATERAL.AVI"):
        (caso / "VIDEOS" / nombre).write_bytes(b"x")
    monkeypatch.setattr("video_airbag.analizar_video", lambda ruta, config: {"estado": "sin_datos"})
    pie = "VW316/5 253101 RdW RT NOM 0ms EDAG Mex BMG 18 JUN 31 Rec5000 fps"
    lectura = {"fotogramas": 3, "textos": [pie], "votos": {
        **{k: {str(v): 3} for k, v in VO.interpretar_pie(pie).items() if k in VO.CAMPOS_PIE or k == "test_reason"},
        "test_place_cabecera": {"EDAG": 3}}}
    config = {"fase1": {}, "ocr": {}, "normalizacion": {},
              "aprendizaje": {"directorio": str(tmp_path / "apr")},
              "empresarial": {"archivo_cache": str(tmp_path / "c.sqlite3"),
                              "archivo_avance_ids": str(tmp_path / "a.json"),
                              "base_conocimiento": str(tmp_path / "b.json"),
                              "overlay_video": {"activar": True}}}
    estructura = guardar_estructura(mapear_estructura(raiz, config), tmp_path / "e.json")
    r = validacion.validar_lote_empresarial(estructura, config, archivo_salida=tmp_path / "v.json",
                                            lector_overlay=lambda ruta: lectura)
    campos = r["resultados"][0]["campos"]
    assert campos["test_date"]["valor"] == "2031-06-18"
    assert campos["test_place"]["valor"] == "EDAG"
    # 2031-06-18 es semana ISO 25 de 2031 y el número 253101 dice WW=25, YY=31: se corrobora
    assert (campos["week"]["valor"], campos["week"]["estado"]) == (25, "derivado_edag")
    assert campos["test_reason"]["valor"] == "IT BMG"   # P51 · regla del usuario: «BMG» → «IT BMG»
