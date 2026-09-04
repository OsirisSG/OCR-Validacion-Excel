from entrenamiento_easyocr import _metricas, _separar_por_id, entrenar_lote


def test_separacion_visual_no_mezcla_ids():
    filas = [{"caso_id": caso, "texto_correcto": caso, "ruta_recorte": "x"}
             for caso in ("A", "B", "C", "D", "E") for _ in range(2)]
    entrenamiento, validacion, prueba = _separar_por_id(filas, .2)
    grupos = [{f["caso_id"] for f in conjunto}
              for conjunto in (entrenamiento, validacion, prueba)]
    assert all(grupos[i].isdisjoint(grupos[j]) for i in range(3) for j in range(i + 1, 3))
    assert set.union(*grupos) == {"A", "B", "C", "D", "E"}


def test_metricas_visual_incluyen_cer_wer_partes_y_seriales():
    salida = _metricas(["AB-123", "SERIE 90"], ["AB-I23", "SERIE 90"])
    assert salida["exactitud"] == .5
    assert 0 < salida["cer"] < 1
    assert "wer" in salida and salida["exactitud_numeros_parte"] == 0
    assert salida["exactitud_seriales"] == .5


def test_entrenamiento_espera_lote_suficiente(tmp_path):
    config = {"aprendizaje": {"directorio": str(tmp_path),
                               "visual": {"minimo_muestras": 4}},
              "fase1": {"dispositivo": "cpu"}}
    salida = entrenar_lote(config)
    assert salida["estado"] == "en_espera"
    assert salida["muestras"] == 0
