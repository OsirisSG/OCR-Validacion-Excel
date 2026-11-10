"""Busca y lee el número **moldeado** del tablero (`2GJ.857.003.G`) en las fotos.

El número no está impreso en ninguna etiqueta: va grabado en el plástico negro con letra de puntos,
en relieve y sin contraste. El OCR de la foto entera no lo ve. Aquí se hace al revés:

1. `localizar_grabado_punteado()` busca renglones de puntos en relieve (blackhat + componentes
   pequeños alineados) y devuelve sus cajas. Es barato: no llama al OCR.
2. `leer_parte_moldeada()` realza el relieve de esas cajas (blackhat + CLAHE), las amplía y las pasa
   al OCR. `interpretar_parte_tablero()` normaliza lo leído al formato del catálogo, tolerando las
   confusiones típicas (`2GJ` → `26J`/`20J`/`201`, `G` final → `6`/`C`).
"""
from __future__ import annotations

import gc
import re

import cv2
import numpy as np

PARTE_TABLERO = "2GJ.857.003.G"


def localizar_grabado_punteado(imagen, maximo: int = 3, lado: int = 2600) -> list[dict]:
    """Cajas (en coordenadas de la foto original) con más pinta de renglón punteado."""
    alto, ancho = imagen.shape[:2]
    escala = lado / max(alto, ancho)
    vista = cv2.resize(imagen, None, fx=escala, fy=escala) if escala < 1 else imagen.copy()
    gris = cv2.cvtColor(vista, cv2.COLOR_BGR2GRAY)

    relieve = cv2.morphologyEx(gris, cv2.MORPH_BLACKHAT,
                               cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    relieve = cv2.normalize(relieve, None, 0, 255, cv2.NORM_MINMAX)
    _, mascara = cv2.threshold(relieve, max(14, int(np.percentile(relieve, 99.2))), 255,
                               cv2.THRESH_BINARY)

    numero, etiquetas, estadisticas, centroides = cv2.connectedComponentsWithStats(mascara, 8)
    puntos = []
    for i in range(1, numero):
        x, y, w, h, area = estadisticas[i]
        if not (3 <= area <= 260):
            continue
        if not (2 <= w <= 26 and 2 <= h <= 26):
            continue
        if not (0.35 <= w / max(1, h) <= 2.8):
            continue
        puntos.append((x, y, w, h))
    if len(puntos) < 12:
        return []

    # se juntan los puntos en renglones: dilatar en horizontal y quedarse con las tiras alargadas
    lienzo = np.zeros(mascara.shape, np.uint8)
    for x, y, w, h in puntos:
        lienzo[y:y + h, x:x + w] = 255
    unido = cv2.dilate(lienzo, np.ones((1, 25), np.uint8), iterations=1)
    numero, _, estadisticas, _ = cv2.connectedComponentsWithStats(unido, 8)

    candidatas = []
    for i in range(1, numero):
        x, y, w, h, area = estadisticas[i]
        if w < 70 or h < 5 or h > 70:
            continue
        if w / max(1, h) < 2.0:
            continue
        dentro = sum(1 for px, py, pw, ph in puntos
                     if x <= px <= x + w and y <= py <= y + h)
        if dentro < 8:
            continue
        candidatas.append({"x": int(x / escala), "y": int(y / escala),
                           "w": int(w / escala), "h": int(h / escala),
                           "puntos": dentro, "puntos_por_lado": round(dentro / w, 3)})
    candidatas.sort(key=lambda c: -c["puntos"])
    return candidatas[:maximo]


def relieves_de_grabado(recorte, tipos=("plano", "bh")) -> list:
    """Variantes con el relieve levantado, que es lo único que el OCR puede leer aquí.

    - `plano`: se divide la imagen por su propio fondo desenfocado, con lo que se quita el degradado
      de la luz y el cepillado del plástico; es la que mejor funciona en fotos oscuras.
    - `bh`: realce de relieve (blackhat) con núcleo 7, la que funciona cuando la letra va hundida.
    """
    gris = cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY) if recorte.ndim == 3 else recorte
    salida = []
    for tipo in tipos:
        if tipo == "plano":
            fondo = cv2.GaussianBlur(gris, (0, 0), 25)
            plano = cv2.divide(gris, fondo, scale=255)
            salida.append(cv2.createCLAHE(clipLimit=6.0, tileGridSize=(8, 8)).apply(plano))
        elif tipo == "bh":
            relieve = cv2.morphologyEx(gris, cv2.MORPH_BLACKHAT,
                                       cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
            salida.append(cv2.createCLAHE(clipLimit=8.0, tileGridSize=(4, 4)).apply(relieve))
        elif tipo == "bh15":
            relieve = cv2.morphologyEx(gris, cv2.MORPH_BLACKHAT,
                                       cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))
            salida.append(cv2.createCLAHE(clipLimit=8.0, tileGridSize=(4, 4)).apply(relieve))
    return salida


