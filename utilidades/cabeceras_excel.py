"""utilidades/cabeceras_excel.py — Adaptador estricto de cabeceras del libro real.

Por qué existe
--------------
El libro de la empresa (`Versuchsmatrix`) tiene **54 encabezados** en la fila 7, con
la columna AH sin encabezado, fórmulas dentro del rango de datos y dos cabeceras
que se llaman **igual** en dos columnas distintas:

    N7  `Lieferant / Supplier`  -> proveedor del generador (Autoliv)
    T7  `Lieferant / Supplier`  -> proveedor del tablero (FORVIA)

El exportador histórico (`reporte_bmg._poblar_lista`) escribe **por posición** y,
además, **sobrescribe la fila 7 con sus propias traducciones**. En este libro eso
significa: renombrar los encabezados de la empresa y, si la maquetación cambia,
meter cada valor debajo de un encabezado que no le corresponde. En un entorno
empresarial eso no es un detalle de estilo: es un dato mal atribuido.

Reglas de este módulo (deliberadamente conservadoras)
----------------------------------------------------
1. **Manda el texto del encabezado**, no la posición. La letra de columna solo
   sirve para *corroborar*.
2. Si un texto puede ser dos campos distintos (`Lieferant`), solo se resuelve si
   la columna es la documentada. Si no, queda **ambigua** y no se escribe.
3. Un encabezado desconocido queda **no resuelto**. Nunca se adivina por posición.
4. Dos columnas no pueden reclamar el mismo campo: si pasa, es **colisión** y no
   se escribe en ninguna de las dos.
5. **Nunca** se reescribe la fila de encabezados.
6. **Nunca** se escribe encima de una fórmula, y **nunca** se limpia una fila.
7. Todo lo que no se escribe se devuelve con su motivo, para que quede en el
   informe: lo que no se hizo también hay que poder auditarlo.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------
# Texto de encabezado -> campo canónico. Se documentan las formas que aparecen
# en el libro y en la guía; las traducciones del exportador histórico se aceptan
# como alias para no romper libros ya generados por el propio programa.
ALIAS_ENCABEZADOS: dict[str, str] = {
    # documentados en el libro real (mapa de campos §3)
    "versuche begrundung": "test_reason",
    "versuchsbegrundung": "test_reason",
    "versuche begruendung": "test_reason",
    "nummer": "test_number",
    "number": "test_number",
    "standort": "test_place",
    "place": "test_place",
    "temperatur c": "temperature_condition",
    "temperatur": "temperature_condition",
    "temperature c": "temperature_condition",
    "woche": "week",
    "week": "week",
    "semana": "week",
    "datum": "test_date",
    "date": "test_date",
    "fecha": "test_date",
    # exportador histórico (es/en/de)
    "motivo de prueba": "test_reason", "test reason": "test_reason", "prufgrund": "test_reason",
    "numero de prueba": "test_number", "test number": "test_number", "versuchsnummer": "test_number",
    "fecha de prueba": "test_date", "test date": "test_date", "testdatum": "test_date",
    "lugar de prueba": "test_place", "test location": "test_place", "prufort": "test_place",
    "temperatura": "temperature_condition", "temperature": "temperature_condition",
    "pab numero de parte": "module_part_number", "pab part number": "module_part_number",
    "pab teilnummer": "module_part_number",
    "pab variante": "module_version", "pab variant": "module_version",
    "pab serie": "module_serial_number", "pab serial": "module_serial_number",
    "pab seriennummer": "module_serial_number",
    "pab fecha fabricacion": "module_date", "pab manufacturing date": "module_date",
    "pab fertigungsdatum": "module_date",
    "pab nivel de ingenieria": "engineering_level",
    "pab engineering level": "engineering_level",
    "pab entwicklungsstand": "engineering_level",
    "delay ms": "delay_ms",
    "tipo de generador": "inflator_type", "inflator type": "inflator_type",
    "generatortyp": "inflator_type",
    "tablero numero de parte": "dashboard_part_number",
    "dashboard part number": "dashboard_part_number",
    "i tafel teilnummer": "dashboard_part_number",
    "tablero serie": "dashboard_serial_number", "dashboard serial": "dashboard_serial_number",
    "i tafel seriennummer": "dashboard_serial_number",
    "tablero fecha fabricacion": "dashboard_date",
    "dashboard manufacturing date": "dashboard_date",
    "i tafel fertigungsdatum": "dashboard_date",
    "tablero nivel de ingenieria": "dashboard_engineering_level",
    "dashboard engineering level": "dashboard_engineering_level",
    "i tafel entwicklungsstand": "dashboard_engineering_level",
    "apertura laser": "laser_opening", "laser opening": "laser_opening",
    "laseroffnung": "laser_opening",
    "evaluacion cushion": "cushion_evaluation", "cushion evaluation": "cushion_evaluation",
    "cushion bewertung": "cushion_evaluation",
    "evaluacion housing": "housing_evaluation", "housing evaluation": "housing_evaluation",
    "housing bewertung": "housing_evaluation",
    "evaluacion cubierta protectora": "protective_cover_evaluation",
    "protective cover evaluation": "protective_cover_evaluation",
    "schutzabdeckungs bewertung": "protective_cover_evaluation",
    "tiempo apertura ms": "opening_time_ms", "opening time ms": "opening_time_ms",
    "offnungszeit ms": "opening_time_ms",
    "medicion forvia ms": "forvia_measurement_ms", "forvia measurement ms": "forvia_measurement_ms",
    "forvia messung ms": "forvia_measurement_ms",
    "inflado completo ms": "full_inflation_time_ms", "full inflation time ms": "full_inflation_time_ms",
    "aufblaszeit ms": "full_inflation_time_ms",
    "segunda revision": "second_review", "second review": "second_review",
    "zweite prufung": "second_review",
    "comentarios pab": "pab_comments", "pab comments": "pab_comments",
    "pab kommentare": "pab_comments",
    "evaluacion pab zsb": "pab_zsb_evaluation", "pab zsb evaluation": "pab_zsb_evaluation",
    "pab zsb bewertung": "pab_zsb_evaluation",
    "comentarios tablero": "dashboard_comments", "dashboard comments": "dashboard_comments",
    "i tafel kommentare": "dashboard_comments",
    "evaluacion tablero zsb": "dashboard_zsb_evaluation",
    "dashboard zsb evaluation": "dashboard_zsb_evaluation",
    "i tafel zsb bewertung": "dashboard_zsb_evaluation",
    "comentarios entorno de prueba": "test_environment_comments",
    "test environment comments": "test_environment_comments",
    "kommentare zur prufumgebung": "test_environment_comments",
    "evaluacion general del sistema": "overall_system_evaluation",
    "overall system evaluation": "overall_system_evaluation",
    "gesamtsystembewertung": "overall_system_evaluation",
    # las dos cabeceras repetidas: SOLO se resuelven con la columna documentada
    "lieferant": "__DUPLICADO__",
    "lieferant supplier": "__DUPLICADO__",
    "supplier": "__DUPLICADO__",
    "proveedor de generador": "inflator_supplier",
    "inflator supplier": "inflator_supplier",
    "generatorlieferant": "inflator_supplier",
    "proveedor de tablero": "dashboard_supplier",
    "dashboard supplier": "dashboard_supplier",
    "i tafel lieferant": "dashboard_supplier",
    "proveedor": "__DUPLICADO__",
}

# ---------------------------------------------------------------------------
# Catálogo del LIBRO REAL (Book-10-Examples.xlsx, hoja Versuchsmatrix, fila 7).
# Cada celda lleva dos idiomas separados por salto de línea, así que se indexa
# por el texto normalizado completo. Verificado encabezado a encabezado contra
# el archivo entregado el 2026-10-30.
# ---------------------------------------------------------------------------
# Textos que el libro repite en varias columnas: el texto por sí solo no basta,
# resuelve la columna documentada. Si el libro cambiara de maquetación, quedan
# ambiguos a propósito.
DUPLICADOS_LIBRO: dict[str, set[str]] = {
    "datum date": {"test_date", "module_date", "dashboard_date"},
    "teilnummer part number": {"module_part_number", "dashboard_part_number"},
    "stand eng level": {"engineering_level", "dashboard_engineering_level"},
    "lieferant supplier": {"inflator_supplier", "dashboard_supplier"},
}

CATALOGO_LIBRO: dict[str, tuple[str, str]] = {
    "woche week": ("week", "campo"),
    "versuche begrundung": ("test_reason", "campo"),
    "nummer number": ("test_number", "campo"),
    "standort place": ("test_place", "campo"),
    "temperatur c temperature c": ("temperature_condition", "campo"),
    "version": ("module_version", "campo"),
    "serial no series": ("module_serial_number", "campo"),
    "delay ms": ("delay_ms", "campo"),
    "gasgenerator inflator": ("inflator_type", "campo"),
    "serial serie number": ("dashboard_serial_number", "campo"),
    "laser": ("laser_opening", "campo"),
    "luftsack cushion": ("cushion_evaluation", "campo"),
    "gehause housing": ("housing_evaluation", "campo"),
    "schutzhuelle protective cover": ("protective_cover_evaluation", "campo"),
    "offnungs zeit ms opening time": ("opening_time_ms", "campo"),
    "forvia": ("forvia_measurement_ms", "campo"),
    "aufblaszeit ms full inflation time": ("full_inflation_time_ms", "campo"),
    "2nd review mario": ("second_review", "campo"),
    "bemerkungen der bfab comments of pab": ("pab_comments", "campo"),
    "bewertung als zsb bfab evaluation as zsb bfab": ("pab_zsb_evaluation", "campo"),
    "bemerkungen der instrumententafel comments of dashboard": ("dashboard_comments", "campo"),
    "bewertung als zsb i tafel evaluation as zsb i tafel": ("dashboard_zsb_evaluation", "campo"),
    "bemerkungen der versuchstrager comments of evironment of test":
        ("test_environment_comments", "campo"),
    "gesamt bewertung als sicherheits sytem ip ab": ("overall_system_evaluation", "campo"),
    # bloque de evaluaciones de daño (AI:BC): se reconocen, no se rellenan por OCR
    "15 weissbruch in seitewand der gehause": ("housing_sidewall_stress_whitening", "dano"),
    "16 weissbruch in innenbereich der gehause": ("housing_inner_stress_whitening", "dano"),
}

# Columnas que el libro dedica al catálogo de daños (mapa §5: AI:BC). Esas
# columnas NO se rellenan desde OCR: son evaluaciones visuales del especialista.
PRIMERA_COLUMNA_DANOS, ULTIMA_COLUMNA_DANOS = "AI", "BC"

# Columnas documentadas del libro real (mapa de campos §3 y §5). La letra sirve
# para CORROBORAR el texto, nunca para sustituirlo.
COLUMNAS_DOCUMENTADAS: dict[str, str | None] = {
    "A": "week", "B": "test_reason", "C": "test_number", "D": "test_date",
    "E": "test_place", "F": "temperature_condition",
    "G": "module_part_number", "H": "module_version", "I": "module_serial_number",
    "J": "module_date", "K": "engineering_level",
    "L": "delay_ms", "M": "inflator_type", "N": "inflator_supplier",
    "O": "dashboard_part_number", "P": "dashboard_serial_number",
    "Q": "dashboard_date", "R": "dashboard_engineering_level",
    "S": "laser_opening", "T": "dashboard_supplier",
    "U": "cushion_evaluation", "V": "housing_evaluation",
    "W": "protective_cover_evaluation",
    "X": "opening_time_ms", "Y": "forvia_measurement_ms", "Z": "full_inflation_time_ms",
    "AA": "second_review", "AB": "pab_comments", "AC": "pab_zsb_evaluation",
    "AD": "dashboard_comments", "AE": "dashboard_zsb_evaluation",
    "AF": "test_environment_comments", "AG": "overall_system_evaluation",
    "AH": None,  # sin encabezado: columna estructural, jamás un campo
}

# Columnas que el libro declara pero que NO están documentadas campo a campo
# (bloque de daños AI:BC). Se reconocen como bloque y no se escriben.
BLOQUE_NO_DOCUMENTADO = ("AI", "BC")


def normalizar_encabezado(texto) -> str:
    """Minúsculas, sin acentos, sin signos y con espacios simples.

    'Versuche Begründung' -> 'versuche begrundung'; 'Temperatur °C' -> 'temperatur c'.
    """
    if texto is None:
        return ""
    # la ß no se descompone en NFKD: se convierte antes o desaparece del texto
    bruto = unicodedata.normalize("NFKD", str(texto).replace("ß", "ss").replace("ẞ", "SS"))
    sin_acentos = "".join(c for c in bruto if not unicodedata.combining(c))
    limpio = sin_acentos.lower().replace("°", " ").replace("º", " ")
    limpio = re.sub(r"[\r\n\t]+", " ", limpio)
    limpio = re.sub(r"[^a-z0-9/ ]+", " ", limpio)
    return re.sub(r"\s+", " ", limpio).strip()


def letra_a_indice(letra: str) -> int:
    """'A' -> 1, 'Z' -> 26, 'AA' -> 27, 'BC' -> 55."""
    total = 0
    for caracter in str(letra).strip().upper():
        if not caracter.isalpha():
            raise ValueError(f"Letra de columna inválida: {letra!r}")
        total = total * 26 + (ord(caracter) - ord("A") + 1)
    return total


def indice_a_letra(indice: int) -> str:
    if indice < 1:
        raise ValueError(f"Índice de columna inválido: {indice}")
    letras = ""
    while indice:
        indice, resto = divmod(indice - 1, 26)
        letras = chr(ord("A") + resto) + letras
    return letras


@dataclass
class Encabezado:
    columna: str
    texto: str
    clave: str | None = None
    estado: str = "no_resuelta"
    motivo: str = ""


@dataclass
class InformeCabeceras:
    fila: int
    encabezados: list[Encabezado] = field(default_factory=list)
    colisiones: dict[str, list[str]] = field(default_factory=dict)
    estructurales: list[str] = field(default_factory=list)

    @property
    def resueltos(self) -> dict[str, str]:
        """clave -> letra de columna (solo las que se pueden escribir)."""
        return {e.clave: e.columna for e in self.encabezados
                if e.estado == "resuelta" and e.clave}

    @property
    def ambiguas(self) -> list[Encabezado]:
        return [e for e in self.encabezados if e.estado == "ambigua"]

    @property
    def no_resueltas(self) -> list[Encabezado]:
        return [e for e in self.encabezados if e.estado == "no_resuelta"]

    @property
    def danos(self) -> list[Encabezado]:
        """Evaluaciones de daño reconocidas: nunca se rellenan por OCR."""
        return [e for e in self.encabezados if e.estado == "dano"]

    def puede_escribir(self, clave: str) -> tuple[bool, str]:
        if any(e.clave == clave and e.estado == "dano" for e in self.encabezados):
            return False, ("el libro usa esa columna para una evaluación visual de daño: "
                           "no se rellena desde OCR")
        if clave in self.colisiones:
            return False, f"colisión entre {', '.join(self.colisiones[clave])}"
        if clave in self.resueltos:
            return True, "resuelta"
        return False, "cabecera no resuelta en este libro"


def _en_bloque_danos(columna: str) -> bool:
    return (letra_a_indice(PRIMERA_COLUMNA_DANOS)
            <= letra_a_indice(columna) <= letra_a_indice(ULTIMA_COLUMNA_DANOS))


def resolver_cabeceras(cabeceras: dict[str, str], fila: int = 7) -> InformeCabeceras:
    """Resuelve `{letra: texto}` leído de la fila de encabezados del libro.

    Orden de decisión:

    1. Bloque de daños (AI:BC): se reconoce como evaluación visual y **no** se
       rellena por OCR. Se admite por columna documentada y por forma (`9) …`).
    2. Catálogo del libro real (texto normalizado exacto).
    3. Alias genéricos (libros generados por el propio programa).
    4. Si nada coincide: **no resuelta**. Nunca se adivina.

    No adivina: lo que no pueda resolver con seguridad queda sin resolver.
    """
    informe = InformeCabeceras(fila=fila)
    for letra, texto in sorted(cabeceras.items(), key=lambda par: letra_a_indice(par[0])):
        columna = str(letra).upper()
        crudo = "" if texto is None else str(texto).strip()
        normalizado = normalizar_encabezado(crudo)
        entrada = Encabezado(columna=columna, texto=crudo)

        if not normalizado:
            entrada.estado = "estructural"
            entrada.motivo = "sin encabezado: columna estructural"
            informe.estructurales.append(columna)
            informe.encabezados.append(entrada)
            continue

        # 1 · bloque de daños
        if _en_bloque_danos(columna):
            del_catalogo = CATALOGO_LIBRO.get(normalizado)
            if del_catalogo and del_catalogo[1] == "dano":
                entrada.clave = del_catalogo[0]
            else:
                # el bloque AI:BC está documentado como catálogo de daños; dentro
                # de él, un encabezado con texto es una evaluación visual, numerada
                # o no ("Schusskanal mit Weissbruch", "Riss in Upperpart…")
                entrada.clave = f"dano_{columna.lower()}"
            entrada.estado = "dano"
            entrada.motivo = ("evaluación visual de daño: se reconoce, no se rellena por OCR"
                              if del_catalogo is None else
                              "evaluación visual de daño reconocida con clave del contrato")
            informe.encabezados.append(entrada)
            continue

        clave = None
        tipo = "campo"
        del_libro = CATALOGO_LIBRO.get(normalizado)
        if del_libro:
            clave, tipo = del_libro
        elif normalizado in ALIAS_ENCABEZADOS:
            clave = ALIAS_ENCABEZADOS[normalizado]

        documentada = COLUMNAS_DOCUMENTADAS.get(columna, "desconocida")
        if normalizado in DUPLICADOS_LIBRO:
            if documentada in DUPLICADOS_LIBRO[normalizado]:
                entrada.clave, entrada.estado = documentada, "resuelta"
                entrada.motivo = (f"texto repetido en el libro; resuelto por la columna "
                                  f"documentada {columna}")
            else:
                entrada.estado = "ambigua"
                entrada.motivo = (f"'{crudo.replace(chr(10), ' / ')[:28]}' aparece en varias "
                                  "columnas: sin la columna documentada no se puede decidir")
        elif clave == "__DUPLICADO__":
            if documentada in {"inflator_supplier", "dashboard_supplier"}:
                entrada.clave, entrada.estado = documentada, "resuelta"
                entrada.motivo = (f"texto repetido en el libro; resuelto por la columna "
                                  f"documentada {columna}")
            else:
                entrada.estado = "ambigua"
                entrada.motivo = ("'Lieferant/Supplier' existe en dos columnas: sin la "
                                  "columna documentada no se puede decidir")
        elif clave:
            if documentada == clave:
                entrada.clave, entrada.estado = clave, "resuelta"
            elif documentada in {"desconocida", None}:
                entrada.clave, entrada.estado = clave, "resuelta"
                entrada.motivo = f"resuelto por texto; la columna {columna} no es la documentada"
            else:
                entrada.estado = "ambigua"
                entrada.motivo = (f"el texto dice {clave} y la columna {columna} está documentada "
                                  f"como {documentada}: no se decide solo")
        elif _en_bloque_danos(columna):
            entrada.estado = "dano"
            entrada.clave = f"dano_{columna.lower()}"
            entrada.motivo = "evaluación visual de daño: se reconoce, no se rellena por OCR"
        else:
            entrada.motivo = "encabezado desconocido para el catálogo"
        informe.encabezados.append(entrada)

    # colisiones: dos columnas con el mismo campo
    por_clave: dict[str, list[str]] = {}
    for entrada in informe.encabezados:
        if entrada.estado == "resuelta" and entrada.clave:
            por_clave.setdefault(entrada.clave, []).append(entrada.columna)
    for clave, columnas in por_clave.items():
        if len(columnas) > 1:
            informe.colisiones[clave] = columnas
            for entrada in informe.encabezados:
                if entrada.clave == clave:
                    entrada.estado = "ambigua"
                    entrada.motivo = f"colisión: {clave} reclamado por {', '.join(columnas)}"
    return informe


def leer_cabeceras(hoja, fila: int = 7, primera: str = "A", ultima: str = "BC") -> dict[str, str]:
    """Lee la fila de encabezados de una hoja de openpyxl sin escribir nada."""
    cabeceras: dict[str, str] = {}
    for indice in range(letra_a_indice(primera), letra_a_indice(ultima) + 1):
        valor = hoja.cell(fila, indice).value
        cabeceras[indice_a_letra(indice)] = "" if valor is None else str(valor)
    return cabeceras


def _es_formula(valor) -> bool:
    return isinstance(valor, str) and valor.strip().startswith("=")


def escribir_valores(hoja, fila: int, valores: dict[str, object], informe: InformeCabeceras,
                     fila_encabezados: int = 7) -> dict[str, list[dict]]:
    """Escribe los valores en las columnas resueltas. No toca nada más.

    Devuelve `{"escritos": [...], "omitidos": [{clave, motivo}, ...]}`.
    """
    if fila == fila_encabezados:
        raise ValueError("No se escribe en la fila de encabezados.")
    resultado: dict[str, list[dict]] = {"escritos": [], "omitidos": []}
    for clave, valor in valores.items():
        if valor is None or valor == "":
            resultado["omitidos"].append({"clave": clave, "motivo": "sin valor"})
            continue
        puede, motivo = informe.puede_escribir(clave)
        if not puede:
            resultado["omitidos"].append({"clave": clave, "motivo": motivo})
            continue
        columna = informe.resueltos[clave]
        celda = hoja[f"{columna}{fila}"]
        if _es_formula(celda.value):
            resultado["omitidos"].append({"clave": clave, "motivo": "la celda contiene una fórmula"})
            continue
        celda.value = valor
        resultado["escritos"].append({"clave": clave, "celda": f"{columna}{fila}"})
    return resultado
