"""Pruebas de contrato del backend del dashboard (Fase 4)."""

from copy import deepcopy
import json
import threading
import time
from pathlib import Path

from urllib.parse import quote

from fastapi.testclient import TestClient

import dashboard.backend.app as backend
from dashboard.backend.app import (_aplicar_correcciones_publicas,
                                   _dimensiones_ocr_desde_archivo,
                                   _imagen_transformada, _orientacion_base_publica,
                                   _rotar_resultado_existente, app)
from aprendizaje import dimensiones_rotadas


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
    assert ejecucion.json()["estado"] in {
        "inactivo", "procesando", "pausado", "cancelando", "detenido_con_avance",
        "completado", "cancelada", "error"}
    assert {"porcentaje", "procesadas", "total", "restantes", "eta_segundos",
            "transcurrido_segundos", "resultados_parciales"} <= set(ejecucion.json())

    aprendizaje = cliente.get("/api/aprendizaje")
    assert aprendizaje.status_code == 200
    assert isinstance(aprendizaje.json()["correcciones"], int)
    assert aprendizaje.json()["almacenamiento"]["base_datos"].endswith(
        ".aprendizaje/aprendizaje.sqlite3")

    frontend = (backend.RAIZ_PROYECTO / "dashboard" / "frontend" / "app.js").read_text(
        encoding="utf-8")
    assert "Zoom de vista · rueda o botones" in frontend
    assert "Ajustar a pantalla" in frontend
    assert "onDoubleClick" in frontend and "onWheel" in frontend
    assert "Zoom OCR · mejora la lectura" in frontend
    assert "Ángulo manual" in frontend
    assert "Vista previa en tiempo real" in frontend
    assert "giroPrevisualizado" in frontend
    assert "Registrar otra plantilla Excel" in frontend
    assert "Identificadores de carpeta" in frontend
    assert "Imagen sin datos de texto" in frontend
    assert "Detener al finalizar la carpeta/ID actual" in frontend
    assert "Cancelar y conservar avance" in frontend
    assert "onPointerMove" in frontend and "scrollLeft" in frontend
    assert "onClick=${() => cambiarImagen(imagen.id, true)}" in frontend
    assert "Previsualización de la corrección" in frontend
    assert "Restablecer zoom" in frontend
    assert "mini-visor-marco" in frontend and "onWheel=${alRueda}" in frontend
    assert "Abrir Excel parcial" in frontend
    assert "miniatura-imagen-lista" in frontend
    assert "imagenesDetalle.map((imagen)" in frontend
    assert "visor-imagen-${imagen.id}" in frontend
    assert 'id="ruta-plantilla"' not in frontend
    assert 'id="ruta-inventario"' not in frontend


def test_pipeline_rechaza_rutas_invalidas_o_demasiado_amplias():
    inexistente = cliente.post("/api/pipeline", json={"ruta": "/ruta/que/no/existe"})
    assert inexistente.status_code == 400

    raiz_sistema = cliente.post("/api/pipeline", json={"ruta": "/"})
    assert raiz_sistema.status_code == 400


def test_checkpoint_persistido_recupera_avance_y_separa_pausa_de_error(
        monkeypatch, tmp_path):
    checkpoint = tmp_path / "estado_pipeline.json"
    original = deepcopy(backend._pipeline_estado)
    hilo_original = backend._pipeline_hilo

    class HiloVivo:
        @staticmethod
        def is_alive():
            return True

    monkeypatch.setattr(backend, "RUTA_CHECKPOINT_PIPELINE", checkpoint)
    try:
        backend._pipeline_hilo = HiloVivo()
        backend._pipeline_estado.update({
            "estado": "procesando", "ultimo_id": "abc", "ultimo_id_nombre": "ID 15",
            "resultados_parciales": [{"id": "abc", "nombre": "ID 15"}],
            "solicitud": {"ruta": str(tmp_path)}, "error": None,
        })
        pausa = backend.pausar_pipeline()
        assert pausa["estado"] == "pausado"
        assert backend._pipeline_estado["reanudable"] is True
        guardado = json.loads(checkpoint.read_text(encoding="utf-8"))
        assert guardado["ultimo_id_nombre"] == "ID 15"
        assert guardado["resultados_parciales"][0]["id"] == "abc"

        reanudado = backend.reanudar_pipeline()
        assert reanudado["estado"] == "procesando"
        assert backend._pipeline_estado["error"] is None
    finally:
        backend._pipeline_estado.clear()
        backend._pipeline_estado.update(original)
        backend._pipeline_hilo = hilo_original
        backend._pipeline_continuar.set()
        backend._pipeline_cancelar.clear()
        backend._pipeline_detener_fin_id.clear()


