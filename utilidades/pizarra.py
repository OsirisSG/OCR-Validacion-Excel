#!/usr/bin/env python3
"""Lectura de la **pizarra escrita a mano** del tablero.

En el embellecedor, junto a la guantera, el técnico escribe a rotulador los datos del ensayo:

```
VW316/5      IT 035
23.2550      185,4   NOM   025
+85 °C       BMG
```

Lo que interesa al libro:

* **Motivo de prueba** = *tipo de prueba* (`IT`) + *proyecto/pizarra* (`BMG`), que van **separados** en la
  pizarra y aquí se unen → `IT BMG`. Es exactamente lo que el libro llama «Proyecto o pizarra explícitos»
  (hoja *Diccionario de datos*): el motivo **no** se deduce de códigos de pieza.
* **Número de prueba** escrito a mano (`23.2550`) → corrobora el número de la carpeta y, con él, la semana.
* **Temperatura** (`+85 °C` → `HT`), **tipo de generador** (`NOM`) y **proyecto** (`VW316/5`).

El OCR de rotulador es frágil (`BMG` sale como `BM6`, `BME`, `BMC`, `8MG`), así que cada token se **repara**
contra el vocabulario del propio libro con un mapa de confusiones (6↔G, 8↔B, 0↔O, 1↔I, 5↔S, C↔G) y una
distancia de edición ≤ 1. Nunca se escribe un token que no aparezca en la lectura: si falta uno de los dos,
el motivo queda **en duda** con el recorte al lado.
"""
from __future__ import annotations

import re
from pathlib import Path

import cv2

from utilidades.lector_etiquetas import leer_con_giros

# Vocabulario de las pizarras vistas. `IT` = tipo de prueba; `BMG` = proyecto/pizarra.
TIPOS_PRUEBA = ("IT", "HT", "RT", "NT", "KT")
PROYECTOS = ("BMG",)
CONFUSIONES = {"6": "G", "8": "B", "0": "O", "1": "I", "5": "S", "C": "G", "Q": "O", "2": "Z"}
# Pares que el rotulador confunde de verdad (sólo estos cuentan como «una edición admisible»).
PARECIDOS = {("G", "E"), ("G", "C"), ("G", "6"), ("B", "8"), ("O", "0"), ("O", "Q"), ("I", "1"),
             ("S", "5"), ("Z", "2"), ("M", "N"), ("I", "L"), ("T", "I"), ("T", "7")}

PATRON_NUMERO_PIZARRA = re.compile(r"\b(?P<semana>\d{2})[.\s,]?(?P<resto>\d{4})\b")
PATRON_TEMPERATURA = re.compile(r"\+?\s?(?P<grados>\d{2,3})\s*[°º]?\s?C?\b")
PATRON_PROYECTO_VW = re.compile(r"\b(?P<vw>V\s?W\s?\d{3}\s?/?\s?\d{0,2})\b")
ETIQUETAS_UI = ("AJUSTAR", "PANTALLA", "SELECCIONAR", "TEXTO", "MOVER", "IMAGEN", "UNIR", "BLOQUES",
                "EDITAR", "BLOQUE", "AMPLIA", "RUEDA", "REGION", "DESPLAZARTE")


def _distancia(a: str, b: str) -> int:
    """Levenshtein (ya está en el motor de etiquetas, aquí para no depender de él)."""
    if a == b:
        return 0
    anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        actual = [i]
        for j, cb in enumerate(b, 1):
            actual.append(min(anterior[j] + 1, actual[j - 1] + 1,
                              anterior[j - 1] + (ca != cb)))
        anterior = actual
    return anterior[-1]


def _normalizar(token: str) -> str:
    limpio = re.sub(r"[^A-Z0-9]", "", token.upper())
    return "".join(CONFUSIONES.get(c, c) for c in limpio)


def _parecido(a: str, b: str) -> bool:
    return (a, b) in PARECIDOS or (b, a) in PARECIDOS


