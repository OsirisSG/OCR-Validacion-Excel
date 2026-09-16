import sqlite3
import unittest
from copy import deepcopy
from utilidades.edicion_zonas import aplicar, guardar, deshacer, expandir, firma, validar_caja, marco, guardar_bloque


class EdicionZonasTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.addCleanup(self.con.close)
        self.ocr = {"dimensiones": [500, 300], "lineas_texto": [
            {"texto": "10.04", "bbox": [10, 10, 40, 20]},
            {"texto": ".25", "bbox": [55, 10, 20, 20]},
            {"texto": "OTRO", "bbox": [200, 100, 40, 20]}]}
        self.ocr["tokens"] = deepcopy(self.ocr["lineas_texto"])
        self.ocr["texto_completo"] = "10.04\n.25\nOTRO"

    def test_guardar_puntos_saltos_y_original(self):
        guardar(self.con, "foto", self.ocr, [10,10,65,20], "10.04.25\nA-1 / B:2")
        r = aplicar(self.con, "foto", self.ocr)
        self.assertEqual(len(r["lineas_texto"]), 2)
        self.assertIn("10.04.25\nA-1 / B:2", r["texto_completo"])
        self.assertEqual(self.ocr["texto_completo"], "10.04\n.25\nOTRO")
        self.assertEqual(aplicar(self.con, "foto", r), r)

    def test_deshacer_persistido_restaura_original(self):
        guardar(self.con, "foto", self.ocr, [10,10,65,20], "10.04.25")
        r = aplicar(self.con, "foto", self.ocr)
        self.assertTrue(deshacer(self.con, "foto", r))
        self.assertEqual(aplicar(self.con, "foto", r), self.ocr)

    def test_uniones_sucesivas_deshacer_en_orden(self):
        guardar(self.con, "foto", self.ocr, [10,10,65,20], "10.04.25")
        primero = aplicar(self.con, "foto", self.ocr)
        guardar(self.con, "foto", primero, [10,10,230,110], "TODO")
        segundo = aplicar(self.con, "foto", primero)
        self.assertEqual(segundo["texto_completo"], "TODO")
        deshacer(self.con, "foto", segundo)
        self.assertEqual(aplicar(self.con, "foto", segundo), primero)

    def test_aislamiento_imagen_y_rotacion(self):
        guardar(self.con, "foto", self.ocr, [10,10,65,20], "CORRECTO")
        self.assertEqual(aplicar(self.con, "otra", self.ocr), self.ocr)
        girado = {**self.ocr, "rotacion_manual_aplicada_grados": 90}
        self.assertEqual(aplicar(self.con, "foto", girado), girado)

    def test_bloques_parciales_se_incluyen_enteros(self):
        self.assertEqual(expandir([30,15,30,5], self.ocr), [10,10,65,20])

    def test_limites(self):
        for b in ([-1,0,10,10], [490,0,20,10], [0,0,1,10]):
            with self.assertRaises(ValueError): validar_caja(b, [500,300])

    def test_firma_detecta_cambios(self):
        self.assertNotEqual(firma(self.ocr, "a"), firma(self.ocr, "b"))
        modificado = deepcopy(self.ocr)
        modificado["lineas_texto"][0]["texto"] = "CORREGIDO"
        self.assertNotEqual(firma(self.ocr, "a"), firma(modificado, "a"))

    def test_marco_publico_compatible(self):
        self.assertEqual(marco(self.ocr), marco({**self.ocr, "orientacion_texto_base_grados": 0}))

    def test_ajustar_no_absorbe_vecino(self):
        guardar_bloque(self.con, "foto", self.ocr, [10,10,40,20],
                       [{"bbox":[10,10,20,20], "texto":"10."}])
        r = aplicar(self.con, "foto", self.ocr)
        self.assertEqual([u["texto"] for u in r["lineas_texto"]], ["10.",".25","OTRO"])
        self.assertEqual(r["lineas_texto"][0]["bbox"], [10,10,20,20])
        self.assertEqual(aplicar(self.con, "foto", r), r)
        deshacer(self.con, "foto", r)
        self.assertEqual(aplicar(self.con, "foto", r), self.ocr)

    def test_dividir_atomico_sin_duplicar(self):
        guardar_bloque(self.con, "foto", self.ocr, [10,10,40,20],
                       [{"bbox":[10,10,20,20], "texto":"10."}, {"bbox":[30,10,20,20], "texto":"04"}])
        r = aplicar(self.con, "foto", self.ocr)
        self.assertEqual([u["texto"] for u in r["lineas_texto"]], ["10.","04",".25","OTRO"])
        self.assertEqual(r["lineas_texto"][2], self.ocr["lineas_texto"][1])
        deshacer(self.con, "foto", r)
        self.assertEqual(aplicar(self.con, "foto", r), self.ocr)

    def test_solapadas_y_origen_obsoleto_rechazados(self):
        with self.assertRaises(ValueError):
            guardar_bloque(self.con, "foto", self.ocr, [10,10,40,20],
                           [{"bbox":[10,10,30,20],"texto":"A"},{"bbox":[20,10,30,20],"texto":"B"}])
        with self.assertRaises(ValueError):
            guardar_bloque(self.con, "foto", self.ocr, [11,10,40,20], [{"bbox":[10,10,30,20],"texto":"A"}])

    def test_dividir_y_luego_ajustar_un_hijo(self):
        guardar_bloque(self.con, "foto", self.ocr, [10,10,40,20],
                       [{"bbox":[10,10,20,20],"texto":"A"},{"bbox":[30,10,20,20],"texto":"B"}])
        r = aplicar(self.con, "foto", self.ocr)
        guardar_bloque(self.con, "foto", r, [10,10,20,20], [{"bbox":[11,11,15,15],"texto":"A."}])
        s = aplicar(self.con, "foto", r)
        self.assertEqual(s["lineas_texto"][0]["texto"], "A.")
        deshacer(self.con, "foto", s)
        self.assertEqual(aplicar(self.con, "foto", s), r)


if __name__ == "__main__":
    unittest.main()
