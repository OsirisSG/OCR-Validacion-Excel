"""Fecha de prueba desde el pie del vídeo (P14).

En este proyecto la fecha de prueba no está impresa en la pieza: aparece en el **pie de página del
vídeo** (marca de tiempo del registro). Así que:

1. se abre el vídeo y se captura un fotograma (por defecto a mitad, que suele tener ya el rótulo);
2. se recorta la franja inferior (el pie);
3. se lee esa franja y se busca una fecha/hora con patrón;
4. se valida con el protocolo del campo `test_date` y **se guarda el recorte como evidencia**, para
   que en la página de dudas se vea la imagen al lado del valor.

Sin motor OCR el recorte se devuelve igual: la duda queda con la imagen, que es lo útil.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import cv2
import numpy as np

PATRONES_FECHA = [
    re.compile(r"(?P<dia>\d{1,2})[./-](?P<mes>\d{1,2})[./-](?P<anio>\d{4})"),
    re.compile(r"(?P<anio>\d{4})-(?P<mes>\d{1,2})-(?P<dia>\d{1,2})"),
    # «17 de mayo de 2025», «17 DE MAYO DEL 2025», «martes 17 mayo 2025»
    re.compile(r"(?P<dia>\d{1,2})\s*(?:(?i:de)\s+)?(?P<mes_letra>[A-Za-zÁÉÍÓÚáéíóú]{3,})\.?\s*"
               r"(?:(?i:de|del)\s+)?(?P<anio>\d{4})"),
    # «mayo 17, 2025» (mes primero, formato inglés)
    re.compile(r"(?P<mes_letra>[A-Za-zÁÉÍÓÚáéíóú]{3,})\s+(?P<dia>\d{1,2}),?\s+(?P<anio>\d{4})"),
]
MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8,
         "sep": 9, "oct": 10, "nov": 11, "dic": 12, "jan": 1, "apr": 4, "aug": 8, "dec": 12,
         # nombres completos en español, con y sin acento
         "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
         "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11,
         "diciembre": 12}
def _sin_acentos(texto: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if unicodedata.category(c) != "Mn")


PATRON_HORA = re.compile(r"\b(?P<hora>[0-2]?\d):(?P<minuto>[0-5]\d)(?::(?P<segundo>[0-5]\d))?\b")


def informacion(archivo: Path) -> dict:
    captura = cv2.VideoCapture(str(archivo))
    if not captura.isOpened():
        return {"ok": False, "error": "no se pudo abrir el vídeo"}
    fps = captura.get(cv2.CAP_PROP_FPS) or 25.0
    fotogramas = int(captura.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    ancho = int(captura.get(cv2.CAP_PROP_FRAME_WIDTH))
    alto = int(captura.get(cv2.CAP_PROP_FRAME_HEIGHT))
    captura.release()
    return {"ok": True, "fps": fps, "fotogramas": fotogramas,
            "duracion_s": round(fotogramas / fps, 2) if fps else 0, "ancho": ancho, "alto": alto}


def capturar(archivo: Path, segundo: float | None = None):
    captura = cv2.VideoCapture(str(archivo))
    if not captura.isOpened():
        return None
    total = captura.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    fps = captura.get(cv2.CAP_PROP_FPS) or 25.0
    if segundo is None:
        segundo = (total / fps) / 2 if total and fps else 0
    captura.set(cv2.CAP_PROP_POS_MSEC, max(0.0, segundo) * 1000)
    ok, fotograma = captura.read()
    captura.release()
    return fotograma if ok else None


def recortar_pie(fotograma, alto_relativo: float = 0.16):
    """Franja inferior del fotograma: donde va el rótulo con la fecha."""
    if fotograma is None:
        return None
    alto = fotograma.shape[0]
    desde = int(alto * (1 - alto_relativo))
    return fotograma[desde:alto, :]


def interpretar(texto: str) -> dict:
    """Saca fecha y hora de un texto de pie de vídeo. Devuelve dict con lo que encuentre."""
    limpio = str(texto or "")
    resultado = {"fecha": None, "hora": None, "texto": limpio.strip()}
    for patron in PATRONES_FECHA:
        coincidencia = patron.search(limpio)
        if not coincidencia:
            continue
        grupos = coincidencia.groupdict()
        try:
            if grupos.get("mes_letra"):
                letra = _sin_acentos(grupos["mes_letra"]).lower()
                mes = MESES.get(letra) or MESES.get(letra[:3])
                if not mes:
                    continue
                fecha = date(int(grupos["anio"]), mes, int(grupos["dia"]))
            else:
                fecha = date(int(grupos["anio"]), int(grupos["mes"]), int(grupos["dia"]))
        except (ValueError, TypeError):
            continue
        if not 2015 <= fecha.year <= 2100:
            continue
        resultado["fecha"] = fecha.isoformat()
        break
    hora = PATRON_HORA.search(limpio)
    if hora:
        resultado["hora"] = hora.group(0)
    return resultado


def _densidad_de_texto(franja) -> float:
    """Cuánto «texto» parece tener una franja: bordes horizontales finos y contraste."""
    if franja is None or franja.size == 0:
        return 0.0
    gris = cv2.cvtColor(franja, cv2.COLOR_BGR2GRAY)
    gris = cv2.resize(gris, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    bordes = cv2.Sobel(gris, cv2.CV_32F, 0, 1, ksize=3)
    return float(np.abs(bordes).mean())


def mejor_pie(archivo: Path, muestras: int = 5, alto_relativo: float = 0.16):
    """Recorre varios fotogramas repartidos y devuelve el pie con más pinta de rótulo.

    Como el rótulo se ve durante todo el vídeo, no hace falta acertar el segundo: se prueban
    varios y gana el que tiene más contraste de texto en la franja inferior.
    """
    datos = informacion(archivo)
    if not datos.get("ok"):
        return None, None, 0.0
    duracion = datos.get("duracion_s") or 0
    candidatos = []
    for i in range(1, muestras + 1):
        segundo = duracion * i / (muestras + 1)
        fotograma = capturar(archivo, segundo)
        if fotograma is None:
            continue
        franja = recortar_pie(fotograma, alto_relativo)
        candidatos.append((_densidad_de_texto(franja), segundo, franja))
    if not candidatos:
        return None, None, 0.0
    densidad, segundo, franja = max(candidatos, key=lambda c: c[0])
    return franja, segundo, densidad


def fecha_de_video(archivo: Path, motor_ocr=None, segundo: float | None = None,
                   carpeta_evidencia: Path | None = None, caso: str = "",
                   alto_relativo: float = 0.16) -> dict:
    """Fotograma + pie + lectura + validación. Devuelve todo, incluida la ruta del recorte."""
    archivo = Path(archivo)
    datos = informacion(archivo)
    salida = {"video": str(archivo), "info": datos, "segundo": segundo, "recorte": "",
              "texto": "", "fecha": None, "hora": None, "estado": "sin_leer", "nota": ""}
    if not datos.get("ok"):
        salida["estado"] = "error"
        salida["nota"] = datos.get("error", "")
        return salida
    if segundo is None:
        # el rótulo está durante todo el vídeo: se elige el pie con más texto
        pie, segundo_elegido, densidad = mejor_pie(archivo, alto_relativo=alto_relativo)
        salida["segundo"] = segundo_elegido
        salida["densidad_texto"] = round(densidad, 2)
    else:
        fotograma = capturar(archivo, segundo)
        pie = recortar_pie(fotograma, alto_relativo) if fotograma is not None else None
    if pie is None:
        salida["estado"] = "error"
        salida["nota"] = "no se pudo leer el fotograma"
        return salida
    if carpeta_evidencia is not None and pie is not None:
        carpeta_evidencia.mkdir(parents=True, exist_ok=True)
        destino = carpeta_evidencia / f"{caso or archivo.stem}_pie_video.png"
        cv2.imwrite(str(destino), pie)
        salida["recorte"] = str(destino)
    if motor_ocr is None:
        salida["nota"] = ("sin motor OCR: el pie se guarda como imagen para revisarlo a ojo")
        salida["estado"] = "sin_leer"
        return salida
    texto = motor_ocr(pie) or ""
    salida["texto"] = texto
    encontrado = interpretar(texto)
    salida["fecha"], salida["hora"] = encontrado["fecha"], encontrado["hora"]
    if encontrado["fecha"]:
        salida["estado"] = "leido"
    else:
        salida["estado"] = "sin_fecha"
        salida["nota"] = "el pie no contiene una fecha reconocible"
    return salida
