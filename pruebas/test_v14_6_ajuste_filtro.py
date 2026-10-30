"""V14.6: ajuste fino acotado, congruencia semántica y filtros útiles."""
from unittest.mock import patch

import numpy as np

from ocr_engine import (_clasificar_informacion_region, _leer_recorte_orientado,
                        _perfil_congruencia_region)


def _lectura(texto, confianza=.8):
    return [{"texto": texto, "bbox": (4, 4, 80, 14), "confianza": confianza}]


def test_clasificador_prioriza_codigo_coherente_y_rechaza_ruido_mixto():
    codigo = _clasificar_informacion_region("S4054664", .80)
    minusculas = _clasificar_informacion_region("abc12345", .78)
    mixto = _clasificar_informacion_region("1CF5Dr", .97)
    basura = _clasificar_informacion_region("adrianaMat16/may0i20z50849971EAIur", .91)
    simbolos = _clasificar_informacion_region("21% : 50", .96)

    assert codigo["tipo_informacion"] == "codigo" and codigo["probable_codigo"]
    assert minusculas["tipo_informacion"] == "codigo" and minusculas["probable_codigo"]
    assert mixto["tipo_informacion"] == "ruido" and not mixto["probable_codigo"]
    assert basura["tipo_informacion"] == "ruido"
    assert simbolos["tipo_informacion"] != "codigo"
    assert codigo["score_informacion"] > mixto["score_informacion"]


def test_fecha_y_numero_no_se_confunden_con_codigo():
    fecha = _clasificar_informacion_region("16/MAY/2026", .70)
    numero = _clasificar_informacion_region("50", .95)
    serial = _clasificar_informacion_region("4054664", .70)
    assert fecha["tipo_informacion"] == "fecha" and not fecha["probable_codigo"]
    assert numero["tipo_informacion"] == "numero" and not numero["probable_codigo"]
    assert serial["tipo_informacion"] == "codigo" and serial["probable_codigo"]


def test_perfil_codigo_gana_a_numero_corto_aunque_tenga_mas_confianza():
    codigo = _perfil_congruencia_region(_lectura("S4054664", .70), .70)
    numero = _perfil_congruencia_region(_lectura("50", .99), .99)
    assert codigo["clave"] > numero["clave"]


class MotorExtendido:
    nombre = "falso"
    def leer_texto_completo(self, imagen):
        h, w = imagen.shape[:2]
        fino = not ((h, w) == (40, 120))
        return _lectura("ABC12345", .92 if fino else .62)


def test_ajuste_extendido_solo_con_evidencia_geometrica_fuerte():
    imagen = np.zeros((40, 120, 3), dtype=np.uint8)
    with patch("ocr_engine.estimar_skew", return_value=-24.0), \
         patch("ocr_engine._evidencia_skew", return_value={"soporte": 1, "dispersion": 8, "cobertura": .01, "fuerte": False}):
        _, info = _leer_recorte_orientado(imagen, MotorExtendido(), permitir_giro=False,
                                           ajuste_fino=True, angulo_fino_max=15,
                                           angulo_fino_extendido_max=30)
    c = info["candidatos_orientacion"][0]
    assert c["ajuste_fino_grados"] == 0.0
    assert c["ajuste_fino_modo"] == "ninguno"

    with patch("ocr_engine.estimar_skew", return_value=-24.0), \
         patch("ocr_engine._evidencia_skew", return_value={"soporte": 3, "dispersion": 1.2, "cobertura": .10, "fuerte": True}):
        _, info = _leer_recorte_orientado(imagen, MotorExtendido(), permitir_giro=False,
                                           ajuste_fino=True, angulo_fino_max=15,
                                           angulo_fino_extendido_max=30)
    c = info["candidatos_orientacion"][0]
    assert 21.9 <= c["ajuste_fino_grados"] <= 26.1
    assert c["ajuste_fino_modo"] == "extendido"
    assert c["ajuste_fino_confiable"] is True


def test_ajuste_nunca_se_extiende_a_36_o_45_grados():
    imagen = np.zeros((40, 120, 3), dtype=np.uint8)
    with patch("ocr_engine.estimar_skew", return_value=-36.0), \
         patch("ocr_engine._evidencia_skew", return_value={"soporte": 5, "dispersion": 0.2, "cobertura": .2, "fuerte": True}):
        _, info = _leer_recorte_orientado(imagen, MotorExtendido(), permitir_giro=False,
                                           ajuste_fino=True, angulo_fino_max=45,
                                           angulo_fino_extendido_max=45)
    c = info["candidatos_orientacion"][0]
    assert c["ajuste_fino_grados"] == 0.0


class MotorMicro:
    nombre = "falso"
    def leer_texto_completo(self, imagen):
        marca = int(imagen[0, 0, 1])
        conf = {0: .60, 5: .74, 7: .79, 9: .96}.get(marca, .50)
        return _lectura("ABC12345", conf)


def test_microbusqueda_corrige_estimacion_un_poco_corta():
    imagen = np.zeros((40, 120, 3), dtype=np.uint8)
    def rotar(vista, grados):
        salida = vista.copy()
        salida[0, 0, 1] = int(round(abs(grados)))
        return salida, np.eye(3, dtype=float)
    with patch("ocr_engine.estimar_skew", return_value=-7.0), \
         patch("ocr_engine.rotar_imagen_libre_con_matriz", side_effect=rotar):
        _, info = _leer_recorte_orientado(imagen, MotorMicro(), permitir_giro=False,
                                           ajuste_fino=True, micro_ajuste_grados=2.0)
    c = info["candidatos_orientacion"][0]
    assert c["ajuste_fino_grados"] == 9.0
    assert c["texto"] == "ABC12345"
