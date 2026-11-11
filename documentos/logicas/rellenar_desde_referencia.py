#!/usr/bin/env python3
"""Rellena el libro con **constantes del proyecto** + **semana ISO** + **barra del vídeo** (P17).

    python rellenar_desde_referencia.py --libro versionV16_0_28.xlsx \\
        --referencia Book-10-Examples.xlsx \\
        --casos "C:\\Programas Base\\Resumen-1-Step" \\
        --salida versionV16_0_30.xlsx --informe informe.json [--simular]

Tres fuentes, en este orden (la primera que tenga dato gana):

1. **Barra de los vídeos del caso** — fecha de prueba, lugar, delay, temperatura y tipo de
   generador (`rellenar_desde_videos`).
2. **Constantes del proyecto** — columnas en las que *todas* las filas del libro completo tienen el
   mismo valor (`Proveedor de generador = Autoliv`, `Apertura láser = 3mm ¨C¨`…). Sólo se aplican a
   celdas vacías y sólo si la columna es constante en al menos 3 casos.
3. **Semana** — semana ISO de la fecha de prueba (`2025-06-19` → `25`).

Nunca se sobrescribe una celda con dato, todo valor pasa el protocolo del campo y el libro de
entrada no se modifica: se escribe en `--salida`.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import cv2
from openpyxl import load_workbook

from rellenar_desde_videos import a_valor_de_celda, leer_caso, mapa_de_casos
from utilidades.barra_estado import cargar_banco
from utilidades.protocolo_campos import evaluar
from utilidades import codigos_modulo as CM
from utilidades import lector_etiquetas as L
from utilidades import video_cabecera as VC
from utilidades import pizarra
from utilidades.tablero_lectura import leer_fotos

CAMPOS_BARRA = {
    "test_date": "test_date",
    "test_place": "test_place",
    "delay_ms": "delay_ms",
    "temperature_condition": "temperature_condition",
    "inflator_type": "inflator_type",
}
NO_CONSTANTES = {"test_number", "test_date", "week", "module_serial_number", "dashboard_serial_number",
                 "engineering_level", "temperature_condition", "inflator_type"}
# Columnas que salen de una **etiqueta** que se ve en la foto: no se copian de ninguna constante,
# se leen con las anclas (pestaña azul, estampa de color, DataMatrix). Si no hay foto o no se lee,
# la celda se queda vacía y sale como duda.
CAMPOS_DE_ETIQUETA = {"dashboard_date", "dashboard_engineering_level", "dashboard_part_number",
                      "dashboard_serial_number", "engineering_level", "module_part_number",
                      "module_date", "module_serial_number"}
CONSTANTES_SEGURAS = {"test_reason", "inflator_supplier", "dashboard_supplier"}
EXTENSIONES_FOTO = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
PATRON_PARTE_CATALOGO = re.compile(r"^\d[A-Z]{2}[.\s]?\d{3}[.\s]?\d{3}[.\s]?[A-Z]$")
MINIMO_CASOS = 3

# Convenciones del libro real (comprobadas contra Book-10-Examples.xlsx, 10/10 casos):
#   · el lugar de prueba se escribe «EDAG», no «EDAG MEX»;
#   · cuando la barra dice 0 ms de delay, el libro escribe «--».
CONVENCIONES = {
    "test_place": {"EDAG MEX": "EDAG", "EDAG MEXICO": "EDAG"},
    "delay_ms": {"0": "--", "0.0": "--"},
}


MAPA_GENERADOR = {"NOM": "NOM", "OGL": "OGL", "UGL": "UGL"}


def arreglar_generador(texto: str) -> str | None:
    """Lleva a `NOM` / `OGL` / `UGL` lo que imprime la barra del vídeo.

    El motor lee `OGU`, `UGU`, `DGU` y cosas así: la última letra se confunde con `L` y la primera
    `U` con `D`. Sólo se arreglan esas dos posiciones, que son las que fallan de verdad.
    """
    limpio = "".join(caracter for caracter in str(texto or "").upper() if caracter.isalpha())
    if len(limpio) != 3:
        return None
    candidatos = {limpio}
    if limpio[2] == "U":
        candidatos.add(limpio[:2] + "L")
    for base in list(candidatos):
        if base[0] == "D":
            candidatos.add("U" + base[1:])
    for candidato in candidatos:
        if candidato in MAPA_GENERADOR:
            return MAPA_GENERADOR[candidato]
    return None


def generador_en_barra(texto_barra: str) -> str | None:
    """El tipo de generador va en la barra del vídeo, tras la temperatura (`NT OGL 0ms`)."""
    partes = str(texto_barra or "").upper().split()
    for posicion, parte in enumerate(partes[:-1]):
        if parte in ("NT", "RT", "HT", "KT"):
            for siguiente in partes[posicion + 1:posicion + 4]:
                valor = arreglar_generador(siguiente)
                if valor:
                    return valor
    for parte in partes:
        valor = arreglar_generador(parte)
        if valor:
            return valor
    return None


def aplicar_convencion(campo: str, valor):
    return CONVENCIONES.get(campo, {}).get(str(valor).strip(), valor)


CAMPOS_DE_FECHA = ("test_date", "module_date", "dashboard_date")


def fechas_a_texto(libro, principal, mapa: dict[str, int], fila_encabezado: int = 7) -> int:
    """Pasa a texto ISO (`2025-06-19`) las fechas de las columnas de fecha, en todas las hojas espejo.

    Excel guarda una fecha como un número de días (45805). Los visores que no aplican formatos enseñan
    ese número; con texto ISO se lee igual en cualquier sitio y sigue siendo ordenable.
    """
    from rescatar_libro import columnas_del_libro
    firma = firma_de_cabeceras(principal, fila_encabezado)
    convertidas = 0
    for hoja in libro.worksheets:
        if firma_de_cabeceras(hoja, fila_encabezado) != firma:
            continue
        mapa_hoja = columnas_del_libro(hoja, fila_encabezado)
        for campo in CAMPOS_DE_FECHA:
            columna = mapa_hoja.get(campo)
            if not columna:
                continue
            for fila in range(fila_encabezado + 1, hoja.max_row + 1):
                celda = hoja.cell(fila, columna)
                if isinstance(celda.value, (datetime, date)):
                    celda.value = celda.value.strftime("%Y-%m-%d")
                    celda.number_format = "@"
                    convertidas += 1
                elif isinstance(celda.value, datetime):
                    celda.value = celda.value.date().isoformat()
                    celda.number_format = "@"
                    convertidas += 1
    return convertidas


def normalizar_lugar(texto: str) -> str:
    """`EDAG MEX`, `EDAG México` y `EDAG Testlab` son el mismo lugar: `EDAG`."""
    limpio = "".join(c for c in str(texto or "").upper() if c.isalnum())
    if not limpio:
        return ""
    if "EDAG" in limpio:
        return "EDAG"
    if limpio.startswith("VW"):
        return "VW"
    return limpio


def formato_de_fecha(hoja, columna: int, fila_datos: int = 8) -> str:
    """Copia el formato de fecha que ya usa esa columna (si no, `DD/MM/YYYY`)."""
    for fila in range(fila_datos, min(hoja.max_row, fila_datos + 3) + 1):
        formato = str(hoja.cell(fila, columna).number_format or "")
        if formato and formato not in ("General", "@"):
            return formato
    return "DD/MM/YYYY"


def firma_de_cabeceras(hoja, fila_encabezado: int = 7, cuantas: int = 6) -> tuple:
    return tuple(str(hoja.cell(fila_encabezado, c).value or "").strip().lower() for c in range(1, cuantas + 1))


def replicar_en_otras_hojas(libro, principal, aplicados: list[dict],
                            fila_encabezado: int = 7) -> tuple[int, list[str]]:
    """Escribe lo mismo en **todas las hojas con la misma estructura** (Rangos y Versuchsmatrix).

    El libro tiene dos hojas espejo con idénticas cabeceras: si sólo se rellenaba la principal, la
    otra se quedaba vacía. Aquí se replica valor a valor, respetando celdas ocupadas y con el
    formato de fecha de la propia columna (para no ver `45827` en lugar de la fecha).
    """
    from rescatar_libro import columnas_del_libro
    firma = firma_de_cabeceras(principal, fila_encabezado)
    replicadas, hojas = 0, []
    for hoja in libro.worksheets:
        if hoja is principal or firma_de_cabeceras(hoja, fila_encabezado) != firma:
            continue
        mapa_otra = columnas_del_libro(hoja, fila_encabezado)
        if "test_number" not in mapa_otra:
            continue
        filas_otra: dict[str, int] = {}
        for fila in range(fila_encabezado + 1, hoja.max_row + 1):
            valor = hoja.cell(fila, mapa_otra["test_number"]).value
            clave = str(valor).strip() if valor not in (None, "") else ""
            if clave:
                filas_otra[clave] = fila
        escritas_aqui = 0
        for aplicado in aplicados:
            fila = filas_otra.get(str(aplicado["numero"]).strip())
            columna = mapa_otra.get(aplicado["campo"])
            if not fila or not columna:
                continue
            celda = hoja.cell(fila, columna)
            if celda.value not in (None, ""):
                continue
            celda.value = aplicado["valor"]
            if isinstance(aplicado["valor"], (datetime, date)):
                celda.number_format = formato_de_fecha(hoja, columna, fila_encabezado + 1)
            escritas_aqui += 1
        if escritas_aqui:
            hojas.append(f"{hoja.title} (+{escritas_aqui})")
            replicadas += escritas_aqui
    return replicadas, hojas


def leer_cabecera_de_caso(numero: str, rutas, motor, carpeta_evidencia: Path,
                          evidencia_barra: dict) -> dict:
    """Lugar de prueba desde la **cabecera del vídeo** (`EDAG Testlab`), con captura de evidencia."""
    from collections import Counter
    votos: Counter = Counter()
    leidos: Counter = Counter()
    muestra = None
    for ruta in rutas:
        lectura = VC.leer_cabecera_de_video(ruta, motor, muestras=2)
        if lectura.get("lugar"):
            votos[lectura["lugar"]] += 1
            leidos[lectura.get("lugar_leido", "")] += 1
            if muestra is None and lectura.get("fotograma") is not None:
                barra = extraer_barra(evidencia_barra, numero)
                captura = carpeta_evidencia / f"video_{numero}_{Path(ruta).stem}.png"
                try:
                    VC.captura_de_evidencia(lectura["fotograma"], lectura.get("lectura") or {},
                                            barra, captura)
                    muestra = str(captura)
                except Exception:                                  # noqa: BLE001
                    muestra = None
    if not votos:
        return {}
    lugar = votos.most_common(1)[0][0]
    return {"lugar": lugar, "lugar_leido": leidos.most_common(1)[0][0],
            "votos": dict(votos), "captura": muestra or "",
            "lugar_barra": (evidencia_barra.get("test_place") or {}).get("valor")}


def extraer_barra(evidencia_barra: dict, numero: str) -> dict:
    """Resumen de la barra para la captura (número, fecha, semana, texto)."""
    resumen = evidencia_barra.get("__resumen__") or {}

    def valor(campo):
        return (evidencia_barra.get(campo) or {}).get("valor") or ""

    fecha = valor("test_date")
    semana = semana_iso(fecha) if fecha else ""
    return {"numero": valor("test_number") or numero, "fecha": fecha, "semana": semana,
            "texto": resumen.get("texto", "")}


def leer_pizarra_de_caso(numero: str, rutas, carpeta_evidencia: Path,
                         aprendizaje: dict | None = None, motor=None) -> dict:
    """Motivo de prueba leído de la pizarra escrita a mano del tablero (no copiado del libro)."""
    motor = motor or L.motor_disponible()
    for ruta in rutas:
        imagen = cv2.imread(str(ruta))
        if imagen is None:
            continue
        if max(imagen.shape[:2]) > 2000:
            factor = 2000 / max(imagen.shape[:2])
            imagen = cv2.resize(imagen, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
        lectura = pizarra.leer_pizarra(imagen, motor, aprendizaje=aprendizaje)
        if lectura.get("proyecto") and lectura.get("tipo_prueba"):
            lectura["captura"] = str(pizarra.recorte_evidencia(
                imagen, carpeta_evidencia / f"pizarra_{numero}_{Path(ruta).stem}.png"))
            lectura["foto"] = str(ruta)
            return lectura
        if lectura.get("proyecto") and "ganador" not in locals().get("_", {}):
            # sirve como evidencia parcial, pero el motivo no se cierra sin el tipo de prueba
            lectura["captura"] = str(pizarra.recorte_evidencia(
                imagen, carpeta_evidencia / f"pizarra_{numero}_{Path(ruta).stem}.png"))
            lectura["foto"] = str(ruta)
            return lectura
    return {}


def mapa_de_fotos(raiz: Path, conocidos: set[str] | None = None) -> dict[str, list[Path]]:
    """Número de prueba → fotos, con la misma regla que los vídeos (número más cercano al archivo)."""
    encontrados: dict[str, list[Path]] = defaultdict(list)
    for archivo in sorted(raiz.rglob("*")):
        if not archivo.is_file() or archivo.suffix.lower() not in EXTENSIONES_FOTO:
            continue
        elegido = None
        for parte in reversed(archivo.relative_to(raiz).parts[:-1]):
            numeros = re.findall(r"\b(\d{6})\b", parte)
            if conocidos:
                numeros = [n for n in numeros if n in conocidos]
            if numeros:
                elegido = numeros[0]
                break
        if elegido:
            encontrados[elegido].append(archivo)
    return {k: sorted(set(v)) for k, v in encontrados.items()}


def columnas(hoja, fila_encabezado: int = 7) -> dict[str, int]:
    """Posición de cada columna por su nombre en castellano (las dos primeras filas de cabecera)."""
    nombres = {}
    for celda in hoja[fila_encabezado]:
        if celda.value:
            nombres[str(celda.value).strip()] = celda.column
    mapa = {}
    from rescatar_libro import columnas_del_libro
    for campo, columna in columnas_del_libro(hoja, fila_encabezado).items():
        mapa[campo] = columna
    return mapa


def filas_con_caso(hoja, columna_numero: int) -> dict[str, int]:
    salida = {}
    for fila in range(8, hoja.max_row + 1):
        valor = hoja.cell(fila, columna_numero).value
        if valor in (None, ""):
            continue
        clave = "".join(ch for ch in str(valor) if ch.isdigit())
        salida.setdefault(clave, fila)
    return salida


def constantes(hoja_referencia, mapa: dict[str, int], columna_numero: int,
               excluir: set[str] | None = None) -> dict[str, dict]:
    """Columnas constantes del libro de referencia (misma estructura de columnas)."""
    excluir = excluir or set()
    salida = {}
    for campo, columna in mapa.items():
        if campo in excluir:
            continue
        valores = []
        for fila in range(8, hoja_referencia.max_row + 1):
            if hoja_referencia.cell(fila, columna_numero).value in (None, ""):
                continue
            valor = hoja_referencia.cell(fila, columna).value
            if valor not in (None, ""):
                valores.append(valor)
        if len(valores) < MINIMO_CASOS:
            continue
        distintos = Counter(str(v).strip() for v in valores)
        if len(distintos) == 1:
            salida[campo] = {"valor": valores[0], "casos": len(valores)}
    return salida


def desglose_del_numero(numero) -> dict | None:
    """La guía (pág. 2) define la estructura del número de prueba: `232541` → `23-25-41`.

    `23` = semana, `25` = año, `41` = número de prueba. Se valida antes de usar nada: semana
    01-53 y año razonable; si no cuadra, no se devuelve nada.
    """
    digitos = "".join(ch for ch in str(numero) if ch.isdigit())
    if len(digitos) != 6:
        return None
    semana, anio, secuencia = int(digitos[:2]), int(digitos[2:4]), digitos[4:]
    if not 1 <= semana <= 53:
        return None
    return {"semana": f"{semana:02d}", "anio": 2000 + anio, "secuencia": secuencia,
            "numero": digitos}


def semana_del_numero(numero, fecha=None) -> tuple[str | None, str]:
    """Semana del número, corroborada con la semana ISO de la fecha de prueba.

    Devuelve (semana, como). `como` dice de dónde sale o por qué no se usa.
    """
    desglose = desglose_del_numero(numero)
    if not desglose:
        return None, "numero_sin_estructura"
    iso = semana_iso(fecha) if fecha is not None else None
    if iso and iso != desglose["semana"]:
        return None, f"conflicto_numero({desglose['semana']})_fecha_iso({iso})"
    return desglose["semana"], "numero_prueba" if not iso else "numero_prueba_corroborado_iso"


def semana_iso(fecha) -> str | None:
    if isinstance(fecha, datetime):
        fecha = fecha.date()
    if isinstance(fecha, date):
        return f"{fecha.isocalendar().week:02d}"
    if isinstance(fecha, str):
        try:
            return f"{datetime.strptime(fecha[:10], '%Y-%m-%d').date().isocalendar().week:02d}"
        except ValueError:
            return None
    return None


def _compacto(texto: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(texto).upper())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Relleno por constantes, semana y barra del vídeo")
    ap.add_argument("--libro", required=True)
    ap.add_argument("--referencia", default=None, help="libro completo del mismo proyecto")
    ap.add_argument("--casos", default=None, help="árbol con las carpetas de los casos (vídeos)")
    ap.add_argument("--fotos", default=None, help="árbol con las fotos de etiquetas de cada caso")
    ap.add_argument("--estricto", action="store_true",
                    help="las columnas de etiqueta SÓLO se rellenan leyendo fotos (por defecto)")
    ap.add_argument("--fechas-texto", action="store_true",
                    help="escribe las fechas como texto ISO (2025-06-19); útil para visores que "
                         "enseñan el número de serie en vez de la fecha")
    ap.add_argument("--modulo-json", default=None,
                    help="evidencia del módulo PAB ya calculada por evidencia_modulo.py "
                         "(número de parte, variante, serie, fecha de fabricación y nivel)")
    ap.add_argument("--tablero-json", default=None,
                    help="evidencia del TABLERO ya calculada por evidencia_tablero.py "
                         "(número de parte grabado, serie, fecha y nivel de ingeniería)")
    ap.add_argument("--video-json", default=None,
                    help="evidencia de vídeo ya calculada por evidencia_video.py (no se abren los vídeos)")
    ap.add_argument("--sin-cabecera", action="store_true",
                    help="no lee la cabecera del vídeo (lugar de prueba)")
    ap.add_argument("--constantes-completas", action="store_true",
                    help="permite rellenar columnas de etiqueta con constantes del libro completo")
    ap.add_argument("--salida", default=None)
    ap.add_argument("--hoja", default="Versuchsmatrix")
    ap.add_argument("--simular", action="store_true")
    ap.add_argument("--informe", default=None)
    args = ap.parse_args(argv)

    entrada = Path(args.libro)
    salida = Path(args.salida) if args.salida else entrada.with_name(entrada.stem + "_relleno.xlsx")
    libro = load_workbook(entrada)
    hoja = libro[args.hoja]
    mapa = columnas(hoja)
    col_numero = mapa["test_number"]
    registro_dudas: list[dict] = []

    # 1) constantes del proyecto
    fuente_constantes = Path(args.referencia) if args.referencia else entrada
    hoja_ref = load_workbook(fuente_constantes, data_only=True)[args.hoja]
    const = constantes(hoja_ref, mapa, col_numero, excluir=NO_CONSTANTES | {"week"})

    # 1-bis) lectura de etiquetas con anclas (pestaña azul / estampa de color / DataMatrix)
    etiquetas: dict[str, dict] = {}
    pizarras: dict[str, dict] = {}
    motor_ocr = L.motor_disponible()          # uno solo para etiquetas, pizarra y cabecera
    aprendizaje_pizarra = pizarra.cargar_aprendizaje()
    if args.fotos:
        raiz_fotos = Path(args.fotos)
        if raiz_fotos.is_dir():
            fotos_por_caso = mapa_de_fotos(raiz_fotos, set(filas_con_caso(hoja, col_numero)))
            # catálogo de números de parte que el libro ya conoce (para el texto grabado)
            catalogo = []
            columnas_catalogo = [mapa["dashboard_part_number"]]
            if "module_part_number" in mapa:      # el módulo también aporta números de parte
                columnas_catalogo.append(mapa["module_part_number"])
            for origen in (hoja, hoja_ref):
                for fila in range(8, origen.max_row + 1):
                    for columna in columnas_catalogo:
                        valor = origen.cell(fila, columna).value
                        texto = str(valor or "").strip()
                        # sólo números de parte de verdad: en el libro hay filas de otras hojas
                        # con «Promedio», «#REF!» o medidas, y eso no es catálogo
                        if texto and PATRON_PARTE_CATALOGO.match(texto) and texto not in catalogo:
                            catalogo.append(texto)
            for numero, rutas in fotos_por_caso.items():
                salida_caso = leer_fotos(rutas, motor=motor_ocr,
                                        carpeta_evidencia=Path(args.fotos) / "_recortes_etiquetas",
                                        caso=numero, catalogo=catalogo)
                etiquetas[numero] = salida_caso
                print(f"  caso {numero}: {salida_caso.fotos} foto(s), {len(salida_caso.campos)} "
                      f"campo(s) leído(s) de etiqueta, {len(salida_caso.dudas)} duda(s)")
                for duda in salida_caso.dudas:
                    registro_dudas.append({"caso": numero, **duda})
                pizarra_caso = leer_pizarra_de_caso(numero, rutas,
                                                    Path(args.fotos) / "_recortes_pizarra",
                                                    aprendizaje=aprendizaje_pizarra,
                                                    motor=motor_ocr)
                if pizarra_caso:
                    pizarras[numero] = pizarra_caso
        else:
            print(f"no existe la carpeta de fotos: {raiz_fotos}")

    # 1-ter) evidencia del módulo PAB (dos códigos de la etiqueta + estampa del nivel)
    tableros: dict[str, dict] = {}
    if args.tablero_json and Path(args.tablero_json).exists():
        tableros = json.loads(Path(args.tablero_json).read_text(encoding="utf-8"))
        for numero, datos in sorted(tableros.items()):
            print(f"  caso {numero}: (tablero) parte={datos.get('dashboard_part_number') or '?'} "
                  f"serie={datos.get('dashboard_serial_number') or '?'} "
                  f"fecha={datos.get('dashboard_date') or '?'} "
                  f"nivel={datos.get('dashboard_engineering_level') or '?'}")

    modulos: dict[str, dict] = {}
    if args.modulo_json:
        modulos = json.loads(Path(args.modulo_json).read_text(encoding="utf-8"))
        for numero, datos in sorted(modulos.items()):
            print(f"  caso {numero}: (del JSON del módulo) parte={datos.get('part_number') or '?'} "
                  f"serie={datos.get('serial_number') or '?'} fecha={datos.get('date') or '?'} "
                  f"nivel={datos.get('engineering_level') or '?'}"
                  + (" · PROTOTIPO" if datos.get("prototipo") else ""))
            if datos.get("prototipo"):
                registro_dudas.append({
                    "caso": numero, "campo": "engineering_level", "motivo": "prototipo",
                    "valor": datos.get("engineering_level") or "",
                    "detalle": ("la etiqueta es de prototipo (en inglés): el nivel no se apoya en las "
                                "demás carpetas, se escribe sólo la lectura propia"),
                    "imagen": datos.get("captura", ""),
                    "opciones": [{"valor": datos.get("engineering_level"), "fuente": "lectura_propia",
                                  "detalle": "nivel de la estampa de esta carpeta"},
                                 {"valor": None, "fuente": "vacio", "detalle": "dejar vacío"}],
                })
            if datos.get("nivel_sin_estampa"):
                registro_dudas.append({
                    "caso": numero, "campo": "engineering_level", "motivo": "sin_estampa",
                    "valor": datos.get("engineering_level") or "",
                    "detalle": ("el módulo no trae la pegatina amarilla del nivel: se escribe el "
                                "nivel de partida 01S; si el módulo llevaba estampa, corregir"),
                    "imagen": datos.get("captura", ""),
                    "opciones": [{"valor": datos.get("engineering_level"), "fuente": "nivel_de_partida",
                                  "detalle": "nivel de partida (sin estampa en las fotos)"},
                                 {"valor": None, "fuente": "vacio", "detalle": "dejar vacío"}],
                })
            CAMPO_DEL_LIBRO = {"part_number": "module_part_number", "date": "module_date",
                               "serial_number": "module_serial_number",
                               "module_version": "module_version",
                               "engineering_level": "engineering_level"}
            for discrepancia in datos.get("discrepancias") or []:
                registro_dudas.append({
                    "caso": numero,
                    "campo": CAMPO_DEL_LIBRO.get(discrepancia.get("campo"),
                                                 "module_serial_number"),
                    "motivo": "dos_codigos_discrepan",
                    "valor": " / ".join(str(v) for v in discrepancia.get("valores") or []),
                    "detalle": (f"en la foto {discrepancia.get('foto')} una parte de la etiqueta dice "
                                f"una cosa y la otra dice otra; se escribió lo que se repite en el "
                                f"resto de fotos de la carpeta"),
                    "imagen": datos.get("captura", ""),
                    "opciones": [{"valor": valor, "fuente": "lectura_en_la_etiqueta",
                                  "detalle": "una de las dos lecturas de esa foto"}
                                 for valor in (discrepancia.get("valores") or [])]
                                or [{"valor": None, "fuente": "vacio", "detalle": "dejar vacío"}],
                })

    # 2) evidencia de la barra del vídeo
    evidencia: dict[str, dict] = {}
    cabeceras: dict[str, dict] = {}
    if args.video_json:
        datos = json.loads(Path(args.video_json).read_text(encoding="utf-8"))
        for numero, fila_video in datos.items():
            evidencia[numero] = {
                "test_number": {"valor": (fila_video.get("numero_barra")
                                          if str(fila_video.get("numero_barra") or "") == str(numero)
                                          else "")},
                "test_date": {"valor": fila_video.get("fecha") or ""},
                "test_place": {"valor": fila_video.get("lugar_barra") or ""},
                "__resumen__": {"texto": fila_video.get("texto_barra") or "",
                                "videos": len(fila_video.get("videos") or [])},
            }
            if fila_video.get("lugar"):
                cabeceras[numero] = {"lugar": fila_video["lugar"],
                                     "lugar_leido": fila_video.get("lugar_leido", ""),
                                     "lugar_barra": fila_video.get("lugar_barra", ""),
                                     "captura": fila_video.get("captura", ""),
                                     "votos": {"json": 1}}
                print(f"  caso {numero}: (del JSON) fecha={fila_video.get('fecha') or '?'} "
                      f"lugar={fila_video['lugar']} «{fila_video.get('lugar_leido') or ''}»")
    elif args.casos:
        banco = cargar_banco(Path(__file__).resolve().parent / "aprendizaje" / "barra_estado.json")
        casos = mapa_de_casos(Path(args.casos), set(filas_con_caso(hoja, col_numero)))
        motor_cabecera = motor_ocr if not args.sin_cabecera else None
        for numero, rutas in casos.items():
            evidencia[numero] = leer_caso(rutas, banco)
            if motor_cabecera is None:
                continue
            lectura = leer_cabecera_de_caso(numero, rutas, motor_cabecera,
                                            Path(args.casos) / "_capturas_video",
                                            evidencia.get(numero) or {})
            if lectura:
                cabeceras[numero] = lectura
                print(f"  caso {numero}: lugar de la cabecera = {lectura.get('lugar') or '?'} "
                      f"(«{lectura.get('lugar_leido') or 'sin leer'}»)")

    filas = filas_con_caso(hoja, col_numero)
    registro, escritas, ocupadas = [], 0, 0

    aplicados: list[dict] = []

    def escribir(campo, fila, valor, origen, extra=None):
        nonlocal escritas, ocupadas
        columna = mapa.get(campo)
        if not columna:
            return
        celda = hoja.cell(fila, columna)
        if celda.value not in (None, ""):
            ocupadas += 1
            return
        if not args.simular:
            if args.fechas_texto and isinstance(valor, (datetime, date)):
                valor = valor.strftime("%Y-%m-%d") if hasattr(valor, "strftime") else str(valor)
            celda.value = valor
            if isinstance(valor, str) and args.fechas_texto:
                celda.number_format = "@"
            if isinstance(valor, (datetime, date)):
                # sin esto Excel enseña el número de serie (`45827`) en lugar de la fecha
                celda.number_format = formato_de_fecha(hoja, columna)
            aplicados.append({"numero": fila_numero, "campo": campo, "valor": valor})
        escritas += 1
        registro.append({"caso": fila_numero, "campo": campo, "valor": str(valor),
                         "origen": origen, **(extra or {})})

    # primero las constantes (rellenan lo que no depende del caso)
    # por defecto las columnas de etiqueta NO se copian de constantes: se leen de las fotos
    # PRIMERO el motivo de prueba, leído de la pizarra escrita a mano (la constante es respaldo)
    # el motivo de prueba sale de la **pizarra escrita a mano**, nunca copiado del libro
    if pizarras:
        motivos_libro = [str(hoja_ref.cell(f, mapa["test_reason"]).value or "").strip()
                         for f in range(8, hoja_ref.max_row + 1)
                         if hoja_ref.cell(f, mapa["test_reason"]).value not in (None, "")]
        vocabulario = pizarra.motivo_del_libro(motivos_libro)
        vocabulario_aprendido = aprendizaje_pizarra
        for numero, fila in sorted(filas.items()):
            fila_numero = numero
            lectura = pizarras.get(numero) or {}
            if not lectura.get("proyecto"):
                # segunda fuente del proyecto: la barra del vídeo (`EDAG Mex BMG`)
                texto_barra = ((evidencia.get(numero) or {}).get("__resumen__") or {}).get("texto", "")
                proyecto_barra = pizarra.proyecto_en_barra(texto_barra)
                if proyecto_barra:
                    lectura.setdefault("faltan", [])
                    lectura.setdefault("lineas", [])
                    lectura.update({"proyecto": proyecto_barra, "proyecto_leido": "barra_video",
                                    "fuente_proyecto": "barra_video", "captura": lectura.get("captura", "")})
                    lectura = pizarra.completar_con_lo_aprendido(lectura, vocabulario_aprendido)
            if not lectura.get("proyecto") and not lectura.get("tipo_prueba"):
                continue
            motivo = lectura.get("motivo") or ""
            procedencia = "pizarra"
            if not motivo and lectura.get("proyecto") and vocabulario["tipos"]:
                # el proyecto sí se ha leído; el tipo de prueba viene del vocabulario del libro
                motivo = f"{vocabulario['tipos'][0]} {lectura['proyecto']}"
                procedencia = "pizarra_proyecto_mas_vocabulario"
            if not motivo:
                registro_dudas.append({
                    "caso": numero, "campo": "test_reason", "motivo": "pizarra_incompleta",
                    "valor": lectura.get("proyecto") or "",
                    "detalle": ("la pizarra se lee a medias: "
                                f"falta {', '.join(lectura.get('faltan') or [])}"),
                    "imagen": lectura.get("captura", ""),
                    "opciones": [{"valor": " ".join(vocabulario["tipos"][:1] + [lectura["proyecto"]])
                                  if lectura.get("proyecto") else None,
                                  "fuente": "pizarra_tipo_libro",
                                  "detalle": "proyecto leído en la pizarra + tipo de prueba del libro"},
                                 {"valor": None, "fuente": "vacio", "detalle": "dejar vacío"}],
                })
                continue
            escribir("test_reason", fila, motivo, "pizarra",
                     {"proyecto_leido": lectura.get("proyecto_leido"),
                      "tipo_leido": lectura.get("tipo_leido"), "procedencia": procedencia,
                      "captura": lectura.get("captura", ""), "numero_pizarra": lectura.get("numero"),
                      "temperatura": lectura.get("temperatura")})


    bloqueadas = set(CAMPOS_BARRA) | (set() if args.constantes_completas else CAMPOS_DE_ETIQUETA)
    for numero, fila in sorted(filas.items()):
        fila_numero = numero
        for campo, dato in const.items():
            if campo in bloqueadas:
                continue          # lo resuelve la evidencia, no la constante
            valor = dato["valor"]
            if isinstance(valor, datetime):
                valor = valor.date()
            veredicto = evaluar(campo, valor if not isinstance(valor, (date,)) else valor.isoformat())
            if not veredicto.escribible:
                registro.append({"caso": numero, "campo": campo, "resultado": "no_pasa_protocolo",
                                 "valor": str(valor)})
                continue
            escribir(campo, fila, valor, "constante_libro", {"casos_constantes": dato["casos"]})

    fechas_del_modulo = Counter(str((d or {}).get("date")) for d in modulos.values()
                                if (d or {}).get("date"))
    if len(fechas_del_modulo) > 1:
        fecha_comun = fechas_del_modulo.most_common(1)[0][0]
        for numero, datos in modulos.items():
            if str(datos.get("date")) != fecha_comun:
                registro_dudas.append({
                    "caso": numero, "campo": "module_date", "motivo": "fecha_discrepa",
                    "valor": datos.get("date") or "",
                    "detalle": (f"la etiqueta de esta carpeta dice {datos.get('date')}; las demás "
                                f"carpetas dicen {fecha_comun}"),
                    "imagen": datos.get("captura", ""),
                    "opciones": [{"valor": datos.get("date"), "fuente": "lectura_propia",
                                  "detalle": "lo que dice la etiqueta de esta carpeta"},
                                 {"valor": fecha_comun, "fuente": "consenso_entre_carpetas",
                                  "detalle": "lo que dicen las demás carpetas"}],
                })

    # el proveedor del generador: si la etiqueta lo imprime en vertical, se lee y se contrasta
    for numero, fila in sorted(filas.items()):
        fila_numero = numero
        datos = modulos.get(numero) or {}
        leido = datos.get("inflator_supplier")
        if not leido or not mapa.get("inflator_supplier"):
            continue
        celda = hoja.cell(fila, mapa["inflator_supplier"])
        if celda.value not in (None, ""):
            if str(celda.value).strip().lower() == str(leido).strip().lower():
                registro.append({"caso": numero, "campo": "inflator_supplier",
                                 "resultado": "corroborado_por_etiqueta", "valor": str(leido),
                                 "origen": "etiqueta_texto_vertical",
                                 "texto": (datos.get("proveedor") or {}).get("texto", "")})
            else:
                registro_dudas.append({
                    "caso": numero, "campo": "inflator_supplier", "motivo": "proveedor_discrepa",
                    "valor": str(celda.value),
                    "detalle": (f"el libro dice {celda.value}; la etiqueta imprime {leido} "
                                f"«{(datos.get('proveedor') or {}).get('texto', '')}»"),
                    "imagen": datos.get("captura", ""),
                    "opciones": [{"valor": str(leido), "fuente": "etiqueta",
                                  "detalle": "lo que imprime la etiqueta en vertical"},
                                 {"valor": str(celda.value), "fuente": "libro",
                                  "detalle": "dejar lo que dice el libro"}],
                })
            continue
        veredicto = evaluar("inflator_supplier", leido)
        if veredicto.escribible:
            escribir("inflator_supplier", fila, a_valor_de_celda("inflator_supplier", veredicto.valor),
                     "etiqueta_texto_vertical",
                     {"texto": (datos.get("proveedor") or {}).get("texto", ""),
                      "giro": (datos.get("proveedor") or {}).get("giro")})

    # sintaxis del nivel: `##K` con estampa y `##S` sin ella (lo que usa el libro)
    for numero, datos in sorted(modulos.items()):
        nivel = datos.get("engineering_level")
        if not nivel:
            continue
        con_estampa = not datos.get("nivel_sin_estampa")
        if not CM.nivel_correcto_por_sintaxis(nivel, con_estampa):
            registro_dudas.append({
                "caso": numero, "campo": "engineering_level", "motivo": "nivel_fuera_de_sintaxis",
                "valor": nivel,
                "detalle": (f"«{nivel}» no sigue la sintaxis del libro: ##K cuando el módulo lleva "
                            f"estampa y ##S cuando no la lleva "
                            f"(aquí {'sí' if con_estampa else 'no'} lleva estampa)"),
                "imagen": datos.get("captura", ""),
                "opciones": [{"valor": nivel, "fuente": "lectura",
                              "detalle": "dejar lo leído"},
                             {"valor": None, "fuente": "vacio", "detalle": "dejar vacío"}],
            })

    # el tablero: lo que se repite entre carpetas vale como corroboración (misma regla que en el
    # módulo). La fecha y el nivel del tablero son los de la pieza, no los del caso: si nueve
    # carpetas dicen lo mismo, esa es la lectura buena y la que discrepa sale como duda.
    # se cuenta **cada lectura**, no cada carpeta: una carpeta con cuatro fotos que dicen lo mismo
    # pesa más que otra con una sola
    fechas_tablero: Counter = Counter()
    niveles_tablero: Counter = Counter()
    for datos_tablero in tableros.values():
        for valor, cuantos in ((datos_tablero.get("votos") or {}).get("dashboard_date") or {}).items():
            fechas_tablero[str(valor)] += int(cuantos)
        for valor, cuantos in ((datos_tablero.get("votos") or {})
                               .get("dashboard_engineering_level") or {}).items():
            niveles_tablero[str(valor)] += int(cuantos)
    partes_tablero: Counter = Counter()
    for datos_tablero in tableros.values():
        for valor, cuantos in ((datos_tablero.get("votos") or {})
                               .get("dashboard_part_number") or {}).items():
            if str(valor).startswith("2GJ.857."):
                partes_tablero[str(valor)] += int(cuantos)
    parte_tablero_comun = partes_tablero.most_common(1)[0][0] if partes_tablero else ""
    if parte_tablero_comun:
        print(f"  tablero: número de parte leído en las fotos = {parte_tablero_comun} "
              f"({len(partes_tablero)} carpeta(s))")
    fecha_tablero_comun = fechas_tablero.most_common(1)[0][0] if fechas_tablero else ""
    nivel_tablero_comun = niveles_tablero.most_common(1)[0][0] if niveles_tablero else ""
    if fecha_tablero_comun:
        print(f"  tablero: fecha que se repite en las fotos = {fecha_tablero_comun} "
              f"({dict(fechas_tablero.most_common(3))})")
    if nivel_tablero_comun:
        print(f"  tablero: nivel que se repite en las fotos = {nivel_tablero_comun} "
              f"({dict(niveles_tablero.most_common(3))})")

    # el tablero de instrumentos: las cuatro columnas que se leen de SUS etiquetas (P30)
    CAMPOS_DEL_TABLERO = ("dashboard_part_number", "dashboard_serial_number", "dashboard_date",
                          "dashboard_engineering_level")
    for numero, fila in sorted(filas.items()):
        fila_numero = numero
        datos = tableros.get(numero) or {}
        if not datos:
            continue
        sin_leer: list[str] = []
        for campo in CAMPOS_DEL_TABLERO:
            valor_crudo = datos.get(campo)
            fuente = (datos.get("fuente") or {}).get(campo) or {}
            dudoso = bool((datos.get("dudoso") or {}).get(campo))
            if valor_crudo in (None, ""):
                sin_leer.append(campo)
                continue
            # la fecha y el nivel se sostienen si coinciden con lo que dicen las demás carpetas
            if campo == "dashboard_date" and fecha_tablero_comun:
                if str(valor_crudo) != fecha_tablero_comun:
                    # si las fotos de esta misma carpeta también leyeron la fecha común, esa manda
                    votos_del_caso = datos.get("votos", {}).get(campo) or {}
                    if fecha_tablero_comun in votos_del_caso:
                        valor_crudo = fecha_tablero_comun
                        fuente = dict(fuente, origen=str(fuente.get("origen", "")) +
                                      " (y la fecha común en otra foto)")
                    registro_dudas.append({
                        "caso": numero, "campo": campo, "motivo": "tablero_fecha_discrepa",
                        "valor": str(valor_crudo),
                        "detalle": (f"la etiqueta de esta carpeta dice {valor_crudo}; las demás "
                                    f"carpetas del tablero dicen {fecha_tablero_comun}"),
                        "imagen": fuente.get("captura", ""),
                        "opciones": [{"valor": str(valor_crudo), "fuente": "lectura_propia",
                                      "detalle": "lo que dice la etiqueta de esta carpeta"},
                                     {"valor": fecha_tablero_comun,
                                      "fuente": "consenso_entre_carpetas",
                                      "detalle": "lo que dicen las demás carpetas"}],
                    })
                    continue
                dudoso = False                     # corroborado por las demás carpetas
            if campo == "dashboard_engineering_level" and nivel_tablero_comun:
                if str(valor_crudo) != nivel_tablero_comun:
                    registro_dudas.append({
                        "caso": numero, "campo": campo, "motivo": "tablero_nivel_discrepa",
                        "valor": str(valor_crudo),
                        "detalle": (f"la estampa de esta carpeta dice {valor_crudo}; las demás "
                                    f"carpetas dicen {nivel_tablero_comun}"),
                        "imagen": fuente.get("captura", ""),
                        "opciones": [{"valor": str(valor_crudo), "fuente": "lectura_propia",
                                      "detalle": "lo que dice la estampa de esta carpeta"},
                                     {"valor": nivel_tablero_comun,
                                      "fuente": "consenso_entre_carpetas",
                                      "detalle": "lo que dicen las demás carpetas"}],
                    })
                    continue
                dudoso = False
            if dudoso:
                # la lectura no se sostiene entre fotos: no se escribe a ciegas
                registro_dudas.append({
                    "caso": numero, "campo": campo, "motivo": "tablero_dudoso",
                    "valor": str(valor_crudo),
                    "detalle": (f"las fotos del tablero no coinciden entre sí "
                                f"({datos.get('votos', {}).get(campo, {})}); entre ellas "
                                f"{fuente.get('foto', '?')} de {fuente.get('carpeta', '?')}"),
                    "imagen": fuente.get("captura", ""),
                    "opciones": [{"valor": str(valor_crudo), "fuente": "consenso_entre_fotos",
                                  "detalle": "lo que más se repite en las fotos"},
                                 {"valor": None, "fuente": "vacio",
                                  "detalle": "dejar la celda vacía"}],
                })
                continue
            # el código del PAB no es el del tablero: si la lectura coincide con la parte del
            # módulo, es que se ha leído la etiqueta equivocada (misma protección que el `ZRZ`
            # en la serie)
            if campo == "dashboard_part_number":
                parte_modulo = (modulos.get(numero) or {}).get("part_number")
                if parte_modulo and _compacto(str(valor_crudo)) == _compacto(str(parte_modulo)):
                    registro_dudas.append({
                        "caso": numero, "campo": campo, "motivo": "tablero_parte_igual_al_modulo",
                        "valor": str(valor_crudo),
                        "detalle": (f"la lectura coincide con el número de parte del módulo "
                                    f"({parte_modulo}); el tablero lleva el suyo, así que la foto "
                                    f"era del PAB"),
                        "imagen": fuente.get("captura", ""),
                        "opciones": [{"valor": None, "fuente": "vacio", "detalle": "dejar vacío"}],
                    })
                    continue
            veredicto = evaluar(campo, valor_crudo)
            if not veredicto.escribible:
                registro.append({"caso": numero, "campo": campo, "resultado": "no_pasa_protocolo",
                                 "valor": str(valor_crudo), "estado": veredicto.estado})
                continue
            valor = a_valor_de_celda(campo, veredicto.valor)
            if valor is None:
                continue
            escribir(campo, fila, valor, "etiqueta_del_tablero",
                     {"foto": fuente.get("foto", ""), "carpeta": fuente.get("carpeta", ""),
                      "lecturas": fuente.get("lecturas", 0),
                      "texto": fuente.get("origen", "")})
        if sin_leer:
            registro_dudas.append({
                "caso": numero, "campo": ", ".join(sin_leer), "motivo": "tablero_sin_lectura",
                "valor": "",
                "detalle": ("no hay lectura que se sostenga en las fotos para: "
                            + ", ".join(sin_leer) + " (la celda queda vacía)"),
                "imagen": next((((datos.get("fuente") or {}).get(c) or {}).get("captura", "")
                                for c in sin_leer
                                if ((datos.get("fuente") or {}).get(c) or {}).get("captura")), ""),
                "opciones": ([{"valor": parte_tablero_comun,
                               "fuente": "leido_en_otras_carpetas",
                               "detalle": "el número de parte moldeado que sí se leyó en las "
                                          "fotos de las otras carpetas"}]
                             if parte_tablero_comun and "dashboard_part_number" in sin_leer else [])
                            + [{"valor": None, "fuente": "vacio", "detalle": "dejar vacío"}],
            })

    # el tipo de generador: nombre de la carpeta + barra del vídeo (dos fuentes, una celda)
    for numero, fila in sorted(filas.items()):
        fila_numero = numero
        datos = modulos.get(numero) or {}
        de_carpeta = arreglar_generador(datos.get("inflator_type"))
        de_barra = generador_en_barra((evidencia.get(numero) or {}).get("__resumen__", {}).get("texto", ""))
        if not de_carpeta and not de_barra:
            continue
        if de_carpeta and de_barra and de_carpeta != de_barra:
            registro_dudas.append({
                "caso": numero, "campo": "inflator_type", "motivo": "generador_discrepa",
                "valor": de_carpeta,
                "detalle": (f"la carpeta dice {de_carpeta} y la barra del vídeo dice {de_barra}"),
                "imagen": datos.get("captura", ""),
                "opciones": [{"valor": de_carpeta, "fuente": "nombre_de_carpeta",
                              "detalle": "lo que dice la carpeta del caso"},
                             {"valor": de_barra, "fuente": "barra_del_video",
                              "detalle": "lo que imprime la barra del vídeo"}],
            })
            continue
        valor = de_carpeta or de_barra
        celda_actual = hoja.cell(fila, mapa["inflator_type"]).value if mapa.get("inflator_type") else None
        if celda_actual not in (None, "") and str(celda_actual).strip().upper() != valor:
            # el libro ya trae otro valor: no se toca, pero se avisa si contradice a las dos fuentes
            registro_dudas.append({
                "caso": numero, "campo": "inflator_type", "motivo": "generador_contra_el_libro",
                "valor": str(celda_actual),
                "detalle": (f"el libro tiene {celda_actual}; la carpeta del caso y/o la barra del "
                            f"vídeo dicen {valor}"),
                "imagen": datos.get("captura", ""),
                "opciones": [{"valor": valor, "fuente": "carpeta_mas_barra",
                              "detalle": "las dos fuentes del caso coinciden"},
                             {"valor": str(celda_actual), "fuente": "libro",
                              "detalle": "dejar lo que ya tiene el libro"}],
            })
            continue
        veredicto = evaluar("inflator_type", valor)
        if not veredicto.escribible:
            continue
        origen = "carpeta_mas_barra" if (de_carpeta and de_barra) else (
            "nombre_de_carpeta" if de_carpeta else "barra_del_video")
        escribir("inflator_type", fila, a_valor_de_celda("inflator_type", veredicto.valor), origen,
                 {"carpeta": de_carpeta, "barra": de_barra,
                  "texto_barra": (evidencia.get(numero) or {}).get("__resumen__", {}).get("texto", "")})

    # la etiqueta del módulo PAB: lo primero que se escribe, porque es la lectura propia de la carpeta
    CAMPOS_DEL_MODULO = (("part_number", "module_part_number"),
                         ("module_version", "module_version"),
                         ("serial_number", "module_serial_number"),
                         ("date", "module_date"),
                         ("engineering_level", "engineering_level"))
    for numero, fila in sorted(filas.items()):
        fila_numero = numero
        datos = modulos.get(numero) or {}
        if not datos:
            continue
        for clave_json, campo in CAMPOS_DEL_MODULO:
            valor_crudo = datos.get(clave_json)
            if valor_crudo in (None, ""):
                continue
            # el código del PAB no es el del tablero: si la lectura coincide con la parte del
            # módulo, es que se ha leído la etiqueta equivocada (misma protección que el `ZRZ`
            # en la serie)
            if campo == "dashboard_part_number":
                parte_modulo = (modulos.get(numero) or {}).get("part_number")
                if parte_modulo and _compacto(str(valor_crudo)) == _compacto(str(parte_modulo)):
                    registro_dudas.append({
                        "caso": numero, "campo": campo, "motivo": "tablero_parte_igual_al_modulo",
                        "valor": str(valor_crudo),
                        "detalle": (f"la lectura coincide con el número de parte del módulo "
                                    f"({parte_modulo}); el tablero lleva el suyo, así que la foto "
                                    f"era del PAB"),
                        "imagen": fuente.get("captura", ""),
                        "opciones": [{"valor": None, "fuente": "vacio", "detalle": "dejar vacío"}],
                    })
                    continue
            veredicto = evaluar(campo, valor_crudo)
            if not veredicto.escribible:
                registro.append({"caso": numero, "campo": campo, "resultado": "no_pasa_protocolo",
                                 "valor": str(valor_crudo), "estado": veredicto.estado})
                continue
            valor = a_valor_de_celda(campo, veredicto.valor)
            if valor is None:
                continue
            escribir(campo, fila, valor, "etiqueta_modulo",
                     {"fuente": (datos.get("fuente_nivel") or {}).get(campo, ""),
                      "fuerza": (datos.get("fuerza") or {}).get(clave_json, ""),
                      "fotos": datos.get("fotos_con_modulo"),
                      "prototipo": bool(datos.get("prototipo")),
                      "sin_estampa": bool(datos.get("nivel_sin_estampa")),
                      "captura": datos.get("captura", "")})

    # después las etiquetas leídas con anclas
    for numero, fila in sorted(filas.items()):
        fila_numero = numero
        lectura = etiquetas.get(numero)
        if not lectura:
            continue
        for campo, dato in lectura.campos.items():
            if dato.get("dudoso"):
                registro.append({"caso": numero, "campo": campo, "resultado": "dudoso_etiqueta",
                                 "valor": dato["valor"], "recorte": dato.get("recorte", "")})
                continue
            veredicto = evaluar(campo, dato["valor"])
            if not veredicto.escribible:
                registro.append({"caso": numero, "campo": campo, "resultado": "no_pasa_protocolo",
                                 "valor": dato["valor"], "estado": veredicto.estado})
                continue
            valor = a_valor_de_celda(campo, veredicto.valor)
            if valor is None:
                continue
            escribir(campo, fila, valor, "etiqueta_ocr",
                     {"confianza": dato.get("confianza"), "ancla": dato.get("ancla"),
                      "recorte": dato.get("recorte", "")})


    # el lugar de prueba viene de la cabecera del vídeo (`EDAG Testlab`), no de la barra
    for numero, fila in sorted(filas.items()):
        fila_numero = numero
        lectura = cabeceras.get(numero)
        if not lectura:
            continue
        lugar = lectura.get("lugar") or ""
        del_barra = str(lectura.get("lugar_barra") or "").strip()
        if del_barra and lugar and normalizar_lugar(del_barra) != lugar:
            registro_dudas.append({"caso": numero, "campo": "test_place", "motivo": "lugar_discrepa",
                                   "valor": lugar, "detalle": f"cabecera {lugar} / barra {del_barra}",
                                   "imagen": lectura.get("captura", "")})
            continue
        if not lugar:
            registro.append({"caso": numero, "campo": "test_place", "resultado": "cabecera_no_legible",
                             "valor": lectura.get("lugar_leido", "")})
            continue
        veredicto = evaluar("test_place", lugar)
        if not veredicto.escribible:
            registro.append({"caso": numero, "campo": "test_place", "resultado": "no_pasa_protocolo",
                             "valor": lugar, "estado": veredicto.estado})
            continue
        escribir("test_place", fila, a_valor_de_celda("test_place", veredicto.valor), "video_cabecera",
                 {"lugar_leido": lectura.get("lugar_leido"), "votos": lectura.get("votos"),
                  "captura": lectura.get("captura", "")})

    # después la barra del vídeo de cada caso
    for numero, fila in sorted(filas.items()):
        fila_numero = numero
        campos = evidencia.get(numero) or {}
        barra_numero = (campos.get("test_number") or {}).get("valor")
        if campos and barra_numero and barra_numero != numero:
            registro.append({"caso": numero, "campo": "*", "resultado": "barra_de_otro_ensayo",
                             "valor": barra_numero})
            continue
        for campo in ("test_date", "test_place", "temperature_condition", "delay_ms", "inflator_type"):
            dato = campos.get(campo)
            if not dato:
                continue
            if dato.get("acuerdo", 1.0) < 0.6:
                registro.append({"caso": numero, "campo": campo, "resultado": "acuerdo_bajo",
                                 "valor": dato["valor"]})
                continue
            leido = aplicar_convencion(campo, dato["valor"])
            veredicto = evaluar(campo, leido)
            if not veredicto.escribible:
                registro.append({"caso": numero, "campo": campo, "resultado": "no_pasa_protocolo",
                                 "valor": dato["valor"], "estado": veredicto.estado})
                continue
            valor = a_valor_de_celda(campo, leido)
            if valor is None:
                continue
            escribir(campo, fila, valor, "barra_video",
                     {"acuerdo": dato.get("acuerdo"), "video": dato.get("video"),
                      "leido": dato["valor"], "convencion": str(leido) != str(dato["valor"])})

    # lo que se repite en las pizarras de esta carpeta se guarda como aprendizaje para las próximas
    if pizarras:
        try:
            ruta_aprendizaje = pizarra.guardar_aprendizaje(
                pizarra.aprender_de_lecturas(list(pizarras.values())))
            print(f"  aprendizaje de pizarra: {ruta_aprendizaje}")
        except OSError as error:
            print(f"  no se pudo guardar el aprendizaje de pizarra: {error}")

    # al final la semana: primero la estructura del número de prueba (guía, pág. 2), corroborada
    # con la semana ISO de la fecha de prueba cuando la fecha existe
    col_fecha = mapa["test_date"]
    for numero, fila in sorted(filas.items()):
        fila_numero = numero
        celda_semana = hoja.cell(fila, mapa["week"])
        if celda_semana.value not in (None, ""):
            ocupadas += 1
            continue
        fecha = hoja.cell(fila, col_fecha).value
        semana, como = semana_del_numero(numero, fecha)
        if semana is None and not fecha:
            como = como or "sin_fecha"
        if semana is None:
            semana_iso_suelta = semana_iso(fecha) if fecha is not None else None
            if semana_iso_suelta:
                escribir("week", fila, semana_iso_suelta, "semana_iso", {"como": como})
            else:
                registro.append({"caso": numero, "campo": "week", "resultado": "no_se_pudo", "valor": como})
            continue
        escribir("week", fila, semana, "numero_prueba", {"como": como})

    if args.fechas_texto and not args.simular:
        convertidas = fechas_a_texto(libro, hoja, mapa, fila_encabezado=7)
        if convertidas:
            print(f"  fechas convertidas a texto ISO: {convertidas}")

    replicadas, hojas_replicadas = 0, []
    if not args.simular:
        replicadas, hojas_replicadas = replicar_en_otras_hojas(libro, hoja, aplicados)
        libro.save(salida)
    print(f"celdas escritas: {escritas} · ocupadas respetadas: {ocupadas} · "
          f"constantes disponibles: {len(const)}")
    if hojas_replicadas:
        print(f"  replicadas en hojas espejo: {replicadas} ({', '.join(hojas_replicadas)})")
    por_origen = Counter(r["origen"] for r in registro if "origen" in r)
    print(f"  por origen: {dict(por_origen)}")
    for r in registro:
        if r.get("origen"):
            print(f"  + {r['caso']} {r['campo']:28s} = {r['valor']!r} [{r['origen']}]")
    if args.informe:
        Path(args.informe).write_text(json.dumps({
            "libro_entrada": str(entrada), "salida": None if args.simular else str(salida),
            "constantes": {k: str(v["valor"]) for k, v in const.items()},
            "celdas_escritas": escritas, "ocupadas": ocupadas,
            "hojas_replicadas": hojas_replicadas, "celdas_replicadas": replicadas,
            "detalle": registro,
            "dudas": registro_dudas,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
