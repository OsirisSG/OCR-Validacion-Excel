"""Lectura de la barra de estado del vídeo (P15).

La barra inferior de los vídeos eDAG es una línea de **texto monoespaciado blanco sobre negro**:

    VW316/5  252590  RdW  RT  NOM  0ms  EDAG Mex  BMG  19 JUN 25  Rec5000 fps, Schutter 80us

De ahí salen seis campos del libro de golpe (proyecto, número de prueba, variante, temperatura,
tipo de generador, delay), el **lugar de prueba** y la **fecha de prueba**.

Como el texto es monoespaciado y siempre el mismo tipo de letra, no hace falta un motor OCR
genérico: se segmenta por paso fijo, se compara cada glifo con una plantilla y se valida el
resultado con el protocolo de cada campo. Es el caso ideal de «salida acotada»: el alfabeto que
puede aparecer está limitado y el formato es fijo.
"""
from __future__ import annotations

import re
from collections import Counter

import cv2
import numpy as np

ALFABETO = ("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
            "/.,:;-_+%°()*#&@'\"!?=")
ALTO_GLIFO = 16
UMBRAL_BLANCO = 150


def franja(imagen, alto_relativo: float = 0.030, minimo: int = 18):
    """Franja de estado: pegada al borde inferior."""
    if imagen is None:
        return None
    alto = imagen.shape[0]
    filas = max(minimo, int(alto * alto_relativo))
    return imagen[alto - filas:alto, :]


def binarizar(imagen) -> np.ndarray:
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY) if imagen.ndim == 3 else imagen
    _, binaria = cv2.threshold(gris, UMBRAL_BLANCO, 255, cv2.THRESH_BINARY)
    return binaria


def _runs(perfil: np.ndarray) -> list[tuple[int, int]]:
    columnas = np.where(perfil > 0)[0]
    if columnas.size == 0:
        return []
    runs, inicio, previo = [], columnas[0], columnas[0]
    for columna in columnas[1:]:
        if columna - previo > 1:
            runs.append((int(inicio), int(previo)))
            inicio = columna
        previo = columna
    runs.append((int(inicio), int(previo)))
    return runs


def avance(franja_binaria: np.ndarray) -> int:
    """Paso horizontal del texto (ancho de celda), medido con los huecos entre glifos.

    En la barra eDAG el texto es monoespaciado: entre dos glifos estrechos consecutivos el paso
    es constante (11 px en los vídeos de 960 px). Se toma la moda de esos pasos, que es más
    robusto que la autocorrelación cuando la imagen tiene escena detrás.
    """
    perfil = (franja_binaria > 0).sum(axis=0)
    runs = _runs(perfil)
    if len(runs) < 3:
        return 0
    pasos = []
    for (_, fin), (inicio, _) in zip(runs, runs[1:]):
        ancho_izq, ancho_der = fin - runs[0][0], 0                           # noqa: F841
        paso = inicio - runs[runs.index((inicio, _)) - 1][0] if False else inicio
        del ancho_izq, ancho_der, paso
    for i in range(len(runs) - 1):
        ancho_i = runs[i][1] - runs[i][0] + 1
        ancho_j = runs[i + 1][1] - runs[i + 1][0] + 1
        paso = runs[i + 1][0] - runs[i][0]
        if ancho_i <= 14 and ancho_j <= 14 and 5 <= paso <= 20:
            pasos.append(paso)
    if not pasos:
        return 0
    return Counter(pasos).most_common(1)[0][0]


class Banco(dict):
    """Diccionario de glifos que además recuerda el paso y el alineamiento con que se aprendió."""

    def __init__(self, *args, paso: int = 0, desplazamiento: int = 0, recorte: int = 0, **kw):
        super().__init__(*args, **kw)
        self.paso, self.desplazamiento, self.recorte = paso, desplazamiento, recorte


def rejilla(franja_binaria: np.ndarray, paso: int, desplazamiento: int = 0):
    """Celdas de ancho fijo desde `desplazamiento`, incluidas las vacías (espacios)."""
    alto = franja_binaria.shape[0]
    salida = []
    for x in range(desplazamiento, franja_binaria.shape[1] - paso + 1, paso):
        celda = franja_binaria[:, x:x + paso]
        ys = np.where(celda.any(axis=1))[0]
        glifo = celda[ys.min():ys.max() + 1, :] if ys.size else np.zeros((1, paso), np.uint8)
        salida.append((x, glifo))
    return salida


