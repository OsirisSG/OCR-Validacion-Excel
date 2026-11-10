"""utilidades/etiqueta_roi.py — Lectura de la etiqueta del módulo en fotos reales.

Problema que resuelve (medido sobre el corpus real, 2026-10-30)
--------------------------------------------------------------
Las fotos de etiqueta del taller están tomadas **de cerca pero giradas** (la
etiqueta se lee en vertical) y el texto queda repartido en cajas sueltas. El OCR
sobre la foto completa devuelve caracteres aislados: `'2'`, `'8'`, `'0'`… y el
extractor, con razón, no puede formar ningún campo.

Este módulo no sustituye al motor de OCR (`ocr_engine`): recibe una función de
lectura ya construida y se limita a **preparar la imagen y ordenar el texto**:

1. `detectar_regiones_etiqueta`  — propone recortes candidatos (zona clara y
   poco saturada, que es como se ve una etiqueta sobre una pieza oscura).
2. `elegir_orientacion`          — prueba 0°/90°/180°/270° y se queda con la que
   produce texto de verdad (palabras, no caracteres sueltos).
3. `reconstruir_lineas`          — vuelve a unir las cajas en renglones por
   geometría, para que `2GJ 880 204` + `J` sea `2GJ 880 204 J`.
4. `leer_etiqueta`               — todo lo anterior junto, devolviendo texto,
   orientación elegida, recorte usado y las cajas originales.

El módulo no decide qué campo es cada cosa: eso sigue siendo competencia de
`flujo_empresarial.extraer_candidatos_texto`, que es el único que conoce las
reglas del libro.
"""
from __future__ import annotations

import gc
from dataclasses import dataclass, field

import cv2
import numpy as np

ORIENTACIONES = (
    (0, None, "0"),
    (90, cv2.ROTATE_90_CLOCKWISE, "90"),
    (180, cv2.ROTATE_180, "180"),
    (270, cv2.ROTATE_90_COUNTERCLOCKWISE, "270"),
)


@dataclass
class LecturaEtiqueta:
    """Resultado de leer una etiqueta."""

    texto: str = ""
    lineas: list[str] = field(default_factory=list)
    orientacion: int = 0
    roi: tuple[int, int, int, int] | None = None
    tokens: list[dict] = field(default_factory=list)
    puntuacion: float = 0.0
    intentos: list[dict] = field(default_factory=list)


def _a_gris(imagen: np.ndarray) -> np.ndarray:
    if imagen.ndim == 2:
        return imagen
    return cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)


def detectar_regiones_etiqueta(imagen_bgr: np.ndarray, maximo: int = 3,
                               area_minima: float = 0.02,
                               area_maxima: float = 0.35) -> list[tuple[int, int, int, int]]:
    """Propone recortes donde puede haber una etiqueta.

    Criterio: zonas claras (alta luminosidad) y poco saturadas, que es como se
    distinguen las etiquetas blancas sobre piezas oscuras. Se devuelven como
    mucho `maximo` cajas, ordenadas de mayor a menor área.

    La función solo PROPONE: si no encuentra nada devuelve una lista vacía y el
    llamador debe seguir con la imagen completa, nunca inventar un recorte.
    """
    if imagen_bgr is None or imagen_bgr.size == 0:
        return []
    alto, ancho = imagen_bgr.shape[:2]
    area_total = float(alto * ancho)
    if imagen_bgr.ndim == 3:
        hsv = cv2.cvtColor(imagen_bgr, cv2.COLOR_BGR2HSV)
        saturacion = hsv[:, :, 1]
        valor = hsv[:, :, 2]
    else:
        saturacion = np.zeros((alto, ancho), dtype=np.uint8)
        valor = imagen_bgr
    # blanco = mucha luz y poca saturación
    mascara = ((valor > 150) & (saturacion < 70)).astype(np.uint8) * 255
    nucleo = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, nucleo, iterations=2)
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_OPEN, nucleo, iterations=1)
    contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidatos: list[tuple[float, tuple[int, int, int, int]]] = []
    for contorno in contornos:
        x, y, w, h = cv2.boundingRect(contorno)
        if w < 40 or h < 40:
            continue
        proporcion = (w * h) / area_total
        if proporcion < area_minima or proporcion > area_maxima:
            continue
        candidatos.append((float(w * h), (int(x), int(y), int(w), int(h))))
    candidatos.sort(key=lambda par: -par[0])
    return [caja for _, caja in candidatos[:maximo]]


