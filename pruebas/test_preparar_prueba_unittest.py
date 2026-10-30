import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from zipfile import ZipFile
import preparar_prueba_ocr as modulo


class PrepararPrueba(unittest.TestCase):
    def test_archiva_solo_progreso_despues_del_respaldo(self):
        with tempfile.TemporaryDirectory() as d:
            raiz=Path(d)
            (raiz/'.cache_ocr').mkdir()
            (raiz/'.aprendizaje').mkdir()
            progreso=raiz/'.cache_ocr/estado_pipeline.json'
            progreso.write_text('{"estado":"pausado"}')
            aprendizaje=raiz/'.aprendizaje/dato.txt'
            aprendizaje.write_text('correcciones importantes')
            resultados=raiz/'validacion_resultados.json'
            resultados.write_text('{"resultados":[]}')
            socket=MagicMock()
            socket.__enter__.return_value.connect_ex.return_value=1
            with patch.object(modulo,'__file__',str(raiz/'preparar_prueba_ocr.py')), \
                 patch.object(modulo,'cargar_config',return_value={}), \
                 patch('sys.argv',['preparar_prueba_ocr.py','--preparar']), \
                 patch.object(modulo.socket,'socket',return_value=socket):
                modulo.main()
            self.assertFalse(progreso.exists())
            self.assertEqual(aprendizaje.read_text(),'correcciones importantes')
            self.assertTrue(resultados.exists())
            archivo=next((raiz/'respaldos_pruebas').rglob('*.zip'))
            with ZipFile(archivo) as z:
                self.assertIsNone(z.testzip())
                self.assertIn('.cache_ocr/estado_pipeline.json',z.namelist())
                self.assertIn('.aprendizaje/dato.txt',z.namelist())
            self.assertTrue((archivo.parent/'progreso_anterior/.cache_ocr/estado_pipeline.json').is_file())

    def test_bloquea_si_servidor_abierto(self):
        with tempfile.TemporaryDirectory() as d:
            socket=MagicMock()
            socket.__enter__.return_value.connect_ex.return_value=0
            with patch.object(modulo,'__file__',str(Path(d)/'preparar_prueba_ocr.py')), \
                 patch.object(modulo,'cargar_config',return_value={}), \
                 patch('sys.argv',['preparar_prueba_ocr.py','--preparar']), \
                 patch.object(modulo.socket,'socket',return_value=socket):
                with self.assertRaises(RuntimeError): modulo.main()
            self.assertFalse((Path(d)/'respaldos_pruebas').exists())


if __name__=='__main__': unittest.main()
