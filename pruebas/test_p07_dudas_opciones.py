"""Pruebas de P07: RDW≠NAR, cola de dudas con opciones y escritura en el Excel.

Lo que se comprueba, sin adornos:
  1. la regla de etapa (RDW=1ST, NAR=2ST) y que el flujo avise cuando no cuadra;
  2. que las dudas salgan con opciones útiles y que la serie descarte el ruido;
  3. que lo elegido acabe en el Excel con el tipo correcto, sin tocar cabeceras ni fórmulas;
  4. que «no lo tengo» no vuelva a preguntar y que el panel funcione de punta a punta.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from utilidades.cola_dudas import Estado
from utilidades.dudas_y_opciones import _estado_serie, aplicar_decisiones, resumen_dudas
from utilidades.protocolo_identidad import VERSION_POR_ETAPA, revisar_etapa

RAIZ = Path(__file__).resolve().parent.parent
LIBRO_PRACTICA = RAIZ / "casos_reproduccion" / "libro_practica.xlsx"
LECTURAS = RAIZ / "casos_reproduccion" / "lecturas_dudas.json"
MAPA = RAIZ / "casos_reproduccion" / "mapa_filas.json"

pytestmark = pytest.mark.skipif(not LIBRO_PRACTICA.is_file(),
                                reason="falta el libro de práctica de P07")


# ---------------------------------------------------------------- regla de etapa
def test_las_dos_etapas_no_son_la_misma_version():
    assert VERSION_POR_ETAPA == {"RDW": "1ST", "NAR": "2ST"}


@pytest.mark.parametrize("version,etapa,caso", [
    ("RDW", "1ST", "coherente"),
    ("NAR", "2ST", "coherente"),
    ("RDW", "2ST", "incoherente"),
    ("NAR", "1ST", "incoherente"),
    ("RDW", "1st", "coherente"),          # la etapa se escribe igual en minúsculas
])
def test_revisar_etapa(version, etapa, caso):
    assert revisar_etapa(version, etapa)["estado"] == caso


def test_revisar_etapa_fuera_de_catalogo_y_sin_comprobar():
    assert revisar_etapa("XXX", "1ST")["estado"] == "fuera_de_catalogo"
    assert revisar_etapa("RDW", None)["estado"] == "sin_comprobar"


def test_aviso_util_si_la_etapa_no_cuadra():
    aviso = revisar_etapa("RDW", "2st")
    assert aviso["estado"] == "incoherente" and aviso["etapa_esperada"] == "1ST"
    assert "RDW" in aviso["motivo"] and "1ST" in aviso["motivo"] and "2ST" in aviso["motivo"]


def test_el_flujo_de_empresa_incorpora_la_comprobacion():
    import flujo_empresarial as fe

    assert any("revisar_etapa" in linea for linea in
               Path(fe.__file__).read_text(encoding="utf-8").splitlines())


# ---------------------------------------------------------------- dudas y opciones
def _entorno():
    lecturas = json.loads(LECTURAS.read_text(encoding="utf-8"))
    mapa = json.loads(MAPA.read_text(encoding="utf-8"))
    return lecturas, mapa, Estado


def test_la_serie_descarta_los_numeros_que_no_son_el_caso():
    assert _estado_serie("232561", "test_number", "232561") == "coherente"
    assert _estado_serie("232561", "test_number", "142025") == "fuera_de_serie"


def test_las_dudas_traen_opciones_y_descartan_el_ruido(tmp_path):
    lecturas, mapa, Estado = _entorno()
    libro = tmp_path / "libro.xlsx"
    shutil.copy2(LIBRO_PRACTICA, libro)
    estado = Estado(libro, lecturas, None, mapa)

    dudas = {d["id"]: d for d in estado.dudas}
    assert len(dudas) == 7, sorted(dudas)

    numero = dudas["232561::test_number"]
    valores = [o["valor"] for o in numero["opciones"]]
    con_valor = [v for v in valores if v is not None]
    assert con_valor, "tiene que haber al menos una opción"
    assert "232561" in con_valor
    assert {o["valor"] for o in numero["opciones_descartadas"]} == {"142025", "162051"}
    assert all("142025" not in str(v) for v in valores)

    conflicto = dudas["232561::inflator_type"]
    assert conflicto["motivo"] == "fuentes_en_conflicto"
    assert {o["valor"] for o in conflicto["opciones"]} >= {"OGL", "NOM"}

    # toda duda dice dónde mirar y ofrece «no lo tengo»
    for duda in estado.dudas:
        assert duda["donde_mirar"], duda["id"]
        assert any(o["fuente"] == "no_lo_tengo" for o in duda["opciones"]), duda["id"]

    resumen = resumen_dudas(estado.dudas)
    assert resumen["casos"] == 4 and resumen["con_al_menos_una_opcion"] == 5


def test_una_duda_sin_datos_no_inventa_opciones(tmp_path):
    lecturas, mapa, Estado = _entorno()
    libro = tmp_path / "libro.xlsx"
    shutil.copy2(LIBRO_PRACTICA, libro)
    estado = Estado(libro, lecturas, None, mapa)
    duda = {d["id"]: d for d in estado.dudas}["252590::module_serial_number"]
    assert [o["fuente"] for o in duda["opciones"]] == ["no_lo_tengo"], "preferible no dar dato"


# ---------------------------------------------------------------- escritura en el Excel
def _decisiones(estado):
    elegidas = {"232561::test_number": "232561", "232561::test_place": "EDAG",
                "232561::inflator_type": "OGL", "232564::module_part_number": "2GJ.880.204.J",
                "252590::module_version": "RDW"}
    return [estado.decidir(i, v) for i, v in elegidas.items()]


def test_aplicar_decisiones_escribe_en_la_celda_correcta(tmp_path):
    lecturas, mapa, Estado = _entorno()
    libro = tmp_path / "libro.xlsx"
    shutil.copy2(LIBRO_PRACTICA, libro)
    estado = Estado(libro, lecturas, None, mapa)

    salida = tmp_path / "libro_confirmado.xlsx"
    diario = tmp_path / "diario.json"
    registro = aplicar_decisiones(libro, _decisiones(estado), ruta_salida=salida, diario=diario)

    celdas = {e["clave"]: e["celda"] for e in registro["escritos"]}
    assert celdas == {"test_number": "C15", "test_place": "E15", "inflator_type": "M15",
                      "module_part_number": "G16", "module_version": "H13"}

    from openpyxl import load_workbook
    ws = load_workbook(salida)["Versuchsmatrix"]
    assert ws["C15"].value == 232561 and isinstance(ws["C15"].value, int), "tipo del libro"
    assert ws["E15"].value == "EDAG"
    assert ws["M15"].value == "OGL"
    assert ws["G16"].value == "2GJ.880.204.J"
    assert ws["H13"].value == "RDW"

    # lo que no se decidió sigue vacío, y ni cabeceras ni fórmulas se han tocado
    assert ws["C8"].value == 222504
    assert ws["A7"].value.startswith("Woche")
    assert ws["G20"].value == "=F20-E20"
    # el libro de entrada no se modifica
    assert load_workbook(libro)["Versuchsmatrix"]["C15"].value is None

    anotado = json.loads(diario.read_text(encoding="utf-8"))
    assert len(anotado["escritos"]) == 5 and anotado["decisiones"]


def test_no_lo_tengo_deja_la_celda_vacia_pero_queda_anotado(tmp_path):
    lecturas, mapa, Estado = _entorno()
    libro = tmp_path / "libro.xlsx"
    shutil.copy2(LIBRO_PRACTICA, libro)
    estado = Estado(libro, lecturas, None, mapa)
    decision = estado.decidir("252590::module_serial_number", None)
    assert decision["valor"] is None

    registro = aplicar_decisiones(libro, [decision], ruta_salida=tmp_path / "salida.xlsx")
    assert registro["escritos"] == []
    assert registro["omitidos"][0]["motivo"].startswith("no_lo_tengo")


# ---------------------------------------------------------------- panel (API)
def test_panel_de_punta_a_punta(tmp_path):
    pytest.importorskip("fastapi", reason="el panel necesita fastapi")
    from fastapi.testclient import TestClient

    import panel_confirmacion as pc

    libro = tmp_path / "libro_panel.xlsx"
    shutil.copy2(LIBRO_PRACTICA, libro)
    anterior = pc.ESTADO
    pc.ESTADO = pc.Estado(libro, json.loads(LECTURAS.read_text(encoding="utf-8")), None,
                          json.loads(MAPA.read_text(encoding="utf-8")))
    try:
        cliente = TestClient(pc.app)
        assert cliente.get("/").status_code == 200
        assert "Panel de dudas" in cliente.get("/").text

        estado = cliente.get("/api/estado").json()
        assert estado["casos"] == 10 and estado["resumen"]["dudas"] == 7
        assert estado["filas_sin_numero_de_caso"] == [], "no confundir el bloque de promedios"

        for id_duda, valor in [("232561::test_number", "232561"), ("232561::test_place", "EDAG"),
                               ("232561::inflator_type", "OGL"),
                               ("232564::module_part_number", "2GJ.880.204.J"),
                               ("252590::module_version", "RDW"),
                               ("222504::engineering_level", None),
                               ("252590::module_serial_number", None)]:
            assert cliente.post("/api/decidir", json={"id": id_duda, "valor": valor}).status_code == 200

        # «no lo tengo» silencia la duda sin escribir nada
        assert len(cliente.get("/api/estado").json()["silenciadas"]) == 2
        assert cliente.get("/api/estado").json()["resumen"]["dudas"] == 5

        guardado = cliente.post("/api/guardar").json()
        assert guardado["escritos"] == 5 and guardado["dudas_restantes"] == 0
        assert cliente.get("/api/descargar").status_code == 200

        # al reabrir el panel, lo silenciado sigue silenciado y no hay dudas vivas
        pc.ESTADO = pc.Estado(libro, json.loads(LECTURAS.read_text(encoding="utf-8")), None,
                              json.loads(MAPA.read_text(encoding="utf-8")))
        assert pc.ESTADO.dudas == []
        assert cliente.post("/api/guardar").status_code == 400, "sin decisiones no hay nada que guardar"
    finally:
        pc.ESTADO = anterior


def test_panel_sin_dudas_lo_dice(tmp_path):
    """Con el libro completo no se pregunta nada: el panel no inventa trabajo."""
    pytest.importorskip("fastapi", reason="el panel necesita fastapi")
    from fastapi.testclient import TestClient
    from openpyxl import load_workbook

    import panel_confirmacion as pc

    libro = tmp_path / "completo.xlsx"
    shutil.copy2(LIBRO_PRACTICA, libro)
    wb = load_workbook(libro)
    ws = wb["Versuchsmatrix"]
    for celda, valor in {"C15": 232561, "E15": "EDAG", "M15": "OGL",
                         "G16": "2GJ.880.204.J", "H13": "RDW", "K8": "01S",
                         "I13": "671 ZRZ0539974G"}.items():
        ws[celda] = valor
    wb.save(libro)

    anterior = pc.ESTADO
    pc.ESTADO = pc.Estado(libro, json.loads(LECTURAS.read_text(encoding="utf-8")), None,
                          json.loads(MAPA.read_text(encoding="utf-8")))
    try:
        respuesta = TestClient(pc.app).get("/api/dudas").json()
        assert respuesta["dudas"] == [], [d["id"] for d in respuesta["dudas"]]
    finally:
        pc.ESTADO = anterior
