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


# ---------------------------------------------------------------------------
# V15.9.2 (C7): identidad de proyecto declarada por el usuario
# ---------------------------------------------------------------------------

PROYECTO_SIN_ASIGNAR = "sin-asignar"
LONGITUD_MAXIMA_NOMBRE_PROYECTO = 120


def normalizar_nombre_proyecto(nombre: str | None) -> str:
    """Texto visible del proyecto: recortado, sin espacios sobrantes."""
    texto = " ".join(str(nombre or "").split())
    return texto[:LONGITUD_MAXIMA_NOMBRE_PROYECTO]


def proyecto_id_desde_nombre(nombre: str | None) -> str:
    """ID técnico estable derivado del nombre visible declarado."""
    return _slug(normalizar_nombre_proyecto(nombre), "proyecto")


def resolver_identidad_proyecto(*, declarado: dict | None = None,
                                raiz: str | Path | None = None,
                                configurado: str | None = None,
                                checkpoint: dict | None = None) -> dict:
    """Origen autoritativo del proyecto de UNA ejecución (C7).

    Prioridad: ``checkpoint`` (reanudación: conserva el proyecto inicial) >
    ``declarado`` (elección humana en esta ejecución, incluido el «Sin
    asignar» expreso) > ``configurado`` (config empresarial legacy) >
    nombre de carpeta (sólo compatibilidad legacy, siempre pendiente).

    La plantilla Excel NUNCA es fuente de identidad: no se consulta aquí.
    Devuelve ``{nombre_proyecto, project_id, origen, sin_asignar, pendiente,
    responsable}``.
    """
    for fuente, origen in ((checkpoint, "checkpoint"), (declarado, "declarado_usuario")):
        if not isinstance(fuente, dict):
            continue
        if not (fuente.get("nombre_proyecto") or fuente.get("proyecto_id")
                or fuente.get("sin_asignar")):
            continue
        if fuente.get("sin_asignar"):
            return {"nombre_proyecto": None,
                    "project_id": str(fuente.get("proyecto_id") or PROYECTO_SIN_ASIGNAR),
                    "origen": ("sin_asignar_expreso" if origen == "declarado_usuario"
                               else "checkpoint"),
                    "sin_asignar": True, "pendiente": True,
                    "responsable": fuente.get("usuario") or fuente.get("responsable")}
        nombre = normalizar_nombre_proyecto(fuente.get("nombre_proyecto"))
        pid = _slug(fuente.get("proyecto_id") or nombre, "proyecto") if nombre \
            else _slug(fuente.get("proyecto_id"), "proyecto")
        return {"nombre_proyecto": nombre or None, "project_id": pid,
                "origen": origen, "sin_asignar": False,
                "pendiente": not nombre,
                "responsable": fuente.get("usuario") or fuente.get("responsable")}
    if configurado:
        return {"nombre_proyecto": normalizar_nombre_proyecto(configurado) or None,
                "project_id": _slug(configurado, "proyecto"),
                "origen": "configuracion", "sin_asignar": False, "pendiente": False,
                "responsable": None}
    if raiz is not None:
        # Legacy (C7/P11): se conserva el project_id histórico derivado de la
        # carpeta, pero la identidad visible queda PENDIENTE de confirmación:
        # no se adopta silenciosamente como proyecto declarado.
        return {"nombre_proyecto": None,
                "project_id": _slug(Path(raiz).name, "proyecto"),
                "origen": "nombre_carpeta_legacy", "sin_asignar": False,
                "pendiente": True, "responsable": None}
    return {"nombre_proyecto": None, "project_id": PROYECTO_SIN_ASIGNAR,
            "origen": "sin_datos", "sin_asignar": True, "pendiente": True,
            "responsable": None}
