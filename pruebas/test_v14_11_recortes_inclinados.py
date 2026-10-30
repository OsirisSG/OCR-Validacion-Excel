from pathlib import Path

import cv2
import numpy as np

from aprendizaje import GestorAprendizaje
from dashboard.backend.app import _recortar_region_revisada, _validar_poligono_recorte


def _gestor(tmp_path):
    return GestorAprendizaje({"aprendizaje": {"activar": True}}, directorio=tmp_path / "aprendizaje")


def test_rectifica_recorte_inclinado_sin_arrastrar_caja_horizontal():
    imagen = np.full((120, 220, 3), 255, dtype=np.uint8)
    poligono = [[45, 30], [165, 50], [160, 78], [40, 58]]
    puntos = _validar_poligono_recorte(poligono, [220, 120])
    recorte = _recortar_region_revisada(imagen, [40, 30, 125, 48], puntos)

    assert recorte.size > 0
    # La rectificación conserva aproximadamente el largo de la línea y una altura
    # pequeña, en vez de quedarse con toda la caja horizontal envolvente.
    assert 115 <= recorte.shape[1] <= 125
    assert 25 <= recorte.shape[0] <= 32


def test_region_entrenable_guarda_poligono_y_recorte_rectificado(tmp_path):
    ruta = tmp_path / "etiqueta.png"
    imagen = np.full((140, 240, 3), 240, dtype=np.uint8)
    cv2.line(imagen, (50, 45), (190, 70), (0, 0, 0), 8)
    ok, codificada = cv2.imencode(".png", imagen)
    assert ok
    codificada.tofile(str(ruta))

    gestor = _gestor(tmp_path)
    poligono = [[45, 34], [195, 60], [190, 86], [40, 60]]
    resultado = gestor.registrar_region(
        "S4054664", [40, 34, 155, 52], poligono=poligono,
        ruta_imagen=str(ruta), carpeta_id="caso-1", carpeta_nombre="Caso 1",
        imagen_nombre=ruta.name, entrenable=True,
        metadatos={"giro_foto": 0},
    )

    anotaciones = gestor.listar_anotaciones([ruta], carpeta_id="caso-1")
    assert len(anotaciones) == 1
    assert anotaciones[0]["poligono"] == poligono
    muestra = resultado["muestra_visual"]
    assert muestra and muestra["entrenable"] is True
    recorte = cv2.imdecode(np.fromfile(muestra["ruta_recorte"], dtype=np.uint8), cv2.IMREAD_COLOR)
    assert recorte is not None
    assert recorte.shape[1] > recorte.shape[0] * 4
