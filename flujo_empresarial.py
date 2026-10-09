"""Descubrimiento, normalización y consolidación del flujo OCR empresarial.

Este módulo no reemplaza el pipeline histórico. Reconoce casos con la forma
``<ID> <VERSIÓN> <INFLADOR> <TEMPERATURA>`` y entrega unidades autocontenidas
que el orquestador puede procesar de forma optimizada o enviar al flujo legacy.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from utilidades.persistencia import escribir_json_seguro
from utilidades.identidad import proyecto_id as resolver_proyecto_id, identidad_caso


PATRON_CASO = re.compile(
    r"^(?P<id>\d+)\s+(?P<version>RDW|RWD|NAR)\s+"
    r"(?P<inflator>NOM|OGL|UGL)\s+(?P<temperature>HT|NT|RT)$",
    re.IGNORECASE,
)
PATRON_TOR = re.compile(r"^TOR\s+(.+)$", re.IGNORECASE)
EXTENSIONES_IMAGEN = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
EXTENSIONES_VIDEO = {".avi", ".mp4", ".mov", ".mkv", ".wmv", ".m4v"}
VERSION_PARSER = "empresarial-6-guia-motivo-prototipos"

CLAVES_PLANTILLA = (
    "week", "test_reason", "test_number", "test_date", "test_place",
    "temperature_condition", "module_part_number", "module_version",
    "module_serial_number", "module_date", "engineering_level", "delay_ms",
    "inflator_type", "inflator_supplier", "dashboard_part_number",
    "dashboard_serial_number", "dashboard_date", "dashboard_engineering_level",
    "laser_opening", "dashboard_supplier", "cushion_evaluation",
    "housing_evaluation", "protective_cover_evaluation", "opening_time_ms",
    "forvia_measurement_ms", "full_inflation_time_ms", "second_review",
    "pab_comments", "pab_zsb_evaluation", "dashboard_comments",
    "dashboard_zsb_evaluation", "test_environment_comments",
    "overall_system_evaluation", "reserved_ah",
    "housing_sidewall_stress_whitening", "housing_inner_stress_whitening",
)

CAMPOS_REQUERIDOS_DEFAULT = {
    "week", "test_reason", "test_number", "test_date", "test_place",
    "temperature_condition", "module_part_number", "module_version",
    "engineering_level", "delay_ms", "inflator_type", "inflator_supplier",
    "dashboard_part_number", "dashboard_supplier", "opening_time_ms",
    "full_inflation_time_ms", "overall_system_evaluation",
}

CAMPOS_APRENDIBLES = {
    "module_part_number", "module_version", "inflator_supplier",
    "dashboard_part_number", "dashboard_supplier", "engineering_level",
    "dashboard_engineering_level",
}

CAMPOS_NUNCA_HEREDAR = {
    "module_serial_number", "dashboard_serial_number", "test_date", "module_date",
    "dashboard_date", "opening_time_ms", "forvia_measurement_ms",
    "full_inflation_time_ms", "pab_comments", "dashboard_comments",
    "test_environment_comments", "cushion_evaluation", "housing_evaluation",
    "protective_cover_evaluation", "pab_zsb_evaluation",
    "dashboard_zsb_evaluation", "overall_system_evaluation", "reserved_ah",
    "housing_sidewall_stress_whitening", "housing_inner_stress_whitening",
}

REGLAS_CODIGO_VISIBLES = (
    "Los catálogos RDW/NAR, NOM/OGL/UGL y HT/RT/NT se aceptan por coincidencia exacta.",
    "Los números de parte deben tener bloques de letras o números separados y al menos un dígito.",
    "Un serial numérico necesita por lo menos cinco dígitos.",
    "Las oraciones, números cortos, unidades sueltas y símbolos aislados no llenan campos.",
    "Un valor sólo se consolida si coincide con una regla de campo, la ruta, un QR válido o evidencia corroborada.",
    "El componente visible o declarado distingue bolsa y tablero; un número compacto sólo llena tablero con ese contexto.",
    "EDAG Testlab o un número de prueba que empieza por VW identifica el laboratorio; VW AG en una etiqueta no lo identifica.",
    "La semana WW del número EDAG WWYYNN se contrasta con la fecha de prueba; no se aplica a otros laboratorios.",
    "Las fechas numéricas ambiguas requieren un formato explícito; los originales de etiquetas distintas se conservan.",
    "El nivel de ingeniería requiere componente; delay requiere una etiqueta explícita y no se deduce del número de parte.",
    "Proyecto/motivo explícitos pueden aportar Motivo de prueba; no copiar el nombre interno de carpeta sin evidencia.",
    "La apertura láser requiere confirmación propia; no se deduce del tiempo de ruptura ni del PN del tablero.",
    "Un P/N ALV de prototipo señalado como serie se conserva como candidato: necesita corroboración o confirmación humana.",
)


def clasificar_codigo_operativo(texto: str) -> dict:
    """Distingue códigos aprovechables de prosa o valores OCR espurios."""
    original = str(texto or "").strip()
    mayus = re.sub(r"\s+", " ", original.upper().replace("−", "-")).strip()
    if not mayus:
        return {"valido": False, "texto": original, "normalizado": "",
                "tipo": "vacio", "razon": "No contiene caracteres."}
    catalogos = {
        "RWD": ("RDW", "versión de módulo"), "ROW": ("RDW", "versión de módulo"),
        "N4R": ("NAR", "versión de módulo"), "RDW": ("RDW", "versión de módulo"),
        "NAR": ("NAR", "versión de módulo"), "NOM": ("NOM", "tipo de inflador"),
        "OGL": ("OGL", "tipo de inflador"), "UGL": ("UGL", "tipo de inflador"),
        "HT": ("HT", "temperatura"), "RT": ("RT", "temperatura"),
        "NT": ("NT", "temperatura"),
    }
    if mayus in catalogos:
        normalizado, nombre = catalogos[mayus]
        return {"valido": True, "texto": original, "normalizado": normalizado,
                "tipo": "catalogo", "razon": f"Coincide con el catálogo de {nombre}."}
    numero_parte = normalizar_numero_parte(mayus)
    if numero_parte:
        return {"valido": True, "texto": original, "normalizado": numero_parte,
                "tipo": "numero_parte", "razon": "Cumple el formato de número de parte."}
    compacto = re.sub(r"[^A-Z0-9._/-]", "", mayus)
    palabras = re.findall(r"[A-ZÁÉÍÓÚÑ]+", mayus)
    digitos = sum(caracter.isdigit() for caracter in compacto)
    letras = sum(caracter.isalpha() for caracter in compacto)
    if len(palabras) >= 3 and digitos == 0:
        return {"valido": False, "texto": original, "normalizado": compacto,
                "tipo": "oracion", "razon": "Es texto descriptivo, no un código."}
    if digitos == 0:
        return {"valido": False, "texto": original, "normalizado": compacto,
                "tipo": "texto", "razon": "No tiene dígitos ni coincide con un catálogo."}
    if re.fullmatch(r"[+-]?\d+(?:[.,]\d+)?(?:\s*(?:MS|°?C))?", mayus):
        if re.fullmatch(r"\d{5,}", mayus):
            return {"valido": True, "texto": original, "normalizado": mayus,
                    "tipo": "serial_numerico", "razon": "Es una secuencia de al menos cinco dígitos."}
        return {"valido": False, "texto": original, "normalizado": mayus,
                "tipo": "valor_numerico", "razon": "Es un valor aislado; requiere una etiqueta de campo."}
    if len(compacto) < 4:
        return {"valido": False, "texto": original, "normalizado": compacto,
                "tipo": "fragmento", "razon": "Es demasiado corto para considerarlo código."}
    if letras and digitos and re.fullmatch(r"[A-Z0-9._/-]+", compacto):
        return {"valido": True, "texto": original, "normalizado": compacto,
                "tipo": "alfanumerico", "razon": "Combina letras y números con separadores permitidos."}
    return {"valido": False, "texto": original, "normalizado": compacto,
            "tipo": "ruido", "razon": "No coincide con una regla de código conocida."}

ALIAS_QR_DEFAULT = {
    "test": "test_number", "test_number": "test_number", "id": "test_number",
    "date": "test_date", "test_date": "test_date", "fecha": "test_date",
    "temperature": "temperature_condition", "temperatura": "temperature_condition",
    "module_pn": "module_part_number", "module_part_number": "module_part_number",
    "module_sn": "module_serial_number", "module_serial_number": "module_serial_number",
    "dashboard_pn": "dashboard_part_number", "dashboard_part_number": "dashboard_part_number",
    "dashboard_sn": "dashboard_serial_number", "dashboard_serial_number": "dashboard_serial_number",
    "inflator": "inflator_type", "inflator_type": "inflator_type",
}


def interpretar_payload_qr(payload: str, aliases: dict | None = None) -> dict:
    """Interpreta texto QR localmente sin abrir URLs ni ejecutar contenido.

    Acepta JSON plano, ``clave=valor`` y ``clave:valor``. Sólo expone claves
    conocidas de la plantilla (o aliases configurados explícitamente).
    """
    texto = str(payload or "").strip()
    resultado = {"texto": texto, "formato": "texto", "campos": {}}
    if not texto:
        return resultado
    mapa = {**ALIAS_QR_DEFAULT, **{str(k).lower(): str(v) for k, v in (aliases or {}).items()}}
    pares: dict[str, object] = {}
    try:
        json_qr = json.loads(texto)
        if isinstance(json_qr, dict):
            pares = json_qr
            resultado["formato"] = "json"
    except (json.JSONDecodeError, TypeError):
        pass
    if not pares:
        for fragmento in re.split(r"[;\n|]+", texto):
            coincidencia = re.match(r"\s*([\w.-]+)\s*[:=]\s*(.*?)\s*$", fragmento)
            if coincidencia:
                pares[coincidencia.group(1)] = coincidencia.group(2)
        if pares:
            resultado["formato"] = "pares"
    for clave_original, valor in pares.items():
        limpia = str(clave_original).strip().lower().replace("-", "_").replace(" ", "_")
        clave = mapa.get(limpia, limpia if limpia in CLAVES_PLANTILLA else None)
        if clave in CLAVES_PLANTILLA and valor not in {None, ""}:
            resultado["campos"][clave] = str(valor).strip()
    if re.match(r"^https?://", texto, re.IGNORECASE):
        resultado["formato"] = "url_texto"
    return resultado


def evidencias_desde_qr(qrs: Iterable[dict], imagen: dict,
                        aliases: dict | None = None) -> list[dict]:
    """Convierte únicamente campos QR explícitos y conocidos en evidencias."""
    evidencias = []
    for indice, qr in enumerate(qrs):
        interpretado = interpretar_payload_qr(qr.get("payload", ""), aliases)
        qr["interpretacion"] = interpretado
        for clave, valor in interpretado["campos"].items():
            normalizado = str(valor).strip()
            if clave == "module_version":
                normalizado = {"RWD": "RDW"}.get(normalizado.upper(), normalizado.upper())
            elif clave in {"inflator_type", "temperature_condition"}:
                normalizado = normalizado.upper()
            evidencias.append({
                "clave": clave, "valor_original": str(valor),
                "valor_normalizado": normalizado, "fuente": "qr",
                "imagen": imagen.get("ruta_relativa") or imagen.get("ruta"),
                "fase": imagen.get("fase"), "tor": imagen.get("tor"),
                "confianza_ocr": 1.0, "valido_catalogo": True,
                "valido_regex": True, "regla_aplicada": "payload_qr_explicito",
                "qr_indice": indice,
            })
    return evidencias


def ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _hijos(ruta: Path) -> list[Path]:
    try:
        return sorted((p for p in ruta.iterdir() if p.is_dir()), key=lambda p: p.name.lower())
    except OSError:
        return []


def detectar_tipos_st(ruta: str | Path, seleccion_manual: str | None = None) -> dict:
    """Busca 1ST/2ST en la ruta, superiores y directorios inmediatamente inferiores."""
    if seleccion_manual:
        manual = seleccion_manual.upper()
        if manual not in {"1ST", "2ST", "LEGACY"}:
            raise ValueError("El tipo manual debe ser 1ST, 2ST o LEGACY.")
        return {"tipos": [] if manual == "LEGACY" else [manual],
                "fuente": "seleccion_manual", "requiere_seleccion": False,
                "usar_legacy": manual == "LEGACY"}

    ruta = Path(ruta).resolve()
    textos: list[tuple[str, str]] = [(str(ruta), "ruta_completa")]
    textos.extend((p.name, "carpeta_superior") for p in [ruta, *ruta.parents])
    textos.extend((p.name, "carpeta_inferior") for p in _hijos(ruta))
    encontrados: list[str] = []
    fuentes: dict[str, list[str]] = defaultdict(list)
    for texto, fuente in textos:
        for tipo in ("1ST", "2ST"):
            if re.search(rf"(?<![A-Z0-9]){tipo}(?![A-Z0-9])", texto, re.IGNORECASE):
                if tipo not in encontrados:
                    encontrados.append(tipo)
                fuentes[tipo].append(fuente)
    encontrados.sort()
    return {"tipos": encontrados, "fuente": "deteccion_ruta" if encontrados else None,
            "fuentes": dict(fuentes), "requiere_seleccion": not encontrados,
            "usar_legacy": False}


def parsear_nombre_caso(nombre: str) -> dict | None:
    coincidencia = PATRON_CASO.fullmatch(" ".join(str(nombre).strip().split()))
    if not coincidencia:
        return None
    valores = {k: v.upper() for k, v in coincidencia.groupdict().items()}
    original = valores["version"]
    valores["version"] = "RDW" if original == "RWD" else original
    return {
        "test_number": valores["id"],
        "module_version": valores["version"],
        "module_version_original": original,
        "inflator_type": valores["inflator"],
        "temperature_condition": valores["temperature"],
        "normalizaciones": ([{"clave": "module_version", "original": "RWD",
                                "normalizado": "RDW", "regla": "alias_module_version"}]
                              if original == "RWD" else []),
    }


def case_key(raiz: str | Path, tipo_st: str | None, ruta_caso: str | Path,
             test_number: str | None = None, proyecto_configurado: str | None = None) -> str:
    raiz, ruta_caso = Path(raiz).resolve(), Path(ruta_caso).resolve()
    try:
        relativa = ruta_caso.relative_to(raiz).as_posix()
    except ValueError:
        relativa = ruta_caso.name
    proyecto = resolver_proyecto_id(raiz, proyecto_configurado)
    return identidad_caso(proyecto, tipo_st, test_number, ruta_caso.name, relativa)


def _tipo_st_para_caso(caso: Path, raiz: Path, tipos: list[str]) -> str | None:
    texto = "/".join(caso.relative_to(raiz).parts).upper()
    hallados = [tipo for tipo in tipos if tipo in texto]
    return hallados[0] if len(hallados) == 1 else (tipos[0] if len(tipos) == 1 else None)


def recorrer_fotos_caso(ruta_caso: str | Path) -> list[dict]:
    """Recorre únicamente NACH y VOR; no explora DIAGRAMM/TEMPERATURE/VIDEOS."""
    caso = Path(ruta_caso)
    fotos: list[dict] = []
    for fase in ("NACH", "VOR"):
        base = caso / "PHOTOS" / fase
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames.sort()
            for nombre in sorted(filenames):
                archivo = Path(dirpath) / nombre
                if archivo.suffix.lower() not in EXTENSIONES_IMAGEN:
                    continue
                relativa_fase = archivo.relative_to(base)
                tor = next((parte for parte in relativa_fase.parts[:-1]
                            if PATRON_TOR.fullmatch(parte)), None)
                fotos.append({
                    "ruta": str(archivo), "ruta_relativa": archivo.relative_to(caso).as_posix(),
                    "fase": fase, "tor": tor,
                })
    return fotos


def recorrer_videos_caso(ruta_caso: str | Path) -> list[dict]:
    """Descubre videos de alta velocidad en carpetas VIDEO/VIDEOS del caso."""
    from video_airbag import descubrir_videos_caso
    return descubrir_videos_caso(ruta_caso)


def _contar_omitidas(caso: Path) -> int:
    total = 0
    for nombre in ("DIAGRAMM", "TEMPERATURE"):
        base = caso / nombre
        if base.is_dir():
            total += sum(1 for p in base.rglob("*") if p.is_file()
                         and p.suffix.lower() in EXTENSIONES_IMAGEN)
    return total


def descubrir_casos(raiz: str | Path, tipo_st_manual: str | None = None,
                     al_descubrir: Callable[[dict], None] | None = None,
                     proyecto_configurado: str | None = None) -> dict:
    """Descubre casos sin hacer una búsqueda recursiva de imágenes desde la raíz."""
    raiz = Path(raiz).resolve()
    deteccion_st = detectar_tipos_st(raiz, tipo_st_manual)
    if deteccion_st["usar_legacy"]:
        return {"perfil": "legacy", "deteccion_st": deteccion_st, "casos": [],
                "casos_encontrados": 0, "casos_validos": 0, "casos_incompletos": 0}

    casos: list[dict] = []
    vistos: set[Path] = set()
    for dirpath, dirnames, _ in os.walk(raiz):
        dirnames.sort()
        ruta = Path(dirpath)
        metadata = parsear_nombre_caso(ruta.name)
        parece_caso = metadata is not None or any(n.upper() == "PHOTOS" for n in dirnames)
        if not parece_caso or ruta in vistos:
            continue
        vistos.add(ruta)
        superior = ruta.parent.name.upper()
        tipo_st = _tipo_st_para_caso(ruta, raiz, deteccion_st["tipos"])
        photos = next((p for p in _hijos(ruta) if p.name.upper() == "PHOTOS"), ruta / "PHOTOS")
        nach = next((p for p in _hijos(photos) if p.name.upper() == "NACH"), photos / "NACH")
        vor = next((p for p in _hijos(photos) if p.name.upper() == "VOR"), photos / "VOR")
        validaciones = {
            "nombre_caso": metadata is not None,
            "carpeta_temperatura": superior in {"HT", "NT", "RT"},
            "temperatura_coincide": bool(metadata and superior == metadata["temperature_condition"]),
            "photos": photos.is_dir(), "nach": nach.is_dir(), "vor": vor.is_dir(),
        }
        valida = all(validaciones.values())
        fotos = recorrer_fotos_caso(ruta) if valida else []
        videos = recorrer_videos_caso(ruta) if valida else []
        tor = sorted({f["tor"] for f in fotos if f.get("tor")})
        proyecto = resolver_proyecto_id(raiz, proyecto_configurado)
        caso = {
            "project_id": proyecto,
            "case_key": case_key(raiz, tipo_st, ruta, (metadata or {}).get("test_number"), proyecto_configurado), "ruta": str(ruta),
            "ruta_relativa": ruta.relative_to(raiz).as_posix(), "nombre": ruta.name,
            "tipo_st": tipo_st, "metadata_ruta": metadata or {},
            "estructura_valida": valida, "validaciones": validaciones,
            "estado_deteccion": "estructura_valida" if valida else "estructura_incompleta",
            "estado": "detectada", "modo_procesamiento": "empresarial" if valida else "legacy",
            "fotos": fotos, "videos": videos, "total_imagenes": len(fotos),
            "total_videos": len(videos),
            "imagenes_nach": sum(f["fase"] == "NACH" for f in fotos),
            "imagenes_vor": sum(f["fase"] == "VOR" for f in fotos),
            "carpetas_tor": tor, "imagenes_omitidas_fuera_photos": _contar_omitidas(ruta),
            "existe_diagramm": (ruta / "DIAGRAMM").is_dir(),
            "existe_temperature": (ruta / "TEMPERATURE").is_dir(),
            "existe_videos": bool(videos),
            "progreso": {"total_imagenes": len(fotos), "revisadas": 0, "con_texto": 0,
                         "sin_texto": 0, "porcentaje": 0.0},
            "ultima_ejecucion": None,
        }
        casos.append(caso)
        if al_descubrir:
            al_descubrir(deepcopy(caso))

    validos = sum(c["estructura_valida"] for c in casos)
    perfil = "empresarial" if casos and validos else "legacy"
    return {
        "perfil": perfil, "deteccion_st": deteccion_st, "casos": casos,
        "casos_encontrados": len(casos), "casos_validos": validos,
        "casos_incompletos": len(casos) - validos,
    }


def normalizar_numero_parte(texto: str) -> str | None:
    limpio = re.sub(r"\s+", " ", str(texto).strip().upper())
    coincidencia = re.fullmatch(
        r"([A-Z0-9]{2,4})[ .\-]+(\d{3})[ .\-]+(\d{3})[ .\-]+([A-Z0-9]{1,3})", limpio)
    return ".".join(coincidencia.groups()) if coincidencia else None


def normalizar_temperatura(texto: str, contexto: str | None = None) -> str | None:
    """Normaliza temperaturas sólo con código, unidad o contexto explícito."""
    bruto = str(texto).upper().replace("−", "-")
    ctx = str(contexto or "").upper()
    for codigo in ("HT", "RT", "NT"):
        if re.search(rf"\b{codigo}\b", bruto):
            return codigo
    contexto_temp = bool(re.search(r"TEMP(?:ERATUR|ERATURE|ERATURA)?", bruto))
    unidad = bool(re.search(r"°\s*C?|\bC\b", bruto))
    numeros = []
    for candidato in re.findall(r"(?<!\d)([+-]?\d{2,3}(?:[.,]\d+)?)(?!\d)", bruto):
        try:
            numeros.append(float(candidato.replace(",", ".")))
        except (TypeError, ValueError):
            continue
    if not numeros or not (contexto_temp or unidad or ctx in {"HT", "NT", "RT"}):
        return None
    objetivos = {"HT": 85.0, "RT": 23.0, "NT": -35.0}
    for numero in numeros:
        if numero == 35 and ("NT" in bruto or ctx == "NT" or "BAJA" in bruto):
            numero = -35
        for codigo, objetivo in objetivos.items():
            if abs(numero - objetivo) <= 2:
                return codigo
    return None



def normalizar_serial(texto: str | None) -> str | None:
    """Conserva letras, números, espacios, guiones, asteriscos y ceros iniciales."""
    if texto is None:
        return None
    limpio = str(texto).strip().upper()
    if not limpio:
        return None
    if not re.fullmatch(r"[A-Z0-9* /-]+", limpio):
        return None
    return re.sub(r"\s+", " ", limpio)


def interpretar_fecha_impresa(texto: str | None, formato: str | None = None) -> dict:
    """Interpreta sólo formatos inequívocos; conserva ambiguos sin adivinar proveedor."""
    original = str(texto or "").strip()
    if not original:
        return {"original": original, "interpretacion": None, "estado": "vacia"}
    # Un mes escrito elimina la ambigüedad numérica (overlay: 04 JUN 25).
    meses = {"JAN": 1, "ENE": 1, "FEB": 2, "MAR": 3, "APR": 4, "ABR": 4,
             "MAY": 5, "MAI": 5, "JUN": 6, "JUL": 7, "AUG": 8, "AGO": 8,
             "SEP": 9, "SEPT": 9, "OCT": 10, "OKT": 10, "NOV": 11,
             "DEC": 12, "DIC": 12, "DEZ": 12}
    m = re.fullmatch(r"(\d{1,2})\s+([A-Z]{3,4})\s+(\d{2}|20\d{2})", original.upper())
    if m and m.group(2) in meses:
        d, mes, y = m.groups()
        try:
            fecha = datetime(2000 + int(y) if len(y) == 2 else int(y), meses[mes], int(d))
            return {"original": original, "interpretacion": fecha.date().isoformat(),
                    "estado": "interpretada", "regla": "mes_escrito"}
        except ValueError:
            return {"original": original, "interpretacion": None, "estado": "invalida"}
    # DMY sólo viene de una declaración de imagen/perfil, nunca del proveedor.
    formato_normalizado = re.sub(r"[^A-Z]", "", str(formato or "").upper())
    if formato_normalizado in {"DMY", "DDMMYY", "DDMMYYYY"}:
        m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2}|20\d{2})", original)
        if m:
            d, mo, y = m.groups()
            try:
                fecha = datetime(2000 + int(y) if len(y) == 2 else int(y), int(mo), int(d))
                return {"original": original, "interpretacion": fecha.date().isoformat(),
                        "estado": "interpretada", "regla": "dmy_explicito"}
            except ValueError:
                return {"original": original, "interpretacion": None, "estado": "invalida"}
    # Año de cuatro dígitos al inicio: YYYY-MM-DD / YYYY.MM.DD / YYYY/MM/DD.
    m = re.fullmatch(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})", original)
    if m:
        y, mo, d = map(int, m.groups())
        try:
            fecha = datetime(y, mo, d).date().isoformat()
            return {"original": original, "interpretacion": fecha, "estado": "interpretada",
                    "regla": "yyyy-mm-dd"}
        except ValueError:
            return {"original": original, "interpretacion": None, "estado": "invalida"}
    # Año de cuatro dígitos al final sólo es seguro cuando uno de los dos primeros
    # valores supera 12; así se evita imponer DD/MM o MM/DD globalmente.
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](20\d{2})", original)
    if m:
        a, b, y = map(int, m.groups())
        if a > 12 >= b:
            d, mo = a, b
        elif b > 12 >= a:
            mo, d = a, b
        else:
            return {"original": original, "interpretacion": None, "estado": "ambigua"}
        try:
            fecha = datetime(y, mo, d).date().isoformat()
            return {"original": original, "interpretacion": fecha, "estado": "interpretada",
                    "regla": "dia_mes_desambiguado"}
        except ValueError:
            return {"original": original, "interpretacion": None, "estado": "invalida"}
    if re.fullmatch(r"\d{2}[./-]\d{2}[./-]\d{2}", original):
        return {"original": original, "interpretacion": None, "estado": "ambigua"}
    return {"original": original, "interpretacion": None, "estado": "no_reconocida"}


def _componente_contextual(texto: str) -> str:
    mayus = str(texto or "").upper()
    tablero = bool(re.search(r"DASH|INSTRUMENT|I-?TAFEL|TABLERO", mayus))
    bolsa = bool(re.search(r"\b(?:AIRBAG|AIR\s*BAG|PAB|MODULE|MODUL)\b", mayus))
    if tablero and not bolsa:
        return "tablero"
    if bolsa and not tablero:
        return "bolsa_aire"
    return "por_identificar"

def extraer_candidatos_texto(texto: str, imagen: dict, contexto: dict) -> list[dict]:
    """Parser conservador que conserva originales y procedencia.

    Opciones explícitas: ``componente`` (bolsa_aire/tablero), ``laboratorio``
    (EDAG/VW) y ``formato_fecha`` (DMY) en imagen o contexto. Un perfil puede
    declararlas en ``contexto.perfil_extraccion``; la imagen tiene prioridad.
    Las menciones locales del componente distinguen etiquetas en una misma foto.
    """
    texto = str(texto or "")
    mayus = texto.upper().replace("−", "-")
    candidatos: list[dict] = []
    perfil = contexto.get("perfil_extraccion") or {}

    def opcion(clave):
        return imagen.get(clave) or contexto.get(clave) or perfil.get(clave)

    componente_declarado = opcion("componente")
    if componente_declarado not in {"bolsa_aire", "tablero"}:
        componente_declarado = _componente_contextual(mayus)

    def componente_en(posicion):
        # La última cabecera cercana permite una etiqueta AIRBAG y otra TABLERO
        # en el mismo OCR, sin asignar todo al primer componente encontrado.
        inicio = max(mayus.rfind("\n\n", 0, posicion), posicion - 240, 0)
        anteriores = list(re.finditer(
            r"\b(?:DASHBOARD|DASH|INSTRUMENT\w*|I-?TAFEL|TABLERO|AIRBAG|AIR\s*BAG|PAB|MODULE|MODUL)\b",
            mayus[inicio:posicion]))
        return (_componente_contextual(anteriores[-1].group()) if anteriores
                else componente_declarado)

    formato_fecha = opcion("formato_fecha")
    if not formato_fecha:
        fm = re.search(r"\b(?:DMY|DD[./-]MM[./-](?:YYYY|YY))\b", mayus)
        formato_fecha = fm.group() if fm else None
    laboratorio = str(opcion("laboratorio") or "").strip().upper()
    if re.search(r"\bEDAG\s*(?:TEST\s*LAB|TESTLAB)\b", mayus):
        laboratorio = "EDAG"

    def agregar(clave: str, original: str, normalizado: str, confianza: float,
                regla: str, valido: bool = True,
                requiere_confirmacion_manual: bool = False,
                componente: str | None = None, **metadatos) -> None:
        candidatos.append({
            "proyecto": contexto.get("project_id") or contexto.get("proyecto"),
            "etapa": contexto.get("tipo_st") or contexto.get("stage"),
            "caso": contexto.get("case_key") or contexto.get("test_number"),
            "componente": componente or componente_declarado,
            "clave": clave, "valor_original": original.strip(),
            "valor_normalizado": normalizado, "fuente": imagen.get("fuente", "ocr"),
            "imagen": imagen.get("ruta_relativa") or imagen.get("ruta"),
            "imagen_absoluta": imagen.get("ruta_absoluta") or imagen.get("ruta"),
            "bbox_original": imagen.get("bbox_original") or imagen.get("bbox"),
            "orientacion_grados": imagen.get("orientacion_grados") or imagen.get("rotacion") or 0,
            "transformaciones": list(imagen.get("transformaciones") or []),
            "fase": imagen.get("fase"), "tor": imagen.get("tor"),
            "confianza_ocr": round(float(confianza), 4), "valido_catalogo": valido,
            "valido_regex": valido, "regla_aplicada": regla,
            "confirmacion_manual": imagen.get("fuente") == "manual",
            "requiere_confirmacion_manual": requiere_confirmacion_manual,
            "version_procesamiento": contexto.get("version_procesamiento") or "v8",
            **metadatos,
        })

    confianza = float(imagen.get("confianza_ocr") or 0.0)
    for m in re.finditer(
            r"(?im)^\s*(?:PROYECTO|PROJECT|PROJEKT|MOTIVO(?:\s+DE\s+PRUEBA)?|TEST\s+REASON|PRÜFGRUND)"
            r"\s*[:=]\s*([^\r\n]{1,100})", texto):
        original = m.group(1).strip()
        if original:
            agregar("test_reason", original, original, confianza, "motivo_proyecto_explicito",
                    componente="por_identificar")
    prueba_vw_detectada = False
    for m in re.finditer(r"\bVW[- /]?\d{3,12}(?:[-/][A-Z0-9]+)*\b", mayus):
        antes = mayus[max(0, m.start()-28):m.start()]
        if re.search(r"(?:SERIAL|S/?N|SERIE|PART|P/?N)\s*[:#-]?\s*$", antes):
            continue
        if (componente_en(m.start()) != "por_identificar" and
                not re.search(r"(?:TEST|PRUEBA|VERSUCH)\s*(?:NO|NR|NUMBER|NUMERO)?\s*[:#.-]?\s*$", antes)):
            continue
        numero = re.sub(r"\s+", "", m.group())
        prueba_vw_detectada = True
        agregar("test_number", m.group(), numero, confianza, "numero_prueba_vw")
        agregar("test_place", m.group(), "VW", confianza, "laboratorio_numero_vw")
    if laboratorio == "VW" and not prueba_vw_detectada:
        agregar("test_place", laboratorio, laboratorio, confianza, "laboratorio_vw_explicito")
    if laboratorio == "EDAG":
        agregar("test_place", "EDAG Testlab" if "EDAG" in mayus else laboratorio,
                "EDAG", confianza, "laboratorio_edag_explicito")
        # Sólo WWYYNN con semana ISO válida y secuencia no nula; no cualquier serial.
        for m in re.finditer(r"(?<![A-Z0-9])([0-5]\d)(\d{2})(\d{2})(?![A-Z0-9])", mayus):
            semana, anio, secuencia = map(int, m.groups())
            try:
                datetime.fromisocalendar(2000 + anio, semana, 1)
            except ValueError:
                continue
            if not secuencia:
                continue
            antes = mayus[max(0, m.start()-28):m.start()]
            if re.search(r"(?:SERIAL|S/?N|SERIE|PART|P/?N)\s*[:#-]?\s*$", antes):
                continue
            if (componente_en(m.start()) != "por_identificar" and
                    not re.search(r"(?:TEST|PRUEBA|VERSUCH)\s*(?:NO|NR|NUMBER|NUMERO)?\s*[:#.-]?\s*$", antes)):
                continue
            numero = m.group()
            agregar("test_number", numero, numero, confianza, "numero_prueba_edag_wwyynn")
            agregar("week", numero, str(semana), confianza, "semana_numero_edag",
                    anio_prueba=2000 + anio, secuencia_prueba=secuencia)
    for original in re.findall(r"\b(?:RDW|RWD|ROW|NAR|N4R)\b", mayus):
        normalizado = {"RWD": "RDW", "ROW": "RDW", "N4R": "NAR"}.get(original, original)
        agregar("module_version", original, normalizado, confianza, "alias_module_version")
    for valor in re.findall(r"\b(?:NOM|OGL|UGL)\b", mayus):
        agregar("inflator_type", valor, valor, confianza, "catalogo_inflator")
    temperatura = normalizar_temperatura(mayus, contexto.get("temperature_condition"))
    if temperatura:
        agregar("temperature_condition", texto, temperatura, confianza, "temperatura_contextual")
    for patron in re.finditer(
            r"\b[A-Z0-9]{2,4}[ .\-]+\d{3}[ .\-]+\d{3}[ .\-]+[A-Z0-9]{1,3}\b", mayus):
        normalizado = normalizar_numero_parte(patron.group())
        if normalizado:
            componente = componente_en(patron.start())
            clave = ("dashboard_part_number" if componente == "tablero"
                     else "module_part_number")
            agregar(clave, patron.group(), normalizado, confianza, "numero_parte",
                    componente=componente)
    for m in re.finditer(r"\b([A-Z0-9]{3})(\d{3})(\d{3})([A-Z]{1,3})?\b", mayus):
        if componente_en(m.start()) == "tablero" and re.search(r"[A-Z]", m.group(1)):
            normalizado = ".".join(valor for valor in m.groups() if valor)
            agregar("dashboard_part_number", m.group(), normalizado, confianza,
                    "numero_parte_compacto_tablero", componente="tablero")
    # La guía identifica Autoliv en el módulo, no como lugar de prueba.
    for m in re.finditer(r"\bAUTOLIV\b", mayus):
        if componente_en(m.start()) == "bolsa_aire":
            agregar("inflator_supplier", m.group(), "Autoliv", confianza,
                    "proveedor_modulo_etiquetado", componente="bolsa_aire")
    for m in re.finditer(r"(?<![A-Z0-9])\d{2}[SK](?![A-Z0-9])", mayus):
        componente = componente_en(m.start())
        if componente in {"bolsa_aire", "tablero"}:
            clave = "dashboard_engineering_level" if componente == "tablero" else "engineering_level"
            agregar(clave, m.group(), m.group(), confianza, "ingenieria_componente_visible",
                    componente=componente)
    for m in re.finditer(
            r"\b(?:ENGINEERING\s+LEVEL|NIVEL\s+(?:DE\s+)?INGENIER[IÍ]A|ENTWICKLUNGSSTAND)"
            r"\s*[:=]\s*([A-Z0-9][A-Z0-9._/-]{0,30})", mayus):
        componente = componente_en(m.start())
        if componente in {"bolsa_aire", "tablero"} and not re.fullmatch(r"\d{2}[SK]", m.group(1)):
            clave = "dashboard_engineering_level" if componente == "tablero" else "engineering_level"
            agregar(clave, m.group(1), m.group(1), confianza, "ingenieria_prototipo_no_catalogada",
                    requiere_confirmacion_manual=True, componente=componente,
                    observacion="Nomenclatura de ingeniería nueva: confirma antes de consolidar.")
    for m in re.finditer(
            r"\b(?:LASER\s+OPENING|APERTURA\s+L[AÁ]SER|LASER[ÖO]FFNUNG)"
            r"\s*[:=]\s*([^\r\n]{1,40})", mayus):
        if componente_en(m.start()) == "tablero":
            agregar("laser_opening", m.group(1), m.group(1).strip(), confianza,
                    "apertura_laser_tablero_explicita", requiere_confirmacion_manual=True,
                    componente="tablero", observacion="Confirmar apertura láser; no equivale al tiempo de ruptura.")
    for m in re.finditer(r"\b(?:DELAY|VERZÖGERUNG|RETARDO)\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*MS\b", mayus):
        agregar("delay_ms", m.group(), m.group(1).replace(",", "."), confianza,
                "delay_etiquetado")
    for clave, etiquetas in (
        ("opening_time_ms", r"OPENING|ÖFFNUNGSZEIT"),
        ("full_inflation_time_ms", r"FULL\s+INFLATION|AUFBLASZEIT"),
        ("forvia_measurement_ms", r"FORVIA"),
    ):
        m = re.search(rf"(?:{etiquetas})[^\d]{{0,20}}(\d+(?:[.,]\d+)?)\s*MS", mayus)
        if m:
            # opening_time_ms se conserva como candidato trazable, pero V8 no lo
            # consolida automáticamente hasta validar el extractor con datos reales.
            agregar(clave, m.group(1), m.group(1).replace(",", "."), confianza,
                    "tiempo_etiquetado",
                    requiere_confirmacion_manual=(clave == "opening_time_ms"))
    # Seriales sólo cuando existe una etiqueta contextual; se preservan asteriscos y ceros.
    for m in re.finditer(r"(?:SERIAL|S/?N|SN|SERIENNUMMER|SERIE)\s*[:#-]?\s*([A-Z0-9*][A-Z0-9* /-]{2,40})", mayus):
        componente = componente_en(m.start())
        original = m.group(1).strip()
        serial = normalizar_serial(original)
        if serial:
            clave = ("dashboard_serial_number" if componente == "tablero" else
                     "module_serial_number" if componente == "bolsa_aire" else "_serial_por_identificar")
            agregar(clave, original, serial, confianza, "serial_etiquetado",
                    valido=(clave != "_serial_por_identificar"), componente=componente)

    # La guía apunta P/N ALV a Serie en una etiqueta de prototipo. No asumir que
    # todos los números de parte del proveedor sean seriales: propone con aviso.
    for m in re.finditer(r"\bP/?N\s+ALV\s*:\s*([A-Z0-9][A-Z0-9/-]{2,40})", mayus):
        if componente_en(m.start()) == "bolsa_aire":
            agregar("module_serial_number", m.group(1), m.group(1), confianza,
                    "serie_prototipo_guia_pn_alv", requiere_confirmacion_manual=True,
                    componente="bolsa_aire",
                    observacion="P/N ALV indicado como Serie en la guía: corroborar antes de usar como serial.")

    # Fechas impresas: conservar siempre el original; sólo consolidar una interpretación segura.
    patron_fecha = r"\b(?:\d{1,4}[./-]\d{1,2}[./-]\d{1,4}|\d{1,2}\s+[A-Z]{3,4}\s+(?:20\d{2}|\d{2}))\b"
    for fm in re.finditer(patron_fecha, mayus):
        info = interpretar_fecha_impresa(fm.group(), formato=formato_fecha)
        componente = componente_en(fm.start())
        if info["estado"] == "interpretada":
            antes = mayus[max(0, fm.start()-32):fm.start()]
            if (re.search(r"TEST\s*DATE|DATUM\s*(?:TEST)?|FECHA\s*(?:DE\s*)?PRUEBA", antes)
                    or (laboratorio == "EDAG" and componente == "por_identificar")):
                clave = "test_date"
            elif componente == "tablero":
                clave = "dashboard_date"
            elif componente == "bolsa_aire":
                clave = "module_date"
            else:
                clave = "_fecha_por_identificar"
            agregar(clave, info["original"], info["interpretacion"], confianza,
                    f"fecha_impresa:{info.get('regla','segura')}", valido=not clave.startswith("_"),
                    componente=componente)
        elif info["estado"] == "ambigua":
            agregar("_fecha_ambigua", info["original"], info["original"], confianza,
                    "fecha_ambigua_pendiente", valido=False)
    return candidatos


def _evidencia_ruta(caso: dict) -> list[dict]:
    salida = []
    for clave, valor in caso.get("metadata_ruta", {}).items():
        if clave not in {"test_number", "module_version", "inflator_type", "temperature_condition"}:
            continue
        salida.append({
            "proyecto": caso.get("project_id"), "etapa": caso.get("tipo_st"),
            "caso": caso.get("case_key"), "componente": "por_identificar",
            "clave": clave, "valor_original": (caso["metadata_ruta"].get(
                "module_version_original") if clave == "module_version" else valor),
            "valor_normalizado": valor, "fuente": "ruta_carpeta", "imagen": None,
            "bbox_original": None, "orientacion_grados": 0, "transformaciones": [],
            "fase": None, "tor": None, "confianza_ocr": 1.0,
            "valido_catalogo": True, "valido_regex": True,
            "regla_aplicada": ("alias_module_version" if clave == "module_version" and
                                caso["metadata_ruta"].get("module_version_original") == "RWD"
                                else "estructura_caso"),
        })
    return salida


def consolidar_caso(caso: dict, evidencias: Iterable[dict],
                     requeridos: set[str] | None = None,
                     reglas_confirmadas: Iterable[dict] = (),
                     claves: Iterable[str] | None = None) -> dict:
    requeridos = requeridos or CAMPOS_REQUERIDOS_DEFAULT
    claves_contrato = tuple(dict.fromkeys(claves or CLAVES_PLANTILLA))
    todos = [*_evidencia_ruta(caso), *list(evidencias)]
    por_clave: dict[str, list[dict]] = defaultdict(list)
    for evidencia in todos:
        if (evidencia.get("clave") in claves_contrato and
                evidencia.get("valor_normalizado") not in {None, ""} and
                not (evidencia.get("requiere_confirmacion_manual") and
                     not evidencia.get("confirmacion_manual"))):
            por_clave[evidencia["clave"]].append(evidencia)
    campos: dict[str, dict] = {}
    conflictos: list[str] = []
    for clave in claves_contrato:
        items = por_clave.get(clave, [])
        por_valor: dict[str, list[dict]] = defaultdict(list)
        for item in items:
            por_valor[str(item["valor_normalizado"])].append(item)
        ruta = [i for i in items if i.get("fuente") == "ruta_carpeta"]
        lectura_valores = {v for v, xs in por_valor.items()
                           if any(x.get("fuente") in {"ocr", "qr", "manual"} for x in xs)}
        if ruta:
            seguro = str(ruta[0]["valor_normalizado"])
            incompatibles = sorted(v for v in lectura_valores if v != seguro)
            if incompatibles:
                conflictos.append(clave)
                campos[clave] = {"valor": seguro, "valor_seguro_ruta": seguro,
                                 "estado": "conflicto", "requiere_revision": True,
                                 "candidatos": items, "fuentes": [i.get("imagen") for i in items]}
            else:
                campos[clave] = {"valor": seguro, "estado": "extraido_ruta",
                                 "confianza": 1.0, "inferido": False,
                                 "candidatos": items, "fuentes": [caso["ruta_relativa"]]}
            continue
        if len(por_valor) == 1:
            valor, coincidencias = next(iter(por_valor.items()))
            imagenes = sorted({i.get("imagen") for i in coincidencias if i.get("imagen")})
            confianza_base = max(float(i.get("confianza_ocr") or 0) for i in coincidencias)
            fuentes = {i.get("fuente") for i in coincidencias}
            estado = ("confirmado_multiples_imagenes" if len(imagenes) > 1 else
                      "extraido_manual" if "manual" in fuentes else
                      "extraido_video" if "video" in fuentes else
                      "extraido_qr" if "qr" in fuentes else "extraido_ocr")
            campos[clave] = {"valor": valor, "estado": estado,
                             "confianza": round(min(0.99, confianza_base + 0.03 * (len(imagenes) - 1)), 4),
                             "inferido": False, "candidatos": coincidencias, "fuentes": imagenes,
                             "fuente_preferida": ("manual" if "manual" in fuentes else
                                                   "video" if "video" in fuentes else
                                                   "qr" if "qr" in fuentes else "ocr")}
        elif len(por_valor) > 1:
            conflictos.append(clave)
            campos[clave] = {"valor": None, "estado": "conflicto",
                             "requiere_revision": True, "candidatos": items,
                             "fuentes": sorted({i.get("imagen") for i in items if i.get("imagen")})}
        else:
            pendientes = [e for e in todos if e.get("clave") == clave
                          and e.get("requiere_confirmacion_manual")
                          and not e.get("confirmacion_manual")]
            campos[clave] = {"valor": None,
                             "estado": "faltante_requerido" if clave in requeridos else "faltante",
                             "requerido": clave in requeridos,
                             "requiere_revision": clave in requeridos or bool(pendientes),
                             "pendiente_confirmacion_manual": bool(pendientes),
                             "candidatos_pendientes": pendientes}

    for regla in reglas_confirmadas:
        clave = regla.get("campo")
        if (regla.get("estado") != "confirmada" or clave not in CAMPOS_APRENDIBLES or
                clave in CAMPOS_NUNCA_HEREDAR or campos.get(clave, {}).get("valor") is not None):
            continue
        alcance = regla.get("alcance", {})
        if all(str(caso.get("metadata_ruta", {}).get(k) or caso.get(k)) == str(v)
               for k, v in alcance.items()):
            campos[clave] = {"valor": regla["valor"], "estado": "inferido_regla_confirmada",
                             "fuente": "regla_aprendida_confirmada",
                             "confianza": regla.get("confianza"), "inferido": True,
                             "regla_id": regla.get("id"), "requiere_revision": True}

    fecha_prueba = campos.get("test_date", {}).get("valor")
    if fecha_prueba:
        try:
            fecha_iso = datetime.strptime(str(fecha_prueba), "%Y-%m-%d").date().isocalendar()
            campo_semana = campos.get("week", {})
            candidatos_edag = [e for e in campo_semana.get("candidatos", [])
                               if e.get("regla_aplicada") == "semana_numero_edag"]
            contradiccion = any(str(e.get("valor_normalizado")) != str(fecha_iso.week)
                                or e.get("anio_prueba") != fecha_iso.year for e in candidatos_edag)
            if contradiccion:
                if "week" not in conflictos:
                    conflictos.append("week")
                campos["week"] = {**campo_semana, "valor": None, "estado": "conflicto",
                                  "requiere_revision": True,
                                  "semana_fecha_prueba": fecha_iso.week,
                                  "anio_fecha_prueba": fecha_iso.year,
                                  "observacion": "La semana/año EDAG no coincide con la fecha de prueba."}
            elif not campo_semana.get("valor") and campo_semana.get("estado") != "conflicto":
                campos["week"] = {"valor": fecha_iso.week, "estado": "derivado",
                                  "fuente": "test_date", "confianza":
                                  campos["test_date"].get("confianza"), "inferido": False,
                                  "requiere_revision": False}
        except ValueError:
            pass

    faltantes = [k for k, v in campos.items() if str(v.get("estado", "")).startswith("faltante")]
    requiere_revision = bool(conflictos or any(campos[k].get("requiere_revision") for k in campos))
    return {"project_id": caso.get("project_id"), "case_key": caso["case_key"],
            "test_number": caso.get("metadata_ruta", {}).get("test_number"),
            "tipo_st": caso.get("tipo_st"), "campos": campos, "candidatos": todos,
            "campos_faltantes": faltantes, "conflictos": conflictos,
            "requiere_revision": requiere_revision}


_CACHE_LOCKS: dict[str, threading.RLock] = {}
_CACHE_LOCKS_GUARD = threading.Lock()


class CacheOCR:
    """Caché SQLite transaccional con importación del JSON histórico.

    WAL y ``busy_timeout`` coordinan procesos; un bloqueo compartido coordina
    hilos del proceso actual. Si una escritura falla el OCR se conserva en
    memoria como pendiente y puede recuperarse con ``recuperar_pendientes``.
    """

    def __init__(self, ruta: str | Path, config_ocr: dict):
        solicitada = Path(ruta)
        self.ruta = (solicitada if solicitada.suffix.lower() in {".sqlite", ".sqlite3", ".db"}
                     else solicitada.with_suffix(".sqlite3"))
        self.ruta_json_legacy = (solicitada if solicitada.suffix.lower() == ".json"
                                 else solicitada.with_suffix(".json"))
        serial = json.dumps(config_ocr, ensure_ascii=False, sort_keys=True, default=str)
        self.config_version = hashlib.sha256(serial.encode()).hexdigest()[:16]
        self.pendientes: dict[str, tuple[dict, dict]] = {}
        with _CACHE_LOCKS_GUARD:
            self._lock = _CACHE_LOCKS.setdefault(str(self.ruta.resolve()), threading.RLock())
        self._inicializar()
        self._importar_json_legacy()

    def _conectar(self) -> sqlite3.Connection:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.ruta, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        con.execute("PRAGMA busy_timeout=30000")
        return con

    def _inicializar(self) -> None:
        with self._lock, self._conectar() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS cache_imagenes (
                    clave TEXT PRIMARY KEY, ruta TEXT NOT NULL, tamano INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL, version_parser TEXT NOT NULL,
                    config_version TEXT NOT NULL, actualizado_en TEXT NOT NULL,
                    resultado_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cache_meta (
                    clave TEXT PRIMARY KEY, valor TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_cache_ruta ON cache_imagenes(ruta);
            """)

    def _importar_json_legacy(self) -> None:
        if not self.ruta_json_legacy.is_file():
            return
        try:
            with self._lock, self._conectar() as con:
                if con.execute(
                        "SELECT 1 FROM cache_meta WHERE clave='json_legacy_importado'").fetchone():
                    return
                documento = json.loads(self.ruta_json_legacy.read_text(encoding="utf-8"))
                for clave, item in documento.get("imagenes", {}).items():
                    if not isinstance(item, dict) or "resultado" not in item:
                        continue
                    con.execute("""
                        INSERT OR IGNORE INTO cache_imagenes
                        (clave, ruta, tamano, mtime_ns, version_parser, config_version,
                         actualizado_en, resultado_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (clave, str(item.get("ruta") or ""), int(item.get("tamano") or 0),
                          int(item.get("mtime_ns") or 0),
                          str(item.get("version_parser") or VERSION_PARSER),
                          str(item.get("config_version") or "legacy"),
                          str(item.get("actualizado_en") or ahora()),
                          json.dumps(item["resultado"], ensure_ascii=False)))
                con.execute("INSERT INTO cache_meta(clave, valor) VALUES (?, ?)",
                            ("json_legacy_importado", ahora()))
        except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError):
            # Un JSON histórico dañado no impide crear una caché nueva.
            return

    def _clave(self, ruta: str | Path) -> tuple[str, dict]:
        archivo = Path(ruta)
        st = archivo.stat()
        firma = {"ruta": str(archivo.resolve()), "tamano": st.st_size,
                 "mtime_ns": st.st_mtime_ns, "version_parser": VERSION_PARSER,
                 "config_version": self.config_version}
        clave = hashlib.sha256(json.dumps(firma, sort_keys=True).encode()).hexdigest()
        return clave, firma

    def obtener(self, ruta: str | Path) -> dict | None:
        clave, _ = self._clave(ruta)
        if clave in self.pendientes:
            return deepcopy(self.pendientes[clave][1])
        try:
            with self._lock, self._conectar() as con:
                fila = con.execute(
                    "SELECT resultado_json FROM cache_imagenes WHERE clave=?", (clave,)).fetchone()
            return json.loads(fila["resultado_json"]) if fila else None
        except (sqlite3.Error, json.JSONDecodeError, OSError):
            return None

    def guardar(self, ruta: str | Path, resultado: dict) -> dict:
        clave, firma = self._clave(ruta)
        self.pendientes[clave] = (firma, deepcopy(resultado))
        return self._guardar_clave(clave)

    def _guardar_clave(self, clave: str) -> dict:
        firma, resultado = self.pendientes[clave]
        ultimo_error = None
        for intento in range(4):
            try:
                with self._lock, self._conectar() as con:
                    con.execute("BEGIN IMMEDIATE")
                    con.execute("""
                        INSERT INTO cache_imagenes
                        (clave, ruta, tamano, mtime_ns, version_parser, config_version,
                         actualizado_en, resultado_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(clave) DO UPDATE SET
                            actualizado_en=excluded.actualizado_en,
                            resultado_json=excluded.resultado_json
                    """, (clave, firma["ruta"], firma["tamano"], firma["mtime_ns"],
                          firma["version_parser"], firma["config_version"], ahora(),
                          json.dumps(resultado, ensure_ascii=False)))
                self.pendientes.pop(clave, None)
                return {"estado": "cache_guardada", "ruta": str(self.ruta)}
            except (sqlite3.Error, OSError) as exc:
                ultimo_error = exc
                time.sleep(0.05 * (intento + 1))
        return {"estado": "error_cache", "ruta": str(self.ruta),
                "error": f"{type(ultimo_error).__name__}: {ultimo_error}"}

    def recuperar_pendientes(self) -> list[dict]:
        return [self._guardar_clave(clave) for clave in list(self.pendientes)]


class BaseConocimiento:
    """Reglas repetidas, persistentes y auditables; nunca auto-confirma propuestas."""

    def __init__(self, ruta: str | Path, minimo_ids: int = 3, consenso: float = 0.90):
        self.ruta = Path(ruta)
        self.minimo_ids = int(minimo_ids)
        self.consenso = float(consenso)
        try:
            self.datos = json.loads(self.ruta.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self.datos = {"version": 1, "reglas": [], "actualizado_en": None}

    def confirmadas(self) -> list[dict]:
        return [r for r in self.datos["reglas"] if r.get("estado") == "confirmada"]

    def proponer(self, consolidados: Iterable[dict]) -> list[dict]:
        grupos: dict[tuple, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        for resultado in consolidados:
            caso = resultado.get("caso") or resultado
            test_number = str(resultado.get("test_number") or "")
            if not test_number:
                continue
            alcances = [
                {"tipo_st": resultado.get("tipo_st")},
                {"tipo_st": resultado.get("tipo_st"),
                 "module_version": (caso.get("metadata_ruta", {}).get("module_version")
                                    or caso.get("module_version"))},
            ]
            for campo in CAMPOS_APRENDIBLES:
                dato = resultado.get("campos", {}).get(campo, {})
                if not dato.get("valor") or dato.get("estado") == "conflicto":
                    continue
                for alcance in alcances:
                    alcance = {k: v for k, v in alcance.items() if v}
                    llave = (json.dumps(alcance, sort_keys=True), campo)
                    grupos[llave][str(dato["valor"])].add(test_number)

        nuevas = []
        existentes = {(json.dumps(r.get("alcance", {}), sort_keys=True), r.get("campo"), r.get("valor"))
                      for r in self.datos["reglas"]}
        for (alcance_json, campo), valores in grupos.items():
            total_ids = len(set().union(*valores.values()))
            valor, ids = max(valores.items(), key=lambda x: (len(x[1]), x[0]))
            confianza = len(ids) / total_ids if total_ids else 0
            llave = (alcance_json, campo, valor)
            if len(ids) < self.minimo_ids or confianza < self.consenso or llave in existentes:
                continue
            regla = {"id": hashlib.sha256("|".join(llave).encode()).hexdigest()[:16],
                     "alcance": json.loads(alcance_json), "campo": campo, "valor": valor,
                     "ids_soporte": sorted(ids), "cantidad_ids": len(ids),
                     "confianza": round(confianza, 4),
                     "conflictos": sorted(set().union(*(v for k, v in valores.items() if k != valor))),
                     "estado": "propuesta", "creada_en": ahora(), "confirmada_en": None,
                     "confirmada_por": None}
            self.datos["reglas"].append(regla)
            nuevas.append(regla)
        if nuevas:
            self.guardar()
        return nuevas

    def cambiar_estado(self, regla_id: str, estado: str, usuario: str = "dashboard") -> dict:
        if estado not in {"confirmada", "rechazada", "desactivada"}:
            raise ValueError("Estado de regla no válido.")
        regla = next((r for r in self.datos["reglas"] if r.get("id") == regla_id), None)
        if not regla:
            raise KeyError(regla_id)
        regla["estado"] = estado
        if estado == "confirmada":
            regla["confirmada_en"], regla["confirmada_por"] = ahora(), usuario
        self.guardar()
        return deepcopy(regla)

    def guardar(self) -> None:
        self.datos["actualizado_en"] = ahora()
        escribir_json_seguro(self.ruta, self.datos, lanzar=True)