def test_cancelacion_ofrece_fin_de_id_y_conserva_checkpoint(monkeypatch, tmp_path):
    checkpoint = tmp_path / "estado_pipeline.json"
    original = deepcopy(backend._pipeline_estado)
    monkeypatch.setattr(backend, "RUTA_CHECKPOINT_PIPELINE", checkpoint)
    try:
        backend._pipeline_estado.update({"estado": "procesando", "error": None})
        resultado = backend.cancelar_pipeline(backend.SolicitudDetencion(accion="fin_id"))
        assert resultado == {"estado": "cancelando", "seguro": True, "accion": "fin_id"}
        assert backend._pipeline_detener_fin_id.is_set()
        assert json.loads(checkpoint.read_text(encoding="utf-8"))["reanudable"] is True
    finally:
        backend._pipeline_estado.clear()
        backend._pipeline_estado.update(original)
        backend._pipeline_continuar.set()
        backend._pipeline_cancelar.clear()
        backend._pipeline_detener_fin_id.clear()


def _preparar_excel_parcial(monkeypatch, tmp_path):
    import generar_excel

    raiz = tmp_path / "lote"
    raiz.mkdir()
    avances = tmp_path / ".cache_ocr" / "avances_ids.json"
    avances.parent.mkdir()
    avances.write_text(json.dumps({"raiz": str(raiz), "avances_ids": {
        "ID-activo": {"estado": "procesando", "fila_parcial": {
            "case_key": "ID-activo", "nombre": "ID activo", "ruta": str(raiz / "ID-activo"),
            "perfil": "empresarial", "comparacion": {"resultado": "coincidencia_parcial"},
            "imagenes": [], "campos": {}, "progreso": {"revisadas": 1},
        }}}}), encoding="utf-8")
    validacion = tmp_path / "validacion_resultados.json"
    validacion.write_text(json.dumps({"resultados": [{
        "case_key": "ID-listo", "nombre": "ID listo", "ruta": str(raiz / "ID-listo"),
        "perfil": "empresarial", "comparacion": {"resultado": "coincidencia_total"},
        "imagenes": [], "campos": {},
    }]}), encoding="utf-8")
    capturado = {}

    def excel_falso(ruta_json, ruta_salida, *_args, **_kwargs):
        capturado["datos"] = _kwargs.get("datos_validacion") or json.loads(
            Path(ruta_json).read_text(encoding="utf-8"))
        Path(ruta_salida).write_bytes(b"excel-parcial")
        return Path(ruta_salida)

    monkeypatch.setattr(backend, "RAIZ_PROYECTO", tmp_path)
    monkeypatch.setattr(backend, "RUTA_VALIDACION", validacion)
    monkeypatch.setattr(backend, "RUTA_CHECKPOINT_PIPELINE",
                        tmp_path / ".cache_ocr" / "estado_pipeline.json")
    monkeypatch.setattr(backend, "CONFIG", {
        "empresarial": {"archivo_avance_ids": str(avances)},
        "fase3": {"archivo_salida": "resultado_maestro.xlsx"},
    })
    monkeypatch.setattr(generar_excel, "generar_excel", excel_falso)
    backend._pipeline_estado.update({
        "estado": "pausado", "ruta": str(raiz), "nombre_excel": "auditoria.xlsx",
        "ruta_plantilla": None, "excel_parcial_pendiente": True,
        "archivo_excel_parcial": None, "advertencia_excel_parcial": None,
        "resultados_parciales": [
            {"case_key": "ID-listo", "estado": "procesada"},
            {"case_key": "ID-activo", "estado": "procesando"},
        ],
    })
    return capturado


