from pathlib import Path
import tempfile

import numpy as np

from aprendizaje import GestorAprendizaje
from ocr_engine import _leer_recorte_orientado


def _crear_img(path: Path, semilla: int):
    path.write_bytes((f"imagen-{semilla}" * 20).encode("utf-8"))


def _estrategia(ajuste=-7, variante="clahe"):
    return {
        "orientacion_base": 90,
        "ajuste_manual": ajuste,
        "variante": variante,
        "tipo_esperado": "codigo",
        "texto_resultado": "S4054664",
        "confianza": .82,
        "congruencia": 86,
        "origen": "relectura_manual",
    }


def test_soporte_es_por_imagen_y_no_por_clic_repetido():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        gestor = GestorAprendizaje({"aprendizaje": {"activar": True,
            "estrategias_ocr": {"activar": True, "minimo_soporte_sugerencia": 2,
                "minimo_soporte_automatico": 4, "dominancia_minima": .75}}}, base / ".aprendizaje")
        img = base / "grupo" / "a.jpg"; img.parent.mkdir(); _crear_img(img, 1)
        bbox, dims = [100, 100, 200, 80], [1000, 800]
        gestor.registrar_estrategia_ocr(img, bbox, dims, _estrategia(-7), contexto={"fase":"1st","campo":"etiqueta"})
        gestor.registrar_estrategia_ocr(img, bbox, dims, _estrategia(-6), contexto={"fase":"1st","campo":"etiqueta"})
        sugerida = gestor.sugerir_estrategia_ocr(img, bbox, dims, {"fase":"1st","campo":"etiqueta"})
        assert sugerida["soporte"] == 1
        assert sugerida["nivel"] == "recordada"
        assert not sugerida["auto_aplicable"]
        assert -7 <= sugerida["ajuste"] <= -5


def test_dos_imagenes_sugieren_y_cuatro_consolidan():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        gestor = GestorAprendizaje({"aprendizaje": {"activar": True,
            "estrategias_ocr": {"activar": True, "minimo_soporte_sugerencia": 2,
                "minimo_soporte_automatico": 4, "dominancia_minima": .75,
                "tolerancia_ajuste_grados": 4}}}, base / ".aprendizaje")
        bbox, dims = [100, 100, 200, 80], [1000, 800]
        rutas=[]
        for i,aj in enumerate((-6,-7,-8,-6),1):
            img=base/"grupo"/f"{i}.jpg"; img.parent.mkdir(exist_ok=True); _crear_img(img,i); rutas.append(img)
            gestor.registrar_estrategia_ocr(img,bbox,dims,_estrategia(aj),
                contexto={"fase":"1st","campo":"etiqueta","tipo_st":"A"})
            sug=gestor.sugerir_estrategia_ocr(img,bbox,dims,{"fase":"1st","campo":"etiqueta","tipo_st":"A"})
            if i==2:
                assert sug["nivel"] == "sugerida"
                assert not sug["auto_aplicable"]
        sug=gestor.sugerir_estrategia_ocr(rutas[-1],bbox,dims,{"fase":"1st","campo":"etiqueta","tipo_st":"A"})
        assert sug["soporte"] == 4
        assert sug["nivel"] == "automatica"
        assert sug["auto_aplicable"]
        assert sug["orientacion_base"] == 90
        assert sug["variante"] == "clahe"


class MotorConstante:
    def leer_texto_completo(self, imagen):
        return [{"texto":"S4054664", "confianza":.80, "bbox":[1,1,20,8]}]


def test_motor_puede_priorizar_patron_consolidado_sin_aceptar_ruido():
    imagen=np.zeros((40,80,3),dtype=np.uint8)
    _, info=_leer_recorte_orientado(imagen, MotorConstante(), ajuste_fino=False,
        estrategia_preferida={"auto_aplicable":True,"orientacion_base":90,"ajuste":0,
            "variante":"original","tipo_esperado":"codigo","soporte":5,"dominancia":.8})
    assert info["orientacion_recomendada_grados"] == 90
    assert any(c["grados"] == 90 and c["recomendada"] for c in info["candidatos_orientacion"])
