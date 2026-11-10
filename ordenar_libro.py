#!/usr/bin/env python3
"""P42 · deja el libro legible y devuelve lo que se borró, preguntando antes de tomarlo.

    python3 ordenar_libro.py --libro versionV16_0_52_real.xlsx --simular
    python3 ordenar_libro.py --libro versionV16_0_52_real.xlsx \
        --recuperar versionV16_0_51.xlsx --preguntar

Por qué existe
--------------
El libro que sale del flujo tiene dos problemas que se ven en la misma pantalla y que,
sin embargo, no tienen nada que ver entre sí:

1. **Se lee mal.** El ancho de las columnas es el de la plantilla de la empresa: «Semana»
   no cabe en A, la serie del PAB se sale de su celda y se monta sobre la vecina, y en la
   banda de cabeceras hay un contador `=SUBTOTAL(3,...)` que aparece como un `0` suelto a
   la izquierda. Nada de eso es un dato: es presentación, y se arregla aquí.
2. **Se perdió lo escrito.** Cuando el flujo vuelve a generar la matriz en vez de rellenarla,
   borra lo que el libro ya traía. Con `--recuperar` se devuelve eso desde la copia anterior.

El riesgo de recuperar, y cómo se controla
------------------------------------------
Recuperar no es neutral: el libro anterior no sólo tiene **lo que se perdió**, también tiene
lo que ya se había corregido o decidido después. Traerlo a ciegas puede resucitar una lectura
vieja. Por eso, con `--preguntar`, cada celda llega a la pregunta con su **rastro de origen**
sacado de la `Trazabilidad` del libro del que se recupera:

    alta     la escribió una persona, o sale de la ruta de la carpeta (determinista)
    media    es una lectura automática (OCR, vídeo, DataMatrix) de una corrida anterior
    ninguna  la celda tiene valor y no hay rastro de dónde salió

Y las celdas que **ya tienen valor** nunca se tocan solas: si el libro anterior decía otra
cosa, es una discrepancia, y sólo cambia con un «sí» explícito (`--tomar todos`).

Garantías
---------
- El original no se toca: se escribe al lado, con `_ordenado`. `--en-sitio` hay que pedirlo.
- Antes de dar el archivo por bueno se comprueba que no se perdió ninguna celda con dato y
  que no desapareció ninguna parte interna del `.xlsx` (imágenes, comentarios). Si algo se
  pierde, no se escribe.
- Cada decisión (tomada o rechazada) queda en el informe si se pide `--informe`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import re
import sys
import zipfile
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter

HOJAS = ("Rangos", "Versuchsmatrix")
FILA_ENCABEZADOS = 7
FILA_DATOS = 8
COLUMNA_NUMERO = 3            # C · número de prueba: la llave para emparejar filas
PRIMERA_COLUMNA = 1
ULTIMA_COLUMNA = 20           # T · hasta aquí llega lo que el flujo escribe
ANCHO_MINIMO = 9.0
ANCHO_MAXIMO = 30.0
ALTO_LINEA = 15.0

# Columna del libro -> nombre interno del campo (el que usa Trazabilidad).
CAMPOS = {1: "week", 2: "test_reason", 3: "test_number", 4: "test_date", 5: "test_place",
          6: "temperature_condition", 7: "module_part_number", 8: "module_version",
          9: "module_serial_number", 10: "module_date", 11: "engineering_level",
          12: "delay_ms", 13: "inflator_type", 14: "inflator_supplier",
          15: "dashboard_part_number", 16: "dashboard_serial_number",
          17: "dashboard_date", 18: "dashboard_engineering_level", 19: "laser_opening",
          20: "dashboard_supplier"}

# Qué se puede esperar de cada fuente que declara la Trazabilidad.
FUENTES_HUMANAS = ("manual", "decision_manual")
FUENTES_DETERMINISTAS = ("ruta_carpeta", "estructura_caso")
FUENTES_AUTOMATICAS = ("ocr", "video", "barra_video", "dataMatrix", "automatica")


# --------------------------------------------------------------------------- lectura

def _vacio(valor) -> bool:
    return valor is None or (isinstance(valor, str) and not valor.strip())


def _texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, (dt.datetime, dt.date)):
        return valor.strftime("%Y-%m-%d")
    return str(valor)


def _es_formula(valor) -> bool:
    return isinstance(valor, str) and valor.strip().startswith("=")


def filas_con_datos(hoja, primera_columna: int = PRIMERA_COLUMNA,
                    ultima_columna: int = ULTIMA_COLUMNA) -> list[int]:
    """Filas que tienen algo en alguna de las columnas de la tabla."""
    filas = []
    for fila in range(FILA_DATOS, hoja.max_row + 1):
        if any(not _vacio(hoja.cell(fila, c).value)
               for c in range(primera_columna, ultima_columna + 1)):
            filas.append(fila)
    return filas


def encabezados(hoja, fila: int = FILA_ENCABEZADOS) -> dict[int, str]:
    return {c: _texto(hoja.cell(fila, c).value) for c in range(1, hoja.max_column + 1)
            if not _vacio(hoja.cell(fila, c).value)}


def numero_de_fila(hoja, fila: int) -> str:
    numero = _texto(hoja.cell(fila, COLUMNA_NUMERO).value).strip()
    return numero if len(numero) == 6 and numero.isdigit() else ""


# --------------------------------------------------------------------------- formato

def lineas_necesarias(texto: str, ancho: float) -> int:
    """Cuántas líneas ocupa `texto` en una columna de `ancho` (unidades de Excel)."""
    if not texto:
        return 1
    disponible = max(4.0, ancho - 0.8)          # margen interno de la celda
    lineas, actual = 1, 0.0
    for palabra in texto.split():
        largo = len(palabra) + (1 if actual else 0)
        if actual + largo > disponible:
            lineas += 1
            actual = float(len(palabra))
        else:
            actual += largo
    return lineas


def ancho_de_columna(hoja, columna: int, filas: list[int], cabecera: str,
                     actual: float | None = None,
                     minimo: float = ANCHO_MINIMO, maximo: float = ANCHO_MAXIMO) -> float:
    """El ancho que necesita la columna: lo que pide su dato más largo, sin pasarse.

    El encabezado no manda aquí: se parte en varias líneas (véase `formato_encabezado`),
    porque si mandara él, una columna como «Blanqueamiento lateral del housing» se
    comería media pantalla por dos palabras que caben en tres renglones.
    """
    palabra_mas_larga = max((len(p) for p in cabecera.split()), default=0)
    deseado = palabra_mas_larga + 2.0
    for fila in filas:
        valor = hoja.cell(fila, columna).value
        if _vacio(valor) or _es_formula(valor):
            continue
        deseado = max(deseado, len(_texto(valor)) + 2.0)
    deseado = min(max(deseado, minimo), maximo)
    # Nunca se estrecha una columna: si la plantilla la tiene más ancha, se respeta.
    if actual is not None:
        deseado = max(deseado, actual)
    return round(deseado, 2)


def formato_encabezado(hoja, anchos: dict[int, float], fila: int = FILA_ENCABEZADOS) -> int:
    """Ajusta el texto del encabezado y da a la fila el alto que necesita. Devuelve las líneas."""
    lineas_max = 1
    for columna, ancho in anchos.items():
        celda = hoja.cell(fila, columna)
        if _vacio(celda.value):
            continue
        alineacion = celda.alignment
        celda.alignment = Alignment(horizontal=alineacion.horizontal or "center",
                                    vertical="center", wrap_text=True,
                                    text_rotation=alineacion.text_rotation,
                                    indent=alineacion.indent)
        lineas_max = max(lineas_max, lineas_necesarias(_texto(celda.value), ancho))
    alto = round(min(ALTO_LINEA * lineas_max + 4.0, 110.0), 1)
    hoja.row_dimensions[fila].height = alto
    return lineas_max


def formato_datos(hoja, filas: list[int], columnas: list[int]) -> int:
    """Centra verticalmente el dato, para que no baile arriba de una fila alta."""
    tocadas = 0
    for fila in filas:
        for columna in columnas:
            celda = hoja.cell(fila, columna)
            if _vacio(celda.value):
                continue
            alineacion = celda.alignment
            if alineacion.vertical == "center":
                continue
            celda.alignment = Alignment(horizontal=alineacion.horizontal,
                                        vertical="center", wrap_text=alineacion.wrap_text,
                                        indent=alineacion.indent,
                                        text_rotation=alineacion.text_rotation)
            tocadas += 1
    return tocadas


def contador_en_banda(hoja, filas: list[int], modo: str = "mover") -> str:
    """El `=SUBTOTAL(3,...)` que vive en la banda de cabeceras (fila 6).

    Ahí se planta como un número suelto a la izquierda de «Prueba / Ensayo» y no dice qué
    cuenta. Se mueve a la primera columna libre a la derecha de la tabla, con su rango
    corregido a las filas que de verdad hay.
    """
    celda = hoja.cell(6, 1)
    if not (_es_formula(celda.value) and "SUBTOTAL" in str(celda.value).upper()):
        return "no había contador en la banda"
    if modo == "dejar":
        return "se deja donde estaba"
    if modo == "borrar":
        celda.value = None
        return "borrado de A6"
    fin = max(filas) if filas else FILA_DATOS
    formula = re.sub(r"A\$?\d+:A\$?\d+", f"A{FILA_DATOS}:A{fin}", str(celda.value))
    destino = get_column_letter(hoja.max_column + 1)
    hoja[f"{destino}6"] = formula
    celda.value = None
    return f"movido de A6 a {destino}6 ({formula})"


# --------------------------------------------------------------------------- rastro de origen

def _indices(hoja) -> dict[str, int]:
    return {str(celda.value).strip(): celda.column - 1
            for celda in hoja[1] if not _vacio(celda.value)}


def _campo(fila, indices: dict[str, int], nombre: str):
    posicion = indices.get(nombre)
    return None if posicion is None else fila[posicion]


def leer_rastro(libro_previo) -> dict[tuple[str, str], dict]:
    """(número de prueba, campo) -> {fuentes, reglas, imagen, lecturas}.

    Sale de la hoja `Trazabilidad` del libro del que se recupera: ahí está, para cada valor,
    de dónde vino (`ruta_carpeta`, `ocr`, `manual`, `decision_manual`…).
    """
    if "Trazabilidad" not in libro_previo.sheetnames:
        return {}
    hoja = libro_previo["Trazabilidad"]
    indices = _indices(hoja)
    rastro: dict[tuple[str, str], dict] = {}
    for fila in hoja.iter_rows(min_row=2, values_only=True):
        caso = str(_campo(fila, indices, "Caso") or "")
        partes = caso.split("|")
        numero = partes[2] if len(partes) > 2 else ""
        campo = _campo(fila, indices, "Campo")
        if not numero or not campo:
            continue
        registro = rastro.setdefault((numero, str(campo)), {
            "fuentes": set(), "reglas": set(), "imagenes": set(), "lecturas": 0})
        fuente = _campo(fila, indices, "Fuente")
        regla = _campo(fila, indices, "Regla")
        imagen = _campo(fila, indices, "Imagen")
        if fuente:
            registro["fuentes"].add(str(fuente))
        if regla:
            registro["reglas"].add(str(regla))
        if imagen:
            registro["imagenes"].add(str(imagen))
        registro["lecturas"] += 1
    return rastro


def clasificar(rastro: dict | None) -> tuple[str, str]:
    """Cuánto pesa un valor según quién lo puso. Devuelve (nivel, explicación)."""
    if not rastro:
        return "ninguna", "sin rastro de origen (venía en el libro y nadie lo anotó)"
    fuentes = rastro["fuentes"]
    imagen = next(iter(sorted(rastro["imagenes"])), "")
    regla = next(iter(sorted(rastro["reglas"])), "")
    if any(f.startswith(FUENTES_HUMANAS) for f in fuentes):
        detalle = "decisión humana registrada" if any(
            f.startswith("decision_manual") for f in fuentes) else "escrita a mano"
        return "alta", detalle
    if fuentes & set(FUENTES_DETERMINISTAS):
        return "alta", f"de la ruta de la carpeta (regla: {regla or '—'})"
    if fuentes & set(FUENTES_AUTOMATICAS):
        de_donde = f" de {imagen}" if imagen else ""
        return "media", f"lectura automática{de_donde} (regla: {regla or '—'})"
    return "media", f"fuente {'/'.join(sorted(fuentes)) or '—'} (regla: {regla or '—'})"


# --------------------------------------------------------------------------- candidatos

def reunir_candidatos(libro, previo, columnas: range, tomar: str) -> list[dict]:
    """Todo lo que se podría devolver, sin devolverlo todavía.

    Una sola entrada por (número de prueba, campo) aunque la celda esté en `Rangos` y en
    `Versuchsmatrix`: son la misma decisión y no se pregunta dos veces.
    """
    rastro = leer_rastro(previo)
    previas = {nombre: previo[nombre] for nombre in HOJAS if nombre in previo.sheetnames}
    por_llave: dict[tuple[str, int], dict] = {}

    for nombre in HOJAS:
        if nombre not in libro.sheetnames:
            continue
        hoja = libro[nombre]
        anterior = previas.get(nombre)
        if anterior is None:
            continue
        mapa = {}
        for fila in filas_con_datos(anterior, columnas.start, columnas.stop - 1):
            numero = numero_de_fila(anterior, fila)
            if numero:
                mapa[numero] = fila
        for fila in filas_con_datos(hoja, columnas.start, columnas.stop - 1):
            numero = numero_de_fila(hoja, fila)
            if not numero or numero not in mapa:
                continue
            for columna in columnas:
                celda = hoja.cell(fila, columna)
                if _es_formula(celda.value):
                    continue
                valor_previo = anterior.cell(mapa[numero], columna).value
                if _vacio(valor_previo):
                    continue
                actual = celda.value
                if _vacio(actual):
                    tipo = "vacio"
                elif _texto(actual) != _texto(valor_previo):
                    tipo = "conflicto" if tomar == "todos" else None
                else:
                    continue
                if tipo is None:
                    continue
                llave = (numero, columna)
                if llave in por_llave:
                    por_llave[llave]["destinos"].append((nombre, fila))
                else:
                    campo = CAMPOS.get(columna, f"columna_{get_column_letter(columna)}")
                    nivel, detalle = clasificar(rastro.get((numero, campo)))
                    por_llave[llave] = {
                        "numero": numero, "columna": columna, "campo": campo,
                        "titulo": _texto(hoja.cell(FILA_ENCABEZADOS, columna).value),
                        "letra": get_column_letter(columna),
                        "previo": valor_previo, "actual": actual, "tipo": tipo,
                        "nivel": nivel, "detalle": detalle,
                        "destinos": [(nombre, fila)]}
    return sorted(por_llave.values(), key=lambda c: (c["numero"], c["columna"]))


def describir(candidato: dict) -> str:
    valor = _texto(candidato["previo"])
    return (f"{candidato['numero']} · {candidato['titulo'][:34]:34} "
            f"← {valor[:26]!r:28} [{candidato['nivel']}] {candidato['detalle']}")


# --------------------------------------------------------------------------- decidir

MENU = """Hay {total} celdas que estaban en el libro anterior y aquí están vacías.
  del libro: {origen}  (guardado el {fecha})
  por rastro:  {alta} de confianza alta · {media} lectura automática · {ninguna} sin rastro
  ------------------------------------------------------------------
  a  tomarlas todas
  c  sólo las de confianza alta (mano / ruta de carpeta)
  d  ver las dudosas una a una (lectura automática y sin rastro)
  u  verlas todas una a una
  l  sólo listarlas y no escribir nada
  r  no tomar ninguna
  q  salir sin escribir