def test_pausa_exporta_excel_parcial_y_continua_desde_checkpoint(monkeypatch, tmp_path):
    original = deepcopy(backend._pipeline_estado)
    capturado = _preparar_excel_parcial(monkeypatch, tmp_path)
    backend._pipeline_cancelar.clear()
    backend._pipeline_continuar.clear()
    terminado = threading.Event()

    def esperar():
        backend._esperar_continuacion()
        terminado.set()

    hilo = threading.Thread(target=esperar, daemon=True)
    try:
        hilo.start()
        limite = time.monotonic() + 3
        while not backend._pipeline_estado.get("archivo_excel_parcial") and time.monotonic() < limite:
            time.sleep(.01)
        assert Path(backend._pipeline_estado["archivo_excel_parcial"]).name == "auditoria_parcial.xlsx"
        assert {fila["case_key"] for fila in capturado["datos"]["resultados"]} == {
            "ID-listo", "ID-activo"}
        assert backend._pipeline_estado["estado"] == "pausado"
        backend._pipeline_continuar.set()
        hilo.join(timeout=2)
        assert terminado.is_set()
    finally:
        backend._pipeline_continuar.set()
        hilo.join(timeout=2)
        backend._pipeline_cancelar.clear()
        backend._pipeline_estado.clear()
        backend._pipeline_estado.update(original)


def test_detener_al_finalizar_id_exporta_excel_y_deja_reanudable(monkeypatch, tmp_path):
    original = deepcopy(backend._pipeline_estado)
    capturado = _preparar_excel_parcial(monkeypatch, tmp_path)
    backend._pipeline_estado.update(estado="cancelando", reanudable=True)
    backend._pipeline_cancelar.set()
    backend._pipeline_continuar.set()
    try:
        try:
            backend._esperar_continuacion()
        except backend.PipelineCancelado:
            pass
        else:
            raise AssertionError("La detención debía cerrar el ciclo de forma cooperativa")
        assert Path(backend._pipeline_estado["archivo_excel_parcial"]).is_file()
        assert capturado["datos"]["parcial"] is True
        assert backend._pipeline_estado["reanudable"] is True
    finally:
        backend._pipeline_cancelar.clear()
        backend._pipeline_continuar.set()
        backend._pipeline_estado.clear()
        backend._pipeline_estado.update(original)


def test_reanudacion_omite_ids_ya_confirmados_y_conserva_su_lista(monkeypatch, tmp_path):
    checkpoint = tmp_path / "estado_pipeline.json"
    original = deepcopy(backend._pipeline_estado)
    hilo_original = backend._pipeline_hilo
    recibida = {}

    def iniciar_falso(solicitud):
        recibida.update(solicitud.model_dump())
        backend._pipeline_estado.update({"estado": "procesando", "resultados_parciales": []})
        return {"aceptado": True, "estado": "procesando"}

    monkeypatch.setattr(backend, "RUTA_CHECKPOINT_PIPELINE", checkpoint)
    monkeypatch.setattr(backend, "iniciar_pipeline", iniciar_falso)
    try:
        backend._pipeline_hilo = None
        backend._pipeline_estado.update({
            "estado": "detenido_con_avance", "reanudable": True,
            "solicitud": {"ruta": str(tmp_path), "modo_ejecucion": "completo"},
            "ultimo_id": "id-publico", "ultimo_id_nombre": "Caso 15",
            "resultados_parciales": [{
                "id": "id-publico", "nombre": "Caso 15", "case_key": "caso-15",
                "ruta": str(tmp_path / "caso-15"), "estado": "procesada",
            }],
        })
        respuesta = backend.reanudar_pipeline()

        assert respuesta["desde_checkpoint"] is True
        assert recibida["casos_omitidos"] == ["caso-15"]
        assert backend._pipeline_estado["resultados_parciales"][0]["id"] == "id-publico"
        assert backend._pipeline_estado["ultimo_id_nombre"] == "Caso 15"
    finally:
        backend._pipeline_estado.clear()
        backend._pipeline_estado.update(original)
        backend._pipeline_hilo = hilo_original


