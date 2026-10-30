"""Contratos V15.10.1: resultados conservadores, casos reales y modo sombra."""
from __future__ import annotations

import copy

import pytest

from flujo_empresarial import consolidar_caso
from utilidades.evidencia_apertura import generar_candidatos
from utilidades.matriz_apertura import construir_matriz_dashboard, criterio_desde_limites
from utilidades.politica_apertura import decidir_apertura
from utilidades.resultado_caso import resolver_resultado_caso
from utilidades.sincronizacion_video import sincronizar_vistas
from utilidades.verificador_apertura import verificar_candidato


def _caso(**extra):
    dato = {
        "case_key": "P|1ST|HT|UGL|42", "project_id": "P", "tipo_st": "1ST",
        "temperature_condition": "HT", "inflator_type": "UGL",
        "metadata_ruta": {"test_number": "42"},
        "ruta_relativa": "42", "ruta": "/tmp/42",
    }
    dato.update(extra)
    return dato


def _metricas_sinteticas():
    # Tres cuadros limpios, primer indicio oscuro/local en f3, continuidad en f4-f5.
    datos = []
    for i in range(7):
        tiene = i in {3, 4, 5}
        datos.append({
            "evidencia_debil": tiene,
            "detectado": tiene,
            "pixeles_ruptura": 3 if tiene else 0,
            "pixeles_grieta_nueva": 3 if tiene else 0,
            "pixeles_blanco_nuevo": 0,
            "componente_ruptura_px": 3 if tiene else 0,
            "min_pixeles_debil": 1,
            "min_componente_debil": 1,
            "centro_componente_norm": [0.55, 0.45] if tiene else None,
            "bbox_componente_norm": [0.54, 0.44, 0.56, 0.46] if tiene else None,
            "scores_fuentes": {"fisura": 0.02 if tiene else 0.0,
                               "tela_clara": 0.0, "reflejo": 0.0,
                               "abombamiento": 0.0, "bordes_nuevos": 0.001 if tiene else 0.0},
        })
    return datos


def test_candidatos_sombra_preservan_primer_indicio_y_no_son_probabilidad():
    metricas = _metricas_sinteticas()
    candidatos = generar_candidatos(metricas, nbase=2, fps_adquisicion=5000)
    assert candidatos
    assert candidatos[0]["frame"] == 3
    assert candidatos[0]["frame_confirmacion_sugerido"] >= 4
    assert candidatos[0]["resolucion_ms"] == 0.2
    assert candidatos[0]["score_es_probabilidad"] is False
    assert candidatos[0]["intervalo_tiempo_local_ms"]


def test_verificador_sombra_busca_antes_y_despues_y_nunca_autoconfirma():
    metricas = _metricas_sinteticas()
    candidato = generar_candidatos(metricas, nbase=2, fps_adquisicion=5000)[0]
    revision = verificar_candidato(candidato, metricas, nbase=2)
    assert "continuidad_espacial_posterior" in revision["razones_a_favor"]
    assert revision["es_independiente_del_detector"] is False
    assert revision["auto_confirmable"] is False
    assert revision["probabilidad_calibrada"] is None


def test_politica_apertura_abstiene_sin_calibracion_y_relojes():
    candidato = {"frame": 4, "tiempo_ms": 0.8, "score_candidato": 0.99}
    revision = {"estado_revision": "propuesta_alta_confianza", "razones_en_contra": [],
                "auto_confirmable": False}
    decision = decidir_apertura(candidato=candidato, verificacion=revision,
                                tiempo_verificado=False, auto_publicacion_habilitada=True,
                                calibracion_validada=True, politica_aprobada=True)
    assert decision["estado"] == "propuesta_alta_confianza"
    assert decision["tiempo_ms"] is None
    assert decision["auto_confirmable"] is False
    assert decision["probabilidad_calibrada"] is None