"""


def _preguntar_una(candidato: dict, indice: int, total: int) -> str:
    etiqueta = "YA TIENE VALOR" if candidato["tipo"] == "conflicto" else "vacía"
    print(f"\n[{indice:>4}/{total}] {candidato['numero']} · {candidato['titulo']}  ({etiqueta})")
    print(f"        anterior: {_texto(candidato['previo'])!r}")
    if candidato["tipo"] == "conflicto":
        print(f"        ahora:    {_texto(candidato['actual'])!r}   ← no coinciden")
    print(f"        origen:   {candidato['detalle']}")
    opciones = "[s/n/a=todas/q=salir]" if candidato["tipo"] == "vacio" else "[s/n/q=salir]"
    while True:
        respuesta = input(f"        ¿tomar el valor anterior? {opciones} (Enter = n): ").strip().lower()
        if respuesta == "":
            return "no"
        if respuesta in ("s", "si", "sí"):
            return "si"
        if respuesta in ("n", "no"):
            return "no"
        if respuesta == "a" and candidato["tipo"] == "vacio":
            return "todas"
        if respuesta in ("q", "salir"):
            return "salir"
        print("        respuesta no válida")


def decidir(candidatos: list[dict], preguntar: bool, origen: Path, fecha: str,
            por_defecto: str, exigir_rastro: bool) -> dict[tuple[str, int], str]:
    """(número, columna) -> 'si' / 'no'. Sin consola, decide la política por defecto."""
    decisiones: dict[tuple[str, int], str] = {}
    if not candidatos:
        return decisiones

    if not preguntar:
        for candidato in candidatos:
            llave = (candidato["numero"], candidato["columna"])
            if candidato["tipo"] == "conflicto":
                decisiones[llave] = "no"
            elif exigir_rastro and candidato["nivel"] == "ninguna":
                decisiones[llave] = "no"
            else:
                decisiones[llave] = "si"
        return decisiones

    cuenta = {"alta": 0, "media": 0, "ninguna": 0}
    for candidato in candidatos:
        cuenta[candidato["nivel"]] += 1
    print(MENU.format(total=len(candidatos), origen=origen.name, fecha=fecha,
                      alta=cuenta["alta"], media=cuenta["media"],
                      ninguna=cuenta["ninguna"]))
    while True:
        eleccion = input("  ¿qué hago? [a/c/d/u/l/r/q]: ").strip().lower()
        if eleccion in ("", "r", "l", "q", "a", "c"):
            break
        if eleccion in ("d", "u"):
            break
        print("  elige una de las letras del menú")

    if eleccion in ("q", "l", ""):
        print("  no se toma nada." if eleccion != "l" else "  sólo listado:")
        if eleccion == "l":
            for i, candidato in enumerate(candidatos, 1):
                print(f"  {i:>4}. {describir(candidato)}")
        return {llave: "no" for llave in ((c["numero"], c["columna"]) for c in candidatos)}

    if eleccion == "r":
        return {llave: "no" for llave in ((c["numero"], c["columna"]) for c in candidatos)}

    if eleccion in ("a", "c"):
        for candidato in candidatos:
            if candidato["tipo"] == "conflicto":
                decisiones[(candidato["numero"], candidato["columna"])] = "no"
            elif eleccion == "c" and candidato["nivel"] != "alta":
                decisiones[(candidato["numero"], candidato["columna"])] = "no"
            else:
                decisiones[(candidato["numero"], candidato["columna"])] = "si"
        return decisiones

    # eleccion == 'd' o 'u': una a una
    vistas = [c for c in candidatos
              if eleccion == "u" or c["nivel"] != "alta"]
    # Las de confianza alta que no entran en la ronda se toman; las conflictivas, nunca.
    for candidato in candidatos:
        if candidato not in vistas:
            llave = (candidato["numero"], candidato["columna"])
            decisiones[llave] = "si" if candidato["tipo"] == "vacio" else "no"
    for i, candidato in enumerate(vistas, 1):
        respuesta = _preguntar_una(candidato, i, len(vistas))
        llave = (candidato["numero"], candidato["columna"])
        if respuesta == "salir":
            print("  se corta aquí: lo decidido hasta ahora se respeta, el resto no se toma.")
            for resto in candidatos:
                decisiones.setdefault((resto["numero"], resto["columna"]), "no")
            break
        if respuesta == "todas":
            decisiones[llave] = "si"
            for resto in candidatos:
                llave_resto = (resto["numero"], resto["columna"])
                if llave_resto not in decisiones:
                    decisiones[llave_resto] = "no" if resto["tipo"] == "conflicto" else "si"
            print("  el resto se toma tal cual (salvo las celdas que ya tenían otro valor).")
            break
        decisiones[llave] = "si" if respuesta == "si" else "no"
    for candidato in candidatos:
        decisiones.setdefault((candidato["numero"], candidato["columna"]), "no")
    return decisiones


def aplicar(libro, candidatos: list[dict], decisiones: dict[tuple[str, int], str]) -> int:
    escritas = 0
    for candidato in candidatos:
        if decisiones.get((candidato["numero"], candidato["columna"])) != "si":
            continue
        for nombre, fila in candidato["destinos"]:
            if nombre in libro.sheetnames:
                libro[nombre].cell(fila, candidato["columna"]).value = candidato["previo"]
                escritas += 1
    return escritas


# --------------------------------------------------------------------------- comprobación

def instantanea(libro) -> dict[tuple[str, int, int], str]:
    foto = {}
    for hoja in libro.worksheets:
        for fila in hoja.iter_rows():
            for celda in fila:
                if not _vacio(celda.value):
                    foto[(hoja.title, celda.row, celda.column)] = _texto(celda.value)
    return foto


def celdas_del_contador(antes: dict, despues: dict) -> set[tuple[str, int, int]]:
    """Las celdas que el contador movió: no son pérdida de datos, son un traslado."""
    movidas = set()
    for clave, valor in antes.items():
        if clave not in despues and "SUBTOTAL" in valor.upper():
            movidas.add(clave)
    for clave, valor in despues.items():
        if clave not in antes and "SUBTOTAL" in valor.upper():
            movidas.add(clave)
    return movidas


def partes_del_zip(ruta: Path) -> set[str]:
    with zipfile.ZipFile(ruta) as z:
        return {n for n in z.namelist() if not n.endswith("/")}


def huella(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()[:16]


def informe_de_decisiones(candidatos: list[dict], decisiones: dict, ruta: Path) -> None:
    lineas = ["| celda | caso | campo | anterior | ahora | origen | decisión |",
              "|---|---|---|---|---|---|---|"]
    for candidato in candidatos:
        decision = decisiones.get((candidato["numero"], candidato["columna"]), "no")
        lineas.append(
            f"| {candidato['letra']} | {candidato['numero']} | {candidato['titulo']} | "
            f"{_texto(candidato['previo'])} | {_texto(candidato['actual']) or '—'} | "
            f"{candidato['nivel']}: {candidato['detalle']} | "
            f"{'tomada' if decision == 'si' else 'rechazada'} |")
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- principal

def ordenar(ruta: Path, salida: Path, recuperar_de: Path | None, modo_contador: str,
            minimo: float, maximo: float, simular: bool, columnas: range,
            preguntar: bool, tomar: str, por_defecto: str, exigir_rastro: bool,
            ruta_informe: Path | None) -> int:
    libro = load_workbook(ruta)
    antes = instantanea(libro)

    print(f"libro:  {ruta}")
    if recuperar_de:
        print(f"origen: {recuperar_de}")
    print(f"hojas de tabla: {', '.join(h for h in HOJAS if h in libro.sheetnames) or '(ninguna)'}")

    previo = load_workbook(recuperar_de) if recuperar_de else None
    if previo is not None:
        propiedades = previo.properties
        fecha_previo = propiedades.modified or propiedades.created
        fecha_texto = fecha_previo.strftime("%Y-%m-%d %H:%M") if fecha_previo else "sin fecha"
        if isinstance(fecha_previo, dt.datetime) and libro.properties.modified and \
                fecha_previo > libro.properties.modified:
            print(f"  [AVISO] el libro del que se recupera es MÁS NUEVO que el que se repara"
                  f" ({fecha_texto}): revisa que no estés yendo al revés.")

    candidatos = reunir_candidatos(libro, previo, columnas, tomar) if previo is not None else []
    decisiones: dict[tuple[str, int], str] = {}
    if candidatos:
        fecha_texto = "sin fecha"
        if previo.properties.modified:
            fecha_texto = previo.properties.modified.strftime("%Y-%m-%d %H:%M")
        decisiones = decidir(candidatos, preguntar, recuperar_de, fecha_texto,
                             por_defecto, exigir_rastro)

    for nombre in HOJAS:
        if nombre not in libro.sheetnames:
            continue
        hoja = libro[nombre]
        filas = filas_con_datos(hoja, columnas.start, columnas.stop - 1)
        cabs = encabezados(hoja)
        print(f"\n== {nombre} · {len(filas)} filas de datos (de {FILA_DATOS} a "
              f"{max(filas) if filas else FILA_DATOS})")

        anchos = {c: ancho_de_columna(hoja, c, filas, cabs[c],
                                      hoja.column_dimensions[get_column_letter(c)].width,
                                      minimo, maximo) for c in cabs}
        cambios = []
        for columna, ancho in anchos.items():
            letra = get_column_letter(columna)
            actual = hoja.column_dimensions[letra].width
            if actual is None or abs(actual - ancho) >= 0.5:
                cambios.append(f"{letra} {('—' if actual is None else round(actual, 1))}→{ancho}")
                if not simular:
                    hoja.column_dimensions[letra].width = ancho
        print(f"   anchos ajustados: {len(cambios)}"
              + (f"  [{', '.join(cambios[:8])}{'…' if len(cambios) > 8 else ''}]" if cambios else ""))

        if not simular:
            lineas = formato_encabezado(hoja, anchos)
            tocadas = formato_datos(hoja, filas, [c for c in cabs if c <= ULTIMA_COLUMNA])
            hoja.freeze_panes = hoja.freeze_panes or f"A{FILA_DATOS}"
            print(f"   encabezado: {lineas} línea(s) · alto {hoja.row_dimensions[FILA_ENCABEZADOS].height}")
            print(f"   datos: {tocadas} celdas centradas")
            print(f"   contador: {contador_en_banda(hoja, filas, modo_contador)}")
        else:
            print("   (simulación: no se toca el formato)")

    if candidatos:
        tomadas = [c for c in candidatos if decisiones.get((c["numero"], c["columna"])) == "si"]
        rechazadas = [c for c in candidatos if decisiones.get((c["numero"], c["columna"])) != "si"]
        print(f"\n== recuperar de {recuperar_de.name}")
        print(f"   tomadas:    {len(tomadas)}")
        for candidato in tomadas[:8]:
            print(f"      + {describir(candidato)}")
        if len(tomadas) > 8:
            print(f"      … y {len(tomadas) - 8} más")
        if rechazadas:
            print(f"   rechazadas: {len(rechazadas)} (se quedan como están)")
            for candidato in rechazadas[:5]:
                print(f"      - {describir(candidato)}")
            if len(rechazadas) > 5:
                print(f"      … y {len(rechazadas) - 5} más")
        if not simular:
            escritas = aplicar(libro, candidatos, decisiones)
            print(f"   aplicadas: {escritas} celdas (en {' y '.join(h for h in HOJAS if h in libro.sheetnames)})")
        if ruta_informe:
            informe_de_decisiones(candidatos, decisiones, ruta_informe)
            print(f"   informe: {ruta_informe}")

    if simular:
        print("\n(simulación) no se escribió nada.")
        return 0

    salida.parent.mkdir(parents=True, exist_ok=True)
    libro.save(salida)

    despues = instantanea(load_workbook(salida))
    movidas = celdas_del_contador(antes, despues)
    perdidas = [k for k, v in antes.items() if despues.get(k) != v and k not in movidas]
    ganadas = [k for k in despues if k not in antes]

    partes_antes, partes_despues = partes_del_zip(ruta), partes_del_zip(salida)
    perdidas_xlsx = sorted(partes_antes - partes_despues)

    print("\n== comprobación")
    print(f"   celdas con dato en el original: {len(antes)}")
    print(f"   celdas que cambiaron de valor:  {len(perdidas)}"
          + ("" if not perdidas else f"  ← {perdidas[:5]}"))
    print(f"   celdas nuevas (recuperadas):    {len(ganadas)}")
    print(f"   partes internas del .xlsx perdidas: {len(perdidas_xlsx)}"
          + ("" if not perdidas_xlsx else f"  ← {perdidas_xlsx[:5]}"))

    if perdidas or perdidas_xlsx:
        salida.unlink(missing_ok=True)
        print("\nNO se ha dejado el archivo: la comprobación no pasó. El original sigue intacto.")
        return 2

    print(f"\nsalida: {salida}  ({salida.stat().st_size / 1e6:.2f} MB · sha256 {huella(salida)}…)")
    print("comprobación en verde: no se perdió ningún dato ni ninguna parte interna.")
    return 0


def _letra_a_indice(letra: str) -> int:
    letra = letra.strip().upper()
    indice = 0
    for caracter in letra:
        indice = indice * 26 + (ord(caracter) - ord("A") + 1)
    return indice


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Ordena el formato del libro y devuelve lo que un flujo anterior borró, "
                    "preguntando antes de tomarlo.")
    p.add_argument("--libro", required=True, help="libro a ordenar (.xlsx)")
    p.add_argument("--salida", help="dónde escribir (por defecto, al lado con _ordenado)")
    p.add_argument("--en-sitio", action="store_true",
                   help="sobrescribir el libro de entrada (haz copia antes)")
    p.add_argument("--recuperar", help="libro anterior del que devolver las celdas vaciadas")
    p.add_argument("--preguntar", action="store_true",
                   help="preguntar celda a celda (o por grupos) antes de tomar nada")
    p.add_argument("--tomar", choices=("vacios", "todos"), default="vacios",
                   help="qué entra en la recuperación: sólo celdas vacías (por defecto) o "
                        "también las que ya tienen otro valor")
    p.add_argument("--por-defecto", choices=("si", "no"), default="no",
                   help="respuesta al pulsar Enter en las preguntas (por defecto: no)")
    p.add_argument("--exigir-rastro", action="store_true",
                   help="descartar los valores sin rastro de origen en la Trazabilidad")
    p.add_argument("--informe", help="escribir un .md con cada decisión tomada o rechazada")
    p.add_argument("--contador", choices=("mover", "dejar", "borrar"), default="mover",
                   help="qué hacer con el SUBTOTAL de la banda de cabeceras")
    p.add_argument("--min-ancho", type=float, default=ANCHO_MINIMO)
    p.add_argument("--max-ancho", type=float, default=ANCHO_MAXIMO)
    p.add_argument("--columnas", default=f"A:{get_column_letter(ULTIMA_COLUMNA)}",
                   help="rango de columnas de la tabla (por defecto A:T)")
    p.add_argument("--simular", action="store_true", help="contar y avisar, sin escribir")
    args = p.parse_args(argv)

    if args.preguntar and not sys.stdin.isatty():
        print("--preguntar necesita una consola: aquí no hay nadie a quien preguntar.\n"
              "  ejecútalo desde la ventana de comandos, o quita --preguntar y usa --exigir-rastro.",
              file=sys.stderr)
        return 2

    ruta = Path(args.libro).expanduser().resolve()
    if not ruta.exists():
        print(f"no existe: {ruta}", file=sys.stderr)
        return 2
    if args.salida:
        salida = Path(args.salida).expanduser().resolve()
    elif args.en_sitio:
        salida = ruta
    else:
        salida = ruta.with_name(f"{ruta.stem}_ordenado{ruta.suffix}")
    if salida == ruta and not args.en_sitio:
        print("para sobrescribir el original hace falta --en-sitio", file=sys.stderr)
        return 2

    inicio, _, fin = args.columnas.partition(":")
    columnas = range(_letra_a_indice(inicio), _letra_a_indice(fin or inicio) + 1)

    recuperar_de = None
    if args.recuperar:
        recuperar_de = Path(args.recuperar).expanduser().resolve()
        if not recuperar_de.exists():
            print(f"no existe el libro anterior: {recuperar_de}", file=sys.stderr)
            return 2

    return ordenar(ruta, salida, recuperar_de, args.contador, args.min_ancho, args.max_ancho,
                   args.simular, columnas, args.preguntar, args.tomar, args.por_defecto,
                   args.exigir_rastro,
                   Path(args.informe).expanduser().resolve() if args.informe else None)


if __name__ == "__main__":
    raise SystemExit(main())