def _una_edicion_admisible(a: str, b: str) -> bool:
    """True si `a` y `b` difieren en **un** carácter y es de los que el rotulador confunde."""
    if len(a) != len(b):
        return False
    distintos = [(x, y) for x, y in zip(a, b) if x != y]
    if len(distintos) != 1:
        return False
    return _parecido(*distintos[0])


def emparejar(token: str, vocabulario, largo: int | None = None) -> tuple[str, int] | None:
    """`BM6` → (`BMG`, 1). Rechaza parecidos genéricos (`RO` no es `RT`)."""
    if len(token) < 2:
        return None
    normalizado = _normalizar(token)
    if largo is not None and len(normalizado) != largo:
        return None
    mejor = None
    for candidato in vocabulario:
        if normalizado == candidato:
            return (candidato, 0)
        if _una_edicion_admisible(normalizado, candidato):
            mejor = (candidato, 1)
    return mejor


def _lineas_utiles(imagen, motor, escalas=(1.0, 1.5, 2.0)) -> list[tuple[str, float]]:
    """OCR a varias escalas; se descartan los textos de la interfaz del visor."""
    vistas: dict[str, float] = {}
    for escala in escalas:
        if escala == 1.0:
            muestra = imagen
        else:
            muestra = cv2.resize(imagen, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
        if max(muestra.shape[:2]) > 2200:
            factor = 2200 / max(muestra.shape[:2])
            muestra = cv2.resize(muestra, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
        lectura, _ = leer_con_giros(muestra, motor, modos=("original",))
        for texto, confianza in lectura.lineas:
            limpio = " ".join(str(texto).split())
            if len(limpio) < 2:
                continue
            if any(palabra in limpio.upper() for palabra in ETIQUETAS_UI):
                continue
            vistas[limpio] = max(vistas.get(limpio, 0.0), float(confianza))
    return sorted(vistas.items(), key=lambda par: -par[1])


def leer_pizarra(imagen, motor, aprendizaje: dict | None = None) -> dict:
    """Devuelve lo que la pizarra dice, con la evidencia de cada token.

    Claves: `tipo_prueba`, `proyecto`, `motivo`, `numero`, `semana`, `temperatura`, `inflator_type`,
    `proyecto_vw`, `lineas`, `faltan` (lo que impide cerrar el motivo).
    """
    lineas = _lineas_utiles(imagen, motor)
    # si la pizarra no aparece en la imagen completa, se acerca la herramienta a su zona y se
    # vuelve a leer en grande (el rotulador es fino y el tablero oscuro)
    if not any(re.search(r"[A-Za-z]{2,}", texto) for texto, _ in lineas):
        cercanas = aproximar_a_la_zona(imagen, motor)
        if cercanas.get("lineas"):
            lineas = lineas + cercanas["lineas"]
            campos_extra = {"acercamiento": True}
    campos: dict[str, object] = {"lineas": lineas, "faltan": []}
    for texto, _confianza in lineas:
        if "proyecto" not in campos:
            for token in re.findall(r"[A-Za-z0-9]{2,5}", texto):
                pareja = emparejar(token, PROYECTOS, largo=3)
                if pareja and pareja[0] not in ("VW",):
                    campos["proyecto"] = pareja[0]
                    campos["proyecto_leido"] = token
                    break
        if "tipo_prueba" not in campos:
            for token in re.findall(r"[A-Za-z0-9]{2,4}", texto):
                pareja = emparejar(token, TIPOS_PRUEBA, largo=2)
                if pareja:
                    campos["tipo_prueba"] = pareja[0]
                    campos["tipo_leido"] = token
                    break
        if "numero" not in campos:
            encontrado = PATRON_NUMERO_PIZARRA.search(texto.replace(".", "."))
            if encontrado:
                digitos = encontrado.group("semana") + encontrado.group("resto")
                if 1 <= int(digitos[:2]) <= 53:
                    campos["numero"] = digitos
                    campos["semana"] = digitos[:2]
        if "temperatura" not in campos:
            grados = PATRON_TEMPERATURA.search(texto)
            # `100%` es el zoom del visor, no la temperatura: la pizarra escribe `+85 °C`
            if grados and "%" not in texto and any(marca in texto for marca in ("+", "°", "º", "C")):
                if not 40 <= int(grados.group("grados")) <= 200:
                    continue
                campos["temperatura"] = f"+{grados.group('grados')}"
        if "inflator_type" not in campos and re.search(r"\bNOM\b", texto.upper()):
            campos["inflator_type"] = "NOM"
        if "proyecto_vw" not in campos:
            vw = PATRON_PROYECTO_VW.search(texto.upper())
            if vw:
                campos["proyecto_vw"] = re.sub(r"\s+", "", vw.group("vw"))
    campos.update(locals().get("campos_extra") or {})
    for obligatorio in ("tipo_prueba", "proyecto"):
        if not campos.get(obligatorio):
            campos["faltan"].append(obligatorio)
    if campos.get("tipo_prueba") and campos.get("proyecto"):
        campos["motivo"] = f"{campos['tipo_prueba']} {campos['proyecto']}"
    else:
        campos["motivo"] = ""
    if aprendizaje:
        campos = completar_con_lo_aprendido(campos, aprendizaje)
    return campos


def motivo_del_libro(motivos: list[str]) -> dict[str, list[str]]:
    """Vocabulario de motivos a partir de los que ya usa el libro (`IT BMG` → IT + BMG)."""
    tipos, proyectos = set(), set()
    for motivo in motivos:
        partes = [p for p in str(motivo or "").upper().split() if p]
        for parte in partes:
            if parte in TIPOS_PRUEBA:
                tipos.add(parte)
            elif len(parte) >= 2:
                proyectos.add(parte)
    return {"tipos": sorted(tipos or TIPOS_PRUEBA), "proyectos": sorted(proyectos or PROYECTOS)}


def recorte_evidencia(imagen, destino: Path) -> Path:
    """Guarda la imagen tal cual (con la pizarra dentro) para poder mirarla junto a la duda."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(destino), imagen)
    return destino


# ---------------------------------------------------------------------------------------------
# Lo aprendido en las demás carpetas: la pizarra repite forma entre ensayos del mismo proyecto
# ---------------------------------------------------------------------------------------------
RUTA_APRENDIZAJE = Path(__file__).resolve().parent.parent / "aprendizaje" / "pizarra.json"
PATRON_BARRA_PROYECTO = re.compile(r"EDAG\s?ME?X?I?C?O?\s+(?P<proyecto>[A-Z0-9]{2,5})\b")


def proyecto_en_barra(texto: str) -> str:
    """`… EDAG Mex BMG 19 JUN 25` → `BMG`. La barra del vídeo es la segunda fuente del proyecto."""
    encontrado = PATRON_BARRA_PROYECTO.search(" ".join(str(texto or "").upper().split()))
    if not encontrado:
        return ""
    pareja = emparejar(encontrado.group("proyecto"), PROYECTOS, largo=3)
    return pareja[0] if pareja else ""


def aprender_de_lecturas(lecturas) -> dict:
    """Cuenta lo que se repite entre carpetas: proyecto, tipo, temperatura, generador y su forma."""
    from collections import Counter
    cuenta: dict[str, Counter] = {"proyectos": Counter(), "tipos": Counter(),
                                  "temperaturas": Counter(), "generadores": Counter()}
    for lectura in lecturas:
        if not lectura:
            continue
        if lectura.get("proyecto"):
            cuenta["proyectos"][lectura["proyecto"]] += 1
        if lectura.get("tipo_prueba"):
            cuenta["tipos"][lectura["tipo_prueba"]] += 1
        if lectura.get("temperatura"):
            cuenta["temperaturas"][lectura["temperatura"]] += 1
        if lectura.get("inflator_type"):
            cuenta["generadores"][lectura["inflator_type"]] += 1
    casos = max(1, len([l for l in lecturas if l]))
    return {
        "casos": casos,
        **{clave: dict(contador.most_common()) for clave, contador in cuenta.items()},
        "repeticion": {clave: round(max(contador.values()) / casos, 2) if contador else 0.0
                       for clave, contador in cuenta.items()},
    }


def guardar_aprendizaje(aprendizaje: dict, ruta: Path | None = None) -> Path:
    import json
    ruta = Path(ruta) if ruta else RUTA_APRENDIZAJE
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(aprendizaje, ensure_ascii=False, indent=1), encoding="utf-8")
    return ruta


def cargar_aprendizaje(ruta: Path | None = None) -> dict:
    import json
    ruta = Path(ruta) if ruta else RUTA_APRENDIZAJE
    if not ruta.exists():
        return {}
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def completar_con_lo_aprendido(lectura: dict, aprendizaje: dict) -> dict:
    """Si el tipo de prueba no se lee, se toma el que **más se repite** en las demás carpetas.

    Queda marcado (`tipo_por_repeticion` + `repeticion`) para que el informe diga de dónde sale;
    nunca se hace pasar por lectura. Se exige que la repetición sea alta (≥ 0.6).
    """
    aprendizaje = aprendizaje or {}
    if lectura.get("tipo_prueba") or not lectura.get("proyecto"):
        return lectura
    tipos = aprendizaje.get("tipos") or {}
    if not tipos:
        return lectura
    tipo, veces = max(tipos.items(), key=lambda par: par[1])
    repeticion = (aprendizaje.get("repeticion") or {}).get("tipos", 0.0)
    if repeticion < 0.6:
        return lectura
    lectura["tipo_prueba"] = tipo
    lectura["tipo_por_repeticion"] = f"{veces}/{aprendizaje.get('casos', veces)} carpetas"
    lectura["repeticion"] = repeticion
    lectura["motivo"] = f"{tipo} {lectura['proyecto']}"
    lectura["faltan"] = [f for f in lectura.get("faltan", []) if f != "tipo_prueba"]
    return lectura


def aproximar_a_la_zona(imagen, motor, intentos: int = 3) -> dict:
    """Acerca la herramienta a la zona escrita a mano y la lee en grande.

    El tablero es oscuro y el rotulador fino: se recorta la franja donde va la pizarra (por debajo del
    borde superior del embellecedor), se amplía ×4 y se prueba gris, CLAHE y adaptativo. Devuelve las
    líneas que aparecen en **al menos dos** de los intentos (repetición = confianza).
    """
    from collections import Counter
    alto, ancho = imagen.shape[:2]
    zonas = [(int(ancho * 0.28), int(alto * 0.45), int(ancho * 0.62), int(alto * 0.70)),
             (int(ancho * 0.30), int(alto * 0.48), int(ancho * 0.58), int(alto * 0.66))]
    vistas: Counter = Counter()
    confianzas: dict[str, float] = {}
    for x0, y0, x1, y1 in zonas[:intentos]:
        recorte = imagen[y0:y1, x0:x1]
        if recorte.size == 0:
            continue
        for escala in (4, 6):
            grande = cv2.resize(recorte, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
            gris = cv2.cvtColor(grande, cv2.COLOR_BGR2GRAY)
            variantes = [cv2.cvtColor(gris, cv2.COLOR_GRAY2BGR),
                         cv2.cvtColor(cv2.createCLAHE(3.0, (8, 8)).apply(gris), cv2.COLOR_GRAY2BGR),
                         cv2.cvtColor(cv2.adaptiveThreshold(gris, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                                            cv2.THRESH_BINARY, 31, 10), cv2.COLOR_GRAY2BGR)]
            for variante in variantes:
                lectura, _ = leer_con_giros(variante, motor, modos=("original",))
                for texto, confianza in lectura.lineas:
                    limpio = " ".join(str(texto).split())
                    if len(limpio) < 2:
                        continue
                    vistas[limpio] += 1
                    confianzas[limpio] = max(confianzas.get(limpio, 0.0), float(confianza))
    return {"lineas": [(t, confianzas[t]) for t, _ in vistas.most_common() if vistas[t] >= 2],
            "repeticiones": dict(vistas)}
