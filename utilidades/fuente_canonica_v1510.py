"""Conciliación conservadora por campo (V15.10, modo sombra por defecto).

No convierte un score OCR en verdad y no importa plantillas como evidencia.
Opera exclusivamente sobre registros explícitos de la ejecución/caso vigente.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable

VERSION = "15.10.1"
FUENTES = frozenset({"manual", "imagen_ocr", "qr", "ruta", "video_overlay", "metadatos"})


def _fecha(texto):
    if not texto:
        return None
    try:
        d = datetime.fromisoformat(str(texto).replace("Z", "+00:00"))
        if d.tzinfo is None:
            return None  # fecha sin zona temporal no decide precedencia
        return d.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _valor(v):
    if v is None or isinstance(v, (dict, list, set)):
        return None
    return str(v).strip() or None


def resolver_campo(evidencias: Iterable[dict], *, project_id: str, case_key: str,
                   campo: str, auto_publicacion: bool = False) -> dict:
    """Resuelve un campo con historial inmutable y procedencia verificable.

    Solo se admiten fuentes con identidad de caso/proyecto exacta. Correcciones
    humanas confirmadas ganan por fecha **si es comparable**. Fechas ambiguas
    o empates contradictorios generan conflicto sin sobreescribir historial.
    """
    permitidas = []
    rechazadas = []
    for pos, e in enumerate(evidencias):
        if not isinstance(e, dict):
            rechazadas.append({"indice": pos, "motivo": "registro_invalido"}); continue
        if e.get("project_id") != project_id or e.get("case_key") != case_key or e.get("campo") != campo:
            rechazadas.append({"indice": pos, "motivo": "identidad_incompatible"}); continue
        v = _valor(e.get("candidato", e.get("valor")))
        if v is None:
            rechazadas.append({"indice": pos, "motivo": "valor_ausente"}); continue
        f = str(e.get("fuente") or "")
        if f not in FUENTES or f == "plantilla":
            rechazadas.append({"indice": pos, "motivo": "fuente_no_confiable"}); continue
        permitidas.append({"indice": pos, "valor": v, "fuente": f,
                          "fecha": _fecha(e.get("corregido_en") or e.get("fecha")),
                          "sha": str(e.get("archivo_sha256") or ""),
                          "confirmado": bool(e.get("confirmado_por_humano")),
                          "id": str(e.get("id") or pos), "evidencia": e})
    base = {"project_id": project_id, "case_key": case_key, "campo": campo,
            "valor": None, "estado": "no_observado", "fuentes": [], "rechazadas": rechazadas,
            "conflictos": [], "version_reglas": VERSION, "motivos": [], "confianza_calibrada": None}
    if not permitidas:
        base["motivos"] = ["sin_evidencia_valida"]
        return base
    humanos = [e for e in permitidas if e["fuente"] == "manual" and e["confirmado"]]
    if humanos:
        if any(e["fecha"] is None for e in humanos) and len({e["valor"] for e in humanos}) > 1:
            return {**base, "estado": "conflicto", "fuentes": [x["id"] for x in humanos],
                    "conflictos": sorted({x["valor"] for x in humanos}),
                    "motivos": ["correcciones_humanas_sin_fecha_comparable"]}
        orden = sorted(humanos, key=lambda e: (e["fecha"] or datetime.min.replace(tzinfo=timezone.utc)))
        reciente = orden[-1]
        empate = [e for e in orden if e["fecha"] == reciente["fecha"]]
        if len({e["valor"] for e in empate}) > 1:
            return {**base, "estado": "conflicto", "fuentes": [x["id"] for x in empate],
                    "conflictos": sorted({x["valor"] for x in empate}),
                    "motivos": ["correcciones_humanas_simultaneas_incompatibles"]}
        base.update(valor=reciente["valor"], estado="verificado_humano",
                    fuentes=[e["id"] for e in empate],
                    motivos=["ultima_correccion_humana_por_campo"])
        return base
    por_valor = defaultdict(list)
    for e in permitidas:
        por_valor[e["valor"]].append(e)
    # Variantes OCR de una imagen (mismo SHA) NO constituyen pruebas independientes.
    def independiente(es):
        return {x["sha"] for x in es if x["sha"] and x["fuente"] in {"qr", "imagen_ocr"}}
    grupos = sorted(por_valor.items(), key=lambda kv: (-len(independiente(kv[1])), kv[0]))
    ganador, evid = grupos[0]
    if len(grupos) > 1:
        base.update(estado="conflicto", conflictos=[v for v, _ in grupos],
                    fuentes=[e["id"] for e in permitidas],
                    motivos=["valores_distintos_sin_verificacion_humana"])
        return base
    independientes = independiente(evid)
    # La auto-publicación queda deshabilitada si no hay política calibrada.
    base.update(valor=ganador, estado="propuesta", fuentes=[e["id"] for e in evid],
                motivos=["evidencia_concordante_no_calibrada" if len(independientes) >= 2
                         else "evidencia_aislada_o_correlacionada"])
    if auto_publicacion:
        base["motivos"].append("auto_publicacion_bloqueada_sin_calibracion")
    return base


def resolver_caso(evidencias: Iterable[dict], *, project_id: str, case_key: str) -> dict:
    """Instantánea por caso; no reinterpreta ni certifica observaciones OCR."""
    datos = list(evidencias)
    campos = sorted({str(e.get("campo")) for e in datos if isinstance(e, dict)
                     and e.get("project_id") == project_id and e.get("case_key") == case_key
                     and e.get("campo")})
    return {"project_id": project_id, "case_key": case_key, "version": VERSION,
            "campos": {c: resolver_campo(datos, project_id=project_id, case_key=case_key, campo=c)
                       for c in campos}}
