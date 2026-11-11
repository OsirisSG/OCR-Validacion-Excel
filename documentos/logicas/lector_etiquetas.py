"""Lectura de las etiquetas del módulo y del tablero guiada por anclas (P18).

La guía del usuario («Guia de etiquetas», 7 páginas) dice de dónde sale cada dato:

* **pestaña/etiqueta azul** del tablero → `17/05/2025` → *Tablero · Fecha fabricación*;
* **estampa redonda de color** (rosa) → `03S` → *Tablero · Nivel de ingeniería*;
* **texto grabado / DataMatrix con texto vertical** → `2GJ.857.003.G` → *Tablero · Número de parte*;
* etiqueta del **módulo** (PN Cust + óvalo amarillo + Autoliv) → parte, nivel (`69K`), fecha y serie;
* el texto vertical junto al DataMatrix es la **serie** (`671 ZRZ0539958G`).

Y añade dos reglas que se implementan aquí:

1. **corroboración**: «Usar el Module para corroborar la información del tablero» → si el módulo y el
   tablero dicen cosas distintas del mismo tipo, se marca duda en vez de elegir a ciegas;
2. **prioridad**: «se usarán ambas» etiquetas cuando aparezcan dos iguales.

El motor de lectura es **intercambiable**: RapidOCR (ONNX, sin torch, funciona aquí) o el
`ocr_engine` que el usuario ya tiene instalado. Si no hay motor, no se inventa nada: el campo queda
como duda con el recorte al lado.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

PATRON_FECHA = re.compile(r"(?P<dia>\d{1,2})[/\-.](?P<mes>\d{1,2})[/\-.](?P<anio>\d{2,4})")
# el nivel siempre acaba en letra: 01S, 03S, 66K, 69K (así no se cuela un «002»)
PATRON_NIVEL = re.compile(r"^[0-9DOQSI]{2}[A-Z]$")
# el último carácter puede salir como dígito (`2GJ 880204 3`): el catálogo del libro lo repara
PATRON_PARTE = re.compile(r"(?P<pref>\d[A-Z]{2})[.\s]?(?P<bloques>\d{3}[.\s]?\d{3})[.\s]?(?P<suf>[A-Z0-9])")
PATRON_SERIE = re.compile(r"(?P<pref>\d{3})\s?(?P<resto>[A-Z]{3}\d{7}[A-Z])")
PATRON_PARTE_COMPACTO = re.compile(r"\b\d[A-Z]{2}\d{6}[A-Z]\b")

# confusiones típicas del OCR en estas etiquetas
REPARACIONES_NIVEL = {"D": "0", "O": "0", "Q": "0", "I": "1", "S": "5"}
MESES = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
         "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12, "ENE": 1, "ABR": 4, "AGO": 8, "DIC": 12}


@dataclass
class Lectura:
    texto: str = ""
    confianza: float = 0.0
    lineas: list[tuple[str, float]] = field(default_factory=list)
    motor: str = ""

    def as_dict(self) -> dict:
        return {"texto": self.texto, "confianza": round(self.confianza, 3),
                "motor": self.motor, "lineas": [list(x) for x in self.lineas]}


def _rapidocr():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception:                                        # noqa: BLE001
        return None
    motor = RapidOCR()
    cache: dict[int, object] = {}

    def leer(imagen) -> list[tuple[str, float]]:
        if id(motor) not in cache:
            cache[id(motor)] = True
        resultado, _ = motor(imagen)
        if not resultado:
            return []
        salida = []
        for caja, texto, conf in resultado:
            try:
                salida.append((str(texto), float(conf)))
            except (TypeError, ValueError):
                continue
        return salida

    leer.nombre = "rapidocr"
    return leer


def _ocr_engine_del_proyecto():
    """Adaptador para el `ocr_engine` que el usuario ya tiene instalado (easyocr)."""
    try:
        import ocr_engine                                          # type: ignore
    except Exception:                                              # noqa: BLE001
        return None
    funciones = [getattr(ocr_engine, n) for n in dir(ocr_engine)
                 if callable(getattr(ocr_engine, n)) and "texto" in n.lower()]
    if not funciones:
        return None
    funcion = funciones[0]

    def leer(imagen) -> list[tuple[str, float]]:
        try:
            resultado = funcion(imagen)
        except Exception:                                          # noqa: BLE001
            return []
        if isinstance(resultado, str):
            return [(resultado, 0.5)]
        salida = []
        for item in resultado or []:
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                salida.append((str(item[0]), float(item[-1])))
            elif isinstance(item, str):
                salida.append((item, 0.5))
        return salida

    leer.nombre = "ocr_engine"
    return leer


def motor_disponible(preferido: str = "auto"):
    """Devuelve un lector de imágenes `leer(imagen) -> [(texto, confianza)]` o `None`."""
    candidatos = []
    if preferido in ("auto", "rapidocr"):
        candidatos.append(_rapidocr)
    if preferido in ("auto", "ocr_engine", "easyocr"):
        candidatos.append(_ocr_engine_del_proyecto)
    for fabrica in candidatos:
        lector = fabrica()
        if lector is not None:
            return lector
    return None


def realzar(imagen, modo: str = "auto"):
    """Prepara el recorte para el OCR.

    Los números **grabados** en el plástico (caso del número de parte del tablero) son oscuros
    sobre oscuro y el OCR no ve nada sin realce: se iguala el histograma y se marca el relieve.
    """
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY) if imagen.ndim == 3 else imagen
    if modo in ("auto", "grabado"):
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gris)
        relieve = cv2.filter2D(clahe, cv2.CV_8U, np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]]))
        _, umbral = cv2.threshold(relieve, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        candidatos = [cv2.cvtColor(relieve, cv2.COLOR_GRAY2BGR),
                      cv2.cvtColor(umbral, cv2.COLOR_GRAY2BGR),
                      cv2.cvtColor(clahe, cv2.COLOR_GRAY2BGR)]
        if modo == "auto":
            return candidatos
        return candidatos[:2]
    return [imagen]


# serie del tablero: `052 3KVJ008R52V` (o `0523KVJ008R52V`); el último carácter es de control
PATRON_SERIE_TABLERO = re.compile(
    r"(?P<pref>\d{3})\s?(?P<cuerpo>[A-Z0-9]{3}[JI]\d{3}[A-Z0-9]{3})(?P<cola>[A-Z0-9])")


def interpretar_serie_tablero(texto: str) -> dict | None:
    """`*0523KVJ008R562` → `052 3KVJ008R56?`.

    El último carácter es un dígito de control que el OCR confunde a menudo (`Z`→`2`, `S`→`5`):
    se devuelve el valor con `dudoso=True` en vez de inventarlo.
    """
    if not texto:
        return None
    limpio = re.sub(r"[^A-Z0-9]", "", texto.upper())
    encontrado = PATRON_SERIE_TABLERO.search(limpio)
    if not encontrado:
        return None
    cola = encontrado.group("cola")
    dudoso = cola.isdigit()
    return {"valor": f"{encontrado.group('pref')} {encontrado.group('cuerpo')}{cola}",
            "dudoso": dudoso, "origen": texto}


def leer_recorte(imagen, motor, modos=("original", "auto")) -> Lectura:
    if motor is None or imagen is None or getattr(imagen, "size", 0) == 0:
        return Lectura(motor="ninguno")
    mejor = Lectura(motor=getattr(motor, "nombre", "desconocido"))
    for modo in modos:
        for variante in realzar(imagen, modo):
            for texto, conf in motor(variante) or []:
                if not texto.strip():
                    continue
                mejor.lineas.append((texto.strip(), conf))
                if len(texto.strip()) > len(mejor.texto):
                    mejor.texto = texto.strip()
                mejor.confianza = max(mejor.confianza, conf)
    return mejor


def interpretar_fecha(texto: str) -> str | None:
    """`17/05/2025`, `17.05.25`, `17/MAY/2025` → `2025-05-17`."""
    if not texto:
        return None
    limpio = texto.upper().replace(" ", "")
    for dia, mes, anio in PATRON_FECHA.findall(limpio):
        numero_mes = int(mes) if mes.isdigit() else MESES.get(mes[:3], 0)
        if not numero_mes or not (1 <= numero_mes <= 12):
            continue
        numero_dia = int(dia)
        if not (1 <= numero_dia <= 31):
            continue
        year = int(anio)
        year = 2000 + year if year < 100 else year
        return f"{year:04d}-{numero_mes:02d}-{numero_dia:02d}"
    # fechas con mes en texto: «17 MAY 2025», «17/MAY/2025», «17-MAY-25»
    partes = re.sub(r"[/\-.,]+", " ", texto.upper())
    piezas = re.findall(r"(\d{1,2})\s*([A-Z]{3})[A-Z]*\s*(\d{2,4})", partes)
    for dia, mes, anio in piezas:
        numero_mes = MESES.get(mes)
        if numero_mes:
            year = int(anio)
            year = 2000 + year if year < 100 else year
            return f"{year:04d}-{numero_mes:02d}-{int(dia):02d}"
    return None


def interpretar_nivel(texto: str) -> tuple[str, bool]:
    """`03S`/`69K`/`01S`. Devuelve (nivel, reparado)."""
    if not texto:
        return "", False
    limpio = re.sub(r"[^A-Z0-9]", "", texto.upper())
    if not 2 <= len(limpio) <= 4:
        return "", False
    # «S03» / «K69»: la letra va delante (se reordena antes de reparar)
    if len(limpio) == 3 and limpio[0].isalpha() and limpio[1:].isdigit():
        return limpio[1:] + limpio[0], True
    if len(limpio) == 3 and PATRON_NIVEL.match(limpio):
        reparado = any(limpio[i] in REPARACIONES_NIVEL and limpio[i].isalpha() for i in (0, 1))
        nivel = "".join(REPARACIONES_NIVEL.get(c, c) if i < 2 else c for i, c in enumerate(limpio))
        if re.match(r"^\d{2}[A-Z]$", nivel):
            return nivel, reparado
    return "", False


def interpretar_parte(texto: str) -> str | None:
    """`2GJ880204J` / `2GJ.880.204.J` → `2GJ.880.204.J`."""
    if not texto:
        return None
    compacto = texto.upper().replace(" ", "")
    for candidato in PATRON_PARTE_COMPACTO.findall(compacto):
        return f"{candidato[:3]}.{candidato[3:6]}.{candidato[6:9]}.{candidato[9]}"
    encontrado = PATRON_PARTE.search(compacto)
    if encontrado:
        bloques = re.sub(r"[^0-9]", "", encontrado.group("bloques"))
        if len(bloques) >= 6:
            return (f"{encontrado.group('pref')}.{bloques[:3]}.{bloques[3:6]}."
                    f"{encontrado.group('suf')}")
    return None


def interpretar_serie(texto: str) -> str | None:
    """`671ZRZ0539958G` → `671 ZRZ0539958G`."""
    if not texto:
        return None
    compacto = re.sub(r"\s+", "", texto.upper())
    encontrado = PATRON_SERIE.search(compacto)
    if encontrado:
        return f"{encontrado.group('pref')} {encontrado.group('resto')}"
    return None


GIROS = (None, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE)


def leer_con_giros(imagen, motor, modos=("original", "auto"), catalogo=None) -> tuple[Lectura, dict]:
    """Lee probando los cuatro giros: muchas etiquetas vienen giradas 90° (texto vertical).

    Se queda con el giro que produce **más campos válidos** y, en caso de empate, el de más
    confianza. Así el DataMatrix del tablero se lee tanto si la foto viene derecha como girada.
    """
    mejor = (Lectura(motor="ninguno"), {}, -1.0)
    for giro in GIROS:
        base = imagen if giro is None else cv2.rotate(imagen, giro)
        lectura = leer_recorte(base, motor, modos=modos)
        campos = interpretar(lectura, catalogo=catalogo)
        puntaje = (len(campos) * 10) + sum(v.get("confianza", 0) for v in campos.values())
        if puntaje > mejor[2]:
            mejor = (lectura, campos, puntaje)
        if len(campos) >= 2 and all(v.get("confianza", 0) > 0.6 for v in campos.values()):
            break                                   # suficiente y bueno: no seguir gastando
    return mejor[0], mejor[1]


def _distancia(a: str, b: str) -> int:
    previo = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        actual = [i]
        for j, cb in enumerate(b, 1):
            actual.append(min(previo[j] + 1, actual[j - 1] + 1, previo[j - 1] + (ca != cb)))
        previo = actual
    return previo[-1]


def reparar_con_catalogo(texto: str, catalogo, maximo: int = 2) -> dict | None:
    """Arregla una lectura con un carácter mal por comparación con el catálogo del libro.

    Es el último recurso y **nunca es silencioso**: el campo queda marcado como `reparado` con la
    lectura original al lado, para que se vea en la duda.
    """
    if not texto or not catalogo:
        return None
    compacto = _compacto(texto)
    if len(compacto) < 8:
        return None
    mejor, distancia_mejor = None, maximo + 1
    for candidato in catalogo:
        objetivo = _compacto(candidato)
        distancia = _distancia(compacto, objetivo)
        if distancia < distancia_mejor:
            mejor, distancia_mejor = str(candidato), distancia
    if mejor is None or distancia_mejor > maximo:
        return None
    return {"valor": mejor, "distancia": distancia_mejor, "origen": texto}


def interpretar(lectura: Lectura, catalogo=None) -> dict:
    """Convierte lo leído en campos del libro, con la línea de la que sale cada uno."""
    campos: dict[str, dict] = {}
    fechas: list[dict] = []
    for texto, conf in lectura.lineas:
        serie_tablero = interpretar_serie_tablero(texto)
        if serie_tablero:
            campos.setdefault("dashboard_serial_number",
                              {"valor": serie_tablero["valor"], "confianza": conf,
                               "dudoso": serie_tablero["dudoso"], "origen": texto})
        fecha = interpretar_fecha(texto)
        if fecha:
            fechas.append({"valor": fecha, "confianza": conf, "origen": texto,
                           "con_puntos": bool(re.search(r"\d{1,2}\.\d{1,2}\.\d{2,4}", texto))})
        nivel, reparado = interpretar_nivel(texto)
        if nivel:
            campos.setdefault("engineering_level", {"valor": nivel, "confianza": conf,
                                                    "reparado": reparado, "origen": texto})
        parte = interpretar_parte(texto)
        if parte:
            campos.setdefault("part_number", {"valor": parte, "confianza": conf, "origen": texto})
        elif catalogo:
            # el OCR se come un carácter (J→3): se repara contra el catálogo, marcado
            reparado_parte = reparar_con_catalogo(texto, catalogo)
            if reparado_parte and "part_number" not in campos:
                campos["part_number"] = {"valor": reparado_parte["valor"], "confianza": conf,
                                         "reparado": True, "origen": texto}
        serie = interpretar_serie(texto)
        if serie:
            campos.setdefault("serial_number", {"valor": serie, "confianza": conf, "origen": texto})
        if "AUTOLIV" in texto.upper():
            campos.setdefault("supplier", {"valor": "Autoliv", "confianza": conf, "origen": texto})
        if "FORVIA" in texto.upper():
            campos.setdefault("supplier", {"valor": "FORVIA", "confianza": conf, "origen": texto})
    # serie a medias: el OCR suele comerse un carácter del principio o del final; se detecta el
    # núcleo `ZRZ0539991` y se devuelve el fragmento como DUDA (nunca se completa a ciegas)
    if "serial_number" not in campos:
        for texto, conf in lectura.lineas:
            nucleo = re.search(r"[A-Z]{3}\d{7}", _compacto(texto))
            if nucleo:
                campos["serial_number"] = {"valor": _compacto(texto), "confianza": conf,
                                          "dudoso": True, "origen": texto}
                break
    # la serie del módulo a veces viene partida en dos líneas: se busca también en el conjunto
    if "serial_number" not in campos:
        todas = _compacto(" ".join(t for t, _ in lectura.lineas))
        encontrado = PATRON_SERIE.search(todas)
        if encontrado:
            campos["serial_number"] = {
                "valor": f"{encontrado.group('pref')} {encontrado.group('resto')}",
                "confianza": max((c for _, c in lectura.lineas), default=0.0),
                "origen": "líneas unidas"}
    if fechas:
        # convención confirmada por el usuario: la fecha del módulo es la del **DataMatrix**
        # (`10.04.25`, con puntos), no la de la etiqueta impresa (`11/04/2025`)
        con_puntos = [f for f in fechas if f["con_puntos"]]
        elegida = (con_puntos or fechas)[0]
        campos["date"] = {"valor": elegida["valor"], "confianza": elegida["confianza"],
                          "origen": elegida["origen"]}
    return campos


def corroborar(modulo: dict, tablero: dict) -> dict:
    """Regla de la guía: «usar el Module para corroborar la información del tablero»."""
    salida = {"acuerdos": [], "discrepancias": []}
    for campo in ("part_number", "engineering_level", "date", "supplier"):
        en_modulo = (modulo.get(campo) or {}).get("valor")
        en_tablero = (tablero.get(campo) or {}).get("valor")
        if en_modulo and en_tablero:
            (salida["acuerdos"] if en_modulo == en_tablero else salida["discrepancias"]).append(campo)
        elif en_modulo or en_tablero:
            salida.setdefault("solo_uno", []).append(campo)
    return salida


# ---------------------------------------------------------------------------------------------
# Texto GRABADO (número de parte del tablero): el OCR genérico no llega, así que se hace lo que
# recomienda la guía: se localizan las **líneas grabadas** (claras sobre plástico oscuro), se
# prefiere la de abajo (la de arriba es el número de molde: «4148399X») y lo leído se identifica
# contra el **catálogo de números de parte del propio libro**, sin inventar nada.
# ---------------------------------------------------------------------------------------------
PATRON_PARTE_VALIDO = re.compile(r"^\d[A-Z]{2}\.\d{3}\.\d{3}\.[A-Z]$")


def bandas_grabadas(imagen, minimo_alto: int = 12) -> list[tuple[int, int]]:
    """Devuelve las bandas (y0, y1) donde hay texto claro grabado, de arriba abajo."""
    return [banda for banda, _ in bandas_con_columnas(imagen, minimo_alto)]


def bandas_con_columnas(imagen, minimo_alto: int = 12) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """Bandas grabadas con su extensión horizontal: `((y0, y1), (x0, x1))`."""
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY) if imagen.ndim == 3 else imagen
    clahe = cv2.createCLAHE(clipLimit=6.0, tileGridSize=(8, 8)).apply(gris)
    nucleo = cv2.morphologyEx(clahe, cv2.MORPH_TOPHAT,
                              cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9)))
    _, binaria = cv2.threshold(nucleo, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    binaria = cv2.morphologyEx(binaria, cv2.MORPH_CLOSE,
                               cv2.getStructuringElement(cv2.MORPH_RECT, (25, 3)))
    perfil = (binaria > 0).sum(axis=1)
    umbral = max(6, int(perfil.max() * 0.25)) if perfil.size else 0
    crudas, dentro = [], None
    for fila, valor in enumerate(perfil):
        if valor >= umbral and dentro is None:
            dentro = fila
        elif valor < umbral and dentro is not None:
            if fila - dentro >= minimo_alto:
                crudas.append((dentro, fila))
            dentro = None
    if dentro is not None and len(perfil) - dentro >= minimo_alto:
        crudas.append((dentro, len(perfil)))
    salida = []
    for y0, y1 in crudas:
        columnas = np.where((binaria[y0:y1] > 0).any(axis=0))[0]
        if columnas.size < 20:
            continue
        salida.append(((y0, y1), (int(columnas[0]), int(columnas[-1]) + 1)))
    return salida


def _compacto(texto: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(texto).upper())


def _subsecuencia_comun(a: str, b: str) -> int:
    previo = [0] * (len(b) + 1)
    for ca in a:
        actual = [0]
        for j, cb in enumerate(b, 1):
            actual.append(previo[j - 1] + 1 if ca == cb else max(previo[j], actual[j - 1]))
        previo = actual
    return previo[-1]


def identificar_parte(fragmentos, catalogo) -> dict | None:
    """Identifica el número de parte contra el catálogo del libro a partir de lo leído.

    No inventa: sólo devuelve una entrada del catálogo, y sólo si el fragmento leído comparte lo
    suficiente (el núcleo numérico `857.003` de `2GJ.857.003.G`) y no hay empate.
    """
    limpios = [_compacto(f) for f in fragmentos if f]
    limpios = [f for f in limpios if len(f) >= 3]
    if not limpios or not catalogo:
        return None
    puntajes = []
    for candidato in catalogo:
        objetivo = _compacto(candidato)
        if len(objetivo) < 6:
            continue
        mejor = 0
        for fragmento in limpios:
            mejor = max(mejor, _subsecuencia_comun(fragmento, objetivo))
        # el núcleo numérico (los 6 dígitos centrales) pesa el doble: es lo que el OCR sí lee
        nucleo = re.sub(r"[^0-9]", "", objetivo)[1:7]
        comparte_nucleo = sum(1 for c in nucleo if c in "".join(limpios))
        puntajes.append((mejor + 2 * comparte_nucleo, mejor, comparte_nucleo, str(candidato)))
    puntajes.sort(reverse=True)
    if not puntajes:
        return None
    mejor_total, mejor_lcs, nucleo_ok, valor = puntajes[0]
    segundo = puntajes[1][0] if len(puntajes) > 1 else 0
    if nucleo_ok < 3 or mejor_lcs < 3:
        return None
    if len(puntajes) > 1 and mejor_total - segundo < 2:
        return None
    return {"valor": valor, "puntaje": mejor_total, "lcs": mejor_lcs, "nucleo": nucleo_ok,
            "fragmentos": limpios, "catalogo": len(puntajes)}


def leer_grabado(imagen, motor, catalogo=None) -> dict | None:
    """Lee el número grabado probando las bandas de arriba abajo; gana la que se identifique.

    La guía y el usuario coinciden: **la buena es la de abajo**; la de arriba (`4148399X`) es el
    número de molde y no entra en el libro. Por eso, si el catálogo no resuelve, se devuelve la
    banda de abajo con `dudoso=True` en vez de un invento.
    """
    bandas = bandas_con_columnas(imagen)[:4]            # como mucho cuatro líneas: memoria
    if not bandas:
        return None
    fragmentos: list[str] = []
    lecturas = []
    for indice, ((y0, y1), (x0, x1)) in enumerate(bandas):
        ancho = max(1, x1 - x0)
        trozo = imagen[max(0, y0 - 4):y1 + 4, max(0, x0 - 6):x1 + 6]
        if trozo.size == 0 or ancho < 25:
            continue
        escala = 3 if ancho < 320 else 2                    # el ancho del recorte manda
        for variante in realzar(trozo, "grabado"):
            grande = cv2.resize(variante, None, fx=escala, fy=escala,
                                interpolation=cv2.INTER_CUBIC)
            nube = cv2.addWeighted(grande, 1.8, cv2.GaussianBlur(grande, (0, 0), 1.2), -0.8, 0)
            for texto, conf in (motor(nube) or []):
                if texto.strip():
                    lecturas.append({"banda": indice, "texto": texto.strip(), "confianza": conf})
                    fragmentos.append(texto.strip())
    identificado = identificar_parte(fragmentos, catalogo) if catalogo else None
    if identificado:
        for lectura in lecturas:
            if _compacto(lectura["texto"]) and _subsecuencia_comun(
                    _compacto(lectura["texto"]), _compacto(identificado["valor"])) >= 3:
                identificado.setdefault("confianza", lectura["confianza"])
                identificado.setdefault("origen", lectura["texto"])
                break
        identificado.setdefault("confianza", 0.0)
        identificado.setdefault("origen", " ".join(identificado["fragmentos"]))
        identificado["bandas"] = len(bandas)
        identificado["dudoso"] = False
        return identificado
    if lecturas:
        ultima = lecturas[-1]
        return {"valor": ultima["texto"], "confianza": ultima["confianza"], "dudoso": True,
                "origen": ultima["texto"], "bandas": len(bandas),
                "fragmentos": fragmentos}
    return None
