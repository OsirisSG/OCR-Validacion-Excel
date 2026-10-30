"""V15.9.3 · Pruebas que reproducen los bloqueantes CRIT-01..04 y ALTA-05.

Todas FALLAN sobre el árbol V15.9.2 (reproducen exactamente los defectos de
`AUDITORIA_ESTRICTA_V_MATRIX_V15_9_2.md`) y pasan con la corrección:

- CRIT-01 (C1): consenso legado SIN `total_principales` se validaba con
  soporte=1. Debe fallar cerrado; sin videos, evidencia pendiente sin elevar.
- CRIT-02 (C2): integrante con `requiere_revision=True` sin motivo se
  publicaba como confirmado. Sólo `revision_informativa=True` explícita
  exceptúa; ausencia de motivo NO implica informativa.
- CRIT-03 (C7/P08): con `identidad_verificada=False` los generadores guardaban
  el reporte identificado de todas formas. La salida identificada debe quedar
  BLOQUEADA: borrador no publicable en ubicación diferenciada, destino oficial
  intacto, plantilla intacta.
- CRIT-04 (C7): `proyectos.json` ilegible se reemplazaba por un registro
  vacío. Debe fallar cerrado preservando los bytes, con recuperación explícita.
- ALTA-05: guardado del Excel empresarial no atómico; un fallo a mitad de
  escritura no debe tocar la salida anterior.

Ejecutar: python -m pytest pruebas/test_v15_9_3_criticos.py -q
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import pathlib
import stat
import sys

import pytest
from openpyxl import Workbook, load_workbook

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "pruebas"))

import utilidades.proyectos as registro
import video_airbag as va
from test_plantilla_empresarial import _plantilla


def _backend():
    return importlib.import_module("dashboard.backend.app")


def _hash(ruta: pathlib.Path) -> str:
    return hashlib.sha256(pathlib.Path(ruta).read_bytes()).hexdigest()


def _item(nombre, tiempo, *, estado="candidato", revision=None, **extra):
    it = {"nombre": nombre, "estado": estado, "tiempo_ms": tiempo,
          "tiempo_fps_ms": tiempo, "resolucion_nativa_ms": 0.1,
          "precision_fuente_ms": 0.1, "fuente_tiempo": "fps_subframe"}
    if revision:
        it["revision_manual"] = revision
    it.update(extra)
    return it


CAM_A, CAM_B, CAM_C, CAM_D = ("09_DETAIL.AVI", "09_FRONTAL.AVI",
                              "09_LATERAL.AVI", "09_SCHEIBE.AVI")

IDENTIDAD_B = {"nombre_proyecto": "Proyecto B", "project_id": "proyecto-b",
               "origen": "declarado_usuario", "sin_asignar": False,
               "pendiente": False, "responsable": "ana",
               "ejecucion_id": "ej-crit", "fecha": "2026-10-12T10:00:00"}


# ---------------------------------------------------------------------------
# CRIT-01 · consenso legado con metadatos incompletos
# ---------------------------------------------------------------------------


def test_crit01_legado_sin_total_principales_falla_cerrado():
    """Reproducción literal de la auditoría."""
    assert va.consenso_valido({"estado": "primera_aparicion", "tiempo_ms": 5.4,
                               "soporte": 1, "requiere_revision": False}) is False
    assert va.consenso_valido({"estado": "primera_aparicion", "tiempo_ms": 5.4,
                               "soporte": 2, "requiere_revision": False}) is False
    # total inválido/no numérico: igualmente cerrado.
    assert va.consenso_valido({"estado": "primera_aparicion", "tiempo_ms": 5.4,
                               "soporte": 2, "total_principales": "?",
                               "requiere_revision": False}) is False
    assert va.consenso_valido({"estado": "primera_aparicion", "tiempo_ms": 5.4,
                               "soporte": 2, "total_principales": 0,
                               "requiere_revision": False}) is False


def test_crit01_metadata_completa_mantiene_las_reglas_v15_9_2():
    assert va.consenso_valido({"estado": "primera_aparicion", "tiempo_ms": 5.4,
                               "soporte": 2, "total_principales": 4,
                               "requiere_revision": False}) is False
    assert va.consenso_valido({"estado": "primera_aparicion", "tiempo_ms": 5.4,
                               "soporte": 3, "total_principales": 4,
                               "requiere_revision": False}) is True
    assert va.consenso_valido({"estado": "confirmado_manual", "tiempo_ms": 5.4,
                               "soporte": 1}) is True


def test_crit01_migracion_sin_videos_deja_evidencia_pendiente(tmp_path, monkeypatch):
    """Sin videos para recalcular: no se publica, se conserva como pendiente."""
    backend = _backend()
    fila = {"nombre": "CASO1", "case_key": "CASO1", "videos": [],
            "campos": {"opening_time_ms": {"valor": "5.4", "estado": "extraido_video",
                                           "fuente": "video_airbag_consenso"}},
            "video_apertura": {"estado": "primera_aparicion", "tiempo_ms": 5.4,
                               "soporte": 1, "requiere_revision": False}}
    validacion = tmp_path / "validacion_resultados.json"
    validacion.write_text(json.dumps({"resultados": [fila]}), encoding="utf-8")
    monkeypatch.setattr(backend, "RUTA_VALIDACION", validacion)
    backend._cache.update({"mtime": None, "datos": None})
    try:
        f = backend._cargar_datos()["resultados"][0]
        assert f["video_apertura_anterior"]["soporte"] == 1  # evidencia conservada
        assert f["video_apertura"]["requiere_revision"] is True
        assert va.consenso_valido(f["video_apertura"]) is False
        campo = f["campos"]["opening_time_ms"]
        assert campo["estado"] == "pendiente_revision"  # ya no publicado
        assert float(campo["valor"]) == pytest.approx(5.4)  # medida conservada
        disco = json.loads(validacion.read_text(encoding="utf-8"))
        assert disco["resultados"][0]["campos"]["opening_time_ms"]["estado"] \
            == "pendiente_revision"
    finally:
        backend._cache.update({"mtime": None, "datos": None})


def test_crit01_migracion_sin_videos_con_respaldo_completo_no_degrada(tmp_path, monkeypatch):
    backend = _backend()
    fila = {"nombre": "CASO2", "case_key": "CASO2", "videos": [],
            "campos": {"opening_time_ms": {"valor": "5.4", "estado": "extraido_video",
                                           "fuente": "video_airbag_consenso"}},
            "video_apertura": {"estado": "primera_aparicion", "tiempo_ms": 5.4,
                               "soporte": 3, "total_principales": 4,
                               "requiere_revision": False}}
    validacion = tmp_path / "validacion_resultados.json"
    validacion.write_text(json.dumps({"resultados": [fila]}), encoding="utf-8")
    monkeypatch.setattr(backend, "RUTA_VALIDACION", validacion)
    backend._cache.update({"mtime": None, "datos": None})
    try:
        f = backend._cargar_datos()["resultados"][0]
        assert f["campos"]["opening_time_ms"]["estado"] == "extraido_video"
        assert va.consenso_valido(f["video_apertura"]) is True
    finally:
        backend._cache.update({"mtime": None, "datos": None})


# ---------------------------------------------------------------------------
# CRIT-02 · revisión sin motivo bloquea la publicación
# ---------------------------------------------------------------------------


def test_crit02_revision_sin_motivo_no_se_publica():
    """Reproducción de la auditoría: 3 principales + SCHEIBE excluida."""
    items = [_item(CAM_A, 5.0),
             _item(CAM_B, 5.0, requiere_revision=True),  # sin motivo ni marca
             _item(CAM_C, 5.0),
             _item(CAM_D, 90.0)]
    consenso = va.consenso_videos(items, {})
    assert consenso["estado_consenso"] == "confirmado"  # respaldo numérico 3
    assert consenso["requiere_revision"] is True
    assert consenso["revision_no_clasificada"] is True
    assert va.consenso_valido(consenso) is False
    # Coherencia: si el consolidado avisa de una cámara pendiente, no publica.
    if any("marcada para revisión" in m or "SIN CLASIFICAR" in m
           for m in consenso["motivo_revision"]):
        assert consenso["requiere_revision"] is True


def test_crit02_tres_de_4_limpio_sigue_confirmado():
    items = [_item(CAM_A, 5.0), _item(CAM_B, 5.0), _item(CAM_C, 5.0),
             _item(CAM_D, 90.0)]
    consenso = va.consenso_videos(items, {})
    assert consenso["estado_consenso"] == "confirmado"
    assert consenso["requiere_revision"] is False
    assert va.consenso_valido(consenso) is True


def test_crit02_marca_informativa_explicita_no_bloquea():
    items = [_item(CAM_A, 5.0),
             _item(CAM_B, 5.0, requiere_revision=True, revision_informativa=True),
             _item(CAM_C, 5.0)]
    consenso = va.consenso_videos(items, {})
    assert consenso["requiere_revision"] is False
    assert va.consenso_valido(consenso) is True


def test_crit02_confirmacion_humana_sigue_mandando():
    items = [_item(CAM_A, 4.8, revision={"estado": "confirmado", "tiempo_ms": 4.8}),
             _item(CAM_B, 5.0, requiere_revision=True),
             _item(CAM_C, 5.0)]
    consenso = va.consenso_videos(items, {})
    assert consenso["estado"] == "confirmado_manual"
    assert va.consenso_valido(consenso) is True


# ---------------------------------------------------------------------------
# CRIT-03 · P08: salida identificada BLOQUEADA cuando la plantilla no mapea
# ---------------------------------------------------------------------------


@pytest.fixture
def plantilla_no_mapeable(tmp_path):
    """Plantilla con título histórico SIN etiqueta identificable de proyecto."""
    ruta = tmp_path / "externa.xlsx"
    _plantilla(ruta)
    libro = load_workbook(ruta)
    libro["Captura_pruebas"]["A1"] = "Reporte del Proyecto A"
    libro.save(ruta)
    return ruta


def test_crit03_empresarial_no_publica_reporte_identificado_incorrecto(
        plantilla_no_mapeable, tmp_path):
    from plantilla_empresarial import generar_desde_plantilla
    plantilla = plantilla_no_mapeable
    hash_plantilla = _hash(plantilla)
    oficial = tmp_path / "salida_oficial.xlsx"
    # Salida vigente previa que NO debe ser contaminada.
    wb = Workbook(); wb.active["A1"] = "resultado anterior vigente"; wb.save(oficial)
    hash_oficial_antes = _hash(oficial)

    resultado = generar_desde_plantilla(plantilla, oficial, [],
                                        identidad_proyecto=IDENTIDAD_B)
    resultado = pathlib.Path(resultado)
    # La publicación identificada quedó BLOQUEADA: destino oficial intacto.
    assert resultado != oficial
    assert "borrador_no_publicable" in resultado.name
    assert _hash(oficial) == hash_oficial_antes
    assert resultado.is_file()
    # El borrador lleva la advertencia visible y el marcador de no publicable.
    libro = load_workbook(resultado)
    resumen = "\n".join(str(c.value) for fila in libro["Resumen"].iter_rows()
                        for c in fila if c.value)
    assert "ADVERTENCIA" in resumen
    assert "BORRADOR NO PUBLICABLE" in resumen.upper()
    # No se suplanta el título antiguo.
    assert libro["Captura_pruebas"]["A1"].value == "Reporte del Proyecto A"
    # Plantilla original intacta.
    assert _hash(plantilla) == hash_plantilla


def test_crit03_bmg_publica_con_proyecto_explicito_sin_celda_mapeada(tmp_path):
    from reporte_bmg import generar_reporte_bmg
    from configuracion import cargar_config, cargar_reglas
    from test_reporte_bmg_v7 import caso
    plantilla = RAIZ / "plantillas" / "reporte_bmg_1st_2st.xlsx"
    assert plantilla.is_file()
    hash_plantilla = _hash(plantilla)
    oficial = tmp_path / "bmg_oficial.xlsx"
    resultados = [caso(1001, "1ST", "HT", "UGL", 5.8)]
    salida = generar_reporte_bmg(plantilla, oficial, resultados,
                                 cargar_config(), cargar_reglas(), idioma="es",
                                 identidad_proyecto=IDENTIDAD_B)
    salida = pathlib.Path(salida)
    # V15.10.1+: la selección explícita del usuario es la identidad autoritativa.
    # La ausencia de una celda de proyecto en la plantilla ya no bloquea por sí
    # sola; sólo una contradicción real debe producir borrador no publicable.
    assert salida == oficial and oficial.is_file()
    libro = load_workbook(salida)
    assert libro["Übersicht Standversuche"]["A1"].value == "Proyecto B"
    assert _hash(plantilla) == hash_plantilla


def test_crit03_identidad_legacy_no_bloquea_la_publicacion(
        plantilla_no_mapeable, tmp_path):
    """P11: cargas legacy (sin proyecto declarado) conservan el flujo anterior."""
    from plantilla_empresarial import generar_desde_plantilla
    oficial = tmp_path / "salida_legacy.xlsx"
    identidad_legacy = {"nombre_proyecto": None, "project_id": "carpeta-x",
                        "origen": "nombre_carpeta_legacy", "sin_asignar": False,
                        "pendiente": True}
    salida = generar_desde_plantilla(plantilla_no_mapeable, oficial, [],
                                     identidad_proyecto=identidad_legacy)
    assert pathlib.Path(salida) == oficial and oficial.is_file()
    resumen = "\n".join(str(c.value) for fila in load_workbook(oficial)["Resumen"].iter_rows()
                        for c in fila if c.value)
    assert "ADVERTENCIA" in resumen  # advertencia visible, sin bloqueo legacy


# La regresión "plantilla mapeable ⇒ publicación normal" se certifica en
# test_c7_p01_salida_usa_proyecto_declarado_y_plantilla_intacta
# (pruebas/test_v15_9_2_proyecto_c7.py).


# ---------------------------------------------------------------------------
# CRIT-04 · registro de proyectos corrupto: fallar cerrado
# ---------------------------------------------------------------------------


BYTES_CORRUPTOS = b'{"version": 1, "proyectos": [{"nombre_proyecto": "Proyecto A"'


def test_crit04_registro_ilegible_bloquea_escrituras_y_preserva_bytes(tmp_path):
    ruta = tmp_path / "proyectos.json"
    ruta.write_bytes(BYTES_CORRUPTOS)
    hash_antes = _hash(ruta)
    with pytest.raises(registro.RegistroProyectosCorruptoError):
        registro.registrar_proyecto("Proyecto B", ruta=ruta)
    # Ni un byte cambiado.
    assert ruta.read_bytes() == BYTES_CORRUPTOS
    assert _hash(ruta) == hash_antes
    # Las lecturas tampoco fingen un registro vacío.
    with pytest.raises(registro.RegistroProyectosCorruptoError):
        registro.listar_proyectos(ruta)
    with pytest.raises(registro.RegistroProyectosCorruptoError):
        registro.registrar_ejecucion("proyecto-b", ruta=ruta)


def test_crit04_recuperacion_explicita_respalda_bytes_originales(tmp_path):
    ruta = tmp_path / "proyectos.json"
    ruta.write_bytes(BYTES_CORRUPTOS)
    hash_antes = _hash(ruta)
    info = registro.recuperar_registro(ruta)
    assert info["recuperado"] is True
    respaldo = pathlib.Path(info["respaldo"])
    assert respaldo.is_file() and _hash(respaldo) == hash_antes  # bytes preservados
    assert "Proyecto A" in respaldo.read_text(encoding="utf-8", errors="replace")
    # Tras la recuperación explícita el registro funciona.
    creado = registro.registrar_proyecto("Proyecto B", ruta=ruta)
    assert creado["proyecto_id"] == "proyecto-b"
    assert [p["proyecto_id"] for p in registro.listar_proyectos(ruta)] == ["proyecto-b"]


def test_crit04_registro_inexistente_se_crea_normal(tmp_path):
    ruta = tmp_path / "nuevo" / "proyectos.json"
    creado = registro.registrar_proyecto("Proyecto B", ruta=ruta)
    assert creado["proyecto_id"] == "proyecto-b" and ruta.is_file()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignora los permisos de lectura")
def test_crit04_permisos_de_lectura_fallan_cerrado(tmp_path):
    ruta = tmp_path / "proyectos.json"
    ruta.write_bytes(BYTES_CORRUPTOS)
    hash_antes = _hash(ruta)
    os.chmod(ruta, 0o000)
    try:
        with pytest.raises(registro.RegistroProyectosCorruptoError):
            registro.listar_proyectos(ruta)
        with pytest.raises(registro.RegistroProyectosCorruptoError):
            registro.registrar_proyecto("Proyecto B", ruta=ruta)
    finally:
        os.chmod(ruta, stat.S_IRUSR | stat.S_IWUSR)
    assert _hash(ruta) == hash_antes


def test_crit04_endpoint_proyectos_reporta_registro_ilegible(tmp_path, monkeypatch):
    from fastapi import HTTPException
    backend = _backend()
    ruta = tmp_path / "proyectos.json"
    ruta.write_bytes(BYTES_CORRUPTOS)
    monkeypatch.setattr(registro, "RUTA_PROYECTOS", ruta)
    with pytest.raises(HTTPException) as err:
        backend.listar_proyectos()
    assert err.value.status_code == 503
    assert "ilegible" in str(err.value.detail)


def test_crit04_pipeline_con_registro_ilegible_no_procesa(tmp_path, monkeypatch):
    from fastapi import HTTPException
    backend = _backend()
    ruta = tmp_path / "proyectos.json"
    ruta.write_bytes(BYTES_CORRUPTOS)
    monkeypatch.setattr(registro, "RUTA_PROYECTOS", ruta)
    lote = tmp_path / "lote"
    lote.mkdir()
    with pytest.raises(HTTPException) as err:
        backend.iniciar_pipeline(backend.SolicitudPipeline(
            ruta=str(lote), proyecto={"nombre_proyecto": "Proyecto B"}))
    assert err.value.status_code == 503
    assert ruta.read_bytes() == BYTES_CORRUPTOS  # intacto


# ---------------------------------------------------------------------------
# ALTA-05 · guardado atómico del Excel empresarial
# ---------------------------------------------------------------------------


def test_alta05_fallo_a_mitad_de_escritura_no_toca_la_salida_anterior(
        plantilla_no_mapeable, tmp_path, monkeypatch):
    from plantilla_empresarial import generar_desde_plantilla
    oficial = tmp_path / "salida.xlsx"
    wb = Workbook(); wb.active["A1"] = "resultado anterior vigente"; wb.save(oficial)
    hash_antes = _hash(oficial)

    def save_roto(self, path, *args, **kwargs):
        # Simula escritura parcial + fallo a mitad del guardado.
        pathlib.Path(path).write_bytes(b"PK\x03\x04parcial-corrupto")
        raise RuntimeError("fallo inyectado a mitad de escritura")

    monkeypatch.setattr(Workbook, "save", save_roto)
    with pytest.raises(RuntimeError):
        # identidad legacy para evitar la puerta P08 y ejercer sólo el guardado
        generar_desde_plantilla(plantilla_no_mapeable, oficial, [],
                                identidad_proyecto={"project_id": "carpeta-x",
                                                    "origen": "nombre_carpeta_legacy",
                                                    "pendiente": True})
    # La salida anterior queda intacta y no hay temporales huérfanos.
    assert _hash(oficial) == hash_antes
    temporales = [p for p in tmp_path.iterdir()
                  if p.name.startswith(".") and p.name.endswith((".tmp", ".tmp.xlsx"))]
    assert temporales == []
