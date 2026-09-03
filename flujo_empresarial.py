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
import tempfile
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable


PATRON_CASO = re.compile(
    r"^(?P<id>\d+)\s+(?P<version>RDW|RWD|NAR)\s+"
    r"(?P<inflator>NOM|OGL|UGL)\s+(?P<temperature>HT|NT|RT)$",
    re.IGNORECASE,
)
PATRON_TOR = re.compile(r"^TOR\s+(.+)$", re.IGNORECASE)
EXTENSIONES_IMAGEN = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
VERSION_PARSER = "empresarial-1"

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


def case_key(raiz: str | Path, tipo_st: str | None, ruta_caso: str | Path) -> str:
    raiz, ruta_caso = Path(raiz).resolve(), Path(ruta_caso).resolve()
    try:
        relativa = ruta_caso.relative_to(raiz).as_posix()
    except ValueError:
        relativa = ruta_caso.as_posix()
    proyecto = raiz.name or "proyecto"
    return f"{proyecto}|{tipo_st or 'SIN_ST'}|{relativa}"


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


def _contar_omitidas(caso: Path) -> int:
    total = 0
    for nombre in ("DIAGRAMM", "TEMPERATURE"):
        base = caso / nombre
        if base.is_dir():
            total += sum(1 for p in base.rglob("*") if p.is_file()
                         and p.suffix.lower() in EXTENSIONES_IMAGEN)
    return total


