import ast
import tempfile
import unittest
from pathlib import Path
from aprendizaje import GestorAprendizaje
from aprendizaje import hash_archivo
from types import SimpleNamespace


class SobrescrituraPublicaTest(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'dashboard/backend/app.py').read_text(encoding='utf-8'))
        f = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_aplicar_correcciones_publicas')
        env = {'_bbox_igual': lambda a,b: a == b}
        exec(compile(ast.Module(body=[f], type_ignores=[]), 'publicar', 'exec'), env)
        self.publicar = env['_aplicar_correcciones_publicas']

    def test_bloque_completo_y_segunda_correccion(self):
        ocr = {'texto_completo': 'ABC\nDEF', 'lineas_texto': [{'texto':'ABC','bbox':[0,0,20,10]}]}
        historial = [{'texto_ocr':'ABC\nDEF','texto_correcto':'A.1\nD.2','bbox':None},
                     {'texto_ocr':'A.1\nD.2','texto_correcto':'A.3\nD.4','bbox':None}]
        self.assertEqual(self.publicar(ocr, historial)['texto_completo'], 'A.3\nD.4')

    def test_sobrescritura_encadenada_y_otra_caja_intacta(self):
        ocr = {'lineas_texto':[{'texto':'ABC','bbox':[0,0,20,10]}, {'texto':'ABC','bbox':[30,0,20,10]}]}
        historial = [{'texto_ocr':'ABC','texto_correcto':'A.1','bbox':[0,0,20,10]},
                     {'texto_ocr':'A.1','texto_correcto':'A.2','bbox':[0,0,20,10]}]
        r = self.publicar(ocr, historial)
        self.assertEqual([u['texto'] for u in r['lineas_texto']], ['A.2','ABC'])

    def test_exportacion_reutiliza_confirmacion_tras_reabrir(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp)/'imagen.jpg'; ruta.write_bytes(b'foto')
            gestor = GestorAprendizaje({'aprendizaje':{}}, directorio=tmp)
            gestor.registrar_correccion('ABC','A.1',ruta_imagen=str(ruta),bbox=[0,0,20,10])
            gestor.registrar_correccion('ABC','A.2',ruta_imagen=str(ruta),bbox=[0,0,20,10])
            gestor = GestorAprendizaje({'aprendizaje':{}}, directorio=tmp)
            ocr = {'lineas_texto':[{'texto':'ABC','bbox':[0,0,20,10]}]}
            r = gestor.filtrar_no_texto(ocr,ruta)
            self.assertEqual(r['lineas_texto'][0]['texto'],'A.2')

    def test_handler_sobrescribe_bloque_completo_y_union_persistidos(self):
        from utilidades.edicion_zonas import guardar
        with tempfile.TemporaryDirectory() as tmp:
            ruta=Path(tmp)/'foto.jpg'; ruta.write_bytes(b'foto')
            gestor=GestorAprendizaje({'aprendizaje':{}},directorio=tmp)
            gestor.registrar_muestra_visual=lambda *a,**k: {}
            ocr={'dimensiones':[100,100],'texto_completo':'ABC',
                 'lineas_texto':[{'texto':'ABC','bbox':[0,0,20,10]}]}
            item={'id':'foto','ruta':str(ruta),'resultado_ocr':ocr}
            env={'SolicitudCorreccion':SimpleNamespace,'_cargar_datos':lambda:{'resultados':[{'imagenes':[item]}]},
                 '_id_fila':lambda f:'caso','GestorAprendizaje':lambda c:gestor,'CONFIG':{},
                 '_fila_publica':lambda f:{'revision':{'estado':'parcial'}},
                 '_resolver_raiz_datos':lambda d:Path(tmp),'_resolver_imagen':lambda *a:ruta,
                 '_regenerar_excel':lambda r:None,'_bbox_igual':lambda a,b:a==b,
                 'normalizar_codigo':lambda s:s,'hash_archivo':hash_archivo}
            tree=ast.parse((Path(__file__).resolve().parents[1]/'dashboard/backend/app.py').read_text(encoding='utf-8'))
            functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in
                       ('corregir_lectura','_buscar_unidad_ocr','_aplicar_correcciones_publicas')]
            for n in functions:n.decorator_list=[]
            exec(compile(ast.Module(body=functions,type_ignores=[]),'handler','exec'),env)
            req=SimpleNamespace(prueba_id='caso',imagen_id='foto',campo='etiqueta',texto_ocr='ABC',
                texto_correcto='A.1',bbox=None,accion='corregir',usuario='test')
            for texto in ['A.1','B.2','A.1']:
                req.texto_correcto=texto
                env['corregir_lectura'](req)
                self.assertEqual(gestor.filtrar_no_texto(ocr,ruta)['texto_completo'],texto)
            with gestor._conectar() as con: guardar(con,hash_archivo(ruta),ocr,[0,0,20,10],'UNION.1')
            req.bbox=[0,0,20,10]
            for original,texto in [('UNION.1','UNION.2'),('UNION.2','UNION.3')]:
                req.texto_ocr=original;req.texto_correcto=texto
                env['corregir_lectura'](req)
                nuevo=GestorAprendizaje({'aprendizaje':{}},directorio=tmp)
                r=nuevo.filtrar_no_texto(ocr,ruta)
                self.assertEqual(r['lineas_texto'][0]['texto'],texto)
                self.assertEqual(r['texto_completo'],texto)


if __name__ == '__main__': unittest.main()
