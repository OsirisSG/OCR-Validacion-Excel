from openpyxl import load_workbook

from generar_excel import generar_excel


def test_excel_agrupa_textos_por_carpeta_imagen_y_region(tmp_path):
    salida = generar_excel(ruta_salida=tmp_path / "resultado.xlsx")
    libro = load_workbook(salida, read_only=False)

    assert "Textos por imagen" in libro.sheetnames
    hoja = libro["Textos por imagen"]
    encabezados = [celda.value for celda in hoja[1]]
    assert encabezados[:8] == [
        "Carpeta", "Ruta carpeta", "Imagen", "Rol", "Origen", "Revisión", "Orden", "Texto"]
    filas = list(hoja.iter_rows(min_row=2, values_only=True))
    assert len(filas) >= 13
    assert {fila[0] for fila in filas} >= {
        "01_A1_variante2", "02_A1_variante3", "03_B7_variante1"}
    assert all(fila[2] and fila[4] in {"OCR", "Manual", "OCR externo"} for fila in filas)
    assert "Bandeja de revisión" in libro.sheetnames
    bandeja = libro["Bandeja de revisión"]
    assert bandeja.max_row >= 15  # encabezado + 6 carpetas + 8 pruebas externas