def test_correccion_empresarial_se_refleja_y_deja_historial(monkeypatch, tmp_path):
    ruta_json = tmp_path / "validacion.json"
    fila = {
        "case_key": "Proyecto|1ST|HT/232541 RDW NOM HT",
        "nombre": "232541 RDW NOM HT", "identificador": "232541",
        "ruta": str(tmp_path / "HT" / "232541 RDW NOM HT"),
        "perfil": "empresarial", "tipo_st": "1ST",
        "comparacion": {"resultado": "coincidencia_parcial", "faltantes": ["dashboard_supplier"]},
        "campos": {"dashboard_supplier": {"valor": None, "estado": "faltante"}},
        "consolidado": {"campos": {}, "campos_faltantes": ["dashboard_supplier"],
                        "conflictos": [], "requiere_revision": True},
        "campos_faltantes": ["dashboard_supplier"], "conflictos": [],
        "requiere_revision": True, "alertas": [], "imagenes": [],
        "historial_ejecuciones": [{"estado": "procesada_con_advertencias"}],
    }
    ruta_json.write_text(json.dumps({"raiz": str(tmp_path), "perfil": "empresarial",
                                     "resultados": [fila]}), encoding="utf-8")
    monkeypatch.setattr(backend, "RUTA_VALIDACION", ruta_json)
    monkeypatch.setattr(backend, "CONFIG", {
        "aprendizaje": {"directorio": str(tmp_path / "aprendizaje")},
        "empresarial": {"base_conocimiento": str(tmp_path / "reglas.json")},
    })
    backend._cache.update({"mtime": None, "datos": None})
    import generar_excel as modulo_excel
    monkeypatch.setattr(modulo_excel, "generar_excel", lambda *args, **kwargs: tmp_path / "salida.xlsx")
    item_id = backend._id_fila(fila)
    respuesta = cliente.post(
        f"/api/casos/{item_id}/campos/dashboard_supplier",
        json={"valor": "FORVIA", "usuario": "prueba"})
    assert respuesta.status_code == 200
    guardado = json.loads(ruta_json.read_text(encoding="utf-8"))["resultados"][0]
    assert guardado["campos"]["dashboard_supplier"]["valor"] == "FORVIA"
    assert "dashboard_supplier" not in guardado["campos_faltantes"]
    assert guardado["historial_acciones"][0]["usuario"] == "prueba"
    historial = cliente.get(f"/api/casos/{item_id}/historial")
    assert historial.status_code == 200
    assert len(historial.json()["ejecuciones"]) == 1


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


