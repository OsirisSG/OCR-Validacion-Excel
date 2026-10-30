"""V15.9.2 (C7): registro de proyectos declarados por el usuario.

Fuente autoritativa de identidad: la elección humana confirmada en cada
ejecución. Este registro guarda los proyectos creados desde el dashboard con
su ``project_id`` estable y detecta colisiones (mismo ID con nombre distinto)
en vez de fusionarlas en silencio.

La plantilla Excel NO aparece aquí: es sólo un contrato de columnas/formato.
Las sugerencias derivadas de carpeta u OCR viven en el backend marcadas como
pendientes de aceptación y nunca se registran solas.
"""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from configuracion import RAIZ_PROYECTO
from utilidades.identidad import (PROYECTO_SIN_ASIGNAR, normalizar_nombre_proyecto,
                                  proyecto_id_desde_nombre)
from utilidades.persistencia import escribir_json_seguro

RUTA_PROYECTOS = RAIZ_PROYECTO / ".aprendizaje" / "proyectos.json"
VERSION_REGISTRO = 1
_BLOQUEO = threading.RLock()


class ErrorPersistenciaProyectos(RuntimeError):
    """La escritura verificada del registro falló (C3/C7)."""


class ColisionProyectoError(RuntimeError):
    """Un ``project_id`` ya existe con otro nombre visible (P12)."""

    def __init__(self, mensaje: str, existente: dict | None = None):
        super().__init__(mensaje)
        self.existente = existente or {}


class RegistroProyectosCorruptoError(RuntimeError):
    """El registro existe pero es ilegible (CRIT-04): fallar cerrado.

    V15.9.3: un ``proyectos.json`` corrupto NO se reinicia en memoria ni se
    sobrescribe: la siguiente escritura borraría los proyectos previos. Se
    propaga este error (lecturas y escrituras bloqueadas, cero bytes
    modificados) hasta que el usuario recupere el respaldo o ejecute
    ``recuperar_registro()`` de forma explícita.
    """

    def __init__(self, mensaje: str, ruta: Path | None = None):
        super().__init__(mensaje)
        self.ruta = Path(ruta) if ruta else None


def _leer(ruta: Path) -> dict:
    if not ruta.is_file():
        return {"version": VERSION_REGISTRO, "proyectos": []}
    try:
        import json
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RegistroProyectosCorruptoError(
            f"El registro {ruta} existe pero es ilegible "
            f"({type(exc).__name__}: {exc}). Se bloquean lecturas y escrituras "
            "para no perder proyectos previos: restaura tu respaldo o ejecuta "
            "la recuperación explícita (recuperar_registro), que respalda los "
            "bytes originales antes de inicializar un registro vacío.",
            ruta=ruta) from exc
    if not isinstance(datos, dict) or not isinstance(datos.get("proyectos"), list):
        raise RegistroProyectosCorruptoError(
            f"El registro {ruta} no tiene la estructura esperada "
            "({\"version\": …, \"proyectos\": […]}); se bloquean lecturas y "
            "escrituras para no perder datos. Restaura tu respaldo o ejecuta "
            "recuperar_registro().", ruta=ruta)
    # V15.9.4 (CRIT-N3): estructura parcialmente corrupta TAMBIÉN falla
    # cerrado. Ninguna entrada se filtra ni se descarta en silencio (al
    # guardar, la entrada inválida desaparecería del documento): se valida
    # que CADA elemento sea un objeto con ``proyecto_id`` de texto no vacío y
    # nombre ausente/None/texto, sin IDs duplicados. Ante una sola entrada
    # ilegible se bloquean las escrituras y se conservan los bytes completos
    # hasta recuperación explícita con respaldo SHA-256.
    vistos: set[str] = set()
    for indice, proyecto in enumerate(datos["proyectos"]):
        if not isinstance(proyecto, dict):
            raise RegistroProyectosCorruptoError(
                f"El registro {ruta} tiene una entrada ilegible en la posición "
                f"{indice} ({type(proyecto).__name__} en vez de objeto); no se "
                "descarta en silencio: escrituras bloqueadas hasta "
                "recuperar_registro() o restauración del respaldo.", ruta=ruta)
        pid = proyecto.get("proyecto_id")
        if not isinstance(pid, str) or not pid.strip():
            raise RegistroProyectosCorruptoError(
                f"El registro {ruta} tiene una entrada sin ``proyecto_id`` "
                f"válido en la posición {indice}; escrituras bloqueadas hasta "
                "recuperación explícita (los bytes se conservan).", ruta=ruta)
        nombre = proyecto.get("nombre_proyecto")
        if nombre is not None and not isinstance(nombre, str):
            raise RegistroProyectosCorruptoError(
                f"El registro {ruta} tiene ``nombre_proyecto`` de tipo "
                f"inválido en la posición {indice}; escrituras bloqueadas "
                "hasta recuperación explícita.", ruta=ruta)
        clave = pid.strip().lower()
        if clave in vistos:
            raise RegistroProyectosCorruptoError(
                f"El registro {ruta} contiene ``proyecto_id`` duplicado "
                f"(«{clave}»): el estado es inconsistente con la regla de "
                "colisiones (P12); escrituras bloqueadas hasta recuperación "
                "explícita.", ruta=ruta)
        vistos.add(clave)
    return datos


