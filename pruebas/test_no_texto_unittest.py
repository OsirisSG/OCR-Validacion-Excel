import tempfile
import unittest
from pathlib import Path
from aprendizaje import GestorAprendizaje


class TestNoTexto(unittest.TestCase):
    def test_descarte_deshacer_y_aislamiento(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / 'foto.jpg'
            ruta.write_bytes(b'imagen-prueba')
            otra = Path(tmp) / 'otra.jpg'
            otra.write_bytes(b'otra-imagen')
            gestor = GestorAprendizaje({'aprendizaje': {}}, directorio=tmp)
            ocr = {'tokens': [{'texto':'8','bbox':[0,0,10,10]}, {'texto':'ABC','bbox':[20,0,30,10]}],
                   'lineas_texto':[{'texto':'8 ABC','bbox':[0,0,50,10]}], 'texto_completo':'8 ABC'}
            gestor.marcar_no_texto(ruta,[0,0,10,10],'8')
            filtrado = gestor.filtrar_no_texto(ocr,ruta)
            self.assertEqual(filtrado['texto_completo'],'ABC')
            self.assertEqual(ocr['texto_completo'],'8 ABC')
            self.assertEqual(gestor.filtrar_no_texto(ocr,otra)['texto_completo'],'8 ABC')
            gestor.marcar_no_texto(ruta,[0,0,10,10],'8',activo=False)
            self.assertEqual(gestor.filtrar_no_texto(ocr,ruta)['texto_completo'],'8 ABC')

    def test_descarte_linea_entera(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta=Path(tmp)/'foto'; ruta.write_bytes(b'foto')
            gestor=GestorAprendizaje({'aprendizaje':{}},directorio=tmp)
            ocr={'lineas_texto':[{'texto':'8','bbox':[1,1,8,8]}], 'texto_completo':'8'}
            gestor.marcar_no_texto(ruta,[1,1,8,8],'8')
            self.assertEqual(gestor.filtrar_no_texto(ocr,ruta)['texto_completo'],'')

if __name__ == '__main__':
    unittest.main()
