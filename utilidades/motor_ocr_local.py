"""P47 · Motor OCR local para el tablero P42 y el overlay de vídeo cuando NO hay RapidOCR.

El lector del tablero (`tablero_campos`, `buscar_mas`, `codigos_modulo`, `video_overlay`) se
escribió contra RapidOCR: `motor(imagen) -> (resultado, tiempos)` con `resultado` como lista de
`(caja_4_puntos, texto, confianza)`. En la máquina del cliente el entorno `.venv_ocr` tiene el
motor del proyecto (EasyOCR/Paddle vía `ocr_engine.obtener_motor`) pero no `rapidocr_onnxruntime`;
sin este adaptador el tablero quedaba siempre en «OCR no disponible».

`MotorProyectoComoRapid` envuelve el motor del proyecto y devuelve EXACTAMENTE la forma de
RapidOCR, así que el resto del código no cambia. No instala nada ni usa red: si tampoco hay motor
del proyecto, la excepción sube y la corrida marca «OCR no disponible» (nunca «sin dato»).

La caché de lecturas P42 incluye `nombre_motor()` en su firma: lecturas hechas con un motor no se
reutilizan con el otro.
"""
from __future__ import annotations

import importlib.util


def rapidocr_instalado() -> bool:
    try:
        return importlib.util.find_spec("rapidocr_onnxruntime") is not None
    except (ImportError, ValueError):
        return False


def nombre_motor() -> str:
    """Nombre estable del motor que usará `codigos_modulo.motor_compartido()`."""
    return "rapidocr" if rapidocr_instalado() else "motor_proyecto"


class MotorProyectoComoRapid:
    """Adaptador: motor del proyecto (`leer_texto_completo`) con la interfaz de RapidOCR."""

    nombre = "motor_proyecto"

    def __init__(self, motor):
        if not hasattr(motor, "leer_texto_completo"):
            raise TypeError("el motor del proyecto no expone leer_texto_completo")
        self._motor = motor
        self.nombre = f"proyecto:{type(motor).__name__}"

    @classmethod
    def crear(cls, config: dict | None = None) -> "MotorProyectoComoRapid":
        import ocr_engine
        motor = ocr_engine.obtener_motor(config)
        if isinstance(motor, tuple):                      # obtener_motor -> (motor, cfg_fase1)
            motor = motor[0]
        return cls(motor)

    def __call__(self, imagen, *args, **kwargs):
        import numpy as np
        if imagen is not None and getattr(imagen, "ndim", 3) == 2:
            import cv2
            imagen = cv2.cvtColor(imagen, cv2.COLOR_GRAY2BGR)
        lineas = self._motor.leer_texto_completo(np.ascontiguousarray(imagen)) or []
        resultado = []
        for linea in lineas:
            if not isinstance(linea, dict):
                continue
            texto = str(linea.get("texto") or "").strip()
            if not texto:
                continue
            x, y, w, h = (float(v) for v in (tuple(linea.get("bbox") or (0, 0, 0, 0)) + (0, 0, 0, 0))[:4])
            caja = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
            try:
                confianza = float(linea.get("confianza") or 0.0)
            except (TypeError, ValueError):
                confianza = 0.0
            resultado.append([caja, texto, confianza])
        return (resultado or None), None
