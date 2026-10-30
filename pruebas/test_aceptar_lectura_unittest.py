import ast
import json
import tempfile
import unittest
from pathlib import Path
from aprendizaje import GestorAprendizaje, hash_archivo


class AceptarLecturaTest(unittest.TestCase):
    def test_aceptacion_previa_se_publica_y_persiste(self):
        with tempfile.TemporaryDirectory() as tmp:
            imagen = Path(tmp)/'foto.jpg'
            imagen.write_bytes(b'foto de prueba')
            gestor = GestorAprendizaje({'aprendizaje':{}}, directorio=tmp)
            with gestor._conectar() as con:
                for i, accion in enumerate(['aceptar','ilegible','no_es_campo']):
                    con.execute('''INSERT INTO muestras_visuales
                        (id,caso_id,imagen_hash,ruta_imagen,bbox_json,texto_ocr,texto_correcto,
                         accion,confirmada,creado_en) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                        (str(i),'caso',hash_archivo(imagen),str(imagen),json.dumps([i*20,0,10,10]),
                         '10.04.25','10.04.25',accion,1,'2026-09-16T10:00:00'))
            gestor = GestorAprendizaje({'aprendizaje':{}}, directorio=tmp)
            correcciones = gestor.listar_correcciones_texto([imagen])
            self.assertEqual(len(correcciones),1)
            self.assertEqual(correcciones[0]['fuente'],'aceptar_ocr')
            tree=ast.parse((Path(__file__).resolve().parents[1]/'dashboard/backend/app.py').read_text(encoding='utf-8'))
            f=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_aplicar_correcciones_publicas')
            env={'_bbox_igual':lambda a,b:a==b}
            exec(compile(ast.Module(body=[f],type_ignores=[]),'publicar','exec'),env)
            ocr={'lineas_texto':[{'texto':'10.04.25','bbox':[0,0,10,10]},
                                {'texto':'10.04.25','bbox':[20,0,10,10]}]}
            r=env['_aplicar_correcciones_publicas'](ocr,correcciones)
            self.assertTrue(r['lineas_texto'][0]['confirmado_manualmente'])
            self.assertNotIn('confirmado_manualmente',r['lineas_texto'][1])
            self.assertEqual(r['lineas_texto'][0]['texto'],'10.04.25')
            otra=Path(tmp)/'otra.jpg'; otra.write_bytes(b'otra foto')
            self.assertEqual(gestor.listar_correcciones_texto([otra]),[])


if __name__ == '__main__': unittest.main()