def recuperar_registro(ruta: str | Path | None = None) -> dict:
    """Recuperación con control explícito del usuario (CRIT-04).

    Respalda los bytes del registro ilegible en
    ``proyectos.json.corrupto-<marca>.bak`` (verificados por SHA-256 antes de
    continuar) e inicializa un registro vacío. Nunca se invoca sola: sólo por
    acción expresa del operador o de mantenimiento.
    """
    import hashlib
    import shutil
    destino = Path(ruta) if ruta else RUTA_PROYECTOS
    if not destino.is_file():
        return {"recuperado": False, "motivo": "registro_inexistente",
                "ruta": str(destino), "respaldo": None}
    try:
        _leer(destino)
    except RegistroProyectosCorruptoError:
        pass
    else:
        return {"recuperado": False, "motivo": "registro_legible",
                "ruta": str(destino), "respaldo": None}
    marca = datetime.now().strftime("%Y%m%d-%H%M%S%f")
    respaldo = destino.with_name(f"{destino.name}.corrupto-{marca}.bak")
    with _BLOQUEO:
        originales = destino.read_bytes()
        digest = hashlib.sha256(originales).hexdigest()
        shutil.copyfile(destino, respaldo)
        if hashlib.sha256(respaldo.read_bytes()).hexdigest() != digest:
            respaldo.unlink(missing_ok=True)
            raise ErrorPersistenciaProyectos(
                f"El respaldo {respaldo.name} no coincide byte a byte con "
                f"{destino.name}; recuperación abortada (el registro no se tocó).")
        _guardar(destino, {"version": VERSION_REGISTRO, "proyectos": []})
    return {"recuperado": True, "ruta": str(destino), "respaldo": str(respaldo),
            "sha256_original": digest}