def test_politica_no_auto_publica_sin_consenso_independiente():
    candidato = {"frame": 4, "tiempo_ms": 0.8, "score_candidato": 1.0}
    revision = {"estado_revision": "evidencia_corrobora", "razones_en_contra": []}
    sync = {"estado": "propuesta_no_sincronizada", "consenso_sincronizado": False,
            "soporte_independiente": 0, "tiempo_verificado": False}
    decision = decidir_apertura(candidato=candidato, verificacion=revision,
                                tiempo_verificado=True, sincronizacion=sync,
                                auto_publicacion_habilitada=True,
                                calibracion_validada=True, politica_aprobada=True)
    assert decision["estado"] == "propuesta_revisar"
    assert decision["auto_confirmable"] is False


def _vista(camara: str, sha: str, onset: float, offset: float = 10.0):
    return {
        "camara_id": camara, "sha256": sha, "tiempo_video_ms": onset,
        "puntos_calibracion": [
            {"tiempo_video_ms": 0, "tiempo_referencia_ms": offset},
            {"tiempo_video_ms": 100, "tiempo_referencia_ms": 100 + offset},
            {"tiempo_video_ms": 200, "tiempo_referencia_ms": 200 + offset},
        ],
    }


def test_sincronizacion_exige_relojes_calibrados_tres_fuentes_y_hashes_distintos():
    vistas = [_vista("A", "a", 90), _vista("B", "b", 90), _vista("C", "c", 90)]
    sync = sincronizar_vistas(vistas)
    assert sync["estado"] == "consenso_sincronizado"
    assert sync["soporte_independiente"] == 3
    assert sync["auto_confirmable"] is False
    duplicado = sincronizar_vistas([_vista("A", "same", 90), _vista("B", "same", 90),
                                   _vista("C", "c", 90)])
    assert duplicado["soporte_independiente"] == 2
    assert duplicado["consenso_sincronizado"] is False


def test_sincronizacion_abstiene_si_falta_calibracion_de_reloj():
    vistas = [_vista("A", "a", 90), {"camara_id": "B", "sha256": "b", "tiempo_video_ms": 90},
              _vista("C", "c", 90)]
    sync = sincronizar_vistas(vistas)
    assert sync["estado"] == "propuesta_no_sincronizada"
    assert sync["consenso_sincronizado"] is False
    assert any("reloj_no_calibrado:B" == x for x in sync["fuentes_no_elegibles"])


def test_decision_campo_manual_prevalece_sobre_ocr_y_ruta():
    evidencias = [
        {"clave": "test_number", "valor_normalizado": "42", "fuente": "ruta_carpeta",
         "imagen": "ruta/42"},
        {"clave": "test_number", "valor_normalizado": "24", "fuente": "ocr",
         "imagen": "foto.jpg", "confianza_ocr": 0.999},
        {"clave": "test_number", "valor_normalizado": "99", "fuente": "manual",
         "imagen": "foto.jpg", "confirmacion_manual": True},
    ]
    resultado = consolidar_caso(_caso(), evidencias, requeridos={"test_number"},
                                 claves=("test_number",))
    campo = resultado["campos"]["test_number"]
    assert campo["valor"] == "99"
    assert campo["estado"] == "extraido_manual"
    assert campo["decision_v15_10"] == "VERIFICADO_HUMANO"
    assert campo["alternativas_resueltas_por_revision_humana"] == ["24", "42"]


def test_dos_fuentes_humanas_distintas_conservan_conflicto():
    evidencias = [
        {"clave": "test_number", "valor_normalizado": "42", "fuente": "manual",
         "confirmacion_manual": True},
        {"clave": "test_number", "valor_normalizado": "24", "fuente": "manual",
         "confirmacion_manual": True},
    ]
    resultado = consolidar_caso(_caso(), evidencias, requeridos={"test_number"},
                                 claves=("test_number",))
    campo = resultado["campos"]["test_number"]
    assert campo["estado"] == "conflicto"
    assert campo["decision_v15_10"] == "CONFLICTO"
    assert campo["valor"] is None


