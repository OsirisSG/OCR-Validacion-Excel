"""Tablero de instrumentos: las cuatro columnas que faltaban, leídas de la foto (P30).

La guía del usuario lo dice así:

| Columna del libro | Dónde está en la pieza | Cómo se reconoce |
|---|---|---|
| `dashboard_part_number` | número **grabado** en el plástico | dos líneas finas; **la de abajo** es la buena y termina en una **letra o número más grande**, en una caja aparte (`2GJ.857.003.[G]`) |
| `dashboard_serial_number` | etiqueta **blanca con QR**, parecida a la del PAB pero no igual | de los códigos que imprime se toma **el más largo** (`052 3KVJ008R6E`) |
| `dashboard_date` | **otra** etiqueta con QR, más estrecha, con **pegatina de color** al lado | la fecha va en formato `DD/MM/AAAA` junto a la hora |
| `dashboard_engineering_level` | **estampa de color** (rosa) con tres caracteres | `##S` cuando el tablero no lleva estampa del nivel, `##K` si la lleva |

Las tres primeras no llevan ancla de color: se buscan por la forma del texto (grabado) o por el QR.
La cuarta sí es un ancla, y se lee en los cuatro giros porque la pegan como cae.

Diferencia entre la serie del tablero y la del módulo (lo que preguntó): las dos son
`NNN + 10 caracteres`, pero la del **tablero** empieza por `052` y lleva `3KVJ` en medio, y la del
**módulo** empieza por `671` y lleva `ZRZ`. Por eso la etiqueta del PAB nunca se confunde con la del
tablero: se descarta el token con `ZRZ` antes de elegir el más largo.
"""
from __future__ import annotations

import re

import cv2
import numpy as np

from utilidades import lector_etiquetas as L

# --- estampas del nivel -------------------------------------------------------------
RANGOS_ESTAMPA = {
    "rosa": ((135, 55, 55), (178, 255, 255)),
    "amarilla": ((16, 70, 70), (38, 255, 255)),
}
AREA_ESTAMPAS = (700, 90000)

# --- pegatinas de color que acompañan a la etiqueta de la fecha ---------------------
RANGOS_PEGATINA = {
    "azul": ((95, 90, 60), (135, 255, 255)),
    "verde": ((40, 70, 60), (85, 255, 255)),
}


def _blobs_de_color(imagen, rango, area_minima=AREA_ESTAMPAS[0], area_maxima=AREA_ESTAMPAS[1],
                    maximo: int = 3) -> list[dict]:
    hsv = cv2.cvtColor(imagen, cv2.COLOR_BGR2HSV)
    mascara = cv2.inRange(hsv, rango[0], rango[1])
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE,
                               cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cajas = []
    for contorno in contornos:
        area = int(cv2.contourArea(contorno))
        if not area_minima <= area <= area_maxima:
            continue
        x, y, w, h = cv2.boundingRect(contorno)
        if not 0.45 <= (w / h if h else 0) <= 2.6:      # la estampa es redonda: ni raya ni franja
            continue
        relleno = area / float(w * h) if w and h else 0.0
        if relleno < 0.45:
            continue
        cajas.append({"x": x, "y": y, "w": w, "h": h, "area": area})
    cajas.sort(key=lambda c: c["area"], reverse=True)
    return cajas[:maximo]


def hay_pegatina_de_color(imagen) -> str:
    """Qué pegatina acompaña a la etiqueta de la fecha: `azul`, `verde` o nada."""
    for nombre, rango in RANGOS_PEGATINA.items():
        if _blobs_de_color(imagen, rango, area_minima=900, area_maxima=200000, maximo=1):
            return nombre
    return ""


