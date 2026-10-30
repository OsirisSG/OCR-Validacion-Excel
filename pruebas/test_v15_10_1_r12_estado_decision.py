from __future__ import annotations


def _fila_publica(*, ident='n1', numero='1', resultado='coincidencia_total', estado='detectada', semaforo='gris'):
    return {
        'id': ident, 'nombre': ident, 'origen': 'carpeta',
        'resultado': resultado, 'estado': estado,
        'semaforo': 'verde', 'semaforo_apertura': semaforo,
        'lote': 'HT', 'confianza_ocr_pct': 98.0,
        'tipo_st': '1ST', 'temperature_condition': 'HT', 'inflator_type': 'UGL',
        'opening_time_ms': None, 'test_number': numero,
    }


def test_fila_inventariada_con_resultado_parcial_sigue_azul(monkeypatch):
    import dashboard.backend.app as app
    fila = _fila_publica(resultado='coincidencia_total', estado='inventariada')
    with app._pipeline_lock:
        anterior = dict(app._pipeline_estado)
        app._pipeline_estado.update({
            'estado': 'procesando', 'total': 1, 'procesadas': 0,
            'ejecucion_id': 'run-r12', 'ruta': 'C:/NEW', 'actualizado_en': 'now',
            'resultados_parciales': [fila],
        })
    try:
        r = app.resumen()
    finally:
        with app._pipeline_lock:
            app._pipeline_estado.clear(); app._pipeline_estado.update(anterior)
    assert r['total_procesadas'] == 0
    assert r['semaforo_apertura']['pendiente'] == 1
    celda = r['matriz_apertura']['etapas'][0]['columnas'][0]['celdas'][0]
    assert celda['estado'] == 'pendiente'
    assert celda['pipeline_pendiente'] is True
    assert r['matriz_apertura']['tiene_pendientes'] is True


def test_fila_procesada_deja_de_ser_pendiente(monkeypatch):
    import dashboard.backend.app as app
    fila = _fila_publica(resultado='coincidencia_total', estado='procesada', semaforo='verde')
    fila['opening_time_ms'] = 5.8
    with app._pipeline_lock:
        anterior = dict(app._pipeline_estado)
        app._pipeline_estado.update({
            'estado': 'procesando', 'total': 1, 'procesadas': 1,
            'ejecucion_id': 'run-r12-ok', 'ruta': 'C:/NEW', 'actualizado_en': 'now',
            'resultados_parciales': [fila],
        })
    try:
        r = app.resumen()
    finally:
        with app._pipeline_lock:
            app._pipeline_estado.clear(); app._pipeline_estado.update(anterior)
    assert r['total_procesadas'] == 1
    assert r['semaforo_apertura']['pendiente'] == 0


def test_estandar_expone_puertas_y_rechaza_senal_unica_sin_geometria():
    from utilidades.estandar_apertura import evaluar_evidencia_estandar
    candidato = {
        'score_candidato': 0.95, 'continuidad_frames': 4,
        'frames_previos_limpios': 3, 'razones_riesgo': [],
        'tipo_senales': ['material_claro_nuevo'],
    }
    metrica = {
        'pixeles_ruptura': 2, 'componente_ruptura_px': 2,
        'min_pixeles_debil': 1, 'min_componente_debil': 1,
        'fraccion_material_en_rango': 0.001,
        'fraccion_borde_nuevo': 0.0,
        'deformacion_confiable': False,
        'proximidad_deformacion': None,
    }
    posteriores = [dict(metrica, pixeles_ruptura=2, componente_ruptura_px=2)] * 3
    r = evaluar_evidencia_estandar(candidato, {'razones_en_contra': []}, metrica,
                                    metricas_ventana=[metrica, *posteriores])
    assert r['puertas_decision']['geometria_coherente'] is False
    assert 'geometria_coherente' in r['puertas_fallidas']
    assert r['auto_colorable'] is False


def test_estandar_sin_geometria_admite_doble_senal_coherente():
    from utilidades.estandar_apertura import evaluar_evidencia_estandar
    candidato = {
        'score_candidato': 1.0, 'continuidad_frames': 4,
        'frames_previos_limpios': 3, 'razones_riesgo': [],
        'tipo_senales': ['material_claro_nuevo', 'borde_local_nuevo'],
    }
    metrica = {
        'pixeles_ruptura': 3, 'componente_ruptura_px': 3,
        'min_pixeles_debil': 1, 'min_componente_debil': 1,
        'fraccion_material_en_rango': 0.003,
        'fraccion_borde_nuevo': 0.004,
        'deformacion_confiable': False,
        'proximidad_deformacion': None,
    }
    posteriores = [dict(metrica, pixeles_ruptura=12, componente_ruptura_px=12)] * 3
    r = evaluar_evidencia_estandar(candidato, {'razones_en_contra': []}, metrica,
                                    metricas_ventana=[metrica, *posteriores], umbral_alta=0.55)
    assert r['puertas_decision']['geometria_coherente'] is True
    assert r['defendible_un_video'] is True
    assert r['auto_colorable'] is True
