import cv2
import numpy as np

from ocr_engine import (_seleccionar_pasada, aplicar_variante,
                        detectar_regiones_texto, reconstruir_lineas_texto)


class MotorPorOrientacion:
    nombre = "falso"

    def leer(self, imagen):
        alto, ancho = imagen.shape[:2]
        if alto > ancho:
            return [{"texto": "AB-1234", "bbox": (2, 2, 14, 5), "confianza": 0.91}]
        return []


class MotorSiempreLegible:
    nombre = "falso"

    def leer(self, imagen):
        return [{"texto": "XY-9876", "bbox": (2, 2, 14, 5), "confianza": 0.95}]


class MotorSoloRelieve:
    nombre = "falso"

    def leer(self, imagen):
        if float(np.mean(imagen)) < 30:
            return [{"texto": "PL-2048", "bbox": (2, 2, 14, 5), "confianza": 0.88}]
        return []


def _config_fase1():
    return {
        "umbral_confianza": 0.5,
        "umbral_espacio_px": 10,
        "preprocesamiento": {
            "activar": True,
            "deskew": False,
            "binarizacion_adaptativa": False,
            "busqueda_adaptativa": {
                "modo": "adaptativo",
                "orientaciones": [0, 90, 180, 270],
                "variantes_respaldo": ["clahe", "relieve"],
                "confianza_codigo_suficiente": 0.7,
            },
        },
        "qr": {"tamano_min_px": 40},
    }


def test_selecciona_etiqueta_vertical_y_reporta_orientacion():
    imagen_horizontal = np.full((20, 40, 3), 127, dtype=np.uint8)

    pasada, intentos = _seleccionar_pasada(
        imagen_horizontal, _config_fase1(), MotorPorOrientacion())

    assert pasada["lineas"][0]["texto"] == "AB-1234"
    assert pasada["grados"] == 90.0
    assert {i["orientacion_grados"] for i in intentos} == {0, 90, 180, 270}


def test_detiene_busqueda_si_codigo_inicial_es_solido():
    imagen = np.full((20, 40, 3), 127, dtype=np.uint8)

    pasada, intentos = _seleccionar_pasada(imagen, _config_fase1(), MotorSiempreLegible())

    assert pasada["grados"] == 0.0
    assert len(intentos) == 1


def test_codigo_solo_numerico_largo_tambien_detiene_busqueda():
    class MotorNumerico:
        nombre = "falso"

        def leer(self, imagen):
            return [{"texto": "96819216", "bbox": (2, 2, 20, 5), "confianza": 0.90}]

    imagen = np.full((20, 40, 3), 127, dtype=np.uint8)
    pasada, intentos = _seleccionar_pasada(imagen, _config_fase1(), MotorNumerico())

    assert pasada["lineas"][0]["texto"] == "96819216"
    assert len(intentos) == 1


def test_variantes_para_grabado_conservan_dimensiones_y_cambian_contraste():
    imagen = np.full((80, 160, 3), 120, dtype=np.uint8)
    imagen[25:55, 35:125] = 145
    cfg = {"clahe_clip_limit": 3.0, "clahe_grid_size": 8, "relieve_kernel": 9}

    clahe = aplicar_variante(imagen, "clahe", cfg)
    relieve = aplicar_variante(imagen, "relieve", cfg)

    assert clahe.shape == imagen.shape
    assert relieve.shape == imagen.shape
    assert np.ptp(relieve) > 0
    assert not np.array_equal(clahe, imagen)


def test_activa_ruta_de_relieve_si_las_lecturas_normales_fallan():
    imagen = np.full((80, 160, 3), 120, dtype=np.uint8)
    imagen[25:55, 35:125] = 145

    pasada, intentos = _seleccionar_pasada(imagen, _config_fase1(), MotorSoloRelieve())

    assert pasada["variante"] == "relieve"
    assert pasada["lineas"][0]["texto"] == "PL-2048"
    assert any(i["variante"] == "relieve" for i in intentos)


def test_detecta_region_horizontal_de_codigo_sin_posicion_fija():
    imagen = np.full((260, 700, 3), 145, dtype=np.uint8)
    cv2.putText(imagen, "ABC-12345", (190, 155), cv2.FONT_HERSHEY_SIMPLEX,
                2.0, (105, 105, 105), 5, cv2.LINE_AA)

    regiones = detectar_regiones_texto(imagen, {
        "max_regiones": 6,
        "margen_horizontal_factor": 0.8,
        "margen_vertical_factor": 0.8,
    })

    assert regiones
    assert any(x < 250 < x + w and y < 140 < y + h for x, y, w, h in regiones)


def test_reconstruye_espacios_y_saltos_de_linea():
    lineas = [
        {"texto": "CODIGO", "bbox": (10, 10, 60, 12), "confianza": 0.98},
        {"texto": "A1", "bbox": (82, 10, 18, 12), "confianza": 0.96},
        {"texto": "LOTE 2026", "bbox": (10, 42, 85, 12), "confianza": 0.94},
    ]

    reconstruidas = reconstruir_lineas_texto(lineas)

    assert [fila["texto"] for fila in reconstruidas] == ["CODIGO A1", "LOTE 2026"]
    assert "\n".join(fila["texto"] for fila in reconstruidas) == "CODIGO A1\nLOTE 2026"
