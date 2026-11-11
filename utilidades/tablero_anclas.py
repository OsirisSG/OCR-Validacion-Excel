"""Anclas del tablero: saber QUÉ es cada foto antes de leerla (Fase 3 del plan, P13).

Tres marcadores visuales identifican sin ambigüedad las etiquetas del tablero, y cada uno alimenta
una columna distinta del libro:

| Ancla | Aspecto en la foto | Qué es | Columna del libro |
|---|---|---|---|
| **pestaña azul** | rectángulo azul saturado pegado al extremo de una etiqueta blanca | fecha de fabricación del tablero | `dashboard_date` |
| **estampa de color** | pegatina redonda magenta/rosa con 3 caracteres | nivel de ingeniería, a veces girado 180° | `dashboard_engineering_level` |
| **código cuadrado** | DataMatrix con borde en L + texto vertical al lado | número de parte / serie del tablero | `dashboard_part_number` |

Con el ancla localizada, el sistema ya sabe qué campo está mirando: no hace falta adivinar por el
texto. Además se corrige la orientación (180° en las estampas, 90° en las etiquetas verticales)
antes de leer, que es donde el OCR se rompe.

Todo se calcula por color y forma, sin modelos: son tres reglas geométricas estables.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

# Rangos HSV de los anclas (amplios a propósito: la luz del taller cambia)
RANGOS_COLOR = {
    "azul": ((95, 80, 50), (135, 255, 255)),
    "estampa": ((135, 70, 70), (178, 255, 255)),   # magenta / rosa
}
AREA_MINIMA = 600          # píxeles: por debajo es ruido
RELACION_MAXIMA_ETIQUETA = 12.0

# Qué columna del libro alimenta cada ancla
CAMPO_POR_ANCLA = {
    "pestana_azul": "dashboard_date",
    "estampa_color": "dashboard_engineering_level",
    "codigo_cuadrado": "dashboard_part_number",
}

MAPA_180 = {"0": "0", "1": "1", "2": "2", "5": "5", "6": "9", "8": "8", "9": "6",
            "E": "3", "S": "S", "h": "4", "L": "7", "Z": "2", "O": "O"}


@dataclass
class Ancla:
    tipo: str
    caja: tuple[int, int, int, int]          # x, y, w, h en píxeles de la imagen original
    area: int
    angulo: float = 0.0
    color: str = ""
    nota: str = ""
    campo: str = field(default="")

    def as_dict(self) -> dict:
        return {"tipo": self.tipo, "caja": list(self.caja), "area": self.area,
                "angulo": round(self.angulo, 1), "color": self.color, "nota": self.nota,
                "campo": self.campo or CAMPO_POR_ANCLA.get(self.tipo, "")}


def _blobs(mascara, area_minima: int = AREA_MINIMA) -> list[tuple[int, tuple]]:
    n, _, stats, centroides = cv2.connectedComponentsWithStats(mascara, 8)
    salida = []
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        if area >= area_minima:
            salida.append((area, (x, y, w, h)))
    return sorted(salida, reverse=True)


def _mascara_color(imagen, nombre: str):
    hsv = cv2.cvtColor(imagen, cv2.COLOR_BGR2HSV)
    bajo, alto = RANGOS_COLOR[nombre]
    mascara = cv2.inRange(hsv, np.array(bajo, np.uint8), np.array(alto, np.uint8))
    nucleo = np.ones((5, 5), np.uint8)
    return cv2.morphologyEx(mascara, cv2.MORPH_OPEN, nucleo)


def _es_redonda(mascara_blob) -> bool:
    contornos, _ = cv2.findContours(mascara_blob, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contornos:
        return False
    contorno = max(contornos, key=cv2.contourArea)
    area = cv2.contourArea(contorno)
    perimetro = cv2.arcLength(contorno, True) or 1
    circularidad = 4 * np.pi * area / (perimetro ** 2)
    return circularidad > 0.65


def _angulo(imagen, caja) -> float:
    x, y, w, h = caja
    recorte = imagen[y:y + h, x:x + w]
    gris = cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY)
    _, binaria = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    puntos = cv2.findNonZero(binaria)
    if puntos is None:
        return 0.0
    (_, _), (_, _), angulo = cv2.minAreaRect(puntos)
    if angulo > 45:
        angulo -= 90
    return float(angulo)


def _caja_data_matrix(imagen, estricto: bool = True) -> tuple[int, int, int, int] | None:
    """Busca un cuadrado oscuro con borde en L (DataMatrix): esquinas rectas y densidad alta."""
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
    _, binaria = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contornos, _ = cv2.findContours(binaria, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    alto, ancho = gris.shape
    mejor = None
    for contorno in contornos:
        x, y, w, h = cv2.boundingRect(contorno)
        if w < 60 or h < 60:
            continue
        relacion = w / h
        if not 0.7 <= relacion <= 1.4:
            continue
        area = w * h
        if area < 5000 or area > 0.12 * alto * ancho:
            continue
        relleno = cv2.contourArea(contorno) / area
        # un DataMatrix es un patrón: parte oscura y parte clara dentro del mismo cuadrado.
        # Un agujero o una sombra es todo oscuro, y se descarta por el porcentaje de claros.
        luminoso = float((gris[y:y + h, x:x + w] > 150).mean())
        if relleno < 0.12 or luminoso < 0.12:
            continue
        umbral_std = 22.0 if estricto else 12.0
        if not _parece_cuadricula(gris[y:y + h, x:x + w], std_minimo=umbral_std):
            continue
        if not _sobre_fondo_claro(gris, x, y, w, h, minimo=150 if estricto else 60):
            continue
        if mejor is None or area > mejor[0]:
            mejor = (area, (x, y, w, h))
    return mejor[1] if mejor else None


def _parece_cuadricula(recorte, celdas: int = 8, std_minimo: float = 22.0) -> bool:
    """Un DataMatrix mezcla claros y oscuros; un agujero o una sombra es todo negro.

    Se mira la media de cada celda de una rejilla: si todas son parecidas, no es un código.
    """
    if recorte.size == 0:
        return False
    alto, ancho = recorte.shape[:2]
    medias = []
    for i in range(celdas):
        for j in range(celdas):
            trozo = recorte[i * alto // celdas:(i + 1) * alto // celdas,
                            j * ancho // celdas:(j + 1) * ancho // celdas]
            if trozo.size:
                medias.append(float(trozo.mean()))
    if len(medias) < 4:
        return False
    return float(np.std(medias)) > std_minimo and float(np.mean(medias)) > 40


def _sobre_fondo_claro(gris, x: int, y: int, w: int, h: int, margen: int = 12,
                       minimo: float = 150) -> bool:
    """Un DataMatrix va pegado en una etiqueta blanca: su marco exterior es claro."""
    alto, ancho = gris.shape[:2]
    y0, y1 = max(0, y - margen), min(alto, y + h + margen)
    x0, x1 = max(0, x - margen), min(ancho, x + w + margen)
    marco = np.concatenate([
        gris[y0:y, x0:x1].ravel(), gris[y + h:y1, x0:x1].ravel(),
        gris[y0:y1, x0:x].ravel(), gris[y0:y1, x + w:x1].ravel()])
    if marco.size == 0:
        return False
    return float(np.median(marco)) > minimo


def detectar(imagen) -> list[Ancla]:
    """Devuelve las anclas encontradas, ya clasificadas. La primera es la más fiable."""
    anclas: list[Ancla] = []

    mascara_azul = _mascara_color(imagen, "azul")
    for area, caja in _blobs(mascara_azul)[:2]:
        x, y, w, h = caja
        if h >= w:                             # la pestaña azul es vertical
            anclas.append(Ancla("pestana_azul", caja, area, color="azul",
                                nota="etiqueta blanca a la izquierda de la pestaña"))

    mascara_estampa = _mascara_color(imagen, "estampa")
    for area, caja in _blobs(mascara_estampa)[:2]:
        recorte = mascara_estampa[caja[1]:caja[1] + caja[3], caja[0]:caja[0] + caja[2]]
        redonda = _es_redonda(recorte)
        angulo = _angulo(imagen, caja)
        anclas.append(Ancla("estampa_color", caja, area, angulo=angulo, color="magenta",
                            nota="pegatina redonda con 3 caracteres" if redonda
                                 else "mancha de color: revisar a mano"))

    hay_color = any(a.tipo in ("pestana_azul", "estampa_color") for a in anclas)
    caja_codigo = _caja_data_matrix(imagen, estricto=True)
    if caja_codigo is None and not hay_color:
        # sin ancla de color, esta foto sólo puede ser la del código: se relaja el criterio
        caja_codigo = _caja_data_matrix(imagen, estricto=False)
    if caja_codigo:
        x, y, w, h = caja_codigo
        anclas.append(Ancla("codigo_cuadrado", caja_codigo, w * h, angulo=_angulo(imagen, caja_codigo),
                            color="blanco/negro", nota="DataMatrix + texto vertical al lado"))
    return anclas


def que_es(imagen) -> dict:
    """Resumen legible: qué etiqueta es esta foto y a qué columna va."""
    anclas = detectar(imagen)
    if not anclas:
        return {"tipo": "desconocido", "campo": "", "confianza": 0.0, "anclas": [],
                "nota": "sin ancla conocida: no se puede saber qué campo es"}
    principal = anclas[0]
    principal_dict = principal.as_dict()
    return {"tipo": principal.tipo, "campo": principal_dict["campo"],
            "confianza": 0.9 if len(anclas) == 1 else 0.7,
            "anclas": [a.as_dict() for a in anclas],
            "nota": principal.nota}


def recorte_etiqueta(imagen, ancla: Ancla, margen: int = 40):
    """Recorta la etiqueta completa a partir de su ancla (la pestaña está en un extremo)."""
    x, y, w, h = ancla.caja
    alto, ancho = imagen.shape[:2]
    if ancla.tipo == "pestana_azul":
        # la etiqueta blanca se extiende hacia la izquierda de la pestaña
        izq = max(0, x - int(w * 9))
        return imagen[max(0, y - margen):min(alto, y + h + margen), izq:min(ancho, x + w + margen)]
    if ancla.tipo == "codigo_cuadrado":
        return imagen[max(0, y - 2 * h):min(alto, y + 2 * h), max(0, x - 2 * w):min(ancho, x + 2 * w)]
    return imagen[max(0, y - margen):min(alto, y + h + margen),
                  max(0, x - margen):min(ancho, x + w + margen)]


def desrotar_180(texto: str) -> str:
    """Deshace una lectura girada 180° (la estampa rosa puede venir al revés).

    «E0S» → «S03»: se invierte el orden y se deshace el mapa de caracteres.
    """
    limpio = "".join(c for c in str(texto or "").upper() if not c.isspace())
    return "".join(MAPA_180.get(c, c) for c in reversed(limpio))


def reordenar_nivel(texto: str) -> str:
    """«S03» → «03S»: en la estampa el nivel puede venir con la letra delante."""
    limpio = "".join(c for c in str(texto or "").upper() if not c.isspace())
    if len(limpio) == 3 and limpio[0].isalpha() and limpio[1:].isdigit():
        return limpio[1:] + limpio[0]
    return limpio


def normalizar_giro(texto: str, campo: str, validador) -> tuple[str, str]:
    """Devuelve (texto, como_se_leyo). Prueba tal cual, girada 180° y con la letra delante."""
    if validador(campo, texto):
        return texto, "tal_cual"
    if campo.endswith("engineering_level"):
        reordenado = reordenar_nivel(texto)
        if validador(campo, reordenado):
            return reordenado, "letra_delante"
        girado_y_reordenado = reordenar_nivel(desrotar_180(texto))
        if validador(campo, girado_y_reordenado):
            return girado_y_reordenado, "girada_180_y_letra_delante"
    alterno = desrotar_180(texto)
    if validador(campo, alterno):
        return alterno, "girada_180"
    return texto, "sin_corregir"
