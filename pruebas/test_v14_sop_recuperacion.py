"""Contratos V14: SOP, perfiles, persistencia y recuperación segura."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from fastapi import HTTPException

import dashboard.backend.app as backend
from generar_excel import generar_excel
from gestor_recursos import GestorRecursos, PERFILES, normalizar_perfil
from ocr_engine import MotorEasyOCR
from orquestador_ocr import PreparadorImagenes
from utilidades.cola_excel import ColaExcel


def test_perfiles_v14_y_alto_predeterminado():
    assert normalizar_perfil(None) == "alto"
    assert normalizar_perfil("Máximo") == "maximo"
    assert PERFILES["estable"]["vram_limite"] == 75
    assert PERFILES["alto"]["vram_limite"] == 85
    assert PERFILES["maximo"]["vram_limite"] == 90
    assert PERFILES["estable"]["cola_max"] < PERFILES["alto"]["cola_max"] < PERFILES["maximo"]["cola_max"]


def test_gestor_registra_rendimiento_sin_inventar_gpu():
    gestor = GestorRecursos("alto")
    gestor.actualizar_batch(6)
    gestor.actualizar_cola(3, 2 * 1024 * 1024, workers_activos=2)
    gestor.registrar_etapa("inferencia_gpu", 0.25)
    gestor.registrar_completada(2)
    snap = gestor.snapshot(forzar=True)
    assert snap["perfil"] == "alto"
    assert snap["batch_actual"] == 6
    assert snap["cola_pendiente"] == 3
    assert snap["cola_mb"] == 2.0
    assert snap["imagenes_por_minuto"] >= 0
    assert "gpu_porcentaje" in snap and "vram_porcentaje" in snap


def test_prefetch_cpu_es_acotado_y_recupera_resultado(tmp_path, monkeypatch):
    rutas = []
    for indice in range(2):
        ruta = tmp_path / f"{indice}.jpg"
        ruta.write_bytes(b"x" * 128)
        rutas.append(ruta)
    # V15.9.3: la prueba ejercita el ACOTADO DE COLA (max_pendientes) y el
    # backpressure, no la carga real del sistema: bajo una suite completa el
    # gestor de recursos podía ver CPU/RAM presionados y el primer preparar
    # devolvía False de forma no determinista. Se aíslan las sondas de presión.
    import gestor_recursos
    monkeypatch.setattr(gestor_recursos.GestorRecursos, "cpu_bajo_presion",
                        lambda self: False)
    monkeypatch.setattr(gestor_recursos.GestorRecursos, "ram_bajo_presion",
                        lambda self: False)
    preparador = PreparadorImagenes(lambda ruta: f"preparada:{Path(ruta).name}", workers=1, max_pendientes=1)
    try:
        assert preparador.preparar(rutas[0]) is True
        # La cola cuenta trabajos hasta que el consumidor los retire, aunque el worker ya haya terminado.
        assert preparador.preparar(rutas[1]) is False
        assert preparador.obtener(rutas[0]) == "preparada:0.jpg"
        assert preparador.preparar(rutas[1]) is True
        assert preparador.obtener(rutas[1]) == "preparada:1.jpg"
    finally:
        preparador.cerrar(cancelar=True)


def test_cola_excel_idempotente_por_actualizacion(tmp_path):
    cola = ColaExcel(tmp_path / "cola.sqlite3", lambda: tmp_path / "maestro.xlsx")
    primera = cola.solicitar("correccion-123")
    segunda = cola.solicitar("correccion-123")
    assert primera == segunda == 1
    assert cola.estado()["pendientes"] == 1
    assert cola.procesar() is True
    assert cola.estado()["pendientes"] == 0


def test_cola_excel_none_se_clasifica_como_datos_y_no_pierde_pendiente(tmp_path):
    cola = ColaExcel(tmp_path / "cola.sqlite3", lambda: None)
    cola.solicitar("correccion-none")
    assert cola.procesar() is False
    estado = cola.estado()
    assert estado["pendientes"] == 1
    assert estado["error_tipo"] == "datos_invalidos"
    assert "devolvió None" in estado["error"]
    assert "Traceback" in estado["traceback"]


def test_generar_excel_rechaza_resultados_none_con_error_explicito(tmp_path):
    with pytest.raises(ValueError, match="resultados.*None"):
        generar_excel(
            ruta_salida=tmp_path / "salida.xlsx",
            config={"fase3": {}},
            reglas={},
            datos_validacion={"resultados": None},
        )


class _ReaderOOMMinimo:
    def readtext(self, *_args, **_kwargs):
        raise RuntimeError("CUDA out of memory")


def test_oom_en_batch_minimo_deriva_solo_tarea_y_conserva_cuda():
    motor = MotorEasyOCR.__new__(MotorEasyOCR)
    motor._reader = _ReaderOOMMinimo()
    motor._allowlist = None
    motor._batch_size = 1
    motor._batch_max = 4
    motor._workers = 0
    motor._reintentos_oom = 2
    motor.dispositivo = "cuda"
    motor.advertencias = []
    motor._limpiar_cache_cuda = lambda: None
    motor._leer_cpu_temporal = lambda imagen, opciones, causa: [
        ([[0, 0], [10, 0], [10, 5], [0, 5]], "CPU-TEMP", .8)
    ]

    lineas = motor._leer(object(), usar_allowlist=False)

    assert motor.dispositivo == "cuda"
    assert motor._batch_size == 1
    assert lineas[0]["texto"] == "CPU-TEMP"


class _HiloFalso:
    def __init__(self, *args, **kwargs):
        self.started = False
        self.kwargs = kwargs

    def start(self):
        self.started = True

    def is_alive(self):
        return False


class _HiloVivo:
    @staticmethod
    def is_alive():
        return True


def test_estado_cancelando_obsoleto_no_bloquea_nueva_ejecucion(monkeypatch, tmp_path):
    original_estado = deepcopy(backend._pipeline_estado)
    original_hilo = backend._pipeline_hilo
    lote = tmp_path / "lote"
    lote.mkdir()
    creados = []

    def hilo_falso(*args, **kwargs):
        hilo = _HiloFalso(*args, **kwargs)
        creados.append(hilo)
        return hilo

    monkeypatch.setattr(backend, "_capacidad_pipeline", lambda: {
        "listo": True, "faltantes": [], "motores": {"easyocr": True}, "recursos": {}
    })
    monkeypatch.setattr(backend, "_persistir_checkpoint_pipeline", lambda: None)
    monkeypatch.setattr(backend.threading, "Thread", hilo_falso)
    try:
        backend._pipeline_hilo = None
        backend._pipeline_estado.update(estado="cancelando", ejecucion_id="anterior")
        respuesta = backend.iniciar_pipeline(backend.SolicitudPipeline(ruta=str(lote)))
        assert respuesta["aceptado"] is True
        assert backend._pipeline_estado["estado"] == "procesando"
        assert backend._pipeline_estado["perfil_rendimiento"] == "alto"
        assert creados and creados[0].started is True
    finally:
        backend._pipeline_estado.clear()
        backend._pipeline_estado.update(original_estado)
        backend._pipeline_hilo = original_hilo
        backend._pipeline_cancelar.clear()
        backend._pipeline_continuar.set()
        backend._pipeline_detener_fin_id.clear()


def test_hilo_anterior_realmente_vivo_impide_segundo_propietario_cuda(monkeypatch, tmp_path):
    original_estado = deepcopy(backend._pipeline_estado)
    original_hilo = backend._pipeline_hilo
    lote = tmp_path / "lote"
    lote.mkdir()
    monkeypatch.setattr(backend, "_capacidad_pipeline", lambda: {
        "listo": True, "faltantes": [], "motores": {"easyocr": True}, "recursos": {}
    })
    try:
        backend._pipeline_hilo = _HiloVivo()
        backend._pipeline_estado.update(estado="cancelada")
        with pytest.raises(HTTPException) as exc:
            backend.iniciar_pipeline(backend.SolicitudPipeline(ruta=str(lote), perfil_rendimiento="maximo"))
        assert exc.value.status_code == 409
        assert "todavía está cerrando recursos" in str(exc.value.detail)
    finally:
        backend._pipeline_estado.clear()
        backend._pipeline_estado.update(original_estado)
        backend._pipeline_hilo = original_hilo


def test_reloj_pipeline_excluye_tiempo_en_pausa():
    original_estado = deepcopy(backend._pipeline_estado)
    try:
        with backend._pipeline_lock:
            backend._pipeline_estado.update(
                estado="procesando",
                transcurrido_base_segundos=10.0,
                transcurrido_segundos=10.0,
                segmento_activo_iniciado_en="2026-09-23T08:00:00.000",
                pausado_en=None,
            )
            t_activo = backend._tiempo_activo_pipeline_locked(
                backend.datetime.fromisoformat("2026-09-23T08:00:05.000"))
            assert t_activo == 15.0
            backend._congelar_tiempo_pipeline_locked(
                backend.datetime.fromisoformat("2026-09-23T08:00:05.000"))
            backend._pipeline_estado["estado"] = "pausado"
            assert backend._tiempo_activo_pipeline_locked(
                backend.datetime.fromisoformat("2026-09-23T08:10:05.000")) == 15.0
            backend._reanudar_tiempo_pipeline_locked(
                backend.datetime.fromisoformat("2026-09-23T08:10:05.000"))
            backend._pipeline_estado["estado"] = "procesando"
            assert backend._tiempo_activo_pipeline_locked(
                backend.datetime.fromisoformat("2026-09-23T08:10:08.000")) == 18.0
    finally:
        with backend._pipeline_lock:
            backend._pipeline_estado.clear()
            backend._pipeline_estado.update(original_estado)


def test_reubicar_ruta_relativa_bajo_raiz_del_lote(tmp_path):
    raiz = tmp_path / "1st"
    imagen = raiz / "PHOTOS" / "NACH" / "IMG_4144.JPG"
    imagen.parent.mkdir(parents=True)
    imagen.write_bytes(b"jpg")
    datos = {"raiz": str(raiz), "resultados": []}
    assert backend._reubicar_ruta("PHOTOS/NACH/IMG_4144.JPG", datos, raiz) == imagen.resolve()


def test_generar_excel_tolera_colecciones_opcionales_none(tmp_path):
    from configuracion import cargar_config, cargar_reglas
    config = deepcopy(cargar_config())
    config.setdefault("fase3", {}).setdefault("reporte_bmg", {})["activar"] = False
    datos = {
        "perfil": "generico",
        "raiz": str(tmp_path),
        "resultados": [{
            "ruta": str(tmp_path / "caso"),
            "nombre": "caso",
            "identificador": "caso",
            "comparacion": {"resultado": "sin_procesar"},
            "imagenes": None,
            "observaciones": None,
            "tipos_archivo": None,
            "etiqueta": {"resultado_ocr": {"tokens": None}},
            "referencia": {"resultado_ocr": {"tokens": None}},
            "confianza_ocr_pct": None,
        }],
    }
    salida = generar_excel(
        ruta_salida=tmp_path / "none-opcionales.xlsx",
        config=config,
        reglas=cargar_reglas(),
        datos_validacion=datos,
    )
    assert Path(salida).is_file()


def test_pausa_se_publica_solo_al_llegar_a_punto_seguro(monkeypatch):
    import threading
    import time

    original_estado = deepcopy(backend._pipeline_estado)
    original_continuar = backend._pipeline_continuar.is_set()
    monkeypatch.setattr(backend, "_persistir_checkpoint_pipeline", lambda: True)
    monkeypatch.setattr(backend, "_exportar_excel_parcial_pipeline", lambda: None)
    try:
        with backend._pipeline_lock:
            backend._pipeline_estado.update(
                estado="procesando",
                transcurrido_base_segundos=0.0,
                transcurrido_segundos=0.0,
                segmento_activo_iniciado_en=backend.datetime.now().isoformat(timespec="milliseconds"),
                pausado_en=None,
            )
        respuesta = backend.pausar_pipeline()
        assert respuesta["estado"] == "pausando"
        assert backend._pipeline_estado["estado"] == "pausando"

        hilo = threading.Thread(target=backend._esperar_continuacion)
        hilo.start()
        limite = time.time() + 1.0
        while time.time() < limite and backend._pipeline_estado["estado"] != "pausado":
            time.sleep(0.01)
        assert backend._pipeline_estado["estado"] == "pausado"
        congelado = backend._pipeline_estado["transcurrido_segundos"]
        time.sleep(0.05)
        with backend._pipeline_lock:
            assert backend._tiempo_activo_pipeline_locked() == congelado
        backend._pipeline_continuar.set()
        hilo.join(1.0)
        assert not hilo.is_alive()
    finally:
        with backend._pipeline_lock:
            backend._pipeline_estado.clear()
            backend._pipeline_estado.update(original_estado)
        if original_continuar:
            backend._pipeline_continuar.set()
        else:
            backend._pipeline_continuar.clear()


def test_telemetria_gpu_usa_nvidia_smi_si_nvml_no_esta(monkeypatch):
    import sys
    import types
    import gestor_recursos as modulo_recursos

    class CudaFalsa:
        @staticmethod
        def is_available(): return True
        @staticmethod
        def current_device(): return 0
        @staticmethod
        def mem_get_info(_indice): return (1 * 1024**3, 6 * 1024**3)
        @staticmethod
        def memory_reserved(_indice): return 4 * 1024**3

    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=CudaFalsa()))
    monkeypatch.setitem(sys.modules, "pynvml", None)
    monkeypatch.setattr(modulo_recursos.shutil, "which", lambda nombre: "nvidia-smi.exe")
    monkeypatch.setattr(modulo_recursos.subprocess, "check_output", lambda *a, **k: "73\n")

    snap = GestorRecursos("maximo").snapshot(forzar=True)
    assert snap["gpu_porcentaje"] == 73.0
    assert snap["gpu_fuente"] == "nvidia-smi"
    assert round(snap["vram_porcentaje"], 1) == 83.3
