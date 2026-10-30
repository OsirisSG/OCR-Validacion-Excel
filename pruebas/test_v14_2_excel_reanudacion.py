from __future__ import annotations

import importlib.util
import tempfile
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aprendizaje import GestorAprendizaje
from configuracion import cargar_config, cargar_reglas
from generar_excel import generar_excel
from utilidades.correcciones_ocr import aplicar_correcciones

APP_PATH = ROOT / "dashboard" / "backend" / "app.py"
spec = importlib.util.spec_from_file_location("dashboard_app_v142", APP_PATH)
app = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(app)


class ExcelNoneV142Tests(unittest.TestCase):
    def test_proyeccion_correcciones_acepta_colecciones_none(self):
        ocr = {
            "texto_completo": "",
            "tokens": None,
            "lineas_texto": None,
            "codigos_detectados": None,
            "recortes": None,
            "qrs": None,
        }
        salida = aplicar_correcciones(ocr, None)
        self.assertEqual([], salida["tokens"])
        self.assertEqual([], salida["lineas_texto"])
        self.assertEqual([], salida["codigos_detectados"])

    def test_filtrar_no_texto_acepta_ocr_parcial_con_none(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = Path(td)
            imagen = raiz / "IMG_1.JPG"
            imagen.write_bytes(b"imagen-de-prueba-no-decodificada")
            gestor = GestorAprendizaje(cargar_config(), directorio=raiz / ".aprendizaje")
            salida = gestor.filtrar_no_texto({
                "imagen": str(imagen), "texto_completo": "",
                "tokens": None, "lineas_texto": None,
                "codigos_detectados": None, "recortes": None, "qrs": None,
            }, imagen)
            self.assertEqual([], salida["tokens"])
            self.assertEqual([], salida["lineas_texto"])
            self.assertEqual([], salida["codigos_detectados"])

    def test_generacion_excel_completa_con_ocr_none_no_lanza_typeerror(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = Path(td)
            imagen = raiz / "IMG_2.JPG"
            imagen.write_bytes(b"imagen-de-prueba-no-decodificada")
            config = deepcopy(cargar_config())
            config.setdefault("fase3", {})["plantilla_empresarial"] = None
            config["fase3"].setdefault("reporte_bmg", {})["activar"] = False
            config.setdefault("aprendizaje", {})["directorio"] = str(raiz / ".aprendizaje")
            datos = {
                "perfil": "empresarial",
                "resultados": [{
                    "ruta": str(raiz / "caso"), "nombre": "caso", "identificador": "1",
                    "imagenes": [{"ruta": str(imagen), "nombre": imagen.name,
                                  "resultado_ocr": {"texto_completo": "", "tokens": None,
                                                    "lineas_texto": None,
                                                    "codigos_detectados": None,
                                                    "recortes": None, "qrs": None}}],
                    "etiqueta": None, "referencia": None,
                    "comparacion": {"resultado": "coincidencia_parcial"},
                    "tipos_archivo": None, "observaciones": None,
                    "confianza_ocr_pct": None, "qr_detectado": False,
                }],
            }
            destino = raiz / "salida.xlsx"
            generado = generar_excel(None, destino, config, cargar_reglas(), datos_validacion=datos)
            self.assertTrue(Path(generado).is_file())

    def test_reporte_bmg_configurado_acepta_ocr_none(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = Path(td)
            imagen = raiz / "IMG_BMG.JPG"
            imagen.write_bytes(b"imagen-de-prueba-no-decodificada")
            config = deepcopy(cargar_config())
            config.setdefault("aprendizaje", {})["directorio"] = str(raiz / ".aprendizaje")
            datos = {
                "perfil": "empresarial",
                "resultados": [{
                    "ruta": str(raiz / "caso"), "ruta_relativa": "1ST/caso",
                    "nombre": "caso", "identificador": "1", "test_number": "1",
                    "tipo_st": "1ST", "project_id": "P",
                    "temperature_condition": "RT", "inflator_type": "NOM",
                    "imagenes": [{"ruta": str(imagen), "nombre": imagen.name,
                                  "resultado_ocr": {"texto_completo": "", "tokens": None,
                                                    "lineas_texto": None,
                                                    "codigos_detectados": None,
                                                    "recortes": None, "qrs": None}}],
                    "etiqueta": None, "referencia": None,
                    "comparacion": {"resultado": "coincidencia_parcial"},
                    "tipos_archivo": None, "observaciones": None,
                    "confianza_ocr_pct": None, "qr_detectado": False,
                    "campos": {}, "consolidado": {"campos": {}, "candidatos": []},
                    "candidatos": None, "estado": "procesada",
                }],
            }
            destino = raiz / "bmg.xlsx"
            generado = generar_excel(None, destino, config, cargar_reglas(), datos_validacion=datos)
            self.assertTrue(Path(generado).is_file())
            self.assertGreater(Path(generado).stat().st_size, 1000)


class ReanudacionCompletaV142Tests(unittest.TestCase):
    def test_detectados_e_inventariados_no_se_marcan_como_omitidos(self):
        original_estado = deepcopy(app._pipeline_estado)
        original_hilo = app._pipeline_hilo
        original_iniciar = app.iniciar_pipeline
        original_persistir = app._persistir_checkpoint_pipeline
        capturado = {}
        try:
            app._pipeline_hilo = None
            app._pipeline_estado.clear()
            app._pipeline_estado.update(original_estado)
            app._pipeline_estado.update({
                "estado": "detenido_con_avance",
                "ejecucion_id": "exec-v142",
                "resultados_parciales": [
                    {"id": "a", "case_key": "A", "ruta": "A", "estado": "procesada",
                     "resultado": "coincidencia_total"},
                    {"id": "b", "case_key": "B", "ruta": "B", "estado": "cancelada",
                     "resultado": "sin_procesar"},
                    {"id": "c", "case_key": "C", "ruta": "C", "estado": "detectada",
                     "resultado": "sin_procesar"},
                    {"id": "d", "case_key": "D", "ruta": "D", "estado": "inventariada",
                     "resultado": "sin_procesar"},
                ],
                "ultimo_id": "b", "ultimo_id_nombre": "B",
                "solicitud": {
                    "ruta": str(ROOT), "nombre_excel": None,
                    "sobrescribir_excel": False, "tipo_st": "LEGACY",
                    "plantilla_id": None, "modo_ejecucion": "completo",
                    "idiomas_exportacion": ["es"], "casos_omitidos": ["PREVIO"],
                    "ejecucion_id": "exec-v142", "perfil_rendimiento": "alto",
                },
            })
            app._persistir_checkpoint_pipeline = lambda: True

            def falso_iniciar(solicitud):
                capturado["omitidos"] = set(solicitud.casos_omitidos)
                app._pipeline_estado["estado"] = "procesando"
                return {"aceptado": True}

            app.iniciar_pipeline = falso_iniciar
            respuesta = app.reanudar_pipeline()
            self.assertTrue(respuesta["desde_checkpoint"])
            self.assertEqual({"A"}, capturado["omitidos"])
            self.assertNotIn("PREVIO", capturado["omitidos"])
            self.assertNotIn("B", capturado["omitidos"])
            self.assertNotIn("C", capturado["omitidos"])
            self.assertNotIn("D", capturado["omitidos"])
        finally:
            app.iniciar_pipeline = original_iniciar
            app._persistir_checkpoint_pipeline = original_persistir
            app._pipeline_hilo = original_hilo
            app._pipeline_estado.clear()
            app._pipeline_estado.update(original_estado)

    def test_legacy_final_sin_estado_si_se_omite(self):
        self.assertTrue(app._caso_realmente_completado_para_reanudar({
            "ruta": "legacy", "resultado": "discrepancia"}))
        self.assertFalse(app._caso_realmente_completado_para_reanudar({
            "ruta": "futuro", "estado": "detectada", "resultado": "sin_procesar"}))


if __name__ == "__main__":
    unittest.main()
