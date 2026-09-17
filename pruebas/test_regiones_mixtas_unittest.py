"""Prueba el flujo regional real con detector/reconocedor simulados."""
import ast
import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path
import numpy as np
from pruebas.test_geometria_orientacion_unittest import entorno, arbol


class RegionesMixtas(unittest.TestCase):
    def test_foto_con_lecturas_perpendiculares(self):
        class Motor:
            nombre='simulado'
            llamadas=0
            def detectar(self, imagen):
                return [{'bbox':[5,5,40,20]}, {'bbox':[80,5,20,40]}]
            def leer_texto_completo(self, imagen):
                region, giro=divmod(self.llamadas,4)
                self.llamadas+=1
                confianza=.95 if giro==region else .65
                return [{'texto':f'CODIGO{region}', 'bbox':[1,1,12,5], 'confianza':confianza}]
        motor=Motor()
        contexto={**entorno,'time':time,'json':json,'hashlib':hashlib,
                  'cargar_imagen':lambda _:np.zeros((100,200,3),dtype=np.uint8),
                  'rotar_imagen_libre':lambda img,a:img,
                  'detectar_qrs':lambda *args:[], 'obtener_motor':lambda cfg:(motor,{}),
                  '_resumen_codigos':lambda tokens:[]}
        funciones=[n for n in arbol.body if isinstance(n,ast.FunctionDef)
                   and n.name=='extraer_texto_empresarial']
        exec(compile(ast.Module(body=funciones,type_ignores=[]),'flujo-regional','exec'),contexto)
        with tempfile.TemporaryDirectory() as d:
            foto=Path(d)/'foto.bin'
            foto.write_bytes(b'foto simulada')
            config={'aprendizaje':{'directorio':str(Path(d)/'memoria'),'activar':False},
                    'ocr':{'margen_recorte':0,'zoom_minimo':1,'zoom_maximo':1},'fase1':{}}
            resultado=contexto['extraer_texto_empresarial'](str(foto),config)
        self.assertEqual(motor.llamadas,8)
        self.assertEqual([r['orientacion_grados'] for r in resultado['recortes']],[0,90])
        self.assertEqual([r['texto'] for r in resultado['lineas_texto']],['CODIGO0','CODIGO1'])
        self.assertEqual(len(resultado['tokens']),2)
        self.assertEqual(tuple(resultado['lineas_texto'][1]['bbox'][2:]),(5,12))
        self.assertEqual(len(resultado['huella_imagen']),64)
        self.assertNotEqual(resultado['recortes'][0]['marco'],resultado['recortes'][1]['marco'])


if __name__=='__main__': unittest.main()
