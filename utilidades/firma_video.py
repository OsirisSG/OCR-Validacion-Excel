"""Identidad estable de un archivo de video (V15.7.1).

Hasta V15.7 la firma era ``ruta|tamaño|mtime``: al copiar o mover la carpeta
del lote (p.ej. a ``copia\\RT\\...``) cambiaba y se perdían revisiones
manuales, zonas bloqueadas y ejemplos aprendidos. Ahora la firma principal
depende sólo del contenido; la antigua se conserva para reconocer los datos
guardados por versiones anteriores.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

_BLOQUE = 1024 * 1024
_memo: dict[tuple[str, int, int], str] = {}


def firma_legacy(ruta: str | Path) -> str:
    """Firma usada hasta V15.7 (depende de la ubicación del archivo)."""
    p = Path(ruta).resolve()
    st = p.stat()
    return hashlib.sha256(f"{p}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()


def firma_contenido(ruta: str | Path) -> str:
    """Tamaño + primer y último MiB: igual aunque el archivo cambie de carpeta."""
    p = Path(ruta).resolve()
    st = p.stat()
    clave = (str(p), int(st.st_size), int(st.st_mtime_ns))
    if clave in _memo:
        return _memo[clave]
    h = hashlib.sha256(f"video-v1|{st.st_size}|".encode())
    with open(p, "rb") as f:
        h.update(f.read(_BLOQUE))
        if st.st_size > 2 * _BLOQUE:
            f.seek(-_BLOQUE, 2)
            h.update(f.read(_BLOQUE))
    firma = "c1-" + h.hexdigest()
    if len(_memo) > 4096:
        _memo.clear()
    _memo[clave] = firma
    return firma


def clave_ruta(ruta: str | Path | None) -> str:
    """Últimos 3 componentes (ID / VIDEOS / archivo) sin distinguir mayúsculas.

    Acepta rutas de Windows aunque se procesen en otro sistema.
    """
    texto = str(ruta or "").replace("\\", "/").rstrip("/")
    partes = [x for x in texto.split("/") if x]
    return "/".join(partes[-3:]).casefold()


def identidad(ruta: str | Path) -> dict:
    """Datos que se guardan junto a cada registro para reencontrarlo."""
    p = Path(ruta).resolve()
    return {"firma": firma_contenido(p), "firma_legacy": firma_legacy(p),
            "tamano": int(p.stat().st_size), "clave_ruta": clave_ruta(p)}


def coincide(registro: dict, ident: dict, campo_firma: str = "firma",
             campo_ruta: str = "ruta_video") -> bool:
    """¿El registro guardado pertenece al video con identidad ``ident``?"""
    if not isinstance(registro, dict):
        return False
    guardada = registro.get(campo_firma)
    if guardada and guardada in {ident.get("firma"), ident.get("firma_legacy")}:
        return True
    if registro.get("firma_contenido") and registro.get("firma_contenido") == ident.get("firma"):
        return True
    # Registros antiguos de una carpeta movida: misma ID/VIDEOS/archivo y, si se
    # conoce, mismo tamaño.
    ruta_guardada = registro.get(campo_ruta)
    if ruta_guardada and clave_ruta(ruta_guardada) == ident.get("clave_ruta"):
        tam = registro.get("tamano")
        return tam is None or int(tam) == int(ident.get("tamano") or -1)
    return False


def buscar(registros: Iterable[dict], ident: dict, campo_firma: str = "firma",
           campo_ruta: str = "ruta_video") -> dict | None:
    """Prioriza la coincidencia por firma; la ruta sólo como último recurso."""
    lista = [r for r in registros if isinstance(r, dict)]
    for r in reversed(lista):
        if r.get(campo_firma) in {ident.get("firma"), ident.get("firma_legacy")} and r.get(campo_firma):
            return r
    for r in reversed(lista):
        if coincide(r, ident, campo_firma, campo_ruta):
            return r
    return None
