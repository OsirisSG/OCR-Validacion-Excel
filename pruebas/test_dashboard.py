"""Pruebas de contrato del backend del dashboard (Fase 4)."""

from urllib.parse import quote

from fastapi.testclient import TestClient

import dashboard.backend.app as backend
from dashboard.backend.app import (_aplicar_correcciones_publicas,
                                   _dimensiones_ocr_desde_archivo,
                                   _imagen_transformada, _orientacion_base_publica,
                                   _rotar_resultado_existente, app)


cliente = TestClient(app)


def test_estado_config_y_frontend():
    estado = cliente.get("/api/estado")
    assert estado.status_code == 200
    assert estado.json()["hay_datos"] is True

    config = cliente.get("/api/config")
    assert config.status_code == 200
    assert config.json()["colores"] == {
        "verde": "#22c55e", "amarillo": "#f59e0b", "rojo": "#ef4444"
    }

    portada = cliente.get("/")
    assert portada.status_code == 200
    assert "Validación de pruebas" in portada.text

    capacidad = cliente.get("/api/pipeline/capacidad")
    assert capacidad.status_code == 200
    assert isinstance(capacidad.json()["listo"], bool)

    ejecucion = cliente.get("/api/pipeline/estado")
    assert ejecucion.status_code == 200
    assert ejecucion.json()["estado"] in {"inactivo", "procesando", "pausado", "completado", "error"}
    assert {"porcentaje", "procesadas", "total", "restantes", "eta_segundos",
            "transcurrido_segundos", "resultados_parciales"} <= set(ejecucion.json())

    aprendizaje = cliente.get("/api/aprendizaje")
    assert aprendizaje.status_code == 200
    assert isinstance(aprendizaje.json()["correcciones"], int)
    assert aprendizaje.json()["almacenamiento"]["base_datos"].endswith(
        ".aprendizaje/aprendizaje.sqlite3")


def test_pipeline_rechaza_rutas_invalidas_o_demasiado_amplias():
    inexistente = cliente.post("/api/pipeline", json={"ruta": "/ruta/que/no/existe"})
    assert inexistente.status_code == 400

    raiz_sistema = cliente.post("/api/pipeline", json={"ruta": "/"})
    assert raiz_sistema.status_code == 400


def test_resumen_cuadra_con_el_total():
    datos = cliente.get("/api/resumen").json()
    assert datos["total_carpetas"] == sum(datos["semaforo"].values())
    assert round(sum(datos["pct"].values()), 1) == 100.0
    assert set(datos["distribucion_por_lote"]) == {"Lote_Pruebas"}
    raiz_normalizada = str(datos["raiz"]).replace("\\", "/")
    assert raiz_normalizada.endswith("datos_prueba/Lote_Pruebas")


def test_busqueda_filtro_y_paginacion():
    busqueda = cliente.get("/api/pruebas", params={"q": "B7"}).json()
    assert busqueda["total"] == 2

    rojas = cliente.get("/api/pruebas", params={"estado": "rojo"}).json()
    assert rojas["total"] >= 2
    assert all(fila["semaforo"] == "rojo" for fila in rojas["items"])
    assert any(fila["origen"] == "externa" for fila in rojas["items"])

    pagina = cliente.get("/api/pruebas", params={"limit": 2, "offset": 2}).json()
    assert pagina["total"] >= 14
    assert len(pagina["items"]) == 2
    assert all(len(fila["id"]) == 16 for fila in pagina["items"])