def _guardar(ruta: Path, datos: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    resultado = escribir_json_seguro(ruta, datos, lanzar=False, compacto=True)
    if not resultado:
        raise ErrorPersistenciaProyectos(
            f"No se pudo guardar {ruta.name}: "
            f"{getattr(resultado, 'error', None) or 'escritura fallida'}. "
            "El registro anterior permanece intacto.")


def listar_proyectos(ruta: str | Path | None = None) -> list[dict]:
    """Proyectos registrados, más recientes primero."""
    destino = Path(ruta) if ruta else RUTA_PROYECTOS
    with _BLOQUEO:
        datos = _leer(destino)
    return sorted(datos["proyectos"],
                  key=lambda p: str(p.get("creado_en") or ""), reverse=True)


def obtener_proyecto(proyecto_id: str, ruta: str | Path | None = None) -> dict | None:
    destino = Path(ruta) if ruta else RUTA_PROYECTOS
    buscado = str(proyecto_id or "").strip().lower()
    with _BLOQUEO:
        datos = _leer(destino)
    return next((p for p in datos["proyectos"]
                 if str(p.get("proyecto_id") or "").lower() == buscado), None)


def registrar_proyecto(nombre_proyecto: str, proyecto_id: str | None = None,
                       responsable: str | None = None,
                       ruta: str | Path | None = None) -> dict:
    """Crea o actualiza un proyecto declarado por el usuario.

    - ``project_id`` explícito y estable si se aporta; si no, se deriva del
      nombre visible (ID normalizado, nunca de la carpeta en modo explícito).
    - Colisión (P12): mismo ID con nombre distinto ⇒ ``ColisionProyectoError``.
      Prohibido fusionar en silencio; el usuario debe resolverlo.
    - Persistencia verificada (C3): si no se guarda, no se declara éxito.
    """
    nombre = normalizar_nombre_proyecto(nombre_proyecto)
    if not nombre:
        raise ValueError("El nombre del proyecto no puede estar vacío.")
    pid = str(proyecto_id or "").strip().lower() or proyecto_id_desde_nombre(nombre)
    if pid == PROYECTO_SIN_ASIGNAR:
        raise ValueError(
            f"«{PROYECTO_SIN_ASIGNAR}» está reservado para la decisión expresa "
            "de no asignar proyecto; no se usa como nombre.")
    destino = Path(ruta) if ruta else RUTA_PROYECTOS
    ahora = datetime.now().isoformat(timespec="seconds")
    with _BLOQUEO:
        datos = _leer(destino)
        existente = next((p for p in datos["proyectos"]
                          if str(p.get("proyecto_id") or "").lower() == pid), None)
        if existente:
            nombre_previo = normalizar_nombre_proyecto(existente.get("nombre_proyecto"))
            if nombre_previo and nombre_previo != nombre:
                raise ColisionProyectoError(
                    f"El ID «{pid}» ya pertenece al proyecto «{nombre_previo}». "
                    f"No se puede registrar «{nombre}» con ese ID: elige otro "
                    "nombre/ID o corrige el proyecto existente (prohibido "
                    "fusionar en silencio).",
                    existente=dict(existente))
            existente["nombre_proyecto"] = nombre
            if responsable:
                existente["responsable"] = str(responsable)
            existente["actualizado_en"] = ahora
            _guardar(destino, datos)
            return dict(existente)
        nuevo = {"proyecto_id": pid, "nombre_proyecto": nombre,
                 "creado_en": ahora, "actualizado_en": ahora,
                 "responsable": str(responsable) if responsable else None,
                 "origen": "declarado_usuario",
                 "ejecuciones": 0, "ultima_ejecucion": None}
        datos["proyectos"].append(nuevo)
        _guardar(destino, datos)
        return dict(nuevo)


def registrar_ejecucion(proyecto_id: str, ejecucion_id: str | None = None,
                        responsable: str | None = None,
                        ruta: str | Path | None = None) -> dict | None:
    """Anota que un proyecto se usó en una ejecución (trazabilidad C7)."""
    pid = str(proyecto_id or "").strip().lower()
    if not pid or pid == PROYECTO_SIN_ASIGNAR:
        return None
    destino = Path(ruta) if ruta else RUTA_PROYECTOS
    ahora = datetime.now().isoformat(timespec="seconds")
    with _BLOQUEO:
        datos = _leer(destino)
        proyecto = next((p for p in datos["proyectos"]
                         if str(p.get("proyecto_id") or "").lower() == pid), None)
        if proyecto is None:
            return None
        proyecto["ejecuciones"] = int(proyecto.get("ejecuciones") or 0) + 1
        proyecto["ultima_ejecucion"] = {"ejecucion_id": ejecucion_id, "en": ahora,
                                        "responsable": responsable}
        proyecto["actualizado_en"] = ahora
        _guardar(destino, datos)
        return dict(proyecto)


def sugerir_desde_datos(datos: dict | None) -> list[dict]:
    """Candidatos SUGERIDOS por carpeta/resultados; pendientes de aceptación.

    Nunca asignan el proyecto por sí solos (C7): el backend los expone como
    sugerencias y el usuario debe confirmarlos expresamente.
    """
    sugerencias: dict[str, dict] = {}

    def _agregar(pid: str, nombre: str | None, origen: str) -> None:
        pid = str(pid or "").strip().lower()
        if not pid or pid == PROYECTO_SIN_ASIGNAR or pid in sugerencias:
            return
        sugerencias[pid] = {"proyecto_id": pid, "nombre_proyecto": nombre,
                            "origen_sugerencia": origen, "sugerencia": True,
                            "pendiente_aceptacion": True}

    if isinstance(datos, dict):
        raiz = datos.get("raiz")
        if raiz:
            _agregar(Path(str(raiz)).name, None, "nombre_carpeta")
        for fila in datos.get("resultados") or []:
            if isinstance(fila, dict) and fila.get("project_id"):
                _agregar(fila["project_id"], None, "resultados_anteriores")
    return list(sugerencias.values())
