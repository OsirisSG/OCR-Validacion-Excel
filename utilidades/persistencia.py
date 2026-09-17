"""Persistencia JSON atómica y tolerante a bloqueos temporales de Windows."""

from __future__ import annotations

import json
import os
import threading
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class AdvertenciaPersistencia(RuntimeWarning):
    """Una escritura recuperable falló sin invalidar el trabajo en memoria."""


@dataclass(frozen=True)
class ResultadoPersistencia:
    guardado: bool
    destino: Path
    intentos: int
    error: str | None = None

    def __bool__(self) -> bool:
        return self.guardado


_BLOQUEOS: dict[str, threading.RLock] = {}
_GUARDA_BLOQUEOS = threading.Lock()


def _bloqueo_para(destino: Path) -> threading.RLock:
    clave = str(destino.resolve(strict=False))
    with _GUARDA_BLOQUEOS:
        return _BLOQUEOS.setdefault(clave, threading.RLock())


def _temporal_unico(destino: Path) -> Path:
    return destino.with_name(
        f".{destino.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp")


def _avisar(destino: Path, exc: BaseException,
            callback: Callable[[str], None] | None) -> str:
    mensaje = (
        f"No se pudo actualizar {destino}; se conserva la última versión válida. "
        f"{type(exc).__name__}: {exc}")
    warnings.warn(mensaje, AdvertenciaPersistencia, stacklevel=3)
    if callback:
        callback(mensaje)
    return mensaje


def escribir_json_seguro(
        destino: str | Path, contenido: Any, *, intentos: int = 8,
        espera_inicial: float = 0.025, default: Callable[[Any], Any] | None = str,
        lanzar: bool = False,
        al_error: Callable[[str], None] | None = None) -> ResultadoPersistencia:
    """Escribe JSON sin exponer un archivo parcial ni reutilizar un ``.tmp`` fijo.

    Cada destino tiene un ``RLock`` dentro del proceso. El temporal se crea en el
    mismo directorio para que ``os.replace`` sea atómico. En Windows, antivirus,
    indexadores o Excel pueden retener brevemente el archivo; por eso un
    ``PermissionError`` se reintenta con espera progresiva. Si finalmente falla,
    el destino anterior permanece intacto y, salvo ``lanzar=True``, se devuelve
    un resultado fallido sin interrumpir el OCR.
    """
    ruta = Path(destino)
    total_intentos = max(1, int(intentos))
    temporal: Path | None = None
    ultimo_error: BaseException | None = None
    with _bloqueo_para(ruta):
        try:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            temporal = _temporal_unico(ruta)
            with open(temporal, "w", encoding="utf-8", newline="\n") as archivo:
                json.dump(contenido, archivo, ensure_ascii=False, indent=2, default=default)
                archivo.flush()
                os.fsync(archivo.fileno())
            for numero in range(1, total_intentos + 1):
                try:
                    os.replace(temporal, ruta)
                    temporal = None
                    return ResultadoPersistencia(True, ruta, numero)
                except PermissionError as exc:
                    ultimo_error = exc
                    if numero < total_intentos:
                        time.sleep(max(0.0, espera_inicial) * numero)
            assert ultimo_error is not None
            if lanzar:
                raise ultimo_error
            mensaje = _avisar(ruta, ultimo_error, al_error)
            return ResultadoPersistencia(False, ruta, total_intentos, mensaje)
        except (OSError, TypeError, ValueError) as exc:
            mensaje = _avisar(ruta, exc, al_error)
            if lanzar:
                raise
            return ResultadoPersistencia(False, ruta, 0, mensaje)
        finally:
            if temporal is not None:
                try:
                    temporal.unlink(missing_ok=True)
                except OSError:
                    pass
