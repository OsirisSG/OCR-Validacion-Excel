"""Fase A: inventario persistente sin ejecutar reconocimiento OCR."""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Callable

from configuracion import RAIZ_PROYECTO


VERSION_INVENTARIO = 1


def _firma_archivo(ruta: str | Path, calcular_hash: bool = False) -> dict:
    archivo = Path(ruta)
    stat = archivo.stat()
    firma = {
        "tamano": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "hash": None,
    }
    if calcular_hash:
        digest = hashlib.sha256()
        with open(archivo, "rb") as entrada:
            for bloque in iter(lambda: entrada.read(1024 * 1024), b""):
                digest.update(bloque)
        firma["hash"] = digest.hexdigest()
    firma["huella"] = hashlib.sha256(
        f"{archivo.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode()).hexdigest()
    return firma


def crear_inventario(estructura: dict, ruta_salida: str | Path | None = None,
                     calcular_hash: bool = False,
                     al_caso: Callable[[dict], None] | None = None) -> dict:
    """Materializa fotografías y metadatos de ruta sin cargar EasyOCR."""
    casos = []
    total_fotos = 0
    for original in estructura.get("casos_empresariales", []):
        caso = deepcopy(original)
        fotos = []
        for foto_original in caso.get("fotos", []):
            foto = dict(foto_original)
            try:
                foto["firma_archivo"] = _firma_archivo(foto["ruta"], calcular_hash)
                foto["estado_inventario"] = "inventariada"
            except OSError as exc:
                foto["firma_archivo"] = None
                foto["estado_inventario"] = "error_lectura"
                foto["error_inventario"] = f"{type(exc).__name__}: {exc}"
            fotos.append(foto)
        caso["fotos"] = fotos
        caso["total_imagenes"] = len(fotos)
        caso["estado"] = ("inventariada" if caso.get("estructura_valida")
                          else "estructura_incompleta")
        total_fotos += len(fotos)
        casos.append(caso)
        if al_caso:
            al_caso(deepcopy(caso))
    documento = {
        "version": VERSION_INVENTARIO,
        "generado_en": datetime.now().isoformat(timespec="seconds"),
        "raiz": estructura["raiz"],
        "perfil": estructura.get("perfil"),
        "tipo_st": estructura.get("tipo_st"),
        "tipos_st": estructura.get("tipos_st", []),
        "deteccion_st": estructura.get("deteccion_st", {}),
        "requiere_seleccion_tipo_st": estructura.get("requiere_seleccion_tipo_st", False),
        "casos": casos,
        "casos_encontrados": len(casos),
        "casos_validos": sum(bool(c.get("estructura_valida")) for c in casos),
        "casos_incompletos": sum(not c.get("estructura_valida", False) for c in casos),
        "fotografias": total_fotos,
        "configuracion": {"hash_completo": bool(calcular_hash)},
    }
    destino = Path(ruta_salida) if ruta_salida else RAIZ_PROYECTO / "inventario_proyecto.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(destino.suffix + ".tmp")
    with open(temporal, "w", encoding="utf-8") as salida:
        json.dump(documento, salida, ensure_ascii=False, indent=2)
        salida.flush()
        os.fsync(salida.fileno())
    os.replace(temporal, destino)
    documento["archivo_salida"] = str(destino)
    return documento


def cargar_inventario(ruta: str | Path, raiz_esperada: str | Path | None = None) -> dict:
    archivo = Path(ruta)
    documento = json.loads(archivo.read_text(encoding="utf-8"))
    if documento.get("version") != VERSION_INVENTARIO or not isinstance(documento.get("casos"), list):
        raise ValueError("El inventario no tiene una versión o estructura compatible.")
    if raiz_esperada and Path(documento["raiz"]).resolve() != Path(raiz_esperada).resolve():
        raise ValueError("El inventario corresponde a una carpeta raíz diferente.")
    documento["archivo_salida"] = str(archivo.resolve())
    return documento


def estructura_desde_inventario(inventario: dict) -> dict:
    """Reconstruye el contrato mínimo consumido por la Fase B empresarial."""
    return {
        "raiz": inventario["raiz"], "generado_en": inventario.get("generado_en"),
        "total_carpetas": inventario.get("casos_encontrados", 0),
        "patron_dominante": None, "anomalias": [], "carpetas": [],
        "perfil": inventario.get("perfil", "empresarial"),
        "deteccion_st": inventario.get("deteccion_st", {}),
        "tipo_st": inventario.get("tipo_st"), "tipos_st": inventario.get("tipos_st", []),
        "requiere_seleccion_tipo_st": inventario.get("requiere_seleccion_tipo_st", False),
        "casos_empresariales": deepcopy(inventario.get("casos", [])),
        "casos_encontrados": inventario.get("casos_encontrados", 0),
        "casos_validos": inventario.get("casos_validos", 0),
        "casos_incompletos": inventario.get("casos_incompletos", 0),
    }

