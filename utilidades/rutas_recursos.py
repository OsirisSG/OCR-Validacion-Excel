"""Resolución segura y portable de imágenes/videos del lote.

V15.10.1 R3
------------
Corrige dos problemas observados en producción:
1. una ``raiz_datos_permitida`` obsoleta impedía usar la raíz válida guardada
   en ``validacion_resultados.json``;
2. rutas Windows reubicadas podían no resolverse por diferencias de mayúsculas,
   separadores o porque el lote fue movido conservando su estructura relativa.

La política sigue siendo restrictiva: este módulo sólo ayuda a encontrar la
raíz/archivo local equivalente. El endpoint debe seguir comprobando que la ruta
solicitada pertenece al inventario registrado del lote.
"""
from __future__ import annotations

import os
import re
from pathlib import Path, PureWindowsPath
from typing import Iterable

_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def es_ruta_windows(ruta: str | os.PathLike | None) -> bool:
    texto = str(ruta or "")
    return bool(_DRIVE_RE.match(texto)) or "\\" in texto


def partes_portables(ruta: str | os.PathLike | None) -> tuple[str, ...]:
    texto = str(ruta or "")
    if es_ruta_windows(texto):
        return tuple(PureWindowsPath(texto).parts)
    return tuple(Path(texto).parts)


def _partes_comparables(ruta: str | os.PathLike | None) -> tuple[str, ...]:
    partes = partes_portables(ruta)
    if es_ruta_windows(ruta):
        return tuple(str(p).casefold() for p in partes)
    return tuple(str(p) for p in partes)


def _resolver_directa(valor: str | os.PathLike | None) -> Path | None:
    texto = str(valor or "").strip().strip('"\'')
    if not texto:
        return None
    try:
        p = Path(texto).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    return p if p.exists() else None


def _iter_rutas_registradas(datos: dict) -> Iterable[str]:
    for fila in datos.get("resultados", []) or []:
        if fila.get("ruta"):
            yield str(fila["ruta"])
        for clave in ("imagenes", "videos"):
            for item in fila.get(clave, []) or []:
                if isinstance(item, dict) and item.get("ruta"):
                    yield str(item["ruta"])
        for clave in ("etiqueta", "referencia"):
            item = fila.get(clave)
            if isinstance(item, dict) and item.get("ruta"):
                yield str(item["ruta"])


def _inferir_raiz_desde_resultados(datos: dict, limite: int = 256) -> Path | None:
    """Obtiene un ancestro común únicamente a partir de rutas YA registradas.

    Se usa sólo como último recurso cuando tanto la configuración como la raíz
    persistida quedaron obsoletas. No amplía el inventario autorizado: el
    consumidor debe continuar validando la ruta contra las entradas registradas.
    """
    existentes: list[Path] = []
    for ruta in _iter_rutas_registradas(datos):
        if len(existentes) >= limite:
            break
        directa = _resolver_directa(ruta)
        if directa is None:
            continue
        existentes.append(directa if directa.is_dir() else directa.parent)
    if not existentes:
        return None
    try:
        comun = Path(os.path.commonpath([str(p) for p in existentes])).resolve()
    except (ValueError, OSError, RuntimeError):
        return existentes[0]
    return comun if comun.is_dir() else comun.parent


def resolver_raiz_datos(datos: dict, configurada: str | os.PathLike | None = None,
                         raiz_proyecto: str | os.PathLike | None = None) -> Path | None:
    """Resuelve la raíz efectiva sin dejar que una configuración vieja bloquee.

    Orden de confianza:
    1. raíz configurada *si existe*;
    2. raíz guardada en los resultados *si existe*;
    3. reubicación conservando una carpeta conocida bajo ``raiz_proyecto``;
    4. ancestro común de archivos realmente existentes y ya registrados.
    """
    candidatos = []
    for valor in (configurada, datos.get("raiz")):
        texto = str(valor or "").strip()
        if texto and texto not in candidatos:
            candidatos.append(texto)
    for valor in candidatos:
        p = _resolver_directa(valor)
        if p is not None and p.is_dir():
            return p

    raiz_local = Path(raiz_proyecto).resolve() if raiz_proyecto else None
    if raiz_local:
        for valor in candidatos:
            partes = partes_portables(valor)
            comparables = _partes_comparables(valor)
            for marcador in ("datos_prueba", "datos", "data", "imagenes", "images"):
                try:
                    idx = comparables.index(marcador.casefold() if es_ruta_windows(valor) else marcador)
                except ValueError:
                    continue
                candidata = raiz_local.joinpath(*partes[idx:]).resolve()
                try:
                    segura = candidata.is_relative_to(raiz_local)
                except AttributeError:  # pragma: no cover - Python < 3.9
                    segura = str(candidata).startswith(str(raiz_local))
                if candidata.is_dir() and segura:
                    return candidata

    return _inferir_raiz_desde_resultados(datos)


def reubicar_ruta(ruta: str, datos: dict, raiz: Path) -> Path | None:
    """Convierte una ruta persistida a su archivo local equivalente.

    Mantiene compatibilidad con rutas relativas y con lotes movidos. Para rutas
    Windows compara las partes sin distinguir mayúsculas/minúsculas.
    """
    ruta_texto = str(ruta or "").strip()
    if not ruta_texto:
        return None

    directa = _resolver_directa(ruta_texto)
    if directa is not None:
        return directa

    # Ruta relativa guardada por el pipeline.
    if not es_ruta_windows(ruta_texto) and not Path(ruta_texto).is_absolute():
        partes_relativas = partes_portables(ruta_texto)
        candidata = raiz.joinpath(*partes_relativas).resolve()
        try:
            segura = candidata.is_relative_to(raiz.resolve())
        except AttributeError:  # pragma: no cover
            segura = str(candidata).startswith(str(raiz.resolve()))
        if candidata.exists() and segura:
            return candidata

    partes_ruta = partes_portables(ruta_texto)
    comparables_ruta = _partes_comparables(ruta_texto)

    # Primero usa la raíz histórica exacta registrada en la corrida.
    for raiz_original in (datos.get("raiz"),):
        if not raiz_original:
            continue
        partes_base = partes_portables(raiz_original)
        comparables_base = _partes_comparables(raiz_original)
        n = len(partes_base)
        if n and comparables_ruta[:n] == comparables_base:
            candidata = raiz.joinpath(*partes_ruta[n:]).resolve()
            try:
                segura = candidata.is_relative_to(raiz.resolve())
            except AttributeError:  # pragma: no cover
                segura = str(candidata).startswith(str(raiz.resolve()))
            if candidata.exists() and segura:
                return candidata

    # Último fallback: localizar dentro de la raíz por el sufijo más largo que
    # exista. Evita depender del nombre de la carpeta padre tras mover el lote.
    # Nunca sale de ``raiz``.
    inicio = 1 if partes_ruta and (partes_ruta[0].endswith("\\") or partes_ruta[0] == os.sep) else 0
    for i in range(max(inicio, len(partes_ruta) - 8), len(partes_ruta)):
        sufijo = partes_ruta[i:]
        if not sufijo:
            continue
        candidata = raiz.joinpath(*sufijo).resolve()
        try:
            segura = candidata.is_relative_to(raiz.resolve())
        except AttributeError:  # pragma: no cover
            segura = str(candidata).startswith(str(raiz.resolve()))
        if candidata.exists() and segura:
            return candidata
    return None
