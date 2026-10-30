from pathlib import Path

import pytest
from openpyxl import load_workbook

from configuracion import cargar_config, cargar_reglas
from reporte_bmg import generar_reporte_bmg
from utilidades.encabezados_institucionales import extraer_metadatos_encabezado, textos_institucionales
from test_reporte_bmg_v7 import caso


def _identidad():
    return {
        "nombre_proyecto": "Ejemplo_VW",
        "project_id": "ejemplo_vw",
        "origen": "declarado_usuario",
        "seleccion_explicita": True,
        "sin_asignar": False,
    }


def _caso_con_ocr():
    fila = caso(930001, '1ST', 'HT', 'UGL', 5.8)
    fila['imagenes'] = [{
        'id': 'img-header', 'nombre': 'header.jpg', 'ruta': 'header.jpg',
        'resultado_ocr': {
            'texto_completo': (
                'VW316/5 PA PAB + IT Standversuche\n'
                'IT BMG Versuche / x50 Programm (1st & 2st)\n'
                'IT Entwicklung / COP BFA Module'
            ),
            'lineas_texto': [
                {'texto': 'VW316/5 PA PAB + IT Standversuche'},
                {'texto': 'IT BMG Versuche / x50 Programm'},
                {'texto': 'IT Entwicklung / COP BFA Module'},
            ],
        },
    }]
    fila['trazabilidad'] = [{
        'ruta_relativa': 'header.jpg',
        'texto_crudo': 'VW316/5 PA PAB + IT Standversuche | IT BMG Versuche / x50 Programm | COP BFA Module',
    }]
    return fila


def test_r8_extrae_terminos_tecnicos_desde_textos_ocr():
    meta = extraer_metadatos_encabezado([_caso_con_ocr()])
    assert meta['programa_vw'] == 'VW316/5'
    assert meta['programa_x'].lower() == 'x50'
    assert meta['pab_observado'] is True
    assert meta['bmg_observado'] is True
    assert meta['cop_bfa_observado'] is True
    assert meta['fuente'] == 'ocr'


@pytest.mark.parametrize(('idioma','b3','b4','c6','g6','o6','u6'), [
    ('es', 'Pruebas IT BMG / Programa x50 (1ra y 2da)', 'Desarrollo IT / Módulos COP BFA',
     'Prueba / Ensayo', 'Airbag del pasajero (PAB)', 'Conjunto tablero de instrumentos', 'Evaluación de subcomponentes'),
    ('en', 'IT BMG Tests / x50 Program (1st & 2nd)', 'IT Development / COP BFA Modules',
     'Test', 'Passenger airbag (PAB)', 'Instrument panel assembly', 'Subcomponent evaluation'),
    ('de', 'IT BMG Versuche / x50 Programm (1. & 2. Stufe)', 'IT Entwicklung / COP BFA Module',
     'Versuch', 'Beifahrerairbag (PAB)', 'ZSB Instrumententafel', 'Bewertung Unterkomponenten'),
])
def test_r8_encabezado_y_grupos_respetan_idioma(tmp_path, idioma, b3, b4, c6, g6, o6, u6):
    root = Path(__file__).resolve().parents[1]
    plantilla = root/'plantillas'/'reporte_bmg_1st_2st.xlsx'
    salida = tmp_path/f'r8_{idioma}.xlsx'
    generar_reporte_bmg(
        plantilla, salida, [_caso_con_ocr()], cargar_config(), cargar_reglas(),
        idioma=idioma,
        criterios_apertura={'verde_max':6.0,'amarillo_max':7.0,'origen':'elegido'},
        identidad_proyecto=_identidad(),
    )
    wb = load_workbook(salida, data_only=False)
    resumen = wb['Übersicht Standversuche']
    lista = wb['Versuchsmatrix']
    assert resumen['A1'].value == 'Ejemplo_VW'  # identidad elegida, nunca OCR
    assert resumen['B3'].value == b3
    assert resumen['B4'].value == b4
    assert lista['A2'].value == 'Ejemplo_VW'
    assert lista['C6'].value == c6
    assert lista['G6'].value == g6
    assert lista['O6'].value == o6
    assert lista['U6'].value == u6
    # La fila de campos también debe estar en el idioma seleccionado.
    if idioma == 'es':
        assert lista['A7'].value == 'Semana'
        assert lista['F7'].value == 'Temperatura'
    elif idioma == 'en':
        assert lista['A7'].value == 'Week'
        assert lista['F7'].value == 'Temperature'
    else:
        assert lista['A7'].value == 'Woche'
        assert lista['F7'].value == 'Temperatur'
