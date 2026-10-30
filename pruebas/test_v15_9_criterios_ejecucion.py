"""V15.9 · Fase 0.5: rangos confirmados antes de «Procesar carpeta».

Cubre los valores predeterminados 6/7 ms, la validación (finitos, no
negativos, 0 ≤ verde < amarillo), la instantánea por ejecución con su origen
y el respeto del historial de preferencias del usuario.
"""
from copy import deepcopy
import json

from fastapi.testclient import TestClient
import pytest

import configuracion
import criterios_usuario as criterios
from utilidades.matriz_apertura import (
    AMARILLO_PREDETERMINADO_MS,
    VERDE_PREDETERMINADO_MS,
    criterio_apertura_efectivo,
    limites_predefinidos,
)


@pytest.fixture
def aislado(tmp_path, monkeypatch):
    monkeypatch.setattr(criterios, "RUTA_CRITERIOS", tmp_path / "criterios.json")
    monkeypatch.setattr(criterios, "RUTA_INSTANTANEAS", tmp_path / "instantaneas")
    return tmp_path


def test_predeterminados_son_6_y_7(aislado):
    assert limites_predefinidos() == (6.0, 7.0)
    assert (VERDE_PREDETERMINADO_MS, AMARILLO_PREDETERMINADO_MS) == (6.0, 7.0)
    vigentes = criterios.criterios_o_predeterminados()
    assert vigentes["verde_max"] == 6.0
    assert vigentes["amarillo_max"] == 7.0
    assert vigentes["origen"] == "predeterminado"


def test_origen_vigente_cuando_hay_preferencia(aislado):
    criterios.guardar_criterios_apertura(5.5, 6.5, "revisor")
    vigentes = criterios.criterios_o_predeterminados()
    assert vigentes["verde_max"] == 5.5
    assert vigentes["origen"] == "vigente"


def test_instantanea_por_ejecucion_no_toca_la_preferencia(aislado):
    criterios.guardar_criterios_apertura(5.0, 6.0, "revisor")
    inst = criterios.guardar_instantanea_ejecucion(
        "ejecucion-1", verde_max=4.0, amarillo_max=5.0, origen="elegido", usuario="operador")
    assert inst["origen"] == "elegido"
    # La preferencia global conserva 5/6; la instantánea sólo explica el lote.
    assert criterios.cargar_criterios_usuario()["verde_max"] == 5.0
    cargada = criterios.cargar_instantanea_ejecucion("ejecucion-1")
    assert cargada["verde_max"] == 4.0
    assert cargada["amarillo_max"] == 5.0
    # La instantánea se reutiliza al reanudar el mismo ejecucion_id.
    otra = criterios.guardar_instantanea_ejecucion(
        "ejecucion-1", verde_max=9.0, amarillo_max=10.0, origen="elegido")
    assert otra["verde_max"] == 9.0
    assert criterios.cargar_instantanea_ejecucion("ejecucion-1")["verde_max"] == 9.0


@pytest.mark.parametrize("v,a", [(5, 5), (6, 4), (-1, 3), (0, -2),
                                 (float("nan"), 3), (2, float("inf")),
                                 (True, 3), ("2", 3)])
def test_instantanea_rechaza_limites_invalidos(aislado, v, a):
    with pytest.raises(ValueError):
        criterios.guardar_instantanea_ejecucion(
            "e", verde_max=v, amarillo_max=a, origen="elegido")
    assert criterios.cargar_instantanea_ejecucion("e") is None


def test_instantanea_rechaza_origen_y_ids_invalidos(aislado):
    with pytest.raises(ValueError):
        criterios.guardar_instantanea_ejecucion(
            "e", verde_max=1, amarillo_max=2, origen="inventado")
    with pytest.raises(ValueError):
        criterios.guardar_instantanea_ejecucion(
            "../escape", verde_max=1, amarillo_max=2, origen="elegido")
    assert criterios.cargar_instantanea_ejecucion("../escape") is None


