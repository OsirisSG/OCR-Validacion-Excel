"""Umbrales explícitos del usuario: persistencia, API y reglas comunes."""
from copy import deepcopy
import json
import os

from fastapi.testclient import TestClient
import pytest

import configuracion
import criterios_usuario as criterios
from utilidades.persistencia import AdvertenciaPersistencia


@pytest.fixture
def aislado(tmp_path, monkeypatch):
    monkeypatch.setattr(criterios, "RUTA_CRITERIOS", tmp_path / "criterios.json")
    return criterios.RUTA_CRITERIOS


def test_umbral_explicito_se_reutiliza_y_preserva_yaml_e_historial(aislado, tmp_path):
    yaml_original = configuracion.RUTA_REGLAS.read_bytes()
    anterior = criterios.guardar_criterios_apertura(5, 7, "revisor A")
    nuevo = criterios.guardar_criterios_apertura(8, 9, "revisor B")
    assert criterios.cargar_criterios_usuario() == nuevo
    assert json.loads(aislado.read_text())["historial"] == [anterior]
    assert configuracion.RUTA_REGLAS.read_bytes() == yaml_original
    regla = configuracion.cargar_reglas()["criterios"]["tiempo_apertura_ms"]
    for valor, color in [(0,"verde"), (8,"verde"), (8.001,"amarillo"), (9,"amarillo"), (9.001,"rojo")]:
        assert configuracion.evaluar_criterio(regla, valor) == color
    alternativo = tmp_path / "alternativo.yaml"
    alternativo.write_bytes(yaml_original)
    assert configuracion.cargar_reglas(alternativo)["criterios"]["tiempo_apertura_ms"] != regla


@pytest.mark.parametrize("v,a", [(True,8), (6,False), (-1,8), (8,8), (9,8), (float("nan"),8), (6,float("inf")), ("6",8)])
def test_limites_invalidos_no_se_guardan(aislado, v, a):
    with pytest.raises(ValueError):
        criterios.guardar_criterios_apertura(v,a,"prueba")
    assert not aislado.exists()


def test_permiso_temporal_reintenta_y_permanente_conserva_regla(aislado, monkeypatch):
    previo = criterios.guardar_criterios_apertura(6,7,"previo")
    original_replace = os.replace
    contador = []
    def reemplazar(origen, destino):
        contador.append(1)
        if len(contador) < 3:
            raise PermissionError("archivo ocupado")
        return original_replace(origen,destino)
    monkeypatch.setattr("utilidades.persistencia.os.replace", reemplazar)
    monkeypatch.setattr("utilidades.persistencia.time.sleep", lambda *_: None)
    criterios.guardar_criterios_apertura(8,9,"nuevo")
    assert len(contador) == 3
    bytes_previos = aislado.read_bytes()
    monkeypatch.setattr("utilidades.persistencia.os.replace",
                        lambda *_: (_ for _ in ()).throw(PermissionError("ocupado")))
    with pytest.warns(AdvertenciaPersistencia), pytest.raises(PermissionError):
        criterios.guardar_criterios_apertura(10,11,"fallido")
    assert aislado.read_bytes() == bytes_previos
    assert json.loads(bytes_previos)["historial"] == [previo]


def test_json_corrupto_no_se_sobrescribe_y_avisa_fallback(aislado):
    aislado.write_text("{incompleto", encoding="utf-8")
    with pytest.raises(ValueError):
        criterios.guardar_criterios_apertura(6,7,"prueba")
    assert aislado.read_text() == "{incompleto"
    with pytest.warns(UserWarning, match="se usan los del YAML"):
        assert configuracion.cargar_reglas()["criterios"]["tiempo_apertura_ms"]["verde"] == "<= 6"


@pytest.fixture
def api(aislado, monkeypatch):
    import dashboard.backend.app as backend
    monkeypatch.setattr(backend,"REGLAS",deepcopy(configuracion.cargar_reglas()))
    monkeypatch.setattr(backend,"_pipeline_estado",{"estado":"completado"})
    monkeypatch.setattr(backend,"_video_reanalisis_hilo",None)
    return TestClient(backend.app), backend


def test_api_actualiza_matriz_sin_cambiar_tiempos_y_reinicio_reutiliza(api, aislado):
    cliente, backend = api
    fila = {"campos":{"opening_time_ms":{"valor":"8.2", "estado":"extraido_manual", "fuente":"manual"}}}
    original = deepcopy(fila)
    r = cliente.post("/api/config/criterios-apertura",json={"verde_max":8.0,"amarillo_max":9.0})
    assert r.status_code == 200 and r.json()["guardado"] is True
    assert backend._estado_apertura_fila(fila) == ("amarillo",8.2)
    from reporte_bmg import _estado_apertura
    assert _estado_apertura(fila,configuracion.cargar_reglas()) == ("amarillo",8.2)
    assert fila == original
    assert cliente.get("/api/config").json()["criterios_usuario"]["verde_max"] == 8
    leyenda = backend._matriz_apertura([{"tipo_st":"1ST"}])["regla"]
    assert leyenda["verde"] == "<= 8 ms"
    assert leyenda["amarillo"] == "8-9 ms"
    assert leyenda["rojo"] == "> 9 ms"


@pytest.mark.parametrize("estado", ["procesando","pausado","reanudando"])
def test_api_no_cambia_criterios_en_lote_en_curso(api, aislado, estado):
    cliente, backend = api
    backend._pipeline_estado["estado"] = estado
    assert cliente.post("/api/config/criterios-apertura",json={"verde_max":8.0,"amarillo_max":9.0}).status_code == 409
    assert not aislado.exists()


def test_api_rechaza_orden_invalido_y_booleanos(api, aislado):
    cliente, _ = api
    for limite in [9, True]:
        assert cliente.post("/api/config/criterios-apertura",json={"verde_max":limite,"amarillo_max":8}).status_code == 422
    assert not aislado.exists()
