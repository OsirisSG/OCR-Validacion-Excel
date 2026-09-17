import ast
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from pruebas.test_geometria_orientacion_unittest import entorno


class PuntuacionTest(unittest.TestCase):
    def test_adaptador_preserva_signos_sin_allowlist(self):
        tree = ast.parse((Path(__file__).resolve().parents[1]/'ocr_engine.py').read_text(encoding='utf-8'))
        clase = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MotorEasyOCR')
        clase.body = [n for n in clase.body if isinstance(n, ast.FunctionDef) and n.name in ('_leer', 'leer_texto_completo')]
        env = {'np': np, 'warnings': warnings}
        exec(compile(ast.Module(body=[clase], type_ignores=[]), 'adaptador', 'exec'), env)
        motor = env['MotorEasyOCR']()
        motor.dispositivo = 'cpu'
        motor._allowlist = '0123456789ABC'
        motor._batch_size, motor._workers = 1, 0
        llamadas = []
        texto = '10.04.25 / A-1: B,2'
        def readtext(im, **kwargs):
            llamadas.append(kwargs)
            return [([[0,0],[100,0],[100,20],[0,20]], texto, .95)]
        motor._reader = SimpleNamespace(readtext=readtext)
        lineas = motor.leer_texto_completo(np.zeros((30,120,3)))
        self.assertNotIn('allowlist', llamadas[0])
        self.assertEqual(entorno['reconstruir_lineas_texto'](lineas)[0]['texto'], texto)


if __name__ == '__main__': unittest.main()