def test_detalle_e_imagen_portable_y_restringida():
    fila = cliente.get("/api/pruebas", params={"q": "01_A1_variante2"}).json()["items"][0]
    detalle = cliente.get(f"/api/pruebas/{fila['id']}")
    assert detalle.status_code == 200
    ruta_normalizada = str(detalle.json()["ruta_mostrada"]).replace("\\", "/")
    assert ruta_normalizada.endswith("Lote_Pruebas/01_A1_variante2")
    etiqueta = detalle.json()["etiqueta"]
    assert etiqueta["ruta_api"].startswith("/api/imagen?ruta=")

    imagen = cliente.get(etiqueta["ruta_api"])
    assert imagen.status_code == 200
    assert imagen.headers["content-type"].startswith("image/")

    ajena = cliente.get(f"/api/imagen?ruta={quote('/etc/passwd', safe='')}")
    assert ajena.status_code == 403

    correccion_identica = cliente.post("/api/aprendizaje/correcciones", json={
        "prueba_id": fila["id"], "campo": "etiqueta",
        "texto_ocr": etiqueta["resultado_ocr"]["tokens"][0]["texto"],
        "texto_correcto": etiqueta["resultado_ocr"]["tokens"][0]["texto"],
    })
    # En una base local persistente la revisión puede haberse completado antes;
    # ambos estados rechazan correctamente la escritura inválida.
    assert correccion_identica.status_code in {400, 409}

    fuera = cliente.post("/api/aprendizaje/regiones", json={
        "prueba_id": fila["id"], "imagen_id": detalle.json()["imagenes"][0]["id"],
        "bbox": [0, 0, 99999, 99999], "texto_correcto": "TEXTO OMITIDO",
    })
    assert fuera.status_code in {400, 409}


def test_banco_externo_es_visible_y_restringido():
    respuesta = cliente.get("/api/externas")
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["casos"] >= 4
    assert 0 <= datos["exactitud_ocr_bruta"] <= datos["exactitud"] <= 1
    assert len(datos["resultados"]) == datos["casos"]
    assert all(item["ruta_api"].startswith("/api/externas/imagen/")
               for item in datos["resultados"])
    assert all("ruta" not in item for item in datos["resultados"])
    assert all("revision" in item and "correcciones" in item and "anotaciones" in item
               for item in datos["resultados"])

    imagen = cliente.get(datos["resultados"][0]["ruta_api"])
    assert imagen.status_code == 200
    assert imagen.headers["content-type"].startswith("image/")

    ajena = cliente.get("/api/externas/imagen/no-permitida.jpg")
    assert ajena.status_code == 403

    exacta = next(item for item in datos["resultados"] if item["coincidencia_exacta"])
    token_datos = exacta["tokens"][0]
    token = token_datos.get("texto_original") or token_datos["texto"]
    correccion_identica = cliente.post("/api/externas/correcciones", json={
        "prueba_id": exacta["id"], "texto_ocr": token,
        "texto_correcto": token,
    })
    assert correccion_identica.status_code == 400


def test_region_externa_se_guarda_como_aprendizaje_y_actualiza_excel(
        monkeypatch, tmp_path):
    import cv2
    import numpy as np
    import pruebas_externas
    from aprendizaje import GestorAprendizaje

    imagen = tmp_path / "compleja.png"
    assert cv2.imwrite(str(imagen), np.zeros((60, 120, 3), dtype=np.uint8))
    fila = {
        "id": "externa-compleja", "imagen": imagen.name, "ruta": str(imagen),
        "tipo": "codigo", "esperado": "A3000", "coincidencia_exacta": False,
        "tokens": [], "lineas_texto": [], "dimensiones": [120, 60],
    }
    config = {"aprendizaje": {
        "activar": True, "directorio": str(tmp_path / "aprendizaje")}}
    monkeypatch.setattr(backend, "CONFIG", config)
    monkeypatch.setattr(pruebas_externas, "cargar", lambda _config: {"resultados": [fila]})
    monkeypatch.setattr(
        pruebas_externas, "rutas", lambda _config: (tmp_path, tmp_path / "resultados.json"))
    monkeypatch.setattr(
        backend, "_regenerar_excel",
        lambda resultado: resultado.update({"excel_actualizado": str(tmp_path / "salida.xlsx")}))

    resultado = backend.anotar_region_externa(backend.SolicitudRegionExterna(
        prueba_id=fila["id"], bbox=[10, 12, 50, 20], texto_correcto="A3000"))

    assert resultado["registrada"] is True
    assert resultado["excel_actualizado"].endswith("salida.xlsx")
    anotaciones = GestorAprendizaje(config).listar_anotaciones(
        [imagen], carpeta_id=fila["id"])
    assert anotaciones[0]["texto_correcto"] == "A3000"
    assert anotaciones[0]["bbox"] == [10, 12, 50, 20]


