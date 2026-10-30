from pathlib import Path

import cv2
import numpy as np

from aprendizaje import GestorAprendizaje

RAIZ = Path(__file__).resolve().parents[1]
APP = (RAIZ / 'dashboard/frontend/app.js').read_text(encoding='utf-8')
CSS = (RAIZ / 'dashboard/frontend/estilos.css').read_text(encoding='utf-8')
I18N = (RAIZ / 'dashboard/frontend/i18n.js').read_text(encoding='utf-8')
BACKEND = (RAIZ / 'dashboard/backend/app.py').read_text(encoding='utf-8')
HTML = (RAIZ / 'dashboard/frontend/index.html').read_text(encoding='utf-8')


def _gestor(tmp_path):
    return GestorAprendizaje({'aprendizaje': {'activar': True, 'registrar_observaciones': True}},
                             directorio=tmp_path / 'aprendizaje')


def test_notificaciones_fijas_traduccion_y_contraste():
    assert '.centro-notificaciones' in CSS and 'position: fixed' in CSS
    assert 'EstadoProcesoGlobal' in APP and 'EstadoColaExcel' in APP
    assert 'detenido_con_avance' in APP
    assert 't(estado?.mensaje || estado?.fase || "Iniciando…")' in APP
    assert 'characterData:true' in I18N
    for texto in ('Seleccionar varios textos', 'Aplicar supervisión', 'Imagen verificada',
                  'Ocultar imágenes verificadas', 'Ajustar o dividir bloque'):
        assert texto in I18N
    assert 'html[data-tema="oscuro"] .estado-pausado' in CSS
    assert 'html[data-tema="oscuro"] option' in CSS
    assert '20260921-v11-1' in HTML


def test_cola_tardia_y_borrado_multiple_estan_protegidos():
    assert 'seleccionActualRef.current.imagenId === seleccionEnviada.imagenId' in APP
    assert 'textoCorrecto !== textoPersistidoRef.current' in APP
    assert '/api/aprendizaje/no-texto-lote' in APP
    assert '@app.post("/api/aprendizaje/no-texto-lote")' in BACKEND
    assert 'demora=3.0' in BACKEND
    assert '_variantes_lectura_cache' in BACKEND and '_VARIANTES_CACHE_MAX = 256' in BACKEND


def test_ajustar_dividir_preserva_anotacion_manual():
    assert 'anotaciones_manual_preservadas' in BACKEND
    assert 'usa Ajustar / dividir bloque; la anotación manual se conserva por separado' in BACKEND
    # La previsualización exacta no entra en el bloqueo reservado a una unión genérica.
    assert 'not getattr(solicitud, "exacta", False)' in BACKEND


def test_region_manual_se_guarda_sin_entrenar_por_defecto_y_es_opt_in(tmp_path):
    imagen = tmp_path / 'placa.png'
    matriz = np.full((80, 180, 3), 220, dtype=np.uint8)
    assert cv2.imwrite(str(imagen), matriz)
    gestor = _gestor(tmp_path)

    guardada = gestor.registrar_region(
        'PA6.6', [10, 10, 60, 25], ruta_imagen=str(imagen),
        carpeta_id='caso-1', imagen_nombre='placa.png')
    assert guardada['registrada'] is True
    assert guardada['muestra_visual'] is None
    assert gestor.estado()['anotaciones_regiones'] == 1
    assert gestor.estado()['muestras_entrenables'] == 0

    propuesta = gestor.registrar_region(
        'PA6.6', [80, 10, 60, 25], ruta_imagen=str(imagen),
        carpeta_id='caso-1', imagen_nombre='placa.png', entrenable=True)
    assert propuesta['muestra_visual'] is not None
    assert propuesta['muestra_visual']['entrenable'] is True
    assert gestor.estado()['muestras_entrenables'] == 1


def test_guardar_correccion_no_entrena_por_defecto():
    assert 'accion: str = Field(default="guardar_sin_entrenar"' in BACKEND
    assert 'useState("guardar_sin_entrenar")' in APP
    assert 'Proponer esta región como ejemplo para entrenamiento OCR' in APP
