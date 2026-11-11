"""Protocolo de campos: decide si un texto leído PUEDE ir en esa celda (P12).

La idea, tomada de cómo se resuelve esto en industria (OCR de placas de características, MPN,
números de serie): un motor de OCR no se corrige pidiéndole más, se corrige **acotando la salida**
y **verificándola contra el formato del campo**:

1. **Gramática por campo** (estructura + longitud + qué tipo de carácter va en cada posición).
2. **Léxico**: valores que ya existen en el proyecto (catálogos cerrados: NT/RT/HT, 01S/02S, tipos
   de generador) — si el valor está en el léxico, se acepta; si está a una errata, se propone.
3. **Matriz de confusión**: pares que el motor confunde de verdad (O↔0, I↔1, S↔5, Z↔2, B↔8, G↔6,
   J↔4…). Se usa para *reparar* una lectura que, cambiando un solo carácter, pasa a ser válida.
   Se aprende de las correcciones humanas guardadas en `Trazabilidad` (texto OCR → texto corregido).
4. **Coherencia entre campos**: prefijo del número de parte igual en todo el proyecto, bloque fijo
   del número de serie, semana derivada de la fecha, número de prueba de 6 cifras ligado a la carpeta.
5. **Umbral por criticidad**: un número de serie exige confianza alta; un proveedor tolera menos.

Salida de `evaluar()`: `estado` ∈ {`valido`, `reparado`, `dudoso`, `invalido`} con `valor`, 
`confianza`, `motivo` y `alternativas`. Nunca «arregla» sin decirlo: cada reparación queda marcada.

Referencias de la técnica: validación por patrón y checksum por campo, restricción de la salida por
léxico, matriz de confusión + distancia de edición para elegir candidato, y umbrales de confianza
distintos para campos críticos (nº de serie ≥ 0,95; descriptivos ≥ 0,85).
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

# --------------------------------------------------------------------------------------------
# 1. Matriz de confusión (grupos de caracteres que el motor intercambia). Simétrica a propósito:
#    el mismo par sirve para O→0 y para 0→O.
# --------------------------------------------------------------------------------------------
GRUPOS_CONFUSION = [
    "0OQD", "1I L".replace(" ", ""), "2Z", "5S", "6Gb", "8B", "4A", "9g", "7T", "UV", "5$", "3B", "J4",
]
CONFUSION: dict[str, set[str]] = defaultdict(set)
for _grupo in GRUPOS_CONFUSION:
    for _caracter in _grupo:
        CONFUSION[_caracter] |= {c for c in _grupo if c != _caracter}
CONFUSION = dict(CONFUSION)


# --------------------------------------------------------------------------------------------
# 2. Gramática por campo: patrón, longitud, criticidad y si tiene catálogo cerrado.
#    Las longitudes salen de los datos reales del proyecto (2GJ.880.204.J = 14; 671 ZRZ0539991D = 15).
# --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Gramatica:
    patron: re.Pattern
    critico: bool = False
    catalogo: bool = False
    unico: bool = False     # el valor es distinto en cada caso (nº de serie): no cabe en un léxico
    prefijo: int = 0        # caracteres que deben coincidir con el resto del proyecto
    forma_legible: str = ""


def _g(patron: str, **kw) -> Gramatica:
    return Gramatica(re.compile(patron), **kw)


GRAMATICAS: dict[str, Gramatica] = {
    # número de parte estilo VW: 3 caracteres, tres grupos de 3 dígitos y letra final
    # número de parte estilo VW: 3 caracteres, tres grupos de 3 dígitos y **1 o 2 caracteres** al
    # final. Las variantes de PAB llevan dos (`2GJ.880.204.AB`, `4M0.880.204.AG`): con una sola
    # posición la variante buena se rechazaba y la celda quedaba vacía sin motivo.
    "module_part_number": _g(r"^[0-9A-Z]{3}\.\d{3}\.\d{3}\.[0-9A-Z]{1,2}$", critico=True,
                             forma_legible="3 caracteres + . + 3 dígitos + . + 3 dígitos + . + 1 o 2"),
    # el tablero puede venir con puntos (2GJ.857.003.G) o seguido (2GJ857003G)
    "dashboard_part_number": _g(r"^[0-9A-Z]{3}\.\d{3}\.\d{3}\.[0-9A-Z]{1,2}$"
                                r"|^[0-9A-Z]{3}[0-9A-Z]{5,10}$",
                                critico=True, forma_legible="ABC.123.456.J o ABC0008R662"),
    # número de serie: bloque fijo + espacio + 3 letras + 7 dígitos + letra
    # (en el libro completo hay una serie que termina en dígito —`671 ZRZ05399609`—, así que la
    #  última posición admite letra o dígito)
    "module_serial_number": _g(r"^\d{3} [A-Z]{3}\d{7}[A-Z0-9]$", critico=True, unico=True, prefijo=7,
                               forma_legible="3 dígitos, espacio, 3 letras, 7 dígitos y una letra"),
    # el del tablero **no** tiene la misma forma que el del módulo: `052 3KVJ008R6E` (10 caracteres
    # tras el espacio) o `052 3KVJ008R6J6` (11). La cola empieza por letra y mide 3 o 4.
    "dashboard_serial_number": _g(r"^\d{3} [A-Z0-9]{3}J\d{3}[A-Z][A-Z0-9]{2,3}$", critico=True,
                                  unico=True, prefijo=7,
                                  forma_legible="3 dígitos, espacio, 3 caracteres, J, 3 dígitos y cola"),
    # niveles de ingeniería: dos dígitos y una letra (02S, 16S, 66K)
    "engineering_level": _g(r"^\d{2}[A-Z]$", catalogo=True, forma_legible="dos dígitos y una letra"),
    # variante del módulo (`PAB · Variante`): tres letras, RDW en todo el proyecto
    "module_version": _g(r"^[A-Z]{3}$", catalogo=True, forma_legible="RDW / NAR / ROW (tres letras)"),
    "dashboard_engineering_level": _g(r"^\d{2}[A-Z]$", catalogo=True,
                                      forma_legible="dos dígitos y una letra"),
    # catálogos cerrados
    "temperature_condition": _g(r"^(NT|RT|HT|KT)$", catalogo=True, forma_legible="NT / RT / HT"),
    "inflator_type": _g(r"^[NOU]GL$|^NOM$", catalogo=True,
                        forma_legible="NOM / OGL / UGL"),
    # número de prueba: 6 cifras, sin cero inicial
    "test_number": _g(r"^[1-9]\d{5}$", critico=True, forma_legible="6 cifras"),
    # apertura láser: marca simple en la etiqueta
    # el libro real escribe tanto la marca (X/O) como la medida («3mm ¨C¨»): las dos valen
    "laser_opening": _g(r"^[XO0-]$|^\d+\s?mm", catalogo=True,
                        forma_legible="X (abierta), O (cerrada) o la medida, p. ej. «3mm ¨C¨»"),
    # proveedores: texto corto, sin dígitos sueltos al principio
    "inflator_supplier": _g(r"^[A-Za-z][A-Za-z .&/-]{1,38}$", forma_legible="nombre del proveedor (Autoliv)"),
    "dashboard_supplier": _g(r"^[A-Za-z][A-Za-z .&/-]{1,38}$", forma_legible="nombre del proveedor (FORVIA)"),
    # fechas: ISO o día.mes.año (etiquetas alemanas)
    "test_date": _g(r"^\d{4}-\d{2}-\d{2}$", critico=True, forma_legible="AAAA-MM-DD"),
    "module_date": _g(r"^\d{4}-\d{2}-\d{2}$", forma_legible="AAAA-MM-DD"),
    "dashboard_date": _g(r"^\d{4}-\d{2}-\d{2}$", forma_legible="AAAA-MM-DD"),
    # derivadas
    "week": _g(r"^\d{4}-W\d{2}$", forma_legible="AAAA-Wnn (semana ISO)"),
    # el motivo lo escribe a mano quien monta la prueba: llega en mayúsculas, pero también con
    # paréntesis, comillas o acentos (`BMG (NOM)`, `-35°C "BMG"`); se normaliza antes de comparar
    "test_reason": _g(r"^[A-Z0-9][A-Z0-9 .&/,\-()]{1,40}$", forma_legible="motivo de la prueba"),
    "test_place": _g(r"^[A-Z][A-Za-z .&/-]{1,38}$", forma_legible="lugar de la prueba"),
    "delay_ms": _g(r"^(\d{1,4}|--)$", forma_legible="milisegundos (entero)"),
}

# Umbral de confianza exigido para escribir solo, por criticidad.
UMBRAL = {"critico": 0.90, "normal": 0.75}

# Campos que comparten léxico: un nivel visto como `_nivel_por_identificar` vale para la columna
# del módulo o la del tablero; un número de parte visto en el módulo informa al del tablero.
FAMILIA = {
    "engineering_level": "nivel", "dashboard_engineering_level": "nivel",
    "_nivel_por_identificar": "nivel",
    "module_part_number": "parte", "dashboard_part_number": "parte",
    "module_serial_number": "serie", "dashboard_serial_number": "serie",
    "_serial_por_identificar": "serie",
    "inflator_supplier": "proveedor", "dashboard_supplier": "proveedor",
    "module_date": "fecha", "dashboard_date": "fecha", "test_date": "fecha",
    "_fecha_ambigua": "fecha", "_fecha_por_identificar": "fecha",
    "_proyecto_designacion": "parte",
}
ANIO_MINIMO, ANIO_MAXIMO = 2020, 2030


SIN_ACENTOS = str.maketrans("ÁÉÍÓÚÜÑáéíóúüñ", "AEIOUUNaeiouun")


def normalizar_por_campo(campo: str, texto: str) -> str:
    """Lleva el valor a la forma en que se compara, **sin cambiar lo que dice**.

    - Números de parte: mayúsculas y puntos. La etiqueta los imprime con espacios
      (`2GJ 880 204 J`) y el libro con puntos (`2GJ.880.204.J`); sin esto, la lectura correcta no
      pasaba la gramática y la celda se quedaba vacía.
    - Motivo de la prueba: mayúsculas y sin acentos (`Certificación` → `CERTIFICACION`), porque el
      campo los admite pero el libro los escribe en mayúsculas.
    """
    if not texto:
        return texto
    if campo.endswith("part_number"):
        limpio = re.sub(r"\s+", " ", texto.upper()).strip()
        if "." not in limpio:
            compacto = limpio.replace(" ", "")
            if re.fullmatch(r"[0-9A-Z]{3}\d{3}\d{3}[0-9A-Z]{1,2}", compacto):
                return f"{compacto[:3]}.{compacto[3:6]}.{compacto[6:9]}.{compacto[9:]}"
            # tres bloques separados por espacios: `2GJ 880 204 J` / `2GJ 880 204 AB`
            trozos = limpio.split(" ")
            if len(trozos) == 4 and re.fullmatch(r"[0-9A-Z]{3}", trozos[0]) \
                    and all(re.fullmatch(r"\d{3}", t) for t in trozos[1:3]) \
                    and re.fullmatch(r"[0-9A-Z]{1,2}", trozos[3]):
                return ".".join(trozos)
        return limpio
    if campo == "test_reason":
        return re.sub(r"\s+", " ", texto.upper().translate(SIN_ACENTOS)).strip()
    return texto


def limpiar(texto) -> str:
    """Normaliza sin destruir la estructura: NFKC, espacios simples, mayúsculas de campo."""
    if texto is None:
        return ""
    t = unicodedata.normalize("NFKC", str(texto)).replace("\u00a0", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t


# --------------------------------------------------------------------------------------------
# 3. Léxico aprendido: valores que el proyecto ya ha confirmado (por campo).
# --------------------------------------------------------------------------------------------
def aprender_lexico(valores_por_campo: dict[str, Counter], minimo: int = 2,
                    cuota_minima: float = 0.05) -> dict[str, set[str]]:
    """Léxico por FAMILIA, construido sólo con valores que cumplen la gramática y se repiten.

    Un valor leído una sola vez, o que no pasa la gramática, **no entra** en el léxico: así una
    lectura basura no se convierte en «verdad del proyecto». Para el número de prueba se puede
    sembrar además con los identificadores de carpeta (`sembrar_test_number`).
    """
    por_familia: dict[str, Counter] = defaultdict(Counter)
    for campo, votos in valores_por_campo.items():
        familia = FAMILIA.get(campo, campo)
        gramatica = GRAMATICAS.get(campo)
        for valor, n in Counter(votos).items():
            limpio = limpiar(valor)
            if not limpio:
                continue
            if familia == "fecha":
                normalizada = normalizar_fecha(limpio)
                if normalizada:
                    por_familia[familia][normalizada] += n
                continue
            if gramatica and not gramatica.patron.match(limpio):
                continue
            por_familia[familia][limpio] += n
    filtrado: dict[str, Counter] = {}
    for familia, votos in por_familia.items():
        total = sum(votos.values()) or 1
        filtrado[familia] = Counter({v: n for v, n in votos.items()
                                     if n >= minimo and n / total >= cuota_minima})
    return colapsar_variantes(filtrado)


def colapsar_variantes(lexico: dict[str, set[str]] | dict[str, Counter],
                       umbral: float = 0.8) -> dict[str, set[str]]:
    """Deja un solo representante por grupo de valores casi idénticos (el más repetido).

    Evita que `26J.880.204.J` (2 lecturas) conviva en el léxico con `2GJ.880.204.J` (13): dos
    variantes de la misma etiqueta no son dos verdades distintas, y la que gana es la mayoritaria.
    """
    from difflib import SequenceMatcher
    salida: dict[str, set[str]] = {}
    for familia, valores in lexico.items():
        conteo = Counter(valores) if not isinstance(valores, Counter) else valores
        ordenados = [v for v, _ in conteo.most_common()]   # el más repetido manda
        grupos: list[list[str]] = []
        for valor in ordenados:
            for grupo in grupos:
                if SequenceMatcher(None, valor, grupo[0]).ratio() >= umbral:
                    grupo.append(valor)
                    break
            else:
                grupos.append([valor])
        salida[familia] = {grupo[0] for grupo in grupos}   # representante = el más frecuente
    return salida


def perfil_proyecto(valores_por_campo: dict[str, Counter]) -> dict[str, str]:
    """Prefijo dominante por familia para los campos únicos (nº de serie, designación)."""
    por_familia: dict[str, Counter] = defaultdict(Counter)
    for campo, votos in valores_por_campo.items():
        familia = FAMILIA.get(campo, campo)
        gramatica = GRAMATICAS.get(campo)
        if not gramatica or not gramatica.prefijo:
            continue
        for valor, n in Counter(votos).items():
            limpio = limpiar(valor)
            if gramatica.patron.match(limpio):
                por_familia[familia][limpio[:gramatica.prefijo]] += n
    return {familia: votos.most_common(1)[0][0] for familia, votos in por_familia.items() if votos}


def sembrar_test_number(lexico: dict[str, set[str]], casos) -> None:
    """El identificador de la carpeta es la fuente más fiable del número de prueba."""
    lexico.setdefault("test_number", set()).update(
        {c for c in casos if c and re.fullmatch(r"[1-9]\d{5}", str(c))})


def matriz_confusion(pares: list[tuple[str, str]]) -> dict[tuple[str, str], int]:
    """Cuenta sustituciones observadas entre el texto OCR y el texto corregido a mano."""
    cuenta: Counter = Counter()
    for original, corregido in pares:
        a, b = limpiar(original), limpiar(corregido)
        if not a or not b or a == b or len(a) != len(b):
            continue
        for x, y in zip(a, b):
            if x != y:
                cuenta[(x, y)] += 1
    return dict(cuenta)


# --------------------------------------------------------------------------------------------
# 4. Evaluación
# --------------------------------------------------------------------------------------------
@dataclass
class Veredicto:
    campo: str
    valor: str
    estado: str                # valido | reparado | dudoso | invalido
    confianza: float
    motivo: str
    alternativas: list[str] = field(default_factory=list)

    @property
    def escribible(self) -> bool:
        return self.estado in ("valido", "reparado") and self.confianza >= UMBRAL[
            "critico" if GRAMATICAS.get(self.campo, Gramatica(re.compile(".*"))).critico else "normal"]

    def as_dict(self) -> dict:
        return {"campo": self.campo, "valor": self.valor, "estado": self.estado,
                "confianza": round(self.confianza, 2), "motivo": self.motivo,
                "alternativas": self.alternativas, "escribible": self.escribible}


MESES = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
         "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def normalizar_fecha(texto) -> str | None:
    """Lleva una fecha de etiqueta a ISO. Reconoce día.mes.año, día/mes/año, día-mes-año e ISO.

    No inventa el orden: si el día y el mes son ambos ≤ 12 la lectura es ambigua y se devuelve
    igualmente en orden día.mes (etiquetas alemanas), pero el llamador puede marcarla como inferida.
    """
    limpio = limpiar(texto).replace("/", ".").replace("-", ".").replace(" ", ".")
    m = re.fullmatch(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", limpio)
    if m:
        anio, mes, dia = (int(g) for g in m.groups())
    else:
        m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})", limpio)
        if m:
            dia, mes, anio = (int(g) for g in m.groups())
            anio = 2000 + anio if anio < 100 else anio
        else:
            m = re.fullmatch(r"(\d{1,2})\.([A-Za-z]{3})\.?(\d{2,4})?", limpio)
            if not m or m.group(2).lower() not in MESES:
                return None
            dia, mes = int(m.group(1)), MESES[m.group(2).lower()]
            anio = int(m.group(3) or 0)
            anio = (2000 + anio if anio < 100 else anio) if anio else date.today().year
    try:
        f = date(anio, mes, dia)
    except ValueError:
        return None
    return f.isoformat() if 2000 <= f.year <= 2100 else None


def _fecha_valida(texto: str) -> date | None:
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", texto)
    if not m:
        return None
    try:
        f = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return f if ANIO_MINIMO <= f.year <= ANIO_MAXIMO else None


def _candidatos_por_sustitucion(valor: str, patron: re.Pattern) -> set[str]:
    salida = set()
    for i, c in enumerate(valor):
        for alterno in CONFUSION.get(c, ()):  # sólo los confundibles declarados
            prueba = valor[:i] + alterno + valor[i + 1:]
            if patron.match(prueba):
                salida.add(prueba)
    return salida


def _candidatos_por_longitud(valor: str, patron: re.Pattern, lexico: set[str]) -> set[str]:
    """Recupera una lectura a la que le falta o le sobra un carácter, usando el léxico.

    Es lo que pasa con `GJ.880.204.J`: falta el primer carácter del número de parte. Se prueba
    el carácter dominante del léxico en las posiciones extremas; si el resultado es único en el
    léxico del proyecto, se acepta como reparación (no como lectura firme).
    """
    salida = set()
    if not lexico:
        return salida
    prefijos = {v[0] for v in lexico if len(v) == len(valor) + 1}
    sufijos = {v[-1] for v in lexico if len(v) == len(valor) + 1}
    for c in prefijos:
        prueba = c + valor
        if patron.match(prueba) and prueba in lexico:
            salida.add(prueba)
    for c in sufijos:
        prueba = valor + c
        if patron.match(prueba) and prueba in lexico:
            salida.add(prueba)
    if len(valor) + 1 in {len(v) for v in lexico}:
        # perfil posicional: qué carácter tiene el proyecto en cada posición
        perfil: dict[int, Counter] = defaultdict(Counter)
        for conocido in lexico:
            if len(conocido) == len(valor) + 1:
                for i, c in enumerate(conocido):
                    perfil[i][c] += 1
        for i in range(len(valor) + 1):
            for c in [x for x, _ in perfil[i].most_common(3)]:
                prueba = valor[:i] + c + valor[i:]
                if patron.match(prueba) and prueba in lexico:
                    salida.add(prueba)
    if len(valor) > 3:  # ¿sobra un carácter?
        for i in range(len(valor)):
            prueba = valor[:i] + valor[i + 1:]
            if patron.match(prueba) and prueba in lexico:
                salida.add(prueba)
    return salida


def evaluar(campo: str, valor, lexico: dict[str, set[str]] | None = None,
            votos: int = 1, total_votos: int = 1,
            confusion: dict[tuple[str, str], int] | None = None,
            perfil: dict[str, str] | None = None) -> Veredicto:
    """Veredicto sobre un texto candidato para un campo."""
    lexico = lexico or {}
    perfil = perfil or {}
    texto = normalizar_por_campo(campo, limpiar(valor))
    gramatica = GRAMATICAS.get(campo)
    if gramatica is None:                      # campo sin protocolo: se acepta tal cual, marcado
        return Veredicto(campo, texto, "valido" if texto else "invalido", 0.5,
                         "campo sin gramática definida")
    if not texto:
        return Veredicto(campo, "", "invalido", 0.0, "vacío")

    apoyo = votos / max(1, total_votos)        # cuánto consenso hay entre lecturas
    conocidos = lexico.get(campo) or lexico.get(FAMILIA.get(campo, ""), set())

    # 1) ya cumple la forma
    if gramatica.patron.match(texto):
        if gramatica.unico:
            # el valor cambia en cada caso: se valida estructura + coherencia del prefijo
            prefijo_esperado = (perfil or {}).get(FAMILIA.get(campo, campo))
            if prefijo_esperado and not texto.startswith(prefijo_esperado):
                return Veredicto(campo, texto, "dudoso", 0.5,
                                 f"empieza por «{texto[:gramatica.prefijo]}» y el resto del "
                                 f"proyecto por «{prefijo_esperado}»")
            return Veredicto(campo, texto, "valido", 0.82 + 0.15 * apoyo,
                             f"cumple la estructura y el prefijo del proyecto "
                             f"(«{prefijo_esperado or '—'}»)")
        if campo in ("test_date", "module_date", "dashboard_date") and not _fecha_valida(texto):
            return Veredicto(campo, texto, "invalido", 0.0, "la fecha no existe o está fuera de rango")
        if conocidos and texto in conocidos:
            return Veredicto(campo, texto, "valido", 0.95 + 0.05 * apoyo,
                             "cumple la forma y está en el léxico del proyecto")
        if conocidos and texto not in conocidos and (gramatica.catalogo or gramatica.critico):
            # ¿es una variante de un valor que sí conocemos? (una errata, no un valor nuevo)
            cercanos = {v for v in conocidos
                        if sum(1 for a, b in zip(texto, v) if a != b) == 1 and len(texto) == len(v)}
            if len(cercanos) == 1:
                nuevo = cercanos.pop()
                return Veredicto(campo, nuevo, "reparado", 0.92,
                                 f"«{texto}» difiere en un carácter de «{nuevo}», que es el valor "
                                 f"del proyecto")
            return Veredicto(campo, texto, "dudoso", 0.55,
                             "cumple la forma pero no se ha visto antes en el proyecto",
                             sorted(conocidos)[:5])
        return Veredicto(campo, texto, "valido", 0.80 + 0.15 * apoyo,
                         f"cumple la forma ({gramatica.forma_legible})")

    # 2) reparable cambiando un solo carácter confundible.
    #    Se restringe al léxico del proyecto: la corrección que coincide con un valor ya conocido
    #    gana sobre cualquier otra que sólo «encaje en la forma» (salida acotada por léxico).
    reparados = _candidatos_por_sustitucion(texto, gramatica.patron)
    confirmados = {v for v in reparados if v in conocidos}
    if len(confirmados) == 1:
        nuevo = confirmados.pop()
        return Veredicto(campo, nuevo, "reparado", 0.92,
                         f"se corrigió un carácter confundible y el resultado es un valor ya "
                         f"conocido del proyecto: «{texto}» → «{nuevo}»")
    if len(reparados) == 1:
        nuevo = reparados.pop()
        peso = 0.05
        if confusion:
            total = sum(confusion.values()) or 1
            peso = min(0.2, 3 * confusion.get(
                (next((a for a, b in zip(texto, nuevo) if a != b), ""),
                 next((b for a, b in zip(texto, nuevo) if a != b), "")), 0) / total)
        # si el par (a→b) aparece en las correcciones humanas, la reparación es fiable
        par = tuple(x for x, y in zip(texto, nuevo) if x != y)
        visto = bool(confusion) and any((a_, b_) in confusion for a_ in par for b_ in par)
        confianza = min(0.95, 0.86 + peso + 0.05 * apoyo) if visto else min(0.88, 0.72 + peso + 0.08 * apoyo)
        return Veredicto(campo, nuevo, "reparado", confianza,
                         f"se corrigió un carácter confundible: «{texto}» → «{nuevo}»")
    if len(reparados) > 1:
        return Veredicto(campo, texto, "dudoso", 0.4,
                         "hay varias formas válidas al corregir un carácter", sorted(reparados)[:5])

    # 3) reparable por longitud (falta o sobra un carácter) usando el léxico del proyecto
    por_longitud = _candidatos_por_longitud(texto, gramatica.patron, conocidos)
    if len(por_longitud) == 1:
        nuevo = por_longitud.pop()
        return Veredicto(campo, nuevo, "reparado", 0.90,
                         f"faltaba o sobraba un carácter frente a «{nuevo}», ya conocido en el proyecto")
    if len(por_longitud) > 1:
        return Veredicto(campo, texto, "dudoso", 0.4, "varias reparaciones posibles",
                         sorted(por_longitud)[:5])

    # 4) no encaja: se explica por qué, para que la persona sepa qué mirar
    return Veredicto(campo, texto, "invalido", 0.0,
                     f"no cumple la forma esperada ({gramatica.forma_legible})")


def elegir_mejor(campo: str, votos: Counter, lexico=None, confusion=None, perfil=None) -> Veredicto:
    """Entre varias lecturas del mismo campo, elige la mejor aplicando el protocolo."""
    if not votos:
        return Veredicto(campo, "", "invalido", 0.0, "sin lecturas")
    total = sum(votos.values())
    evaluados = [evaluar(campo, valor, lexico, n, total, confusion, perfil)
                 for valor, n in votos.items()]
    orden = {"valido": 3, "reparado": 2, "dudoso": 1, "invalido": 0}
    evaluados.sort(key=lambda v: (orden[v.estado], v.confianza, votos.get(v.valor, 0)), reverse=True)
    mejor = evaluados[0]
    empatados = [v for v in evaluados if v.estado == mejor.estado and abs(v.confianza - mejor.confianza) < 1e-9]
    if len(empatados) > 1 and votos.get(empatados[0].valor, 0) == votos.get(empatados[1].valor, 0):
        return Veredicto(campo, mejor.valor, "dudoso", 0.45,
                         "dos lecturas igual de buenas: decide una persona",
                         [v.valor for v in empatados][:5])
    return mejor


def coherencia(campo: str, valor: str, contexto: dict) -> Veredicto | None:
    """Comprobaciones que cruzan campos. Devuelve veredicto si hay algo que decir."""
    if campo == "week" and "test_date" in contexto:
        f = _fecha_valida(contexto["test_date"])
        if f:
            anio, semana, _ = f.isocalendar()
            esperado = f"{anio}-W{semana:02d}"
            if valor and valor != esperado:
                return Veredicto("week", valor, "invalido", 0.0,
                                 f"la semana de {contexto['test_date']} es {esperado}")
    if campo == "test_number" and "carpeta" in contexto and contexto["carpeta"]:
        if valor and valor != contexto["carpeta"]:
            return Veredicto("test_number", valor, "dudoso", 0.5,
                             f"el nombre de la carpeta dice {contexto['carpeta']}")
    return None