def test_imagen_externa_sin_datos_persiste_como_revision_no_error(
        monkeypatch, tmp_path):
    import pruebas_externas
    from aprendizaje import GestorAprendizaje

    imagen = tmp_path / "contexto.jpg"
    imagen.write_bytes(b"foto-contexto")
    salida = tmp_path / "resultados.json"
    documento = {"resultados": [{
        "id": "externa-contexto", "imagen": imagen.name, "ruta": str(imagen),
        "tipo": "codigo", "tokens": [], "lineas_texto": [],
    }]}
    config = {"aprendizaje": {
        "activar": True, "directorio": str(tmp_path / "aprendizaje")}}
    monkeypatch.setattr(backend, "CONFIG", config)
    monkeypatch.setattr(pruebas_externas, "cargar", lambda _config: documento)
    monkeypatch.setattr(pruebas_externas, "rutas", lambda _config: (tmp_path, salida))

    resultado = backend.marcar_imagen_sin_datos(backend.SolicitudImagenSinDatos(
        tipo="externa", prueba_id="externa-contexto", motivo="Sin etiqueta",
        usuario="revisor"))

    assert resultado["estado_imagen"] == "revisada_sin_datos"
    assert "sin datos" in resultado["mensaje"].lower()
    persistido = json.loads(salida.read_text(encoding="utf-8"))["resultados"][0]
    assert persistido["revision_sin_datos"]["motivo"] == "Sin etiqueta"
    assert GestorAprendizaje(config).imagen_sin_datos(imagen)["usuario"] == "revisor"


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

    libre = _imagen_transformada(ruta, rotacion=30)
    libre_decodificada = cv2.imdecode(
        np.frombuffer(libre.body, dtype=np.uint8), cv2.IMREAD_COLOR)
    ancho, alto = dimensiones_rotadas(40, 20, 30)
    assert libre_decodificada.shape[:2] == (alto, ancho)

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


def test_giro_manual_libre_reemplaza_y_restaura_orientacion_automatica():
    original = [10, 20, 30, 40]
    ocr = {
        "dimensiones": [200, 100], "rotacion_manual_aplicada_grados": 0,
        "orientacion_texto_base_grados": 180, "deskew_texto_aplicado_grados": 2.5,
        "tokens": [{"texto": "ABC123", "bbox": list(original)}], "lineas_texto": [],
        "orientacion_texto_grados": 182.5,
    }

    giro = _rotar_resultado_existente(ocr, 27.5)
    assert round(giro["delta"], 1) == 207.5
    assert ocr["orientacion_manual_prioritaria"] is True
    assert ocr["orientacion_texto_base_grados"] == 0
    assert ocr["deskew_texto_aplicado_grados"] == 0
    assert ocr["rotacion_manual_aplicada_grados"] == 27.5
    assert ocr["tokens"][0]["bbox"] != original

    _rotar_resultado_existente(ocr, 0)
    assert ocr["orientacion_manual_prioritaria"] is False
    assert ocr["orientacion_texto_base_grados"] == 180
    assert ocr["deskew_texto_aplicado_grados"] == 2.5
    assert ocr["dimensiones"] == [200, 100]
    assert ocr["tokens"][0]["bbox"] == original


def test_giro_libre_posterior_parte_del_angulo_manual_ya_aplicado():
    ocr = {
        "dimensiones_originales": [200, 100],
        "dimensiones": list(dimensiones_rotadas(200, 100, 27.5)),
        "rotacion_manual_aplicada_grados": 27.5,
        "orientacion_manual_prioritaria": True,
        "orientacion_texto_base_grados": 0,
        "tokens": [{"texto": "ABC123", "bbox": [40, 30, 60, 20]}],
        "lineas_texto": [],
    }

    giro = _rotar_resultado_existente(ocr, 40)

    assert round(giro["delta"], 1) == 12.5
    assert ocr["dimensiones"] == list(dimensiones_rotadas(200, 100, 40))
    _rotar_resultado_existente(ocr, 0)
    assert ocr["dimensiones"] == [200, 100]
    assert ocr["orientacion_manual_prioritaria"] is False


def test_giro_manual_cero_no_se_confunde_con_orientacion_automatica():
    ocr = {
        "dimensiones_originales": [200, 100], "dimensiones": [200, 100],
        "rotacion_manual_aplicada_grados": 0,
        "orientacion_texto_base_grados": 180,
        "tokens": [], "lineas_texto": [], "orientacion_texto_grados": 180,
    }

    _rotar_resultado_existente(ocr, 0, restaurar_automatico=False)

    assert ocr["orientacion_manual_prioritaria"] is True
    assert ocr["orientacion_texto_base_grados"] == 0
    assert ocr["rotacion_manual_aplicada_grados"] == 0


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
