"""Identidades portables para proyecto/etapa/caso, sin depender de rutas absolutas."""
from __future__ import annotations
import hashlib
import re
from pathlib import Path


def _slug(valor: str | None, fallback: str = "sin_valor") -> str:
    texto = str(valor or "").strip().lower()
    texto = re.sub(r"[^a-z0-9._-]+", "-", texto).strip("-")
    return texto or fallback


def proyecto_id(raiz: str | Path, configurado: str | None = None) -> str:
    return _slug(configurado or Path(raiz).name, "proyecto")


def identidad_caso(proyecto: str, etapa: str | None, numero: str | None,
                    nombre_caso: str | None, ruta_relativa: str | None) -> str:
    base = "|".join((_slug(proyecto, "proyecto"), _slug(etapa, "sin_st"),
                     _slug(numero, "sin_numero"), _slug(nombre_caso, "caso")))
    # La ruta relativa sólo desambigua casos repetidos dentro del mismo proyecto;
    # el hash evita exponer separadores o depender de una ruta absoluta.
    huella = hashlib.sha256(str(ruta_relativa or "").replace("\\", "/").encode("utf-8")).hexdigest()[:10]
    return f"{base}|{huella}"
