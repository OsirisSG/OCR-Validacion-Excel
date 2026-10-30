"""Extracción conservadora de metadatos institucionales desde OCR para el reporte BMG.

No usa el texto OCR como identidad de proyecto. Sólo recupera términos técnicos
visibles (programa VW, xNN, PAB, BMG, COP BFA) y los presenta con etiquetas
localizadas ES/EN/DE. Si OCR no aporta un término, se conserva el término
institucional de la plantilla como fallback explícito.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable


_RE_VW = re.compile(r"\bVW\s*([0-9]{3}(?:\s*/\s*[0-9]+)?)\b", re.I)
_RE_XPROG = re.compile(r"\bX\s*([0-9]{2,3})\b", re.I)


def _texto_linea(item) -> str:
    if isinstance(item, dict):
        return str(item.get("texto") or item.get("texto_original") or "").strip()
    return str(item or "").strip()


def iterar_textos_ocr(resultados: Iterable[dict]):
    """Emite textos OCR conservando sólo datos observados en resultados."""
    vistos = set()
    for resultado in resultados or []:
        if not isinstance(resultado, dict):
            continue
        for traza in resultado.get("trazabilidad") or []:
            if isinstance(traza, dict):
                txt = str(traza.get("texto_crudo") or "").strip()
                if txt and txt not in vistos:
                    vistos.add(txt); yield txt
        items = list(resultado.get("imagenes") or [])
        for extra in (resultado.get("etiqueta"), resultado.get("referencia")):
            if isinstance(extra, dict):
                items.append(extra)
        for item in items:
            if not isinstance(item, dict):
                continue
            ocr = item.get("resultado_ocr") or {}
            if not isinstance(ocr, dict):
                continue
            candidatos = [str(ocr.get("texto_completo") or "").strip()]
            candidatos += [_texto_linea(x) for x in (ocr.get("lineas_texto") or [])]
            candidatos += [_texto_linea(x) for x in (ocr.get("tokens") or [])]
            for txt in candidatos:
                if txt and txt not in vistos:
                    vistos.add(txt); yield txt


def extraer_metadatos_encabezado(resultados: list[dict]) -> dict:
    textos = list(iterar_textos_ocr(resultados))
    joined = "\n".join(textos)
    upper = joined.upper()
    vw = Counter()
    xprog = Counter()
    for texto in textos:
        for m in _RE_VW.finditer(texto):
            vw[f"VW{m.group(1).replace(' ', '')}"] += 1
        for m in _RE_XPROG.finditer(texto):
            xprog[f"x{m.group(1)}"] += 1
    programa_vw = vw.most_common(1)[0][0] if vw else None
    programa_x = xprog.most_common(1)[0][0] if xprog else None
    return {
        "programa_vw": programa_vw,
        "programa_x": programa_x or "x50",
        "pab_observado": bool(re.search(r"\bPAB\b|BEIFAHRERAIRBAG|PASSENGER\s*AIRBAG", upper)),
        "bmg_observado": "BMG" in upper,
        "cop_bfa_observado": bool(re.search(r"COP\s*BFA", upper)),
        "fuentes_ocr": len(textos),
        "fuente": "ocr" if textos else "fallback_plantilla",
    }


_T = {
    "es": {
        "linea_bmg": "Pruebas IT BMG / Programa {x} (1ra y 2da)",
        "linea_cop": "Desarrollo IT / Módulos COP BFA",
        "grupo_prueba": "Prueba / Ensayo",
        "grupo_pab": "Airbag del pasajero (PAB)",
        "grupo_panel_zsb": "Conjunto tablero de instrumentos",
        "grupo_sub": "Evaluación de subcomponentes",
        "grupo_airbag": "Airbag del pasajero",
        "grupo_panel": "Tablero de instrumentos",
    },
    "en": {
        "linea_bmg": "IT BMG Tests / {x} Program (1st & 2nd)",
        "linea_cop": "IT Development / COP BFA Modules",
        "grupo_prueba": "Test",
        "grupo_pab": "Passenger airbag (PAB)",
        "grupo_panel_zsb": "Instrument panel assembly",
        "grupo_sub": "Subcomponent evaluation",
        "grupo_airbag": "Passenger airbag",
        "grupo_panel": "Instrument panel",
    },
    "de": {
        "linea_bmg": "IT BMG Versuche / {x} Programm (1. & 2. Stufe)",
        "linea_cop": "IT Entwicklung / COP BFA Module",
        "grupo_prueba": "Versuch",
        "grupo_pab": "Beifahrerairbag (PAB)",
        "grupo_panel_zsb": "ZSB Instrumententafel",
        "grupo_sub": "Bewertung Unterkomponenten",
        "grupo_airbag": "Beifahrerairbag",
        "grupo_panel": "Instrumententafel",
    },
}


def textos_institucionales(resultados: list[dict], idioma: str = "es") -> dict:
    idioma = idioma if idioma in _T else "es"
    meta = extraer_metadatos_encabezado(resultados)
    t = _T[idioma]
    return {
        **meta,
        "linea_bmg": t["linea_bmg"].format(x=meta["programa_x"]),
        "linea_cop": t["linea_cop"],
        "grupos": {k: t[k] for k in (
            "grupo_prueba", "grupo_pab", "grupo_panel_zsb", "grupo_sub",
            "grupo_airbag", "grupo_panel")},
    }
