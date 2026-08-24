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
    assert datos["raiz"].endswith("datos_prueba/Lote_Pruebas")
    assert not datos["raiz"].startswith("C:\\")


def test_busqueda_filtro_y_paginacion():
    busqueda = cliente.get("/api/pruebas", params={"q": "B7"}).json()
    assert busqueda["total"] == 2

    rojas = cliente.get("/api/pruebas", params={"estado": "rojo"}).json()
    assert rojas["total"] == 2
    assert all(fila["semaforo"] == "rojo" for fila in rojas["items"])

    pagina = cliente.get("/api/pruebas", params={"limit": 2, "offset": 2}).json()
    assert pagina["total"] == 6
    assert len(pagina["items"]) == 2
    assert all(len(fila["id"]) == 16 for fila in pagina["items"])


def test_detalle_e_imagen_portable_y_restringida():
    fila = cliente.get("/api/pruebas", params={"q": "01_A1_variante2"}).json()["items"][0]
    detalle = cliente.get(f"/api/pruebas/{fila['id']}")
    assert detalle.status_code == 200
    assert detalle.json()["ruta_mostrada"].endswith("Lote_Pruebas/01_A1_variante2")
    etiqueta = detalle.json()["etiqueta"]
    assert etiqueta["ruta_api"].startswith("/api/imagen?ruta=")

    imagen = cliente.get(etiqueta["ruta_api"])
    assert imagen.status_code == 200
    assert imagen.headers["content-type"].startswith("image/")

    ajena = cliente.get(f"/api/imagen?ruta={quote('/etc/passwd', safe='')}")
    assert ajena.status_code == 403
