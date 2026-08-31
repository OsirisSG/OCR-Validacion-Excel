"""La Fase 2 conserva y combina todas las imágenes de cada carpeta."""

from pathlib import Path

import validacion


def test_conserva_todas_las_imagenes_y_agrega_tokens(monkeypatch, tmp_path):
    nombres = ["frontal.jpg", "lateral.jpg", "info_referencia.jpg"]
    for nombre in nombres:
        (tmp_path / nombre).write_bytes(b"fixture")

    textos = {
        "frontal.jpg": "ABC-100",
        "lateral.jpg": "XYZ-200",
        "info_referencia.jpg": "ABC-100 XYZ-200",
    }

    def ocr(ruta, config):
        texto = textos[Path(ruta).name]
        piezas = texto.split()
        return {
            "imagen": ruta, "motor": "falso", "confianza_media": 0.9,
            "tokens": [{"texto": pieza, "bbox": (1 + i * 35, 2, 30, 10), "confianza": 0.9}
                       for i, pieza in enumerate(piezas)],
            "lineas_texto": [{"texto": texto, "bbox": (1, 2, 30, 10), "confianza": 0.9}],
            "texto_completo": texto, "qr_bbox": None, "num_lineas_ocr": 1,
        }

    monkeypatch.setattr(validacion, "extraer_texto", ocr)
    monkeypatch.setattr(
        validacion, "clasificar_archivo",
        lambda ruta, config: "candidato_referencia" if "info_referencia" in ruta else "fotografia")
    carpeta = {
        "ruta": str(tmp_path), "nombre": "01_A1_variante1", "conforme": True,
        "motivo_anomalia": None,
        "archivos": {"imagenes": nombres, "otros": [], "videos": []},
    }

    fila = validacion._validar_carpeta(
        carpeta, {"fase2": {}}, {"comparar_solo_tokens_codigo": True}, {}, None)

    assert len(fila["imagenes"]) == 3
    assert {item["rol"] for item in fila["imagenes"]} == {
        "etiqueta_principal", "etiqueta_adicional", "referencia"}
    assert fila["comparacion"]["resultado"] == "coincidencia_total"
    assert all(item["resultado_ocr"]["texto_completo"] for item in fila["imagenes"])