def _realces_de_grabado(recorte, motor_de_realce=(3, 5)):
    """Compatibilidad: variantes de blackhat con los núcleos indicados."""
    gris = cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY) if recorte.ndim == 3 else recorte
    salida = []
    for tamano in motor_de_realce:
        relieve = cv2.morphologyEx(gris, cv2.MORPH_BLACKHAT,
                                   cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                                             (tamano, tamano)))
        salida.append(cv2.createCLAHE(clipLimit=8.0, tileGridSize=(4, 4)).apply(relieve))
    return salida


CONFUSIONES_DE_COLA = {"6": "G", "C": "G", "Q": "G", "0": "G", "O": "G", "9": "G", "3": "G"}


def interpretar_parte_tablero(texto: str, exigir_cola: bool = True,
                              normalizar_digitos: bool = False) -> str:
    """Lleva lo que leyó el OCR al formato `2GJ.857.003.X`, tolerando sus confusiones.

    Lo que no cambia nunca es el bloque `857` del medio. A partir de ahí:

    - delante se pone `2GJ` (el OCR lo lee `2EJ`, `26J`, `201`, `361`…);
    - el bloque final es el último carácter del renglón, sea letra o número, y la `G` grabada se
      lee `6`, `C`, `Q` o incluso `(`;
    - si no hay bloque final —el OCR se corta en `…003`— se devuelve lo que sí se sostiene
      (`2GJ.857.003`) y el caso lo completa con la lectura de otra foto.
    """
    compacto = re.sub(r"[^0-9A-Z]", "", str(texto).upper())
    posicion = compacto.find("857")
    if posicion < 0:
        return ""
    resto = compacto[posicion + 3:]
    if not resto.startswith("00"):
        return ""
    resto = resto[2:]
    if not resto:
        return ""
    if resto[0] in "38B":
        ultimo = resto[1:2]
    elif not resto[0].isdigit():
        ultimo = resto[0]          # el OCR se saltó el `3` del medio: el bloque final está ahí
    else:
        return ""
    if not ultimo or not re.match(r"[0-9A-Z]", ultimo):
        return "" if exigir_cola else "2GJ.857.003"
    if ultimo in "6CQ":
        ultimo = "G"               # la `G` grabada se lee `6`, `C` o `Q` con mucha facilidad
    elif normalizar_digitos and ultimo in CONFUSIONES_DE_COLA:
        # el bloque final del catálogo es una letra: un dígito aquí es la letra mal cerrada
        ultimo = CONFUSIONES_DE_COLA[ultimo]
    return f"2GJ.857.003.{ultimo}"


def cola_del_grabado(texto: str) -> str:
    """El bloque final del número, leído en un recorte del extremo derecho: `00` + `3` + bloque."""
    compacto = re.sub(r"[^0-9A-Z]", "", str(texto).upper())
    posicion = compacto.find("00")
    while posicion >= 0:
        resto = compacto[posicion + 2:]
        if len(resto) >= 2 and resto[0] in "38B" and re.match(r"[0-9A-Z]", resto[1]):
            return "G" if resto[1] in "6Q" else resto[1]
        posicion = compacto.find("00", posicion + 1)
    return ""


def _region_de_grabado(cajas: list[dict], alto: int, ancho: int) -> dict:
    """La unión de las cajas, abierta: el renglón del número no siempre sale entero en una caja."""
    x0 = min(c["x"] for c in cajas)
    y0 = min(c["y"] for c in cajas)
    x1 = max(c["x"] + c["w"] for c in cajas)
    y1 = max(c["y"] + c["h"] for c in cajas)
    ancho_region = max(240, x1 - x0)
    alto_region = max(140, y1 - y0)
    mx = int(ancho_region * 0.75) + 120
    my = int(alto_region * 0.55) + 70
    return {"x": max(0, x0 - mx), "y": max(0, y0 - my),
            "x1": min(ancho, x1 + mx), "y1": min(alto, y1 + my)}


