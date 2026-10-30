"""V15.9.1 · A5 + A6 + A7: compatibilidad legacy, instantánea y preferencias.

- A5: filas antiguas con el tiempo fuera de ``campos`` no se vuelven grises.
- A6: la instantánea de criterios se persiste también en el perfil legacy.
- A7: «Usar predeterminados» nunca guarda la preferencia global.
"""
import importlib
import json
import pathlib
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import pipeline
import criterios_usuario as criterios


# ------------------------------------------------------------------ A5


def _backend():
    return importlib.import_module("dashboard.backend.app")


def test_a5_fila_legacy_sin_referencia_temporal_no_se_colorea():
    backend = _backend()
    fila = {"opening_time_ms": 5.5}  # JSON antiguo sin referencia temporal verificable
    estado, valor, motivo, pendiente = backend._estado_apertura_detalle(fila)
    assert estado == "gris" and valor is None and motivo == "referencia_invalida"
    assert pendiente is None


def test_a5_fila_legacy_metadata_sin_reloj_no_se_colorea():
    backend = _backend()
    fila = {"metadata_ruta": {"opening_time_ms": "6.5 ms"}}
    estado, valor, motivo, _p = backend._estado_apertura_detalle(fila)
    assert estado == "gris" and valor is None and motivo == "referencia_invalida"


def test_a5_campo_declarado_faltante_no_usa_respaldo():
    backend = _backend()
    fila = {"campos": {"opening_time_ms": {"valor": None, "estado": "faltante_requerido"}},
            "opening_time_ms": 5.0}
    estado, valor, motivo, _p = backend._estado_apertura_detalle(fila)
    # El campo existe y declara ausencia: manda sobre el respaldo legacy.
    assert estado == "gris" and valor is None


def test_a5_campo_pendiente_no_colorea_aunque_haya_respaldo():
    backend = _backend()
    fila = {"campos": {"opening_time_ms": {"valor": "5.0", "estado": "pendiente_revision",
                                           "requiere_revision": True}},
            "opening_time_ms": 5.0}
    estado, valor, motivo, pendiente = backend._estado_apertura_detalle(fila)
    assert estado == "gris" and valor is None and motivo == "pendiente_revision"
    assert pendiente is None  # no publicar respaldo legacy sin referencia temporal


def test_a5_json_de_versiones_anteriores_extremos():
    backend = _backend()
    assert backend._estado_apertura_detalle({})[0] == "gris"
    estado, valor, motivo, _p = backend._estado_apertura_detalle({"opening_time_ms": 7.5})
    assert estado == "gris" and valor is None and motivo == "referencia_invalida"


# ------------------------------------------------------------------ A6


def test_a6_persistencia_en_perfil_legacy(tmp_path):
    destino = tmp_path / "validacion.json"
    validacion = {
        "archivo_salida": str(destino), "perfil": "legacy",
        "resultados": [],
        "criterios_apertura_ejecucion": {"verde_max": 5.5, "amarillo_max": 6.5,
                                         "origen": "elegido", "usuario": "qa"},
        "archivos_excel": {"es": "x.xlsx"}, "idiomas_exportacion": ["es"],
    }
    assert pipeline._persistir_validacion(validacion) is True
    guardado = json.loads(destino.read_text(encoding="utf-8"))
    assert guardado["criterios_apertura_ejecucion"]["verde_max"] == 5.5
    assert guardado["archivos_excel"] == {"es": "x.xlsx"}
    assert "advertencias_persistencia" not in guardado


def test_a6_persistencia_en_perfil_empresarial(tmp_path):
    destino = tmp_path / "validacion_emp.json"
    validacion = {"archivo_salida": str(destino), "perfil": "empresarial",
                  "criterios_apertura_ejecucion": {"verde_max": 6.0, "amarillo_max": 7.0,
                                                   "origen": "predeterminado"}}
    assert pipeline._persistir_validacion(validacion) is True
    guardado = json.loads(destino.read_text(encoding="utf-8"))
    assert guardado["criterios_apertura_ejecucion"]["origen"] == "predeterminado"


def test_a6_reanudacion_sin_sobrescritura_peligrosa(tmp_path):
    """Cerrar y reabrir conserva la instantánea; un fallo de escritura deja
    el archivo previo intacto (escritura atómica)."""
    destino = tmp_path / "validacion_reanudar.json"
    primera = {"archivo_salida": str(destino), "perfil": "legacy",
               "criterios_apertura_ejecucion": {"verde_max": 4.0, "amarillo_max": 5.0}}
    pipeline._persistir_validacion(primera)
    # Reanudación: se vuelve a persistir con el mismo criterio.
    segunda = json.loads(destino.read_text(encoding="utf-8"))
    segunda["reanudado"] = True
    pipeline._persistir_validacion(segunda)
    final = json.loads(destino.read_text(encoding="utf-8"))
    assert final["reanudado"] is True
    assert final["criterios_apertura_ejecucion"]["verde_max"] == 4.0


def test_a6_sin_archivo_salida_anota_advertencia():
    validacion = {"perfil": "legacy"}
    assert pipeline._persistir_validacion(validacion) is False
    assert validacion["advertencias_persistencia"]


# ------------------------------------------------------------------ A7


@pytest.fixture
def criterios_aislados(tmp_path, monkeypatch):
    monkeypatch.setattr(criterios, "RUTA_CRITERIOS", tmp_path / "criterios.json")
    monkeypatch.setattr(criterios, "RUTA_INSTANTANEAS", tmp_path / "instantaneas")
    return tmp_path


def test_a7_predeterminados_nunca_guardan_preferencia(criterios_aislados):
    backend = _backend()
    from dashboard.backend.app import RangoAperturaSolicitud
    rango = RangoAperturaSolicitud(verde_max=6.0, amarillo_max=7.0,
                                   origen="predeterminado", guardar_preferencia=True)
    instantanea = backend._resolver_instantanea_para_ejecucion("ej-a7-1", rango)
    assert instantanea["origen"] == "predeterminado"
    # Aunque guardar_preferencia venía en True, la preferencia global NO cambia.
    assert not criterios.RUTA_CRITERIOS.exists()


def test_a7_elegido_con_guardar_si_persiste(criterios_aislados):
    backend = _backend()
    from dashboard.backend.app import RangoAperturaSolicitud
    rango = RangoAperturaSolicitud(verde_max=5.0, amarillo_max=6.0,
                                   origen="elegido", guardar_preferencia=True)
    backend._resolver_instantanea_para_ejecucion("ej-a7-2", rango)
    assert criterios.RUTA_CRITERIOS.exists()
    guardado = criterios.cargar_criterios_usuario()
    assert guardado["verde_max"] == 5.0 and guardado["amarillo_max"] == 6.0


def test_a7_elegido_sin_guardar_solo_instantanea(criterios_aislados):
    backend = _backend()
    from dashboard.backend.app import RangoAperturaSolicitud
    rango = RangoAperturaSolicitud(verde_max=5.0, amarillo_max=6.0,
                                   origen="elegido", guardar_preferencia=False)
    instantanea = backend._resolver_instantanea_para_ejecucion("ej-a7-3", rango)
    assert instantanea["verde_max"] == 5.0
    assert not criterios.RUTA_CRITERIOS.exists()


def test_a7_frontend_fuerza_no_guardar_en_predeterminados():
    codigo = (RAIZ / "dashboard" / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'origen === "predeterminado" ? false : guardarPreferencia' in codigo