def test_resolvedor_canonico_no_eleva_score_ocr_a_probabilidad():
    fila = _caso(campos={"test_number": {"valor": "42", "estado": "extraido_ocr",
                                        "confianza": 0.999, "fuente_preferida": "ocr"},
                         "opening_time_ms": {"valor": 1.8, "estado": "extraido_video",
                                              "confianza": 0.99, "fuente_preferida": "video",
                                              "referencia_tiempo_valida": True,
                                              "estado_tiempo": "VALIDO"}},
                 video_apertura={"estado": "primera_aparicion", "estado_consenso": "propuesto",
                                 "tiempo_ms": 1.8, "soporte": 2,
                                 "referencia_tiempo_valida": True, "estado_tiempo": "VALIDO"}, videos=[])
    canon = resolver_resultado_caso(fila)
    assert canon["campos"]["test_number"]["decision"] == "PROPUESTA"
    assert canon["campos"]["opening_time_ms"]["decision"] == "PROPUESTA"
    assert canon["apertura"]["estado"] == "PROPUESTA"
    assert canon["apertura"]["auto_publicable"] is False
    assert canon["resumen"]["probabilidades_calibradas"] is False


def test_matriz_dinamica_tiene_celdas_solo_para_casos_existentes():
    filas = [
        _caso(case_key="A", id="a", test_number="1", campos={
            "opening_time_ms": {"valor": 2.2, "estado": "confirmado_manual",
                                 "fuente_preferida": "manual", "confirmacion_manual": True,
                                 "referencia_tiempo_valida": True, "estado_tiempo": "VALIDO"}}),
        _caso(case_key="B", id="b", test_number="2", temperature_condition="NT",
              campos={"opening_time_ms": {"valor": None, "estado": "faltante"}}),
    ]
    matriz = construir_matriz_dashboard(filas, criterio_desde_limites(6, 7))
    for etapa in matriz["etapas"]:
        for columna in etapa["columnas"]:
            assert all(c["tipo"] == "caso" for c in columna["celdas"])
            assert len(columna["celdas"]) == columna["ocupados"]
    assert sum(len(c["celdas"]) for e in matriz["etapas"] for c in e["columnas"]) == 2
    estados = [c["estado"] for e in matriz["etapas"] for col in e["columnas"]
               for c in col["celdas"]]
    assert "verde" in estados and "gris" in estados


def test_sincronizacion_no_cuenta_segundas_vistas_de_la_misma_camara():
    vistas = [_vista("A", "a1", 90), _vista("A", "a2", 90), _vista("B", "b", 90),
              _vista("C", "c", 90)]
    sync = sincronizar_vistas(vistas)
    assert sync["soporte_independiente"] == 3
    assert any("mas_de_un_clip_por_camara:A" in x for x in sync["fuentes_no_elegibles"])


def test_apertura_en_conflicto_no_se_sobrescribe_con_consenso_de_video():
    fila = _caso(
        campos={"opening_time_ms": {
            "valor": 1.8, "estado": "conflicto", "conflicto": True,
            "alternativas": [1.8, 2.2], "requiere_revision": True,
            "referencia_tiempo_valida": True, "estado_tiempo": "VALIDO"}},
        video_apertura={"estado": "consenso_automatico", "estado_consenso": "confirmado",
                        "tiempo_ms": 2.2, "soporte": 3,
                        "referencia_tiempo_valida": False, "estado_tiempo": "REFERENCIA_INVALIDA"},
    )

    canon = resolver_resultado_caso(fila)
    apertura = canon["apertura"]

    assert apertura["estado"] == "CONFLICTO"
    assert apertura["tiempo_ms"] is None
    assert apertura["tiempo_propuesto_ms"] == 1.8
    assert apertura["requiere_revision"] is True
    assert apertura["auto_publicable"] is False
    assert canon["campos"]["opening_time_ms"]["decision"] == "CONFLICTO"