def _normalizar_tokens(tokens) -> list[dict]:
    """Acepta cajas de EasyOCR ([[x,y],…], texto, confianza) o dicts."""
    salida: list[dict] = []
    for token in tokens or []:
        if isinstance(token, dict):
            texto = token.get("texto") or token.get("text") or ""
            confianza = float(token.get("confianza", token.get("conf", 0.0)) or 0.0)
            bbox = token.get("bbox")
            if bbox and len(bbox) == 4 and not isinstance(bbox[0], (list, tuple)):
                x, y, w, h = [float(v) for v in bbox]
                puntos = [(x, y), (x + w, y), (x, y + h), (x + w, y + h)]
            else:
                puntos = bbox or []
            salida.append({"texto": str(texto), "confianza": confianza, "puntos": puntos})
            continue
        try:
            puntos, texto, confianza = token[0], token[1], token[2]
        except (IndexError, TypeError):
            continue
        salida.append({"texto": str(texto), "confianza": float(confianza), "puntos": puntos})
    for token in salida:
        xs = [float(p[0]) for p in token["puntos"]] or [0.0]
        ys = [float(p[1]) for p in token["puntos"]] or [0.0]
        token["x0"], token["x1"] = min(xs), max(xs)
        token["y0"], token["y1"] = min(ys), max(ys)
        token["cy"] = (token["y0"] + token["y1"]) / 2.0
        token["alto"] = max(1.0, token["y1"] - token["y0"])
    return salida


def puntuar_tokens(tokens) -> float:
    """Cuánto texto *de verdad* hay: palabras de 3+ caracteres, ponderadas.

    Un OCR de etiqueta girada devuelve muchos caracteres sueltos con confianza
    alta; eso puntúa poco. Una lectura correcta devuelve palabras.
    """
    normalizados = _normalizar_tokens(tokens)
    if not normalizados:
        return 0.0
    puntuacion = 0.0
    for token in normalizados:
        limpio = token["texto"].strip()
        if len(limpio) >= 3:
            puntuacion += 1.0 + min(token["confianza"], 1.0)
        elif len(limpio) == 2:
            puntuacion += 0.25
    return puntuacion


