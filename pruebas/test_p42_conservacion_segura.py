"""Regresiones sin fotos: conservar trabajo humano y abstenerse ante identidad ambigua."""
import pytest
from openpyxl import Workbook
from openpyxl.comments import Comment
import reporte_bmg as R


def caso(numero, **campos):
    return {"case_key": f"1st|{numero}", "tipo_st": "1ST",
            "campos": {k: {"valor": v} for k, v in {"test_number": str(numero), **campos}.items()}}


def hoja():
    ws = Workbook().active
    ws.title = 'Versuchsmatrix'
    ws['C8'] = 232561
    ws['B7'] = 'Cabecera institucional'
    ws['B8'] = 'Revisión humana'
    ws['B8'].comment = Comment('Decisión de la persona', 'Operador')
    ws['B8'].hyperlink = 'https://example.org/evidencia'
    return ws


def test_conserva_valor_humano_aunque_ocr_discrepe():
    ws = hoja()
    R._poblar_lista(ws, [caso(232561, test_reason='OTRA LECTURA')])
    assert ws['B8'].value == 'Revisión humana'
    assert ws['B8'].comment.text == 'Decisión de la persona'
    assert ws['B8'].hyperlink.target == 'https://example.org/evidencia'


def test_conserva_historicos_cabeceras_y_formulas_sin_moverlos():
    ws = hoja()
    ws['C410'] = 232599
    ws['B410'] = '=B8'
    R._poblar_lista(ws, [caso(232561)])
    assert ws['C410'].value == 232599
    assert ws['B410'].value == '=B8'
    assert ws['B7'].value == 'Cabecera institucional'


def test_duplicado_1st_2st_se_rechaza_antes_de_modificar():
    ws = hoja()
    ws['C58'] = 232561
    ws['B58'] = 'Segunda etapa'
    with pytest.raises(ValueError, match='ambigua'):
        R._poblar_lista(ws, [caso(232561)])
    assert ws['B8'].value == 'Revisión humana'
    assert ws['B58'].value == 'Segunda etapa'


def test_numero_corregido_no_usurpa_fila_antigua():
    ws = hoja()
    mapa = R._poblar_lista(ws, [caso(232562, test_reason='NUEVA')])
    assert ws['C8'].value == 232561
    assert ws.cell(mapa['1st|232562'], 3).value == 232562


def test_rellena_huecos_sin_republicar_un_tiempo_pendiente():
    ws = hoja()
    r = caso(232561, module_version='RDW')
    r['campos']['opening_time_ms'] = {'valor': 4, 'requiere_revision': True}
    R._poblar_lista(ws, [r])
    assert ws['H8'].value == 'RDW'
    assert ws['X8'].value is None


def test_relleno_no_borra_historicos_por_ser_la_plantilla(tmp_path):
    ws = hoja()
    p = tmp_path / 'entrada.xlsx'
    ws.parent.save(p)
    R._rellenar_lista(ws, [caso(232562)], {'fase3': {'limpiar_ejemplos': True}}, p)
    assert ws['C8'].value == 232561
    assert ws['B8'].value == 'Revisión humana'


def test_rangos_comentarios_y_once_imagenes_sobreviven_serializacion(tmp_path):
    from io import BytesIO
    from hashlib import sha256
    from PIL import Image as PILImage
    from openpyxl import load_workbook
    from openpyxl.drawing.image import Image
    from zipfile import ZipFile
    ws = hoja()
    wb = ws.parent
    espejo = wb.copy_worksheet(ws)
    espejo.title = 'Rangos'
    for i in range(11):
        buffer = BytesIO()
        PILImage.new('RGB', (2, 2), (i, 0, 0)).save(buffer, format='PNG')
        buffer.seek(0)
        ws.add_image(Image(buffer), f'BF{i+1}')
    entrada = tmp_path / 'original.xlsx'
    salida = tmp_path / 'resultado.xlsx'
    wb.save(entrada)
    original = sha256(entrada.read_bytes()).digest()
    wb = load_workbook(entrada)
    R._poblar_lista(wb['Versuchsmatrix'], [caso(232561, module_version='RDW')])
    R._copiar_lista_a_rangos(wb, [caso(232561, module_version='RDW')])
    wb.save(salida)
    with ZipFile(salida) as z:
        assert len([n for n in z.namelist() if n.startswith('xl/media/')]) == 11
    resultado = load_workbook(salida)
    for nombre in ['Versuchsmatrix', 'Rangos']:
        assert resultado[nombre]['B8'].comment.text == 'Decisión de la persona'
        assert resultado[nombre]['H8'].value == 'RDW'
    assert sha256(entrada.read_bytes()).digest() == original
