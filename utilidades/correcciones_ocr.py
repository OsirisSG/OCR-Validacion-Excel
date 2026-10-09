"""Proyección de confirmaciones humanas sin modificar el resultado OCR bruto."""
from copy import deepcopy


def aplicar_correcciones(ocr, correcciones):
    ocr = ocr or {}
    salida = deepcopy(ocr)
    # El proveedor entrega el historial cronológico. Acepta también registros
    # antiguos que guardaron como origen la corrección visible anterior.
    historial = list(correcciones or [])

    def resolver(original, visible, bbox):
        conocidos = {str(original).strip()}
        texto, ultimo = visible, -1
        for i, c in enumerate(historial):
            if c.get('bbox') != bbox or str(c.get('texto_ocr') or '').strip() not in conocidos:
                continue
            texto = str(c.get('texto_correcto') or '')
            conocidos.add(texto.strip())
            ultimo = i
        return texto, ultimo

    # En resultados parciales/antiguos estas colecciones pueden existir con
    # valor None. Semánticamente significan "sin unidades todavía", no un
    # iterable inválido. Normalizamos únicamente los campos OCR conocidos.
    for clave in ('tokens', 'lineas_texto', 'codigos_detectados', 'recortes', 'qrs'):
        if salida.get(clave) is None:
            salida[clave] = []

    ultimo_espacial = -1
    for clave in ('tokens', 'lineas_texto'):
        for unidad in (salida.get(clave) or []):
            original = str(unidad.get('texto_original') or unidad.get('texto') or '')
            texto, indice = resolver(original, unidad.get('texto', ''), unidad.get('bbox'))
            if indice >= 0:
                unidad['texto_original'] = original
                unidad['texto'] = texto
                unidad['confirmado_manualmente'] = True
                ultimo_espacial = max(ultimo_espacial, indice)
    original_completo = str(ocr.get('texto_completo_original') or ocr.get('texto_completo') or '')
    if ultimo_espacial >= 0:
        salida['texto_completo'] = '\n'.join(str(u.get('texto') or '') for u in
                                            (salida.get('lineas_texto') or salida.get('tokens') or []))
    texto, indice = resolver(original_completo, salida.get('texto_completo', ''), None)
    # Una edición posterior de un renglón deja obsoleta una confirmación global.
    if indice >= 0 and indice >= ultimo_espacial:
        salida['texto_completo_original'] = original_completo
        salida['texto_completo'] = texto
        salida['texto_completo_confirmado'] = True
    elif ultimo_espacial >= 0:
        salida['texto_completo_confirmado'] = False
    return salida
