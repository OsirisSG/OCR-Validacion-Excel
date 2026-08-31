"""Pruebas de contrato del backend del dashboard (Fase 4)."""

from urllib.parse import quote

from fastapi.testclient import TestClient

from dashboard.backend.app import app


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
    assert ejecucion.json()["estado"] in {"inactivo", "procesando", "completado", "error"}
    assert {"porcentaje", "procesadas", "total", "restantes", "eta_segundos",
            "transcurrido_segundos", "resultados_parciales"} <= set(ejecucion.json())

    aprendizaje = cliente.get("/api/aprendizaje")
    assert aprendizaje.status_code == 200
    assert isinstance(aprendizaje.json()["correcciones"], int)


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
    assert correccion_identica.status_code == 400

    fuera = cliente.post("/api/aprendizaje/regiones", json={
        "prueba_id": fila["id"], "imagen_id": detalle.json()["imagenes"][0]["id"],
        "bbox": [0, 0, 99999, 99999], "texto_correcto": "TEXTO OMITIDO",
    })
    assert fuera.status_code == 400


def test_banco_externo_es_visible_y_restringido():
    respuesta = cliente.get("/api/externas")
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["casos"] >= 4
    assert len(datos["resultados"]) == datos["casos"]
    assert all(item["ruta_api"].startswith("/api/externas/imagen/")
               for item in datos["resultados"])
    assert all("ruta" not in item for item in datos["resultados"])

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