def segmentar(franja_binaria: np.ndarray, paso: int) -> list[tuple[int, np.ndarray | None]]:
    """Segmenta por huecos reales (no por rejilla fija) para que el texto no derive.

    Entre «VW316/5» y el final hay ~85 caracteres: una rejilla de paso entero se desalinea a la
    mitad. Aquí se buscan los tramos con tinta, se parten los que son más anchos que un carácter
    y los huecos grandes se marcan como espacio.
    """
    perfil = (franja_binaria > 0).sum(axis=0)
    runs = _runs(perfil)
    salida: list[tuple[int, np.ndarray | None]] = []
    previo_fin = None
    for inicio, fin in runs:
        ancho = fin - inicio + 1
        if previo_fin is not None and inicio - previo_fin > paso * 0.55:
            salida.append((previo_fin + 1, None))            # espacio
        partes = max(1, int(round(ancho / paso)))
        for k in range(partes):
            desde = inicio + round(k * ancho / partes)
            hasta = inicio + round((k + 1) * ancho / partes)
            tira = franja_binaria[:, desde:hasta]
            ys = np.where(tira.any(axis=1))[0]
            glifo = tira[ys.min():ys.max() + 1, :] if ys.size else None
            salida.append((desde, glifo))
        previo_fin = fin
    return salida


def mejor_desplazamiento(franja_binaria: np.ndarray, paso: int) -> int:
    """Alinea la rejilla con los glifos.

    Con el paso correcto pero un desplazamiento malo, cada glifo queda partido en dos celdas.
    Se elige el desplazamiento en el que las celdas con contenido tienen **bordes vacíos**
    (o sea, el glifo entra completo y centrado).
    """
    mejor, puntaje_mejor = 0, -1.0
    for desplazamiento in range(paso):
        celdas = rejilla(franja_binaria, paso, desplazamiento)
        puntajes = []
        for _, glifo in celdas:
            if glifo.shape[0] <= 2 or glifo.max() == 0:
                continue
            columnas = glifo.any(axis=0)
            if not columnas.any():
                continue
            primera = int(np.argmax(columnas))
            ultima = int(len(columnas) - np.argmax(columnas[::-1]) - 1)
            puntajes.append(min(primera, glifo.shape[1] - 1 - ultima))
        if puntajes and float(np.mean(puntajes)) > puntaje_mejor:
            mejor, puntaje_mejor = desplazamiento, float(np.mean(puntajes))
    return mejor


def _celdas(franja_binaria: np.ndarray, paso: int) -> list[tuple[int, np.ndarray]]:
    """Trocea la franja en celdas de ancho fijo; devuelve (x, glifo) por celda con contenido."""
    salida = []
    alto = franja_binaria.shape[0]
    for x in range(0, franja_binaria.shape[1] - paso + 1, paso):
        celda = franja_binaria[:, x:x + paso]
        if celda.max() == 0:
            continue
        ys = np.where(celda.any(axis=1))[0]
        if ys.size == 0:
            continue
        recorte = celda[ys.min():ys.max() + 1, :]
        if recorte.shape[0] < alto * 0.3:              # ruido (una línea o un punto)
            continue
        salida.append((x, recorte))
    return salida


