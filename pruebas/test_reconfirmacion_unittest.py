import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from copy import deepcopy
from aprendizaje import GestorAprendizaje, hash_archivo


class ReconfirmacionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ruta = Path(self.tmp.name)/'foto.jpg'
        self.ruta.write_bytes(b'foto')
        self.gestor = GestorAprendizaje({'aprendizaje':{}},directorio=self.tmp.name)
        self.gestor.registrar_muestra_visual = lambda *a,**k: {'entrenable':k.get('entrenable')}

    def guardar(self, texto):
        return self.gestor.registrar_correccion('ABC',texto,ruta_imagen=str(self.ruta),bbox=[0,0,10,10])

    def test_identica_y_repeticion_no_crean_duplicados(self):
        self.guardar('ABC')
        self.assertTrue(self.guardar('ABC')['duplicada'])
        self.assertEqual(len(self.gestor.listar_correcciones_texto([self.ruta])),1)

    def test_volver_a_una_correccion_anterior_es_la_vigente(self):
        self.guardar('A.1'); self.guardar('B.2'); self.guardar('A.1')
        correcciones = self.gestor.listar_correcciones_texto([self.ruta])
        self.assertEqual(len(correcciones),2)
        self.assertEqual(correcciones[-1]['texto_correcto'],'A.1')
        tokens=self.gestor.aplicar_memoria_imagen([{'texto':'ABC','bbox':[0,0,10,10]}],self.ruta)
        self.assertEqual(tokens[0]['texto'],'A.1')

    def test_aceptar_conserva_correccion_visible_en_handler(self):
        self.guardar('A.1')
        item={'id':'foto','ruta':str(self.ruta),'resultado_ocr':{
            'lineas_texto':[{'texto':'ABC','bbox':[0,0,10,10]}], 'texto_completo':'ABC'}}
        env={'SolicitudCorreccion':SimpleNamespace,'_cargar_datos':lambda:{'resultados':[{'imagenes':[item]}]},
             '_id_fila':lambda f:'caso','GestorAprendizaje':lambda c:self.gestor,'CONFIG':{},
             '_fila_publica':lambda f:{'revision':{'estado':'parcial'}},
             '_resolver_raiz_datos':lambda d:Path(self.tmp.name),'_resolver_imagen':lambda *a:self.ruta,
             '_regenerar_excel':lambda r:None,'_bbox_igual':lambda a,b:a==b,
             'normalizar_codigo':lambda s:s,'hash_archivo':hash_archivo}
        tree=ast.parse((Path(__file__).resolve().parents[1]/'dashboard/backend/app.py').read_text(encoding='utf-8'))
        functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in
                   ('corregir_lectura','_buscar_unidad_ocr','_orientacion_regional_pendiente','_aplicar_correcciones_publicas')]
        for n in functions:n.decorator_list=[]
        exec(compile(ast.Module(body=functions,type_ignores=[]),'handler','exec'),env)
        req=SimpleNamespace(prueba_id='caso',imagen_id='foto',campo='etiqueta',texto_ocr='ABC',
                            texto_correcto='A.1',bbox=[0,0,10,10],accion='aceptar',usuario='test')
        env['corregir_lectura'](req)
        self.assertEqual(self.gestor.listar_correcciones_texto([self.ruta])[-1]['texto_correcto'],'A.1')


if __name__=='__main__':unittest.main()
