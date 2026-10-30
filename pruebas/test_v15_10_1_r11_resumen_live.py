from __future__ import annotations


def _fila_publica(*, ident='n1', numero='1', resultado='coincidencia_total', semaforo='verde'):
    return {
        'id': ident,
        'nombre': ident,
        'origen': 'carpeta',
        'resultado': resultado,
        'semaforo': 'verde',
        'semaforo_apertura': semaforo,
        'lote': 'HT',
        'confianza_ocr_pct': 98.0,
        'tipo_st': '1ST',
        'temperature_condition': 'HT',
        'inflator_type': 'UGL',
        'opening_time_ms': 5.8 if semaforo == 'verde' else None,
        'referencia_tiempo_valida': True,
        'estado_tiempo': 'VALIDO',
        'test_number': numero,
    }


def test_resumen_en_vivo_no_mezcla_corrida_anterior(monkeypatch):
    import dashboard.backend.app as app

    monkeypatch.setattr(app, '_cargar_datos', lambda: {
        'resultados': [{'nombre': 'OLD'}], 'generado_en': 'old', 'raiz': 'C:/OLD'
    })
    with app._pipeline_lock:
        anterior = dict(app._pipeline_estado)
        app._pipeline_estado.update({
            'estado': 'procesando',
            'total': 3,
            'procesadas': 1,
            'ejecucion_id': 'run-r11',
            'ruta': 'C:/NEW',
            'actualizado_en': 'now',
            'resultados_parciales': [_fila_publica()],
        })
    try:
        r = app.resumen()
    finally:
        with app._pipeline_lock:
            app._pipeline_estado.clear()
            app._pipeline_estado.update(anterior)

    assert r['resumen_en_vivo'] is True
    assert r['raiz'] == 'C:/NEW'
    assert r['total_carpetas'] == 3
    assert r['total_procesadas'] == 1
    assert r['pendientes_pipeline'] == 2
    assert r['semaforo_apertura']['verde'] == 1
    assert r['semaforo_apertura']['rojo'] == 0
    assert r['semaforo_apertura']['pendiente'] == 2


def test_caso_detectado_sin_procesar_es_pendiente_no_gris(monkeypatch):
    import dashboard.backend.app as app

    pendiente = _fila_publica(ident='p1', numero='2', resultado='sin_procesar', semaforo='gris')
    pendiente['opening_time_ms'] = None
    with app._pipeline_lock:
        anterior = dict(app._pipeline_estado)
        app._pipeline_estado.update({
            'estado': 'procesando', 'total': 1, 'procesadas': 0,
            'ejecucion_id': 'run-r11-p', 'ruta': 'C:/NEW', 'actualizado_en': 'now',
            'resultados_parciales': [pendiente],
        })
    try:
        r = app.resumen()
    finally:
        with app._pipeline_lock:
            app._pipeline_estado.clear()
            app._pipeline_estado.update(anterior)

    assert r['semaforo_apertura']['pendiente'] == 1
    matriz = r['matriz_apertura']
    celda = matriz['etapas'][0]['columnas'][0]['celdas'][0]
    assert celda['estado'] == 'pendiente'
    assert celda['motivo_estado'] == 'procesamiento_pendiente'
    assert celda['pipeline_pendiente'] is True


def test_matriz_expone_score_y_llenado_en_trazabilidad():
    from utilidades.matriz_apertura import celda_caso, criterio_desde_limites

    fila = {
        'id': 'a1', 'test_number': '3',
        'resultado_caso_canonico': {
            'apertura': {
                'estado': 'PROPUESTA',
                'tiempo_estimado_auto_ms': 5.8,
                'auto_color_elegible': True,
                'auto_color_soporte': 1,
                'auto_color_prioridad': 'video_unico_defendible',
                'auto_color_evidencias': [
                    {'score_evidencia': 0.84, 'nivel': 'alta'},
                    {'score_evidencia': 0.77, 'nivel': 'alta'},
                ],
                'duracion_llenado_estimada_ms': 1.2,
                'motivos': ['primer_onset_defendible'],
            }
        },
    }
    celda = celda_caso(fila, criterio_desde_limites(6, 7))
    assert celda['estado'] == 'verde'
    assert celda['tiempo_es_estimado'] is True
    assert celda['auto_color_score_max'] == 0.84
    assert celda['auto_color_niveles'] == ['alta']
    assert celda['duracion_llenado_estimada_ms'] == 1.2