def _normalizar(glifo: np.ndarray) -> np.ndarray:
    return cv2.resize(glifo, (12, ALTO_GLIFO), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0


def plantillas(fuente: str = "hershey", escala: float = 0.45, grosor: int = 1) -> dict[str, np.ndarray]:
    """Plantillas sintéticas del alfabeto con la fuente monoespaciada de OpenCV."""
    tipos = {"hershey": cv2.FONT_HERSHEY_PLAIN, "duplex": cv2.FONT_HERSHEY_DUPLEX,
             "simplex": cv2.FONT_HERSHEY_SIMPLEX}[fuente]
    salida = {}
    for caracter in ALFABETO:
        lienzo = np.zeros((28, 22), np.uint8)
        cv2.putText(lienzo, caracter, (2, 22), tipos, escala, 255, grosor, cv2.LINE_AA)
        ys, xs = np.where(lienzo > 60)
        if ys.size == 0:
            continue
        salida[caracter] = _normalizar(lienzo[ys.min():ys.max() + 1, xs.min():xs.max() + 1])
    return salida


def aprender(imagen, texto_esperado: str, paso: int | None = None) -> Banco:
    """Aprende el tipo de letra de la barra usando una lectura conocida.

    Se alinea la rejilla con el texto esperado y cada celda se guarda con su carácter. Así el banco
    sale de la propia fuente del vídeo, no de una parecida: es lo que hace que acierte.
    """
    trozo = franja(imagen)
    binaria = binarizar(trozo)
    paso = paso or avance(binaria)
    if not paso:
        return Banco()
    limpio = texto_esperado
    # el texto puede no empezar en x=0: se prueba el desplazamiento de rejilla y el arranque
    mejor = (None, -1)
    for desplazamiento in range(paso):
        celdas = rejilla(binaria, paso, desplazamiento)
        for recorte_inicial in range(0, 3):
            seleccion = celdas[recorte_inicial:]
            if len(seleccion) < len(limpio):
                continue
            aciertos = 0
            for (_, glifo), caracter in zip(seleccion, limpio):
                vacia = glifo.shape[0] <= 2 or glifo.max() == 0
                if vacia == (caracter == " "):
                    aciertos += 1
            if aciertos > mejor[1]:
                mejor = ((desplazamiento, recorte_inicial), aciertos)
    if mejor[0] is None:
        # sin coincidencia de rejilla se aprende con el segmentado adaptativo y el texto tal cual
        celdas = segmentar(binaria, paso)
        banco = Banco(paso=paso)
        for (_, glifo), caracter in zip(celdas, limpio):
            if glifo is None or caracter == " ":
                continue
            banco.setdefault(caracter, _normalizar(glifo))
        return banco
    desplazamiento, recorte_inicial = mejor[0]
    celdas = segmentar(binaria, paso)
    banco = Banco(paso=paso, desplazamiento=desplazamiento, recorte=recorte_inicial)
    for (_, glifo), caracter in zip(celdas, limpio):
        if caracter == " " or glifo is None or glifo.shape[0] <= 2 or glifo.max() == 0:
            continue
        banco.setdefault(caracter, _normalizar(glifo))
    return banco


def aprender_por_palabras(imagen, texto_esperado: str, paso: int | None = None) -> Banco:
    """Aprende el alfabeto emparejando **palabra a palabra** con una lectura conocida.

    Es más fiable que alinear la rejilla: si una palabra tiene tantos glifos como caracteres
    (`252590` → 6 glifos), el emparejamiento es directo. Las palabras que no cuadran se descartan,
    así que el banco nunca aprende etiquetas dadas de mala gana.
    """
    trozo = franja(imagen)
    binaria = binarizar(trozo)
    paso = paso or avance(binaria)
    if not paso:
        return Banco()
    # trocear el segmentado en palabras (los None son espacios)
    palabras: list[list[np.ndarray]] = [[]]
    for _, glifo in segmentar(binaria, paso):
        if glifo is None:
            if palabras[-1]:
                palabras.append([])
            continue
        if glifo.shape[0] <= 2 or glifo.max() == 0:
            continue
        palabras[-1].append(glifo)
    palabras = [p for p in palabras if p]
    esperadas = [w for w in str(texto_esperado).split() if w]
    banco = Banco(paso=paso)
    emparejadas = 0
    # se emparejan por orden, admitiendo desajustes de número de palabras
    for glifos, palabra in zip(palabras, esperadas):
        if len(glifos) != len(palabra):
            continue
        emparejadas += 1
        for glifo, caracter in zip(glifos, palabra):
            banco.setdefault(caracter, _normalizar(glifo))
    banco.emparejadas = emparejadas
    banco.palabras_vistas = len(palabras)
    return banco


def guardar_banco(banco: Banco, ruta) -> None:
    import json
    from pathlib import Path
    datos = {caracter: (m * 255).astype(np.uint8).ravel().tolist() for caracter, m in banco.items()}
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    Path(ruta).write_text(json.dumps({"alto": ALTO_GLIFO, "ancho": 12, "glifos": datos,
                                     "paso": getattr(banco, "paso", 0),
                                     "desplazamiento": getattr(banco, "desplazamiento", 0),
                                     "recorte": getattr(banco, "recorte", 0)}),
                          encoding="utf-8")


def cargar_banco(ruta) -> Banco:
    import json
    from pathlib import Path
    archivo = Path(ruta)
    if not archivo.is_file():
        return Banco()
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    return Banco({caracter: (np.array(valores, np.float32).reshape(ALTO_GLIFO, 12) / 255.0)
                  for caracter, valores in datos["glifos"].items()},
                 paso=datos.get("paso", 0), desplazamiento=datos.get("desplazamiento", 0),
                 recorte=datos.get("recorte", 0))


def clasificar(glifo: np.ndarray, banco: dict[str, np.ndarray]) -> tuple[str, float]:
    """Compara por forma (intersección sobre unión) y por correlación; gana la suma."""
    if glifo is None or getattr(glifo, "size", 0) == 0:
        return " ", 1.0
    objetivo = _normalizar(glifo)
    binario = (objetivo > 0.45).astype(np.float32)
    mejor, puntaje = "?", -1.0
    for caracter, plantilla in banco.items():
        a = cv2.resize(binario, (plantilla.shape[1], plantilla.shape[0]),
                       interpolation=cv2.INTER_AREA)
        a = (a > 0.45).astype(np.float32)
        b = (plantilla > 0.45).astype(np.float32)
        union = float(np.logical_or(a, b).sum()) or 1.0
        iou = float(np.logical_and(a, b).sum()) / union
        suma = iou + 0.25 * float(np.mean(1 - np.abs(objetivo - plantilla)))
        if suma > puntaje:
            mejor, puntaje = caracter, suma
    return mejor, puntaje


def leer(imagen, banco: Banco | None = None, paso: int | None = None) -> dict:
    """Devuelve el texto de la barra, la confianza media y las celdas leídas."""
    trozo = franja(imagen)
    binaria = binarizar(trozo)
    paso = paso or avance(binaria)
    banco = banco or plantillas()
    if not paso:
        return {"texto": "", "confianza": 0.0, "celdas": 0, "paso": 0}
    # si el banco se aprendió de este mismo vídeo, se usa su alineamiento exacto
    celdas = segmentar(binaria, paso)
    if not celdas:
        return {"texto": "", "confianza": 0.0, "celdas": 0, "paso": paso}
    letras, puntajes = [], []
    for _, glifo in celdas:
        if glifo is None:
            letras.append(" ")
            continue
        if glifo.shape[0] <= 2 or glifo.max() == 0:
            continue
        caracter, puntaje = clasificar(glifo, banco)
        letras.append(caracter)
        puntajes.append(puntaje)
    return {"texto": "".join(letras), "confianza": round(float(np.mean(puntajes)), 3),
            "celdas": len(celdas), "paso": paso}


# ---------------------------------------------------------------------------------------------
# Interpretación de la barra: de texto a campos del libro
# ---------------------------------------------------------------------------------------------
MESES = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
         "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
         "ENE": 1, "ABR": 4, "AGO": 8, "DIC": 12}

