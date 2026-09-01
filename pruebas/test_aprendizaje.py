from aprendizaje import GestorAprendizaje, rotar_bbox


def _gestor(tmp_path, **cambios):
    cfg = {
        "activar": True,
        "registrar_observaciones": True,
        "aplicar_modelo": True,
        "minimo_soporte_exacto": 2,
        "minimo_soporte_caracter": 3,
        "minimo_soporte_patron": 2,
        "dominancia_minima": 0.8,
        **cambios,
    }
    return GestorAprendizaje({"aprendizaje": cfg}, directorio=tmp_path / "modelo")


def test_no_aprende_de_una_prediccion_sin_confirmar(tmp_path):
    imagen = tmp_path / "foto.jpg"
    imagen.write_bytes(b"imagen-ficticia")
    gestor = _gestor(tmp_path)

    registro = gestor.registrar_ejecucion([{
        "imagen": str(imagen), "motor": "falso",
        "tokens": [{"texto": "K001", "confianza": 0.9, "bbox": (1, 2, 3, 4)}],
    }])

    assert registro["tokens"] == 1
    assert gestor.estado()["correcciones"] == 0
    assert gestor.aplicar("K001") == ("K001", None)


def test_promueve_correccion_exacta_solo_con_soporte_repetido(tmp_path):
    gestor = _gestor(tmp_path)

    primera = gestor.registrar_correccion("K001", "GCC10", imagen_hash="imagen-1")
    assert primera["entrenamiento"]["promovido"] is False
    assert gestor.aplicar("K001") == ("K001", None)

    segunda = gestor.registrar_correccion("K001", "GCC10", imagen_hash="imagen-2")
    assert segunda["entrenamiento"]["promovido"] is True
    corregido, evidencia = gestor.aplicar("K001")
    assert corregido == "GCC10"
    assert evidencia["tipo"] == "exacta"
    assert evidencia["soporte"] == 2


def test_reutiliza_correccion_en_misma_imagen_y_caja_sin_generalizar(tmp_path):
    imagen = tmp_path / "placa.jpg"
    imagen.write_bytes(b"misma-imagen")
    gestor = _gestor(tmp_path)
    gestor.registrar_correccion(
        "GCCIO", "GCC10", ruta_imagen=str(imagen), bbox=[10, 20, 80, 30])

    tokens = [
        {"texto": "GCCio", "bbox": (10, 20, 80, 30), "confianza": 0.7},
        {"texto": "GCCio", "bbox": (200, 20, 80, 30), "confianza": 0.7},
    ]
    recordados = gestor.aplicar_memoria_imagen(tokens, imagen)

    assert recordados[0]["texto"] == "GCC10"
    assert recordados[0]["correccion_modelo"]["tipo"] == "memoria_imagen_confirmada"
    assert recordados[1]["texto"] == "GCCio"
    assert gestor.aplicar("GCCio") == ("GCCio", None)
    assert gestor.estado()["memorias_imagen"] == 1


def test_generaliza_confusion_de_caracter_solo_con_patron_confirmado(tmp_path):
    gestor = _gestor(tmp_path)
    pares = [
        ("A0-123", "AO-123", "imagen-a"),
        ("B0-456", "BO-456", "imagen-b"),
        ("C0-789", "CO-789", "imagen-c"),
    ]
    for crudo, correcto, imagen_hash in pares:
        gestor.registrar_correccion(crudo, correcto, imagen_hash=imagen_hash)

    corregido, evidencia = gestor.aplicar("D0-111")
    assert corregido == "DO-111"
    assert evidencia["tipo"] == "caracteres"
    assert evidencia["soporte_patron"] == 3


def test_rollback_reactiva_version_anterior(tmp_path):
    gestor = _gestor(tmp_path)
    gestor.registrar_correccion("K001", "GCC10", imagen_hash="imagen-1")
    primera = gestor.registrar_correccion("K001", "GCC10", imagen_hash="imagen-2")
    version_primera = primera["entrenamiento"]["version"]
    gestor.registrar_correccion("Z999", "IBC20", imagen_hash="imagen-3")
    segunda = gestor.registrar_correccion("Z999", "IBC20", imagen_hash="imagen-4")
    assert segunda["entrenamiento"]["promovido"] is True

    resultado = gestor.rollback(version_primera)

    assert resultado["activo"] == version_primera
    assert gestor.aplicar("K001")[0] == "GCC10"
    assert gestor.aplicar("Z999")[0] == "Z999"


def test_guarda_correccion_de_espacios_sin_contaminar_modelo(tmp_path):
    gestor = _gestor(tmp_path)

    resultado = gestor.registrar_correccion(
        "LOTE2026\nLINEA2", "LOTE 2026\nLINEA 2", imagen_hash="imagen-layout")

    assert resultado["registrada"] is True
    assert resultado["tipo"] == "layout"
    assert resultado["entrenamiento"] is None
    estado = gestor.estado()
    assert estado["correcciones"] == 1
    assert estado["correcciones_modelo"] == 0


def test_guarda_region_sin_lectura_ocr_y_la_agrupa(tmp_path):
    imagen = tmp_path / "foto.jpg"
    imagen.write_bytes(b"imagen-region")
    gestor = _gestor(tmp_path)

    resultado = gestor.registrar_region(
        "SERIE NO DETECTADA\nA-019", [10, 20, 120, 45],
        ruta_imagen=str(imagen), carpeta_id="carpeta-1",
        carpeta_nombre="01_A1", imagen_nombre="foto.jpg")

    assert resultado["registrada"] is True
    regiones = gestor.listar_anotaciones([imagen], carpeta_id="carpeta-1")
    assert len(regiones) == 1
    assert regiones[0]["texto_correcto"] == "SERIE NO DETECTADA\nA-019"
    assert regiones[0]["bbox"] == [10, 20, 120, 45]
    assert gestor.estado()["anotaciones_regiones"] == 1


def test_revision_es_reversible_y_no_borra_resultados(tmp_path):
    gestor = _gestor(tmp_path)

    quitada = gestor.actualizar_revision(
        "carpeta", "carpeta-1", estado="completada", oculto=True)
    restaurada = gestor.actualizar_revision("carpeta", "carpeta-1", oculto=False)

    assert quitada["estado"] == "completada" and quitada["oculto"] is True
    assert restaurada["estado"] == "completada" and restaurada["oculto"] is False
    assert gestor.estado_revision("carpeta", "carpeta-1") == restaurada


def test_rotacion_manual_se_memoriza_por_archivo(tmp_path):
    imagen = tmp_path / "girada.jpg"
    imagen.write_bytes(b"contenido-estable")
    gestor = _gestor(tmp_path)

    guardada = gestor.actualizar_rotacion(imagen, 90)

    assert guardada["grados"] == 90
    assert guardada["aplicar_en_siguiente_ocr"] is True
    assert gestor.rotacion_preferida(imagen) == 90
    assert gestor.estado()["rotaciones_confirmadas"] == 1
    assert next(iter(gestor.listar_rotaciones([imagen]).values()))["grados"] == 90

    gestor.actualizar_rotacion(imagen, 0)
    assert gestor.rotacion_preferida(imagen) == 0
    assert gestor.estado()["rotaciones_confirmadas"] == 0


def test_rotacion_de_cajas_conserva_su_posicion_visual():
    caja = [10, 20, 30, 40]

    assert rotar_bbox(caja, 90, 200, 100) == [40, 10, 40, 30]
    assert rotar_bbox(caja, 180, 200, 100) == [160, 40, 30, 40]
    assert rotar_bbox(caja, 270, 200, 100) == [20, 160, 40, 30]
