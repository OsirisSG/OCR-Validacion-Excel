"""Pruebas del escritor común, incluyendo bloqueos típicos de Windows."""

import json
import os
import threading
import time

import pytest

from utilidades.persistencia import AdvertenciaPersistencia, escribir_json_seguro


def test_reintenta_permission_error_y_reemplaza_atomico(monkeypatch, tmp_path):
    destino = tmp_path / ".cache_ocr" / "estado.json"
    destino.parent.mkdir()
    destino.write_text('{"version":"anterior"}', encoding="utf-8")
    reemplazar_real = os.replace
    llamadas = []

    def reemplazar_temporal(origen, final):
        llamadas.append((origen, final))
        if len(llamadas) < 4:
            raise PermissionError(13, "archivo ocupado")
        reemplazar_real(origen, final)

    monkeypatch.setattr("utilidades.persistencia.os.replace", reemplazar_temporal)
    resultado = escribir_json_seguro(
        destino, {"version": "nueva", "completo": True}, espera_inicial=0)

    assert resultado.guardado is True
    assert resultado.intentos == 4
    assert json.loads(destino.read_text(encoding="utf-8")) == {
        "version": "nueva", "completo": True}
    assert not list(destino.parent.glob("*.tmp"))


def test_bloqueo_permanente_conserva_checkpoint_valido(monkeypatch, tmp_path):
    destino = tmp_path / ".cache_ocr" / "avances_ids.json"
    destino.parent.mkdir()
    anterior = {"avances_ids": {"ID-1": {"imagenes": ["lista.jpg"]}}}
    destino.write_text(json.dumps(anterior), encoding="utf-8")

    def siempre_ocupado(_origen, _final):
        raise PermissionError(13, "archivo ocupado por antivirus")

    monkeypatch.setattr("utilidades.persistencia.os.replace", siempre_ocupado)
    with pytest.warns(AdvertenciaPersistencia, match="última versión válida"):
        resultado = escribir_json_seguro(
            destino, {"avances_ids": {"ID-2": {}}}, intentos=3, espera_inicial=0)

    assert resultado.guardado is False
    assert json.loads(destino.read_text(encoding="utf-8")) == anterior
    assert not list(destino.parent.glob("*.tmp"))


def test_rlock_serializa_escrituras_concurrentes_del_mismo_json(monkeypatch, tmp_path):
    destino = tmp_path / ".cache_ocr" / "estado_pipeline.json"
    reemplazar_real = os.replace
    estado = {"activas": 0, "maximas": 0}
    guarda = threading.Lock()

    def reemplazo_lento(origen, final):
        with guarda:
            estado["activas"] += 1
            estado["maximas"] = max(estado["maximas"], estado["activas"])
        try:
            time.sleep(.01)
            reemplazar_real(origen, final)
        finally:
            with guarda:
                estado["activas"] -= 1

    monkeypatch.setattr("utilidades.persistencia.os.replace", reemplazo_lento)
    hilos = [threading.Thread(target=escribir_json_seguro,
                              args=(destino, {"escritor": numero}))
             for numero in range(4)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join(timeout=2)

    assert all(not hilo.is_alive() for hilo in hilos)
    assert estado["maximas"] == 1
    assert json.loads(destino.read_text(encoding="utf-8"))["escritor"] in range(4)
    assert not list(destino.parent.glob("*.tmp"))


def test_error_checkpoint_no_convierte_el_pipeline_en_error(monkeypatch, tmp_path):
    import dashboard.backend.app as backend

    destino = tmp_path / ".cache_ocr" / "estado_pipeline.json"
    destino.parent.mkdir()
    anterior = {"estado": "pausado", "ultimo_id": "ID-anterior"}
    destino.write_text(json.dumps(anterior), encoding="utf-8")
    estado_original = dict(backend._pipeline_estado)
    monkeypatch.setattr(backend, "RUTA_CHECKPOINT_PIPELINE", destino)
    monkeypatch.setattr("utilidades.persistencia.time.sleep", lambda _segundos: None)
    monkeypatch.setattr(
        "utilidades.persistencia.os.replace",
        lambda _origen, _destino: (_ for _ in ()).throw(PermissionError("ocupado")))
    try:
        backend._pipeline_estado.update(
            estado="procesando", ultimo_id="ID-nuevo", error=None,
            advertencias_cache=[])
        with pytest.warns(AdvertenciaPersistencia):
            guardado = backend._persistir_checkpoint_pipeline()

        assert guardado is False
        assert backend._pipeline_estado["estado"] == "procesando"
        assert backend._pipeline_estado["error"] is None
        assert backend._pipeline_estado["advertencias_cache"]
        assert json.loads(destino.read_text(encoding="utf-8")) == anterior
    finally:
        backend._pipeline_estado.clear()
        backend._pipeline_estado.update(estado_original)


def test_json_compacto_reduce_bytes_y_conserva_contenido(tmp_path):
    datos = {
        "resultados": [
            {"id": f"ID-{i:04d}", "texto": "ABC 123", "imagenes": [
                {"ruta": f"PHOTOS/NACH/IMG_{j:04d}.JPG", "estado": "verificada"}
                for j in range(8)
            ]}
            for i in range(120)
        ]
    }
    legible = tmp_path / "legible.json"
    compacto = tmp_path / "compacto.json"
    assert escribir_json_seguro(legible, datos, fsync=False)
    assert escribir_json_seguro(compacto, datos, compacto=True, fsync=False)
    assert json.loads(legible.read_text(encoding="utf-8")) == datos
    assert json.loads(compacto.read_text(encoding="utf-8")) == datos
    assert compacto.stat().st_size < legible.stat().st_size * 0.72