def test_criterio_efectivo_prefiere_instantanea_y_declara_origen(aislado):
    criterios.guardar_criterios_apertura(8.0, 9.0, "revisor")
    inst = criterios.guardar_instantanea_ejecucion(
        "ejecucion-2", verde_max=4.0, amarillo_max=5.0, origen="elegido")
    criterio, origen = criterio_apertura_efectivo(
        None, criterios.cargar_criterios_usuario(), inst)
    assert origen == "instantanea_ejecucion"
    assert criterio == {"verde": "<= 4", "amarillo": "4-5", "rojo": "> 5"}
    # Sin instantánea manda la preferencia del usuario.
    criterio2, origen2 = criterio_apertura_efectivo(
        None, criterios.cargar_criterios_usuario(), None)
    assert origen2 == "criterios_usuario"
    assert criterio2["rojo"] == "> 9"


@pytest.fixture
def api(aislado, monkeypatch):
    import dashboard.backend.app as backend
    monkeypatch.setattr(backend, "REGLAS", deepcopy(configuracion.cargar_reglas()))
    monkeypatch.setattr(backend, "_pipeline_estado", {"estado": "completado"})
    monkeypatch.setattr(backend, "_video_reanalisis_hilo", None)
    return TestClient(backend.app), backend


def _solicitud_base():
    return {"ruta": ".", "modo_ejecucion": "completo"}


def test_api_pipeline_rechaza_limites_invalidos_antes_de_trabajar(api, aislado, monkeypatch):
    cliente, backend = api
    ejecutado = []
    monkeypatch.setattr(backend, "_pipeline_hilo", None)
    monkeypatch.setattr(backend.threading, "Thread",
                        lambda **kw: ejecutado.append(kw) or type("H", (), {"start": lambda self: None, "is_alive": lambda self: False})())
    monkeypatch.setattr(backend, "_capacidad_pipeline", lambda: {"listo": True})
    cuerpo = _solicitud_base()
    cuerpo["rango_apertura"] = {"verde_max": 9, "amarillo_max": 8}
    r = cliente.post("/api/pipeline", json=cuerpo)
    assert r.status_code == 422
    assert not ejecutado, "No debe iniciarse ningún trabajo con rangos inválidos"
    assert not (aislado / "instantaneas").exists() or not any(
        (aislado / "instantaneas").glob("*.json"))


def test_api_pipeline_registra_instantanea_y_puede_guardar_preferencia(api, aislado, monkeypatch):
    cliente, backend = api
    monkeypatch.setattr(backend, "_pipeline_hilo", None)
    monkeypatch.setattr(backend.threading, "Thread",
                        lambda **kw: type("H", (), {"start": lambda self: None, "is_alive": lambda self: False})())
    monkeypatch.setattr(backend, "_capacidad_pipeline", lambda: {"listo": True})
    monkeypatch.setattr(backend, "_persistir_checkpoint_pipeline", lambda: None)
    cuerpo = _solicitud_base()
    cuerpo["ruta"] = str(aislado)
    cuerpo["ejecucion_id"] = "ejec-dialogo-1"
    cuerpo["rango_apertura"] = {"verde_max": 5.5, "amarillo_max": 6.5,
                                "origen": "elegido", "guardar_preferencia": False,
                                "usuario": "operador"}
    r = cliente.post("/api/pipeline", json=cuerpo)
    assert r.status_code == 202
    assert r.json()["criterios_apertura"]["verde_max"] == 5.5
    inst = criterios.cargar_instantanea_ejecucion("ejec-dialogo-1")
    assert inst["verde_max"] == 5.5 and inst["origen"] == "elegido"
    # Sin guardar preferencia, el usuario conserva sus valores anteriores (ninguno).
    assert criterios.cargar_criterios_usuario() is None

    # Con guardar_preferencia explícito sí se persiste la preferencia.
    cuerpo["ejecucion_id"] = "ejec-dialogo-2"
    cuerpo["rango_apertura"] = {"verde_max": 3.5, "amarillo_max": 4.5,
                                "origen": "elegido", "guardar_preferencia": True,
                                "usuario": "operador"}
    r = cliente.post("/api/pipeline", json=cuerpo)
    assert r.status_code == 202
    assert criterios.cargar_criterios_usuario()["verde_max"] == 3.5
    assert len(json.loads((aislado / "criterios.json").read_text())["historial"]) == 0


def test_config_publica_predeterminados_y_vigentes(api, aislado):
    cliente, _ = api
    datos = cliente.get("/api/config").json()
    assert datos["criterios_predeterminados"] == {"verde_max": 6.0, "amarillo_max": 7.0}
    assert datos["criterios_vigentes"]["origen"] in {"predeterminado", "vigente"}
    assert "criterio_efectivo" in datos