def leer_estampa_del_nivel(imagen, motor=None, colores=("rosa", "amarilla"),
                          confianza_minima: float = 0.45, maximo: int = 2) -> dict:
    """Lee el nivel de la estampa de color probando los cuatro giros.

    Se valida contra la sintaxis que indicó el usuario: `##S` sin estampa del nivel y `##K` con
    ella; lo que no encaje se descarta aquí para no arrastrarlo al libro.
    """
    alto, ancho = imagen.shape[:2]
    marco = imagen
    if max(alto, ancho) > 1600:
        factor = 1600 / max(alto, ancho)
        marco = cv2.resize(imagen, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    alto, ancho = marco.shape[:2]
    mejor: dict = {}
    for color in colores:
        for caja in _blobs_de_color(marco, RANGOS_ESTAMPA[color], maximo=maximo):
            pad = int(max(caja["w"], caja["h"]) * 0.30)
            x0, y0 = max(0, caja["x"] - pad), max(0, caja["y"] - pad)
            x1 = min(ancho, caja["x"] + caja["w"] + pad)
            y1 = min(alto, caja["y"] + caja["h"] + pad)
            recorte = marco[y0:y1, x0:x1]
            if recorte.size == 0:
                continue
            for giro, codigo in enumerate((None, cv2.ROTATE_180, cv2.ROTATE_90_CLOCKWISE,
                                           cv2.ROTATE_90_COUNTERCLOCKWISE)):
                vista = recorte if codigo is None else cv2.rotate(recorte, codigo)
                escala = 700 / max(vista.shape[:2])
                if escala > 1:
                    vista = cv2.resize(vista, None, fx=escala, fy=escala,
                                       interpolation=cv2.INTER_CUBIC)
                gris = cv2.createCLAHE(2.0, (8, 8)).apply(cv2.cvtColor(vista, cv2.COLOR_BGR2GRAY))
                for texto, confianza in _textos(gris, motor):
                    limpio = re.sub(r"[^0-9A-Z]", "", texto.upper())
                    if not 2 <= len(limpio) <= 4 or float(confianza) < confianza_minima:
                        continue
                    nivel = L.interpretar_nivel(limpio)[0]
                    if not nivel or not _sintaxis_del_nivel(nivel):
                        continue
                    if float(confianza) > mejor.get("confianza", 0.0):
                        mejor = {"nivel": nivel, "texto": texto, "color": color,
                                 "confianza": float(confianza), "giro": giro,
                                 "area": caja["area"], "recorte": recorte}
    return mejor


def _sintaxis_del_nivel(nivel: str) -> bool:
    """`##S` / `##K`: es la sintaxis del libro (la misma de P29, aplicada al tablero)."""
    from utilidades import codigos_modulo as CM
    return len(nivel) == 3 and CM.nivel_correcto_por_sintaxis(nivel, nivel.endswith("K"))


def _textos(imagen, motor=None) -> list[tuple[str, float]]:
    if motor is None:
        from utilidades import codigos_modulo as CM
        motor = CM.motor_compartido()
    vista = cv2.cvtColor(imagen, cv2.COLOR_GRAY2BGR) if imagen.ndim == 2 else imagen
    try:
        crudo = motor(vista)
    except Exception:                                    # noqa: BLE001
        return []
    # RapidOCR devuelve `(caja, texto, confianza)`; `ocr_engine` del proyecto, `(texto, confianza)`
    if isinstance(crudo, tuple):                         # RapidOCR: (resultado, tiempos)
        crudo = crudo[0]
    salida = []
    for linea in crudo or []:
        if isinstance(linea, (tuple, list)) and len(linea) >= 3:
            salida.append((str(linea[1]), float(linea[2])))
        elif isinstance(linea, (tuple, list)) and len(linea) == 2:
            salida.append((str(linea[0]), float(linea[1])))
    return salida


# --- número de parte grabado en el plástico ------------------------------------------
def bandas_finas(imagen, minimo_alto: int = 8, maximo: int = 4) -> list[tuple]:
    """Líneas grabadas, **separadas**: `bandas_con_columnas` cierra con un núcleo ancho y pega las
    dos líneas del código (`4148399X` y `2GJ.857.003.G`) en un solo bloque ilegible.
    """
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY) if imagen.ndim == 3 else imagen
    clahe = cv2.createCLAHE(clipLimit=6.0, tileGridSize=(8, 8)).apply(gris)
    nucleo = cv2.morphologyEx(clahe, cv2.MORPH_TOPHAT,
                              cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15)))
    _, binaria = cv2.threshold(nucleo, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    binaria = cv2.morphologyEx(binaria, cv2.MORPH_CLOSE,
                               cv2.getStructuringElement(cv2.MORPH_RECT, (13, 1)))
    perfil = (binaria > 0).sum(axis=1)
    umbral = max(5, int(perfil.max() * 0.25)) if perfil.size else 0
    bandas, dentro = [], None
    for fila, valor in enumerate(perfil):
        if valor >= umbral and dentro is None:
            dentro = fila
        elif valor < umbral and dentro is not None:
            if fila - dentro >= minimo_alto:
                bandas.append((dentro, fila))
            dentro = None
    if dentro is not None and len(perfil) - dentro >= minimo_alto:
        bandas.append((dentro, len(perfil)))
    salida = []
    for y0, y1 in bandas:
        columnas = np.where((binaria[y0:y1] > 0).any(axis=0))[0]
        if columnas.size < 20:
            continue
        salida.append(((y0, y1), (int(columnas[0]), int(columnas[-1]) + 1)))
    return salida[-maximo:]


def _variantes_de_grabado(trozo) -> list:
    """Lo que hace legible un número grabado: contraste local y relieve acentuado."""
    gris = cv2.cvtColor(trozo, cv2.COLOR_BGR2GRAY) if trozo.ndim == 3 else trozo
    clahe = cv2.createCLAHE(6.0, (8, 8)).apply(gris)
    difusa = cv2.GaussianBlur(clahe, (0, 0), 3)
    nitida = cv2.addWeighted(clahe, 1.9, difusa, -0.9, 0)
    realce = [nitida]
    for lado in (11, 15):
        realce.append(cv2.morphologyEx(clahe, cv2.MORPH_TOPHAT,
                                       cv2.getStructuringElement(cv2.MORPH_RECT,
                                                                 (lado, lado))))
    return [cv2.cvtColor(v, cv2.COLOR_GRAY2BGR) for v in realce]


def leer_parte_grabada(imagen, motor=None, catalogo=None) -> dict:
    """El número grabado en el plástico: **la línea de abajo** es la del libro.

    Arriba va el número de molde (`4148399X`); abajo, el número de parte con su remate más grande
    (`2GJ.857.003.[G]`). Se leen las líneas de abajo arriba y gana la primera que se identifique: si
    el texto sale entero se acepta tal cual; si el OCR pierde caracteres, se identifica contra el
    catálogo del libro y **se anota que fue confirmado**, no se escribe a ciegas.
    """
    alto, ancho = imagen.shape[:2]
    marco = imagen
    if max(alto, ancho) > 1600:
        factor = 1600 / max(alto, ancho)
        marco = cv2.resize(imagen, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    bandas = bandas_finas(marco)
    if not bandas:
        return {}
    fragmentos: list[str] = []
    mejor: dict = {}
    for indice, ((y0, y1), (x0, x1)) in enumerate(reversed(bandas)):    # de abajo arriba
        if (x1 - x0) < 60:
            continue
        trozo = marco[max(0, y0 - 6):y1 + 6, max(0, x0 - 10):x1 + 10]
        if trozo.size == 0:
            continue
        escala = max(2.0, min(4.0, 900 / max(1, (x1 - x0))))
        for variante in _variantes_de_grabado(trozo):
            grande = cv2.resize(variante, None, fx=escala, fy=escala,
                                interpolation=cv2.INTER_CUBIC)
            for texto, confianza in _textos(grande, motor):
                if not texto.strip():
                    continue
                fragmentos.append(texto.strip())
                parte = interpretar_parte_grabada(texto)
                if parte:
                    return {"valor": parte, "texto": texto, "banda": len(bandas) - 1 - indice,
                            "bandas": len(bandas), "confianza": float(confianza),
                            "confirmado_catalogo": _confirmar_con_catalogo(parte, catalogo)}
                if not mejor or float(confianza) > mejor.get("confianza", 0.0):
                    mejor = {"texto": texto, "confianza": float(confianza),
                             "banda": len(bandas) - 1 - indice, "bandas": len(bandas)}
        del trozo
    if catalogo and fragmentos:
        limpios = [f for f in fragmentos if not _es_codigo_de_resina(f)]
        identificado = L.identificar_parte(limpios, catalogo) if limpios else None
        if identificado and _parece_numero_de_parte(identificado["valor"], limpios):
            return {"valor": identificado["valor"], "texto": mejor.get("texto", ""),
                    "banda": mejor.get("banda", 0), "bandas": len(bandas),
                    "confianza": float(mejor.get("confianza", 0.0)),
                    "confirmado_catalogo": True, "fragmentos": identificado["fragmentos"]}
    return {}


PATRON_PARTE_GRABADA = re.compile(
    r"(?P<pref>\d[A-Z]{2})[.,\s]?(?P<b1>\d{3})[.,\s]?(?P<b2>\d{3})[.,\s]?(?P<suf>[A-Z0-9])")


def interpretar_parte_grabada(texto: str) -> str | None:
    """`2GJ857 003 G` → `2GJ.857.003.G`, con el punto del libro."""
    if not texto:
        return None
    limpio = re.sub(r"[^A-Z0-9.\s]", " ", str(texto).upper())
    for trozo in (limpio, limpio.replace(" ", "")):
        encontrado = PATRON_PARTE_GRABADA.search(trozo)
        if encontrado:
            pref = encontrado.group("pref")
            if pref[0].isdigit() and pref[1:].isalpha():
                return f"{pref}.{encontrado.group('b1')}.{encontrado.group('b2')}." \
                       f"{encontrado.group('suf')}"
    return None


RESINAS = ("PA66", "PA6", "POM", "PBT", "ABS", "PP", "PE", "PC", "TPE", "TPU", "HLI", "HDL",
           "GF", "SABIC", "UL94")


def _es_codigo_de_resina(texto: str) -> bool:
    """`PA66`, `>PBT-GF30<`, `UL94`… son marcas del material, no el número de parte."""
    compacto = re.sub(r"[^A-Z0-9]", "", str(texto).upper())
    if len(compacto) < 8:
        return True
    return any(resina in compacto for resina in RESINAS)


def _parece_numero_de_parte(valor: str, fragmentos: list[str]) -> bool:
    """Para aceptar una identificación del catálogo, lo leído tiene que parecerse de verdad."""
    objetivo = re.sub(r"[^A-Z0-9]", "", str(valor).upper())
    for fragmento in fragmentos:
        compacto = re.sub(r"[^A-Z0-9]", "", str(fragmento).upper())
        if len(compacto) < 8:
            continue
        if L._subsecuencia_comun(compacto, objetivo) >= 6:      # no basta con parecerse «un poco»
            return True
    return False


def _confirmar_con_catalogo(parte: str, catalogo) -> bool:
    if not catalogo:
        return False
    compacto = re.sub(r"[^A-Z0-9]", "", parte.upper())
    return any(re.sub(r"[^A-Z0-9]", "", str(c).upper()) == compacto for c in catalogo)


# --- etiquetas con código: serie y fecha ---------------------------------------------
# serie del tablero: `052` + `3KVJ008` + cola que empieza por letra (`R6E`, `R6J6`, `R52V`).
# La cola **no tiene largo fijo** en este lote (13 o 14 caracteres), así que no se fuerza: se
# aceptan las dos formas y decide el voto entre fotos.
PATRON_SERIE_TABLERO = re.compile(
    r"(?P<pref>\d{3})\s?(?P<cuerpo>[A-Z0-9]{3}J\d{3})(?P<cola>[A-Z][A-Z0-9]{1,3})")

MESES = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
         "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12, "ENE": 1, "ABR": 4, "AGO": 8, "DIC": 12}
# con bordes de dígito a los lados: si no, `1911-05-25` se leería como `11-05-25`
PATRON_FECHA_NUMERICA = re.compile(
    r"(?<!\d)(?P<dia>\d{1,2})\s*[/\-.\s]\s*(?P<mes>\d{1,2})\s*[/\-.\s]\s*"
    r"(?P<anio>\d{4}|\d{2})(?!\d)")
PATRON_FECHA_CON_MES = re.compile(
    r"(?P<dia>\d{1,2})\s*[/\-.\s]\s*(?P<mes>[A-Z]{3})[A-Z0-9]{0,2}\s*[/\-.\s]\s*"
    r"(?P<anio>\d{4}|\d{2})")


def _fecha_plausible(anio: int, mes: int, dia: int) -> bool:
    """Una fecha de fabricación es de este siglo: fuera de 2000–2100 es un error de lectura."""
    return 2000 <= anio <= 2100 and 1 <= mes <= 12 and 1 <= dia <= 31


def interpretar_fecha_de_tablero(texto: str) -> str | None:
    """Fecha de la etiqueta del tablero: `17/MAY/2025` (mes en letra) o `17/05/2025`.

    La etiqueta del tablero **no** escribe la fecha como la del módulo (`10.04.25`): pone el mes
    con tres letras en inglés. Se aceptan las dos formas y se devuelve `AAAA-MM-DD`.
    """
    if not texto:
        return None
    crudo = str(texto).upper()
    encontrado = PATRON_FECHA_CON_MES.search(crudo)
    if encontrado:
        mes = MESES.get(encontrado.group("mes"))
        dia = int(encontrado.group("dia"))
        anio = int(encontrado.group("anio"))
        if anio < 100:
            anio += 2000
        if mes and _fecha_plausible(anio, mes, dia):
            return f"{anio:04d}-{mes:02d}-{dia:02d}"
    numerica = PATRON_FECHA_NUMERICA.search(crudo)
    if numerica:
        dia, mes, anio = (int(numerica.group("dia")), int(numerica.group("mes")),
                          int(numerica.group("anio")))
        if anio < 100:
            anio += 2000
        if _fecha_plausible(anio, mes, dia):
            return f"{anio:04d}-{mes:02d}-{dia:02d}"
    return None


def interpretar_serie_tablero(texto: str) -> dict | None:
    """`*0523KVJ008R6E` → `052 3KVJ008R6E` (con el espacio del libro)."""
    if not texto:
        return None
    limpio = re.sub(r"[^A-Z0-9]", "", str(texto).upper())
    encontrado = PATRON_SERIE_TABLERO.search(limpio)
    if encontrado:
        return {"valor": f"{encontrado.group('pref')} {encontrado.group('cuerpo')}"
                          f"{encontrado.group('cola')}",
                "cola": encontrado.group("cola")}
    return L.interpretar_serie_tablero(texto)


def _recorte_alrededor(imagen, zona, izquierda=1.0, derecha=2.0, arriba=1.8, abajo=0.6):
    """La etiqueta entera alrededor del código: el texto va pegado a uno de sus lados."""
    alto, ancho = imagen.shape[:2]
    x0 = int(max(0, zona["x"] - zona["w"] * izquierda))
    x1 = int(min(ancho, zona["x"] + zona["w"] * (1 + derecha)))
    y0 = int(max(0, zona["y"] - zona["h"] * arriba))
    y1 = int(min(alto, zona["y"] + zona["h"] * (1 + abajo)))
    return imagen[y0:y1, x0:x1]


def _textos_de_bandas(imagen, motor=None, escala_minima: float = 2.5,
                      maximo_bandas: int = 3) -> list[tuple[str, float]]:
    """OCR de cada línea de texto por separado y ampliada: leer la etiqueta de una vez falla.

    Se limita a tres bandas y a una sola variante de realce: cada llamada al OCR deja ~150 MB y la
    máquina tiene 2 GB, así que el presupuesto por foto es corto.
    """
    salida: list[tuple[str, float]] = []
    bandas = bandas_finas(imagen)[:maximo_bandas]
    for (y0, y1), (x0, x1) in bandas:
        if (y1 - y0) < 6 or (x1 - x0) < 40:
            continue
        trozo = imagen[max(0, y0 - 4):y1 + 4, max(0, x0 - 6):x1 + 6]
        if trozo.size == 0:
            continue
        escala = max(escala_minima, min(4.0, 1000 / max(1, (x1 - x0))))
        variante = _variantes_de_grabado(trozo)[0]
        grande = cv2.resize(variante, None, fx=escala, fy=escala,
                            interpolation=cv2.INTER_CUBIC)
        salida.extend(_textos(grande, motor))
        del grande
    return salida


def franjas_de_etiqueta(imagen, zona) -> list[tuple[str, object]]:
    """Las dos franjas de texto que acompañan al código: **encima** y **debajo** de él.

    En la etiqueta del tablero la serie va pegada al código y la fecha debajo de la serie, así que
    con dos franjas se recoge todo el texto sin leer la foto entera.
    """
    alto, ancho = imagen.shape[:2]
    x, y, w, h = zona["x"], zona["y"], zona["w"], zona["h"]
    franjas = []
    for nombre, (x0, y0, x1, y1) in (
            ("debajo", (x - 0.25 * w, y + h - 0.05 * h, x + 1.30 * w, y + h + 0.50 * h)),
            ("encima", (x - 0.25 * w, y - 0.50 * h, x + 1.30 * w, y + 0.05 * h))):
        recorte = imagen[int(max(0, y0)):int(min(alto, y1)), int(max(0, x0)):int(min(ancho, x1))]
        if recorte.size:
            franjas.append((nombre, recorte))
    return franjas


def _textos_de_franja(recorte, motor=None, objetivo: int = 1000) -> list[tuple[str, float]]:
    if recorte is None or getattr(recorte, "size", 0) == 0:
        return []
    escala = objetivo / max(1, recorte.shape[1])
    vista = recorte if 0.9 <= escala <= 1.1 else cv2.resize(
        recorte, None, fx=max(0.5, min(4.0, escala)), fy=max(0.5, min(4.0, escala)),
        interpolation=cv2.INTER_CUBIC)
    return _textos(_variantes_de_grabado(vista)[0], motor)


def leer_serial_de_codigo(imagen, motor=None) -> dict:
    """La serie leída **en las franjas de la etiqueta**, no en la foto entera.

    La etiqueta imprime la serie pegada al DataMatrix y muchas veces girada: leer la foto completa
    acierta la mitad de los caracteres; leer la franja recortada y ampliada los acierta casi todos.
    """
    mejor: dict = {}
    alto_imagen, ancho_imagen = imagen.shape[:2]
    for zona in zonas_de_codigo(imagen, maximo=2):
        x0 = int(max(0, zona["x"] - zona["w"] * 1.0))
        x1 = int(min(ancho_imagen, zona["x"] + zona["w"] * 3.0))
        y0 = int(max(0, zona["y"] - zona["h"] * 1.8))
        y1 = int(min(alto_imagen, zona["y"] + zona["h"] * 1.6))
        base = imagen[y0:y1, x0:x1]
        if base.size == 0:
            continue
        zona_rel = {"x": zona["x"] - x0, "y": zona["y"] - y0, "w": zona["w"], "h": zona["h"]}
        for giro, codigo in enumerate((None, cv2.ROTATE_180)):
            vista = base if codigo is None else cv2.rotate(base, codigo)
            relativa = dict(zona_rel)
            if codigo is not None:                      # al girar, la zona cambia de sitio
                alto_base, ancho_base = base.shape[:2]
                relativa = {"x": ancho_base - (zona_rel["x"] + zona_rel["w"]),
                            "y": alto_base - (zona_rel["y"] + zona_rel["h"]),
                            "w": zona_rel["w"], "h": zona_rel["h"]}
            for _, franja in franjas_de_etiqueta(vista, relativa):
                for texto, confianza in _textos_de_franja(franja, motor):
                    if "ZRZ" in re.sub(r"[^A-Z0-9]", "", texto.upper()):
                        continue                            # etiqueta del módulo
                    serie = interpretar_serie_tablero(texto)
                    if not serie:
                        continue
                    largo = len(re.sub(r"[^A-Z0-9]", "", serie["valor"]))
                    clave = (largo, float(confianza))
                    if clave > mejor.get("_clave", (0, 0.0)):
                        mejor = {"valor": serie["valor"], "texto": texto, "largo": largo,
                                 "confianza": float(confianza), "giro": giro,
                                 "dudoso": False, "_clave": clave}
    mejor.pop("_clave", None)
    return mejor


def leer_serie_de_etiqueta(lineas, motor=None) -> dict:
    """La serie del tablero: de los códigos impresos, **el más largo**.

    Se descarta antes el código del PAB (`…ZRZ…`), que se parece pero no es: esa etiqueta va en el
    módulo, no en el tablero. La del tablero empieza por `052` y lleva `3KVJ` en medio.
    """
    if lineas is None:
        return {}
    pares = _pares_de_lineas(lineas, motor)
    candidatos: list[dict] = []
    for texto, confianza in pares:
        serie = interpretar_serie_tablero(texto)
        if not serie:
            continue
        if "ZRZ" in re.sub(r"[^A-Z0-9]", "", texto.upper()):
            continue                                      # es la etiqueta del módulo
        candidatos.append({"valor": serie["valor"], "texto": texto,
                           "largo": len(re.sub(r"[^A-Z0-9]", "", serie["valor"])),
                           "dudoso": bool(serie.get("dudoso")), "confianza": float(confianza)})
    if not candidatos:
        return {}
    # el más largo; a igualdad, el que no es dudoso y el de más confianza
    candidatos.sort(key=lambda c: (c["largo"], not c["dudoso"], c["confianza"]), reverse=True)
    elegido = dict(candidatos[0])
    elegido["votos"] = len({c["valor"] for c in candidatos})
    return elegido


def leer_fecha_de_etiqueta(lineas, motor=None) -> dict:
    """La fecha de fabricación del tablero en la etiqueta con código y pegatina de color."""
    if lineas is None:
        return {}
    candidatos: list[dict] = []
    for texto, confianza in _pares_de_lineas(lineas, motor):
        crudo = str(texto).upper()
        if "/" not in crudo and not re.search(r"[A-Z]{3}", crudo):
            continue                       # `10.04.25` es la etiqueta del módulo, no ésta
        fecha = interpretar_fecha_de_tablero(texto)
        if fecha:
            candidatos.append({"fecha": fecha, "texto": texto, "confianza": float(confianza)})
    if not candidatos:
        return {}
    candidatos.sort(key=lambda c: c["confianza"], reverse=True)
    elegido = dict(candidatos[0])
    elegido["votos"] = len({c["fecha"] for c in candidatos})
    return elegido


def _pares_de_lineas(lineas, motor=None) -> list[tuple[str, float]]:
    """Acepta tanto `[(texto, confianza)]` como las líneas con caja del OCR."""
    if isinstance(lineas, dict):
        lineas = lineas.get("lineas") or []
    salida: list[tuple[str, float]] = []
    for linea in lineas or []:
        if isinstance(linea, str):
            salida.append((linea, 0.0))
        elif isinstance(linea, dict):
            salida.append((str(linea.get("texto", "")), float(linea.get("confianza") or 0.0)))
        elif isinstance(linea, (tuple, list)) and linea:
            texto = str(linea[0])
            confianza = float(linea[1]) if len(linea) > 1 and linea[1] is not None else 0.0
            salida.append((texto, confianza))
    return salida


# --- una foto → lo que se pueda leer -------------------------------------------------
def leer_foto_de_tablero(imagen, motor=None, catalogo=None, pista=None) -> dict:
    """Las cuatro lecturas con el menor número de OCR posible, y sólo lo que salió.

    Nada se rellena a ojo: si un campo no aparece, no está en el resultado y el libro no se toca.
    """
    alto, ancho = imagen.shape[:2]
    marco = imagen
    if max(alto, ancho) > 1280:
        factor = 1280 / max(alto, ancho)
        marco = cv2.resize(imagen, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    pista = pista_de_tablero(marco)      # se recalcula aquí: las cajas tienen que ir en la misma escala
    campos: dict[str, dict] = {}

    if pista["estampa"]:
        # sólo la **rosa**: la amarilla es la estampa del módulo, no la del tablero
        estampa = leer_estampa_del_nivel(marco, motor, colores=("rosa",))
        if estampa.get("nivel"):
            campos["dashboard_engineering_level"] = {
                "valor": estampa["nivel"], "confianza": estampa["confianza"],
                "origen": f"estampa_{estampa['color']}", "recorte": estampa["recorte"],
                "giro": estampa["giro"]}

    if pista["grabado"] and not pista["etiqueta"]:
        parte = leer_parte_grabada(marco, motor, catalogo)
        if parte.get("valor"):
            campos["dashboard_part_number"] = {
                "valor": parte["valor"], "confianza": parte["confianza"],
                "origen": f"grabado_banda_{parte['banda']}",
                "confirmado_catalogo": parte["confirmado_catalogo"]}

    recorte_codigo = None
    if pista["etiqueta"] or pista["codigos"]:
        # primero las etiquetas recortadas (cuestan poco y el texto sale grande); si de ahí no sale
        # nada, la foto entera reducida. En algunas fotos el plástico blanco es mayor que la
        # etiqueta, así que ninguna de las dos vías sirve sola.
        lineas: list[tuple[str, float]] = []
        # alrededor de cada código, con margen: ahí están la serie y la fecha
        for codigo in pista["codigos"][:2]:
            x0 = max(0, codigo["x"] - codigo["w"] // 2)
            x1 = min(marco.shape[1], codigo["x"] + codigo["w"] * 2)
            y0 = max(0, codigo["y"] - codigo["h"] * 2)
            y1 = min(marco.shape[0], codigo["y"] + codigo["h"] + codigo["h"] // 2)
            trozo = marco[y0:y1, x0:x1]
            if trozo.size == 0:
                continue
            escala = 1000 / max(trozo.shape[:2])
            if escala > 1:
                trozo = cv2.resize(trozo, None, fx=escala, fy=escala,
                                   interpolation=cv2.INTER_CUBIC)
            lineas.extend(_textos(trozo, motor))
            recorte_codigo = trozo.copy()
            del trozo
        for etiqueta in pista["etiquetas"][:2]:
            trozo = marco[etiqueta["y"]:etiqueta["y"] + etiqueta["h"],
                          etiqueta["x"]:etiqueta["x"] + etiqueta["w"]]
            if trozo.size == 0:
                continue
            escala = 1000 / max(trozo.shape[:2])
            if escala > 1:
                trozo = cv2.resize(trozo, None, fx=escala, fy=escala,
                                   interpolation=cv2.INTER_CUBIC)
            lineas.extend(_textos(trozo, motor))
            del trozo
        serie = leer_serie_de_etiqueta(lineas, motor)
        fecha = leer_fecha_de_etiqueta(lineas, motor)
        if not serie and not fecha:
            vista = marco
            if max(marco.shape[:2]) > 1100:
                factor = 1100 / max(marco.shape[:2])
                vista = cv2.resize(marco, None, fx=factor, fy=factor,
                                   interpolation=cv2.INTER_AREA)
            lineas = _textos(vista, motor)
            serie = leer_serie_de_etiqueta(lineas, motor)
            fecha = leer_fecha_de_etiqueta(lineas, motor)
        if serie.get("valor"):
            campos["dashboard_serial_number"] = {
                "valor": serie["valor"], "confianza": serie["confianza"],
                "origen": serie["texto"], "dudoso": serie["dudoso"],
                "recorte": recorte_codigo}
        if fecha.get("fecha"):
            campos["dashboard_date"] = {
                "valor": fecha["fecha"], "confianza": fecha["confianza"],
                "origen": fecha["texto"], "pegatina": pista["pegatina"],
                "recorte": recorte_codigo}
    return campos


# --- filtro barato antes del OCR ------------------------------------------------------
def etiquetas_con_texto(imagen, maximo: int = 2) -> list[dict]:
    """Etiquetas **blancas con texto impreso**: lo que separa una etiqueta de una pared blanca.

    Una pared o una bata es blanco liso; una etiqueta tiene letra. Por eso se exige contraste
    dentro del recorte y una fracción de píxeles oscuros (la tinta), no sólo el color.
    """
    alto, ancho = imagen.shape[:2]
    hsv = cv2.cvtColor(imagen, cv2.COLOR_BGR2HSV)
    mascara = cv2.inRange(hsv, (0, 0, 130), (180, 75, 255))
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE,
                               cv2.getStructuringElement(cv2.MORPH_RECT, (21, 11)))
    contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    total = float(alto * ancho) or 1.0
    salida = []
    for contorno in contornos:
        x, y, w, h = cv2.boundingRect(contorno)
        area = (w * h) / total
        if not 0.010 <= area <= 0.60:
            continue
        trozo = imagen[y:y + h, x:x + w]
        if trozo.size == 0:
            continue
        gris = cv2.cvtColor(trozo, cv2.COLOR_BGR2GRAY)
        contraste = float(gris.std())
        tinta = float((gris < 90).mean())
        if contraste < 26 or not 0.004 <= tinta <= 0.45:
            continue
        salida.append({"x": x, "y": y, "w": w, "h": h, "area": area,
                       "contraste": round(contraste, 1), "tinta": round(tinta, 3)})
    salida.sort(key=lambda c: (c["w"] * c["h"]), reverse=True)
    return salida[:maximo]


def pegatinas_de_color(imagen, maximo: int = 3) -> list[dict]:
    """Pegatinas redondas y saturadas: la que va al lado de la etiqueta de la fecha."""
    alto, ancho = imagen.shape[:2]
    hsv = cv2.cvtColor(imagen, cv2.COLOR_BGR2HSV)
    salida = []
    for nombre, rango in RANGOS_PEGATINA.items():
        mascara = cv2.inRange(hsv, rango[0], rango[1])
        mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE,
                                   cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
        contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contorno in contornos:
            area = int(cv2.contourArea(contorno))
            if not 250 <= area <= int(0.06 * alto * ancho):
                continue
            x, y, w, h = cv2.boundingRect(contorno)
            if not 0.45 <= (w / h if h else 0) <= 2.2:
                continue
            relleno = area / float(w * h) if w * h else 0.0
            if relleno < 0.55:
                continue
            salida.append({"color": nombre, "x": x, "y": y, "w": w, "h": h, "area": area})
    salida.sort(key=lambda c: c["area"], reverse=True)
    return salida[:maximo]


def zonas_de_codigo(imagen, maximo: int = 2, lado_minimo: int = 40) -> list[dict]:
    """Zonas con pinta de **código** (QR o DataMatrix) por densidad de bordes.

    El lector de QR de OpenCV no reconoce el DataMatrix de estas etiquetas (`detectMulti` devuelve
    vacío aunque el código esté nítido), así que el código se localiza por su textura —cuadros
    pequeños en blanco y negro— y el texto se lee alrededor.
    """
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY) if imagen.ndim == 3 else imagen
    gradiente = cv2.morphologyEx(gris, cv2.MORPH_GRADIENT,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    _, binaria = cv2.threshold(gradiente, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # cuántos cambios hay alrededor de cada píxel: un código es la zona más "nerviosa" de la foto
    densidad = cv2.boxFilter(binaria, cv2.CV_32F, (25, 25), normalize=True)
    _, caliente = cv2.threshold(densidad, 60, 255, cv2.THRESH_BINARY)
    caliente = cv2.morphologyEx(caliente.astype("uint8"), cv2.MORPH_CLOSE,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (11, 11)))
    contornos, _ = cv2.findContours(caliente, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    alto, ancho = gris.shape[:2]
    cajas = []
    for contorno in contornos:
        x, y, w, h = cv2.boundingRect(contorno)
        if min(w, h) < lado_minimo:
            continue
        relacion = (w / h) if h else 0
        if not 0.70 <= relacion <= 1.45:        # un DataMatrix es casi cuadrado
            continue
        proporcion = (w * h) / float(alto * ancho)
        if not 0.002 <= proporcion <= 0.08:     # ni motas ni texturas de la pieza
            continue
        cajas.append({"x": x, "y": y, "w": w, "h": h, "area": w * h,
                      "densidad": round(float(densidad[y:y + h, x:x + w].mean()), 1),
                      "lado": min(w, h)})
    # manda el lado: un código grande y cuadrado es el de la etiqueta
    cajas.sort(key=lambda c: (c["lado"], c["densidad"]), reverse=True)
    return cajas[:maximo]


def pista_de_tablero(imagen) -> dict:
    """Filtro barato antes de gastar OCR: ¿esta foto puede tener algo del tablero?

    Cada columna tiene su pista y su puerta:

    * **nivel** — estampa **rosa** (la del tablero; la amarilla es la del módulo).
    * **serie** — etiqueta blanca **con tinta** (el OCR decidirá si lleva el código).
    * **fecha** — esa misma etiqueta **más** una pegatina de color al lado.
    * **número de parte** — líneas grabadas finas sobre plástico y **sin** etiqueta.
    """
    alto, ancho = imagen.shape[:2]
    marco = imagen
    if max(alto, ancho) > 1280:
        factor = 1280 / max(alto, ancho)
        marco = cv2.resize(imagen, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    pistas: dict = {"estampa": "", "pegatina": "", "etiquetas": [], "blanco": 0.0,
                    "grabado": False}
    if _blobs_de_color(marco, RANGOS_ESTAMPA["rosa"], area_minima=250, area_maxima=40000,
                       maximo=2):
        pistas["estampa"] = "rosa"
    pegatinas = pegatinas_de_color(marco)
    pistas["pegatina"] = pegatinas[0]["color"] if pegatinas else ""
    pistas["etiquetas"] = etiquetas_con_texto(marco)
    pistas["blanco"] = round(float(sum(e["area"] for e in pistas["etiquetas"])), 3)
    bandas = L.bandas_con_columnas(marco)
    pistas["grabado"] = len([b for b in bandas
                             if 8 <= (b[0][1] - b[0][0]) <= 60 and (b[1][1] - b[1][0]) >= 40]) >= 2
    pistas["etiqueta"] = bool(pistas["etiquetas"])
    pistas["codigos"] = zonas_de_codigo(marco)
    pistas["algo"] = bool(pistas["estampa"] or pistas["pegatina"] or pistas["etiqueta"]
                          or pistas["grabado"] or pistas["codigos"])
    return pistas