PATRON_FECHA = re.compile(r"\b(?P<dia>\d{1,2})\s*(?P<mes>[A-Z]{3})[A-Z]*\s*(?P<anio>\d{2,4})\b")
PATRON_HORA = re.compile(r"\b(?P<hora>[0-2]?\d):(?P<minuto>[0-5]\d)(?::(?P<segundo>[0-5]\d))?\b")
PATRON_NUMERO = re.compile(r"\b(?P<numero>\d{6})\b")
PATRON_DELAY = re.compile(r"\b(?P<ms>\d{1,4})\s?ms\b", re.IGNORECASE)
PATRON_PROYECTO = re.compile(r"\b(?P<proyecto>(?:VW|AU|BMW|MB|SK|SE)\s?\d{3}(?:/\d{1,2})?)\b")
PATRON_TEMP = re.compile(r"\b(?P<temp>NT|RT|HT|KT)\b")
PATRON_INFLADOR = re.compile(r"\b(?P<tipo>NOM|OGL|UGL)\b")
PATRON_VERSION = re.compile(r"\b(?P<version>RdW|RDW|RdW/2)\b")
PATRON_LUGAR = re.compile(r"\b(?P<lugar>EDAG\s?(?:Mex|Méx|Mexico|México))\b", re.IGNORECASE)


