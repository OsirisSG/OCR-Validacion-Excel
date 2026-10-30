"""Validaciones preventivas de entradas de usuario para V-Matrix.

No contienen lógica de negocio OCR: sólo rechazan entradas que en Windows o en
el visor producirían fallos tardíos, resultados ambiguos o escrituras inválidas.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Iterable

_RESERVADOS_WINDOWS = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
# R15 (MEDIA-10): Windows también reserva las variantes con superíndices.
_SUPERINDICES_WINDOWS = str.maketrans({"¹": "1", "²": "2", "³": "3"})
_INVALIDOS_WINDOWS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def validar_nombre_excel(nombre: str | None) -> str | None:
    """Normaliza un nombre .xlsx y falla temprano ante nombres inválidos en Windows."""
    if nombre is None:
        return None
    crudo = str(nombre)
    # R15 (MEDIA-10): el valor CRUDO se valida antes del trim: un espacio
    # final es rechazo temprano, no una corrección silenciosa
    # ('archivo ' antes se convertía en 'archivo.xlsx').
    if crudo.endswith(" "):
        raise ValueError("El nombre del Excel no puede terminar en espacio.")
    texto = crudo.strip()
    if not texto:
        return None
    if Path(texto).name != texto or texto in {".", ".."}:
        raise ValueError("Escribe solamente el nombre del Excel, sin carpetas.")
    if _INVALIDOS_WINDOWS.search(texto):
        raise ValueError('El nombre del Excel contiene caracteres no permitidos en Windows: <>:"/\\|?*.')
    if texto.endswith((" ", ".")):
        raise ValueError("El nombre del Excel no puede terminar en espacio o punto.")
    p = Path(texto)
    if p.suffix and p.suffix.lower() != ".xlsx":
        texto = p.with_suffix(".xlsx").name
    elif not p.suffix:
        texto += ".xlsx"
    # R15 (MEDIA-10): en Windows los nombres reservados siguen reservados
    # aunque vayan seguidos de extensiones múltiples (CON.foo.xlsx, NUL.data.
    # xlsx). Se comprueba el PRIMER componente antes del primer punto,
    # incluidas las variantes con superíndices (COM¹/²/³, LPT¹/²/³).
    primer_componente = texto.split(".", 1)[0].strip(" .").upper()
    if (primer_componente in _RESERVADOS_WINDOWS
            or primer_componente.translate(_SUPERINDICES_WINDOWS) in _RESERVADOS_WINDOWS):
        raise ValueError(f"«{primer_componente}» es un nombre reservado por Windows; elige otro nombre para el Excel.")
    if len(texto) > 128:
        raise ValueError("El nombre del Excel es demasiado largo (máximo 128 caracteres).")
    return texto


def validar_bbox_normalizado(valores: Iterable[float], *, min_lado: float = 1e-4) -> list[float]:
    """Valida [x1,y1,x2,y2] normalizado y no sólo cada coordenada aislada."""
    try:
        bbox = [float(v) for v in valores]
    except (TypeError, ValueError) as exc:
        raise ValueError("La zona de video contiene coordenadas inválidas.") from exc
    if len(bbox) != 4 or any(not math.isfinite(v) for v in bbox):
        raise ValueError("La zona de video debe contener cuatro coordenadas finitas.")
    if any(v < 0.0 or v > 1.0 for v in bbox):
        raise ValueError("La zona de video debe estar normalizada entre 0 y 1.")
    x1, y1, x2, y2 = bbox
    if x2 <= x1 or y2 <= y1:
        raise ValueError("La zona de video está invertida o vacía; arrastra de una esquina a la opuesta.")
    if (x2 - x1) < min_lado or (y2 - y1) < min_lado:
        raise ValueError("La zona de video es demasiado pequeña para analizarse de forma fiable.")
    return bbox


def es_raiz_codigo_seleccionada(ruta: str | Path, raiz_proyecto: str | Path) -> bool:
    """Evita procesar por accidente la carpeta del programa (o un padre) como lote.

    R15 (MEDIA-11): además de la igualdad exacta, se bloquea cualquier
    ANCESTRO de la raíz del programa: el lote se escanea recursivamente y un
    padre (p. ej. «Programas Base») incluiría el árbol de V-Matrix completo.
    """
    try:
        objetivo = Path(ruta).resolve()
        programa = Path(raiz_proyecto).resolve()
    except OSError:
        return False
    if objetivo == programa:
        return True
    return programa.is_relative_to(objetivo)