def test_conflicto_agregado_sincroniza_decision_del_campo_canonico():
    fila = _caso(
        campos={"opening_time_ms": {"valor": "5,8 ms", "estado": "confirmado_manual",
                                     "fuente_preferida": "manual", "confirmacion_manual": True,
                                     "referencia_tiempo_valida": True, "estado_tiempo": "VALIDO"}}, 
        videos=[{"id": "clip-1", "revision_manual": {
            "estado": "confirmado", "frame_index": 31, "tiempo_ms": 6.2,
            "referencia_tiempo_valida": True, "estado_tiempo": "VALIDO"}}],
    )

    canon = resolver_resultado_caso(fila)

    assert canon["apertura"]["estado"] == "CONFLICTO"
    assert canon["apertura"]["intervalo_tiempo_ms"] == [5.8, 6.2]
    assert canon["campos"]["opening_time_ms"]["decision"] == "CONFLICTO"
    assert canon["campos"]["opening_time_ms"]["requiere_revision"] is True
    assert "confirmaciones_humanas_discrepantes_requieren_resolucion" in canon["campos"]["opening_time_ms"]["razones"]


@pytest.mark.parametrize(("crudo", "estado_tiempo"), [
    (-122.8, "NO_POSITIVO"), (0, "NO_POSITIVO"),
    ("nan", "NO_FINITO"), ("inf", "NO_FINITO"),
])
def test_matriz_explica_tiempos_finales_invalidos_sin_publicarlos(crudo, estado_tiempo):
    fila = _caso(case_key="P|1ST|HT|UGL|42", id="invalid-time", test_number="42",
                 temperature_condition="HT", inflator_type="UGL",
                 campos={"opening_time_ms": {
                     "valor": crudo, "raw_time_ms": crudo,
                     "estado": "confirmado_manual", "fuente_preferida": "manual",
                     "confirmacion_manual": True, "referencia_tiempo_valida": True,
                     "estado_tiempo": "VALIDO",
                 }})
    matriz = construir_matriz_dashboard([fila], criterio_desde_limites(6, 7))
    celda = next(c for etapa in matriz["etapas"] for columna in etapa["columnas"]
                 for c in columna["celdas"] if c["id"] == "invalid-time")
    assert celda["estado"] == "gris"
    assert celda["decision_apertura"] == "PROPUESTA"
    assert celda["estado_tiempo"] == estado_tiempo
    assert celda["motivo_estado"] == estado_tiempo.casefold()
    assert celda["raw_time_ms"] == crudo
    assert celda["motivo_rechazo"]
    assert celda["opening_time_ms"] is None


def test_tiempo_crudo_nan_se_serializa_como_texto_sin_perder_estado():
    import json
    fila = _caso(campos={"opening_time_ms": {
        "valor": float("nan"), "raw_time_ms": float("nan"),
        "estado": "confirmado_manual", "fuente_preferida": "manual",
        "confirmacion_manual": True, "referencia_tiempo_valida": True,
        "estado_tiempo": "VALIDO"}})
    canon = resolver_resultado_caso(fila)
    assert canon["apertura"]["estado"] == "PROPUESTA"
    assert canon["apertura"]["revisiones_temporales_invalidas"][0]["raw_time_ms"] == "nan"
    json.dumps(canon, allow_nan=False)


def test_apertura_manual_con_revision_pendiente_queda_en_propuesta():
    fila = _caso(campos={"opening_time_ms": {
        "valor": "5,8 ms", "estado": "confirmado_manual",
        "fuente_preferida": "manual", "confirmacion_manual": True,
        "requiere_revision": True, "referencia_tiempo_valida": True,
        "estado_tiempo": "VALIDO"}})

    canon = resolver_resultado_caso(fila)

    assert canon["apertura"]["estado"] == "PROPUESTA"
    assert canon["apertura"]["tiempo_ms"] is None
    assert canon["apertura"]["tiempo_propuesto_ms"] == 5.8
    assert canon["campos"]["opening_time_ms"]["decision"] == "PROPUESTA"
    assert canon["campos"]["opening_time_ms"]["requiere_revision"] is True
