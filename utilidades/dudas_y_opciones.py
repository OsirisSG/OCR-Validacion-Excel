"""Cuando el programa duda, no se calla: pide ayuda y ofrece de dónde podría salir el dato.

Cada duda es un campo de un caso que quedó vacío. La duda lleva:

* **por qué** no se llenó (`sin_lectura_valida`, `fuentes_en_conflicto`, …);
* **opciones**: cada valor que podría ir ahí, con la fuente que lo propone, cuánto lo
  respalda y **dónde mirar** para comprobarlo a mano;
* la opción explícita **«no lo tengo»**, para que no llenar sea una decisión y no un olvido.

Las opciones no son inventadas: salen de las imágenes del propio caso (votos), del nombre
de la carpeta, del diagrama, de la barra del vídeo, de la serie de casos y de lo que dicen
las otras filas del libro.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

# Campos del contrato que se pueden rellenar desde OCR.
CAMPOS_RELLENABLES = (
    "week", "test_reason", "test_number", "test_date", "test_place", "temperature_condition",
    "module_part_number", "module_version", "module_serial_number", "module_date",
    "engineering_level", "delay_ms", "inflator_type", "inflator_supplier",
    "dashboard_part_number", "dashboard_serial_number", "dashboard_date",
    "dashboard_engineering_level", "dashboard_supplier", "laser_opening",
)

# Dónde suele estar cada dato, para poder comprobarlo a mano. Sale de lo medido sobre el
# corpus: qué regla y qué imagen produjeron cada campo.
DONDE_BUSCAR: dict[str, list[str]] = {
    "test_number": ["barra inferior del vídeo (… 222509 RdW NT NOM …)",
                    "rótulo del diagrama", "etiqueta del módulo"],
    "module_version": ["barra inferior del vídeo (RdW = 1st, NAR = 2st)",
                       "nombre de la carpeta del caso", "título del diagrama"],
    "temperature_condition": ["nombre de la carpeta (… NT / HT / RT)",
                              "barra inferior del vídeo", "etiqueta TEMPERATURE"],
    "inflator_type": ["nombre de la carpeta (… NOM / OGL / UGL)",
                      "barra inferior del vídeo", "título del diagrama"],
    "module_part_number": ["etiqueta del módulo, bloque PART NUMBER (2GJ.880.204.J)"],
    "module_serial_number": ["etiqueta del módulo, serial impreso (671 ZRZ0539991D)"],
    "dashboard_part_number": ["etiqueta del tablero (2GJ.857.003.G)"],
    "dashboard_serial_number": ["etiqueta del tablero (052 3KVJ008R6E)"],
    "engineering_level": ["etiqueta del módulo: código de tres caracteres (01S / 66K / 69K)"],
    "dashboard_engineering_level": ["etiqueta del tablero (03S)"],
    "inflator_supplier": ["etiqueta del módulo: fabricante del inflador (Autoliv)"],
    "dashboard_supplier": ["etiqueta del tablero: fabricante (FORVIA)"],
    "test_place": ["barra del vídeo o rótulo EDAG Testlab", "cabecera del vídeo"],
    "test_date": ["etiqueta: bloque de fecha", "barra del vídeo (28 MAY 25)"],
    "module_date": ["etiqueta del módulo: fecha de fabricación"],
    "test_reason": ["barra del vídeo (BMG)", "rótulo Versuche Begrundung"],
    "laser_opening": ["etiqueta del módulo: apertura láser (3mm)"],
    "opening_time_ms": ["medición de tiempos: carril diferido"],
}

MOTIVOS = ("sin_lectura_valida", "fuentes_en_conflicto", "valor_no_coherente",
           "fuera_del_alcance_declarado")

FUENTES = ("carpeta", "barra_video", "diagrama", "lectura_ocr", "serie",
           "otros_casos_del_libro", "no_lo_tengo")

# Orden de preferencia cuando dos fuentes proponen el mismo valor.
PRIORIDAD = {"barra_video": 0, "carpeta": 1, "diagrama": 2, "lectura_ocr": 3,
             "serie": 4, "otros_casos_del_libro": 5, "no_lo_tengo": 9}


def _id(caso: str, campo: str) -> str:
    return f"{caso}::{campo}"


def _opcion(valor, fuente: str, respaldo: str, confianza: float, donde: list[str]) -> dict:
    return {"valor": valor, "fuente": fuente, "respaldo": respaldo,
            "confianza": round(float(confianza), 2), "donde_mirar": donde}


def _opciones_de_serie(campo: str, numero: str) -> list[dict]:
    try:
        from utilidades.protocolo_identidad import bloque_de_serie
    except Exception:                                     # pragma: no cover
        return []
    bloque = bloque_de_serie(numero)
    if not bloque:
        return []
    if campo == "temperature_condition":
        return [_opcion(bloque["temperatura"], "serie",
                        f"el bloque {bloque['desde']}-{bloque['hasta']} es {bloque['temperatura']}",
                        0.6, DONDE_BUSCAR.get(campo, []))]
    if campo == "inflator_type":
        return [_opcion(bloque["inflador"], "serie",
                        f"el bloque {bloque['desde']}-{bloque['hasta']} es {bloque['inflador']}",
                        0.6, DONDE_BUSCAR.get(campo, []))]
    return []


def _opciones_de_otros_casos(campo: str, caso: str, libro_filas: dict) -> list[dict]:
    """Lo que dicen las demás filas del libro. Solo si es mayoritario, y con confianza baja."""
    valores = [str(f.get(campo)).strip() for otro, f in libro_filas.items()
               if otro != caso and f.get(campo) not in (None, "")]
    if len(valores) < 3:
        return []
    cuenta: dict[str, int] = {}
    for v in valores:
        cuenta[v] = cuenta.get(v, 0) + 1
    valor, votos = max(cuenta.items(), key=lambda par: par[1])
    if votos / len(valores) < 0.6:
        return []
    return [_opcion(valor, "otros_casos_del_libro",
                    f"{votos} de {len(valores)} filas del libro dicen lo mismo", 0.35,
                    DONDE_BUSCAR.get(campo, []))]


CAMPOS_CON_SERIE = ("test_number", "temperature_condition", "inflator_type")


def _estado_serie(caso: str, campo: str, valor) -> str | None:
    """'coherente' / 'fuera_de_serie' / 'incoherente' para ese valor, o None si no aplica."""
    try:
        from utilidades.protocolo_identidad import revisar_serie
    except Exception:                                     # pragma: no cover
        return None
    if campo not in CAMPOS_CON_SERIE or valor in (None, ""):
        return None
    argumentos = {"test_number": None, "temperature_condition": None, "inflator_type": None}
    argumentos[campo] = str(valor)
    return revisar_serie(argumentos["test_number"], argumentos["temperature_condition"],
                         argumentos["inflator_type"])["estado"]


def _filtrar_por_serie(caso: str, campo: str, opciones: list[dict]) -> tuple[list[dict], list[dict]]:
    """Quita las opciones que contradicen la serie cuando otra sí la cumple.

    Medido: en el caso 232561 las imágenes proponían `142025` y `162051` como número de
    prueba (son otros números impresos en la etiqueta). La serie demuestra que el número
    es 232561. Se descartan de la vista, pero quedan en el registro.
    """
    if campo not in CAMPOS_CON_SERIE:
        return opciones, []
    fuertes = [o for o in opciones if o["fuente"] in {"carpeta", "barra_video", "diagrama"}
               and _estado_serie(caso, campo, o["valor"]) == "coherente"]
    if not fuertes:
        return opciones, []
    conservadas, descartadas = [], []
    for opcion in opciones:
        if opcion["valor"] is None or opcion in fuertes:
            conservadas.append(opcion)
            continue
        estado = _estado_serie(caso, campo, opcion["valor"])
        if estado in {"incoherente", "fuera_de_serie"}:
            descartadas.append({**opcion, "motivo_descarte":
                                "la serie de casos no la respalda y hay otra opción que sí"})
        else:
            conservadas.append(opcion)
    return conservadas, descartadas


def _fusionar(opciones: list[dict]) -> list[dict]:
    """Un valor por opción: se juntan los respaldos y se queda la mejor confianza."""
    por_valor: dict[str, dict] = {}
    for op in opciones:
        clave = "" if op["valor"] in (None, "") else str(op["valor"]).strip().upper()
        if clave not in por_valor:
            por_valor[clave] = dict(op, fuentes=[op["fuente"]], respaldos=[op["respaldo"]])
            continue
        actual = por_valor[clave]
        actual["fuentes"].append(op["fuente"])
        actual["respaldos"].append(op["respaldo"])
        if op["confianza"] > actual["confianza"]:
            actual["confianza"] = op["confianza"]
            actual["fuente"] = op["fuente"]
        actual["donde_mirar"] = sorted(set(actual["donde_mirar"]) | set(op["donde_mirar"]))
    for op in por_valor.values():
        op["fuente"] = min(op["fuentes"], key=lambda f: PRIORIDAD.get(f, 8))
        op["respaldo"] = " · ".join(dict.fromkeys(op["respaldos"]))
    return sorted(por_valor.values(),
                  key=lambda o: (-o["confianza"], PRIORIDAD.get(o["fuente"], 8)))


def construir_dudas(libro_filas: dict[str, dict], lecturas: dict[str, dict],
                    columnas: dict[str, str] | None = None,
                    casos: list[str] | None = None,
                    campos: tuple[str, ...] | None = None) -> list[dict]:
    """Devuelve la cola de dudas, con opciones, para los campos vacíos del libro.

    `libro_filas`: {caso: {campo: valor}} — lo que ya hay escrito en el libro.
    `lecturas`:    {caso: {"ocr": {campo: {valor: nº imágenes}}, "carpeta": {...},
                            "diagrama": {...}, "barra_video": {...}}}
    `columnas`:    {campo: letra} — del informe de cabeceras (opcional, para mostrar la celda).
    """
    columnas = columnas or {}
    campos = campos or CAMPOS_RELLENABLES
    dudas: list[dict] = []
    for caso in sorted(casos or libro_filas):
        fila = libro_filas.get(caso, {})
        fuentes_caso = lecturas.get(caso, {})
        for campo in campos:
            actual = fila.get(campo)
            if actual not in (None, ""):
                continue
            if campo not in columnas and columnas:
                continue          # el libro no tiene columna para ese campo: no es una duda
            opciones: list[dict] = []
            for fuente in ("barra_video", "carpeta", "diagrama"):
                valor = (fuentes_caso.get(fuente) or {}).get(campo)
                if valor:
                    opciones.append(_opcion(valor, fuente, f"leído en {fuente.replace('_', ' ')}",
                                            0.85 if fuente == "barra_video" else 0.8,
                                            DONDE_BUSCAR.get(campo, [])))
            # P08 (regla 7): si el libro tiene la MISMA columna repetida en todos los casos
            # (IT BMG, EDAG, 2GJ.857.003.G…), esa constante es una opción legítima y se
            # confirma una sola vez para todas las filas.
            constante = (fuentes_caso.get("libro_constante") or {}).get(campo)
            if constante:
                opciones.append(_opcion(constante, "libro_constante",
                                        "el libro lo repite igual en todos los casos",
                                        0.75, DONDE_BUSCAR.get(campo, [])))
            votos = (fuentes_caso.get("ocr") or {}).get(campo) or {}
            total_imagenes = sum(votos.values()) if votos else 0
            # una sola imagen diciendo algo no es una lectura: es una coincidencia
            candidatos = [(v, n) for v, n in sorted(votos.items(), key=lambda p: -p[1]) if n >= 2]
            if not candidatos and votos:
                candidatos = [max(votos.items(), key=lambda p: p[1])]
            for valor, n in candidatos[:3]:
                opciones.append(_opcion(valor, "lectura_ocr",
                                        f"{n} de las {total_imagenes} lecturas del caso",
                                        min(0.7, 0.25 + 0.15 * n),
                                        DONDE_BUSCAR.get(campo, [])))
            opciones.extend(_opciones_de_serie(campo, caso))
            opciones.extend(_opciones_de_otros_casos(campo, caso, libro_filas))
            opciones = _fusionar(opciones)
            opciones, descartadas = _filtrar_por_serie(caso, campo, opciones)
            opciones.append(_opcion(None, "no_lo_tengo", "dejar la celda vacía a propósito",
                                    0.0, DONDE_BUSCAR.get(campo, [])))
            if len(opciones) == 1:
                motivo = "sin_lectura_valida"
                detalle = "ninguna fuente propone un valor para este campo"
            elif any(o["fuente"] == "lectura_ocr" for o in opciones) and any(
                    o["fuente"] in {"carpeta", "barra_video"} for o in opciones):
                valores_ocr = {str(o["valor"]).upper() for o in opciones if o["fuente"] == "lectura_ocr"}
                valores_carpeta = {str(o["valor"]).upper() for o in opciones
                                   if o["fuente"] in {"carpeta", "barra_video"}}
                if valores_ocr - valores_carpeta:
                    motivo = "fuentes_en_conflicto"
                    detalle = ("la carpeta/vídeo y las imágenes no dicen lo mismo; "
                               "elige tú cuál manda")
                else:
                    motivo, detalle = "sin_lectura_valida", "sin una lectura que se pueda dar por buena"
            else:
                motivo, detalle = "sin_lectura_valida", ("hay propuestas, pero ninguna es una "
                                                         "lectura directa del campo")
            dudas.append({
                "id": _id(caso, campo), "caso": caso, "campo": campo,
                "columna": columnas.get(campo), "motivo": motivo, "detalle": detalle,
                "donde_mirar": DONDE_BUSCAR.get(campo, []),
                "opciones": opciones,
                "opciones_descartadas": descartadas,
                "opcion_recomendada": next((o["valor"] for o in opciones
                                            if o["valor"] is not None), None),
            })
    return dudas


def resumen_dudas(dudas: list[dict]) -> dict:
    por_motivo: dict[str, int] = {}
    con_opcion: dict[str, int] = {}
    for d in dudas:
        por_motivo[d["motivo"]] = por_motivo.get(d["motivo"], 0) + 1
        utiles = [o for o in d["opciones"] if o["valor"] is not None]
        con_opcion[str(len(utiles))] = con_opcion.get(str(len(utiles)), 0) + 1
    return {"dudas": len(dudas), "casos": len({d["caso"] for d in dudas}),
            "campos": len({d["campo"] for d in dudas}),
            "por_motivo": por_motivo, "dudas_por_numero_de_opciones": con_opcion,
            "con_al_menos_una_opcion": sum(1 for d in dudas
                                           if any(o["valor"] is not None for o in d["opciones"]))}


def _ajustar_tipo(hoja, informe, campo, fila, valor):
    """Devuelve el valor con el tipo que ya usa esa columna en el libro.

    El libro guarda `232561` como número; escribir la cadena `"232561"` rompería los
    filtros y las fórmulas que lo leen. Se respeta lo que ya hay en la columna.
    """
    if not isinstance(valor, str):
        return valor
    letra = informe.resueltos.get(campo)
    if not letra:
        return valor
    from openpyxl.utils import column_index_from_string
    columna = column_index_from_string(letra)
    vecinos = [hoja.cell(f, columna).value for f in range(8, hoja.max_row + 1)
               if hoja.cell(f, columna).value not in (None, "") and f != fila]
    if not vecinos:
        return valor
    numericos = sum(1 for v in vecinos if isinstance(v, (int, float)))
    if numericos / len(vecinos) >= 0.8 and valor.strip().lstrip("-").isdigit():
        return int(valor.strip())
    return valor


def aplicar_decisiones(ruta_libro: str | Path, decisiones: list[dict],
                       ruta_salida: str | Path | None = None,
                       fila_encabezados: int = 7, hoja: str | None = None,
                       diario: str | Path | None = None) -> dict:
    """Escribe las decisiones en el libro y deja constancia de ellas.

    Cada decisión: `{"caso": "232561", "fila": 15, "campo": "inflator_type", "valor": "OGL",
                     "fuente": "serie", "opciones_descartadas": [...]}`

    Se escribe con el mismo adaptador que no toca cabeceras ni fórmulas, y se guarda un
    diario con qué se eligió, de dónde salió y qué se descartó.
    """
    from openpyxl import load_workbook
    from utilidades import cabeceras_excel as ce

    ruta = Path(ruta_libro)
    libro = load_workbook(ruta)
    ws = libro[hoja] if hoja else libro[load_workbook(ruta, read_only=True).sheetnames[0]]
    informe = ce.resolver_cabeceras(ce.leer_cabeceras(ws, fila_encabezados), fila_encabezados)

    escritos, omitidos = [], []
    for decision in decisiones:
        valor = decision.get("valor")
        if valor in (None, ""):
            omitidos.append({**decision, "motivo": "no_lo_tengo: se deja vacío a propósito"})
            continue
        valor = _ajustar_tipo(ws, informe, decision["campo"], int(decision["fila"]), valor)
        resultado = ce.escribir_valores(ws, int(decision["fila"]), {decision["campo"]: valor},
                                        informe, fila_encabezados=fila_encabezados)
        escritos.extend(resultado["escritos"])
        omitidos.extend(resultado["omitidos"])

    salida = Path(ruta_salida) if ruta_salida else ruta
    libro.save(salida)

    registro = {"fecha": datetime.now().isoformat(timespec="seconds"),
                "libro_entrada": str(ruta), "libro_salida": str(salida),
                "decisiones": decisiones, "escritos": escritos, "omitidos": omitidos}
    if diario:
        Path(diario).parent.mkdir(parents=True, exist_ok=True)
        Path(diario).write_text(json.dumps(registro, ensure_ascii=False, indent=1, default=str),
                                encoding="utf-8")
    return registro


def lecturas_desde_base(ruta_base: str | Path, casos: list[str],
                        minimo_confianza: float = 0.0) -> dict[str, dict]:
    """Construye las lecturas de cada caso a partir de la base de aprendizaje.

    Es lo que alimenta las opciones en producción: agrupa el texto OCR guardado por
    carpeta de caso, lo pasa por el extractor y cuenta cuántas imágenes proponen cada
    valor. No inventa nada: si un campo no aparece, no aparece.
    """
    import sqlite3

    import flujo_empresarial as fe

    con = sqlite3.connect(str(ruta_base))
    lecturas: dict[str, dict] = {caso: {"ocr": {}} for caso in casos}
    for ruta, texto in con.execute(
            "select ruta_imagen, texto_ocr from observaciones where texto_ocr is not null"):
        caso = next((c for c in casos if f"{c} " in (ruta or "")), None)
        if not caso:
            continue
        for candidato in fe.extraer_candidatos_texto(str(texto), {"confianza_ocr": minimo_confianza}, {}):
            if candidato.get("valido_catalogo") is False:
                continue
            valor = str(candidato.get("valor_normalizado") or "").strip()
            if not valor:
                continue
            campo = lecturas[caso]["ocr"].setdefault(candidato["clave"], {})
            campo[valor] = campo.get(valor, 0) + 1
    return lecturas