def reconstruir_lineas(tokens, tolerancia: float = 0.6) -> list[str]:
    """Une las cajas en renglones usando la geometría.

    `tolerancia` es la fracción de la altura mediana de las cajas que se admite
    como desviación vertical para considerar que dos cajas están en la misma
    línea.
    """
    normalizados = _normalizar_tokens(tokens)
    if not normalizados:
        return []
    alturas = sorted(t["alto"] for t in normalizados)
    mediana = alturas[len(alturas) // 2]
    limite = max(4.0, mediana * tolerancia)
    ordenados = sorted(normalizados, key=lambda t: (t["cy"], t["x0"]))
    lineas: list[list[dict]] = []
    for token in ordenados:
        if lineas:
            actual = lineas[-1]
            centro = sum(t["cy"] for t in actual) / len(actual)
            if abs(token["cy"] - centro) <= limite:
                actual.append(token)
                continue
        lineas.append([token])
    textos: list[str] = []
    for linea in lineas:
        linea.sort(key=lambda t: t["x0"])
        texto = " ".join(t["texto"].strip() for t in linea if t["texto"].strip())
        if texto:
            textos.append(texto)
    return textos


def _ampliar(imagen: np.ndarray, factor: float, lado_maximo: int = 1280) -> np.ndarray:
    """Amplía el recorte sin pasarse de tamaño.

    El tope no es capricho: el detector del motor limita su entrada y, además,
    un recorte grande dispara la memoria (medido: el proceso muere por OOM en un
    entorno de 2 GB). Si al ampliar se pasa del tope, se reduce después en vez
    de entregar una imagen que el motor va a encoger de todas formas.
    """
    if factor > 1.01:
        imagen = cv2.resize(imagen, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
    alto, ancho = imagen.shape[:2]
    lado = max(alto, ancho)
    if lado_maximo and lado > lado_maximo:
        escala = lado_maximo / float(lado)
        imagen = cv2.resize(imagen, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA)
    return imagen


def leer_etiqueta(imagen_bgr: np.ndarray, lector, escalas=(1.0, 1.5),
                  orientaciones=ORIENTACIONES, regiones: int = 2,
                  lado_maximo: int = 1280) -> LecturaEtiqueta:
    """Lee la etiqueta de una foto: primero orientación, después escala.

    `lector` es una función `imagen_gris -> lista de cajas` (por ejemplo, la del
    motor de `ocr_engine`). El módulo no construye ningún motor propio.

    Dos fases, medidas sobre el corpus real:

    1. Se prueban los recortes candidatos y las cuatro orientaciones a escala
       natural. Es barato y descarta la foto girada, que es el caso normal.
    2. Con el recorte y la orientación ya elegidos se prueban las escalas y se
       queda la que produce más texto de verdad. Ampliar de más empeora la
       lectura (medido: ×1.5 acierta `2GJ 880 204 J`; ×2.0 confunde `2GJ` con
       `26J`), así que no se amplía a ciegas.

    Si no hay recortes candidatos se usa la imagen completa: nunca se devuelve
    vacío por no haber encontrado una etiqueta.
    """
    resultado = LecturaEtiqueta()
    if imagen_bgr is None or imagen_bgr.size == 0 or lector is None:
        return resultado

    regiones_candidatas = detectar_regiones_etiqueta(imagen_bgr, maximo=max(1, regiones))
    if not regiones_candidatas:
        # Sin zona clara no hay etiqueta: es una foto de detalle (un tornillo, el
        # cojín, un retazo). Se hace UNA sola pasada sobre la imagen completa en
        # lugar de ocho o doce: el resultado es el mismo y se evita gastar
        # memoria y tiempo en una foto que no va a dar datos.
        alto, ancho = imagen_bgr.shape[:2]
        regiones_candidatas = [(0, 0, ancho, alto)]
        orientaciones = (ORIENTACIONES[0],)
        escalas = (1.0,)

    def _leer(recorte, grados, operacion, escala):
        imagen = recorte if operacion is None else cv2.rotate(recorte, operacion)
        imagen = _a_gris(imagen)
        imagen = _ampliar(imagen, escala, lado_maximo)
        try:
            tokens = lector(imagen)
        except Exception as exc:                       # noqa: BLE001
            resultado.intentos.append({"orientacion": grados, "escala": escala,
                                       "puntuacion": 0.0, "error": type(exc).__name__})
            return 0.0, []
        puntuacion = puntuar_tokens(tokens)
        resultado.intentos.append({"orientacion": grados, "escala": escala,
                                   "puntuacion": round(puntuacion, 2),
                                   "tokens": len(tokens or [])})
        # El motor acumula memoria entre lecturas; se libera en cada vuelta.
        gc.collect()
        return puntuacion, tokens

    # ---- fase 1: recorte y orientación
    mejor = {"puntuacion": 0.0, "roi": None, "grados": 0, "operacion": None}
    for caja in regiones_candidatas:
        x, y, w, h = caja
        recorte = imagen_bgr[y:y + h, x:x + w]
        if recorte.size == 0:
            continue
        for grados, operacion, _ in orientaciones:
            puntuacion, _tokens = _leer(recorte, grados, operacion, float(escalas[0]))
            if puntuacion > mejor["puntuacion"]:
                mejor = {"puntuacion": puntuacion, "roi": (int(x), int(y), int(w), int(h)),
                         "grados": grados, "operacion": operacion}
    if mejor["roi"] is None:
        return resultado

    # ---- fase 2: escala sobre el ganador
    #
    # Se conservan las lecturas de las escalas que quedan cerca de la mejor y se
    # UNEN sus renglones. Medido: a ×1.5 se lee `2GJ 880 204 J` completo y a ×1.0
    # se lee `02S`; quedarse con una sola lectura pierde un campo que la otra sí
    # tenía. Unir no inventa nada: los valores que no coincidan se marcan para
    # revisión en el extractor, tal como pide la guía con las etiquetas repetidas.
    x, y, w, h = mejor["roi"]
    recorte = imagen_bgr[y:y + h, x:x + w]
    lecturas: list[tuple[float, list[str], list]] = []
    for escala in escalas:
        puntuacion, tokens = _leer(recorte, mejor["grados"], mejor["operacion"], float(escala))
        lecturas.append((puntuacion, reconstruir_lineas(tokens), tokens))
    if not lecturas:
        return resultado
    maxima = max(p for p, _l, _t in lecturas)
    if maxima <= 0:
        return resultado
    lineas_union: list[str] = []
    tokens_union: list = []
    for puntuacion, lineas, tokens in lecturas:
        if puntuacion < 0.8 * maxima:
            continue
        for linea in lineas:
            if linea not in lineas_union:
                lineas_union.append(linea)
        tokens_union.extend(_normalizar_tokens(tokens))
    resultado.lineas = lineas_union
    resultado.texto = "\n".join(lineas_union)
    resultado.tokens = tokens_union
    resultado.orientacion = mejor["grados"]
    resultado.roi = mejor["roi"]
    resultado.puntuacion = maxima
    return resultado
