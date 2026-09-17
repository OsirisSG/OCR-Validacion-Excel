import tempfile
import unittest
from pathlib import Path
from aprendizaje import GestorAprendizaje


class OrientacionesGuardadas(unittest.TestCase):
    def test_persistencia_aislamiento_y_restauracion(self):
        with tempfile.TemporaryDirectory() as d:
            ruta=Path(d)/'imagen.bin'
            ruta.write_bytes(b'contenido original')
            gestor=GestorAprendizaje({'aprendizaje':{}},directorio=Path(d)/'memoria')
            self.assertEqual(gestor.orientaciones_regionales(ruta),{})
            gestor.guardar_orientacion_regional(ruta,'a'*64,90)
            gestor.guardar_orientacion_regional(ruta,'b'*64,0)
            nuevo=GestorAprendizaje({'aprendizaje':{}},directorio=Path(d)/'memoria')
            self.assertEqual(nuevo.orientaciones_regionales(ruta),{'a'*64:90,'b'*64:0})
            nuevo.guardar_orientacion_regional(ruta,'a'*64,None)
            self.assertEqual(nuevo.orientaciones_regionales(ruta),{'b'*64:0})
            ruta.write_bytes(b'imagen reemplazada')
            self.assertEqual(nuevo.orientaciones_regionales(ruta),{})

    def test_rechaza_angulos_invalidos(self):
        with tempfile.TemporaryDirectory() as d:
            gestor=GestorAprendizaje({'aprendizaje':{}},directorio=Path(d))
            with self.assertRaises(ValueError):
                gestor.guardar_orientacion_regional(Path(d)/'no-existe','a'*64,45)


if __name__=='__main__': unittest.main()
