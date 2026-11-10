"""Rescate de columnas: escribe en el libro lo que la Trazabilidad YA leyó (P12).

El diagnóstico sobre el libro real (16.0.24) dice que de 20 columnas sólo se llenan 6-7 y que
13 no tienen ninguna lectura en todo el proyecto. Pero la hoja `Trazabilidad` sí guarda valores
para columnas que luego quedan vacías: `_nivel_por_identificar`, `_fecha_ambigua`,
`inflator_type`, `module_serial_number`, `module_part_number`.

Este módulo los lleva a su columna sin tocar nada que ya esté escrito:

- **nunca sobrescribe** una celda ocupada;
- **exige mayoría** entre las lecturas del caso (empate → no escribe);
- **valida la forma** antes de escribir;
- deja constancia del **origen** de cada celda (qué campo, cuántas lecturas, con qué regla).

No inventa: si el dato no está leído en la Trazabilidad, la celda sigue vacía.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime

from utilidades.protocolo_campos import elegir_mejor, evaluar
from utilidades.validacion_formas import normalizar, revisar_forma

# campo del libro -> campos de la Trazabilidad que pueden alimentarlo, en orden de preferencia
FUENTES = {
    "test_number": ("test_number",),
    "temperature_condition": ("temperature_condition",),
    "module_version": ("module_version",),
    "module_part_number": ("module_part_number",),
    "module_serial_number": ("module_serial_number", "_serial_por_identificar"),
    "engineering_level": ("engineering_level", "_nivel_por_identificar"),
    "inflator_type": ("inflator_type",),
    # la fecha de PRUEBA nunca se toma de la etiqueta del módulo: la etiqueta lleva la fecha de
    # FABRICACIÓN. Se resuelve por contexto de imagen en `resolver_fechas`.
    "test_date": ("test_date", "_fecha_por_identificar"),
    "module_date": ("module_date",),
    "opening_time_ms": ("opening_time_ms",),
}
# columnas del libro que se pueden derivar de otra ya confirmada
DERIVADAS = {"week": ("test_date",)}

# Campos que, leídos en la misma imagen, delatan que esa foto es la etiqueta del módulo (y por
# tanto que la fecha impresa ahí es la de fabricación, no la de la prueba).
CAMPOS_ETIQUETA = {"module_serial_number", "module_part_number", "engineering_level",
                   "_nivel_por_identificar", "_proyecto_designacion"}


def fechas_por_contexto(hoja, col_caso: int = 3, col_campo: int = 5, col_imagen: int = 6,
                        col_original: int = 8, col_corregido: int = 9) -> dict[str, dict[str, Counter]]:
    """Separa las fechas leídas según la imagen: `etiqueta` (fabricación) vs `documento` (prueba).

    Una foto que además trae número de serie, número de parte o nivel de ingeniería es la etiqueta
    del módulo: su fecha es la de fabricación. Las demás fechas (hoja de prueba, informe, tablero)
    se agrupan como documento. Es la desambiguación que faltaba para que `PAB · Fecha fabricación`
    deje de estar vacía y para no poner la fecha de fabricación como fecha de prueba.
    """
    campos_por_imagen: dict[tuple[str, str], set[str]] = {}
    filas = []
    for fila in range(2, hoja.max_row + 1):
        caso = hoja.cell(fila, col_caso).value
        campo = str(hoja.cell(fila, col_campo).value or "").strip().lower()
        imagen = hoja.cell(fila, col_imagen).value
        valor = hoja.cell(fila, col_corregido).value or hoja.cell(fila, col_original).value
        if not caso or not campo:
            continue
        numero = _caso_de(caso)
        if imagen:
            campos_por_imagen.setdefault((numero, str(imagen)), set()).add(campo)
        filas.append((numero, campo, str(imagen or ""), normalizar(valor) if valor else ""))
    salida: dict[str, dict[str, Counter]] = {}
    for numero, campo, imagen, valor in filas:
        if not valor:
            continue
        if campo in ("test_date", "_fecha_por_identificar"):
            fecha, _ = _fecha(valor)
            if fecha:
                salida.setdefault(numero, {"etiqueta": Counter(), "documento": Counter(),
                                           "documento_iso": Counter()})["documento_iso"][fecha] += 1
            continue
        if campo not in ("_fecha_ambigua", "module_date", "dashboard_date"):
            continue
        if campo == "test_date":
            continue
        fecha, _ = _fecha(valor)
        if not fecha:
            continue
        es_etiqueta = bool(campos_por_imagen.get((numero, imagen), set()) & CAMPOS_ETIQUETA)
        destino = "etiqueta" if es_etiqueta else "documento"
        salida.setdefault(numero, {"etiqueta": Counter(), "documento": Counter(),
                                   "documento_iso": Counter()})[destino][fecha] += 1
    return salida

MESES = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
         "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def _caso_de(caso: str) -> str:
    partes = str(caso).split("|")
    return partes[2] if len(partes) > 2 else str(caso)


def _fecha(texto: str) -> tuple[date | None, str]:
    """Interpreta la fecha de la etiqueta. Devuelve (fecha, regla).

    Las etiquetas del proyecto son alemanas (dirección de Dachau, «Made in»), así que el orden
    es día.mes.año; se marca como `inferido` cuando el día es ≤12 y la lectura sería ambigua.
    """
    crudo = normalizar(texto)
    iso = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", crudo)   # primero ISO (AAAA-MM-DD)
    if iso:
        anio, mes, dia = (int(g) for g in iso.groups())
        try:
            return date(anio, mes, dia), "iso"
        except ValueError:
            return None, "fecha_imposible"
    limpio = crudo.replace("/", ".").replace("-", ".").replace(" ", ".")
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})", limpio)
    if m:
        dia, mes, anio = (int(g) for g in m.groups())
        anio = 2000 + anio if anio < 100 else anio
        regla = "etiqueta_dia.mes.año"
        if dia <= 12 and mes <= 12:
            regla = "inferido_dia.mes.año"
        try:
            return date(anio, mes, dia), regla
        except ValueError:
            return None, "fecha_imposible"
    m = re.fullmatch(r"(\d{1,2})[.\s]([A-Za-z]{3})[.\s]?(\d{2,4})", normalizar(texto))
    if m and m.group(2).lower() in MESES:
        dia, anio = int(m.group(1)), int(m.group(3))
        anio = 2000 + anio if anio < 100 else anio
        try:
            return date(anio, MESES[m.group(2).lower()], dia), "etiqueta_dia.mes_letra"
        except ValueError:
            return None, "fecha_imposible"
    return None, "no_reconocida"


def leer_trazabilidad(hoja) -> dict[str, dict[str, Counter]]:
    """{caso: {campo: Counter({valor: nº de filas})}} desde la hoja Trazabilidad."""
    cabeceras = {str(hoja.cell(1, c).value).strip().lower(): c for c in range(1, hoja.max_column + 1)}
    col_caso = cabeceras.get("caso", 3)
    col_campo = cabeceras.get("campo", 5)
    col_corregido = cabeceras.get("texto corregido", 9)
    col_original = cabeceras.get("texto ocr original", 8)
    datos: dict[str, dict[str, Counter]] = {}
    for fila in range(2, hoja.max_row + 1):
        caso = hoja.cell(fila, col_caso).value
        # los nombres de campo se comparan en minúsculas (normalizar() los pondría en mayúsculas)
        campo = str(hoja.cell(fila, col_campo).value or "").strip().lower()
        if not caso or not campo:
            continue
        valor = hoja.cell(fila, col_corregido).value or hoja.cell(fila, col_original).value
        valor = normalizar(valor) if valor is not None else ""
        if not valor:
            continue
        datos.setdefault(_caso_de(caso), {}).setdefault(campo, Counter())[valor] += 1
    return datos


def elegir(votos: Counter, campo: str) -> tuple[str | None, int, str]:
    """Valor con mayoría estricta y forma válida. Devuelve (valor, votos, motivo)."""
    if not votos:
        return None, 0, "sin_lectura"
    ordenados = votos.most_common()
    valor, veces = ordenados[0]
    if len(ordenados) > 1 and ordenados[0][1] == ordenados[1][1]:
        return None, veces, "empate"
    if not revisar_forma(campo, valor)["valido"]:
        return None, veces, "forma_invalida"
    return valor, veces, "mayoria"


def planificar(hoja, trazabilidad: dict[str, dict[str, Counter]], columnas: dict[str, int],
               fila_encabezado: int = 7, primera_fila: int = 8,
               contexto: dict | None = None) -> list[dict]:
    """`contexto` trae léxico, perfil y matriz de confusión del protocolo; si falta, se usa la
    validación de forma antigua (compatible con lo que ya había)."""
    contexto = contexto or {}
    """Qué celdas se pueden rellenar, con su origen. No modifica nada."""
    plan = []
    for fila in range(primera_fila, hoja.max_row + 1):
        numero = normalizar(hoja.cell(fila, columnas.get("test_number", 3)).value)
        if not numero.isdigit():
            continue
        fuentes = trazabilidad.get(numero) or {}
        fechas: list[date] = []
        for campo, columna in columnas.items():
            if campo not in FUENTES:
                continue
            actual = hoja.cell(fila, columna).value
            if actual not in (None, ""):
                continue
            valor = origen = regla = None
            votos_totales = 0
            for fuente in FUENTES[campo]:
                votos = fuentes.get(fuente)
                if not votos:
                    continue
                if campo == "test_date":
                    por_fecha = Counter()
                    for texto, n in votos.items():
                        f, regla_f = _fecha(texto)
                        if f:
                            por_fecha[f] += n
                    if por_fecha:
                        mejor, veces = por_fecha.most_common(1)[0]
                        if len(por_fecha) > 1 and por_fecha.most_common(2)[0][1] == por_fecha.most_common(2)[1][1]:
                            continue
                        veredicto = evaluar("test_date", mejor.isoformat(), contexto.get("lexico"),
                                            veces, sum(por_fecha.values()),
                                            contexto.get("confusion"), contexto.get("perfil"))
                        if not veredicto.escribible:
                            continue
                        valor, votos_totales, regla = veredicto.valor, veces, regla_f
                        origen = fuente
                        fechas.append(mejor)
                        break
                    continue
                if contexto.get("lexico") is not None:
                    veredicto = elegir_mejor(campo, votos, contexto.get("lexico"),
                                             contexto.get("confusion"), contexto.get("perfil"))
                    if veredicto.escribible:
                        valor = (veredicto.valor, sum(votos.values()), fuente,
                                 f"{veredicto.estado}:{veredicto.motivo[:60]}")
                        valor, votos_totales, origen, regla = valor
                        break
                    continue
                candidato, veces, motivo = elegir(votos, campo)
                if candidato:
                    valor, votos_totales, origen, regla = candidato, veces, fuente, "mayoria"
                    break
            if valor:
                plan.append({"caso": numero, "fila": fila, "campo": campo, "columna": columna,
                             "valor": valor, "origen": origen, "votos": votos_totales, "regla": regla})
    # ventana de plausibilidad del proyecto para fechas de fabricación
    todas = [f for v in (contexto.get("fechas") or {}).values()
             for bolsa in ("documento_iso", "documento") for f in (v.get(bolsa) or {})]
    if todas:
        # referencia robusta: la fecha más repetida en los documentos, no el mínimo ni el máximo
        # (una lectura basura como 2045-01-09 no puede abrir la ventana de todo el proyecto)
        referencia = Counter(todas).most_common(1)[0][0]
        limite_inferior = date(referencia.year - 2, referencia.month, referencia.day)
        limite_superior = date(referencia.year + 1, referencia.month, referencia.day)
    else:
        limite_inferior = limite_superior = None

    # fechas resueltas por contexto de imagen (fabricación en la etiqueta, prueba en el documento)
    for fila in range(primera_fila, hoja.max_row + 1):
        numero = normalizar(hoja.cell(fila, columnas.get("test_number", 3)).value)
        if not numero.isdigit():
            continue
        contexto_fechas = (contexto.get("fechas") or {}).get(numero) or {}
        for campo, bolsa in (("module_date", "etiqueta"), ("test_date", "documento")):
            columna = columnas.get(campo)
            if not columna or hoja.cell(fila, columna).value not in (None, ""):
                continue
            votos = Counter()
            if campo == "test_date" and contexto_fechas.get("documento_iso"):
                votos = Counter(contexto_fechas["documento_iso"])
            if not votos:
                votos = contexto_fechas.get(bolsa) or Counter()
            if not votos:
                continue
            ordenados = votos.most_common(2)
            if len(ordenados) > 1 and ordenados[0][1] == ordenados[1][1]:
                continue                      # empate: no se escribe
            fecha, veces = ordenados[0]
            if campo == "module_date":
                prueba = hoja.cell(fila, columnas.get("test_date", 4)).value
                prueba = (date.fromisoformat(prueba) if isinstance(prueba, str)
                          and re.fullmatch(r"\d{4}-\d{2}-\d{2}", prueba) else None)
                if prueba is None:
                    prueba = next((p["valor"] for p in plan
                                   if p["fila"] == fila and p["campo"] == "test_date"), None)
                    prueba = date.fromisoformat(prueba) if prueba else None
                if prueba and not (date(prueba.year - 3, prueba.month, prueba.day) <= fecha <= prueba):
                    continue      # fuera de la ventana: se descarta
                if prueba is None and limite_inferior and not (
                        limite_inferior <= fecha <= limite_superior):
                    continue      # sin fecha de prueba: se usa la ventana de todo el proyecto
            veredicto = evaluar(campo, fecha.isoformat(), contexto.get("lexico"), veces,
                                sum(votos.values()), contexto.get("confusion"), contexto.get("perfil"))
            if not veredicto.escribible:
                continue
            plan.append({"caso": numero, "fila": fila, "campo": campo, "columna": columna,
                         "valor": fecha.isoformat(), "origen": f"fecha_en_{bolsa}",
                         "votos": veces, "regla": f"{veredicto.estado}:{veredicto.motivo[:60]}"})
            if campo == "test_date":
                fechas.append(fecha)

    # derivadas: semana ISO a partir de la fecha de prueba (escrita o ya presente)
    for fila in range(primera_fila, hoja.max_row + 1):
        numero = normalizar(hoja.cell(fila, columnas.get("test_number", 3)).value)
        if not numero.isdigit() or "week" not in columnas:
            continue
        if hoja.cell(fila, columnas["week"]).value not in (None, ""):
            continue
        fecha = None
        actual = hoja.cell(fila, columnas.get("test_date", 4)).value
        if isinstance(actual, (date, datetime)):
            fecha = actual.date() if isinstance(actual, datetime) else actual
        elif actual:
            fecha, _ = _fecha(str(actual))
        if fecha is None:
            fecha = next((p["valor"] for p in plan if p["fila"] == fila and p["campo"] == "test_date"), None)
            fecha = date.fromisoformat(fecha) if fecha else None
        if fecha:
            anio, semana, _ = fecha.isocalendar()
            plan.append({"caso": numero, "fila": fila, "campo": "week", "columna": columnas["week"],
                         "valor": f"{anio}-W{semana:02d}", "origen": "derivada_de_test_date",
                         "votos": 0, "regla": "semana_iso"})
    if limite_inferior:
        plan = [paso for paso in plan
                if not (paso["campo"] == "module_date"
                        and not (limite_inferior <= date.fromisoformat(paso["valor"]) <= limite_superior))]
    return plan


def aplicar(hoja, plan: list[dict]) -> int:
    """Escribe sólo celdas vacías. Devuelve cuántas escribió."""
    escritas = 0
    for paso in plan:
        celda = hoja.cell(paso["fila"], paso["columna"])
        if celda.value not in (None, ""):
            continue
        celda.value = paso["valor"]
        escritas += 1
    return escritas


def resumen(plan: list[dict]) -> dict:
    por_campo = Counter(p["campo"] for p in plan)
    por_origen = Counter(p["origen"] for p in plan)
    return {"celdas": len(plan), "por_campo": dict(por_campo), "por_origen": dict(por_origen)}
