"""Política conservadora de decisión para V15.10.1.

Separa candidato, verificación y sincronización. En caso de duda, abstiene.
"""
from __future__ import annotations

from typing import Any

VERSION_POLITICA = "politica-apertura-v1"


def _extraer_tiempo(candidato: dict | None) -> float | None:
    if not isinstance(candidato, dict):
        return None
    for clave in ("tiempo_ms", "tiempo_local_ms"):
        valor = candidato.get(clave)
        try:
            numero = float(valor)
        except (TypeError, ValueError):
            continue
        if numero > 0:
            return round(numero, 6)
    return None


def decidir_apertura(*,
                     candidato: dict | None,
                     verificacion: dict | None = None,
                     sincronizacion: dict | None = None,
                     evento_al_inicio: bool = False,
                     analisis_completo: bool = False,
                     tiempo_verificado: bool = False,
                     revision_manual: dict | None = None,
                     auto_publicacion_habilitada: bool = False,
                     calibracion_validada: bool = False,
                     politica_aprobada: bool = False) -> dict:
    candidato = candidato if isinstance(candidato, dict) else None
    verificacion = verificacion if isinstance(verificacion, dict) else {}
    sincronizacion = sincronizacion if isinstance(sincronizacion, dict) else {}
    revision_manual = revision_manual if isinstance(revision_manual, dict) else {}
    tiempo_propuesto = _extraer_tiempo(candidato)
    motivos: list[str] = []

    if revision_manual.get("estado") == "confirmado":
        tiempo_manual = _extraer_tiempo(revision_manual)
        return {
            "estado": "VERIFICADO_HUMANO",
            "tiempo_ms": tiempo_manual,
            "tiempo_propuesto_ms": None,
            "motivos": ["revision_manual_confirmada"],
            "auto_confirmable": False,
            "probabilidad_calibrada": None,
            "version_politica": VERSION_POLITICA,
        }
    if revision_manual.get("estado") == "sin_evento":
        return {
            "estado": "SIN_EVENTO",
            "tiempo_ms": None,
            "tiempo_propuesto_ms": None,
            "motivos": ["revision_manual_sin_evento"],
            "auto_confirmable": False,
            "probabilidad_calibrada": None,
            "version_politica": VERSION_POLITICA,
        }

    if evento_al_inicio:
        return {
            "estado": "EVENTO_AL_INICIO",
            "tiempo_ms": None,
            "tiempo_propuesto_ms": tiempo_propuesto,
            "motivos": ["evento_censurado_por_izquierda"],
            "auto_confirmable": False,
            "probabilidad_calibrada": None,
            "version_politica": VERSION_POLITICA,
        }

    if candidato is None:
        return {
            "estado": "sin_evento_detectado" if analisis_completo else "no_evaluable",
            "tiempo_ms": None,
            "tiempo_propuesto_ms": None,
            "motivos": ["sin_candidato"] if analisis_completo else ["analisis_incompleto"],
            "auto_confirmable": False,
            "probabilidad_calibrada": None,
            "version_politica": VERSION_POLITICA,
        }

    estado_ver = str(verificacion.get("estado_revision") or "propuesta_revisar")
    razones_contra = list(verificacion.get("razones_en_contra") or [])
    consenso = bool(sincronizacion.get("consenso_sincronizado"))
    soporte = int(sincronizacion.get("soporte_independiente") or 0)

    # Reglas de abstención primero.
    if not tiempo_verificado:
        motivos.append("tiempo_no_verificado")
    if not auto_publicacion_habilitada:
        motivos.append("auto_publicacion_deshabilitada")
    if not calibracion_validada:
        motivos.append("calibracion_no_validada")
    if not politica_aprobada:
        motivos.append("politica_no_aprobada")
    if razones_contra:
        motivos.extend(razones_contra)

    if estado_ver == "revisar_conflicto":
        estado = "revisar_conflicto"
    elif estado_ver == "propuesta_alta_confianza" and not tiempo_verificado:
        estado = "propuesta_alta_confianza"
    elif estado_ver in {"evidencia_corrobora", "propuesta_alta_confianza"}:
        if tiempo_verificado and consenso and soporte >= 3 and auto_publicacion_habilitada and calibracion_validada and politica_aprobada and not razones_contra:
            estado = "confirmado_automatico"
        else:
            estado = "propuesta_revisar"
    else:
        estado = estado_ver

    return {
        "estado": estado,
        "tiempo_ms": (tiempo_propuesto if estado == "confirmado_automatico" else None),
        "tiempo_propuesto_ms": (None if estado == "confirmado_automatico" else tiempo_propuesto),
        "motivos": motivos,
        "auto_confirmable": False,
        "probabilidad_calibrada": None,
        "version_politica": VERSION_POLITICA,
    }