def interpretar_barra(texto: str) -> dict:
    """Convierte la barra en campos. Todo lo que devuelve se valida después con el protocolo."""
    limpio = " ".join(str(texto or "").split())
    datos: dict[str, object] = {"texto": limpio}
    fecha = PATRON_FECHA.search(limpio)
    if fecha:
        anio = int(fecha.group("anio"))
        anio = 2000 + anio if anio < 100 else anio
        mes = MESES.get(fecha.group("mes").upper())
        if mes:
            datos["test_date"] = f"{anio:04d}-{mes:02d}-{int(fecha.group('dia')):02d}"
    hora = PATRON_HORA.search(limpio)
    if hora:
        datos["hora"] = hora.group(0)
    numero = PATRON_NUMERO.search(limpio)
    if numero:
        datos["test_number"] = numero.group("numero")
    delay = PATRON_DELAY.search(limpio)
    if delay:
        datos["delay_ms"] = delay.group("ms")
    proyecto = PATRON_PROYECTO.search(limpio)
    if proyecto:
        datos["proyecto"] = proyecto.group("proyecto").replace(" ", "")
    temperatura = PATRON_TEMP.search(limpio)
    if temperatura:
        datos["temperature_condition"] = temperatura.group("temp")
    inflador = PATRON_INFLADOR.search(limpio)
    if inflador:
        datos["inflator_type"] = inflador.group("tipo")
    version = PATRON_VERSION.search(limpio)
    if version:
        datos["module_version"] = "RDW" if version.group("version").upper().startswith("RDW") else version.group("version")
    lugar = PATRON_LUGAR.search(limpio)
    if lugar:
        datos["test_place"] = " ".join(lugar.group("lugar").split()).upper().replace("MÉX", "MEX").replace("MÉXICO", "MEXICO")
    return datos


def ajustar_a_lexico(valor, lexico, maximo: int = 2):
    """Ajusta un valor leído a la lista de valores que el libro ya usa (O/0, 5/S, m/n).

    Sólo se ajusta si la distancia de edición es pequeña; si no, se devuelve `None` para que el
    campo quede como duda en vez de inventado.
    """
    if valor is None or not lexico:
        return None
    texto = str(valor).strip()
    if texto in lexico:
        return texto
    mejor, distancia_mejor = None, maximo + 1
    for candidato in lexico:
        distancia = _distancia(texto.upper(), str(candidato).upper())
        if distancia < distancia_mejor:
            mejor, distancia_mejor = candidato, distancia
    return mejor if distancia_mejor <= maximo else None


def _distancia(a: str, b: str) -> int:
    previo = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        actual = [i]
        for j, cb in enumerate(b, 1):
            actual.append(min(previo[j] + 1, actual[j - 1] + 1, previo[j - 1] + (ca != cb)))
        previo = actual
    return previo[-1]


