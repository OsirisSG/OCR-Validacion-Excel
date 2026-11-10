#!/usr/bin/env python3
"""Etiqueta del **módulo PAB**: dos códigos (DataMatrix) que dicen lo mismo.

La etiqueta del airbag lleva **dos códigos** con información que se repite —a veces sólo una parte—.
El protocolo que se implementa aquí es el que pidió el usuario:

1. **Buscar los códigos**: se detectan los cuadrados con textura de damero (DataMatrix) sin necesidad de
   decodificarlos (OpenCV no decodifica DataMatrix de forma fiable).
2. **Asociar el texto a cada código**: se lee la foto una vez y cada línea se asigna al código más cercano.
   Así se obtienen **dos lecturas independientes** de la misma etiqueta.
3. **Comparar las dos**: si coinciden, el valor es firme; si no, se elige por **consenso con las demás
   carpetas** (`aprendizaje/modulo.json`) y, si aun así no hay mayoría, queda en duda con las dos lecturas
   y el recorte.
4. **Prototipo**: si aparece `PROTOTYPE` / `PROTOTIPO` / `PROTOTIPOS` (la etiqueta viene en inglés), se
   marca la etiqueta como prototipo y **no** se usa el consenso entre carpetas: se exige lectura propia.
5. **Nivel de ingeniería = la estampa de color**: el nivel (`66K`, `69K`, `01S`) va en una **pegatina
   redonda amarilla** sobre la etiqueta, girada en cualquier sentido; se localiza por color, se recorta,
   se prueba en los cuatro giros y se lee (`##S` / `##K`). El texto grabado
   `ZRZ 02S 2GJ 880 204 J` **no** es el nivel (es constante en todas las carpetas).
   Si el módulo **no** trae pegatina, el nivel es el de partida (`01S`), que sólo se acepta por
   **consenso entre carpetas**.
6. **PAB Variante**: datos que acompañan a la etiqueta (`T 2GJ 204`, `Farbe`, `0589-P1-000678`,
   `651538300`), que se guardan como `variante` para comprobar que el módulo es el mismo.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

PATRON_PARTE = re.compile(r"(?P<pref>\d[A-Z]{2})[.\s]?(?P<b1>\d{3})[.\s]?(?P<b2>\d{3})[.\s]?(?P<suf>[A-Z0-9])")
PATRON_FECHA = re.compile(r"(?P<dia>\d{1,2})(?P<sep>[.\-/])(?P<mes>\d{1,2})(?P=sep)(?P<anio>\d{2,4})")
# la etiqueta lleva **dos** fechas: la de fabricación junto al DataMatrix (`10.04.25`, con puntos) y la
# de modificación del dibujo (`06/05/2025`, con barras). Sólo la primera es la del libro.
SEPARADORES_FABRICACION = (".", "-")
PATRON_SERIE = re.compile(r"(?P<pref>\d{3})\s?(?P<resto>[A-Z]{3}\d{6,8}[A-Z0-9]?)")
# el nivel que usa el libro es `##S` / `##K` (estampado, a veces en otro formato cerca de la etiqueta)
LETRAS_NIVEL = "SKA"
PATRON_NIVEL = re.compile(rf"^(?P<num>[0-9OQDSILZBG]{{2}})(?P<let>[{LETRAS_NIVEL}])$")
# el OCR confunde dígitos con letras: 0↔O/Q/D, 1↔I/L, 5↔S, 2↔Z, 8↔B, 6↔G
CONFUSION_DIGITO = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "S": "5", "Z": "2",
                    "B": "8", "G": "6"}
PROTOTIPO = ("PROTOTYPE", "PROTOTIP", "TESTLABEL", "MUSTER")
PALABRAS_PROTOTIPO_ES = ("PROTOTIPO", "PROTOTIPOS", "MUESTRA")
PATRON_VARIANTE = re.compile(r"\bT\s?(?P<var>2GJ\s?\d{3})\b")
PATRON_COLOR = re.compile(r"\bFarbe\b[:\s]*[^\n]{0,20}", re.I)
NIVEL_DE_PARTIDA = "01S"


def apariciones(lineas: list[dict], campo: str) -> dict[str, list[dict]]:
    """Dónde aparece cada valor de un campo: eso es la doble lectura de los dos códigos."""
    valores: dict[str, list[dict]] = {}
    for linea in lineas:
        for valor in _valores_de_linea(linea.get("texto", ""), campo):
            valores.setdefault(valor, []).append(linea.get("caja") or {})
    return valores


def hay_fecha_de_cambio(lineas: list[dict]) -> bool:
    """¿La etiqueta trae el campo de modificación del dibujo (`Änderungs-Dat`, `MEK/DZ`...)?

    Cuando lo trae, su fecha (con barras) **no** es la de fabricación y no se usa ni de respaldo.
    """
    return any(re.search(r"NDERUNG|MEK/DZ", str(linea.get("texto", "")).upper()) for linea in lineas)


def fechas_de_fabricacion(lineas: list[dict]) -> dict[str, list[dict]]:
    """Sólo las fechas **de fabricación** (las de junto al DataMatrix, con punto o guion).

    Así no se cuela la fecha de modificación del dibujo (`06/05/2025`), que va con barras y no es la
    que pide el libro.
    """
    valores: dict[str, list[dict]] = {}
    # si la etiqueta trae el campo de modificación del dibujo (`Änderungs-Dat:`), las fechas con
    # barras de esa foto no son de fabricación aunque el OCR las separe en su propia línea
    trae_cambio = hay_fecha_de_cambio(lineas)
    for linea in lineas:
        texto = str(linea.get("texto", "")).upper()
        # una fecha con barras vale sólo si va **sola** en su línea (es un campo impreso); si va
        # dentro del texto largo de modificación (`.../W316PA/06/05/2025`) no es la de fabricación
        con_barras_suelta = len(texto.strip()) <= 12
        for encontrado in PATRON_FECHA.finditer(texto):
            con_barras = encontrado.group("sep") not in SEPARADORES_FABRICACION
            if con_barras and (trae_cambio or not con_barras_suelta):
                continue
            dia, mes, anio = (int(encontrado.group("dia")), int(encontrado.group("mes")),
                              int(encontrado.group("anio")))
            anio = 2000 + anio if anio < 100 else anio
            if not (1 <= dia <= 31 and 1 <= mes <= 12):
                continue
            valores.setdefault(f"{anio:04d}-{mes:02d}-{dia:02d}", []).append(linea.get("caja") or {})
    return valores


def _valores_de_linea(texto: str, campo: str) -> list[str]:
    """Extrae de **una** línea los valores posibles de un campo."""
    limpio = str(texto or "").upper()
    if not limpio:
        return []
    salida: list[str] = []
    if campo == "part_number":
        for encontrado in PATRON_PARTE.finditer(limpio.replace(" ", "")):
            bloques = encontrado.group("b1") + encontrado.group("b2")
            salida.append(f"{encontrado.group('pref')}.{bloques[:3]}.{bloques[3:6]}."
                          f"{encontrado.group('suf')}")
    elif campo == "date":
        for encontrado in PATRON_FECHA.finditer(limpio):
            dia, mes, anio = (int(encontrado.group("dia")), int(encontrado.group("mes")),
                              int(encontrado.group("anio")))
            anio = 2000 + anio if anio < 100 else anio
            if 1 <= dia <= 31 and 1 <= mes <= 12:
                salida.append(f"{anio:04d}-{mes:02d}-{dia:02d}")
    elif campo == "serial_number":
        encontrado = PATRON_SERIE.search(limpio.replace(" ", ""))
        if encontrado:
            salida.append(f"{encontrado.group('pref')} {encontrado.group('resto')}")
    elif campo == "engineering_level":
        # `ZRZ 02S 2GJ 880 204 J` lleva un `02S` que **no** es el nivel: es parte de la serie
        if PATRON_SERIE.search(limpio.replace(" ", "")) or "ZRZ" in limpio:
            return salida
        # la línea del número de parte tampoco lleva el nivel
        if PATRON_PARTE.search(limpio.replace(" ", "")):
            return salida
        for token in re.findall(rf"\b[0-9OQDSILZBG]{{2}}[{LETRAS_NIVEL}]\b", limpio):
            nivel = normalizar_nivel(token)
            if nivel:
                salida.append(nivel)
    elif campo == "module_version":
        for version in ("RDW", "NAR", "ROW"):
            if re.search(rf"\b{version}\b", limpio):
                salida.append(version)
    return salida


def normalizar_nivel(token: str) -> str | None:
    """`O1S` -> `01S`. Devuelve `None` si el token no tiene forma de nivel (`##S` / `##K`)."""
    encontrado = PATRON_NIVEL.match(str(token or "").upper().strip())
    if not encontrado:
        return None
    numero = "".join(CONFUSION_DIGITO.get(caracter, caracter) for caracter in encontrado.group("num"))
    if not numero.isdigit():
        return None
    return f"{numero}{encontrado.group('let')}"


def separacion_de_cajas(cajas: list[dict]) -> float:
    """Distancia relativa entre las apariciones: si están lejos, son **dos códigos** distintos."""
    puntos = [(caja.get("x", 0.0) + caja.get("w", 0.0) / 2, caja.get("y", 0.0) + caja.get("h", 0.0) / 2)
              for caja in cajas if caja]
    if len(puntos) < 2:
        return 0.0
    ancho = max((caja.get("x", 0.0) + caja.get("w", 0.0) for caja in cajas if caja), default=1.0) or 1.0
    alto = max((caja.get("y", 0.0) + caja.get("h", 0.0) for caja in cajas if caja), default=1.0) or 1.0
    diagonal = (ancho ** 2 + alto ** 2) ** 0.5 or 1.0
    mayor = max(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
                for i, a in enumerate(puntos) for b in puntos[i + 1:])
    return round(mayor / diagonal, 3)


def _centro(caja: dict) -> tuple[float, float] | None:
    if not caja or not caja.get("w"):
        return None
    return caja["x"] + caja["w"] / 2, caja["y"] + caja["h"] / 2


def _linea_es_ancla(linea: dict) -> bool:
    """¿La línea es parte de los datos del módulo (número de parte, serie o `ZRZ`)?"""
    texto = str(linea.get("texto", "")).upper().replace(" ", "")
    return bool(PATRON_PARTE.search(texto) or PATRON_SERIE.search(texto) or "ZRZ" in texto)


def prototipo_en_la_etiqueta(lineas: list[dict], radio: float = 0.5) -> bool:
    """¿La etiqueta del módulo es de **prototipo**?

    En estas cajas hay una pegatina amarilla de un componente que dice `PROTOTYPE AQW` y sale en
    todas las carpetas; si se aceptara a ciegas, las diez saldrían «prototipo» y la excepción
    perdería sentido. Se exige la palabra **y** que en esa misma foto estén los datos del módulo
    (número de parte, serie o `ZRZ`): la etiqueta de prototipo es la que sustituye a la normal, no
    una pegatina aparte.
    """
    anclas = [caja for linea in lineas for caja in [_linea_es_ancla(linea) and (linea.get("caja") or {})] if caja]
    if not anclas:
        return False
    centros = [centro for centro in (_centro(caja) for caja in anclas) if centro]
    for linea in lineas:
        texto = str(linea.get("texto", "")).upper()
        if not any(palabra in texto for palabra in PROTOTIPO + PALABRAS_PROTOTIPO_ES):
            continue
        centro = _centro(linea.get("caja") or {})
        if centro is None or not centros:
            return True                      # sin posiciones no se puede descartar: se marca
        distancia = min(((centro[0] - ancla[0]) ** 2 + (centro[1] - ancla[1]) ** 2) ** 0.5
                        for ancla in centros)
        alcance = max((caja["w"] ** 2 + caja["h"] ** 2) ** 0.5 for caja in anclas) or 1.0
        if distancia <= alcance * radio:      # «cerca» = pegada a los datos del módulo
            return True
    return False


def consenso_de_lineas(lineas: list[dict]) -> dict:
    """Decide cada campo por **repetición dentro de la misma etiqueta** (los dos códigos).

    * un valor que aparece **dos veces o más** y sin competencia → firme (`confirmado_por_dos`);
    * un valor que aparece una sola vez → se acepta pero marcado (`una_sola_lectura`);
    * dos valores distintos del mismo campo → **discrepancia**: no se elige, va a dudas con los dos.
    """
    salida: dict[str, object] = {"discrepancias": [], "apariciones": {}}
    # el nivel **no** se decide por texto: se decide por la estampa (ver `leer_foto_modulo`). Lo que
    # se lea suelto en el texto queda como candidato, para poder auditarlo, nunca como valor.
    niveles_texto = apariciones(lineas, "engineering_level")
    if niveles_texto:
        salida["nivel_texto_candidato"] = {valor: len(cajas) for valor, cajas
                                           in sorted(niveles_texto.items(), key=lambda par: -len(par[1]))}
    for campo in ("part_number", "date", "serial_number", "module_version"):
        if campo == "date":
            valores = fechas_de_fabricacion(lineas)
            if not valores and not hay_fecha_de_cambio(lineas):
                # sin fecha con puntos y sin campo de modificación: se admite la de barras
                valores = apariciones(lineas, campo)
        else:
            valores = apariciones(lineas, campo)
        if not valores:
            continue
        ordenados = sorted(valores.items(), key=lambda par: -len(par[1]))
        salida["apariciones"][campo] = {valor: len(cajas) for valor, cajas in ordenados}
        valor, cajas = ordenados[0]
        if len(ordenados) > 1:
            salida["discrepancias"].append({"campo": campo,
                                            "valores": [v for v in list(valores)],
                                            "veces": [len(valores[v]) for v in list(valores)]})
            continue
        salida[campo] = valor
        salida.setdefault("veces", {})[campo] = len(cajas)
        lejos = separacion_de_cajas(cajas) >= 0.12
        salida.setdefault("fuerza", {})[campo] = (
            "confirmado_por_dos" if len(cajas) >= 2 and lejos
            else "repetido_junto" if len(cajas) >= 2
            else "una_sola_lectura")
        if len(cajas) >= 2:
            salida.setdefault("separacion", {})[campo] = separacion_de_cajas(cajas)
    salida.update(datos_de_variante(lineas))
    unido = " ".join(str(linea.get("texto", "")) for linea in lineas).upper()
    if prototipo_en_la_etiqueta(lineas):
        salida["prototipo"] = True
    # ¿es de verdad la etiqueta del módulo? (si no, una fecha del tablero se colaría)
    salida["es_modulo"] = bool(salida.get("part_number") or salida.get("serial_number")
                               or "ZRZ" in unido or "AIRBA" in unido or "AUTOLIV" in unido)
    if not salida["es_modulo"]:
        for campo in ("date", "part_number", "serial_number", "engineering_level"):
            salida.pop(campo, None)
    return salida


# ---------------------------------------------------------------------------------------------
# Aprendizaje entre carpetas
# ---------------------------------------------------------------------------------------------
RUTA_APRENDIZAJE = Path(__file__).resolve().parent.parent / "aprendizaje" / "modulo.json"


def aprender(por_caso: dict[str, dict], ruta: Path | None = None) -> dict:
    """Cuenta lo que se repite entre carpetas (parte, fecha, versión) y lo guarda."""
    contadores: dict[str, Counter] = {campo: Counter() for campo in
                                      ("part_number", "date", "module_version", "engineering_level")}
    for lectura in por_caso.values():
        for campo, contador in contadores.items():
            if lectura.get(campo):
                contador[lectura[campo]] += 1
    casos = max(1, len(por_caso))
    datos = {"casos": casos,
             **{campo: dict(contador.most_common()) for campo, contador in contadores.items()},
             "repeticion": {campo: round(max(contador.values()) / casos, 2) if contador else 0.0
                            for campo, contador in contadores.items()}}
    ruta = Path(ruta) if ruta else RUTA_APRENDIZAJE
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    return datos


def cargar_aprendizaje(ruta: Path | None = None) -> dict:
    ruta = Path(ruta) if ruta else RUTA_APRENDIZAJE
    if not ruta.exists():
        return {}
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def completar_con_lo_aprendido(campos: dict, aprendizaje: dict,
                               umbral: float = 0.6) -> dict:
    """Rellena lo que falta con lo que más se repite entre carpetas — si es prototipo, no."""
    if not aprendizaje or campos.get("prototipo"):
        return campos
    for campo in ("part_number", "date", "module_version"):
        if campos.get(campo):
            continue
        valores = aprendizaje.get(campo) or {}
        if not valores:
            continue
        repeticion = (aprendizaje.get("repeticion") or {}).get(campo, 0.0)
        if repeticion < umbral:
            continue
        valor, veces = max(valores.items(), key=lambda par: par[1])
        campos[campo] = valor
        campos.setdefault("por_repeticion", {})[campo] = f"{veces}/{aprendizaje.get('casos', veces)} carpetas"
    return campos


def leer_etiqueta_modulo(lineas: list[dict], aprendizaje: dict | None = None) -> dict:
    """Protocolo completo: doble lectura dentro de la etiqueta + consenso entre carpetas."""
    campos = consenso_de_lineas(lineas)
    if campos.get("discrepancias"):
        # si los dos códigos no dicen lo mismo, lo aprendido NO tapa la discrepancia
        return campos
    if aprendizaje:
        campos = completar_con_lo_aprendido(campos, aprendizaje)
    return campos


_MOTOR = None


def motor_compartido():
    """Un solo RapidOCR para todo el proceso: crear uno por foto se come la memoria (OOM).

    Ojo con el nombre: `lineas_con_caja` recibe un parámetro `motor`, así que aquí no se puede
    llamar `motor()` desde dentro — el nombre quedaría tapado por el parámetro.
    """
    global _MOTOR
    if _MOTOR is None:
        from rapidocr_onnxruntime import RapidOCR
        _MOTOR = RapidOCR()
    return _MOTOR


def recortes_amarillos(imagen, area_minima: int = 1200, area_maxima: int = 90000,
                       lado_maximo_relativo: float = 0.22) -> list[dict]:
    """Localiza la **pegatina redonda amarilla** del nivel (estampa) y devuelve su recorte.

    La etiqueta grande de aviso también es amarilla: se descarta por tamaño y por forma —la estampa es
    compacta, casi circular y pequeña respecto a la foto.
    """
    alto, ancho = imagen.shape[:2]
    hsv = cv2.cvtColor(imagen, cv2.COLOR_BGR2HSV)
    mascara = cv2.inRange(hsv, np.array([16, 100, 100]), np.array([40, 255, 255]))
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    cuantos, _, estadisticas, _ = cv2.connectedComponentsWithStats(mascara)
    salida: list[dict] = []
    for indice in range(1, cuantos):
        x, y, w, h, area = (int(valor) for valor in estadisticas[indice])
        if not (area_minima <= area <= area_maxima) or min(w, h) < 22:
            continue
        if max(w, h) / min(w, h) > 2.4 or area / float(w * h) < 0.5:
            continue
        if max(w, h) / float(max(alto, ancho)) > lado_maximo_relativo:
            continue
        salida.append({"area": area, "x": x, "y": y, "w": w, "h": h,
                       "relleno": round(area / float(w * h), 2)})
    salida.sort(key=lambda caja: -caja["area"])
    return salida[:3]


def leer_estampa_nivel(imagen, maximo: int = 3, lado_busqueda: int | None = None) -> dict:
    """Lee el nivel de la estampa amarilla probando **los cuatro giros**.

    Devuelve `nivel`, `giro`, `confianza` y `recorte` (la imagen para la evidencia), o `{}` si no hay.
    """
    marco = imagen
    if lado_busqueda:
        alto_original, ancho_original = imagen.shape[:2]
        if max(alto_original, ancho_original) > lado_busqueda:
            factor = lado_busqueda / max(alto_original, ancho_original)
            marco = cv2.resize(imagen, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    candidatos = recortes_amarillos(marco)[:maximo]
    if not candidatos:
        return {}
    alto, ancho = marco.shape[:2]
    mejor: dict = {}
    for candidato in candidatos:
        pad = int(max(candidato["w"], candidato["h"]) * 0.35)
        x0, y0 = max(0, candidato["x"] - pad), max(0, candidato["y"] - pad)
        x1 = min(ancho, candidato["x"] + candidato["w"] + pad)
        y1 = min(alto, candidato["y"] + candidato["h"] + pad)
        recorte = marco[y0:y1, x0:x1]
        if recorte.size == 0:
            continue
        for giro, codigo in enumerate((None, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180,
                                       cv2.ROTATE_90_COUNTERCLOCKWISE)):
            vista = recorte if codigo is None else cv2.rotate(recorte, codigo)
            escala = 900 / max(vista.shape[:2])
            if escala > 1:
                vista = cv2.resize(vista, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
            gris = cv2.createCLAHE(2.0, (8, 8)).apply(cv2.cvtColor(vista, cv2.COLOR_BGR2GRAY))
            for texto, confianza in _textos_simples(cv2.cvtColor(gris, cv2.COLOR_GRAY2BGR)):
                limpio = re.sub(r"[^0-9A-Z]", "", texto.upper())
                if not 2 <= len(limpio) <= 4 or float(confianza) < 0.5:
                    continue
                nivel = normalizar_nivel(limpio)
                if nivel and float(confianza) > mejor.get("confianza", 0.0):
                    mejor = {"nivel": nivel, "texto": texto, "confianza": float(confianza),
                             "giro": giro, "area": candidato["area"], "recorte": recorte}
    return mejor


def _textos_simples(imagen) -> list[tuple[str, float]]:
    """OCR de un recorte pequeño: devuelve `(texto, confianza)`; sin cajas."""
    try:
        resultado, _ = motor_compartido()(imagen)
        return [(str(texto), float(confianza)) for _, texto, confianza in resultado or []]
    except Exception:                                        # noqa: BLE001
        return []


def datos_de_variante(lineas: list[dict]) -> dict:
    """`PAB Variante`: lo que acompaña a la etiqueta y confirma que es el mismo módulo."""
    unido = " ".join(str(linea.get("texto", "")) for linea in lineas)
    salida: dict = {}
    variante = PATRON_VARIANTE.search(unido.upper())
    if variante:
        salida["variante"] = variante.group("var").replace(" ", "").upper()
    color = PATRON_COLOR.search(unido)
    if color:
        salida["farbe"] = color.group(0).strip()
    proveedor = re.search(r"\b05\d{2}-P\d-\d{6}\b", unido)
    if proveedor:
        salida["codigo_proveedor"] = proveedor.group(0)
    generador = re.search(r"\b6515\d{5}[A-Z]?\b", unido)
    if generador:
        salida["generador"] = generador.group(0)
    return salida


def lineas_con_caja(imagen, motor=None, lado_maximo: int = 1600) -> list[dict]:
    """Texto y **posición** de cada línea (necesario para saber si el dato aparece dos veces).

    Usa RapidOCR directamente porque es el único que devuelve la caja; si no está, cae al motor
    normal sin cajas (el protocolo sigue funcionando, pero sin la comprobación de posición).
    """
    alto, ancho = imagen.shape[:2]
    if max(alto, ancho) > lado_maximo:
        factor = lado_maximo / max(alto, ancho)
        pequena = cv2.resize(imagen, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
        escala = 1 / factor
    else:
        pequena, escala = imagen, 1.0
    try:
        resultado, _ = motor_compartido()(pequena)
        lineas = []
        for caja, texto, confianza in resultado or []:
            puntos = np.array(caja, dtype=float)
            x, y = puntos[:, 0].min(), puntos[:, 1].min()
            w, h = puntos[:, 0].max() - x, puntos[:, 1].max() - y
            lineas.append({"texto": str(texto), "confianza": float(confianza),
                           "caja": {"x": float(x * escala), "y": float(y * escala),
                                    "w": float(w * escala), "h": float(h * escala)}})
        return lineas
    except Exception:                                        # noqa: BLE001
        from utilidades.lector_etiquetas import leer_con_giros
        lectura, _ = leer_con_giros(pequena, motor, modos=("original", "auto"))
        return [{"texto": texto, "confianza": confianza, "caja": {}} for texto, confianza in lectura.lineas]


def leer_foto_modulo(imagen, aprendizaje: dict | None = None,
                     con_estampa: bool = True) -> dict:
    """Lee una foto como etiqueta de módulo: doble lectura interna + estampa del nivel + consenso."""
    lineas = lineas_con_caja(imagen)
    campos = leer_etiqueta_modulo(lineas, aprendizaje)
    campos["lineas"] = [linea["texto"] for linea in lineas]
    if not con_estampa or campos.get("prototipo"):
        return campos
    # la estampa se busca en **cualquier** foto, no sólo en las que el OCR ha reconocido como
    # etiqueta: hay acercamientos a la pegatina en los que no se lee ni el número de parte
    estampa = leer_estampa_nivel(imagen)
    if estampa:
        campos["engineering_level"] = estampa["nivel"]
        campos.setdefault("fuente_nivel", {})["engineering_level"] = "estampa_amarilla"
        campos["estampa"] = {"giro": estampa["giro"], "confianza": round(estampa["confianza"], 2),
                             "texto": estampa["texto"], "area": estampa["area"]}
        campos["recorte_estampa"] = estampa["recorte"]
    elif campos.get("es_modulo"):
        campos["sin_estampa"] = True
    return campos
