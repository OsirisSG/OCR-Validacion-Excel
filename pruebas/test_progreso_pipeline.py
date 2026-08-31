"""Contrato de avance granular del orquestador."""

from pathlib import Path

import pipeline


def test_pipeline_emite_resultados_parciales_y_cierra_en_cien(monkeypatch, tmp_path):
    estructura = {
        "total_carpetas": 2, "patron_dominante": None, "anomalias": [],
        "carpetas": [],
    }
    monkeypatch.setattr(pipeline, "mapear_estructura", lambda ruta, config: estructura)
    monkeypatch.setattr(pipeline, "guardar_estructura", lambda datos: tmp_path / "estructura.json")
    monkeypatch.setattr(pipeline, "carpetas_hoja", lambda datos: [{}, {}])

    filas = [
        {"nombre": "uno", "comparacion": {"resultado": "coincidencia_total"}},
        {"nombre": "dos", "comparacion": {"resultado": "discrepancia"}},
    ]

    def validar(ruta, config, al_resultado, al_imagen):
        al_imagen(1, 2, "/tmp/uno.jpg", 3.2)
        al_resultado(1, 2, filas[0], 3.2)
        al_imagen(2, 2, "/tmp/dos.jpg", 0.0)
        al_resultado(2, 2, filas[1], 0.0)
        return {
            "resultados": filas, "archivo_salida": str(tmp_path / "validacion.json"),
            "carpetas_procesadas": 2,
        }

    monkeypatch.setattr(pipeline, "validar_lote", validar)
    monkeypatch.setattr(pipeline, "generar_excel", lambda *args: Path(tmp_path / "salida.xlsx"))
    eventos = []
    pipeline.ejecutar_pipeline(tmp_path, config={"fase3": {}},
                               al_progreso=lambda fase, mensaje, detalle: eventos.append(
                                   (fase, mensaje, detalle)))

    parciales = [evento for evento in eventos if evento[2] and evento[2].get("resultado")]
    imagenes = [evento for evento in eventos if evento[2] and
                evento[2].get("imagenes_procesadas")]
    assert [evento[2]["procesadas"] for evento in parciales] == [1, 2]
    assert imagenes[0][2]["eta_segundos"] == 3.2
    assert [evento[2]["imagenes_procesadas"] for evento in imagenes] == [1, 2]
    assert eventos[-1][0] == "completado"
    assert eventos[-1][2]["porcentaje"] == 100