def leer_video(archivo, muestras: int = 5, banco=None, lexico: dict | None = None) -> dict:
    """Lee la barra en varios fotogramas y **vota campo por campo**.

    Un fotograma suelto puede perder un glifo (`19 JUN 25` → sin fecha). Al votar, el valor que
    aparece en más fotogramas gana y el desacuerdo queda registrado en `acuerdo`.
    """
    lexico = lexico or {}
    captura = cv2.VideoCapture(str(archivo))
    if not captura.isOpened():
        return {"campos": {}, "acuerdo": {}, "muestras": 0, "texto": ""}
    total = int(captura.get(cv2.CAP_PROP_FRAME_COUNT) or 0) or 1
    votos: dict[str, Counter] = {}
    textos: Counter = Counter()
    confianzas: list[float] = []
    leidos = 0
    for k in range(max(1, muestras)):
        posicion = int(total * (0.15 + 0.7 * (k / max(1, muestras - 1 or 1))))
        captura.set(cv2.CAP_PROP_POS_FRAMES, min(posicion, total - 1))
        correcto, fotograma = captura.read()
        if not correcto or fotograma is None:
            continue
        lectura = leer(fotograma, banco)
        if not lectura.get("texto"):
            continue
        leidos += 1
        confianzas.append(float(lectura.get("confianza") or 0.0))
        textos[lectura["texto"]] += 1
        for campo, valor in interpretar_barra(lectura["texto"]).items():
            if campo == "texto" or valor in (None, ""):
                continue
            votos.setdefault(campo, Counter())[valor] += 1
    captura.release()
    campos: dict[str, object] = {}
    acuerdo: dict[str, float] = {}
    for campo, contador in votos.items():
        valor, cuantos = contador.most_common(1)[0]
        campos[campo] = valor
        acuerdo[campo] = round(cuantos / leidos, 2) if leidos else 0.0
    for campo, permitidos in lexico.items():
        if campo in campos:
            ajustado = ajustar_a_lexico(campos[campo], permitidos)
            if ajustado is not None:
                campos[campo] = ajustado
            else:
                acuerdo[campo] = min(acuerdo.get(campo, 0.0), 0.5)
    return {"campos": campos, "acuerdo": acuerdo, "muestras": leidos,
            "texto": textos.most_common(1)[0][0] if textos else "",
            "confianza": round(sum(confianzas) / len(confianzas), 3) if confianzas else 0.0}


def campos_disponibles() -> tuple[str, ...]:
    return ("test_number", "module_version", "temperature_condition", "inflator_type",
            "delay_ms", "test_place", "test_date", "proyecto")


# ---------------------------------------------------------------------------------------------
# Reparación del texto de la barra (P25)
#
# El banco de glifos lee la barra, pero confunde parecidos: `22250A` por `222504`, `28 MAf 25` por
# `28 MAY 25`. Como el número de prueba y los meses son conjuntos cerrados, se reparan contra ellos
# en vez de descartar la lectura.
# ---------------------------------------------------------------------------------------------
DIGITOS_POR_LETRA = {"A": "4", "S": "5", "O": "0", "Q": "0", "D": "0", "I": "1", "L": "1",
                     "B": "8", "G": "6", "Z": "2", "T": "7", "E": "8"}
MESES_POR_LETRA = {"JAN": ("JAN",), "FEB": ("FEB",), "MAR": ("MAR",), "APR": ("APR",), "MAY": ("MAY",),
                   "JUN": ("JUN",), "JUL": ("JUL",), "AUG": ("AUG",), "SEP": ("SEP",), "OCT": ("OCT",),
                   "NOV": ("NOV",), "DEC": ("DEC",)}


def reparar_numero(token: str) -> str:
    """`22250A` → `222504`. Sólo si quedan 6 dígitos y el token se parece a un número."""
    limpio = str(token or "").upper()
    if len(limpio) != 6:
        return ""
    if sum(c.isdigit() for c in limpio) < 4:
        return ""
    reparado = "".join(DIGITOS_POR_LETRA.get(c, c) for c in limpio)
    return reparado if reparado.isdigit() else ""


def reparar_dia(token: str) -> str:
    """`0A` → `04`: el día de la barra también se confunde (`A` por `4`)."""
    limpio = str(token or "").upper()
    if not limpio or len(limpio) > 2:
        return ""
    reparado = "".join(DIGITOS_POR_LETRA.get(c, c) for c in limpio)
    if reparado.isdigit() and 1 <= int(reparado) <= 31:
        return f"{int(reparado):02d}"
    return ""


def reparar_mes(token: str) -> str:
    """`MAf` → `MAY`: una letra de diferencia en un mes de tres."""
    limpio = str(token or "").upper()
    if len(limpio) != 3:
        return ""
    if limpio in MESES_POR_LETRA:
        return limpio
    for mes in MESES_POR_LETRA:
        if sum(1 for a, b in zip(limpio, mes) if a != b) == 1:
            return mes
    return ""


LEXEMAS_DE_LA_BARRA = {"NOM", "OGL", "UGL", "NT", "RT", "HT", "KT", "RDW", "EDAG", "MEX", "BMG",
                       "MS", "FPS", "REC5000", "SCHUTTER", "US"}


