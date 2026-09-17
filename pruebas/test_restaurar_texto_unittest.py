import ast
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from aprendizaje import GestorAprendizaje, hash_archivo


class RestaurarTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ruta = Path(self.tmp.name)/'foto.jpg'
        self.ruta.write_bytes(b'foto')
        self.gestor = GestorAprendizaje({'aprendizaje':{}}, directorio=self.tmp.name)
        self.gestor.registrar_imagen_sin_datos(self.ruta, 'caso')
        self.gestor.registrar_correccion('ABC','ABC.',ruta_imagen=str(self.ruta),bbox=[0,0,10,10])
        self.item = {'id':'foto','ruta':str(self.ruta),'estado_imagen':'revisada_sin_datos',
                     'revision_sin_datos':{},'resultado_ocr':{'texto_completo':'ABC',
                     'tokens':[{'texto':'ABC','bbox':[0,0,10,10]}],'estado_imagen':'revisada_sin_datos'}}
        datos = {'resultados':[{'imagenes':[self.item], 'trazabilidad':[{'ruta_absoluta':str(self.ruta)}]}]}
        self.guardado = []
        self.env = {'SolicitudImagenSinDatos':SimpleNamespace,'_pipeline_hilo':None,
            'GestorAprendizaje':lambda c:self.gestor,'CONFIG':{},'deepcopy':deepcopy,
            '_cargar_datos':lambda:datos,'_id_fila':lambda f:'caso',
            '_resolver_raiz_datos':lambda d:Path(self.tmp.name),
            '_resolver_imagen':lambda *a:self.ruta,'RUTA_VALIDACION':'resultado.json',
            'hash_archivo':hash_archivo,'_guardar_json_atomico':lambda p,d:self.guardado.append(d),
            '_cache':{},'_regenerar_excel':lambda r:r.update(excel_pendiente=True)}
        tree=ast.parse((Path(__file__).resolve().parents[1]/'dashboard/backend/app.py').read_text(encoding='utf-8'))
        funciones=[f for f in tree.body if isinstance(f,ast.FunctionDef) and f.name in
                   ('_restaurar_estado_con_texto','restaurar_imagen_con_texto')]
        for f in funciones: f.decorator_list=[]
        exec(compile(ast.Module(body=funciones,type_ignores=[]),'restaurar','exec'),self.env)

    def llamar(self):
        return self.env['restaurar_imagen_con_texto'](SimpleNamespace(tipo='carpeta',prueba_id='caso',imagen_id='foto'))

    def test_restaura_conservando_texto_y_correcciones(self):
        self.assertTrue(self.llamar()['excel_pendiente'])
        self.assertIsNone(self.gestor.imagen_sin_datos(self.ruta))
        nuevo=self.guardado[-1]['resultados'][0]['imagenes'][0]
        self.assertEqual(nuevo['estado_imagen'],'pendiente')
        self.assertNotIn('revision_sin_datos',nuevo)
        self.assertEqual(nuevo['resultado_ocr']['tokens'],self.item['resultado_ocr']['tokens'])
        self.assertEqual(len(self.gestor.listar_correcciones_texto([self.ruta])),1)
        self.assertTrue(self.llamar()['restaurada'])

    def test_fallo_guardado_no_elimina_marca(self):
        def falla(*a): raise OSError('archivo ocupado')
        self.env['_guardar_json_atomico']=falla
        with self.assertRaises(OSError): self.llamar()
        self.assertIsNotNone(self.gestor.imagen_sin_datos(self.ruta))

    def test_formato_externo_conserva_lecturas(self):
        item={'estado_imagen':'revisada_sin_datos','revision_sin_datos':{},'texto_completo':'ABC'}
        self.env['_restaurar_estado_con_texto'](item)
        self.assertEqual(item,{'estado_imagen':'pendiente','texto_completo':'ABC'})


if __name__ == '__main__': unittest.main()
