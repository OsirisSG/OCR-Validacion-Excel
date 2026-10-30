import tempfile
import threading
import time
import unittest
from pathlib import Path

from utilidades.cola_excel import ColaExcel


class PruebasColaExcel(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ruta = Path(self.temp.name) / 'cola.sqlite3'

    def test_agrupa_y_recupera_despues_de_reinicio(self):
        cola = ColaExcel(self.ruta, lambda: 'maestro.xlsx')
        for _ in range(20):
            cola.solicitar()
        llamadas = []
        reiniciada = ColaExcel(self.ruta, lambda: llamadas.append(1) or 'maestro.xlsx')
        self.assertEqual(reiniciada.estado()['pendientes'], 20)
        self.assertTrue(reiniciada.procesar())
        self.assertEqual(llamadas, [1])
        self.assertEqual(reiniciada.estado()['pendientes'], 0)

    def test_error_conserva_trabajo_y_reintenta(self):
        def bloqueado():
            raise PermissionError('Excel abierto')
        cola = ColaExcel(self.ruta, bloqueado)
        cola.solicitar()
        self.assertFalse(cola.procesar())
        self.assertEqual(cola.estado()['estado'], 'error')
        reiniciada = ColaExcel(self.ruta, lambda: 'maestro.xlsx')
        self.assertEqual(reiniciada.estado()['pendientes'], 1)
        self.assertTrue(reiniciada.procesar())
        self.assertIsNone(reiniciada.estado()['error'])

    def test_no_pierde_cambios_mientras_exporta(self):
        dentro, continuar = threading.Event(), threading.Event()
        def exportar():
            dentro.set()
            if not continuar.wait(3):
                raise TimeoutError('La prueba no liberó el exportador')
            return 'maestro.xlsx'
        cola = ColaExcel(self.ruta, exportar)
        cola.solicitar()
        hilo = threading.Thread(target=cola.procesar)
        hilo.start()
        try:
            self.assertTrue(dentro.wait(2))
            cola.solicitar()
            self.assertEqual(cola.estado()['estado'], 'actualizando')
        finally:
            continuar.set()
            hilo.join(3)
        self.assertEqual(cola.estado()['pendientes'], 1)
        cola.procesar()
        self.assertEqual(cola.estado()['pendientes'], 0)

    def test_solicitudes_simultaneas(self):
        cola = ColaExcel(self.ruta, lambda: 'maestro.xlsx')
        hilos = [threading.Thread(target=cola.solicitar) for _ in range(12)]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join()
        self.assertEqual(cola.estado()['pendientes'], 12)

    def test_debounce_deslizante_agrupa_correcciones_rapidas(self):
        llamadas = []
        cola = ColaExcel(
            self.ruta, lambda: llamadas.append(time.monotonic()) or 'maestro.xlsx',
            demora=0.08, latencia_maxima=0.30)
        cola.iniciar()
        try:
            cola.solicitar()
            time.sleep(0.03)
            cola.solicitar()
            time.sleep(0.03)
            cola.solicitar()
            limite = time.monotonic() + 2.0
            while time.monotonic() < limite and cola.estado()['pendientes']:
                time.sleep(0.02)
            self.assertEqual(cola.estado()['pendientes'], 0)
            self.assertEqual(len(llamadas), 1)
        finally:
            cola.detener()



if __name__ == '__main__':
    unittest.main()