def _distancia(a: str, b: str) -> int:
    if a == b:
        return 0
    anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        actual = [i]
        for j, cb in enumerate(b, 1):
            actual.append(min(anterior[j] + 1, actual[j - 1] + 1, anterior[j - 1] + (ca != cb)))
        anterior = actual
    return anterior[-1]


def semanas_posibles(mes: str, dia: int, anio: int) -> str:
    """Semana ISO del día indicado (para desempatar meses parecidos)."""
    try:
        from datetime import date as _date
        return f"{_date(anio, MESES[mes], dia).isocalendar().week:02d}"
    except (KeyError, ValueError):
        return ""


def mes_que_cuadra(candidatos, dia: int, anio: int, semana: str) -> str:
    """Si `MAR` y `MAY` encajan igual, gana el mes cuya **semana ISO** coincide con la del número."""
    if not candidatos:
        return ""
    if len(candidatos) == 1:
        return candidatos[0]
    if semana:
        for mes in candidatos:
            if semanas_posibles(mes, dia, anio) == semana:
                return mes
    return candidatos[0]


def interpretar_barra_reparada(texto: str, numero_esperado: str = "",
                               semana_esperada: str = "") -> dict:
    """Interpreta la barra **reparando** número y mes con lo que ya sabemos del caso.

    * **Número**: se busca un token de 6 que, reparadas las letras por dígitos (`A`→4, `S`→5, `B`→8…),
      quede igual al número de la carpeta (o a distancia ≤ 2 de él). Sin carpeta de referencia no se
      inventa: se exige que el token sea ya de 6 dígitos.
    * **Fecha**: se busca el trío `día mes año`; si el mes se parece a dos (`MAf` ~ `MAR`/`MAY`) se elige
      el que cuadra con la **semana** del número. Un lexema conocido (`NOM`, `NT`, `RdW`…) nunca se toma
      por un mes.
    """
    tokens = str(texto or "").split()
    numero = ""
    leido_reparado = ""
    for indice, token in enumerate(tokens):
        reparado = reparar_numero(token)
        if not reparado:
            continue
        leido_reparado = leido_reparado or reparado
        if numero_esperado:
            # sólo si la reparación da EXACTAMENTE el número de la carpeta (nada de parecidos)
            if reparado == numero_esperado:
                numero = numero_esperado
                tokens[indice] = numero
                break
        elif token.isdigit():
            numero = reparado
            tokens[indice] = numero
            break
    # la semana que desempata los meses sale del número de la **carpeta** (fuente autorizada),
    # no de la lectura de la barra, que puede venir mal
    semana = semana_esperada or (numero_esperado[:2] if numero_esperado else (numero[:2] if numero else ""))
    for indice in range(len(tokens) - 2):
        dia_crudo, mes_token, anio_token = tokens[indice], tokens[indice + 1], tokens[indice + 2]
        dia = reparar_dia(dia_crudo)
        if not dia:
            continue
        if not (anio_token.isdigit() and len(anio_token) in (2, 4)):
            continue
        candidato = mes_token.upper()
        if candidato in LEXEMAS_DE_LA_BARRA:
            continue
        if candidato in MESES:
            posibilidades = [candidato]            # si ya es un mes, no se duda
        else:
            posibilidades = [mes for mes in MESES if _distancia(candidato, mes) <= 1]
        if not posibilidades:
            continue
        anio = int(anio_token)
        anio = 2000 + anio if anio < 100 else anio
        mes = mes_que_cuadra(posibilidades, int(dia), anio, semana)
        if not mes:
            continue
        tokens[indice] = dia
        tokens[indice + 1] = mes
        break
    datos = interpretar_barra(" ".join(tokens))
    if numero_esperado:
        # la carpeta es la fuente del número: si la barra no lo repite exacto, no se da por leído
        leido = datos.get("test_number")
        datos["numero_barra_leido"] = (leido if leido and leido != numero_esperado
                                       else (leido_reparado if leido_reparado != numero_esperado
                                             else ""))
        datos["test_number"] = numero or ""
    elif numero:
        datos["test_number"] = numero
    return datos