def test_vista_orientada_rota_y_rechaza_archivo_corrupto(tmp_path):
    import cv2
    import numpy as np

    original = np.zeros((20, 40, 3), dtype=np.uint8)
    original[:, :10] = (255, 255, 255)
    ruta = tmp_path / "rectangulo.png"
    assert cv2.imwrite(str(ruta), original)

    respuesta = _imagen_transformada(ruta, rotacion=90)
    decodificada = cv2.imdecode(np.frombuffer(respuesta.body, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decodificada.shape[:2] == (40, 20)

    corrupta = tmp_path / "corrupta.jpg"
    corrupta.write_bytes(b"no-es-imagen")
    try:
        _imagen_transformada(corrupta)
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 422
    else:
        raise AssertionError("La imagen corrupta debió rechazarse")


def test_giro_inmediato_actualiza_cajas_y_dimensiones_ocr():
    ocr = {
        "dimensiones": [200, 100], "rotacion_manual_aplicada_grados": 0,
        "tokens": [{"texto": "ABC", "bbox": [10, 20, 30, 40]}],
        "lineas_texto": [], "orientacion_texto_grados": 0,
    }

    giro = _rotar_resultado_existente(ocr, 90)

    assert giro["delta"] == 90
    assert ocr["dimensiones"] == [100, 200]
    assert ocr["tokens"][0]["bbox"] == [40, 10, 40, 30]
    assert ocr["rotacion_manual_aplicada_grados"] == 90


def test_giro_recupera_dimensiones_de_imagen_si_el_ocr_no_las_guardo(tmp_path):
    import cv2
    import numpy as np

    ruta = tmp_path / "antigua.png"
    assert cv2.imwrite(str(ruta), np.zeros((100, 200, 3), dtype=np.uint8))
    ocr = {"tokens": [{"texto": "ABC", "bbox": [10, 20, 30, 40]}]}

    dimensiones = _dimensiones_ocr_desde_archivo(ruta, ocr)
    giro = _rotar_resultado_existente(ocr, 90, dimensiones)

    assert dimensiones == (200, 100)
    assert giro["delta"] == 90
    assert ocr["dimensiones"] == [100, 200]


def test_correccion_publica_reemplaza_texto_y_conserva_original():
    ocr = {
        "texto_completo": "ETQ-2O24",
        "lineas_texto": [{"texto": "ETQ-2O24", "bbox": [1, 2, 80, 20]}],
        "tokens": [],
    }
    corregido = _aplicar_correcciones_publicas(ocr, [{
        "texto_ocr": "ETQ-2O24", "texto_correcto": "ETQ-2024",
        "bbox": [1, 2, 80, 20],
    }])

    assert corregido["texto_completo"] == "ETQ-2024"
    assert corregido["lineas_texto"][0]["texto"] == "ETQ-2024"
    assert corregido["lineas_texto"][0]["texto_original"] == "ETQ-2O24"
    assert corregido["lineas_texto"][0]["confirmado_manualmente"] is True


def test_recupera_orientacion_automatica_de_resultado_anterior():
    assert _orientacion_base_publica({"orientacion_texto_grados": 180.0}) == 180
    assert _orientacion_base_publica({
        "orientacion_texto_grados": 270.0,
        "rotacion_manual_aplicada_grados": 90,
    }) == 180


def test_listado_unificado_tiene_cuatro_estados_y_enlace_de_detalle_externo():
    listado = cliente.get("/api/pruebas", params={"incluir_ocultos": True}).json()
    externa = next(item for item in listado["items"] if item["origen"] == "externa")
    assert externa["enlace"] == f"#/externas/{externa['id']}"
    for estado in ("por_revisar", "parcial", "casi_listo", "completada"):
        respuesta = cliente.get("/api/pruebas", params={"estado": estado})
        assert respuesta.status_code == 200
