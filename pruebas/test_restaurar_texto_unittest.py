"""Prueba unitaria de ``restaurar_imagen_con_texto`` (rama carpeta).

R15.1 (CRÍTICO-01): el endpoint committea por la primitiva
``mutar_documento``. R15.2 (CRÍTICO-02): esa primitiva vive ahora en la
autoridad compartida ``utilidades.persistencia_documento``, de modo que las
funciones extraídas del backend son envoltorios finos y el entorno inyecta
el módulo real (``_pdoc``) con ``escribir_json_seguro`` parcheado para
capturar la escritura. La garantía probada es la misma de V15.9.3: si la
escritura JSON falla, la marca ``sin_datos`` persistida NO se elimina (el
DELETE sqlite sólo se confirma tras el commit del documento).
"""
import ast
import json
import tempfile
import threading
import unittest
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

import dashboard.backend.app as backend
from aprendizaje import GestorAprendizaje, hash_archivo
from utilidades import persistencia_documento
from utilidades.persistencia import ResultadoPersistencia


class _TxStub:
    """R15.5: stub mínimo del coordinador para el arnés legacy.

    El coordinador real (``TransaccionMultiAlmacen``) está cubierto por
    test_v15_10_1_r155_transaccion_coordinada.py y por las pruebas de fallo
    doble de cada endpoint; aquí sólo se necesita su contrato local:
    capturar/aplicado/fallar (compensa y relanza)/exito.
    """

    def __init__(self, operacion, recurso=None):
        self._pendientes = []

    def capturar(self, nombre, capturar_fn, restaurar_fn):
        estado = capturar_fn()
        self._pendientes.append((nombre, restaurar_fn, estado))
        return estado

    def aplicado(self):
        return None

    def fallar(self, exc):
        for _, restaurar, estado in reversed(self._pendientes):
            restaurar(estado)
        raise exc

    def exito(self):
        return None


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
        # R15.1: la primitiva lee el documento FRESCO de disco; el stub de
        # caché y el archivo deben partir del mismo contenido.
        self.validacion = Path(self.tmp.name)/'validacion_resultados.json'
        self.validacion.write_text(json.dumps(datos), encoding='utf-8')
        self.guardado = []

        def escribir_stub(ruta, doc, lanzar=False, compacto=False, **kw):
            self.guardado.append(deepcopy(doc))
            Path(ruta).write_text(json.dumps(doc), encoding='utf-8')
            return ResultadoPersistencia(True, Path(ruta), 1)

        self.escribir_stub = escribir_stub
        self.env = {'SolicitudImagenSinDatos':SimpleNamespace,'_pipeline_hilo':None,
            # R15.3 (ALTO-03): la guarda uniforme de pipeline se prueba por
            # separado (test_v15_10_1_r153_cas_efectos.py); aquí se stubbea.
            '_assert_documento_editable':lambda accion='':None,
            # R15.5: registro global de inconsistencias no aplica al arnés
            # (recurso en tmp); se stubbea como la guarda de pipeline.
            '_assert_recurso_consistente':lambda recurso, accion='':None,
            'TransaccionMultiAlmacen':_TxStub,
            'GestorAprendizaje':lambda c:self.gestor,'CONFIG':{},'deepcopy':deepcopy,
            '_cargar_datos':lambda:datos,'_id_fila':lambda f:'caso',
            '_resolver_raiz_datos':lambda d:Path(self.tmp.name),
            '_resolver_imagen':lambda *a:self.ruta,'RUTA_VALIDACION':self.validacion,
            'hash_archivo':hash_archivo,'_cache':{},
            '_regenerar_excel':lambda r:r.update(excel_pendiente=True),
            # Dependencias de la primitiva mutar_documento (R15.1); en R15.2
            # la primitiva real es ``utilidades.persistencia_documento`` y el
            # backend sólo la envuelve/traduce a HTTP.
            'threading':threading,'datetime':datetime,'json':json,
            'HTTPException':HTTPException,'_pdoc':persistencia_documento,
            # R15.7 (ALTO-02): identidad canónica de recursos — el arnés
            # inyecta los MISMOS constructores del backend (subrecurso de
            # imagen/extensión), no una copia.
            '_recurso_carpeta':backend._recurso_carpeta,
            '_recurso_imagen':backend._recurso_imagen,
            '_recurso_video':backend._recurso_video,
            '_recurso_externa':backend._recurso_externa}
        tree=ast.parse((Path(__file__).resolve().parents[1]/'dashboard/backend/app.py').read_text(encoding='utf-8'))
        # R15.6 (ALTO-04): el handler público es un wrapper que toma el lock
        # del documento externo; la lógica vive en _restaurar_imagen_con_texto_impl.
        funciones=[f for f in tree.body if isinstance(f,ast.FunctionDef) and f.name in
                   ('_restaurar_estado_con_texto','restaurar_imagen_con_texto',
                    '_restaurar_imagen_con_texto_impl',
                    'mutar_documento','_leer_documento_disco','_commit_documento',
                    '_verificar_expected_revision','_invalidar_cache_documento',
                    '_capturar_revision_estado','_restaurar_revision_estado')]
        for f in funciones: f.decorator_list=[]
        exec(compile(ast.Module(body=funciones,type_ignores=[]),'restaurar','exec'),self.env)
        # R15.2: la escritura del documento ocurre DENTRO del módulo de la
        # autoridad compartida; se parchea ahí (con restauración automática).
        self.addCleanup(setattr, persistencia_documento, 'escribir_json_seguro',
                        persistencia_documento.escribir_json_seguro)
        persistencia_documento.escribir_json_seguro = escribir_stub

    def llamar(self):
        # R15.2 (ALTO-04): CAS estricto en mutaciones humanas; la UI correcta
        # envía la revisión vigente del documento (antes: expected=None).
        disco = (json.loads(self.validacion.read_text(encoding='utf-8'))
                 if self.validacion.exists() else {})
        return self.env['restaurar_imagen_con_texto'](SimpleNamespace(
            tipo='carpeta',prueba_id='caso',imagen_id='foto',
            expected_revision=disco.get('revision_documento')))

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
        # R15.1: la escritura verificada falla dentro del commit de la
        # primitiva ⇒ rollback sqlite ⇒ la marca NO se elimina.
        def falla(*a, **kw): raise OSError('archivo ocupado')
        persistencia_documento.escribir_json_seguro=falla
        with self.assertRaises(OSError): self.llamar()
        self.assertIsNotNone(self.gestor.imagen_sin_datos(self.ruta))
        disco=json.loads(self.validacion.read_text(encoding='utf-8'))
        self.assertEqual(disco['resultados'][0]['imagenes'][0]['estado_imagen'],
                         'revisada_sin_datos')

    def test_formato_externo_conserva_lecturas(self):
        item={'estado_imagen':'revisada_sin_datos','revision_sin_datos':{},'texto_completo':'ABC'}
        self.env['_restaurar_estado_con_texto'](item)
        self.assertEqual(item,{'estado_imagen':'pendiente','texto_completo':'ABC'})


if __name__ == '__main__': unittest.main()