def descubrir_casos(raiz: str | Path, tipo_st_manual: str | None = None,
                     al_descubrir: Callable[[dict], None] | None = None) -> dict:
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
        tor = sorted({f["tor"] for f in fotos if f.get("tor")})
        caso = {
            "case_key": case_key(raiz, tipo_st, ruta), "ruta": str(ruta),
            "ruta_relativa": ruta.relative_to(raiz).as_posix(), "nombre": ruta.name,
            "tipo_st": tipo_st, "metadata_ruta": metadata or {},
            "estructura_valida": valida, "validaciones": validaciones,
            "estado_deteccion": "estructura_valida" if valida else "estructura_incompleta",
            "estado": "detectada", "modo_procesamiento": "empresarial" if valida else "legacy",
            "fotos": fotos, "total_imagenes": len(fotos),
            "imagenes_nach": sum(f["fase"] == "NACH" for f in fotos),
            "imagenes_vor": sum(f["fase"] == "VOR" for f in fotos),
            "carpetas_tor": tor, "imagenes_omitidas_fuera_photos": _contar_omitidas(ruta),
            "existe_diagramm": (ruta / "DIAGRAMM").is_dir(),
            "existe_temperature": (ruta / "TEMPERATURE").is_dir(),
            "existe_videos": (ruta / "VIDEOS").is_dir(),
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
    numeros = [float(n) for n in re.findall(r"(?<!\d)([+-]?\d{2,3}(?:[.,]\d+)?)", bruto)]
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


def extraer_candidatos_texto(texto: str, imagen: dict, contexto: dict) -> list[dict]:
    """Parser conservador: produce candidatos, nunca completa campos sin evidencia."""
    texto = str(texto or "")
    mayus = texto.upper().replace("−", "-")
    candidatos: list[dict] = []

    def agregar(clave: str, original: str, normalizado: str, confianza: float,
                regla: str, valido: bool = True) -> None:
        candidatos.append({
            "clave": clave, "valor_original": original.strip(),
            "valor_normalizado": normalizado, "fuente": imagen.get("fuente", "ocr"),
            "imagen": imagen.get("ruta_relativa") or imagen.get("ruta"),
            "fase": imagen.get("fase"), "tor": imagen.get("tor"),
            "confianza_ocr": round(float(confianza), 4), "valido_catalogo": valido,
            "valido_regex": valido, "regla_aplicada": regla,
        })

    confianza = float(imagen.get("confianza_ocr") or 0.0)
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
            clave = ("dashboard_part_number" if re.search(r"DASH|INSTRUMENT|I-?TAFEL", mayus)
                     else "module_part_number")
            agregar(clave, patron.group(), normalizado, confianza, "numero_parte")
    for clave, etiquetas in (
        ("opening_time_ms", r"OPENING|ÖFFNUNGSZEIT"),
        ("full_inflation_time_ms", r"FULL\s+INFLATION|AUFBLASZEIT"),
        ("forvia_measurement_ms", r"FORVIA"),
    ):
        m = re.search(rf"(?:{etiquetas})[^\d]{{0,20}}(\d+(?:[.,]\d+)?)\s*MS", mayus)
        if m:
            agregar(clave, m.group(1), m.group(1).replace(",", "."), confianza,
                    "tiempo_etiquetado")
    fecha = re.search(
        r"(?:TEST\s*DATE|DATUM\s*(?:TEST)?|FECHA\s*(?:DE\s*)?PRUEBA)\D{0,16}"
        r"(\d{4}-\d{2}-\d{2})", mayus)
    if fecha:
        agregar("test_date", fecha.group(1), fecha.group(1), confianza, "fecha_prueba_etiquetada")
    return candidatos


def _evidencia_ruta(caso: dict) -> list[dict]:
    salida = []
    for clave, valor in caso.get("metadata_ruta", {}).items():
        if clave not in {"test_number", "module_version", "inflator_type", "temperature_condition"}:
            continue
        salida.append({
            "clave": clave, "valor_original": (caso["metadata_ruta"].get(
                "module_version_original") if clave == "module_version" else valor),
            "valor_normalizado": valor, "fuente": "ruta_carpeta", "imagen": None,
            "fase": None, "tor": None, "confianza_ocr": 1.0,
            "valido_catalogo": True, "valido_regex": True,
            "regla_aplicada": ("alias_module_version" if clave == "module_version" and
                                caso["metadata_ruta"].get("module_version_original") == "RWD"
                                else "estructura_caso"),
        })
    return salida


def consolidar_caso(caso: dict, evidencias: Iterable[dict],
                     requeridos: set[str] | None = None,
                     reglas_confirmadas: Iterable[dict] = ()) -> dict:
    requeridos = requeridos or CAMPOS_REQUERIDOS_DEFAULT
    todos = [*_evidencia_ruta(caso), *list(evidencias)]
    por_clave: dict[str, list[dict]] = defaultdict(list)
    for evidencia in todos:
        if evidencia.get("clave") in CLAVES_PLANTILLA and evidencia.get("valor_normalizado") not in {None, ""}:
            por_clave[evidencia["clave"]].append(evidencia)
    campos: dict[str, dict] = {}
    conflictos: list[str] = []
    for clave in CLAVES_PLANTILLA:
        items = por_clave.get(clave, [])
        por_valor: dict[str, list[dict]] = defaultdict(list)
        for item in items:
            por_valor[str(item["valor_normalizado"])].append(item)
        ruta = [i for i in items if i.get("fuente") == "ruta_carpeta"]
        ocr_valores = {v for v, xs in por_valor.items() if any(x.get("fuente") == "ocr" for x in xs)}
        if ruta:
            seguro = str(ruta[0]["valor_normalizado"])
            incompatibles = sorted(v for v in ocr_valores if v != seguro)
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
            estado = "confirmado_multiples_imagenes" if len(imagenes) > 1 else "extraido_ocr"
            campos[clave] = {"valor": valor, "estado": estado,
                             "confianza": round(min(0.99, confianza_base + 0.03 * (len(imagenes) - 1)), 4),
                             "inferido": False, "candidatos": coincidencias, "fuentes": imagenes}
        elif len(por_valor) > 1:
            conflictos.append(clave)
            campos[clave] = {"valor": None, "estado": "conflicto",
                             "requiere_revision": True, "candidatos": items,
                             "fuentes": sorted({i.get("imagen") for i in items if i.get("imagen")})}
        else:
            campos[clave] = {"valor": None,
                             "estado": "faltante_requerido" if clave in requeridos else "faltante",
                             "requerido": clave in requeridos,
                             "requiere_revision": clave in requeridos}

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
    if fecha_prueba and not campos.get("week", {}).get("valor"):
        try:
            semana = datetime.strptime(str(fecha_prueba), "%Y-%m-%d").date().isocalendar().week
            campos["week"] = {"valor": semana, "estado": "derivado",
                              "fuente": "test_date", "confianza":
                              campos["test_date"].get("confianza"), "inferido": False,
                              "requiere_revision": False}
        except ValueError:
            pass

    faltantes = [k for k, v in campos.items() if str(v.get("estado", "")).startswith("faltante")]
    requiere_revision = bool(conflictos or any(campos[k].get("requiere_revision") for k in campos))
    return {"case_key": caso["case_key"], "test_number": caso.get("metadata_ruta", {}).get("test_number"),
            "tipo_st": caso.get("tipo_st"), "campos": campos, "candidatos": todos,
            "campos_faltantes": faltantes, "conflictos": conflictos,
            "requiere_revision": requiere_revision}


class CacheOCR:
    """Caché JSON atómica por huella de archivo, parser y configuración OCR."""

    def __init__(self, ruta: str | Path, config_ocr: dict):
        self.ruta = Path(ruta)
        serial = json.dumps(config_ocr, ensure_ascii=False, sort_keys=True, default=str)
        self.config_version = hashlib.sha256(serial.encode()).hexdigest()[:16]
        try:
            self.datos = json.loads(self.ruta.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self.datos = {"version_parser": VERSION_PARSER, "imagenes": {}}

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
        item = self.datos.get("imagenes", {}).get(clave)
        return deepcopy(item.get("resultado")) if item else None

    def guardar(self, ruta: str | Path, resultado: dict) -> None:
        clave, firma = self._clave(ruta)
        self.datos.setdefault("imagenes", {})[clave] = {
            **firma, "actualizado_en": ahora(), "resultado": resultado}
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        fd, temporal = tempfile.mkstemp(prefix=self.ruta.name, suffix=".tmp", dir=self.ruta.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as archivo:
                json.dump(self.datos, archivo, ensure_ascii=False, indent=2)
            os.replace(temporal, self.ruta)
        finally:
            if os.path.exists(temporal):
                os.unlink(temporal)


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
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.datos["actualizado_en"] = ahora()
        self.ruta.write_text(json.dumps(self.datos, ensure_ascii=False, indent=2), encoding="utf-8")