def _bandas_del_grabado(recorte, cuantas: int = 3):
    """Tiras horizontales solapadas: la letra punteada necesita aumento, y una tira ancha y baja
    se puede ampliar mucho sin que el OCR se coma la memoria. Devuelve (desplazamiento, tira)."""
    alto = recorte.shape[0]
    paso = max(60, alto // cuantas)
    y = 0
    while y < alto:
        yield y, recorte[y:min(alto, y + paso + paso // 2)]
        y += paso


def _ocr_de_recorte(recorte, motor, ancho_objetivo: int = 1500,
                    motores_de_realce=("plano", "bh")):
    """OCR con el relieve levantado; devuelve (texto, confianza, caja) en coordenadas del recorte."""
    if recorte is None or recorte.size == 0:
        return []
    alto_recorte, ancho_recorte = recorte.shape[:2]
    # el aumento se corta por **área**: por encima de ~1,1 Mpx el OCR se come la memoria
    escala = min(ancho_objetivo / max(1, ancho_recorte),
                 (900_000 / max(1, ancho_recorte * alto_recorte)) ** 0.5)
    escala = max(1.0, escala)
    salida = []
    for realce in relieves_de_grabado(recorte, tipos=motores_de_realce):
        grande = cv2.resize(realce, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
        resultado = motor(cv2.cvtColor(grande, cv2.COLOR_GRAY2BGR))
        lista = resultado[0] if isinstance(resultado, tuple) else resultado
        for caja, texto, confianza in (lista or []):
            if not str(texto).strip():
                continue
            x0 = min(p[0] for p in caja) / escala
            y0 = min(p[1] for p in caja) / escala
            x1 = max(p[0] for p in caja) / escala
            y1 = max(p[1] for p in caja) / escala
            salida.append({"texto": str(texto), "confianza": float(confianza),
                           "x": int(x0), "y": int(y0), "w": int(x1 - x0), "h": int(y1 - y0)})
        del grande
        gc.collect()
    return salida


def leer_parte_moldeada(imagen, motor, maximo: int = 6) -> dict:
    """Lee el número moldeado: una ventana de OCR por cada zona donde el detector vio letra.

    Probar la zona entera no sirve (en el 232550 la unión se iba a media foto y el aumento caía por
    debajo de lo legible): se va caja por caja, con una ventana de 900 px de ancho alrededor, que
    ampliada al doble deja la letra grabada nítida y no pasa del presupuesto de memoria.
    """
    alto, ancho = imagen.shape[:2]
    cajas = localizar_grabado_punteado(imagen, maximo=maximo)
    if not cajas:
        return {}
    mejor: dict = {}
    for caja in cajas[:4]:
        ancho_ventana = int(max(900, caja["w"] * 2.2))
        x0 = max(0, caja["x"] - int(caja["w"] * 0.45) - 40)
        x1 = min(ancho, x0 + min(ancho_ventana, 1800))
        # la ventana baja más de lo que sube: la caja suele ser el renglón de arriba (`4148399X`) y
        # el número de parte va **debajo**
        y0 = max(0, caja["y"] - int(caja["h"] * 1.6) - 30)
        y1 = min(alto, caja["y"] + caja["h"] + int(caja["h"] * 3.6) + 30)
        ventana = imagen[y0:y1, x0:x1]
        if ventana.size == 0:
            continue
        for lectura in _ocr_de_recorte(ventana, motor, ancho_objetivo=1800,
                                       motores_de_realce=("plano", "bh")):
            if __import__("os").environ.get("PARTE_DEBUG"):
                print("   ventana:", lectura["texto"], round(lectura["confianza"], 2))
            completo = (interpretar_parte_tablero(lectura["texto"])
                        or interpretar_parte_tablero(lectura["texto"], normalizar_digitos=True))
            parcial = completo or interpretar_parte_tablero(lectura["texto"], exigir_cola=False)
            if not parcial:
                continue
            if float(lectura["confianza"]) > mejor.get("confianza", 0.0):
                mejor = {"valor": parcial, "texto": lectura["texto"],
                         "confianza": float(lectura["confianza"]),
                         "cola": completo[-1] if completo else "",
                         "region": {"x": int(x0), "y": int(y0), "x1": int(x1), "y1": int(y1)}}
        if mejor.get("cola"):
            break
    return mejor
