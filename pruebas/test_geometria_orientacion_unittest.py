"""Pruebas aisladas de decisión y coordenadas; no ejecutan EasyOCR ni OpenCV."""
import ast
import re
import unittest
from pathlib import Path
import numpy as np


class Transformacion:
    @staticmethod
    def perspectiveTransform(puntos, matriz):
        p=np.concatenate([puntos,np.ones((*puntos.shape[:-1],1))],axis=-1)
        q=p@matriz.T
        return q[...,:2]/q[...,2:3]


arbol=ast.parse((Path(__file__).resolve().parents[1]/'ocr_engine.py').read_text(encoding='utf-8'))
funciones=[n for n in arbol.body if isinstance(n,ast.FunctionDef) and n.name in
           {'_bbox_proyectada','_leer_recorte_orientado','reconstruir_lineas_texto','_agrupar_por_filas'}]
entorno={'np':np,'re':re,'cv2':Transformacion,'_rotar_recto':lambda img,a:np.rot90(img,-a//90),
         'aplicar_variante':lambda img,*args:img,'_calidad':lambda ls:(len(ls),0)}
exec(compile(ast.Module(body=funciones,type_ignores=[]),'geometria','exec'),entorno)


class TestGeometria(unittest.TestCase):
    def test_proyeccion_90_y_escala(self):
        self.assertEqual(entorno['_bbox_proyectada']([10,20,30,40],
            np.array([[0,1,0],[-1,0,100],[0,0,1]],float)),[20,60,40,30])
        self.assertEqual(entorno['_bbox_proyectada']([10,20,30,40],
            np.array([[.5,0,5],[0,.5,7],[0,0,1]],float)),[10,17,15,20])

    def test_duda_y_prioridad_manual(self):
        class Motor:
            llamadas=0
            def leer_texto_completo(self,imagen):
                self.llamadas+=1
                return [{'texto':'ABC8','bbox':[1,1,3,3],'confianza':.9}]
        motor=Motor()
        _,info=entorno['_leer_recorte_orientado'](np.zeros((20,40,3)),motor)
        self.assertTrue(info['orientacion_dudosa']); self.assertEqual(info['orientacion_grados'],0)
        self.assertEqual(motor.llamadas,4)
        motor=Motor()
        _,info=entorno['_leer_recorte_orientado'](np.zeros((20,40,3)),motor,False)
        self.assertEqual(motor.llamadas,1); self.assertFalse(info['orientacion_dudosa'])

    def test_empate_no_restaura_cero_si_gana_noventa(self):
        class Motor:
            llamadas=0
            def leer_texto_completo(self,imagen):
                confianza=[.85,.90,.84,.83][self.llamadas]
                self.llamadas+=1
                return [{'texto':'ABC123','bbox':[1,1,10,3],'confianza':confianza}]
        _,info=entorno['_leer_recorte_orientado'](np.zeros((20,40,3)),Motor())
        self.assertTrue(info['orientacion_dudosa'])
        self.assertEqual(info['orientacion_grados'],90)
        self.assertEqual(len(info['candidatos_orientacion']),4)

    def test_texto_corto_no_se_declara_seguro(self):
        class Motor:
            def leer_texto_completo(self,imagen):
                return [{'texto':'1 1','bbox':[1,1,8,3],'confianza':.99}]
        _,info=entorno['_leer_recorte_orientado'](np.zeros((20,40,3)),Motor())
        self.assertTrue(info['orientacion_dudosa'])

    def test_orden_local_se_conserva_al_volver_a_vertical(self):
        class Motor:
            llamadas=0
            def leer_texto_completo(self,imagen):
                self.llamadas+=1
                return [{'texto':'AB','bbox':[1,1,8,3],'confianza':.9},
                        {'texto':'CD','bbox':[12,1,8,3],'confianza':.9}]
        motor=Motor()
        lineas,info=entorno['_leer_recorte_orientado'](
            np.zeros((30,40,3)),motor,orientacion_forzada=90)
        self.assertEqual(motor.llamadas,1)
        self.assertEqual(len(lineas),1)
        self.assertEqual(lineas[0]['texto'],'AB CD')
        self.assertGreater(lineas[0]['bbox'][3],lineas[0]['bbox'][2])
        self.assertTrue(info['orientacion_confirmada'])
        self.assertEqual(len(lineas[0]['poligono_lectura']),4)

if __name__=='__main__': unittest.main()
